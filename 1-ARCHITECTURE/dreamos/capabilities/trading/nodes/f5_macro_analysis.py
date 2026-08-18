"""
F5 宏观分析节点

基于基本面分析系统的宏观分析能力：
    - 政策评分
    - 美元指数 (DXY)
    - 利率影响
    - 加密友好度
    - 宏观事件
    - 黄金相关性

输入: state.market_data 或 state.inputs["mkt"]
输出: direction / confidence / macro_score / policy_score / dxy / rationale
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


class F5MacroAnalysisNode(BaseNode):
    """F5 宏观分析节点

    基于宏观因素的分析，判断整体环境对加密资产的影响。
    """

    node_id = "F5"
    name = "宏观分析"
    description = "宏观分析（政策评分/DXY/利率/加密友好度/宏观事件/黄金相关性）"
    chain = "F"
    tags = ["macro", "fundamental", "policy", "dxy", "interest_rate"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        scores = []

        # ── 1. 政策评分 ──────────────────────────────────
        policy_score = mkt.get("policy_score", 50)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [40, 60]
        policy_norm = normalize_signed(policy_score, 40, 60)
        if policy_norm > 0.5:
            scores.append(("LONG", 0.20, f"政策偏友好({policy_score:.0f}, z={policy_norm:.2f})，流动性改善"))
        elif policy_norm < -0.5:
            scores.append(("SHORT", 0.20, f"政策偏紧缩({policy_score:.0f}, z={policy_norm:.2f})，流动性收紧"))

        # ── 2. 美元指数 (DXY) ────────────────────────────
        dxy_strength = mkt.get("dxy_strength", 50)
        dxy_change = mkt.get("dxy_change", 0)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [45, 60]（注意：强美元=空头）
        dxy_norm = normalize_signed(dxy_strength, 45, 60)
        if dxy_norm < -0.5:
            scores.append(("LONG", 0.20, f"美元走弱(DXY={dxy_strength:.0f}, z={dxy_norm:.2f})，风险资产利好"))
        elif dxy_norm > 0.5:
            scores.append(("SHORT", 0.20, f"美元走强(DXY={dxy_strength:.0f}, z={dxy_norm:.2f})，风险资产承压"))

        # ── 3. 利率影响 ──────────────────────────────────
        rate_impact = mkt.get("rate_impact", 0)
        if rate_impact < -0.3:
            scores.append(("SHORT", 0.25, f"利率冲击({rate_impact:+.2f})，高利率压制估值"))
        elif rate_impact > 0.1:
            scores.append(("LONG", 0.15, f"利率利好({rate_impact:+.2f})，降息预期"))

        # ── 4. 加密友好度 ────────────────────────────────
        crypto_friendly_score = mkt.get("crypto_friendly_score", 50)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [30, 70]
        cf_norm = normalize_signed(crypto_friendly_score, 30, 70)
        if cf_norm > 0.5:
            scores.append(("LONG", 0.15, f"加密友好度高({crypto_friendly_score:.0f}, z={cf_norm:.2f})"))
        elif cf_norm < -0.5:
            scores.append(("SHORT", 0.15, f"加密友好度低({crypto_friendly_score:.0f}, z={cf_norm:.2f})"))

        # ── 4.1 恐惧贪婪指数（仅当免费数据源可用） ────────
        fear_greed_index = mkt.get("fear_greed_index")
        fgi_norm = 0.0
        if fear_greed_index is not None:
            # 统计标准化：线性归一化到 [-1, 1]，区间 [25, 75]
            fgi_norm = normalize_signed(fear_greed_index, 25, 75)
            if fgi_norm < -0.5:
                scores.append(("LONG", 0.15, f"恐惧贪婪指数={fear_greed_index:.0f}(z={fgi_norm:.2f})，极度恐惧，反向机会"))
            elif fgi_norm > 0.5:
                scores.append(("SHORT", 0.15, f"恐惧贪婪指数={fear_greed_index:.0f}(z={fgi_norm:.2f})，极度贪婪，警惕回调"))

        # ── 5. 宏观事件 ──────────────────────────────────
        upcoming_events = mkt.get("upcoming_events_count", 0)
        event_severity = mkt.get("event_severity", "low")
        if upcoming_events > 3 and event_severity == "high":
            scores.append(("HOLD", 0.20, f"重大事件密集({upcoming_events}件)，不确定性上升"))

        # ── 6. 黄金相关性 ────────────────────────────────
        gold_correlation = mkt.get("gold_correlation", 0)
        if gold_correlation > 0.4:
            scores.append(("LONG", 0.10, f"与黄金相关性上升({gold_correlation:.2f})，避险属性显现"))

        # ── 7. 美股相关性 ────────────────────────────────
        spx_correlation = mkt.get("spx_correlation", 0)
        if spx_correlation > 0.6:
            scores.append(("HOLD", 0.10, f"与美股相关性高({spx_correlation:.2f})，风险联动"))

        # ── 综合计算（统计化聚合） ────────────────────────
        stats = aggregate_signals(scores)
        direction = stats.direction
        confidence = stats.confidence
        # 保持向后兼容：复用 aggregate_signals 计算的得分
        long_score = stats.long_score
        short_score = stats.short_score
        hold_score = stats.hold_score

        macro_score = long_score - short_score

        rationale = stats.rationale[:6]
        rationale.insert(0, f"[F5宏观分析] 宏观得分={macro_score:+.2f}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        # ── 降级检测：无 Tavily 时降低置信度 ──────────
        degraded = mkt.get("_f_chain_degraded", False)
        if degraded:
            confidence *= 0.5
            rationale.append("  ⚠ 基本面数据源降级，置信度已折减")

        # 构建标准化值字典（恐惧贪婪指数仅在数据可用时包含）
        normalized_values = {
            "policy_score": round(policy_norm, 4),
            "dxy_strength": round(dxy_norm, 4),
            "crypto_friendly_score": round(cf_norm, 4),
        }
        if fear_greed_index is not None:
            normalized_values["fear_greed_index"] = round(fgi_norm, 4)

        outputs = {
            "macro_score": round(macro_score, 3),
            "degraded": degraded,
            "policy": {
                "score": policy_score,
            },
            "dxy": {
                "strength": dxy_strength,
                "change": dxy_change,
            },
            "rate_impact": rate_impact,
            "crypto_friendly": crypto_friendly_score,
            "fear_greed_index": fear_greed_index,
            "events": {
                "count": upcoming_events,
                "severity": event_severity,
            },
            "correlations": {
                "gold": gold_correlation,
                "spx": spx_correlation,
            },
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
            "stats": {
                "z_score": round(stats.z_score, 4),
                "percentile": round(stats.percentile, 2),
                "active_signals": stats.active_signals,
                "total_signals": stats.total_signals,
            },
            "normalized_values": normalized_values,
            "rationale": rationale,
        }

        return NodeResult(
            node_id="F5",
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