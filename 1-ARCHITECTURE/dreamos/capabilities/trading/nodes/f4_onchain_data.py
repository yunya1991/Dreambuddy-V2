"""
F4 链上数据分析节点

基于基本面分析系统的链上数据能力：
    - 鲸鱼持仓变化
    - 矿工持仓变化
    - Gas 费用
    - 链上交易量
    - 交易所余额变化
    - 巨鲸转账

输入: state.market_data 或 state.inputs["mkt"]
输出: direction / confidence / onchain_score / whale_activity / miner_position / rationale
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


class F4OnchainDataNode(BaseNode):
    """F4 链上数据分析节点

    基于链上数据的深度分析，捕捉大户动向和市场活跃度。
    """

    node_id = "F4"
    name = "链上数据"
    description = "链上数据分析（鲸鱼/矿工/Gas/链上交易量/交易所余额）"
    chain = "F"
    tags = ["onchain", "fundamental", "whale", "miner", "gas"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        scores = []

        # ── 1. 鲸鱼持仓变化 ──────────────────────────────
        whale_accumulation = mkt.get("whale_accumulation_score", 50)
        whale_balance_change = mkt.get("whale_balance_change", 0)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [40, 60]
        whale_norm = normalize_signed(whale_accumulation, 40, 60)
        if whale_norm > 0.5:
            scores.append(("LONG", 0.25, f"鲸鱼积累({whale_accumulation:.0f}, z={whale_norm:.2f})，大户吸筹"))
        elif whale_norm < -0.5:
            scores.append(("SHORT", 0.20, f"鲸鱼抛售({whale_accumulation:.0f}, z={whale_norm:.2f})，大户出货"))
        if whale_balance_change > 5:
            scores.append(("LONG", 0.15, f"鲸鱼余额增加({whale_balance_change:.1f}%)"))

        # ── 2. 矿工持仓变化 ──────────────────────────────
        miner_position = mkt.get("miner_position", 50)
        miner_balance_change = mkt.get("miner_balance_change", 0)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [40, 70]（注意：高分=抛压）
        miner_norm = normalize_signed(miner_position, 40, 70)
        if miner_norm < -0.5:
            scores.append(("LONG", 0.20, f"矿工囤币({miner_position:.0f}, z={miner_norm:.2f})，供给减少"))
        elif miner_norm > 0.5:
            scores.append(("SHORT", 0.20, f"矿工出货({miner_position:.0f}, z={miner_norm:.2f})，抛压增加"))

        # ── 3. Gas 费用分析 ──────────────────────────────
        gas_price = mkt.get("gas_price_gwei", 30)
        gas_change = mkt.get("gas_price_change", 0)
        # 统计标准化：线性归一化到 [-1, 1]，区间 [10, 80]
        gas_norm = normalize_signed(gas_price, 10, 80)
        if gas_norm > 0.5:
            scores.append(("LONG", 0.15, f"Gas高涨({gas_price:.0f}Gwei, z={gas_norm:.2f})，链上活动活跃"))
        elif gas_norm < -0.5:
            scores.append(("HOLD", 0.10, f"Gas低迷({gas_price:.0f}Gwei, z={gas_norm:.2f})，链上活动冷清"))

        # ── 4. 链上交易量 ────────────────────────────────
        chain_volume = mkt.get("chain_volume", 0)
        chain_volume_change = mkt.get("chain_volume_change", 0)
        if chain_volume_change > 20:
            scores.append(("LONG", 0.15, f"链上交易量增加({chain_volume_change:.1f}%)"))
        elif chain_volume_change < -20:
            scores.append(("SHORT", 0.15, f"链上交易量减少({chain_volume_change:.1f}%)"))

        # ── 5. 交易所余额变化 ────────────────────────────
        exchange_balance_change = mkt.get("exchange_balance_change", 0)
        # 统计标准化：tanh 归一化，scale=5（单位百分比）
        ebc_norm = normalize_tanh(exchange_balance_change, scale=5)
        if ebc_norm < -0.5:
            scores.append(("LONG", 0.20, f"交易所余额减少({exchange_balance_change:.1f}%, z={ebc_norm:.2f})，场外积累"))
        elif ebc_norm > 0.5:
            scores.append(("SHORT", 0.20, f"交易所余额增加({exchange_balance_change:.1f}%, z={ebc_norm:.2f})，抛压增加"))

        # ── 6. 巨鲸转账 ──────────────────────────────────
        whale_transfers = mkt.get("whale_transfers", 0)
        whale_transfer_net = mkt.get("whale_transfer_net", 0)
        if whale_transfers > 10 and whale_transfer_net < 0:
            scores.append(("LONG", 0.15, f"巨鲸转出({whale_transfers}笔)，场外积累"))

        # ── 综合计算（统计化聚合） ────────────────────────
        stats = aggregate_signals(scores)
        direction = stats.direction
        confidence = stats.confidence
        # 保持向后兼容：复用 aggregate_signals 计算的得分
        long_score = stats.long_score
        short_score = stats.short_score
        hold_score = stats.hold_score

        onchain_score = long_score - short_score

        rationale = stats.rationale[:6]
        rationale.insert(0, f"[F4链上数据] 链上得分={onchain_score:+.2f}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        # ── 降级检测：无 Tavily 时降低置信度 ──────────
        degraded = mkt.get("_f_chain_degraded", False)
        if degraded:
            confidence *= 0.5
            rationale.append("  ⚠ 基本面数据源降级，置信度已折减")

        outputs = {
            "onchain_score": round(onchain_score, 3),
            "degraded": degraded,
            "whale": {
                "accumulation_score": whale_accumulation,
                "balance_change": whale_balance_change,
                "transfers": whale_transfers,
                "transfer_net": whale_transfer_net,
            },
            "miner": {
                "position": miner_position,
                "balance_change": miner_balance_change,
            },
            "gas": {
                "price_gwei": gas_price,
                "change": gas_change,
            },
            "chain_volume": {
                "value": chain_volume,
                "change": chain_volume_change,
            },
            "exchange_balance_change": exchange_balance_change,
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
            "stats": {
                "z_score": round(stats.z_score, 4),
                "percentile": round(stats.percentile, 2),
                "active_signals": stats.active_signals,
                "total_signals": stats.total_signals,
            },
            "normalized_values": {
                "whale_accumulation_score": round(whale_norm, 4),
                "miner_position": round(miner_norm, 4),
                "gas_price_gwei": round(gas_norm, 4),
                "exchange_balance_change": round(ebc_norm, 4),
            },
            "rationale": rationale,
        }

        return NodeResult(
            node_id="F4",
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