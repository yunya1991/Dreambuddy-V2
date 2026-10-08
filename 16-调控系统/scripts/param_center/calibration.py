"""任务③: 影子模式参数校准 — 偏差分析 + 校准建议

依赖: shadow_integration.ParamCenterShadowLogger (读偏差记录)
      verifier.BayesianVerifier (验证校准后的参数)
      aggregator.trigger_recompute (重新聚合作为校准锚点)

设计思路：
  1. 影子模式记录"参数中心推荐值 vs 子系统实际值"偏差
  2. 偏差信号统计：
     - 持续正偏差 → 子系统过于保守，参数中心建议可放宽
     - 持续负偏差 → 子系统激进，需要校准向中心收紧
     - 偏差大 + 高波动 → 参数中心聚合不稳定，需要回看窗口延长
  3. 校准建议：偏差均值 + 偏差方差 + 异常值剔除 → 校准后的推荐参数
  4. 用 BayesianVerifier 跑回测验证校准参数不退化

校准触发条件（任一命中即触发）：
  A. 样本数 ≥ 30 条
  B. 平均偏差 ≥ 15%
  C. 偏差标准差 ≥ 10%
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 校准触发阈值
# ============================================================================
MIN_SAMPLE_COUNT = 30       # 最少样本数
DEVIATION_AVG_THRESHOLD = 0.15  # 平均偏差阈值
DEVIATION_STD_THRESHOLD = 0.10  # 偏差标准差阈值


# ============================================================================
# 数据结构
# ============================================================================
@dataclass
class DeviationStats:
    """偏差统计结果"""
    symbol: str
    sample_count: int
    avg_deviation: float = 0.0
    std_deviation: float = 0.0
    max_deviation: float = 0.0
    min_deviation: float = 0.0
    # 推荐值均值（参数中心历史输出）
    avg_recommended: Dict[str, float] = field(default_factory=dict)
    # 实际值均值（子系统历史使用）
    avg_actual: Dict[str, float] = field(default_factory=dict)


@dataclass
class CalibrationProposal:
    """校准建议"""
    symbol: str
    should_calibrate: bool = False
    reason: str = ""
    calibrated_params: Dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    stats: Optional[DeviationStats] = None


# ============================================================================
# CalibrationAnalyzer
# ============================================================================
class CalibrationAnalyzer:
    """影子模式参数校准分析器。

    Args:
        shadow_logger: ParamCenterShadowLogger 实例（None 时用默认单例）
    """

    def __init__(self, shadow_logger=None) -> None:
        if shadow_logger is None:
            try:
                from .shadow_integration import get_shadow_logger
                shadow_logger = get_shadow_logger()
            except Exception:
                shadow_logger = None
        self._shadow = shadow_logger

    # ----------------------------------------------------------------------
    # 对外主接口
    # ----------------------------------------------------------------------
    def analyze_deviation(self, symbol: str, days: int = 30) -> DeviationStats:
        """分析最近 N 天的偏差统计"""
        if self._shadow is None:
            return DeviationStats(symbol=symbol, sample_count=0)

        records = self._shadow.query_deviation_report(symbol, days=days)
        if not records:
            return DeviationStats(symbol=symbol, sample_count=0)

        import json
        deviations = [r.get("deviation_pct", 0) for r in records]
        # 解析 JSON 字段
        rec_params_list = []
        act_params_list = []
        for r in records:
            try:
                rec = json.loads(r.get("param_center_recommended") or "{}")
                act = json.loads(r.get("actual_used") or "{}")
                if rec:
                    rec_params_list.append(rec)
                if act:
                    act_params_list.append(act)
            except Exception:
                continue

        # 各参数均值
        def _avg_params(lst: List[Dict]) -> Dict[str, float]:
            if not lst:
                return {}
            keys = set()
            for d in lst:
                keys.update(d.keys())
            return {
                k: sum(d.get(k, 0) for d in lst) / len(lst)
                for k in keys
                if isinstance(d.get(k), (int, float)) or True
            }

        return DeviationStats(
            symbol=symbol,
            sample_count=len(records),
            avg_deviation=statistics.mean(deviations),
            std_deviation=statistics.pstdev(deviations) if len(deviations) > 1 else 0.0,
            max_deviation=max(deviations),
            min_deviation=min(deviations),
            avg_recommended=_avg_params(rec_params_list),
            avg_actual=_avg_params(act_params_list),
        )

    def propose_calibration(
        self,
        symbol: str,
        days: int = 30,
    ) -> CalibrationProposal:
        """基于影子数据给出校准建议。

        校准公式:
          - 若 avg_deviation ≥ 阈值 → 用 avg_actual + 当前 trigger_recompute 输出加权
          - 若 std_deviation ≥ 阈值 → 标记不稳定，降置信度
          - 若样本 < MIN_SAMPLE_COUNT → 不触发校准，should_calibrate=False
        """
        stats = self.analyze_deviation(symbol, days)

        # 样本不足，不触发校准
        if stats.sample_count < MIN_SAMPLE_COUNT:
            return CalibrationProposal(
                symbol=symbol,
                should_calibrate=False,
                reason=f"样本不足: {stats.sample_count} < {MIN_SAMPLE_COUNT}",
                stats=stats,
            )

        # 判断是否需要校准
        need_calibrate = (
            stats.avg_deviation >= DEVIATION_AVG_THRESHOLD
            or stats.std_deviation >= DEVIATION_STD_THRESHOLD
        )

        if not need_calibrate:
            return CalibrationProposal(
                symbol=symbol,
                should_calibrate=False,
                reason=(
                    f"偏差稳定: avg={stats.avg_deviation:.3f} "
                    f"std={stats.std_deviation:.3f}"
                ),
                stats=stats,
            )

        # 计算校准参数：用 avg_actual 作为基准（子系统实际值更接近实战）
        calibrated = dict(stats.avg_actual)
        # 兜底：硬约束检查
        sl = calibrated.get("sl_floor", 0.03)
        tp = calibrated.get("tp_floor", 0.12)
        atr = calibrated.get("atr_mult", 4.5)
        calibrated["sl_floor"] = max(0.03, min(0.15, sl))
        calibrated["tp_floor"] = max(0.12, min(0.30, tp))
        calibrated["atr_mult"] = max(2.0, min(8.0, atr))
        # RR 比 ≥ 2:1
        if calibrated["tp_floor"] / calibrated["sl_floor"] < 2.0:
            calibrated["tp_floor"] = calibrated["sl_floor"] * 2.0

        # 置信度：偏差越小越高，样本越多越高
        confidence = max(0.3, min(0.9, 1.0 - stats.avg_deviation))

        return CalibrationProposal(
            symbol=symbol,
            should_calibrate=True,
            reason=(
                f"偏差触发: avg={stats.avg_deviation:.3f} "
                f"std={stats.std_deviation:.3f} "
                f"n={stats.sample_count}"
            ),
            calibrated_params=calibrated,
            confidence=confidence,
            stats=stats,
        )

    def calibrate_with_verifier(
        self,
        symbol: str,
        verifier=None,
        days: int = 30,
    ):
        """完整校准流程：偏差分析 → 校准建议 → BayesianVerifier 验证

        Returns:
            (CalibrationProposal, VerificationResult)
        """
        # 延迟导入避免循环依赖
        if verifier is None:
            from .verifier import BayesianVerifier
            verifier = BayesianVerifier()

        # Step 1: 偏差分析 + 校准建议
        proposal = self.propose_calibration(symbol, days)

        if not proposal.should_calibrate:
            # 不需要校准，返回中性 VerificationResult
            from .verifier import VerificationResult
            return proposal, VerificationResult(
                passed=False,
                rollback_reason=f"无需校准: {proposal.reason}",
            )

        # Step 2: 用 BayesianVerifier 跑回测验证
        from .aggregator import ParamProposal
        param_proposal = ParamProposal(
            params=proposal.calibrated_params,
            confidence=proposal.confidence,
        )
        ver_result = verifier.verify_and_upgrade(
            param_proposal, symbol, history_days=days,
        )
        return proposal, ver_result


# ============================================================================
# 便捷函数
# ============================================================================
def run_calibration(symbol: str, days: int = 30):
    """模块级便捷接口：对指定 symbol 跑参数校准流程"""
    analyzer = CalibrationAnalyzer()
    return analyzer.calibrate_with_verifier(symbol, days=days)
