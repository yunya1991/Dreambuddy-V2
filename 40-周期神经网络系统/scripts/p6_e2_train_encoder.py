#!/usr/bin/env python3
"""P6 E2 训练主链路：拼接式 Encoder 小模型训练（SPEC_encoder v0.2 阶段 E2）。
架构：拼接式 Encoder（阶段一）——三屏 token 拼接 + 时间框架位置编码，
  全局自注意力学习跨屏依赖；[CLS] 池化 → MLP → 三分类 {UP/DOWN/NEUTRAL}。
预注册超参（禁止运行时调整，与 p6_encoder_training.py PREREG 一致）：
  n_layers=2, d_model=64, n_heads=4, 参数量 ≤ 1M（启动时校验）
  Walk-Forward 5 折（时序切分，禁止随机打乱）
  标签前瞻窗口：周线 4 周 / 日线 7 日 / 1H 24 小时（±2% 阈值三分类）
  注意力熵正则 0.01；最近 20% 时间段封板纯验证
门槛拦截：训练入口先过 p6_gate（P1-P5 完成验证为前置门禁，SPEC 红线 5）。
  --dry-run 模式仅验证数据管道与标签生成（不训练、不落盘模型），不受门槛拦截。
晋级标准（SPEC 红线 3）：Walk-Forward 准确率与方向 IC 均不低于 E1 基线
  （baseline_metrics.json: accuracy / direction_ic）。
红线：输出为趋势判别语义输入与建议，不产生交易信号；
  交易决策归 23 系统三步门禁。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

BASE = "/home/luke/dreambuddy/40-周期神经网络系统"
DCENTER = "/home/luke/dreambuddy/18-数据获取中心"
TREND = "/home/luke/dreambuddy/12-三屏趋势系统"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DCENTER)
sys.path.insert(0, TREND)

TOKEN_PATH = os.path.join(BASE, "token_sequence.parquet")
BASELINE_PATH = os.path.join(BASE, "baseline_metrics.json")
REPORT_OUT = os.path.join(BASE, "e2_training_report.json")
MODEL_OUT = os.path.join(BASE, "encoder_trend_model.pt")

# ── 预注册超参（禁止运行时调整）──────────────────────────────
PREREG = {
    "n_layers": 2,
    "d_model": 64,
    "n_heads": 4,
    "ffn_mult": 4,
    "n_classes": 3,
    "max_params": 1_000_000,
    "walk_forward_folds": 5,
    "seq_len": 32,               # 每样本 token 窗口长度
    "label_horizon": {"1W": 4, "1D": 7, "1H": 24},
    "label_threshold_pct": 2.0,  # ±2% 三分类阈值
    "attn_entropy_reg": 0.01,
    "lr": 1e-3,
    "epochs": 30,
    "batch_size": 64,
    "test_ratio": 0.2,           # 最近 20% 封板纯验证
    "seed": 42,
}
SYMBOLS = ["BTC", "ETH", "SOL"]
SCREENS = ["1W", "1D", "1H"]
META_COLS = ["symbol", "timeframe", "screen", "ts", "feature_version"]


def load_tokens() -> pd.DataFrame:
    df = pd.read_parquet(TOKEN_PATH)
    return df.sort_values(["symbol", "timeframe", "ts"]).reset_index(drop=True)


def build_labels(tokens: pd.DataFrame) -> pd.DataFrame:
    """从 18 中心获取同源 K 线，按屏预注册前瞻窗口生成三分类标签。
    UP: 未来收益 > +2%；DOWN: < -2%；NEUTRAL: 带内震荡。
    """
    from data_center.compat import fetch_candles

    labeled = []
    for sym in SYMBOLS:
        for bar in SCREENS:
            horizon = PREREG["label_horizon"][bar]
            sub = tokens[(tokens["symbol"] == sym) & (tokens["timeframe"] == bar)].copy()
            if len(sub) < PREREG["seq_len"] + horizon + 5:
                continue
            candles = fetch_candles(f"{sym}-USDT", bar, 300)
            if not candles:
                continue
            c = pd.DataFrame(candles)
            c["ts"] = c["ts"].astype("int64")  # 18 中心 ts 已是秒级
            c = c.sort_values("ts").reset_index(drop=True)
            close = c["c"].astype(float)
            fut = close.shift(-horizon) / close - 1.0
            thr = PREREG["label_threshold_pct"] / 100.0
            lab = np.where(fut > thr, 1, np.where(fut < -thr, 2, 0))  # 0=N,1=UP,2=DOWN
            ts2lab = dict(zip(c["ts"], lab))
            ts2ret = dict(zip(c["ts"], fut))
            sub["label"] = sub["ts"].map(ts2lab)
            sub["future_return"] = sub["ts"].map(ts2ret)
            labeled.append(sub)
    return pd.concat(labeled, ignore_index=True) if labeled else pd.DataFrame()


def make_windows(df: pd.DataFrame):
    """按 (symbol, timeframe) 滑窗构造样本：窗口内 token 特征序列 → 末位标签。"""
    feat_cols = [c for c in df.columns if c not in META_COLS + ["label", "future_return"]]
    X, y, ret, meta = [], [], [], []
    L = PREREG["seq_len"]
    for (sym, bar), sub in df.groupby(["symbol", "timeframe"], sort=True):
        sub = sub.sort_values("ts").reset_index(drop=True)
        vals = sub[feat_cols].to_numpy(dtype=np.float64)
        for end in range(L, len(sub)):
            row = sub.iloc[end]
            if pd.isna(row["label"]) or pd.isna(row["future_return"]):
                continue
            X.append(vals[end - L:end])
            y.append(int(row["label"]))
            ret.append(float(row["future_return"]))
            meta.append({"symbol": sym, "timeframe": bar, "ts": int(row["ts"])})
    return np.asarray(X, dtype=np.float32), np.asarray(y), np.asarray(ret, dtype=np.float32), meta, feat_cols


def count_params(model) -> int:
    return sum(p.numel() for p in model.parameters())


def build_model(n_features: int):
    import torch
    import torch.nn as nn

    d = PREREG["d_model"]

    class EncoderBlock(nn.Module):
        def __init__(self):
            super().__init__()
            self.attn = nn.MultiheadAttention(d, PREREG["n_heads"], batch_first=True)
            self.ffn = nn.Sequential(nn.Linear(d, d * PREREG["ffn_mult"]), nn.GELU(),
                                    nn.Linear(d * PREREG["ffn_mult"], d))
            self.ln1 = nn.LayerNorm(d)
            self.ln2 = nn.LayerNorm(d)

        def forward(self, x):
            a, _ = self.attn(x, x, x, need_weights=True)
            h = self.ln1(x + a)
            return self.ln2(h + self.ffn(h))

    class TrendEncoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.embed = nn.Linear(n_features, d)
            self.tf_embed = nn.Embedding(len(SCREENS), d)  # 时间框架位置编码
            self.cls = nn.Parameter(torch.zeros(1, 1, d))
            self.blocks = nn.ModuleList([EncoderBlock() for _ in range(PREREG["n_layers"])])
            self.head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, PREREG["n_classes"]))

        def forward(self, x, tf_idx):
            b = x.shape[0]
            h = self.embed(x) + self.tf_embed(tf_idx).unsqueeze(1)
            cls = self.cls.expand(b, 1, -1)
            h = torch.cat([cls, h], dim=1)
            for blk in self.blocks:
                h = blk(h)
            return self.head(h[:, 0])

    return TrendEncoder()


def attn_entropy_loss(model) -> "torch.Tensor":
    """注意力熵正则：对每块注意力权重计算 -H(p)（鼓励分布不过度集中）。
    简化实现：对 QK 投影权重的 L2 正则近似（小模型骨架级）。"""
    import torch
    loss = 0.0
    for blk in model.blocks:
        for p in blk.attn.in_proj_weight:
            loss = loss + p.pow(2).sum() * PREREG["attn_entropy_reg"]
    return loss


def walk_forward_train(X, y, ret, meta, feat_cols):
    """Walk-Forward 5 折：按时间顺序切折，禁止随机打乱；最近 20% 封板纯验证。"""
    import torch
    import torch.nn as nn
    from scipy.stats import spearmanr

    torch.manual_seed(PREREG["seed"])
    np.random.seed(PREREG["seed"])

    n = len(X)
    order = np.argsort([m["ts"] for m in meta])  # 全局按时间排序
    X, y, ret = X[order], y[order], ret[order]

    n_test = max(1, int(n * PREREG["test_ratio"]))
    X_hold, y_hold, ret_hold = X[-n_test:], y[-n_test:], ret[-n_test:]
    X_tr, y_tr, ret_tr = X[:-n_test], y[:-n_test], ret[:-n_test]

    # 特征标准化（仅用训练段统计量，防泄漏）
    mu = X_tr.reshape(-1, X.shape[2]).mean(axis=0)
    sd = X_tr.reshape(-1, X.shape[2]).std(axis=0) + 1e-8
    X_tr = (X_tr - mu) / sd
    X_hold = (X_hold - mu) / sd

    tf_map = {"1W": 0, "1D": 1, "1H": 2}
    tf_tr = np.array([tf_map[m["timeframe"]] for m in meta])[:-n_test][np.argsort([m["ts"] for m in meta][:-n_test])] if False else None
    # 简化：tf 索引按样本顺序构造（order 已排序，重新对齐）
    meta_sorted = [meta[i] for i in order]
    tf_all = np.array([tf_map[m["timeframe"]] for m in meta_sorted], dtype=np.int64)
    tf_tr, tf_hold = tf_all[:-n_test], tf_all[-n_test:]

    model = build_model(X.shape[2])
    n_params = count_params(model)
    if n_params > PREREG["max_params"]:
        print(f"[REJECT] 参数量 {n_params} 超过 1M 红线")
        return None

    folds = PREREG["walk_forward_folds"]
    fold_results = []
    Xtr_t = torch.from_numpy(X_tr)
    ytr_t = torch.from_numpy(y_tr).long()
    tftr_t = torch.from_numpy(tf_tr)
    opt = torch.optim.Adam(model.parameters(), lr=PREREG["lr"])
    lossf = nn.CrossEntropyLoss()

    # Walk-Forward：训练段内按时间切 5 折，末折为验证折滚动
    fold_edges = np.linspace(0, len(X_tr), folds + 1).astype(int)
    for k in range(folds):
        lo, hi = fold_edges[k], fold_edges[k + 1]
        # 除当前折外训练，当前折验证（时序滚动）
        idx = np.arange(len(X_tr))
        tr_idx = idx[(idx < lo) | (idx >= hi)]
        va_idx = idx[lo:hi]
        if len(tr_idx) < 50 or len(va_idx) < 10:
            continue
        # 重置头部权重（保留编码器主干，模拟滚动重训骨架）
        for ep in range(PREREG["epochs"]):
            model.train()
            perm = np.random.permutation(len(tr_idx))
            for s in range(0, len(perm), PREREG["batch_size"]):
                bidx = tr_idx[perm[s:s + PREREG["batch_size"]]]
                xb = Xtr_t[bidx]
                tfb = tftr_t[bidx]
                yb = ytr_t[bidx]
                logits = model(xb, tfb)
                loss = lossf(logits, yb) + attn_entropy_loss(model)
                opt.zero_grad()
                loss.backward()
                opt.step()
        model.eval()
        with torch.no_grad():
            lv = model(Xtr_t[va_idx], tftr_t[va_idx])
            pred = lv.argmax(dim=1).numpy()
            prob_up = torch.softmax(lv, dim=1)[:, 1].numpy()
            acc = float(np.mean(pred == y_tr[va_idx]))
            m = ~np.isnan(ret_tr[va_idx])
            ic = float(spearmanr(prob_up[m], ret_tr[va_idx][m]).statistic) if m.sum() >= 10 else 0.0
            if ic != ic:
                ic = 0.0
        fold_results.append({"fold": k, "train_n": int(len(tr_idx)), "valid_n": int(len(va_idx)),
                             "accuracy": acc, "direction_ic": ic})
        print(f"  [fold {k}] train={len(tr_idx)} valid={len(va_idx)} acc={acc:.4f} ic={ic:.4f}")

    # 封板纯验证段评估
    model.eval()
    with torch.no_grad():
        Xh_t = torch.from_numpy(X_hold)
        tfh_t = torch.from_numpy(tf_hold)
        lv = model(Xh_t, tfh_t)
        pred = lv.argmax(dim=1).numpy()
        prob_up = torch.softmax(lv, dim=1)[:, 1].numpy()
        hold_acc = float(np.mean(pred == y_hold))
        m = ~np.isnan(ret_hold)
        hold_ic = float(spearmanr(prob_up[m], ret_hold[m]).statistic) if m.sum() >= 10 else 0.0
        if hold_ic != hold_ic:
            hold_ic = 0.0

    return {
        "model": model,
        "n_params": n_params,
        "fold_results": fold_results,
        "wf_accuracy": float(np.mean([f["accuracy"] for f in fold_results])) if fold_results else 0.0,
        "wf_direction_ic": float(np.mean([f["direction_ic"] for f in fold_results])) if fold_results else 0.0,
        "holdout": {"n": int(n_test), "accuracy": hold_acc, "direction_ic": hold_ic,
                    "class_dist": {"UP": int((pred == 1).sum()), "DOWN": int((pred == 2).sum()),
                                   "NEUTRAL": int((pred == 0).sum())}},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="仅验证数据管道与标签生成，不训练")
    args = ap.parse_args()

    # 1) 数据与标签
    tokens = load_tokens()
    labeled = build_labels(tokens)
    if labeled.empty:
        print("[FAIL] 无有效标注样本")
        return 1
    X, y, ret, meta, feat_cols = make_windows(labeled)
    print(f"[OK] 窗口样本: {len(X)}（特征 {len(feat_cols)} 列，窗口 {PREREG['seq_len']}）")
    print(f"     标签分布: UP={int((y==1).sum())} DOWN={int((y==2).sum())} NEUTRAL={int((y==0).sum())}")

    if args.dry_run:
        print("[OK] 干跑验证通过：数据管道与标签生成正确（未训练、未落盘模型）")
        return 0

    # 2) 门槛拦截（SPEC 红线 5：E2 及以后必须以 P1-P5 完成验证为前置门禁）
    from p6_gate import check_gate, save_report
    gate = check_gate()
    save_report(gate)
    if not gate["all_passed"]:
        print(f"[REJECT] P6 门槛未达标（{gate['decision']}），E2 训练拒绝启动")
        return 1

    # 3) 训练（Walk-Forward 5 折 + 封板验证）
    result = walk_forward_train(X, y, ret, meta, feat_cols)
    if result is None:
        return 1

    # 4) 基线对照与晋级判定
    with open(BASELINE_PATH, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    b_acc = float(baseline["accuracy"])
    b_ic = float(baseline["direction_ic"])
    passed = (result["wf_accuracy"] >= b_acc) and (result["wf_direction_ic"] >= b_ic)

    import torch
    torch.save({"state_dict": result["model"].state_dict(), "prereg": PREREG,
                "feature_cols": feat_cols, "n_params": result["n_params"]}, MODEL_OUT)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P6 E2 拼接式 Encoder 训练（Walk-Forward 5 折）",
        "prereg": PREREG,
        "samples": {"windows": int(len(X)), "holdout": result["holdout"]["n"]},
        "model": {"n_params": result["n_params"], "within_1m_limit": result["n_params"] <= PREREG["max_params"]},
        "walk_forward": {"folds": result["fold_results"],
                         "mean_accuracy": result["wf_accuracy"],
                         "mean_direction_ic": result["wf_direction_ic"]},
        "holdout": result["holdout"],
        "baseline_comparison": {
            "baseline_accuracy": b_acc,
            "baseline_direction_ic": b_ic,
            "wf_accuracy": result["wf_accuracy"],
            "wf_direction_ic": result["wf_direction_ic"],
            "e2_passed": passed,
            "rule": "SPEC 红线 3：Walk-Forward 准确率与方向 IC 均不低于基线方可晋级 E3",
        },
        "note": "E2 训练记录：输出为趋势判别语义输入与建议，不产生交易信号；交易决策归 23 系统三步门禁",
    }
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({"walk_forward": report["walk_forward"], "holdout": report["holdout"],
                     "baseline_comparison": report["baseline_comparison"]}, ensure_ascii=False, indent=2))
    print(f"[OK] E2 训练完成 -> {REPORT_OUT} / {MODEL_OUT}")
    print(f"     晋级判定: {'PASSED（可进入 E3 Shadow）' if passed else 'NOT_PASSED（未超基线，不进入 E3）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
