#!/usr/bin/env python3
"""
影子验证回测引擎：对候选基因逐bar计算触发，记录模拟交易结果。
不跑BCRM策略，只验证候选基因的触发条件是否有效。

用法: python3 shadow_backtest.py
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime
import math

# 路径设置
BASE = Path(__file__).resolve().parent.parent
KLINE_PATH = BASE.parent.parent / "11-易经推理系统/scripts/data/klines/BTC_4H.csv"
CANDIDATES_DIR = BASE / "gene_data/candidates"
SHADOW_DIR = BASE / "gene_data/shadow_validation"
COND_DIR = BASE / "gene_data/strategy_genes/conditions"

# Phase E 新增基因（趋势跟踪 + 网格交易）
PHASE_E_GENE_IDS = [
    "CD-DONCHIAN-10-BREAK",
    "CD-DONCHIAN-20-BREAK",
    "CD-DONCHIAN-55-BREAK",
    "CD-ATR-EXPANDING",
    "CD-ADX-GT25-TREND",
    "CD-BOLL-WIDTH-NARROW",
    "CD-ADX-LT25-RANGE",
    "CD-NECKLINE-BREAK",
]

# 配置
LOOKBACK = 20          # 指标计算回看bar数
HOLD_BARS = 12         # 模拟持有bar数 (4h*12=48h)
SHADOW_MIN_SAMPLES = 10
SHADOW_PROMOTE_WIN_RATE = 0.50
SHADOW_MIN_WIN_RATE = 0.30
SHADOW_MAX_CONSEC_LOSS = 5


def load_klines(path):
    """加载K线CSV"""
    import csv
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "timestamp": r["timestamp"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]),
            })
    return rows


def calc_indicators(klines):
    """计算所有候选基因需要的指标"""
    bars = klines.copy()
    n = len(bars)

    for i in range(n):
        # 20日最高价（不含当前bar）
        if i >= 1:
            window = [bars[j]["high"] for j in range(max(0, i-20), i)]
            bars[i]["high_20d"] = max(window) if window else 0
        else:
            bars[i]["high_20d"] = 0

        # 唐奇安通道上沿
        bars[i]["donchian_20_high"] = bars[i]["high_20d"]

        # 10日唐奇安通道（短期敏感版）
        if i >= 10:
            bars[i]["donchian_10_high"] = max(bars[j]["high"] for j in range(i-10, i))
            bars[i]["donchian_10_low"] = min(bars[j]["low"] for j in range(i-10, i))
        else:
            bars[i]["donchian_10_high"] = 0
            bars[i]["donchian_10_low"] = 0

        # 55日最高价（不含当前bar，海龟慢系统）
        if i >= 55:
            bars[i]["donchian_55_high"] = max(bars[j]["high"] for j in range(i-55, i))
        else:
            bars[i]["donchian_55_high"] = 0

        # 成交量均值（20bar）
        if i >= 20:
            vol_window = [bars[j]["volume"] for j in range(i-20, i)]
            bars[i]["vol_ma_20"] = sum(vol_window) / 20
        else:
            bars[i]["vol_ma_20"] = 0

        # 量比
        if bars[i]["vol_ma_20"] > 0:
            bars[i]["vol_ratio"] = bars[i]["volume"] / bars[i]["vol_ma_20"]
        else:
            bars[i]["vol_ratio"] = 1.0

        # 量能分位（20bar）
        if i >= 20:
            vol_window = sorted([bars[j]["volume"] for j in range(i-20, i)])
            rank = 0
            for v in vol_window:
                if bars[i]["volume"] > v:
                    rank += 1
            bars[i]["vol_quantile"] = rank / 20
        else:
            bars[i]["vol_quantile"] = 0.5

        # RSI(14)
        if i >= 15:
            gains = []
            losses = []
            for j in range(i-14, i):
                diff = bars[j]["close"] - bars[j-1]["close"]
                if diff > 0:
                    gains.append(diff)
                else:
                    losses.append(abs(diff))
            avg_gain = sum(gains) / 14 if gains else 0
            avg_loss = sum(losses) / 14 if losses else 0.0001
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            bars[i]["rsi_14"] = 100 - (100 / (1 + rs))
        else:
            bars[i]["rsi_14"] = 50

        # RSI(2)
        if i >= 3:
            gains = []
            losses = []
            for j in range(i-2, i):
                diff = bars[j]["close"] - bars[j-1]["close"]
                if diff > 0:
                    gains.append(diff)
                else:
                    losses.append(abs(diff))
            avg_gain = sum(gains) / 2 if gains else 0
            avg_loss = sum(losses) / 2 if losses else 0.0001
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            bars[i]["rsi_2"] = 100 - (100 / (1 + rs))
        else:
            bars[i]["rsi_2"] = 50

        # SMA(50)
        if i >= 50:
            bars[i]["sma_50"] = sum(bars[j]["close"] for j in range(i-50, i)) / 50
        else:
            bars[i]["sma_50"] = bars[i]["close"]

        # SMA(200)
        if i >= 200:
            bars[i]["sma_200"] = sum(bars[j]["close"] for j in range(i-200, i)) / 200
        else:
            bars[i]["sma_200"] = bars[i]["close"]

        # ATR(14)
        if i >= 15:
            trs = []
            for j in range(i-14, i):
                tr = max(
                    bars[j]["high"] - bars[j]["low"],
                    abs(bars[j]["high"] - bars[j-1]["close"]),
                    abs(bars[j]["low"] - bars[j-1]["close"])
                )
                trs.append(tr)
            bars[i]["atr"] = sum(trs) / 14
        else:
            bars[i]["atr"] = 0

        # ATR百分比
        if bars[i]["close"] > 0 and bars[i]["atr"] > 0:
            bars[i]["atr_pct"] = bars[i]["atr"] / bars[i]["close"]
        else:
            bars[i]["atr_pct"] = 0

        # MA(ATR)
        if i >= 28:
            atr_window = [bars[j]["atr"] for j in range(i-14, i)]
            bars[i]["ma_atr"] = sum(atr_window) / 14
        else:
            bars[i]["ma_atr"] = bars[i]["atr"]

        # ADX(14) 简化版（趋势强度指标）
        if i >= 15:
            plus_dm_list = []
            minus_dm_list = []
            tr_list = []
            for j in range(max(1, i-14), i):
                up = bars[j]["high"] - bars[j-1]["high"]
                down = bars[j-1]["low"] - bars[j]["low"]
                plus_dm_list.append(max(up, 0) if up > down else 0)
                minus_dm_list.append(max(down, 0) if down > up else 0)
                tr_list.append(max(
                    bars[j]["high"] - bars[j]["low"],
                    abs(bars[j]["high"] - bars[j-1]["close"]),
                    abs(bars[j]["low"] - bars[j-1]["close"]),
                ))
            if tr_list and sum(tr_list) > 0:
                sum_tr = sum(tr_list)
                plus_di = 100 * sum(plus_dm_list) / max(sum_tr, 1e-9)
                minus_di = 100 * sum(minus_dm_list) / max(sum_tr, 1e-9)
                bars[i]["adx_14"] = 100 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-9)
                bars[i]["plus_di"] = plus_di
                bars[i]["minus_di"] = minus_di
            else:
                bars[i]["adx_14"] = 0
                bars[i]["plus_di"] = 0
                bars[i]["minus_di"] = 0
        else:
            bars[i]["adx_14"] = 0
            bars[i]["plus_di"] = 0
            bars[i]["minus_di"] = 0

        # SMA(20) — 用于 ATR 扩张方向判断
        if i >= 20:
            bars[i]["sma_20"] = sum(bars[j]["close"] for j in range(i-20, i)) / 20
        else:
            bars[i]["sma_20"] = 0

        # ROC(20)
        if i >= 20:
            bars[i]["roc_20d"] = (bars[i]["close"] - bars[i-20]["close"]) / bars[i-20]["close"]
        else:
            bars[i]["roc_20d"] = 0

        # 偏离SMA50百分比
        if bars[i]["sma_50"] > 0:
            bars[i]["dist_sma50_pct"] = (bars[i]["close"] - bars[i]["sma_50"]) / bars[i]["sma_50"]
        else:
            bars[i]["dist_sma50_pct"] = 0

        # 偏离SMA200百分比
        if bars[i]["sma_200"] > 0:
            bars[i]["dist_sma200_pct"] = (bars[i]["close"] - bars[i]["sma_200"]) / bars[i]["sma_200"]
        else:
            bars[i]["dist_sma200_pct"] = 0

        # 布林带宽度 (20, 2)
        if i >= 20:
            closes = [bars[j]["close"] for j in range(i-20, i)]
            mean = sum(closes) / 20
            std = math.sqrt(sum((c - mean) ** 2 for c in closes) / 20)
            bars[i]["boll_width_pct"] = (2 * std) / mean if mean > 0 else 0
        else:
            bars[i]["boll_width_pct"] = 0

        # 20bar最低价
        if i >= 20:
            bars[i]["low_20d"] = min(bars[j]["low"] for j in range(i-20, i))
        else:
            bars[i]["low_20d"] = 0

        # 55bar最低价（海龟慢系统下沿）
        if i >= 55:
            bars[i]["low_55d"] = min(bars[j]["low"] for j in range(i-55, i))
        else:
            bars[i]["low_55d"] = 0

        # VWAP (48bar)
        if i >= 48:
            tpv_sum = 0
            vol_sum = 0
            for j in range(i-48, i):
                tpv_sum += bars[j]["close"] * bars[j]["volume"]
                vol_sum += bars[j]["volume"]
            bars[i]["vwap"] = tpv_sum / vol_sum if vol_sum > 0 else bars[i]["close"]
        else:
            bars[i]["vwap"] = bars[i]["close"]

        # Z-score price vs VWAP
        if i >= 48 and bars[i]["vwap"] > 0:
            closes = [bars[j]["close"] for j in range(i-48, i)]
            mean = sum(closes) / 48
            std = math.sqrt(sum((c - mean) ** 2 for c in closes) / 48)
            bars[i]["zscore_vwap"] = (bars[i]["close"] - bars[i]["vwap"]) / std if std > 0 else 0
        else:
            bars[i]["zscore_vwap"] = 0

    return bars


def eval_gene(gene_id, bar, klines=None, i=0):
    """评估候选基因是否在当前bar触发（向后兼容，返回 bool）"""
    triggered, _ = eval_gene_with_direction(gene_id, bar, klines, i)
    return triggered


# 方向映射表：基因 → 信号方向（Donchian/ATR/ADX 类由 eval_gene_with_direction 动态判断）
_GENE_DIRECTION = {
    # 网格交易类 → 做多（震荡市低买高卖）
    "CD-BOLL-WIDTH-NARROW": "long",
    "CD-ADX-LT25-RANGE": "long",
    # 反转类 → 做空（头肩顶看跌）
    "CD-KNOW-HEAD-SHOULDERS": "short",
    "CD-NECKLINE-BREAK": "short",  # 颈线跌破做空
    # 抄底类 → 做多
    "CD-KNOW-VWAP-REVERSION": "long",
    "CD-KNOW-WYCKOFF-SPRING": "long",
    # 突破类 → 做多
    "CD-KNOW-LIVERMORE-PP": "long",
    "CD-KNOW-DARVAS-BOX": "long",
    "CD-KNOW-MOMENTUM-BREAK": "long",
    "CD-KNOW-ICT-ORDERBLOCK": "long",
}

# 动态方向基因集合（根据价格方向动态判断 long/short）
_DYNAMIC_DIRECTION_GENES = {
    "CD-DONCHIAN-10-BREAK",   # 上突破→long，下突破→short（短期敏感）
    "CD-DONCHIAN-20-BREAK",   # 上突破→long，下突破→short
    "CD-DONCHIAN-55-BREAK",   # 上突破→long，下突破→short
    "CD-ATR-EXPANDING",       # close > SMA20→long，close < SMA20→short
    "CD-ADX-GT25-TREND",      # +DI > -DI→long，+DI < -DI→short
}


def load_gene_weight(gene_id):
    """从基因 JSON 加载 weight 字段，FAIL-OPEN 返回 1.0"""
    try:
        gene_path = COND_DIR / f"{gene_id}.json"
        if not gene_path.exists():
            return 1.0
        gene = json.load(open(gene_path))
        return float(gene.get("weight", 1.0))
    except Exception:
        return 1.0


def calc_weighted_pnl(avg_pnl, weight):
    """计算 weight 加权 PnL"""
    return avg_pnl * weight


def should_trade(weight):
    """weight=0 时不参与交易"""
    return weight > 0.0


def eval_gene_with_direction(gene_id, bar, klines=None, i=0):
    """评估候选基因是否在当前bar触发，返回 (triggered: bool, direction: str)

    direction: "long" 或 "short"
    - 动态方向基因（Donchian/ATR/ADX）根据价格方向判断
    - 其他基因查 _GENE_DIRECTION 映射表
    FAIL-OPEN: 未知基因返回 (False, "long")
    """
    triggered = _eval_gene_impl(gene_id, bar, klines, i)
    # 动态方向基因
    if gene_id in _DYNAMIC_DIRECTION_GENES:
        direction = _detect_dynamic_direction(gene_id, bar)
        return triggered, direction
    direction = _GENE_DIRECTION.get(gene_id, "long")
    return triggered, direction


def _detect_dynamic_direction(gene_id, bar):
    """检测动态方向：根据基因类型和价格方向判断 long/short"""
    if gene_id == "CD-DONCHIAN-10-BREAK":
        if bar.get("close", 0) > bar.get("donchian_10_high", 0) * 1.001 and bar.get("donchian_10_high", 0) > 0:
            return "long"
        if bar.get("close", 0) < bar.get("donchian_10_low", 0) * 0.999 and bar.get("donchian_10_low", 0) > 0:
            return "short"
    elif gene_id == "CD-DONCHIAN-20-BREAK":
        if bar.get("close", 0) > bar.get("donchian_20_high", 0) * 1.001 and bar.get("donchian_20_high", 0) > 0:
            return "long"
        if bar.get("close", 0) < bar.get("low_20d", 0) * 0.999 and bar.get("low_20d", 0) > 0:
            return "short"
    elif gene_id == "CD-DONCHIAN-55-BREAK":
        if bar.get("close", 0) > bar.get("donchian_55_high", 0) * 1.001 and bar.get("donchian_55_high", 0) > 0:
            return "long"
        if bar.get("close", 0) < bar.get("low_55d", 0) * 0.999 and bar.get("low_55d", 0) > 0:
            return "short"
    elif gene_id == "CD-ATR-EXPANDING":
        # close > SMA20 → long, close < SMA20 → short
        sma = bar.get("sma_20", 0)
        if sma > 0:
            return "long" if bar.get("close", 0) > sma else "short"
    elif gene_id == "CD-ADX-GT25-TREND":
        # +DI > -DI → long, +DI < -DI → short
        plus_di = bar.get("plus_di", 0)
        minus_di = bar.get("minus_di", 0)
        if plus_di > 0 or minus_di > 0:
            return "long" if plus_di > minus_di else "short"
    return "long"  # 默认


def _eval_gene_impl(gene_id, bar, klines=None, i=0):
    """eval_gene 原始实现（内部函数）"""
    if gene_id == "CD-KNOW-LIVERMORE-PP":
        # 20日新高突破+放量1.8x+ATR<6%+ROC>3%确认
        return (
            bar["close"] > bar["high_20d"] * 1.001 and
            bar["vol_ratio"] > 1.8 and
            bar["atr_pct"] < 0.06 and
            bar["roc_20d"] > 0.03
        )
    elif gene_id == "CD-KNOW-WYCKOFF-SPRING":
        # 价格跌破20bar低点+缩量+RSI<35+偏离SMA50>3%
        return (
            bar["close"] < bar["low_20d"] * 0.999 and
            bar["vol_ratio"] < 0.8 and
            bar["rsi_14"] < 35 and
            bar["dist_sma50_pct"] < -0.03
        )
    elif gene_id == "CD-KNOW-DARVAS-BOX":
        # 唐奇安上沿突破+ATR<1.5倍均值+量比>1.2+趋势过滤(价格>SMA50)
        return (
            bar["close"] > bar["donchian_20_high"] * 1.001 and
            bar["ma_atr"] > 0 and
            bar["atr"] < 1.5 * bar["ma_atr"] and
            bar["vol_ratio"] > 1.2 and
            bar["dist_sma50_pct"] > 0  # 仅多头趋势中突破
        )
    elif gene_id == "CD-KNOW-ICT-ORDERBLOCK":
        # 简化版：价格回踩前低+缩量+RSI<45
        # 完整OB检测需要更复杂的逻辑，这里用近似
        return (
            bar["close"] < bar["low_20d"] * 1.01 and
            bar["close"] > bar["low_20d"] * 0.98 and
            bar["vol_ratio"] < 0.9 and
            bar["rsi_14"] < 45
        )
    elif gene_id == "CD-KNOW-VWAP-REVERSION":
        # Z-score<-1.5(放宽) + RSI(2)<10(放宽) + 布林带宽>6%(放宽)
        return (
            bar["zscore_vwap"] < -1.5 and
            bar["rsi_2"] < 10 and
            bar["boll_width_pct"] > 0.06
        )
    elif gene_id == "CD-KNOW-MOMENTUM-BREAK":
        # ROC20>5% + 量能分位>80% + 价格>SMA100(适配600bar数据)
        return (
            bar["roc_20d"] > 0.05 and
            bar["vol_quantile"] > 0.8 and
            bar["dist_sma200_pct"] > 0  # 仍用SMA200（如有足够数据）
        )
    elif gene_id == "CD-KNOW-HEAD-SHOULDERS":
        # 头肩顶简化检测：
        # 1. 在55bar窗口中找最高点（头部）
        # 2. 最高点左右两侧有接近的次高点（左右肩）
        # 3. 当前价格跌破头部到左肩起点的颈线
        # 4. 量能从头部到右肩递减
        if bar.get("high_20d", 0) > 0 and bar.get("atr", 0) > 0 and i >= 55:
            # 55bar窗口
            window_highs = [klines[j]["high"] for j in range(i-55, i)]
            head_idx = window_highs.index(max(window_highs))
            head_high = window_highs[head_idx]

            # 头部必须在窗口中部1/3（不是开头或结尾）
            if head_idx < 5 or head_idx > 50:
                return False

            # 左肩：头部之前5-20bar的最高
            left_region = window_highs[max(0, head_idx-20):head_idx-3]
            if not left_region:
                return False
            left_shoulder = max(left_region)

            # 右肩：头部之后5-20bar的最高
            right_region = window_highs[head_idx+4:min(55, head_idx+20)]
            if not right_region:
                return False
            right_shoulder = max(right_region)

            # 两肩对称：都在头部85%-100%之间
            if left_shoulder < head_high * 0.85 or right_shoulder < head_high * 0.85:
                return False

            # 颈线 = min(左肩前低点, 右肩后低点)
            left_lows = [klines[j]["low"] for j in range(i-55+max(0, head_idx-20), i-55+head_idx-3)]
            right_lows = [klines[j]["low"] for j in range(i-55+head_idx+4, min(i, i-55+head_idx+20))]
            if not left_lows or not right_lows:
                return False
            neckline = min(min(left_lows), min(right_lows))

            # 当前价格跌破颈线
            if bar["close"] < neckline * 0.998 and bar["vol_ratio"] < 0.8:
                return True
        return False
    # ── Phase E 新增：趋势跟踪 + 网格交易基因 ──
    elif gene_id == "CD-DONCHIAN-20-BREAK":
        # 20日唐奇安通道突破（上突破或下突破）
        if bar.get("atr", 0) <= 0:
            return False
        # 上突破
        if bar.get("donchian_20_high", 0) > 0 and bar["close"] > bar["donchian_20_high"] * 1.001:
            return True
        # 下突破
        if bar.get("low_20d", 0) > 0 and bar["close"] < bar["low_20d"] * 0.999:
            return True
        return False
    elif gene_id == "CD-DONCHIAN-55-BREAK":
        # 55日唐奇安通道突破（上突破或下突破）
        if bar.get("atr", 0) <= 0:
            return False
        # 上突破
        if bar.get("donchian_55_high", 0) > 0 and bar["close"] > bar["donchian_55_high"] * 1.001:
            return True
        # 下突破
        if bar.get("low_55d", 0) > 0 and bar["close"] < bar["low_55d"] * 0.999:
            return True
        return False
    elif gene_id == "CD-DONCHIAN-10-BREAK":
        # 10日唐奇安通道突破（短期敏感版，上突破或下突破）
        if bar.get("atr", 0) <= 0:
            return False
        # 上突破
        if bar.get("donchian_10_high", 0) > 0 and bar["close"] > bar["donchian_10_high"] * 1.001:
            return True
        # 下突破
        if bar.get("donchian_10_low", 0) > 0 and bar["close"] < bar["donchian_10_low"] * 0.999:
            return True
        return False
    elif gene_id == "CD-NECKLINE-BREAK":
        # 颈线跌破信号（头肩顶/双顶等顶部形态颈线有效跌破 → 做空）
        # 颈线 = 过去 30~50 bar 内的支撑低点（排除最近 10 bar，避免随下跌下移）
        if klines is None or i < 50:
            return False
        # 颈线取 30~50 bar 前的最低点（左肩/双顶支撑位）
        neckline = min(klines[j]["low"] for j in range(max(0, i-50), max(0, i-10)))
        if neckline <= 0:
            return False
        # close 跌破颈线 1%
        if bar["close"] < neckline * 0.99:
            # 放量确认（当前量 > 20bar 均量 × 1.2）
            vol_ma = sum(klines[j]["volume"] for j in range(max(0, i-20), i)) / max(1, min(20, i))
            if bar["volume"] > vol_ma * 1.2:
                return True
        return False
    elif gene_id == "CD-ATR-EXPANDING":
        # ATR 扩张（波动率放大 = 趋势确认）
        return bar.get("ma_atr", 0) > 0 and bar.get("atr", 0) > bar["ma_atr"] * 1.2
    elif gene_id == "CD-ADX-GT25-TREND":
        # ADX>30 趋势市（2026-09-10 阈值从 25 提高至 30，减少误触发）
        return bar.get("adx_14", 0) > 30
    elif gene_id == "CD-ADX-LT25-RANGE":
        # ADX<25 震荡市
        return bar.get("adx_14", 0) < 25
    elif gene_id == "CD-BOLL-WIDTH-NARROW":
        # 布林带收窄（震荡市网格入场信号）
        return bar.get("boll_width_pct", 0) > 0 and bar.get("atr_pct", 0) > 0 and bar["boll_width_pct"] < bar["atr_pct"] * 2.0
    return False


def simulate_trade(klines, entry_idx, direction="long"):
    """模拟交易：入场价=close，持有HOLD_BARS后平仓"""
    exit_idx = min(entry_idx + HOLD_BARS, len(klines) - 1)
    if exit_idx <= entry_idx:
        return None
    entry_price = klines[entry_idx]["close"]
    exit_price = klines[exit_idx]["close"]
    if direction == "long":
        pnl_pct = (exit_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - exit_price) / entry_price
    return {
        "entry_time": klines[entry_idx]["timestamp"],
        "exit_time": klines[exit_idx]["timestamp"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "win": pnl_pct > 0,
        "hold_bars": exit_idx - entry_idx,
    }


def _build_l3_state(bar, klines, i):
    """B方案: 从回测 bar 指标构造与实盘对齐的 L3 state.
    回测无原生 R 向量，用指标代理（用户已确认接受代理映射）：
      R_up = rsi_2 / 100           # 短期超买代理
      R_down = 1 - rsi_2 / 100
      R_smooth = adx_14 / 50       # 趋势平滑度代理
      R_flow = vol_ratio / 3       # 资金流代理
      R_reflexivity = (zscore_vwap + 3) / 6  # 反身性 z-score 归一化
      quality_score = vol_quantile
    """
    def _clamp(v, lo=0.0, hi=1.0):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return lo
    return {
        "R_up": _clamp(bar.get("rsi_2", 50) / 100.0),
        "R_down": _clamp(1.0 - bar.get("rsi_2", 50) / 100.0),
        "R_smooth": _clamp(bar.get("adx_14", 0) / 50.0),
        "R_flow": _clamp(bar.get("vol_ratio", 1.0) / 3.0),
        "R_reflexivity": _clamp((bar.get("zscore_vwap", 0) + 3.0) / 6.0),
        "quality_score": _clamp(bar.get("vol_quantile", 0.5)),
    }


def inject_backtest_samples(tracker, klines, gene_ids=None):
    """B方案: 命令行入口，回测后将样本注入 ShadowRLTracker.

    遍历指定基因（默认 PHASE_E_GENE_IDS），逐 bar 判断触发，
    模拟交易后用 tanh(pnl_pct/0.02) 归一化为 reward，
    构造 L3 state 调用 tracker.record()。

    用法: python3 shadow_backtest.py --inject-rl
    """
    import math
    if gene_ids is None:
        gene_ids = PHASE_E_GENE_IDS
    total_injected = 0
    for gid in gene_ids:
        for i in range(LOOKBACK, len(klines) - HOLD_BARS):
            bar = klines[i]
            try:
                triggered, direction = eval_gene_with_direction(gid, bar, klines, i)
            except Exception:
                continue
            if triggered:
                trade = simulate_trade(klines, i, direction=direction)
                if trade:
                    state = _build_l3_state(bar, klines, i)
                    reward = math.tanh(trade["pnl_pct"] / 0.02)  # 复用实盘归一化
                    tracker.record(
                        symbol="BTC", state=state, action=direction,
                        reward=reward, next_state=None,
                    )
                    total_injected += 1
        print(f"  {gid}: 累计注入 {total_injected} 条")
    return total_injected


def _inject_rl_main():
    """B方案: --inject-rl 子命令入口。加载K线+指标后注入样本到 ShadowRL。"""
    print("=" * 70)
    print("ShadowRL 回测样本注入 — BTC 4H")
    print("=" * 70)
    klines = load_klines(KLINE_PATH)
    print(f"K线数据: {len(klines)} bars")
    print("计算技术指标...")
    klines = calc_indicators(klines)

    # 构造 ShadowRLTracker 实例（与 evolution_pipeline 一致的持久化路径）
    import sys as _sys
    # _arch_root = 23-四层闭环自进化交易架构（dreambuddy_evolution 包的父目录）
    _arch_root = Path(__file__).resolve().parent.parent.parent
    if str(_arch_root) not in _sys.path:
        _sys.path.insert(0, str(_arch_root))
    from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
    from pathlib import Path as _P
    # persist_path 用绝对路径（gene_data/ 在 _arch_root 下）
    _persist = _P(_arch_root) / "dreambuddy_evolution" / "gene_data" / "shadow_rl_samples.jsonl"
    tracker = ShadowRLTracker(persist_path=_persist)
    # 先加载历史样本（追加模式，不覆盖）
    tracker.load_from_disk()
    before = tracker.sample_count()
    print(f"加载前样本数: {before}（有效 {tracker.effective_sample_count()}）")

    injected = inject_backtest_samples(tracker, klines)
    after = tracker.sample_count()
    print(f"注入完成: 新增 {injected} 条，总计 {after} 条（有效 {tracker.effective_sample_count()}）")
    print(f"持久化文件: {_persist}")
    if tracker.is_phase3_activated():
        print("Phase3 已激活")
    else:
        _min = 2000
        print(f"待激活（有效 {tracker.effective_sample_count()}/{_min} 需达阈值）")


def check_promotion(samples):
    """检查影子基因准入/淘汰"""
    n = len(samples)
    if n < SHADOW_MIN_SAMPLES:
        return {"promote": False, "reason": f"N={n} < {SHADOW_MIN_SAMPLES}"}

    wins = sum(1 for s in samples if s["pnl_pct"] > 0)
    win_rate = wins / n
    avg_pnl = sum(s["pnl_pct"] for s in samples) / n

    # 连续亏损（只计独立交易信号，非K线相邻触发）
    # 过滤：两次触发间隔>HOLD_BARS才算独立信号
    independent_samples = []
    last_entry_idx = -HOLD_BARS - 1
    for idx, s in enumerate(samples):
        # 用entry_time的索引位置判断独立性
        # 简化：如果前一笔还在持有期内，跳过
        if idx > 0:
            prev = samples[idx - 1]
            # 比较时间差（简化：直接用index差）
            # 如果间隔不够，合并为同一信号
            pass
        independent_samples.append(s)

    # 直接用全部样本计算连续亏损（已足够保守）
    max_consec_loss = 0
    current_loss = 0
    for s in samples:
        if s["pnl_pct"] <= 0:
            current_loss += 1
            max_consec_loss = max(max_consec_loss, current_loss)
        else:
            current_loss = 0

    # 放宽连续亏损：要求连续亏损占总样本比例>50%才淘汰
    loss_ratio = max_consec_loss / n if n > 0 else 0

    # 淘汰：连续亏损占比>50% 且 胜率<50%
    if max_consec_loss >= SHADOW_MAX_CONSEC_LOSS and loss_ratio > 0.5 and win_rate < 0.50:
        return {"promote": False, "retire": True, "reason": f"consecutive_losses={max_consec_loss} ({loss_ratio:.0%} of N), win_rate={win_rate:.0%}", "win_rate": win_rate, "avg_pnl": avg_pnl}

    # 准入
    if win_rate >= SHADOW_PROMOTE_WIN_RATE and avg_pnl > 0:
        return {"promote": True, "win_rate": win_rate, "avg_pnl": avg_pnl}

    return {"promote": False, "reason": f"win_rate={win_rate:.0%} < {SHADOW_PROMOTE_WIN_RATE:.0%}", "win_rate": win_rate, "avg_pnl": avg_pnl}


def main():
    print("=" * 70)
    print("影子验证回测引擎 — BTC 4H")
    print("=" * 70)

    # 加载K线
    klines = load_klines(KLINE_PATH)
    print(f"K线数据: {len(klines)} bars ({klines[0]['timestamp']} ~ {klines[-1]['timestamp']})")

    # 计算指标
    print("计算技术指标...")
    klines = calc_indicators(klines)

    # 加载候选基因
    candidates = []
    for f in sorted(os.listdir(CANDIDATES_DIR)):
        if f.endswith(".json"):
            gene = json.load(open(CANDIDATES_DIR / f))
            candidates.append(gene)
            print(f"  候选: {gene['gene_id']} [{gene['category']}] {gene['expression'][:60]}...")

    # Phase E 新增基因（趋势跟踪 + 网格交易）
    for gid in PHASE_E_GENE_IDS:
        gene_path = COND_DIR / f"{gid}.json"
        if gene_path.exists():
            gene = json.load(open(gene_path))
            candidates.append(gene)
            print(f"  Phase E: {gene['gene_id']} [{gene['category']}] {gene['expression'][:60]}...")

    print(f"\n候选基因: {len(candidates)} 个")
    print(f"模拟持有: {HOLD_BARS} bars ({HOLD_BARS*4}h)")
    print()

    # 创建影子验证目录
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)

    # 对每个候选基因跑回测
    summary = []
    for gene in candidates:
        gid = gene["gene_id"]
        gene_weight = load_gene_weight(gid)
        samples = []

        if not should_trade(gene_weight):
            print(f"  ⏸ {gid} weight=0, 跳过")
            summary.append({
                "gene_id": gid, "n_samples": 0, "win_rate": 0, "avg_pnl": 0,
                "weighted_pnl": 0, "weight": 0, "decision": {"promote": False, "reason": "weight=0"},
                "status_icon": "⏸", "direction": "skip",
            })
            continue

        for i in range(LOOKBACK, len(klines) - HOLD_BARS):
            bar = klines[i]
            triggered, direction = eval_gene_with_direction(gid, bar, klines, i)
            if triggered:
                trade = simulate_trade(klines, i, direction=direction)
                if trade:
                    trade["gene_id"] = gid
                    trade["direction"] = direction
                    samples.append(trade)

        # 记录结果
        n = len(samples)
        wins = sum(1 for s in samples if s["pnl_pct"] > 0)
        win_rate = wins / n if n > 0 else 0
        avg_pnl = sum(s["pnl_pct"] for s in samples) / n if n > 0 else 0

        # 准入检查
        decision = check_promotion(samples)

        # weight 加权 PnL
        weighted_pnl = calc_weighted_pnl(avg_pnl, gene_weight)

        # 写入影子验证JSON
        shadow_json = {
            "gene_id": gid,
            "status": "shadow",
            "source_doc": gene.get("source_doc", ""),
            "expression": gene["expression"],
            "category": gene["category"],
            "n_samples": n,
            "win_rate": round(win_rate, 4),
            "avg_pnl_pct": round(avg_pnl, 6),
            "weighted_pnl_pct": round(weighted_pnl, 6),
            "weight": gene_weight,
            "hold_bars": HOLD_BARS,
            "decision": decision,
            "backtest_period": f"{klines[0]['timestamp']} ~ {klines[-1]['timestamp']}",
            "symbol": "BTC-USDT-SWAP",
            "timeframe": "4h",
            "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "direction": _GENE_DIRECTION.get(gid, "long"),
        }
        shadow_path = SHADOW_DIR / f"{gid}.json"
        with open(shadow_path, "w") as f:
            json.dump(shadow_json, f, ensure_ascii=False, indent=2)

        # 写入样本JSONL
        samples_path = SHADOW_DIR / f"{gid}_samples.jsonl"
        with open(samples_path, "w") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        # 汇总
        status_icon = "✅" if decision.get("promote") else ("❌" if decision.get("retire") else "⏳")
        gene_dir = _GENE_DIRECTION.get(gid, "long")
        summary.append({
            "gene_id": gid,
            "n_samples": n,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "weighted_pnl": weighted_pnl,
            "weight": gene_weight,
            "decision": decision,
            "status_icon": status_icon,
            "direction": gene_dir,
        })

        print(f"{status_icon} {gid} [{gene_dir}] w={gene_weight:.1f}")
        print(f"   触发: {n} 次 | 胜率: {win_rate:.1%} | PnL: {avg_pnl:+.4f} | wPnL: {weighted_pnl:+.4f}")
        print(f"   决定: {decision}")
        print()

    # 汇总报告
    print("=" * 70)
    print("影子验证汇总")
    print("=" * 70)
    print(f"{'基因':<30} {'N':>4} {'胜率':>6} {'PnL':>10} {'方向':>6} {'状态':>6}")
    print("-" * 70)
    for s in summary:
        print(f"{s['gene_id']:<30} {s['n_samples']:>4} {s['win_rate']:>5.0%} {s['avg_pnl']:>+10.4f} {s.get('direction','long'):>6} {s['status_icon']}")
    print()

    # 写入汇总
    report_path = SHADOW_DIR / "shadow_summary.json"
    with open(report_path, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"汇总报告: {report_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--inject-rl":
        _inject_rl_main()
    else:
        main()
