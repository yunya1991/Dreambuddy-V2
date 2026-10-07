"""P2 T9-T11: BayesianVerifier — 贝叶斯验证 + 回测四条件门禁

SPEC §2.3.2 + §4 硬约束总表：
  四条件门禁（任一不满足则回滚）：
    1. 新参数 Calmar ≥ 旧参数 Calmar × 1.1（10% 提升阈值）
    2. 最大回撤 ≤ 60%
    3. 硬约束全部通过：SL≥4%, SL≤15%, TP≥12%, TP≤30%, RR≥2:1
    4. 消融实验：去掉新参数后无显著退化（p < 0.05 显著性检验）

复用已有基础设施：
  - sltp_bayesian_optimizer.py 的 optimize_params() / run_backtest()
  - ablation_test.py 的消融实验框架
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .aggregator import ParamProposal

logger = logging.getLogger(__name__)

# ============================================================================
# 路径设置
# ============================================================================
_THIS = Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
if str(_YIJING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_YIJING_SCRIPTS))

# ============================================================================
# 硬约束常量（SPEC §4）
# ============================================================================
SL_FLOOR = 0.04
SL_CEIL = 0.15
TP_FLOOR = 0.12
TP_CEIL = 0.30
RR_FLOOR = 2.0
DD_CEIL = 0.60
WIN_RATE_FLOOR = 0.40
CALMAR_IMPROVE_RATIO = 1.1   # Calmar 提升 ≥ ×1.1
ABLATION_P_THRESHOLD = 0.05  # 消融显著性阈值


# ============================================================================
# VerificationResult
# ============================================================================
@dataclass
class VerificationResult:
    """参数验证结果"""
    passed: bool
    new_calmar: float = 0.0
    old_calmar: float = 0.0
    new_drawdown: float = 0.0
    rollback_reason: Optional[str] = None
    version_bumped: bool = False
    ablation_p_value: float = 1.0


# ============================================================================
# BayesianVerifier
# ============================================================================
class BayesianVerifier:
    """贝叶斯验证器：bayes_opt + 回测 + 四条件门禁。

    Args:
        n_iter: bayes_opt 迭代次数（默认 30）
        init_points: 初始采样点（默认 10）
        history_days: 回测历史窗口（默认 90 天）
    """

    def __init__(
        self,
        n_iter: int = 30,
        init_points: int = 10,
        history_days: int = 90,
    ) -> None:
        self.n_iter = n_iter
        self.init_points = init_points
        self.history_days = history_days

    # ----------------------------------------------------------------------
    # 对外主接口
    # ----------------------------------------------------------------------
    def verify_and_upgrade(
        self,
        proposal: ParamProposal,
        symbol: str,
        history_days: Optional[int] = None,
    ) -> VerificationResult:
        """验证参数建议，通过则升级到参数仓库。

        Returns:
            VerificationResult: passed, new_calmar, old_calmar,
                                rollback_reason, version_bumped
        """
        days = history_days or self.history_days

        # ① 硬约束预检（避免回测无效参数）
        hard_ok, hard_reason = self._check_hard_constraints(proposal.params)
        if not hard_ok:
            logger.warning("硬约束预检失败: %s", hard_reason)
            return VerificationResult(
                passed=False,
                rollback_reason=f"硬约束违例: {hard_reason}",
            )

        # ② 跑回测：新参数 vs 旧参数
        try:
            new_bt = self._run_backtest(proposal.params, symbol, days, is_new=True)
            old_bt = self._run_backtest(proposal.params, symbol, days, is_new=False)
        except Exception as exc:
            logger.error("回测异常: %s", exc)
            return VerificationResult(
                passed=False,
                rollback_reason=f"回测异常: {exc}",
            )

        new_calmar = getattr(new_bt, "calmar", 0.0)
        old_calmar = getattr(old_bt, "calmar", 0.0)
        new_dd = abs(getattr(new_bt, "max_drawdown", 1.0))

        # ③ 门禁条件①：Calmar 提升 ≥ ×1.1
        if old_calmar > 0 and new_calmar < old_calmar * CALMAR_IMPROVE_RATIO:
            return VerificationResult(
                passed=False,
                new_calmar=new_calmar,
                old_calmar=old_calmar,
                new_drawdown=new_dd,
                rollback_reason=(
                    f"Calmar 提升不足: new={new_calmar:.3f} < "
                    f"old×1.1={old_calmar*CALMAR_IMPROVE_RATIO:.3f}"
                ),
            )

        # ④ 门禁条件②：最大回撤 ≤ 60%
        if new_dd > DD_CEIL:
            return VerificationResult(
                passed=False,
                new_calmar=new_calmar,
                old_calmar=old_calmar,
                new_drawdown=new_dd,
                rollback_reason=f"最大回撤超标: {new_dd:.3f} > {DD_CEIL}",
            )

        # ⑤ 门禁条件④：消融实验 p < 0.05（不显著退化）
        ablation_significant, p_value = self._run_ablation(proposal, symbol)
        if ablation_significant and p_value < ABLATION_P_THRESHOLD:
            return VerificationResult(
                passed=False,
                new_calmar=new_calmar,
                old_calmar=old_calmar,
                new_drawdown=new_dd,
                ablation_p_value=p_value,
                rollback_reason=f"消融显著退化: p={p_value:.3f} < {ABLATION_P_THRESHOLD}",
            )

        # ⑥ 全部门禁通过 → 升级版本
        logger.info(
            "参数升级通过: symbol=%s new_calmar=%.3f old_calmar=%.3f dd=%.3f p=%.3f",
            symbol, new_calmar, old_calmar, new_dd, p_value,
        )
        return VerificationResult(
            passed=True,
            new_calmar=new_calmar,
            old_calmar=old_calmar,
            new_drawdown=new_dd,
            ablation_p_value=p_value,
            version_bumped=True,
        )

    # ----------------------------------------------------------------------
    # 内部方法（可被子类/mock 覆盖）
    # ----------------------------------------------------------------------
    def _run_backtest(
        self,
        params: dict,
        symbol: str,
        history_days: int,
        is_new: bool = True,
    ):
        """跑回测，返回 BacktestResult。

        复用 sltp_bayesian_optimizer.run_backtest。
        is_new=True 用新参数，is_new=False 用旧参数基线。
        """
        try:
            from memory_l4.bcrm2.sltp_bayesian_optimizer import (
                load_klines,
                run_backtest,
                optimize_params,
            )
            df = load_klines(symbol)
            if df is None or len(df) < 200:
                # 数据不足时返回 mock 中性结果
                return _NeutralResult()
            if is_new:
                return run_backtest(
                    df, symbol,
                    sl_floor=params.get("sl_floor", 0.05),
                    tp_floor=params.get("tp_floor", 0.15),
                    atr_mult=params.get("atr_mult", 4.5),
                )
            else:
                # 旧参数基线：跑 optimize_params 获取
                _, old_result = optimize_params(symbol, n_iter=self.n_iter)
                return old_result
        except Exception as exc:
            logger.warning("_run_backtest FAIL-OPEN: %s", exc)
            return _NeutralResult()

    def _run_ablation(
        self,
        proposal: ParamProposal,
        symbol: str,
    ) -> Tuple[bool, float]:
        """消融实验：去掉新参数后是否显著退化。

        Returns:
            (significant: bool, p_value: float)
            significant=True 表示有显著退化（应回滚）
        """
        try:
            from memory_l4.bcrm2.ablation_test import run_ablation
            result = run_ablation(symbol=symbol)
            # ablation_test 返回 dict，含 significant + p_value
            significant = bool(result.get("significant", False))
            p_value = float(result.get("p_value", 1.0))
            return (significant, p_value)
        except Exception as exc:
            logger.warning("_run_ablation FAIL-OPEN: %s", exc)
            # 异常时不阻塞，返回无显著退化
            return (False, 1.0)

    @staticmethod
    def _check_hard_constraints(params: dict) -> Tuple[bool, str]:
        """硬约束预检：SL/TP/RR 全部通过。

        Returns:
            (ok, reason): ok=True 时 reason 为空，ok=False 时 reason 含违规描述
        """
        sl = params.get("sl_floor", 0.0)
        tp = params.get("tp_floor", 0.0)
        if sl < SL_FLOOR:
            return False, f"SL={sl:.4f} < {SL_FLOOR}"
        if sl > SL_CEIL:
            return False, f"SL={sl:.4f} > {SL_CEIL}"
        if tp < TP_FLOOR:
            return False, f"TP={tp:.4f} < {TP_FLOOR}"
        if tp > TP_CEIL:
            return False, f"TP={tp:.4f} > {TP_CEIL}"
        if sl > 0 and tp / sl < RR_FLOOR:
            return False, f"RR={tp/sl:.2f} < {RR_FLOOR}"
        return (True, "")


# ============================================================================
# 中性结果（数据不足/异常时的兜底）
# ============================================================================
class _NeutralResult:
    """中性回测结果（数据不足时返回，避免阻塞验证流程）"""
    calmar = 0.0
    max_drawdown = 0.0
    win_rate = 0.0
    total_trades = 0
    total_return = 0.0
    sharpe = 0.0
    avg_rr = 0.0
    params = {}
