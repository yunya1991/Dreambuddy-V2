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
        if whale_accumulation > 60:
            scores.append(("LONG", 0.25, f"鲸鱼积累({whale_accumulation:.0f})，大户吸筹"))
        elif whale_accumulation < 40:
            scores.append(("SHORT", 0.20, f"鲸鱼抛售({whale_accumulation:.0f})，大户出货"))
        if whale_balance_change > 5:
            scores.append(("LONG", 0.15, f"鲸鱼余额增加({whale_balance_change:.1f}%)"))

        # ── 2. 矿工持仓变化 ──────────────────────────────
        miner_position = mkt.get("miner_position", 50)
        miner_balance_change = mkt.get("miner_balance_change", 0)
        if miner_position < 40:
            scores.append(("LONG", 0.20, f"矿工囤币({miner_position:.0f})，供给减少"))
        elif miner_position > 70:
            scores.append(("SHORT", 0.20, f"矿工出货({miner_position:.0f})，抛压增加"))

        # ── 3. Gas 费用分析 ──────────────────────────────
        gas_price = mkt.get("gas_price_gwei", 30)
        gas_change = mkt.get("gas_price_change", 0)
        if gas_price > 80:
            scores.append(("LONG", 0.15, f"Gas高涨({gas_price:.0f}Gwei)，链上活动活跃"))
        elif gas_price < 10:
            scores.append(("HOLD", 0.10, f"Gas低迷({gas_price:.0f}Gwei)，链上活动冷清"))

        # ── 4. 链上交易量 ────────────────────────────────
        chain_volume = mkt.get("chain_volume", 0)
        chain_volume_change = mkt.get("chain_volume_change", 0)
        if chain_volume_change > 20:
            scores.append(("LONG", 0.15, f"链上交易量增加({chain_volume_change:.1f}%)"))
        elif chain_volume_change < -20:
            scores.append(("SHORT", 0.15, f"链上交易量减少({chain_volume_change:.1f}%)"))

        # ── 5. 交易所余额变化 ────────────────────────────
        exchange_balance_change = mkt.get("exchange_balance_change", 0)
        if exchange_balance_change < -5:
            scores.append(("LONG", 0.20, f"交易所余额减少({exchange_balance_change:.1f}%)，场外积累"))
        elif exchange_balance_change > 5:
            scores.append(("SHORT", 0.20, f"交易所余额增加({exchange_balance_change:.1f}%)，抛压增加"))

        # ── 6. 巨鲸转账 ──────────────────────────────────
        whale_transfers = mkt.get("whale_transfers", 0)
        whale_transfer_net = mkt.get("whale_transfer_net", 0)
        if whale_transfers > 10 and whale_transfer_net < 0:
            scores.append(("LONG", 0.15, f"巨鲸转出({whale_transfers}笔)，场外积累"))

        # ── 综合计算 ────────────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        hold_score = sum(w for d, w, _ in scores if d == "HOLD")
        total = long_score + short_score + hold_score

        if total == 0:
            direction = "HOLD"
            confidence = 0.3
        elif hold_score > long_score and hold_score > short_score:
            direction = "HOLD"
            confidence = hold_score / max(total, 0.01)
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(total, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(total, 0.01)

        onchain_score = long_score - short_score

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[F4链上数据] 链上得分={onchain_score:+.2f}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        outputs = {
            "onchain_score": round(onchain_score, 3),
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