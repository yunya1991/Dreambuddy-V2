"""
C_MARTIN_V15 — v15 经典马丁策略节点

PROP-20260810-CMARTIN-NODE 方案A（2026-08-10 用户批准）：
从基线锚点 6-TRADING/baselines/v15-six-trading-20260601/backtest_strategy.py
实现 C 链节点，恢复 NEUTRAL_* 场景 → v15 基线策略的路由。

V9 红线（不可修改基线，本节点逐字复现基线 run_screen2 L880-898 的仓位数学）：
    1. 加仓间隔: 8% × vol_mult 复利（最多 3 次等额加仓）
    2. 止盈: 均价 + 4% × vol_mult 一次全仓止盈
    3. 无固定止损
    4. 优化只允许叠加，不允许替换

vol_mult 静态表（基线 _STATIC_REGIME_VOL_MULT，L254-258）：
    BTC=1.00 / ETH=1.50 / SOL=1.75（其余默认 1.0）

方向判定为基线 Screen1 语义在节点上下文（state.market 指标）下的忠实适配：
    EMA 排列 + 价格与 EMA200 关系（MA200 牛熊分界）。
Screen2 评分保留基线可用维度（趋势一致性/RSI），MACD/量能维度在节点
上下文无数据时按基线缺省语义跳过（中性）。

置信度遵循 P0-5 修复：纯代码节点输出 clamp 至 [0.3, 0.95]，
避免 Reflector 对确定性节点发起无意义 REDO。

输入: state.market / state.market_data / state.intent["mkt"]
输出: direction / confidence / outputs.martin_plan
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult

# ── 基线常量（逐字摘自 v15-six-trading-20260601/backtest_strategy.py）────
_V9_ADDON_GAP_PCT = 8.0      # V9: BTC 加仓间隔基准 8%（×vol_mult）
_V9_TP_PCT = 4.0             # V9: BTC 止盈基准 4%（×vol_mult）
_V9_MAX_ADDONS = 3           # V9: 最多 3 次等额加仓
_V9_NO_STOP_LOSS = None      # V9: 无固定止损

_STATIC_REGIME_VOL_MULT: Dict[str, float] = {   # 基线 L254-258
    "BTC-USDT-SWAP": 1.00,
    "ETH-USDT-SWAP": 1.50,
    "SOL-USDT-SWAP": 1.75,
}

_ADDON_SUPPRESS_THRESHOLDS: Dict[str, Dict[str, float]] = {   # 基线 L262-266
    "BTC-USDT-SWAP": {"rsi_long": 70, "rsi_short": 30},
    "ETH-USDT-SWAP": {"rsi_long": 72, "rsi_short": 28},
    "SOL-USDT-SWAP": {"rsi_long": 76, "rsi_short": 24},
}

_STRENGTH_MULT = {"STRONG": 1.0, "MEDIUM": 0.7, "WEAK": 0.4, "NONE": 0.2}  # 基线 L861-866
_TOTAL_POSITION_LIMIT = 0.60  # 基线规范: 60%/40%/20% 总仓位上限（强信号档）


def _classify_signal(score: float) -> str:   # 基线 L717-724
    if score >= 70:
        return "STRONG"
    elif score >= 50:
        return "MEDIUM"
    elif score >= 30:
        return "WEAK"
    return "NONE"


class CMartinV15Node(BaseNode):
    """v15 经典马丁策略节点（V9 基线承载者）"""

    node_id = "C_MARTIN_V15"
    name = "V15经典马丁"
    description = ("v15 经典马丁策略：8%×vol_mult 复利加仓（≤3次）+ "
                   "4%×vol_mult 全仓止盈 + 无固定止损（V9 基线）")
    chain = "C"
    tags = ["martingale", "v15", "baseline", "classic"]
    estimated_tokens = 0
    estimated_latency_ms = 50

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        symbol = str(mkt.get("symbol") or "BTC").upper()
        inst_id = symbol if symbol.endswith("-USDT-SWAP") else f"{symbol}-USDT-SWAP"
        price = float(mkt.get("price") or 0)

        rationale: List[str] = []
        if price <= 0:
            rationale.append("[C_MARTIN_V15] 无有效价格数据，输出 HOLD")
            return NodeResult(
                node_id=self.node_id,
                confidence=0.3,          # P0-5: 纯代码节点下限，防 REDO
                direction="HOLD",
                outputs={"martin_plan": {}, "rationale": rationale},
            )

        ema20 = float(mkt.get("ema20") or price)
        ema50 = float(mkt.get("ema50") or price)
        ema200 = float(mkt.get("ema200") or price)
        rsi = mkt.get("rsi14")
        rsi = float(rsi) if rsi is not None else None

        # ── 1. 方向判定（基线 Screen1 语义适配：EMA 排列 + MA200 牛熊分界）──
        bull_aligned = price > ema200 and ema20 > ema50
        bear_aligned = price < ema200 and ema20 < ema50
        if bull_aligned:
            direction = "LONG"
            rationale.append(f"牛市结构: price>{ema200:.2f}(EMA200) 且 EMA20>EMA50 → LONG")
        elif bear_aligned:
            direction = "SHORT"
            rationale.append(f"熊市结构: price<{ema200:.2f}(EMA200) 且 EMA20<EMA50 → SHORT")
        else:
            direction = "WAIT"
            rationale.append("多空交织（EMA 排列与 MA200 不一致）→ WAIT 观望")

        # ── 2. vol_mult（基线静态表）────────────────────────
        vol_mult = _STATIC_REGIME_VOL_MULT.get(inst_id, 1.0)

        # ── 3. Screen2 评分（基线 L758-813 可用维度）────────
        score = 50.0
        if direction == "LONG" and ema20 > ema50:
            score += 15
            rationale.append("趋势一致性: LONG 且 EMA20>EMA50 (+15)")
        elif direction == "SHORT" and ema20 < ema50:
            score += 15
            rationale.append("趋势一致性: SHORT 且 EMA20<EMA50 (+15)")
        elif direction != "WAIT":
            score -= 10

        if rsi is not None and direction in ("LONG", "SHORT"):
            if direction == "LONG":
                if rsi < 30:
                    score += 15
                    rationale.append(f"RSI={rsi:.1f}<30 超卖区做多 (+15)")
                elif rsi > 70:
                    score -= 10
                    rationale.append(f"RSI={rsi:.1f}>70 超买风险 (-10)")
                elif 40 <= rsi <= 60:
                    score += 5
            else:
                if rsi > 70:
                    score += 15
                    rationale.append(f"RSI={rsi:.1f}>70 超买区做空 (+15)")
                elif rsi < 30:
                    score -= 10
                    rationale.append(f"RSI={rsi:.1f}<30 超卖风险 (-10)")
                elif 40 <= rsi <= 60:
                    score += 5

        score = max(0.0, min(100.0, score))
        strength = _classify_signal(score)

        # ── 4. V9 马丁计划（基线 L880-898 逐字数学）─────────
        gap = _V9_ADDON_GAP_PCT / 100.0 * vol_mult
        add_on_levels: List[float] = []
        tp_target = 0.0
        if direction == "LONG":
            add_on_levels = [
                round(price * (1 - gap) ** 1, 2),
                round(price * (1 - gap) ** 2, 2),
                round(price * (1 - gap) ** 3, 2),
            ]
            tp_target = round(price * (1 + _V9_TP_PCT / 100.0 * vol_mult), 2)
        elif direction == "SHORT":
            add_on_levels = [
                round(price * (1 + gap) ** 1, 2),
                round(price * (1 + gap) ** 2, 2),
                round(price * (1 + gap) ** 3, 2),
            ]
            tp_target = round(price * (1 - _V9_TP_PCT / 100.0 * vol_mult), 2)

        # 加仓抑制（基线 L900-912 的 RSI 分量；ATR 扩张分量在节点上下文
        # 无 20d ATR 基线，按保守不抑制处理）
        sup_cfg = _ADDON_SUPPRESS_THRESHOLDS.get(
            inst_id, _ADDON_SUPPRESS_THRESHOLDS["ETH-USDT-SWAP"])
        addon_suppressed = False
        if rsi is not None:
            if direction == "LONG" and rsi > sup_cfg["rsi_long"]:
                addon_suppressed = True
                rationale.append(f"RSI={rsi:.1f} 过热，抑制加仓（基线 v7.0 Opt-2）")
            elif direction == "SHORT" and rsi < sup_cfg["rsi_short"]:
                addon_suppressed = True
                rationale.append(f"RSI={rsi:.1f} 过冷，抑制加仓（基线 v7.0 Opt-2）")

        # 仓位（基线 L859-869: total_limit × strength_mult / 4 层）
        strength_mult = _STRENGTH_MULT.get(strength, 0.2)
        single_layer_pct = round(
            _TOTAL_POSITION_LIMIT * strength_mult * 1.0 / 4.0, 4)

        # ── 5. 置信度（P0-5: clamp [0.3, 0.95] 防 REDO）────
        confidence = round(max(min(0.3 + (score / 100.0) * 0.45, 0.95), 0.3), 3)

        out_direction = direction if direction != "WAIT" else "HOLD"
        rationale.insert(0, (f"[C_MARTIN_V15] {symbol} ${price:.2f} | "
                             f"vol_mult={vol_mult} | score={score:.1f}({strength})"))
        rationale.append(f"  方向: {out_direction} | 置信度: {confidence:.1%}")

        martin_plan = {
            "entry_price": price,
            "direction": out_direction,
            "add_on_levels": add_on_levels,
            "tp_target": tp_target,
            "stop_loss": _V9_NO_STOP_LOSS,        # V9: 无固定止损
            "max_addons": _V9_MAX_ADDONS,          # V9: ≤3 次
            "addon_gap_pct": _V9_ADDON_GAP_PCT * vol_mult,
            "tp_pct": _V9_TP_PCT * vol_mult,
            "vol_mult": vol_mult,
            "signal_score": round(score, 2),
            "signal_strength": strength,
            "position_pct": single_layer_pct,
            "addon_suppressed": addon_suppressed,
            "v9_baseline": "v15-six-trading-20260601",
        }

        return NodeResult(
            node_id=self.node_id,
            confidence=confidence,
            direction=out_direction,
            outputs={"martin_plan": martin_plan, "rationale": rationale},
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        """从 state 中提取市场数据（与 C1 等节点同构）"""
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(getattr(state, "intent", None), dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}
