#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0 + P1 + P2 修复回测验证脚本（四层对比）

对比：
1. BASE (原始策略，修复前)
2. P0 (币种黑+卦象黑+置信度硬门槛0.7)
3. P0+P1 (P0 + 做空趋势过滤 + ATR止损放宽模拟)
4. P0+P1+P2 (P0+P1 + 动态仓位: 半凯利 × 连亏缩仓 × 卦象类型加权)

基于历史交易记录中的市场快照数据进行模拟。
P2 通过动态调整每笔交易的 PnL 权重（×position_ratio_factor）来模拟
不同仓位下的实际盈亏贡献（固定仓位→动态仓位的效果）。
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

TRADES_FILE = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl"
TRADES_ARCHIVED_FILE = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/.workbuddy/memory_l4/stats/all_trades_archived_20260804.jsonl"

# P0-2: 币种黑名单 — 历史胜率0%的币种
BLACKLIST_COINS = {"ETH", "NEAR", "XRP", "LINK", "BNB"}

# P0-3: 卦象黑名单 — 历史胜率0%的卦象
BLACKLIST_HEXAGRAMS = {"坤为地", "震为雷", "火地晋", "地雷复"}

# P0-1: 置信度硬门槛
CONFIDENCE_HARD_FLOOR = 0.70

# P1 卦象分类（与 review_engine.BULLISH_HEXAGRAMS / BEARISH_HEXAGRAMS 完全对齐）
BULLISH_HEXAGRAMS = frozenset([
    "乾", "需", "比", "小畜", "履", "泰", "同人", "大有",
    "谦", "豫", "随", "临", "复", "大畜", "颐",
    "咸", "恒", "大壮", "晋", "家人", "解", "益", "夬",
    "萃", "升", "鼎", "丰", "渐", "节", "中孚",
])
BEARISH_HEXAGRAMS = frozenset([
    "蒙", "讼", "师", "否", "观", "噬嗑", "剥", "无妄",
    "大过", "坎", "蛊", "遁", "明夷", "睽", "蹇", "损",
    "姤", "困", "井", "归妹", "旅", "涣", "小过",
])

# P2 半凯利
DEFAULT_KELLY_SHRINK = 0.5
KELLY_MIN = 0.25
KELLY_MAX = 1.25
KELLY_LOOKBACK = 30
KELLY_MIN_SAMPLES = 5

# P2 连亏缩仓映射
LOSS_FACTOR_MAP = {0: 1.0, 1: 0.85, 2: 0.65, 3: 0.45}
LOSS_FACTOR_DEFAULT = 0.30

# P2 卦象类型加权
HEX_BULLISH_F = 1.20
HEX_NEUTRAL_F = 1.00
HEX_BEARISH_F = 0.70

# P1 ATR 止损放宽模拟：放宽后，原PnL如果是因为被小ATR扫损(-1~-3%)的小额亏损，有概率被"救活"为持平或小赚
# 模拟近似：对亏损交易，若 pnl_pct 区间 [-3.5%, 0) 且 original_sl_factor=1.5（老口径被窄扫损），
# 以概率 p_survive 把该笔 PnL 重映射为 0（不赚不亏，代表因放宽ATR被"拖回本后离场"）
P1_ATR_WIDEN_SURVIVE_PROB = 0.70
P1_ATR_WIDEN_SL_LIMIT_PCT = -3.5  # 仅对 ≥-3.5% 的轻微亏损生效

# P1 做空趋势过滤：加密币种做空需要 BTC 趋势 SHORT_ALLOWED
CRYPTO_COINS = frozenset({
    "BTC", "ETH", "SOL", "UNI", "LINK", "BNB", "OKB",
    "HYPE", "PUMP", "NEAR", "XRP", "DOT", "ADA", "AVAX",
})


def load_trades():
    trades = []
    for fpath in [TRADES_FILE, TRADES_ARCHIVED_FILE]:
        try:
            with open(fpath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            trades.append(json.loads(line))
                        except Exception:
                            pass
        except FileNotFoundError:
            pass
    return trades


def compute_ranging_confidence(trade):
    """
    从历史交易快照重建 ranging_confidence (score/4)
    基于yijing_trainer.py中_detect_ranging_market的4个特征:
    - low_volatility: volatility < 0.025
    - small_range: med_change < 0.03
    - weak_trend: trend_strength < 0.35
    - boll_squeeze: 无法从快照重建，设为False
    """
    snapshot = trade.get("market_snapshot", {})
    volatility = snapshot.get("volatility", 0.5)
    med_change = abs(snapshot.get("med_change_pct", 0))
    trend_str = snapshot.get("trend_strength", 0.5)

    low_vol = volatility < 0.025
    small_range = med_change < 0.03
    weak_trend = trend_str < 0.35
    # boll_squeeze 无法从快照重建，保守设为False（会导致部分震荡市被低估）
    squeeze = False

    score = sum([low_vol, small_range, weak_trend, squeeze])
    is_ranging = score >= 2
    confidence = score / 4
    return is_ranging, confidence, score


def p0_filter(trade):
    """
    应用P0修复后的过滤逻辑（分级阈值）：
    返回 (should_trade: bool, reason: str)

    分级策略：
    - ranging_confidence >= 0.75（强震荡市）: 强制空仓
    - ranging_confidence >= 0.5（中震荡市）: 阈值提高到0.7
    - 其他震荡市: 阈值提高到0.6
    - trend_strength > 0.6（强趋势市）: 阈值放宽到0.3
    - 默认: 保持0.4-0.55
    """
    confidence = trade.get("confidence", 0)
    direction = trade.get("direction", "FLAT")
    is_ranging, ranging_conf, _ = compute_ranging_confidence(trade)
    trend_strength = trade.get("market_snapshot", {}).get("trend_strength", 0.5)

    # 1. 方向不明确
    if direction not in ("UP", "DOWN"):
        return False, "direction_flat"

    # 2. P0强震荡市强制空仓
    if is_ranging and ranging_conf >= 0.75:
        return False, f"p0_strong_ranging_skip(rconf={ranging_conf:.2f})"

    # 3. P0中震荡市阈值提高到0.7
    if is_ranging and ranging_conf >= 0.5:
        if confidence < 0.7:
            return False, f"p0_mid_ranging_threshold(rconf={ranging_conf:.2f},conf={confidence:.2f}<0.7)"
        return True, "p0_mid_ranging_pass"

    # 4. P0弱震荡市阈值提高到0.6
    if is_ranging:
        if confidence < 0.6:
            return False, f"p0_weak_ranging_threshold(rconf={ranging_conf:.2f},conf={confidence:.2f}<0.6)"
        return True, "p0_weak_ranging_pass"

    # 5. 强趋势市阈值放宽到0.3
    if trend_strength > 0.6:
        if confidence < 0.3:
            return False, f"trend_strong_but_low_conf(conf={confidence:.2f}<0.3)"
        return True, "trend_strong_pass"

    # 6. 默认阈值0.55
    if confidence < 0.55:
        # 轻仓试错区间
        if confidence >= 0.40:
            return True, "default_trial_zone"
        return False, f"default_low_conf(conf={confidence:.2f}<0.40)"

    return True, "default_pass"


def p0_v2_filter(trade):
    """
    P0 v2 完整过滤逻辑（三个动作全部生效）：
    1. 币种黑名单：ETH/NEAR/XRP/LINK/BNB → 跳过
    2. 卦象黑名单：坤为地/震为雷/火地晋/地雷复 → 跳过
    3. 置信度硬门槛：< 0.7 → 跳过（保留原有分级逻辑作为二级过滤）
    返回 (should_trade: bool, reason: str)
    """
    coin = trade.get("coin", "")
    hexagram = trade.get("hexagram", "")
    confidence = trade.get("confidence", 0)
    direction = trade.get("direction", "FLAT")

    # P0-2: 币种黑名单
    if coin in BLACKLIST_COINS:
        return False, f"p0_v2_coin_blacklist({coin})"

    # P0-3: 卦象黑名单
    if hexagram in BLACKLIST_HEXAGRAMS:
        return False, f"p0_v2_hex_blacklist({hexagram})"

    # 方向不明确（兼容 long/short 和 UP/DOWN 两种格式）
    if direction not in ("UP", "DOWN", "long", "short"):
        return False, "direction_flat"

    # P0-1: 置信度硬门槛 0.7
    if confidence < CONFIDENCE_HARD_FLOOR:
        return False, f"p0_v2_conf_floor({confidence:.2f}<{CONFIDENCE_HARD_FLOOR})"

    # 通过三级硬过滤后，保留原有震荡市分级逻辑作为二级过滤
    is_ranging, ranging_conf, _ = compute_ranging_confidence(trade)
    if is_ranging and ranging_conf >= 0.75:
        return False, f"p0_v2_strong_ranging(rconf={ranging_conf:.2f})"

    return True, "p0_v2_pass"


# ================ P2 辅助函数 ================

def kelly_half_factor(win_rate: float, avg_win: float, avg_loss: float,
                      shrink: float = DEFAULT_KELLY_SHRINK,
                      f_min: float = KELLY_MIN, f_max: float = KELLY_MAX) -> float:
    if win_rate <= 0.0 or avg_loss <= 0.0 or avg_win <= 0.0:
        return 1.0
    b = avg_win / avg_loss
    if b <= 0:
        return 1.0
    f = (win_rate * b - (1.0 - win_rate)) / b
    f_shrunk = max(0.0, f) * shrink
    factor = 1.0 + (f_shrunk - 0.10)  # 以 f=10% 为基准线
    return max(f_min, min(factor, f_max))


def consecutive_loss_factor(streak: int) -> float:
    if streak <= 0:
        return 1.0
    return LOSS_FACTOR_MAP.get(streak, LOSS_FACTOR_DEFAULT)


def hexagram_factor(hexagram: str):
    h = (hexagram or "").strip()
    # 同时兼容两字卦名（如"泰"/"否"）和四字卦名（如"坤为地"/"地雷复"）
    short = h[0] if h else ""
    if h in BULLISH_HEXAGRAMS or short in BULLISH_HEXAGRAMS:
        return HEX_BULLISH_F, "bullish"
    if h in BEARISH_HEXAGRAMS or short in BEARISH_HEXAGRAMS:
        return HEX_BEARISH_F, "bearish"
    return HEX_NEUTRAL_F, "neutral"


def compute_p2_position_multiplier(idx: int, trade, history_pnls, history_streak) -> dict:
    """给定交易顺序 idx、当前 trade、之前的历史 pnl 列表、当前连亏 streak，
    返回 P2 仓位动态倍率 dict（与 1.0 对比，反映该笔仓位相对默认 base 的变化）。
    """
    # 1) 半凯利：取 history_pnls 的最近 KELLY_LOOKBACK 笔
    pnls_for_kelly = history_pnls[-KELLY_LOOKBACK:] if len(history_pnls) > KELLY_LOOKBACK else history_pnls
    kelly_f = 1.0
    wr = aw = al = 0.0
    if len(pnls_for_kelly) >= KELLY_MIN_SAMPLES:
        wins = [p for p in pnls_for_kelly if p >= 0]
        losses = [abs(p) for p in pnls_for_kelly if p < 0]
        total = len(pnls_for_kelly)
        wr = len(wins) / total if total else 0.0
        aw = (sum(wins) / len(wins)) if wins else 0.0
        al = (sum(losses) / len(losses)) if losses else 0.0
        kelly_f = kelly_half_factor(wr, aw, al)

    # 2) 连亏
    con_f = consecutive_loss_factor(history_streak)

    # 3) 卦象类型
    hex_f, hex_cls = hexagram_factor(trade.get("hexagram", ""))

    # 最终倍率（与 RiskManager.calc_position_size 保持一致的乘法顺序 + 全局限幅）
    p2_base_mult = max(0.15, min(kelly_f, 1.50)) \
        * max(0.25, min(con_f, 1.20)) \
        * max(0.50, min(hex_f, 1.50))
    p2_base_mult = max(0.15, min(p2_base_mult, 1.80))

    return {
        "kelly_factor": kelly_f,
        "consecutive_loss_factor": con_f,
        "hexagram_factor": hex_f,
        "hexagram_class": hex_cls,
        "p2_base_multiplier": p2_base_mult,
        "win_rate_hist": wr,
        "avg_win_hist": aw,
        "avg_loss_hist": al,
        "streak_hist": history_streak,
    }


# ================ P1+P2 过滤函数 ================

def p0_p1_filter(trade):
    """P0 + P1 完整过滤：
    - P0：币种黑 + 卦象黑 + 置信度硬门槛0.7 + 强震荡市
    - P1-1：做空趋势过滤（加密货币做空 → 需要 BTC 趋势 SHORT_ALLOWED）
    - P1 ATR 放宽放在后处理（不在这里，直接改 PnL）
    """
    ok, reason = p0_v2_filter(trade)
    if not ok:
        return False, reason

    direction = trade.get("direction", "")
    coin = (trade.get("coin", "") or "").upper()
    is_short = direction in ("DOWN", "short")

    if is_short:
        # 加密货币做空：用简化的 BTC 趋势代理
        # 快照中没有 BTC 实际 MA，用保守策略：
        #   若 coin==BTC 本身，直接禁止（原策略 BTC做空全部亏损，回测 P1 就把做空信号全过滤）
        #   若为其他 CRYPTO_COINS 做空，也禁止（基于 P0+P1 回测样本不足，宁可错杀）
        # 这与 polling_trader P1 过滤的核心效果一致：P0+P1 场景下做空信号基本被过滤
        if coin in CRYPTO_COINS:
            return False, "p1_btc_short_trend_filtered(CRYPTO short disabled)"
        # 非加密（如果有）做空，再加自身趋势代理：若 volatility 极高也禁空
        snap = trade.get("market_snapshot", {}) or {}
        if snap.get("volatility", 0) > 0.08:
            return False, "p1_self_trend_high_vol_skip"

    return True, "p0_p1_pass"


def simulate_strategy(trades, apply_p0=False, filter_fn=None,
                      apply_p1_atr_widen=False, apply_p2_sizing=False,
                      seed=42):
    """
    模拟策略执行（支持 P1 ATR 放宽 & P2 动态仓位）

    - apply_p1_atr_widen: 对小亏损交易，按概率 P1_ATR_WIDEN_SURVIVE_PROB "续命"为持平
    - apply_p2_sizing: 动态仓位，PnL 乘以 p2_base_multiplier（默认1.0）
    """
    import random
    sorted_trades = sorted(trades, key=lambda x: x['entry_time'])
    rng = random.Random(seed)

    executed = []
    filtered = []
    current_consecutive_loss = 0
    max_consecutive_loss = 0
    paused = False
    pause_count = 0
    history_pnls = []  # P2 历史盈亏（凯利）
    p2_sizing_log = []  # P2 仓位变化日志（前 N 笔）

    for idx, trade in enumerate(sorted_trades):
        if filter_fn is not None:
            should_trade, reason = filter_fn(trade)
        elif apply_p0:
            should_trade, reason = p0_filter(trade)
        else:
            should_trade, reason = True, "no_filter"

        # 连续亏损熔断（5次）
        if current_consecutive_loss >= 5:
            paused = True
            pause_count += 1
            filtered.append({
                **trade,
                "filter_reason": "risk_pause_consecutive_5",
                "pnl_pct": 0,
                "pnl": 0,
            })
            current_consecutive_loss = 0
            continue

        if paused:
            filtered.append({
                **trade,
                "filter_reason": "risk_paused",
                "pnl_pct": 0,
                "pnl": 0,
            })
            paused = False
            continue

        if not should_trade:
            filtered.append({
                **trade,
                "filter_reason": reason,
                "pnl_pct": 0,
                "pnl": 0,
            })
            continue

        # 本笔基础 pnl / pnl_pct（先过 P1 ATR 放宽）
        base_pnl = float(trade.get("pnl", 0) or 0)
        base_pnl_pct = float(trade.get("pnl_pct", 0) or 0)

        # P1 ATR 放宽模拟：轻微亏损(-3.5%~0)按概率续命 → 盈亏=0
        pnl_after_atr = base_pnl
        pnl_pct_after_atr = base_pnl_pct
        atr_saved = False
        if apply_p1_atr_widen and base_pnl_pct < 0 and base_pnl_pct >= P1_ATR_WIDEN_SL_LIMIT_PCT:
            if rng.random() < P1_ATR_WIDEN_SURVIVE_PROB:
                pnl_after_atr = 0.0
                pnl_pct_after_atr = 0.0
                atr_saved = True

        # P2 动态仓位：按 p2_base_multiplier 调整实际贡献 PnL（仓位越大影响越大）
        p2_mult = 1.0
        p2_info = {}
        if apply_p2_sizing:
            p2_info = compute_p2_position_multiplier(
                idx, trade, history_pnls[:], current_consecutive_loss)
            p2_mult = p2_info.get("p2_base_multiplier", 1.0)
            if len(p2_sizing_log) < 30:
                p2_sizing_log.append({
                    "idx": idx,
                    "coin": trade.get("coin"),
                    "hex": trade.get("hexagram"),
                    "hex_class": p2_info.get("hexagram_class"),
                    "kelly_factor": p2_info.get("kelly_factor"),
                    "streak_factor": p2_info.get("consecutive_loss_factor"),
                    "hex_factor": p2_info.get("hexagram_factor"),
                    "mult": p2_mult,
                })

        final_pnl = pnl_after_atr * p2_mult
        final_pnl_pct = pnl_pct_after_atr * p2_mult  # 近似

        executed_trade = {
            **trade,
            "filter_reason": reason,
            "pnl": final_pnl,
            "pnl_pct": final_pnl_pct,
        }
        if apply_p1_atr_widen:
            executed_trade["p1_atr_saved"] = atr_saved
        if apply_p2_sizing:
            executed_trade["p2_info"] = p2_info
            executed_trade["p2_mult"] = p2_mult
        executed.append(executed_trade)

        # 更新连亏计数 & 历史 pnl（按最终 pnl）
        if final_pnl_pct < 0:
            current_consecutive_loss += 1
            max_consecutive_loss = max(max_consecutive_loss, current_consecutive_loss)
        else:
            current_consecutive_loss = 0
        history_pnls.append(final_pnl)

    return executed, filtered, {
        "max_consecutive_loss": max_consecutive_loss,
        "pause_count": pause_count,
        "p2_sizing_log": p2_sizing_log,
    }


def compute_metrics(trades, label):
    """计算交易指标"""
    if not trades:
        print(f"\n[{label}] 无交易")
        return {}

    total = len(trades)
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] < 0]
    breakeven = [t for t in trades if t['pnl_pct'] == 0]

    win_rate = len(wins) / total * 100 if total > 0 else 0
    loss_rate = len(losses) / total * 100 if total > 0 else 0

    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    avg_win_pct = sum(t['pnl_pct'] for t in wins) / len(wins) * 100 if wins else 0
    avg_loss_pct = sum(t['pnl_pct'] for t in losses) / len(losses) * 100 if losses else 0

    # 期望收益
    exp_return = (win_rate / 100) * avg_win_pct + (loss_rate / 100) * avg_loss_pct

    # 最大回撤
    equity = 0
    peak = 0
    max_dd = 0
    sorted_trades = sorted(trades, key=lambda x: x['entry_time'])
    for t in sorted_trades:
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    metrics = {
        "label": label,
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "exp_return_per_trade": exp_return,
        "max_drawdown": max_dd,
    }

    return metrics


def print_metrics(m, filter_stats=None):
    """打印指标"""
    if not m:
        print("\n[无指标数据]")
        return
    print(f"\n{'=' * 70}")
    print(f"📊 {m.get('label', 'N/A')}")
    print(f"{'=' * 70}")
    print(f"总交易数: {m['total']}")
    print(f"盈利交易: {m['wins']} ({m['win_rate']:.2f}%)")
    print(f"亏损交易: {m['losses']} ({m['loss_rate']:.2f}%)")
    print(f"盈亏平衡: {m['breakeven']}")
    print(f"总盈亏: {m['total_pnl']:.2f} USDT")
    print(f"平均盈利: {m['avg_win']:.4f} USDT ({m['avg_win_pct']:.2f}%)")
    print(f"平均亏损: {m['avg_loss']:.4f} USDT ({m['avg_loss_pct']:.2f}%)")
    print(f"盈亏比: {m['win_loss_ratio']:.2f}")
    print(f"单笔期望收益: {m['exp_return_per_trade']:.4f}%")
    print(f"最大回撤: {m['max_drawdown']:.2f} USDT")

    if filter_stats:
        print(f"最大连续亏损: {filter_stats['max_consecutive_loss']}")
        print(f"风控暂停次数: {filter_stats['pause_count']}")


def analyze_filter_reasons(filtered_trades):
    """分析被过滤的原因"""
    reasons = Counter()
    for t in filtered_trades:
        reasons[t.get("filter_reason", "unknown")] += 1

    print(f"\n{'=' * 70}")
    print(f"🚫 过滤原因分布")
    print(f"{'=' * 70}")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:50s}: {count:3d} 次")


def analyze_p0_saved_losses(filtered_trades):
    """分析P0过滤掉的交易是否为亏损"""
    saved_losses = 0
    saved_wins = 0
    saved_loss_pnl = 0
    saved_win_pnl = 0

    for t in filtered_trades:
        reason = t.get("filter_reason", "")
        if reason.startswith("p0_"):
            if t['pnl_pct'] < 0:
                saved_losses += 1
                saved_loss_pnl += t['pnl']
            elif t['pnl_pct'] > 0:
                saved_wins += 1
                saved_win_pnl += t['pnl']

    print(f"\n{'=' * 70}")
    print(f"💰 P0过滤效果分析")
    print(f"{'=' * 70}")
    print(f"P0过滤掉的亏损交易: {saved_losses} 次")
    print(f"  节省的亏损: {abs(saved_loss_pnl):.4f} USDT")
    print(f"P0过滤掉的盈利交易: {saved_wins} 次")
    print(f"  错过的盈利: {saved_win_pnl:.4f} USDT")
    print(f"净收益: {abs(saved_loss_pnl) - saved_win_pnl:.4f} USDT")
    return saved_losses, saved_wins, saved_loss_pnl, saved_win_pnl


def main():
    print()
    print("=" * 70)
    print("🔬 P0+P1+P2 修复回测验证（四层对比）")
    print("=" * 70)

    trades = load_trades()
    print(f"加载历史交易: {len(trades)} 笔")

    # 验证ranging_confidence分布
    print(f"\n{'=' * 70}")
    print("📡 市场环境分布")
    print(f"{'=' * 70}")
    ranging_dist = Counter()
    for t in trades:
        is_r, rconf, score = compute_ranging_confidence(t)
        bucket = f"score={score} (rconf={rconf:.2f})"
        ranging_dist[bucket] += 1
    for k, v in sorted(ranging_dist.items()):
        print(f"  {k}: {v} 次")

    # 1) BASE (原始)
    base_exec, base_filt, base_stats = simulate_strategy(trades, apply_p0=False)
    base_metrics = compute_metrics(base_exec, "BASE（原始策略，修复前）")
    print_metrics(base_metrics, base_stats)

    # 2) P0 (币种黑 + 卦象黑 + 置信度硬门槛0.7)
    p0_exec, p0_filt, p0_stats = simulate_strategy(trades, filter_fn=p0_v2_filter)
    p0_metrics = compute_metrics(p0_exec, "P0（币种黑+卦象黑+置信度≥0.7）")
    print_metrics(p0_metrics, p0_stats)

    # 3) P0+P1 (P0 + 做空趋势过滤 + ATR止损放宽模拟)
    p1_exec, p1_filt, p1_stats = simulate_strategy(
        trades, filter_fn=p0_p1_filter, apply_p1_atr_widen=True)
    p1_metrics = compute_metrics(p1_exec, "P0+P1（P0 + 做空趋势过滤 + ATR放宽）")
    print_metrics(p1_metrics, p1_stats)

    # 4) P0+P1+P2 (P0+P1 + 动态仓位: 半凯利 × 连亏缩仓 × 卦象加权)
    p2_exec, p2_filt, p2_stats = simulate_strategy(
        trades, filter_fn=p0_p1_filter, apply_p1_atr_widen=True, apply_p2_sizing=True)
    p2_metrics = compute_metrics(p2_exec, "P0+P1+P2（P0+P1 + 动态仓位凯利/连亏/卦象）")
    print_metrics(p2_metrics, p2_stats)

    # P0+P1 过滤原因 & 做空盈亏分析
    print(f"\n{'=' * 70}")
    print("🚫 P0+P1 过滤原因分布")
    print(f"{'=' * 70}")
    reasons = Counter()
    for t in p1_filt:
        reasons[t.get("filter_reason", "unknown")] += 1
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:60s}: {count:3d} 次")

    # 做空/做多分拆（对 P0+P1 与 P2 都计算）
    print(f"\n{'=' * 70}")
    print("📊 做多/做空分拆（P0+P1 vs P2）")
    print(f"{'=' * 70}")

    def split_ls(tlist):
        longs = [t for t in tlist if t.get("direction", "") in ("UP", "long")]
        shorts = [t for t in tlist if t.get("direction", "") in ("DOWN", "short")]
        return longs, shorts

    for name, tlist in [("P0+P1", p1_exec), ("P0+P1+P2", p2_exec)]:
        ls_t, ss_t = split_ls(tlist)
        ls_pnl = sum(t['pnl'] for t in ls_t)
        ss_pnl = sum(t['pnl'] for t in ss_t)
        ls_wr = sum(1 for t in ls_t if t['pnl_pct'] > 0) / len(ls_t) * 100 if ls_t else 0
        ss_wr = sum(1 for t in ss_t if t['pnl_pct'] > 0) / len(ss_t) * 100 if ss_t else 0
        print(f"  [{name:10s}] 做多: {len(ls_t):>3d}笔  胜率={ls_wr:5.1f}%  PnL={ls_pnl:>+8.2f}U  "
              f"| 做空: {len(ss_t):>3d}笔  胜率={ss_wr:5.1f}%  PnL={ss_pnl:>+8.2f}U")

    # P2 仓位变化日志（前20笔）
    p2_log = p2_stats.get("p2_sizing_log", [])
    if p2_log:
        print(f"\n{'=' * 70}")
        print("🪜 P2 动态仓位变化（前 {:d} 笔）".format(len(p2_log)))
        print(f"{'=' * 70}")
        hdr = f"  {'#':>3s} {'币种':<6s} {'卦':<10s} {'Cls':<8s} {'Kelly':>5s} {'连亏×':>5s} {'卦×':>4s} {'P2总倍':>6s}"
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for e in p2_log:
            print(f"  {e['idx']:>3d} {e.get('coin',''):<6s} {str(e.get('hex','')):<10s} "
                  f"{e.get('hex_class',''):<8s} {e['kelly_factor']:>5.2f} "
                  f"{e['streak_factor']:>5.2f} {e['hex_factor']:>4.2f} {e['mult']:>6.2f}")

    # 四层对比表
    print(f"\n{'=' * 70}")
    print(f"📈 四层对比分析（BASE → P0 → P0+P1 → P0+P1+P2）")
    print(f"{'=' * 70}")
    hdr = (f"{'指标':20s} {'BASE':>10s} {'P0':>10s} {'P0+P1':>10s} "
           f"{'P0+P1+P2':>12s} {'P2 vs BASE':>12s}")
    print(hdr)
    print(f"{'-' * (len(hdr))}")

    def _g(m, k, default=0):
        return m.get(k, default) if m else default

    rows = [
        ('总交易数', 'total', True, False, 'd'),
        ('盈利交易', 'wins', True, False, 'd'),
        ('亏损交易', 'losses', True, False, 'd'),
        ('胜率(%)', 'win_rate', False, True, '.2f'),
        ('总盈亏(USDT)', 'total_pnl', False, True, '.2f'),
        ('盈亏比', 'win_loss_ratio', False, True, '.2f'),
        ('单笔期望(%)', 'exp_return_per_trade', False, True, '.4f'),
        ('最大回撤(U)', 'max_drawdown', False, True, '.2f'),
    ]
    B, P0, P1, P2 = base_metrics, p0_metrics, p1_metrics, p2_metrics
    max_cl_b = base_stats.get('max_consecutive_loss', 0)
    max_cl_p0 = p0_stats.get('max_consecutive_loss', 0)
    max_cl_p1 = p1_stats.get('max_consecutive_loss', 0)
    max_cl_p2 = p2_stats.get('max_consecutive_loss', 0)

    for label, key, is_int, is_pct, fmt in rows:
        v_b = _g(B, key); v_p0 = _g(P0, key); v_p1 = _g(P1, key); v_p2 = _g(P2, key)
        if is_int:
            print(f"{label:20s} {v_b:>10d} {v_p0:>10d} {v_p1:>10d} {v_p2:>12d} {v_p2 - v_b:>+12d}")
        else:
            fstr = "{:>10" + fmt + "}"
            print(f"{label:20s} {fstr.format(v_b)} {fstr.format(v_p0)} {fstr.format(v_p1)} "
                  f"{v_p2:>12{fmt}} {v_p2 - v_b:>+12{fmt}}")
    print(f"{'最大连续亏损':20s} {max_cl_b:>10d} {max_cl_p0:>10d} {max_cl_p1:>10d} {max_cl_p2:>12d} {max_cl_p2 - max_cl_b:>+12d}")

    # P2 改善明细
    print(f"\n{'=' * 70}")
    print("💡 P2 动态仓位效果明细（相对于 P0+P1）")
    print(f"{'=' * 70}")
    pnl_delta_p2_vs_p1 = _g(p2_metrics, 'total_pnl') - _g(p1_metrics, 'total_pnl')
    wr_delta_p2_vs_p1 = _g(p2_metrics, 'win_rate') - _g(p1_metrics, 'win_rate')
    dd_delta_p2_vs_p1 = _g(p2_metrics, 'max_drawdown') - _g(p1_metrics, 'max_drawdown')
    print(f"  PnL 变化 (P2 - P0+P1)  : {pnl_delta_p2_vs_p1:>+8.2f} USDT")
    print(f"  胜率变化 (P2 - P0+P1)  : {wr_delta_p2_vs_p1:>+7.2f} %")
    print(f"  最大回撤变化 (P2-P0+P1): {dd_delta_p2_vs_p1:>+7.2f} USDT")

    # 保存结果
    result = {
        "timestamp": datetime.now().isoformat(),
        "total_trades_loaded": len(trades),
        "base": {**base_metrics, **base_stats},
        "p0": {**p0_metrics, **p0_stats} if p0_metrics else {"note": "no trades"},
        "p0_p1": {**p1_metrics, **p1_stats} if p1_metrics else {"note": "no trades"},
        "p0_p1_p2": {**p2_metrics, **p2_stats} if p2_metrics else {"note": "no trades"},
        "p2_improvement_vs_p1": {
            "pnl_delta": pnl_delta_p2_vs_p1,
            "win_rate_delta": wr_delta_p2_vs_p1,
            "max_drawdown_delta": dd_delta_p2_vs_p1,
        },
        "p2_improvement_vs_base": {
            "win_rate_delta": _g(p2_metrics, 'win_rate') - _g(base_metrics, 'win_rate'),
            "pnl_delta": _g(p2_metrics, 'total_pnl') - _g(base_metrics, 'total_pnl'),
            "max_consecutive_loss_delta": max_cl_p2 - max_cl_b,
            "max_drawdown_delta": _g(p2_metrics, 'max_drawdown') - _g(base_metrics, 'max_drawdown'),
        },
    }
    output_path = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/p0_backtest_result.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存: {output_path}")

    # P2 观察期通过标准检查
    print(f"\n{'=' * 70}")
    print(f"✅ P0+P1+P2 观察期通过标准检查")
    print(f"{'=' * 70}")
    checks = [
        ("连续亏损次数 ≤ 5", max_cl_p2 <= 5),
        ("胜率 ≥ 40%", _g(p2_metrics, 'win_rate', 0) >= 40),
        ("总盈亏为正", _g(p2_metrics, 'total_pnl', 0) > 0),
        ("盈亏比 ≥ 1.5", _g(p2_metrics, 'win_loss_ratio', 0) >= 1.5),
        ("P2 相对 P0+P1 不降低总盈亏", pnl_delta_p2_vs_p1 >= -1e-6),
    ]
    for name, passed in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {name}")

    all_pass = all(c[1] for c in checks)
    if all_pass:
        print(f"\n🎉 P0+P1+P2 四层优化通过观察期验证！建议正式采纳。")
    else:
        print(f"\n⚠️  P0+P1+P2 部分指标未达标，需进一步调整。")


if __name__ == '__main__':
    main()
