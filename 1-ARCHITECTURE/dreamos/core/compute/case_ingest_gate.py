"""
L4 自迭代: 案例库自动 ingest
=============================
SACG 循环后自动判断学习价值 → evolution-case-ingest

学习价值评估维度:
    1. 异常度: 与历史案例的偏差 (越异常 → 学习价值越高)
    2. 结果显著性: 盈亏幅度 / 置信度变化
    3. 新颖性: 是否出现新 pattern (指标/信号/形态组合)
    4. 可复现性: 同一条件是否在历史中出现过

用法:
    gate = CaseIngestGate(
        recall_fn=cognitive_recall,
        ingest_fn=evolution_case_ingest,
    )
    report = gate.evaluate_and_ingest(
        cycle_result={...},
        market_context={...},
    )
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 价值评估阈值 ────────────────────────────────────────
NOVELTY_THRESHOLD = 0.6         # 新颖性 ≥ 0.6 → 高价值
SIGNIFICANCE_THRESHOLD = 0.05   # 盈亏幅度 ≥ 5% → 显著
ANOMALY_THRESHOLD = 0.7         # 异常度 ≥ 0.7 → 高价值
REPRODUCIBILITY_PENALTY = 0.3   # 可复现性高 → 降低价值 (非新知识)


class IngestDecision(str, Enum):
    INGEST = "ingest"            # 高学习价值, 入库
    SKIP = "skip"                # 低学习价值, 跳过
    DEFERRED = "deferred"        # 需人工确认


@dataclass
class LearningValue:
    """学习价值评估"""
    novelty: float = 0.0             # 新颖性 0-1
    significance: float = 0.0        # 显著性 0-1
    anomaly: float = 0.0             # 异常度 0-1
    reproducibility: float = 0.0     # 可复现性 0-1
    overall_score: float = 0.0       # 综合评分
    factors: List[str] = field(default_factory=list)  # 评分因子说明

    def to_dict(self) -> Dict[str, Any]:
        return {
            "novelty": round(self.novelty, 3),
            "significance": round(self.significance, 3),
            "anomaly": round(self.anomaly, 3),
            "reproducibility": round(self.reproducibility, 3),
            "overall_score": round(self.overall_score, 3),
            "factors": self.factors,
        }


@dataclass
class IngestReport:
    """案例入库报告"""
    decision: IngestDecision
    value: LearningValue
    ingested: bool = False
    case_id: Optional[str] = None
    reason: str = ""
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "value": self.value.to_dict(),
            "ingested": self.ingested,
            "case_id": self.case_id,
            "reason": self.reason,
            "evaluated_at": self.evaluated_at,
        }


class CaseIngestGate:
    """案例库自动 ingest 门控

    在 SACG 循环后评估学习价值, 决定是否入库

    用法:
        gate = CaseIngestGate(
            recall_fn=cognitive_recall,
            ingest_fn=ingest_case,
        )
        report = gate.evaluate_and_ingest(cycle_result, market_context)
    """

    def __init__(
        self,
        recall_fn: Optional[Callable] = None,
        ingest_fn: Optional[Callable] = None,
        record_fn: Optional[Callable] = None,
    ):
        self._recall_fn = recall_fn
        self._ingest_fn = ingest_fn
        self._record_fn = record_fn

    # ── 价值评估 ─────────────────────────────────────────

    def _assess_novelty(
        self, cycle_result: Dict[str, Any], recalled: List[Dict]
    ) -> tuple:
        """评估新颖性 (与历史案例的差异)"""
        if not recalled:
            return 1.0, ["无历史相似案例 → 全新知识"]

        # 检查方向/信号组合是否在历史中出现过
        direction = cycle_result.get("direction", "")
        signals = cycle_result.get("signals", [])
        signal_set = set()
        if isinstance(signals, list):
            for s in signals:
                if isinstance(s, dict):
                    signal_set.add(s.get("name", ""))
                elif isinstance(s, str):
                    signal_set.add(s)

        # 检查历史中是否有相同方向 + 相同信号组合
        matched_count = 0
        for mem in recalled:
            content = mem.get("content", "")
            if isinstance(content, str) and direction and direction in content:
                matched_count += 1

        novelty = 1.0 - (matched_count / len(recalled)) if recalled else 1.0

        factors = []
        if novelty >= NOVELTY_THRESHOLD:
            factors.append(f"新颖性 {novelty:.2f} ≥ {NOVELTY_THRESHOLD}")
        elif novelty < 0.3:
            factors.append(f"新颖性低 {novelty:.2f} (历史已有 {matched_count} 相似)")

        return novelty, factors

    def _assess_significance(self, cycle_result: Dict[str, Any]) -> tuple:
        """评估结果显著性"""
        pnl = abs(float(cycle_result.get("pnl_pct", 0)))
        confidence = float(cycle_result.get("confidence", 0))

        # 归一化: pnl 5% → 1.0
        sig_pnl = min(pnl / SIGNIFICANCE_THRESHOLD, 1.0) if SIGNIFICANCE_THRESHOLD > 0 else 0.0
        # 置信度直接用
        sig_conf = confidence

        significance = (sig_pnl + sig_conf) / 2

        factors = []
        if pnl >= SIGNIFICANCE_THRESHOLD:
            factors.append(f"盈亏幅度 {pnl:.1%} ≥ {SIGNIFICANCE_THRESHOLD:.0%}")
        if confidence >= 0.8:
            factors.append(f"高置信度 {confidence:.2f}")

        return significance, factors

    def _assess_anomaly(self, cycle_result: Dict[str, Any]) -> tuple:
        """评估异常度"""
        indicators = cycle_result.get("indicators", {})
        if not isinstance(indicators, dict):
            return 0.0, []

        anomaly_score = 0.0
        factors = []

        # RSI 极端值
        rsi = float(indicators.get("rsi14", 50))
        if rsi < 25 or rsi > 75:
            anomaly_score += 0.3
            factors.append(f"RSI 极端值 {rsi:.1f}")

        # 成交量异常
        vol_ratio = float(indicators.get("volume_ratio", 1.0))
        if vol_ratio > 2.0 or vol_ratio < 0.5:
            anomaly_score += 0.3
            factors.append(f"成交量异常 ratio={vol_ratio:.2f}")

        # 价格突变
        price_change = abs(float(indicators.get("price_change_pct", 0)))
        if price_change > 0.03:  # 3%
            anomaly_score += 0.4
            factors.append(f"价格突变 {price_change:.1%}")

        anomaly_score = min(anomaly_score, 1.0)

        return anomaly_score, factors

    def _assess_reproducibility(
        self, cycle_result: Dict[str, Any], recalled: List[Dict]
    ) -> tuple:
        """评估可复现性 (高可复现 → 低新颖 → 降低价值)"""
        if not recalled:
            return 0.0, ["无历史对比"]

        # 简化: 历史相似案例越多 → 可复现性越高
        reproducibility = min(len(recalled) / 10.0, 1.0)

        factors = []
        if reproducibility > 0.7:
            factors.append(f"高可复现性 {reproducibility:.2f} (已有 {len(recalled)} 相似)")

        return reproducibility, factors

    def evaluate_learning_value(
        self,
        cycle_result: Dict[str, Any],
        market_context: Optional[Dict[str, Any]] = None,
    ) -> LearningValue:
        """评估学习价值"""
        # recall 相似历史
        recalled = []
        if self._recall_fn:
            try:
                direction = cycle_result.get("direction", "")
                signals = cycle_result.get("signals", [])
                query = f"{direction} {' '.join(str(s) for s in signals[:3])}"
                result = self._recall_fn(context=query, top_k=10, min_quality="C")
                if isinstance(result, list):
                    recalled = result
                elif isinstance(result, dict) and "memories" in result:
                    recalled = result["memories"]
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[case_ingest] recall 失败: {e}")

        # 4 维评估
        novelty, nov_factors = self._assess_novelty(cycle_result, recalled)
        significance, sig_factors = self._assess_significance(cycle_result)
        anomaly, anom_factors = self._assess_anomaly(cycle_result)
        reproducibility, rep_factors = self._assess_reproducibility(
            cycle_result, recalled
        )

        # 综合评分: 新颖性 + 显著性 + 异常度 - 可复现性惩罚
        overall = (
            novelty * 0.35
            + significance * 0.30
            + anomaly * 0.25
            + (1 - reproducibility) * 0.10
        )

        all_factors = nov_factors + sig_factors + anom_factors + rep_factors

        return LearningValue(
            novelty=novelty,
            significance=significance,
            anomaly=anomaly,
            reproducibility=reproducibility,
            overall_score=overall,
            factors=all_factors,
        )

    # ── 入库决策 ─────────────────────────────────────────

    def _decide_ingest(self, value: LearningValue) -> IngestDecision:
        """决定是否入库"""
        if value.overall_score >= 0.5:
            return IngestDecision.INGEST
        if value.overall_score >= 0.3:
            return IngestDecision.DEFERRED
        return IngestDecision.SKIP

    # ── 主循环 ───────────────────────────────────────────

    def evaluate_and_ingest(
        self,
        cycle_result: Dict[str, Any],
        market_context: Optional[Dict[str, Any]] = None,
    ) -> IngestReport:
        """评估学习价值并决定是否入库

        Args:
            cycle_result: SACG 循环结果, 含 direction/signals/indicators/pnl_pct/confidence
            market_context: 市场上下文 (可选)

        Returns:
            IngestReport
        """
        value = self.evaluate_learning_value(cycle_result, market_context)
        decision = self._decide_ingest(value)

        report = IngestReport(decision=decision, value=value)

        if decision == IngestDecision.INGEST and self._ingest_fn:
            try:
                case_id = self._ingest_fn(
                    cycle_result=cycle_result,
                    market_context=market_context or {},
                    value_score=value.overall_score,
                )
                report.ingested = True
                report.case_id = str(case_id) if case_id else None
                report.reason = f"学习价值 {value.overall_score:.2f} ≥ 0.5, 已入库"
                logger.info(
                    f"[case_ingest] 入库: score={value.overall_score:.2f}, "
                    f"case_id={report.case_id}"
                )
            except Exception as e:  # noqa: BLE001 FAIL-OPEN
                report.ingested = False
                report.reason = f"入库失败: {e}"
                logger.warning(f"[case_ingest] 入库失败: {e}")
        elif decision == IngestDecision.INGEST:
            report.reason = f"学习价值 {value.overall_score:.2f} ≥ 0.5, 但无 ingest_fn"
        elif decision == IngestDecision.DEFERRED:
            report.reason = f"学习价值 {value.overall_score:.2f} 中等, 需人工确认"
        else:
            report.reason = f"学习价值 {value.overall_score:.2f} < 0.3, 跳过"

        # 记录到认知库
        if self._record_fn and decision != IngestDecision.SKIP:
            try:
                self._record_fn(
                    content=(
                        f"[案例入库评估] decision={decision.value}, "
                        f"score={value.overall_score:.2f}, "
                        f"novelty={value.novelty:.2f}, "
                        f"significance={value.significance:.2f}, "
                        f"anomaly={value.anomaly:.2f}, "
                        f"reason={report.reason}"
                    ),
                    quality_level="B",
                    tags="L4自迭代,案例入库,case_ingest",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[case_ingest] 认知库记录失败: {e}")

        return report
