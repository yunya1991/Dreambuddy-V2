#!/usr/bin/env python3
"""
离场模块 Exit Module — 三层离场架构
=====================================

L1 — 基础离场（波动率止损止盈）：
    入场时基于 ATR 自动计算止损止盈，作为保底机制
    任何情况下都生效，高级层可以修改但不能删除

L2 — Agent A 智能离场：
    每次 LLM 决策时评估现有持仓
    可以修改/更新预设的止损止盈
    可以主动平仓（信号离场）

L3 — Agent B 离场系统：
    AI 驱动时调用 A9 离场评估节点
    无大模型时回退到经典指标系统
    可以修改预设止盈止损

数据存储：
    各 agent 的 memory.active_positions 中维护活跃持仓
    结构：{
        "BTC": {
            "entry_price": 65000.0,
            "action": "LONG",
            "position_size_usdt": 100.0,
            "leverage": 3,
            "stop_loss_price": 63700.0,    # L1 预设
            "take_profit_price": 67600.0,  # L1 预设
            "sl_source": "atr_basic",     # 止损来源
            "tp_source": "atr_basic",     # 止盈来源
            "entry_ts": "2024-...",
            "max_pnl_pct": 0.0,          # 历史最大浮盈
            "cycle_id": "20240101_000000"
        }
    }
"""
import os, sys, json, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))
from execution.aster_spot import HyperliquidClient, get_candles


# ── 离场原因枚举 ──────────────────────────────────────────────────────────
EXIT_REASON_SL_BASE     = "SL_BASE"        # L1 基础止损
EXIT_REASON_TP_BASE     = "TP_BASE"        # L1 基础止盈
EXIT_REASON_SL_SMART    = "SL_SMART"       # L2/L3 智能止损
EXIT_REASON_TP_SMART    = "TP_SMART"       # L2/L3 智能止盈
EXIT_REASON_SIGNAL      = "SIGNAL"         # 信号反转离场
EXIT_REASON_TRAILING    = "TRAILING_STOP"  # 移动止损
EXIT_REASON_RISK        = "RISK_PROTECT"   # 风控保护离场


# ── L1: 基于 ATR 波动率的基础止损止盈 ──────────────────────────────────

def calculate_atr(coin: str, proxies=None, period: int = 14,
                  interval: str = "1h") -> float:
    """
    计算 ATR（平均真实波幅）
    返回 ATR 绝对值（如 BTC 的 ATR 可能是 800 美元）
    """
    try:
        candles = get_candles(coin, interval, period + 2, proxies)
        if len(candles) < 2:
            return 0.0
        trs = []
        for i in range(1, min(len(candles), period + 1)):
            h = float(candles[i].get("h", 0))
            l = float(candles[i].get("l", 0))
            c_prev = float(candles[i-1].get("c", 0))
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 0.0
    except Exception:
        return 0.0


def calculate_basic_exit_levels(
    coin: str,
    entry_price: float,
    action: str,
    atr_value: Optional[float] = None,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 3.0,
    min_sl_pct: float = 0.02,     # 最小止损 2%
    min_tp_pct: float = 0.04,     # 最小止盈 4%
    max_sl_pct: float = 0.10,     # 最大止损 10%
    max_tp_pct: float = 0.20,     # 最大止盈 20%
    proxies=None,
) -> Tuple[float, float]:
    """
    L1 基础离场：基于 ATR 波动率计算止损止盈价格

    参数:
        coin: 币种
        entry_price: 入场价格
        action: "LONG" 或 "SHORT"
        atr_value: 可选，预计算的 ATR 值
        sl_atr_mult: 止损 ATR 倍数（默认 1.5x ATR）
        tp_atr_mult: 止盈 ATR 倍数（默认 3.0x ATR，盈亏比 2:1）

    返回: (stop_loss_price, take_profit_price)
    """
    if entry_price <= 0:
        return 0.0, 0.0

    # 获取 ATR
    if atr_value is None or atr_value <= 0:
        atr_value = calculate_atr(coin, proxies)

    # ATR 百分比（相对入场价）
    atr_pct = atr_value / entry_price if entry_price > 0 else 0

    # 计算止损止盈百分比（夹在 min/max 之间）
    sl_pct = max(min(atr_pct * sl_atr_mult, max_sl_pct), min_sl_pct)
    tp_pct = max(min(atr_pct * tp_atr_mult, max_tp_pct), min_tp_pct)

    is_long = action.upper() in ("LONG", "BUY")

    if is_long:
        sl_price = entry_price * (1 - sl_pct)
        tp_price = entry_price * (1 + tp_pct)
    else:
        sl_price = entry_price * (1 + sl_pct)
        tp_price = entry_price * (1 - tp_pct)

    return round(sl_price, _price_decimals(coin)), round(tp_price, _price_decimals(coin))


def _price_decimals(coin: str) -> int:
    return {"BTC": 1, "ETH": 2, "SOL": 3, "HYPE": 3}.get(coin, 4)


# ── 活跃持仓管理 ──────────────────────────────────────────────────────────

def init_position(
    active_positions: Dict,
    coin: str,
    entry_price: float,
    action: str,
    position_size_usdt: float,
    leverage: int,
    stop_loss_price: Optional[float] = None,
    take_profit_price: Optional[float] = None,
    cycle_id: str = "",
    proxies=None,
) -> Dict:
    """
    开仓时初始化持仓记录，自动计算 L1 基础止损止盈
    如果传入了自定义 SL/TP，则覆盖基础值
    """
    action = action.upper()

    # 计算 L1 基础止损止盈
    basic_sl, basic_tp = calculate_basic_exit_levels(
        coin, entry_price, action, proxies=proxies
    )

    # 优先使用传入的自定义值，否则用基础值
    sl_price = stop_loss_price if stop_loss_price and stop_loss_price > 0 else basic_sl
    tp_price = take_profit_price if take_profit_price and take_profit_price > 0 else basic_tp

    sl_source = "custom" if stop_loss_price and stop_loss_price > 0 else "atr_basic"
    tp_source = "custom" if take_profit_price and take_profit_price > 0 else "atr_basic"

    now_iso = datetime.now(timezone.utc).isoformat()

    active_positions[coin] = {
        "entry_price": entry_price,
        "action": action,
        "position_size_usdt": position_size_usdt,
        "leverage": leverage,
        "stop_loss_price": sl_price,
        "take_profit_price": tp_price,
        "sl_source": sl_source,
        "tp_source": tp_source,
        "entry_ts": now_iso,
        "max_pnl_pct": 0.0,
        "cycle_id": cycle_id,
    }

    return active_positions


def update_position_exit_levels(
    active_positions: Dict,
    coin: str,
    new_stop_loss: Optional[float] = None,
    new_take_profit: Optional[float] = None,
    sl_source: str = "smart_override",
    tp_source: str = "smart_override",
) -> Dict:
    """
    L2/L3 层更新止损止盈（智能调整）
    保留 L1 基础值作为兜底（不清除，只是覆盖显示值）
    """
    if coin not in active_positions:
        return active_positions

    pos = active_positions[coin]

    if new_stop_loss is not None and new_stop_loss > 0:
        # 移动止损：只允许向有利方向移动
        is_long = pos["action"] in ("LONG", "BUY")
        if is_long:
            if new_stop_loss > pos["stop_loss_price"]:
                pos["stop_loss_price"] = new_stop_loss
                pos["sl_source"] = sl_source
        else:
            if new_stop_loss < pos["stop_loss_price"]:
                pos["stop_loss_price"] = new_stop_loss
                pos["sl_source"] = sl_source

    if new_take_profit is not None and new_take_profit > 0:
        pos["take_profit_price"] = new_take_profit
        pos["tp_source"] = tp_source

    active_positions[coin] = pos
    return active_positions


def close_position_record(
    active_positions: Dict,
    coin: str,
    exit_price: float,
    exit_reason: str,
) -> Tuple[Dict, Optional[Dict]]:
    """
    平仓时移除持仓记录，返回平仓详情
    返回: (active_positions, closed_position_info)
    """
    if coin not in active_positions:
        return active_positions, None

    pos = active_positions.pop(coin)

    is_long = pos["action"] in ("LONG", "BUY")
    entry_px = pos["entry_price"]

    if is_long:
        pnl_pct = (exit_price - entry_px) / entry_px
    else:
        pnl_pct = (entry_px - exit_price) / entry_px

    closed_info = {
        "coin": coin,
        "entry_price": entry_px,
        "exit_price": exit_price,
        "action": pos["action"],
        "pnl_pct": round(pnl_pct, 6),
        "exit_reason": exit_reason,
        "entry_ts": pos["entry_ts"],
        "exit_ts": datetime.now(timezone.utc).isoformat(),
        "position_size_usdt": pos["position_size_usdt"],
        "leverage": pos["leverage"],
        "stop_loss_at_exit": pos["stop_loss_price"],
        "take_profit_at_exit": pos["take_profit_price"],
        "cycle_id": pos["cycle_id"],
    }

    return active_positions, closed_info


# ── L1 离场检测 ──────────────────────────────────────────────────────────

def check_l1_exits(
    client: HyperliquidClient,
    active_positions: Dict,
) -> List[Dict]:
    """
    检查 L1 基础离场条件（止损/止盈）
    返回需要平仓的列表: [{coin, reason, current_price}]
    """
    if not active_positions:
        return []

    exits = []
    mids = client.get_all_mids()

    for coin, pos in active_positions.items():
        current_price = mids.get(coin, 0)
        if current_price <= 0:
            continue

        is_long = pos["action"] in ("LONG", "BUY")
        sl = pos["stop_loss_price"]
        tp = pos["take_profit_price"]

        # 更新最大浮盈
        if is_long:
            pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
        else:
            pnl_pct = (pos["entry_price"] - current_price) / pos["entry_price"]
        pos["max_pnl_pct"] = max(pos.get("max_pnl_pct", 0), pnl_pct)

        # 止损检测
        if sl and sl > 0:
            if (is_long and current_price <= sl) or (not is_long and current_price >= sl):
                exits.append({
                    "coin": coin,
                    "reason": EXIT_REASON_SL_BASE,
                    "current_price": current_price,
                    "trigger_level": sl,
                    "position": pos,
                })
                continue

        # 止盈检测
        if tp and tp > 0:
            if (is_long and current_price >= tp) or (not is_long and current_price <= tp):
                exits.append({
                    "coin": coin,
                    "reason": EXIT_REASON_TP_BASE,
                    "current_price": current_price,
                    "trigger_level": tp,
                    "position": pos,
                })
                continue

    return exits


# ── L3 Agent B: 经典指标离场系统（无 LLM 回退）─────────────────────────

def check_classical_indicator_exits(
    coin: str,
    current_price: float,
    position_action: str,
    candles_1h: List[Dict],
    rsi_period: int = 14,
    ema_fast: int = 9,
    ema_slow: int = 21,
) -> Tuple[bool, str, float]:
    """
    L3 经典指标离场系统（Agent B 无 LLM 时的回退方案）

    离场信号：
    1. RSI 超买/超卖反转
    2. EMA 死叉/金叉
    3. 价格跌破/突破关键均线

    返回: (should_exit, reason, suggested_exit_price)
    """
    if not candles_1h or len(candles_1h) < ema_slow + 5:
        return False, "", 0.0

    closes = [float(c["c"]) for c in candles_1h if "c" in c]
    if len(closes) < ema_slow + 5:
        return False, "", 0.0

    closes = closes[::-1]  # 旧→新

    # EMA 计算
    def ema(prices, n):
        if len(prices) < n:
            return prices[-1]
        k = 2 / (n + 1)
        e = prices[-n]
        for p in prices[-n+1:]:
            e = p * k + e * (1 - k)
        return e

    ema_fast_val = ema(closes, ema_fast)
    ema_slow_val = ema(closes, ema_slow)
    ema_20 = ema(closes, 20)
    ema_50 = ema(closes, 50) if len(closes) >= 50 else ema_slow_val

    # RSI 计算
    def rsi(prices, n=14):
        if len(prices) < n + 1:
            return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, n+1)]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        avg_g = sum(gains) / n
        avg_l = sum(losses) / n
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - 100 / (1 + rs)

    rsi_val = rsi(closes, rsi_period)

    is_long = position_action.upper() in ("LONG", "BUY")

    # ── 多头离场信号 ──
    if is_long:
        # 信号1: RSI 超买（>70）且 EMA 快线下穿慢线（死叉）
        if rsi_val > 70 and ema_fast_val < ema_slow_val * 0.998:
            return True, "CLASSIC_RSI_OVERBOUGHT+EMA_DEATH_CROSS", current_price

        # 信号2: 价格跌破 EMA20 且 RSI < 45（趋势走弱）
        if current_price < ema_20 and rsi_val < 45:
            return True, "CLASSIC_BELOW_EMA20+RSI_WEAK", current_price

        # 信号3: 价格跌破 EMA50（中期趋势反转）
        if current_price < ema_50 * 0.995:
            return True, "CLASSIC_BELOW_EMA50_TREND_REVERSAL", current_price

    # ── 空头离场信号 ──
    else:
        # 信号1: RSI 超卖（<30）且 EMA 快线上穿慢线（金叉）
        if rsi_val < 30 and ema_fast_val > ema_slow_val * 1.002:
            return True, "CLASSIC_RSI_OVERSOLD+EMA_GOLDEN_CROSS", current_price

        # 信号2: 价格突破 EMA20 且 RSI > 55（趋势走强）
        if current_price > ema_20 and rsi_val > 55:
            return True, "CLASSIC_ABOVE_EMA20+RSI_STRONG", current_price

        # 信号3: 价格突破 EMA50（中期趋势反转）
        if current_price > ema_50 * 1.005:
            return True, "CLASSIC_ABOVE_EMA50_TREND_REVERSAL", current_price

    return False, "", 0.0


# ── 移动止损（Trailing Stop）─────────────────────────────────────────────

def update_trailing_stop(
    active_positions: Dict,
    coin: str,
    current_price: float,
    trail_pct: float = 0.03,  # 3% 回撤触发
) -> Dict:
    """
    移动止损：当浮盈达到一定程度后，止损价随价格向有利方向移动
    触发条件：浮盈 >= 2x trail_pct 时启动移动止损
    """
    if coin not in active_positions:
        return active_positions

    pos = active_positions[coin]
    is_long = pos["action"] in ("LONG", "BUY")
    entry_px = pos["entry_price"]

    if is_long:
        pnl_pct = (current_price - entry_px) / entry_px
    else:
        pnl_pct = (entry_px - current_price) / entry_px

    # 浮盈足够时才启动移动止损
    if pnl_pct < trail_pct * 2:
        return active_positions

    if is_long:
        new_sl = current_price * (1 - trail_pct)
        # 只向上移动，不向下
        if new_sl > pos["stop_loss_price"]:
            pos["stop_loss_price"] = new_sl
            pos["sl_source"] = "trailing_stop"
    else:
        new_sl = current_price * (1 + trail_pct)
        # 只向下移动，不向上
        if new_sl < pos["stop_loss_price"]:
            pos["stop_loss_price"] = new_sl
            pos["sl_source"] = "trailing_stop"

    active_positions[coin] = pos
    return active_positions


# ── 执行离场 ──────────────────────────────────────────────────────────────

def execute_exit(
    client: HyperliquidClient,
    active_positions: Dict,
    coin: str,
    exit_reason: str,
    tag: str = "ab",
) -> Tuple[Dict, Optional[Dict], Dict]:
    """
    执行平仓操作，返回 (active_positions, closed_info, exec_result)
    """
    exec_result = client.close_position(coin, tag)

    if not exec_result.get("ok"):
        return active_positions, None, exec_result

    # 获取成交价格（用 mid price 近似）
    try:
        exit_price = client.get_mid_price(coin)
    except Exception:
        exit_price = 0

    active_positions, closed_info = close_position_record(
        active_positions, coin, exit_price, exit_reason
    )

    return active_positions, closed_info, exec_result


# ── 同步持仓状态（从交易所实际持仓同步）─────────────────────────────────

def sync_positions_from_exchange(
    client: HyperliquidClient,
    active_positions: Dict,
) -> Dict:
    """
    将内存中的 active_positions 与交易所实际持仓同步
    防止因异常退出导致的记录不一致
    """
    acct = client.get_account()
    real_positions = acct.get("positions", {})

    # 1. 移除交易所已不存在的持仓
    coins_to_remove = [c for c in active_positions if c not in real_positions]
    for c in coins_to_remove:
        del active_positions[c]

    # 2. 新增交易所存在但内存中没有的持仓（异常恢复）
    for coin, pos in real_positions.items():
        if coin not in active_positions and abs(pos.get("size", 0)) > 0:
            size = pos["size"]
            action = "LONG" if size > 0 else "SHORT"
            entry_px = pos.get("entry_px", 0)
            if entry_px <= 0:
                continue

            # 初始化基础止损止盈
            basic_sl, basic_tp = calculate_basic_exit_levels(
                coin, entry_px, action, proxies=client.proxies
            )

            active_positions[coin] = {
                "entry_price": entry_px,
                "action": action,
                "position_size_usdt": abs(size) * entry_px / (pos.get("leverage", 1) or 1),
                "leverage": int(pos.get("leverage", 1)),
                "stop_loss_price": basic_sl,
                "take_profit_price": basic_tp,
                "sl_source": "atr_basic",
                "tp_source": "atr_basic",
                "entry_ts": datetime.now(timezone.utc).isoformat(),
                "max_pnl_pct": 0.0,
                "cycle_id": "recovered",
            }

    return active_positions


# ── 主入口：离场检查与执行 ────────────────────────────────────────────────

def run_exit_check(
    client: HyperliquidClient,
    active_positions: Dict,
    agent_id: str = "a",
    enable_trailing: bool = True,
) -> Tuple[Dict, List[Dict]]:
    """
    执行完整的离场检查流程（L1 基础层）

    流程：
    1. 同步交易所持仓
    2. 更新移动止损（如启用）
    3. 检查 L1 止损止盈
    4. 执行触发的离场

    返回: (active_positions, closed_trades_list)
    """
    closed_trades = []

    # 1. 同步持仓
    active_positions = sync_positions_from_exchange(client, active_positions)

    if not active_positions:
        return active_positions, closed_trades

    mids = client.get_all_mids()

    # 2. 更新移动止损
    if enable_trailing:
        for coin in list(active_positions.keys()):
            price = mids.get(coin, 0)
            if price > 0:
                active_positions = update_trailing_stop(
                    active_positions, coin, price
                )

    # 3. 检查 L1 离场
    exits = check_l1_exits(client, active_positions)

    # 4. 执行离场
    for exit_info in exits:
        coin = exit_info["coin"]
        reason = exit_info["reason"]
        tag = f"{agent_id}_exit"

        active_positions, closed_info, exec_result = execute_exit(
            client, active_positions, coin, reason, tag
        )

        if closed_info:
            closed_info["execution"] = exec_result
            closed_trades.append(closed_info)

    return active_positions, closed_trades


# ── 快速测试 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== 离场模块测试 ===")

    # 测试 ATR 计算
    print("\n[L1] ATR 计算测试:")
    for coin in ["BTC", "ETH", "SOL"]:
        atr = calculate_atr(coin)
        print(f"  {coin}: ATR = {atr:.2f} USD")

    # 测试基础止损止盈计算
    print("\n[L1] 基础止损止盈测试 (BTC LONG @ 65000):")
    sl, tp = calculate_basic_exit_levels("BTC", 65000.0, "LONG")
    print(f"  止损: {sl:.2f} (基础)")
    print(f"  止盈: {tp:.2f} (基础)")

    print("\n[L1] 基础止损止盈测试 (ETH SHORT @ 3500):")
    sl, tp = calculate_basic_exit_levels("ETH", 3500.0, "SHORT")
    print(f"  止损: {sl:.2f} (基础)")
    print(f"  止盈: {tp:.2f} (基础)")

    # 测试持仓管理
    print("\n[持仓管理] 初始化持仓:")
    positions = {}
    positions = init_position(positions, "BTC", 65000.0, "LONG", 100.0, 3,
                             cycle_id="test_cycle")
    print(f"  BTC 持仓: SL={positions['BTC']['stop_loss_price']}, "
          f"TP={positions['BTC']['take_profit_price']}, "
          f"source=SL:{positions['BTC']['sl_source']}/TP:{positions['BTC']['tp_source']}")

    print("\n[持仓管理] 更新止损（移动止损模拟）:")
    positions = update_position_exit_levels(positions, "BTC", new_stop_loss=64500.0)
    print(f"  BTC 持仓: SL={positions['BTC']['stop_loss_price']} (source: {positions['BTC']['sl_source']})")

    print("\n[持仓管理] 平仓记录:")
    positions, closed = close_position_record(positions, "BTC", 67000.0, EXIT_REASON_TP_BASE)
    if closed:
        print(f"  平仓: PnL={closed['pnl_pct']*100:.2f}%, 原因={closed['exit_reason']}")
    print(f"  剩余持仓: {list(positions.keys())}")

    print("\n✅ 离场模块加载成功")
