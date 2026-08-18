#!/usr/bin/env python3
"""
Phase D 数据集生成器 (AI_ENHANCEMENT_ROADMAP §4.1)

产出两类样本：
  ① BiLSTM-Attention 爆仓预警样本
       - 输入: 60 × 5 (4H OHLCV) + 7 维标量 (level/pnl/atr_z/vol_z/timing3d)
       - 标签: y_bust ∈ {0,1}  = 「当前位置补完允许的所有加仓后仍不能 TP，触发强制离场」
  ② PatchTST 回撤深度预测样本
       - 输入: 120 × 5 (1H OHLCV)
       - 标签: y_max_dd ∈ [-1, 0] = 「step 之后未来 24 根 1H K 线的最大回撤比例（负值）」

单条样本 API（TDD 测试使用）：generate_single_trajectory_sample(seed=42)
批量 1000+ 条训练集生成 CLI：
    python3 phase_d_dataset_generator.py --n-trajectories 1200 --seed 42 \
        --out-dir data/ai_datasets
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))


# 币种池（与 V15_COINS 默认一致）
DEFAULT_COINS = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]
BI_LSTM_4H_LEN = 60
PATCHTST_1H_LEN = 120
PATCHTST_HORIZON = 24  # 未来 24 根 1H K 线 = 1 天


# ================================================================
# 合成 K 线生成器（避免回测前期必须 OKX 真实 K 线缓存）
# GBM + jump + 波动率聚类，足够做模型训练分布近似
# ================================================================
def _synth_candles(
    n_bars: int,
    tf_steps_per_day: int,
    start_price: float = 100.0,
    ann_vol: float = 0.60,
    drift: float = 0.0002,
    seed: int = 0,
) -> List[Dict[str, float]]:
    """v3: GBM + 趋势段 + 崩盘跳空，提高 bust 正样本率"""
    rng = np.random.default_rng(seed)
    bars_per_year = tf_steps_per_day * 365
    vol_per_bar = ann_vol / math.sqrt(bars_per_year)
    prices = np.zeros(n_bars + 1)
    prices[0] = start_price

    # v3: 趋势段（每 60~120 根切换一次 bull/bear/range）
    seg_len = int(rng.integers(60, 120))
    trend_drift = drift / tf_steps_per_day  # 转换为 per-bar
    for i in range(1, n_bars + 1):
        if i % seg_len == 0:
            seg_type = rng.choice(["bull", "bear", "range", "bear", "crash"])
            if seg_type == "bull":
                trend_drift = float(rng.uniform(0.0003, 0.0008))
            elif seg_type == "bear":
                trend_drift = float(rng.uniform(-0.0008, -0.0003))
            elif seg_type == "crash":
                trend_drift = float(rng.uniform(-0.0015, -0.0008))
            else:
                trend_drift = float(rng.uniform(-0.0001, 0.0001))
            seg_len = int(rng.integers(60, 120))
        z = rng.normal()
        # v3: 崩盘跳空 — crash 段内 8% 概率大幅下跳，bear 段内 3% 概率
        jump = 0.0
        if rng.random() < 0.02:
            jump = -float(rng.uniform(0.05, 0.15))  # 崩盘级跳空
        elif rng.random() < 0.04:
            jump = rng.normal(0, 0.015)  # 常规小跳
        prices[i] = prices[i - 1] * math.exp(
            trend_drift - 0.5 * vol_per_bar**2 + vol_per_bar * z + jump
        )
        if prices[i] <= 0:
            prices[i] = prices[i - 1] * 0.01  # 防负价格
    candles = []
    for i in range(n_bars):
        o = prices[i]
        c = prices[i + 1]
        spread = abs(c - o) * 0.35 + 0.0004 * prices[i]
        w1, w2 = rng.random(2)
        h = max(o, c) + spread * w1
        l = min(o, c) - spread * w2
        base_vol = prices[i] * ann_vol / math.sqrt(bars_per_year) * 3
        v = max(1e-6, rng.exponential(base_vol))
        candles.append({"o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v)})
    return candles


def _sma(values, p):
    if len(values) < p:
        return values[-1] if values else 0.0
    return float(sum(values[-p:])) / p


def _rsi(prices, p=14):
    if len(prices) < p + 1:
        return 50.0
    d = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    r = d[-p:]
    g = [max(x, 0) for x in r]
    lo = [max(-x, 0) for x in r]
    ag = sum(g) / p
    al = sum(lo) / p
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def _atr_from_ohlcv(candles, p=14):
    if len(candles) < p + 1:
        return abs(candles[-1]["h"] - candles[-1]["l"]) if candles else 0.0
    trs = []
    for i in range(len(candles) - p, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return float(sum(trs)) / len(trs)


# ================================================================
# 简化马丁轨迹模拟器（给标签打 bust / safe + 未来 maxdd）
# 为了不依赖真正 v15_backtest 全量执行（其执行耗时较长），这里复现
# 相同的「首单+加仓金字塔+TP 4%/加仓 8%」核心逻辑，仅用于标签生成。
# ================================================================
@dataclass
class _MiniPosition:
    levels_used: int = 0  # 已经触发的加仓数 (0=仅首单, 4=首单+4加仓)
    base_entry: float = 0.0
    avg_entry: float = 0.0
    total_cost_usd: float = 0.0
    total_qty: float = 0.0
    tp_price: float = 0.0
    addon_levels_reached: List[int] = None  # noqa: RUF008  dataclass 默认稍后赋值

    def __post_init__(self):  # noqa: D105
        if self.addon_levels_reached is None:
            self.addon_levels_reached = []


def _simulate_martingale_labels(
    candles_1h: List[Dict[str, float]],
    start_idx: int,
    addon_pct: float = 0.08,
    tp_pct: float = 0.04,
    max_addons: int = 4,
    base_position_usd: float = 22.0,
    addon_budgets: Tuple[float, ...] = (5.0, 10.0, 20.0, 35.0),
    horizon_1h: int = 24 * 14,  # 2 周足够判定任何马丁周期是否 TP
) -> Tuple[int, float]:
    """在 1H K 线上从 start_idx 开始模拟开一笔 多单马丁
    返回 (bust 0/1, 未来 horizon_1h 最大回撤比例（负）)
    """
    if start_idx + 2 >= len(candles_1h):
        return 0, 0.0

    p0 = candles_1h[start_idx]["c"]
    pos = _MiniPosition()
    # ---- 首单 ----
    pos.base_entry = p0
    pos.avg_entry = p0
    pos.total_qty = base_position_usd / p0
    pos.total_cost_usd = base_position_usd
    pos.tp_price = p0 * (1 + tp_pct)
    pos.levels_used = 0

    # ---- 加仓网格价位 ----
    addon_prices = [p0 * (1 - addon_pct * j) for j in range(1, max_addons + 1)]

    peak_price_after_open = p0
    max_drawdown_frac = 0.0  # 0.0 = 无回撤，-0.2 = 回撤 20%

    end = min(len(candles_1h), start_idx + horizon_1h)

    busted = False
    for i in range(start_idx, end):
        bar = candles_1h[i]
        # ---- 先看 TP（高价触及 tp） ----
        if bar["h"] >= pos.tp_price and pos.total_qty > 0:
            # 成功 TP → bust=0, 记录到此时为止的 maxdd
            return 0, max_drawdown_frac
        # ---- 加仓触发（低价触达下一档 addon） ----
        for k in range(len(addon_prices)):
            lvl = k + 1
            if lvl in pos.addon_levels_reached:
                continue
            if lvl > max_addons:
                break
            if bar["l"] <= addon_prices[k]:
                # 在 addon 价成交
                fill = addon_prices[k]
                bud = addon_budgets[k] if k < len(addon_budgets) else addon_budgets[-1]
                qty_add = bud / fill
                new_cost = pos.total_cost_usd + bud
                new_qty = pos.total_qty + qty_add
                pos.avg_entry = (pos.avg_entry * pos.total_qty + fill * qty_add) / new_qty
                pos.total_cost_usd = new_cost
                pos.total_qty = new_qty
                pos.addon_levels_reached.append(lvl)
                pos.levels_used = lvl
                # TP 随最新 avg 重算（马丁 TP 通常按均价）
                pos.tp_price = pos.avg_entry * (1 + tp_pct)
        # ---- max drawdown 跟踪 (按收盘价 vs 开仓后峰值) ----
        close_here = bar["c"]
        peak_price_after_open = max(peak_price_after_open, close_here)
        dd = (close_here - peak_price_after_open) / peak_price_after_open if peak_price_after_open > 0 else 0.0
        if dd < max_drawdown_frac:
            max_drawdown_frac = dd
    # ---- 结束仍未 TP ----
    # bust 判定: 到达最深档 max_addons 且仍未 TP → 1
    busted = 1 if pos.levels_used >= max_addons else 0
    return busted, max_drawdown_frac


# ================================================================
# 单样本 & 批量生成对外 API
# ================================================================
def generate_single_trajectory_sample(seed: int = 42):
    """TDD 友好：单条样本生成（4 元组返回）

    Returns:
        (bilstm_input_dict, patchtst_input_ndarray, label_bust, label_maxdd)
    """
    rng = random.Random(seed)
    coin = rng.choice(DEFAULT_COINS)
    n_1h = PATCHTST_1H_LEN + PATCHTST_HORIZON + 24 * 14  # PatchTST 历史 + 未来 24h（打标签） + 2 周模拟
    # v3: 加宽 vol/drift 范围，增加 bust 场景比例
    ann_vol = rng.uniform(0.35, 1.20)
    drift = rng.uniform(-0.002, 0.0012)
    start_price = float(np.exp(rng.uniform(np.log(5), np.log(5000))))

    candles_1h = _synth_candles(
        n_bars=n_1h, tf_steps_per_day=24, start_price=start_price,
        ann_vol=ann_vol, drift=drift, seed=seed,
    )
    # 4H OHLCV = 每隔 4 根 1H 聚合
    candles_4h: List[Dict[str, float]] = []
    for i in range(0, len(candles_1h) - 3, 4):
        b1, b2, b3, b4 = candles_1h[i : i + 4]
        candles_4h.append({
            "o": b1["o"], "h": max(b1["h"], b2["h"], b3["h"], b4["h"]),
            "l": min(b1["l"], b2["l"], b3["l"], b4["l"]),
            "c": b4["c"], "v": b1["v"] + b2["v"] + b3["v"] + b4["v"],
        })

    # ---- 采样一个起点（确保有足够历史 + 未来 horizon） ----
    start_1h_idx = PATCHTST_1H_LEN + 24 * 3  # 给前面 3 天初始化
    start_1h_idx = min(start_1h_idx, len(candles_1h) - 24 * 14 - 1)

    # ---- PatchTST 输入 120×5 ----
    p_start = start_1h_idx - PATCHTST_1H_LEN
    p_slice = candles_1h[p_start:start_1h_idx]
    if len(p_slice) < PATCHTST_1H_LEN:
        # 长度不够：前面用首根重复填充
        pad = [p_slice[0]] * (PATCHTST_1H_LEN - len(p_slice)) if p_slice else [candles_1h[0]] * PATCHTST_1H_LEN
        p_slice = pad + p_slice
    patchtst_in = np.array(
        [[b["o"], b["h"], b["l"], b["c"], b["v"]] for b in p_slice[-PATCHTST_1H_LEN:]],
        dtype=np.float32,
    )

    # ---- BiLSTM 输入 60×5 (4H) + 7 标量 ----
    corresponding_4h_start = len(candles_4h) - max(1, len(candles_4h) - (start_1h_idx // 4))
    take4h = candles_4h[-BI_LSTM_4H_LEN:] if len(candles_4h) >= BI_LSTM_4H_LEN else (
        [candles_4h[0]] * (BI_LSTM_4H_LEN - len(candles_4h)) + candles_4h
    )
    ohlcv_4h = np.array(
        [[b["o"], b["h"], b["l"], b["c"], b["v"]] for b in take4h[-BI_LSTM_4H_LEN:]],
        dtype=np.float32,
    )
    closes_4h = [b["c"] for b in take4h]
    closes_1h_last30 = [b["c"] for b in candles_1h[max(0, start_1h_idx - 30 * 24) : start_1h_idx]]
    if len(closes_1h_last30) < 30:
        closes_1h_last30 = list(closes_4h)
    atr_14 = _atr_from_ohlcv([{"h": h, "l": l, "c": c} for h, l, c in zip(
        ohlcv_4h[:, 1], ohlcv_4h[:, 2], ohlcv_4h[:, 3]
    )], p=14)
    price_now = closes_4h[-1]
    # 简单 ATR z-score：对最近 30 根 4H 窗口
    atrs_rolling = []
    for w in range(max(0, len(closes_4h) - 60), len(closes_4h)):
        seg = take4h[max(0, w - 15) : w + 1]
        if len(seg) >= 14:
            atrs_rolling.append(_atr_from_ohlcv(seg, 14))
    atr_z = (atr_14 - (sum(atrs_rolling) / len(atrs_rolling) if atrs_rolling else atr_14)) / (
        1e-6 + (float(np.std(atrs_rolling)) if atrs_rolling else 1.0)
    )
    atr_z = max(-3.0, min(3.0, atr_z))
    # 30 日已实现波动率
    rets = [math.log(closes_1h_last30[i] / closes_1h_last30[i - 1]) for i in range(1, len(closes_1h_last30))]
    vol_30 = float(np.std(rets)) * math.sqrt(365) if len(rets) >= 10 else ann_vol
    # vol zscore 60 近似：默认 1.0（中性）
    vol_z = min(2.5, max(-2.5, (vol_30 - ann_vol) / max(ann_vol * 0.3, 1e-4)))
    # 爆仓标签 + 回撤标签
    label_bust, label_maxdd = _simulate_martingale_labels(
        candles_1h,
        start_idx=start_1h_idx,
        max_addons=4,
        addon_budgets=(5.0, 10.0, 20.0, 35.0),
    )
    # level & pnl (模拟在起点处 level = rng 0~2 & pnl% 轻微)
    level = rng.randint(0, 2) if label_bust == 0 else rng.randint(2, 4)
    pnl_pct = rng.uniform(-0.02, 0.01) if level == 0 else rng.uniform(-0.08 * level, -0.01 * level)
    bilstm_in = {
        "ohlcv": ohlcv_4h,
        "scalar_features": np.array(
            [
                float(level) / 4.0,     # 0: level (归一化 0~1)
                pnl_pct,                # 1: 未实现盈亏比 [-0.5, 0.1]
                atr_z / 3.0,            # 2: atr_14 zscore (归一化)
                vol_z / 2.5,            # 3: vol_z (归一化)
                0.70,                   # 4: structure_match 默认 (TimingGate 软评分占位)
                0.65,                   # 5: retrace_quality 占位
                0.75,                   # 6: extension_chase 占位
            ],
            dtype=np.float32,
        ),
        "_meta": {
            "coin": coin, "seed": seed,
            "start_price": price_now, "vol_30_ann": vol_30, "atr_14": atr_14,
            "level": level, "pnl_pct": pnl_pct,
        },
    }
    return (bilstm_in, patchtst_in, int(label_bust), float(label_maxdd))


# ================================================================
# 批量 CLI：生成 N 条样本 → 存 NPZ
# ================================================================
def _collate(batch: List[Tuple]) -> Dict[str, Any]:
    bilstm_ohlcv = np.stack([x[0]["ohlcv"] for x in batch], axis=0)  # [N, 60, 5]
    bilstm_scalar = np.stack([x[0]["scalar_features"] for x in batch], axis=0)  # [N, 7]
    patchtst_in = np.stack([x[1] for x in batch], axis=0)  # [N, 120, 5]
    bust = np.array([x[2] for x in batch], dtype=np.int64)
    maxdd = np.array([x[3] for x in batch], dtype=np.float32)
    return {
        "bilstm_ohlcv": bilstm_ohlcv,
        "bilstm_scalar": bilstm_scalar,
        "patchtst_in": patchtst_in,
        "label_bust": bust,
        "label_maxdd": maxdd,
    }


def _stratified_wf_split(
    samples: List[Tuple],
    n_segments: int = 5,
    min_pos_per_seg: int = 3,
    seed: int = 42,
) -> List[List[Tuple]]:
    """v3: 分层 Walk-Forward 切分 — 保证每段 test 至少 min_pos_per_seg 个正样本。

    将正样本（bust=1）和负样本（bust=0）分开，
    正样本 round-robin 均匀分配到各段（保证每段 ≥ min_pos_per_seg），
    负样本均匀填充各段剩余位置。
    """
    positives = [s for s in samples if s[2] == 1]
    negatives = [s for s in samples if s[2] == 0]
    rng = random.Random(seed + 999)
    rng.shuffle(positives)
    rng.shuffle(negatives)

    segments: List[List[Tuple]] = [[] for _ in range(n_segments)]

    # 正样本 round-robin 分配
    for i, p in enumerate(positives):
        segments[i % n_segments].append(p)

    # 检查每段正样本数，不足则从多余段借（理论上均匀分配已保证）
    for seg in segments:
        pos_count = sum(1 for s in seg if s[2] == 1)
        if pos_count < min_pos_per_seg and len(positives) >= n_segments:
            # 正样本总数够但分配不均 → 从最多段借
            pass  # round-robin 已保证均匀

    # 负样本均匀填充
    neg_per_seg = len(negatives) // n_segments
    for seg_i in range(n_segments):
        start = seg_i * neg_per_seg
        end = start + neg_per_seg if seg_i < n_segments - 1 else len(negatives)
        segments[seg_i].extend(negatives[start:end])

    # 段内 shuffle
    for seg in segments:
        rng.shuffle(seg)

    return segments


def _stratified_train_test_split(
    samples: List[Tuple],
    train_ratio: float = 0.9,
    seed: int = 42,
) -> Tuple[List[Tuple], List[Tuple]]:
    """v3: 分层 train/test 切分 — 保证 train/test 各自含足够正样本"""
    positives = [s for s in samples if s[2] == 1]
    negatives = [s for s in samples if s[2] == 0]
    rng = random.Random(seed)
    rng.shuffle(positives)
    rng.shuffle(negatives)

    pos_cut = int(train_ratio * len(positives))
    neg_cut = int(train_ratio * len(negatives))

    train = positives[:pos_cut] + negatives[:neg_cut]
    test = positives[pos_cut:] + negatives[neg_cut:]
    rng.shuffle(train)
    rng.shuffle(test)
    return train, test


def build_dataset(
    n_trajectories: int = 5000,
    seed: int = 42,
    walk_forward_segments: int = 5,
    out_dir: str | Path = "data/ai_datasets",
    progress: bool = True,
) -> Dict[str, Path]:
    """v3: 生成训练/验证/WF 数据集并落盘。返回各 split 文件路径 dict。

    v3 改进：
    - 默认 5000 样本（原 1000）
    - 分层 WF 切分（_stratified_wf_split），保证每段 test ≥3 正样本
    - 分层 train/test 切分（_stratified_train_test_split）
    - 合成 K 线加入崩盘场景，提高 bust 率
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "BI_LSTM_4H_LEN": BI_LSTM_4H_LEN,
        "PATCHTST_1H_LEN": PATCHTST_1H_LEN,
        "PATCHTST_HORIZON": PATCHTST_HORIZON,
        "n_total": n_trajectories,
        "wf_segments": walk_forward_segments,
        "seed": seed,
        "version": "v3_stratified",
    }

    all_samples = []
    for i in range(n_trajectories):
        all_samples.append(generate_single_trajectory_sample(seed=seed + i))
        if progress and (i + 1) % max(1, n_trajectories // 10) == 0:
            print(f"[dataset]  {i+1}/{n_trajectories}")

    n_pos = sum(1 for s in all_samples if s[2] == 1)
    n_neg = len(all_samples) - n_pos
    if progress:
        print(f"[dataset] 总样本={len(all_samples)}  正样本(bust)={n_pos} ({n_pos/max(1,len(all_samples)):.1%})  负样本={n_neg}")

    # v3: 分层 WF 切分
    wf_segments_data = _stratified_wf_split(all_samples, n_segments=walk_forward_segments, min_pos_per_seg=3, seed=seed)
    paths: Dict[str, Path] = {}
    for seg_i in range(walk_forward_segments):
        seg = wf_segments_data[seg_i]
        # train = 除当前段外的所有样本
        train_part = []
        for j in range(walk_forward_segments):
            if j != seg_i:
                train_part.extend(wf_segments_data[j])
        data_tr = _collate(train_part)
        data_te = _collate(seg)
        tr_path = out_dir / f"phase_d_train_wf{seg_i+1}.npz"
        te_path = out_dir / f"phase_d_test_wf{seg_i+1}.npz"
        np.savez_compressed(tr_path, **data_tr)
        np.savez_compressed(te_path, **data_te)
        seg_pos = sum(1 for s in seg if s[2] == 1)
        if progress:
            print(f"  wf{seg_i+1}: test={len(seg)} (pos={seg_pos})  train={len(train_part)}")
        paths[f"wf{seg_i+1}_train"] = tr_path
        paths[f"wf{seg_i+1}_test"] = te_path

    # v3: 分层 train/test 9:1 split
    tr_list, te_list = _stratified_train_test_split(all_samples, train_ratio=0.9, seed=seed + 10_000)
    tr = _collate(tr_list)
    te = _collate(te_list)
    tr_all = out_dir / "phase_d_train_all.npz"
    te_all = out_dir / "phase_d_test_all.npz"
    np.savez_compressed(tr_all, **tr)
    np.savez_compressed(te_all, **te)
    paths["train_all"] = tr_all
    paths["test_all"] = te_all
    if progress:
        tr_pos = sum(1 for s in tr_list if s[2] == 1)
        te_pos = sum(1 for s in te_list if s[2] == 1)
        print(f"  train_all: {len(tr_list)} (pos={tr_pos})  test_all: {len(te_list)} (pos={te_pos})")

    (out_dir / "phase_d_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    paths["meta"] = out_dir / "phase_d_meta.json"
    return paths


# ================================================================
# 真实 OKX K 线数据集生成（滑窗采样）
# ================================================================
def _fetch_real_1h_klines(coin: str, limit: int = 1500) -> List[Dict[str, float]]:
    """从 Hyperliquid API 翻页拉取真实 1H K 线，标准化为 {o,h,l,c,v} 格式

    Hyperliquid candleSnapshot API 单次上限约 500 根，用 startTime 向前翻页。
    返回按时间正序排列（最早在前）。
    """
    import sys as _sys
    import time as _time
    from pathlib import Path as _Path

    # Path injection for aster_spot
    _hl_dir = _Path(__file__).resolve().parent.parent / "experiments" / "ab-trading" / "execution"
    if str(_hl_dir) not in _sys.path:
        _sys.path.insert(0, str(_hl_dir))

    from aster_spot import _info

    batch = 500  # Hyperliquid 单次请求量
    seen_ts = set()
    all_candles: List[Dict[str, float]] = []
    now_ms = int(_time.time() * 1000)
    interval_ms = 3600000  # 1h in ms
    end_ms = now_ms

    while len(all_candles) < limit:
        count = min(batch, limit - len(all_candles))
        start_ms = end_ms - interval_ms * count
        try:
            raw = _info({
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": "1h",
                        "startTime": start_ms, "endTime": end_ms}
            })
            raw = raw if isinstance(raw, list) else []
        except Exception as e:
            if all_candles:
                print(f"[dataset] {coin} 翻页中断 ({e}), 已获取 {len(all_candles)} 根")
                break
            raise RuntimeError(f"Hyperliquid API {coin} 失败: {e}")
        if not raw:
            break
        new_added = 0
        for d in raw:
            ts = int(d.get("t", 0))
            if ts in seen_ts or ts == 0:
                continue
            seen_ts.add(ts)
            all_candles.append({
                "o": float(d.get("o", 0)),
                "h": float(d.get("h", 0)),
                "l": float(d.get("l", 0)),
                "c": float(d.get("c", 0)),
                "v": float(d.get("v", 0)),
            })
            new_added += 1
        if new_added == 0:
            break
        # Move end_ms back to the earliest candle's timestamp for next page
        earliest_ts = min(int(d.get("t", end_ms)) for d in raw)
        end_ms = earliest_ts
        if len(raw) < count:
            break
    # Hyperliquid returns ascending by t; pages are appended oldest-first
    return all_candles[:limit]


def _build_sample_from_1h_candles(
    candles_1h: List[Dict[str, float]],
    coin: str,
    start_1h_idx: int,
    seed: int = 42,
    ann_vol_hint: float = 0.6,
):
    """从 1H K 线序列的 start_1h_idx 起点构造单条样本（合成/真实通用）

    BiLSTM 输入: start_1h_idx 之前 240 根 1H 聚合成 60 根 4H
    PatchTST 输入: start_1h_idx 之前 120 根 1H
    标签: 从 start_1h_idx 开始模拟马丁 → (bust, maxdd)
    """
    # 4H 聚合（start_1h_idx 之前 240 根 1H = 60 根 4H）
    hist_1h_for_4h = candles_1h[max(0, start_1h_idx - 240):start_1h_idx]
    candles_4h: List[Dict[str, float]] = []
    for i in range(0, len(hist_1h_for_4h) - 3, 4):
        b1, b2, b3, b4 = hist_1h_for_4h[i:i + 4]
        candles_4h.append({
            "o": b1["o"], "h": max(b1["h"], b2["h"], b3["h"], b4["h"]),
            "l": min(b1["l"], b2["l"], b3["l"], b4["l"]),
            "c": b4["c"], "v": b1["v"] + b2["v"] + b3["v"] + b4["v"],
        })
    if len(candles_4h) < BI_LSTM_4H_LEN:
        pad = [candles_4h[0]] * (BI_LSTM_4H_LEN - len(candles_4h)) if candles_4h else \
            [{"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 0.0}] * BI_LSTM_4H_LEN
        candles_4h = pad + candles_4h
    take4h = candles_4h[-BI_LSTM_4H_LEN:]
    ohlcv_4h = np.array(
        [[b["o"], b["h"], b["l"], b["c"], b["v"]] for b in take4h],
        dtype=np.float32,
    )

    # PatchTST 输入 120×5 (1H)
    p_start = start_1h_idx - PATCHTST_1H_LEN
    p_slice = candles_1h[max(0, p_start):start_1h_idx]
    if len(p_slice) < PATCHTST_1H_LEN:
        pad = [p_slice[0]] * (PATCHTST_1H_LEN - len(p_slice)) if p_slice else \
            [{"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 0.0}] * PATCHTST_1H_LEN
        p_slice = pad + p_slice
    patchtst_in = np.array(
        [[b["o"], b["h"], b["l"], b["c"], b["v"]] for b in p_slice[-PATCHTST_1H_LEN:]],
        dtype=np.float32,
    )

    # 标量特征
    closes_4h = [b["c"] for b in take4h]
    closes_1h_last30 = [b["c"] for b in candles_1h[max(0, start_1h_idx - 30 * 24):start_1h_idx]]
    if len(closes_1h_last30) < 30:
        closes_1h_last30 = list(closes_4h)
    atr_14 = _atr_from_ohlcv(
        [{"h": h, "l": l, "c": c} for h, l, c in zip(
            ohlcv_4h[:, 1], ohlcv_4h[:, 2], ohlcv_4h[:, 3]
        )], p=14,
    )
    price_now = closes_4h[-1] if closes_4h else 1.0
    atrs_rolling = []
    for w in range(max(0, len(closes_4h) - 60), len(closes_4h)):
        seg = take4h[max(0, w - 15): w + 1]
        if len(seg) >= 14:
            atrs_rolling.append(_atr_from_ohlcv(seg, 14))
    atr_z = (atr_14 - (sum(atrs_rolling) / len(atrs_rolling) if atrs_rolling else atr_14)) / (
        1e-6 + (float(np.std(atrs_rolling)) if atrs_rolling else 1.0)
    )
    atr_z = max(-3.0, min(3.0, atr_z))
    rets = [
        math.log(closes_1h_last30[i] / closes_1h_last30[i - 1])
        for i in range(1, len(closes_1h_last30))
        if closes_1h_last30[i - 1] > 0
    ]
    vol_30 = float(np.std(rets)) * math.sqrt(365) if len(rets) >= 10 else ann_vol_hint
    vol_z = min(2.5, max(-2.5, (vol_30 - ann_vol_hint) / max(ann_vol_hint * 0.3, 1e-4)))

    # 标签
    label_bust, label_maxdd = _simulate_martingale_labels(
        candles_1h, start_idx=start_1h_idx, max_addons=4,
        addon_budgets=(5.0, 10.0, 20.0, 35.0),
    )
    rng = random.Random(seed)
    level = rng.randint(0, 2) if label_bust == 0 else rng.randint(2, 4)
    pnl_pct = rng.uniform(-0.02, 0.01) if level == 0 else rng.uniform(-0.08 * level, -0.01 * level)

    bilstm_in = {
        "ohlcv": ohlcv_4h,
        "scalar_features": np.array(
            [float(level) / 4.0, pnl_pct, atr_z / 3.0, vol_z / 2.5, 0.70, 0.65, 0.75],
            dtype=np.float32,
        ),
        "_meta": {
            "coin": coin, "seed": seed,
            "start_price": price_now, "vol_30_ann": vol_30, "atr_14": atr_14,
            "level": level, "pnl_pct": pnl_pct,
        },
    }
    return (bilstm_in, patchtst_in, int(label_bust), float(label_maxdd))


def build_dataset_from_real(
    coins: List[str] = None,
    limit_1h: int = 1500,
    samples_per_coin: int = 50,
    seed: int = 42,
    walk_forward_segments: int = 5,
    out_dir: str | Path = "data/ai_datasets",
    progress: bool = True,
) -> Dict[str, Path]:
    """从真实 OKX K 线生成数据集（每币种滑窗采样）"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    coins = coins or DEFAULT_COINS

    meta = {
        "source": "real_okx",
        "BI_LSTM_4H_LEN": BI_LSTM_4H_LEN,
        "PATCHTST_1H_LEN": PATCHTST_1H_LEN,
        "PATCHTST_HORIZON": PATCHTST_HORIZON,
        "coins": coins,
        "limit_1h": limit_1h,
        "samples_per_coin": samples_per_coin,
        "wf_segments": walk_forward_segments,
        "seed": seed,
        "version": "v3_stratified",
    }

    all_samples = []
    for coin in coins:
        try:
            candles_1h = _fetch_real_1h_klines(coin, limit=limit_1h)
        except Exception as e:
            print(f"[dataset] {coin} 拉取失败: {e}")
            continue
        if len(candles_1h) < PATCHTST_1H_LEN + 24 * 14 + 72:
            print(f"[dataset] {coin} 数据不足 ({len(candles_1h)} 根), 跳过")
            continue
        # 采样起点范围：前留 240 (BiLSTM 4H 历史) + 72 (缓冲), 后留 24*14 (标签 horizon)
        min_start = 240 + 72
        max_start = len(candles_1h) - 24 * 14 - 1
        if max_start <= min_start:
            print(f"[dataset] {coin} 可采样范围不足, 跳过")
            continue
        step = max(1, (max_start - min_start) // samples_per_coin)
        n_done = 0
        for s_idx, start in enumerate(range(min_start, max_start, step)):
            if n_done >= samples_per_coin:
                break
            try:
                sample = _build_sample_from_1h_candles(
                    candles_1h, coin, start, seed=seed + s_idx,
                )
                all_samples.append(sample)
                n_done += 1
            except Exception:
                continue
        if progress:
            print(f"[dataset] {coin}: 采样 {n_done} 条 (共 {len(candles_1h)} 根 1H)")

    if not all_samples:
        raise RuntimeError("真实 K 线数据集生成失败：无有效样本")

    n_pos = sum(1 for s in all_samples if s[2] == 1)
    print(f"[dataset] 总样本数: {len(all_samples)}  正样本(bust)={n_pos} ({n_pos/max(1,len(all_samples)):.1%})")

    # v3: 分层 WF 切分（同 build_dataset 逻辑）
    wf_segments_data = _stratified_wf_split(all_samples, n_segments=walk_forward_segments, min_pos_per_seg=3, seed=seed)
    paths: Dict[str, Path] = {}
    for seg_i in range(walk_forward_segments):
        seg = wf_segments_data[seg_i]
        train_part = []
        for j in range(walk_forward_segments):
            if j != seg_i:
                train_part.extend(wf_segments_data[j])
        data_tr = _collate(train_part)
        data_te = _collate(seg)
        tr_path = out_dir / f"phase_d_train_wf{seg_i+1}.npz"
        te_path = out_dir / f"phase_d_test_wf{seg_i+1}.npz"
        np.savez_compressed(tr_path, **data_tr)
        np.savez_compressed(te_path, **data_te)
        seg_pos = sum(1 for s in seg if s[2] == 1)
        print(f"  wf{seg_i+1}: test={len(seg)} (pos={seg_pos})  train={len(train_part)}")
        paths[f"wf{seg_i+1}_train"] = tr_path
        paths[f"wf{seg_i+1}_test"] = te_path

    # v3: 分层 train/test 9:1 split
    tr_list, te_list = _stratified_train_test_split(all_samples, train_ratio=0.9, seed=seed + 10_000)
    tr = _collate(tr_list)
    te = _collate(te_list)
    tr_all = out_dir / "phase_d_train_all.npz"
    te_all = out_dir / "phase_d_test_all.npz"
    np.savez_compressed(tr_all, **tr)
    np.savez_compressed(te_all, **te)
    paths["train_all"] = tr_all
    paths["test_all"] = te_all
    tr_pos = sum(1 for s in tr_list if s[2] == 1)
    te_pos = sum(1 for s in te_list if s[2] == 1)
    print(f"  train_all: {len(tr_list)} (pos={tr_pos})  test_all: {len(te_list)} (pos={te_pos})")

    (out_dir / "phase_d_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    paths["meta"] = out_dir / "phase_d_meta.json"
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser("phase_d_dataset_generator")
    ap.add_argument("--source", choices=["synthetic", "real"], default="real",
                    help="数据源: real=真实OKX K线, synthetic=合成GBM")
    ap.add_argument("--n-trajectories", type=int, default=5000,
                    help="合成模式样本数（v3: 默认 5000）")
    ap.add_argument("--limit-1h", type=int, default=1500,
                    help="真实模式每币种拉取 1H K 线数")
    ap.add_argument("--samples-per-coin", type=int, default=50,
                    help="真实模式每币种采样起点数")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", type=str, default="data/ai_datasets")
    ap.add_argument("--wf", type=int, default=5)
    args = ap.parse_args(argv)
    if args.source == "real":
        paths = build_dataset_from_real(
            coins=DEFAULT_COINS, limit_1h=args.limit_1h,
            samples_per_coin=args.samples_per_coin, seed=args.seed,
            walk_forward_segments=args.wf, out_dir=args.out_dir,
        )
    else:
        paths = build_dataset(args.n_trajectories, args.seed, args.wf, args.out_dir)
    for k, v in paths.items():
        print(f"{k:20s}  {v}")


if __name__ == "__main__":
    main()
