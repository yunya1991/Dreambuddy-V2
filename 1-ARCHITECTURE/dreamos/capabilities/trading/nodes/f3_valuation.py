"""
F3 估值分析节点

基于基本面分析系统的链上估值分析能力：
    - MVRV Z-Score
    - SOPR (Spent Output Profit Ratio)
    - AHR999 指数
    - Mayer Multiple
    - Pi Cycle Top
    - 链上活跃地址

输入: state.market_data 或 state.inputs["mkt"]
输出: direction / confidence / valuation_score / valuation_zone / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult
from dreamos.capabilities.trading.stats_utils import (
    normalize_tanh,
    normalize_signed,
    aggregate_signals,
    z_score,
    percentile_rank,
)


class F3ValuationNode(BaseNode):
    """F3 估值分析节点

    基于链上指标的估值分析，判断市场处于高估/低估/合理区间。
    """

    node_id = "F3"
    name = "估值分析"
    description = "链上估值分析（MVRV/SOPR/AHR999/Mayer/Pi Cycle）"
    chain = "F"
    tags = ["valuation", "fundamental", "onchain", "mvrv", "sopr"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        scores = []

        # ── 1. MVRV Z-Score ──────────────────────────────
        mvrv_z = mkt.get("mvrv_z_score", 0)
        # 已经是 z-score，直接用作为标准化值
        mvrv_norm = mvrv_z
        if mvrv_z < -1:
            scores.append(("LONG", 0.25, f"MVRV Z-Score={mvrv_z:.2f}，低估区域"))
        elif mvrv_z > 2:
            scores.append(("SHORT", 0.25, f"MVRV Z-Score={mvrv_z:.2f}，过热区域"))
        elif mvrv_z > 1:
            scores.append(("SHORT", 0.10, f"MVRV Z-Score={mvrv_z:.2f}，偏高"))

        # ── 2. SOPR ──────────────────────────────────────
        sopr = mkt.get("sopr", 1)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [0.95, 1.05]
        sopr_norm = normalize_signed(sopr, 0.95, 1.05)
        if sopr_norm < -0.5:
            scores.append(("LONG", 0.20, f"SOPR={sopr:.4f} (z={sopr_norm:.2f})，亏损区，洗盘接近尾声"))
        elif sopr_norm > 0.5:
            scores.append(("SHORT", 0.15, f"SOPR={sopr:.4f} (z={sopr_norm:.2f})，盈利区，警惕获利回吐"))

        # ── 3. AHR999 ────────────────────────────────────
        ahr999 = mkt.get("ahr999", 0.5)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [0.45, 1.2]
        ahr999_norm = normalize_signed(ahr999, 0.45, 1.2)
        if ahr999_norm < -0.5:
            scores.append(("LONG", 0.25, f"AHR999={ahr999:.3f} (z={ahr999_norm:.2f})，定投黄金区"))
        elif ahr999_norm > 0.5:
            scores.append(("SHORT", 0.20, f"AHR999={ahr999:.3f} (z={ahr999_norm:.2f})，风险区"))

        # ── 4. Mayer Multiple ────────────────────────────
        mayer = mkt.get("mayer_multiple", 1)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [0.8, 2.6]
        mayer_norm = normalize_signed(mayer, 0.8, 2.6)
        if mayer_norm < -0.5:
            scores.append(("LONG", 0.20, f"Mayer={mayer:.3f} (z={mayer_norm:.2f})，过冷区"))
        elif mayer_norm > 0.5:
            scores.append(("SHORT", 0.20, f"Mayer={mayer:.3f} (z={mayer_norm:.2f})，过热区"))

        # ── 5. Pi Cycle Top ──────────────────────────────
        pi_cycle = mkt.get("pi_cycle_top", 0)
        if pi_cycle > 0.9:
            scores.append(("SHORT", 0.25, f"Pi Cycle={pi_cycle:.2f}，顶部预警"))

        # ── 6. 链上活跃地址 ──────────────────────────────
        active_addresses = mkt.get("active_addresses", 0)
        address_change = mkt.get("active_addresses_change", 0)
        if address_change > 20:
            scores.append(("LONG", 0.15, f"活跃地址增加({address_change:.1f}%)，需求提升"))
        elif address_change < -20:
            scores.append(("SHORT", 0.15, f"活跃地址减少({address_change:.1f}%)，需求下降"))

        # ── 综合计算（统计化聚合） ────────────────────────
        stats = aggregate_signals(scores)
        direction = stats.direction
        confidence = stats.confidence
        # 保持向后兼容：复用 aggregate_signals 计算的得分
        long_score = stats.long_score
        short_score = stats.short_score

        # 判断估值区间
        valuation_score = long_score - short_score
        if valuation_score > 0.5:
            valuation_zone = "undervalued"
        elif valuation_score < -0.5:
            valuation_zone = "overvalued"
        else:
            valuation_zone = "fair_value"

        rationale = stats.rationale[:6]
        rationale.insert(0, f"[F3估值] 估值得分={valuation_score:+.2f} | 区间={valuation_zone}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        # ── 降级检测：无 Tavily 时降低置信度 ──────────
        degraded = mkt.get("_f_chain_degraded", False)
        if degraded:
            confidence *= 0.5
            rationale.append("  ⚠ 基本面数据源降级，置信度已折减")

        outputs = {
            "valuation_score": round(valuation_score, 3),
            "valuation_zone": valuation_zone,
            "mvrv_z_score": mvrv_z,
            "sopr": sopr,
            "ahr999": ahr999,
            "mayer_multiple": mayer,
            "pi_cycle_top": pi_cycle,
            "active_addresses": {
                "count": active_addresses,
                "change": address_change,
            },
            "degraded": degraded,
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3)},
            "stats": {
                "z_score": round(stats.z_score, 4),
                "percentile": round(stats.percentile, 2),
                "active_signals": stats.active_signals,
                "total_signals": stats.total_signals,
            },
            "normalized_values": {
                "mvrv_z_score": round(mvrv_norm, 4),
                "sopr": round(sopr_norm, 4),
                "ahr999": round(ahr999_norm, 4),
                "mayer_multiple": round(mayer_norm, 4),
            },
            "rationale": rationale,
        }

        return NodeResult(
            node_id="F3",
            confidence=round(confidence, 3),
            direction=direction,
            outputs=outputs,
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}