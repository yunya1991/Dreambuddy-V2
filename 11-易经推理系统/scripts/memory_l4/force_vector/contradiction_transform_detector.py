"""矛盾转化检测器 —— 6 类转化条件监控。

纯 Python 实现。所有路径 FAIL-OPEN（异常返回中性默认值，transforming=False）。
对应 Spec §三-A Step 3-A-2 ContradictionTransform。

6 类转化条件：
  1. elasticity_decay         弹性衰减（elasticity_beta.decay_signal，β_ratio<0.5持续3天）
  2. elasticity_amplification 弹性放大（elasticity_beta.amplification_signal，β_ratio>2.0持续3天）
  3. dominant_shift           维度主导切换（rank_shift，7天内top-1特征切换≥2次）
  4. resonance_break          共振破裂（resonance_break，sign_alignment降幅≥0.4）
  5. cbr_divergence           CBR背离（cbr_divergence，同类事件方向相反）
  6. data_quality_warning     数据质量预警（s3_pass_rate<0.7 持续3天）

置信度 = 触发条件数 / 6
S4辅助：crr>0.3或mr<0.5时，已触发条件置信度权重 ×1.2（不增加触发数，封顶1.0）
transforming = 触发条件数>=2 或 data_quality_warning触发 或 (S4佐证 且 触发条件数>=1)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from force_vector.models import ContradictionTransform, ElasticityBeta

# ============================================================
# 注入「9-基本面分析」到 sys.path（S3/S4 engines.* 导入前置）
#   · 定位：本文件（.../memory_l4/force_vector/contradiction_transform_detector.py）
#     上溯 5 层到项目根（dreambuddy-v2），再拼「9-基本面分析」子目录
#     （比 five_domain_feature_computer.py 多 1 层，因本文件在 force_vector/ 子目录下）
#   · Fail-Open：目录不存在或已在 sys.path 中 → 静默跳过
# ============================================================
try:  # noqa: E402
    _FUND_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "9-基本面分析"
    if _FUND_DIR.is_dir() and str(_FUND_DIR) not in sys.path:
        sys.path.insert(0, str(_FUND_DIR))
except Exception:
    pass


class ContradictionTransformDetector:
    """矛盾转化检测器（6 类转化条件监控）。

    检测弹性衰减/放大、维度主导切换、共振破裂、CBR背离、S3数据质量预警，
    输出 ContradictionTransform。所有异常路径 FAIL-OPEN。
    """

    # 数据质量预警阈值
    _S3_LOW_THRESHOLD = 0.7        # pass_rate < 0.7 → 低质量
    _S3_LOW_PERSIST_DAYS = 3      # 持续 3 天 → 触发预警
    _DATA_QUALITY_FACTOR = 0.7     # 预警触发时的降级因子
    _NEUTRAL_DQF = 1.0             # 正常数据质量因子

    # S4 辅助佐证阈值
    _S4_CRR_THRESHOLD = 0.3        # crr > 0.3 → S4佐证
    _S4_MR_THRESHOLD = 0.5         # mr < 0.5 → S4佐证
    _S4_CONFIDENCE_BOOST = 1.2     # 置信度放大系数
    _CONFIDENCE_CAP = 1.0          # 置信度封顶

    _TOTAL_CONDITIONS = 6          # 转化条件总数

    # S3 / S4 FAIL-OPEN 中性默认值
    _S3_NEUTRAL_RATE = 0.8
    _S4_NEUTRAL_CRR = 0.0
    _S4_NEUTRAL_MR = 1.0

    def detect(self, elasticity_beta: ElasticityBeta,
               rank_shift: bool = False,
               resonance_break: bool = False,
               cbr_divergence: bool = False,
               s3_pass_rate: float = 1.0,
               s3_low_days: int = 0,
               s4_crr: float = 0.0,
               s4_mr: float = 1.0) -> ContradictionTransform:
        """6 类转化条件监控。

        elasticity_beta 为 None 时其两信号视为 False（FAIL-OPEN 不崩）。
        """
        try:
            # === 6 类条件检测 ===
            # 条件1/2：弹性衰减/放大（getattr 兼容 elasticity_beta=None）
            decay_sig = bool(getattr(elasticity_beta, "decay_signal", False))
            ampl_sig = bool(getattr(elasticity_beta, "amplification_signal", False))
            # 条件3：维度主导切换
            rank_shift = bool(rank_shift)
            # 条件4：共振破裂
            resonance_break = bool(resonance_break)
            # 条件5：CBR背离
            cbr_divergence = bool(cbr_divergence)
            # 条件6：数据质量预警（pass_rate<0.7 且 持续>=3天）
            data_quality_warning = (
                float(s3_pass_rate) < self._S3_LOW_THRESHOLD
                and int(s3_low_days) >= self._S3_LOW_PERSIST_DAYS
            )

            # 按条件编号顺序构建触发列表（顺序决定 transform_type 选取）
            trigger_conditions: List[str] = []
            monitoring_points: List[str] = []
            if decay_sig:
                trigger_conditions.append("elasticity_decay")
                monitoring_points.append("弹性衰减信号触发（β_ratio<0.5持续3天）")
            if ampl_sig:
                trigger_conditions.append("elasticity_amplification")
                monitoring_points.append("弹性放大信号触发（β_ratio>2.0持续3天）")
            if rank_shift:
                trigger_conditions.append("dominant_shift")
                monitoring_points.append("维度主导切换（7天内top-1特征切换≥2次）")
            if resonance_break:
                trigger_conditions.append("resonance_break")
                monitoring_points.append("共振破裂（sign_alignment降幅≥0.4）")
            if cbr_divergence:
                trigger_conditions.append("cbr_divergence")
                monitoring_points.append("CBR背离（同类事件方向相反）")
            if data_quality_warning:
                trigger_conditions.append("data_quality_warning")
                monitoring_points.append("S3数据质量预警（pass_rate<0.7持续3天）")

            trigger_count = len(trigger_conditions)

            # === 置信度 = 触发条件数 / 6 ===
            confidence = trigger_count / self._TOTAL_CONDITIONS

            # === S4 辅助佐证：crr>0.3 或 mr<0.5 → 已触发条件置信度权重 ×1.2 ===
            s4_aux = (
                float(s4_crr) > self._S4_CRR_THRESHOLD
                or float(s4_mr) < self._S4_MR_THRESHOLD
            )
            if s4_aux and trigger_count > 0:
                # 不增加触发数，仅放大置信度，封顶 1.0
                confidence = min(
                    self._CONFIDENCE_CAP,
                    confidence * self._S4_CONFIDENCE_BOOST,
                )

            # === transforming 判定 ===
            # 触发条件数>=2 或 数据质量预警触发 或 (S4佐证 且 至少1条件已触发)
            transforming = bool(
                trigger_count >= 2
                or data_quality_warning
                or (s4_aux and trigger_count >= 1)
            )

            # === transform_type 选取：取首个触发条件，无则 'none' ===
            transform_type = trigger_conditions[0] if trigger_conditions else "none"

            # === data_quality_factor：预警触发→0.7，否则 1.0 ===
            data_quality_factor = (
                self._DATA_QUALITY_FACTOR if data_quality_warning
                else self._NEUTRAL_DQF
            )

            return ContradictionTransform(
                transforming=transforming,
                transform_type=transform_type,
                trigger_conditions=trigger_conditions,
                confidence=float(confidence),
                monitoring_points=monitoring_points,
                data_quality_factor=float(data_quality_factor),
            )
        except Exception:
            # FAIL-OPEN：异常时全中性，transforming=False
            return ContradictionTransform(
                transforming=False,
                transform_type="none",
                trigger_conditions=[],
                confidence=0.0,
                monitoring_points=[],
                data_quality_factor=self._NEUTRAL_DQF,
            )

    def fetch_s3_pass_rate(self, news_list: list) -> float:
        """调用 S3 news_contract_validator 获取 pass_rate。

        异常时返回 0.8（中性 FAIL-OPEN）。
        """
        try:
            from engines.news_contract_validator import validate_batch  # type: ignore
            result = validate_batch(news_list)
            if isinstance(result, dict):
                rate = result.get("pass_rate", self._S3_NEUTRAL_RATE)
                return float(rate)
            return self._S3_NEUTRAL_RATE
        except Exception:
            return self._S3_NEUTRAL_RATE

    def fetch_s4_crr_mr(self, news_list: list) -> tuple:
        """调用 S4 event_mapping_engine 统计 crr/mr。

        crr（冲突率）= 声明 event_type 与映射结果不一致的比例（映射非 unknown 才计）
        mr （一致性）= 出现最多的映射类别占比
        返回 (crr, mr)，异常时返回 (0.0, 1.0)。
        """
        try:
            if not isinstance(news_list, list):
                return (self._S4_NEUTRAL_CRR, self._S4_NEUTRAL_MR)

            from collections import Counter
            from engines.event_mapping_engine import map_event_type  # type: ignore

            total = len(news_list)
            if total == 0:
                return (self._S4_NEUTRAL_CRR, self._S4_NEUTRAL_MR)

            etypes: List[str] = []
            mismatches = 0
            for n in news_list:
                if not isinstance(n, dict):
                    continue
                title = str(n.get("title") or "")
                body = str(n.get("content") or "")
                topic = str(n.get("event_type") or "")
                category = str(n.get("category") or "")
                mapped = map_event_type(
                    title=title, body=body, topic=topic, category=category,
                )
                etypes.append(mapped)
                declared = str(n.get("event_type") or "")
                # 声明非空 且 映射与声明不一致 且 映射非 unknown → 计入冲突
                if declared and mapped != declared and mapped != "unknown":
                    mismatches += 1

            t_total = max(1, total)
            crr = float(mismatches) / float(t_total)
            top_c = Counter(etypes).most_common(1)[0][1] if etypes else 0
            mr = float(top_c) / float(t_total)
            return (crr, mr)
        except Exception:
            return (self._S4_NEUTRAL_CRR, self._S4_NEUTRAL_MR)
