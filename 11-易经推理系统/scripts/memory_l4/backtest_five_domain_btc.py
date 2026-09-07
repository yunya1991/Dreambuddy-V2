#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC 长周期数据回测五计庙算（FiveDomainHeuristicScorer）实际水平
数据源：OKX BTC-USDT-SWAP 日K（300根，约10个月：2025-11-01 → 2026-08-27）
五维代理构造：基于BTC价格序列派生可量化的道/天/地/将/法分数
评估维度：
  1. war_state 命中率：FREEZE/COOLDOWN/ALLOW 时后市涨跌分布
  2. 仓位映射正确性：各档位累计盈亏
  3. style_mask 匹配度：不同策略模式与后市波动率/趋势的匹配
  4. 维度否决合理性：否决触发后的实际风险暴露
  5. 跨类约束有效性：mult_mode 调整后的风险收益
"""
import sys, os
from pathlib import Path
PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ))
os.chdir(str(PROJ))

import numpy as np
import json
from collections import defaultdict, Counter
from dataclasses import asdict

from scripts.memory_l4.yijing_trainer import _load_kline_from_okx
from scripts.memory_l4.five_domain_scorer import FiveDomainHeuristicScorer


# ================================================================
# Step 0: 获取 BTC 日K（300 根 ≈ 10 个月）
# ================================================================
print("=" * 78)
print("[Step 0] 获取 BTC-USDT-SWAP 日K线数据")
klines_raw = _load_kline_from_okx(inst_id="BTC-USDT-SWAP", bar="1D", limit=300)
# OKX 返回是最新在前 → 时间正序
klines_raw = list(reversed(klines_raw))
print(f"  数据范围: {klines_raw[0]['ts_str']} → {klines_raw[-1]['ts_str']}")
print(f"  K线根数: {len(klines_raw)}")

closes = np.array([float(k["c"]) for k in klines_raw])
highs  = np.array([float(k["h"]) for k in klines_raw])
lows   = np.array([float(k["l"]) for k in klines_raw])
vols   = np.array([float(k["v"]) for k in klines_raw])
n = len(closes)

# 派生特征（最小Warmup=120根≈4个月）
def sma(arr, w):
    out = np.full(len(arr), np.nan)
    for i in range(w-1, len(arr)):
        out[i] = np.mean(arr[i-w+1:i+1])
    return out

def std(arr, w):
    out = np.full(len(arr), np.nan)
    for i in range(w-1, len(arr)):
        out[i] = np.std(arr[i-w+1:i+1])
    return out

ret_1d = np.zeros(n); ret_1d[1:] = (closes[1:]/closes[:-1]) - 1
ret_7d = np.full(n, np.nan); ret_7d[7:] = (closes[7:]/closes[:-7]) - 1
ret_30d = np.full(n, np.nan); ret_30d[30:] = (closes[30:]/closes[:-30]) - 1
ret_90d = np.full(n, np.nan); ret_90d[90:] = (closes[90:]/closes[:-90]) - 1

ma20  = sma(closes, 20)
ma50  = sma(closes, 50)
ma90  = sma(closes, 90)
vol20 = std(ret_1d, 20)
vol90 = std(ret_1d, 90)
atr14 = np.zeros(n)
for i in range(1, n):
    tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    if i == 1: atr14[i] = tr
    else: atr14[i] = (atr14[i-1]*13 + tr)/14
atr14_pct = atr14 / np.maximum(closes, 1e-8)

ma200 = sma(closes, 200)
print(f"  Warmup 完成后起始索引: {120} ({klines_raw[120]['ts_str']})")

# ================================================================
# Step 1: 五维代理分数（基于 BTC 价格序列派生）
#
# 设计思路：用可量化的市场特征映射五维 0-100 分，力求合理中立
#   道 dao: 方向一致性 = 长期趋势 + 资金流代理(量价背离系数)
#   天 tian: 宏观周期代理 = 波动率周期 + 季节性（近30日绝对收益）
#   地  di : 价格结构 = MA200距离 + ATR相对位 + 回撤深度
#   将  jiang: 数据支撑/决策质量 = 信号清晰度（趋势/震荡区分度）
#   法  fa : 纪律/数据一致性 = 滚动收益稳定性（夏普）
# ================================================================
WARMUP = 120

def score_linear(x, lo, hi, invert=False):
    """线性映射 x ∈ [lo, hi] → [0, 100]"""
    v = (x - lo) / max(hi - lo, 1e-12)
    v = np.clip(v, 0.0, 1.0) * 100.0
    return 100.0 - v if invert else v

def compute_five_scores(i):
    """基于索引 i 的 BTC 历史数据，计算五维 0-100 分数"""
    # ---- 道 dao: 方向一致性 ----
    # 长期方向 + 量价背离（ret90 作为趋势代理）
    trend_long = ret_90d[i] if not np.isnan(ret_90d[i]) else 0
    price_above_ma200 = (closes[i] / ma200[i] - 1) * 100 if not np.isnan(ma200[i]) else 0
    # 量价一致性：上涨放量 vs 下跌放量
    if i >= 30:
        up_days = ret_1d[i-29:i+1] > 0
        down_days = ~up_days
        vol_up = vols[i-29:i+1][up_days].mean() if up_days.any() else 0
        vol_dn = vols[i-29:i+1][down_days].mean() if down_days.any() else 0
        vol_ratio = vol_up / max(vol_dn, 1e-8)
    else:
        vol_ratio = 1.0
    dao_raw = trend_long * 5 + price_above_ma200 * 0.8 + (vol_ratio - 1.0) * 15
    dao = int(np.clip(50 + dao_raw, 0, 100))

    # ---- 天 tian: 波动周期 ----
    # 低波动→好(高)，极高波动→坏(低)
    vol_rel = (vol20[i] / max(vol90[i], 1e-12) - 1.0) * 100 if not np.isnan(vol90[i]) and vol90[i] > 0 else 0
    # 近30日绝对收益：大涨大跌都不稳定
    r30 = ret_30d[i] if not np.isnan(ret_30d[i]) else 0
    sharpness = 100 - min(abs(r30)*300, 100)  # 近30日波动越平缓越好
    tian_raw = -vol_rel + sharpness - 50
    tian = int(np.clip(50 + tian_raw * 0.3, 0, 100))

    # ---- 地 di: 价格结构 ----
    dist_ma200 = 0
    if not np.isnan(ma200[i]) and ma200[i] > 0:
        d = (closes[i] - ma200[i]) / ma200[i] * 100  # -20%~+40%
        # 适度偏离好，极高/极低偏离都差
        dist_ma200 = score_linear(d, -30, 30) * (1 - (abs(d) - 20)/10 if abs(d) > 20 else 1)
    # ATR 相对位：适中最好
    atr_score = score_linear(atr14_pct[i], 0.0, 0.1, invert=True) if atr14_pct[i] > 0 else 50
    # 回撤深度：相对于90日高点的回撤
    if i >= 30:
        hh = highs[max(0,i-89):i+1].max()
        dd = (closes[i] / hh - 1) * 100
        dd_score = score_linear(dd, -40, 0)
    else:
        dd_score = 50
    di = int(np.clip((dist_ma200 + atr_score + dd_score) / 3, 0, 100))

    # ---- 将 jiang: 决策质量 / 信号清晰度 ----
    # 趋势存在度：ma20/ma50/ma90 同向性 + ATR足够大
    trend_consist = 0
    if not any(np.isnan([ma20[i], ma50[i], ma90[i]])):
        r20_50 = ma20[i] / ma50[i] - 1
        r50_90 = ma50[i] / ma90[i] - 1
        # 同向性：都是正或都是负，且差不过大
        if (r20_50 * r50_90) > 0:
            trend_consist = 50 + min(abs(r20_50 + r50_90) * 1000, 50)
        else:
            trend_consist = 50 - min(abs(r20_50 - r50_90) * 500, 50)
    # 避免ATR过小导致假信号
    signal_clear = min(max(atr14_pct[i] / 0.03, 0), 1) * 100
    jiang = int(np.clip((trend_consist * 0.6 + signal_clear * 0.4), 0, 100))

    # ---- 法 fa: 纪律/收益稳定性 ----
    # 滚动30日夏普近似（无风险利率=0）
    if i >= 30:
        r30_a = ret_1d[i-29:i+1]
        mu, sig = r30_a.mean(), r30_a.std()
        sharpe = mu / max(sig, 1e-12) * np.sqrt(365)
    else:
        sharpe = 0
    fa_raw = sharpe * 20  # 夏普0=50, 1=70, -1=30
    # 胜率：近30日上涨日占比
    if i >= 30:
        win_rate = (ret_1d[i-29:i+1] > 0).mean() * 100
    else:
        win_rate = 50
    fa = int(np.clip((50 + fa_raw) * 0.5 + win_rate * 0.5, 0, 100))

    return {"dao": dao, "tian": tian, "di": di, "jiang": jiang, "fa": fa}


# ================================================================
# Step 2: 初始化 Scorer + 配置 7 子开关全开
# ================================================================
scorer = FiveDomainHeuristicScorer(enable=True)

class FakeCfg:
    enable_five_domain_war_state = True
    enable_five_domain_style_mask = True
    enable_five_domain_position_cap = True
    enable_five_domain_cross_asset = True
    enable_five_domain_dimensio = True
    enable_five_domain_front_layer_band = True
    enable_five_domain_ol = True

scorer._cfg = FakeCfg()

ASSETS = ["crypto_usdt", "us_stock", "precious_metal"]
# 回测只评估 crypto_usdt，us_stock/precious_metal 复用同一份（因为只有BTC数据）
# 但我们做差异化：crypto 用原始值，us/precious 加 -5/ -10 偏移（模拟美股黄金相对不同景气）
OFFSET = {"crypto_usdt": 0, "us_stock": -5, "precious_metal": -10}

records = []  # 每根K一条记录
print("=" * 78)
print(f"[Step 1-2] 逐K线计算五维分数 + Scorer决策（i={WARMUP}..{n-1}）")

for i in range(WARMUP, n):
    s_raw = compute_five_scores(i)
    prices = {
        "ts": klines_raw[i]["ts"],
        "ts_str": klines_raw[i]["ts_str"],
        "close": float(closes[i]),
        "ret_1d": float(ret_1d[i]) if not np.isnan(ret_1d[i]) else 0.0,
        "ret_7d": float(ret_7d[i+7]) if i+7 < n and not np.isnan(ret_7d[i+7]) else float("nan"),
        "ret_30d": float(ret_30d[i+30]) if i+30 < n and not np.isnan(ret_30d[i+30]) else float("nan"),
        "vol20": float(vol20[i]) if not np.isnan(vol20[i]) else 0.0,
    }
    # 构建三类资产分数
    scores = {}
    for cls in ASSETS:
        off = OFFSET[cls]
        scores[cls] = {k: max(0, min(100, int(v + off))) for k, v in s_raw.items()}

    state = scorer._apply_decision_rules(scores)
    # 三类资产的 crypto 决策
    ws = state.war_state["crypto_usdt"]
    cap = state.aggregate_position_cap_pct["crypto_usdt"]
    mult = state.position_mult["crypto_usdt"]
    cm  = state.cross_asset_multiplier["crypto_usdt"]
    mask = state.allowed_style_mask["crypto_usdt"]
    veto = state.dimension_veto_flags["crypto_usdt"]
    # 映射总权重分（用 scorer 内部函数保证口径一致）
    s = scores["crypto_usdt"]
    try:
        total_wt = scorer._weighted_total(s, "crypto_usdt")
    except Exception:
        total_wt = (s["dao"]*0.3 + s["tian"]*0.15 + s["di"]*0.25 + s["jiang"]*0.15 + s["fa"]*0.15)

    rec = {
        **prices,
        **{f"s_{k}": v for k, v in scores["crypto_usdt"].items()},
        "total_raw": sum(scores["crypto_usdt"].values()),
        "total_wt": round(total_wt, 2),
        "war_state": ws,
        "cap": cap,
        "mult_position": mult,       # 维度否决乘数
        "mult_crossasset": cm,       # 跨类约束乘数
        "effective_cap": cap * mult * cm,
        **{f"mask_{k}": v for k, v in mask.items()},
        **{f"veto_{k}": v for k, v in veto.items()},
    }
    records.append(rec)

print(f"  共记录 {len(records)} 条")

# ================================================================
# Step 3: 回测评估
# ================================================================
print("=" * 78)
print("[Step 3] 回测评估")
print("-" * 78)

# 3.1 分数分布
score_arr = np.array([r["total_wt"] for r in records])
bins = [0, 50, 60, 75, 85, 100]
labels_bin = ["<50极差", "50-60防守", "60-74防御", "75-84进攻", "≥85猛攻"]
print("\n【3.1 五维加权总分分布】")
for bi, lab in enumerate(labels_bin):
    lo, hi = bins[bi], bins[bi+1]
    cnt = ((score_arr >= lo) & (score_arr < hi)).sum() if bi < len(labels_bin)-1 else (score_arr >= lo).sum()
    pct = cnt/len(score_arr)*100
    print(f"  {lab:8s}: {cnt:4d} 根 ({pct:5.1f}%)")

# 3.2 war_state vs 后市收益
print("\n【3.2 war_state vs 后市收益命中率】")
print(f"  {'状态':8s} {'样本':>6s} {'7日上涨占比':>10s} {'30日上涨占比':>11s} {'7日均值%':>9s} {'30日均值%':>10s}")
for ws_name in ["FREEZE", "COOLDOWN", "ALLOW"]:
    rs = [r for r in records if r["war_state"] == ws_name]
    if not rs:
        continue
    r7 = [r["ret_7d"] for r in rs if not np.isnan(r["ret_7d"])]
    r30 = [r["ret_30d"] for r in rs if not np.isnan(r["ret_30d"])]
    up7 = sum(1 for x in r7 if x > 0) / max(len(r7),1) * 100
    up30 = sum(1 for x in r30 if x > 0) / max(len(r30),1) * 100
    m7 = np.mean(r7)*100 if r7 else 0
    m30 = np.mean(r30)*100 if r30 else 0
    print(f"  {ws_name:8s} {len(rs):6d} {up7:9.1f}% {up30:10.1f}% {m7:8.2f}% {m30:9.2f}%")

# 3.3 档位 vs 累计收益（有效仓位cap模拟：买入并持有N日）
print("\n【3.3 档位映射 vs 有效仓位收益】")
print(f"  模拟：当日收盘开仓BTC多单（按effective_cap），7日后平仓，无手续费")
cum_ret_map = defaultdict(list)
for r in records:
    if np.isnan(r["ret_7d"]): continue
    # 按档位标签
    t = r["total_wt"]
    if t < 50: bin_lab = "<50极差"
    elif t < 60: bin_lab = "50-60防守"
    elif t < 75: bin_lab = "60-74防御"
    elif t < 85: bin_lab = "75-84进攻"
    else: bin_lab = "≥85猛攻"
    # 仓位比例下的收益（单利）
    sim_ret = r["ret_7d"] * r["effective_cap"]
    cum_ret_map[bin_lab].append(sim_ret)
    cum_ret_map["ALL"].append(r["ret_7d"])

print(f"  {'档位':8s} {'交易':>5s} {'胜率':>7s} {'平均单利%':>10s} {'累计单利%':>10s} {'夏普似值':>8s}")
for lab in ["<50极差", "50-60防守", "60-74防御", "75-84进攻", "≥85猛攻", "ALL"]:
    lst = cum_ret_map.get(lab, [])
    if not lst:
        continue
    arr = np.array(lst) * 100
    wr = (arr > 0).mean() * 100
    m = arr.mean()
    s = arr.std()
    sharpe_like = m / max(s, 1e-9) * np.sqrt(365/7)
    cum = arr.sum()
    print(f"  {lab:8s} {len(lst):5d} {wr:6.1f}% {m:9.3f}% {cum:9.2f}% {sharpe_like:7.2f}")

# 3.4 style_mask vs 后市波动率匹配
print("\n【3.4 style_mask 策略匹配质量】")
print(f"  评估：mean_revert=True 时 后市是否真的震荡（7日低波动）；trend=True 时是否真的趋势")
# 构建每根K的"未来7日波动率"（相对基准）
for idx, r in enumerate(records):
    j = WARMUP + idx
    if j+7 < n:
        fut_ret = ret_1d[j+1:j+8]
        vol_f7 = fut_ret.std()
        r["vol_f7_pct"] = float(vol_f7) * 100
        # 震荡判定：未来7日波动低于vol20*0.8 且 绝对收益<3%
        if not np.isnan(vol20[j]) and vol20[j] > 0:
            r["is_range_f7"] = bool(vol_f7 < vol20[j]*0.8 and abs(r.get("ret_7d",0)) < 0.03)
        else:
            r["is_range_f7"] = False
        # 趋势判定：未来7日绝对收益>5% 且 方向一致性（多数日同向）
        r["is_trend_f7"] = bool(abs(r.get("ret_7d",0)) > 0.05 and (fut_ret>0).mean() > 0.7)
    else:
        r["vol_f7_pct"] = float("nan")
        r["is_range_f7"] = False
        r["is_trend_f7"] = False

rows_eval = [r for r in records if not np.isnan(r["vol_f7_pct"])]

def eval_mask(key_mask, attr_should):
    n_yes = sum(1 for r in rows_eval if r.get(key_mask) is True)
    n_no  = sum(1 for r in rows_eval if r.get(key_mask) is False)
    if n_yes > 0:
        yes_matched = sum(1 for r in rows_eval if r.get(key_mask) is True and r.get(attr_should)) / n_yes * 100
    else:
        yes_matched = 0.0
    if n_no > 0:
        no_notmatched = sum(1 for r in rows_eval if r.get(key_mask) is False and r.get(attr_should)) / n_no * 100
    else:
        no_notmatched = 0.0
    return n_yes, n_no, yes_matched, no_notmatched

n1, n0, m1, m0 = eval_mask("mask_mean_revert", "is_range_f7")
print(f"  mean_revert=True: {n1:4d}次 → 后市震荡匹配率={m1:.1f}%")
print(f"  mean_revert=False: {n0:4d}次 → 后市震荡占比={m0:.1f}%")
n1, n0, m1, m0 = eval_mask("mask_trend_follow", "is_trend_f7")
print(f"  trend_follow=True: {n1:4d}次 → 后市趋势匹配率={m1:.1f}%")
print(f"  trend_follow=False: {n0:4d}次 → 后市趋势占比={m0:.1f}%")
n1, n0, m1, m0 = eval_mask("mask_volatility", "is_trend_f7")  # volatility 对应高波动
vols_true = [r["vol_f7_pct"] for r in rows_eval if r.get("mask_volatility") is True]
vols_false = [r["vol_f7_pct"] for r in rows_eval if r.get("mask_volatility") is False]
print(f"  volatility=True: {len(vols_true):4d}次 → 后市7日波动率均值={np.mean(vols_true)*100:.3f}%" if vols_true else "  volatility=True: 0次")
print(f"  volatility=False: {len(vols_false):4d}次 → 后市7日波动率均值={np.mean(vols_false)*100:.3f}%" if vols_false else "  volatility=False: 0次")

# 3.5 维度否决合理性
print("\n【3.5 维度否决触发情况】")
for veto_key, veto_name in [
    ("veto_dao_jv_fou_jue","道<40否决(≤30%)"),
    ("veto_jiang_xiao_40","将<40否决(≤30%)"),
    ("veto_fa_xiao_40","法<40否决(不开新仓)"),
    ("veto_di_tian_shuang_cha","地天双差(只对冲/空仓)"),
]:
    n_hit = sum(1 for r in records if r.get(veto_key))
    if n_hit == 0:
        print(f"  {veto_name:24s}: {n_hit:4d} 次")
        continue
    hit_rows = [r for r in records if r.get(veto_key)]
    # 否决触发后7日/30日收益
    r7 = [r["ret_7d"] for r in hit_rows if not np.isnan(r["ret_7d"])]
    r30 = [r["ret_30d"] for r in hit_rows if not np.isnan(r["ret_30d"])]
    m7 = np.mean(r7)*100 if r7 else 0
    m30 = np.mean(r30)*100 if r30 else 0
    # 全基准
    all_r7 = np.array([r["ret_7d"] for r in records if not np.isnan(r["ret_7d"])])
    all_m7 = all_r7.mean()*100 if len(all_r7) else 0
    print(f"  {veto_name:24s}: {n_hit:4d}次 → 7日均值{m7:+.2f}% (基准{all_m7:+.2f}%) → {'有效' if m7 < all_m7 else '无效'}")

# 3.6 总分预测未来涨跌的 Spearman 相关性
rows_f7 = [r for r in records if not np.isnan(r["ret_7d"])]
scores = np.array([r["total_wt"] for r in rows_f7])
rets7 = np.array([r["ret_7d"] for r in rows_f7])
from scipy.stats import spearmanr
spearman_r, pval = spearmanr(scores, rets7) if len(scores) > 5 else (0,1)
print(f"\n【3.6 总分 vs 未来7日收益 Spearman 相关系数】")
print(f"  Spearman r = {spearman_r:+.3f} (p={pval:.3f}, {'显著' if pval<0.05 else '不显著'})")
# 五分位排序：高分vs低分组合表现
order = np.argsort(scores)
low_idx = order[:len(order)//5]
high_idx = order[-len(order)//5:]
low_ret = rets7[low_idx].mean()*100 if len(low_idx) else 0
high_ret = rets7[high_idx].mean()*100 if len(high_idx) else 0
print(f"  最低20%分组合: 7日均值{low_ret:+.2f}%")
print(f"  最高20%分组合: 7日均值{high_ret:+.2f}%")
print(f"  高/低分组差 = {high_ret - low_ret:+.2f}% ({'正确方向' if high_ret > low_ret else '反方向'})")

# 3.7 跨类约束有效性
print(f"\n【3.7 跨类约束 mult_crossasset × 有效仓位】")
for cm_val, cm_name in [(1.0, "无跨类约束(1.0)"), (0.8, "跨类约束触发(0.8)"), (0.5, "三类均差(0.5)")]:
    rows_cm = [r for r in records if r["mult_crossasset"] == cm_val]
    if not rows_cm:
        print(f"  {cm_name:20s}: 0 次")
        continue
    r7 = np.array([r["ret_7d"] for r in rows_cm if not np.isnan(r["ret_7d"])])
    # 全仓位 vs 有效仓位下收益
    if len(r7):
        raw_ret = r7.mean() * 100
        eff_ret = (r7 * np.array([r["effective_cap"] for r in rows_cm if not np.isnan(r["ret_7d"])])).mean()*100
        raw_vol = r7.std() * 100 * np.sqrt(365/7)
        eff_r = r7 * np.array([r["effective_cap"] for r in rows_cm if not np.isnan(r["ret_7d"])])
        eff_vol = eff_r.std() * 100 * np.sqrt(365/7)
        print(f"  {cm_name:20s}: {len(rows_cm):4d}次 全仓收益{raw_ret:+.2f}%(vol{raw_vol:.1f}) → 有效仓收益{eff_ret:+.2f}%(vol{eff_vol:.1f})")

# 3.8 滞回机制（COOLDOWN→ALLOW解冻）效果
print(f"\n【3.8 war_state滞回合理性】")
cnt = Counter(r["war_state"] for r in records)
print(f"  状态分布: {dict(cnt)}")
# 计算FREEZE/COOLDOWN持续时长
streaks = []
cur_state = records[0]["war_state"]
cur_len = 1
for r in records[1:]:
    if r["war_state"] == cur_state:
        cur_len += 1
    else:
        streaks.append((cur_state, cur_len))
        cur_state = r["war_state"]
        cur_len = 1
streaks.append((cur_state, cur_len))
freeze_lens = [s[1] for s in streaks if s[0] == "FREEZE"]
cooldown_lens = [s[1] for s in streaks if s[0] == "COOLDOWN"]
allow_lens = [s[1] for s in streaks if s[0] == "ALLOW"]
if freeze_lens: print(f"  FREEZE  平均持续: {np.mean(freeze_lens):.1f}日 (最短{min(freeze_lens)} 最长{max(freeze_lens)})")
if cooldown_lens: print(f"  COOLDOWN 平均持续: {np.mean(cooldown_lens):.1f}日 (最短{min(cooldown_lens)} 最长{max(cooldown_lens)})")
if allow_lens: print(f"  ALLOW    平均持续: {np.mean(allow_lens):.1f}日 (最短{min(allow_lens)} 最长{max(allow_lens)})")

# ================================================================
# Step 4: 保存详细回测记录
# ================================================================
print("=" * 78)
out_path = PROJ / "scripts" / "memory_l4" / "artifacts_five_domain_btc_backtest.json"
json.dump(records, open(out_path, "w"), ensure_ascii=False, indent=2, default=str)
print(f"[Step 4] 详细记录已保存: {out_path}")
print(f"  记录数: {len(records)} 条")
print("=" * 78)
print("回测完成")
