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

# R-42-04/P1-03：DREAMBUDDY_ROOT 环境变量统一模块根路径；未设置时按 __file__ 推导（仓库内模块同级布局）
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

BASE = os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统")
DCENTER = os.path.join(_DREAMBUDDY_ROOT, "18-数据获取中心")
TREND = os.path.join(_DREAMBUDDY_ROOT, "12-三屏趋势系统")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DCENTER)
sys.path.insert(0, TREND)

TOKEN_PATH = os.path.join(BASE, "token_sequence.parquet")
BASELINE_PATH = os.path.join(BASE, "baseline_metrics_v2.json")  # C1：同口径基线（2026-11-11 拍板）
BASELINE_LEGACY_PATH = os.path.join(BASE, "baseline_metrics.json")  # E1 旧口径基线（仅存档参考）
REPORT_OUT = os.path.join(BASE, "e2_training_report.json")
MODEL_OUT = os.path.join(BASE, "encoder_trend_model.pt")

# ── 预注册超参 v2（2026-11-11 PROPOSAL-E2-PREREG-CHANGE-v0.1 用户拍板变更，重新冻结）──
# v2 变更：B1 标签阈值按屏差异化 / B2 特征版本 v2 无量纲化 / B3 类别权重 / B4 熵正则 0.01→0.001
# 不变：n_layers=2, d_model=64, n_heads=4, ≤1M, 5 折, seq_len=32（B5/B6 本轮冻结），前瞻窗口, 20% 封板
PREREG = {
    "n_layers": 2,
    "d_model": 64,
    "n_heads": 4,
    "ffn_mult": 4,
    "n_classes": 3,
    "max_params": 1_000_000,
    "walk_forward_folds": 5,
    "seq_len": 32,  # 每样本 token 窗口长度
    "label_horizon": {"1W": 4, "1D": 7, "1H": 24},
    # B1：按屏差异化阈值（依据各屏 |前瞻收益| 分布 q33 取整：1W 7.42→7.0 / 1D 2.35→2.0 / 1H 0.71→0.75）
    "label_threshold_pct": {"1W": 7.0, "1D": 2.0, "1H": 0.75},
    "attn_entropy_reg": 0.001,  # B4：真注意力熵正则（A4 修复实现后）系数
    "class_weight": "balanced_train_fold",  # B3：按当前折训练段逆频率加权（封板段统计禁用）
    "feature_version_required": "classic_indicators_v2_dimensionless+ma200_v1",  # B2
    "lr": 1e-3,
    "epochs": 30,
    "batch_size": 64,
    "test_ratio": 0.2,  # 最近 20% 封板纯验证
    "seed": 42,
}
SYMBOLS = ["BTC", "ETH", "SOL"]
SCREENS = ["1W", "1D", "1H"]
META_COLS = ["symbol", "timeframe", "screen", "ts", "feature_version"]


def load_tokens() -> pd.DataFrame:
    df = pd.read_parquet(TOKEN_PATH)
    # B2：特征版本校验（E0 重生成后版本必须匹配，防止旧版特征混入）
    versions = set(df["feature_version"].unique())
    req = PREREG["feature_version_required"]
    if versions != {req}:
        raise RuntimeError(
            f"[REJECT] token 特征版本不匹配：{versions}，要求 {req}（请先重跑 p6_e0_token_sequence.py）"
        )
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
            thr = PREREG["label_threshold_pct"][bar] / 100.0  # B1：按屏差异化阈值
            lab = np.where(fut > thr, 1, np.where(fut < -thr, 2, 0))  # 0=N,1=UP,2=DOWN
            ts2lab = dict(zip(c["ts"], lab))  # noqa: B905
            ts2ret = dict(zip(c["ts"], fut))  # noqa: B905
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
            X.append(vals[end - L : end])
            y.append(int(row["label"]))
            ret.append(float(row["future_return"]))
            meta.append({"symbol": sym, "timeframe": bar, "ts": int(row["ts"])})
    return (
        np.asarray(X, dtype=np.float32),
        np.asarray(y),
        np.asarray(ret, dtype=np.float32),
        meta,
        feat_cols,
    )


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
            self.ffn = nn.Sequential(
                nn.Linear(d, d * PREREG["ffn_mult"]),
                nn.GELU(),
                nn.Linear(d * PREREG["ffn_mult"], d),
            )
            self.ln1 = nn.LayerNorm(d)
            self.ln2 = nn.LayerNorm(d)
            self.last_attn = None  # A4：保留真实注意力权重供熵正则使用

        def forward(self, x):
            a, w = self.attn(x, x, x, need_weights=True, average_attn_weights=False)
            self.last_attn = w  # (B, heads, T, T)
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


def attn_entropy_loss(model) -> "torch.Tensor":  # noqa: F821
    """A4 修复：真注意力熵正则。对每块多头注意力分布计算平均熵 H(p)，
    损失项取 -coeff * H（最大化熵，鼓励注意力分布不过度集中，SPEC §1.4）。
    v1 误实现为 in_proj_weight 的 L2 范数，与预注册语义不符，已废弃。"""

    import torch

    ent = None
    n = 0
    for blk in model.blocks:
        w = blk.last_attn
        if w is None:
            continue
        p = w.clamp_min(1e-9)
        h = -(p * p.log()).sum(dim=-1).mean()  # 熵在最后一维（注意力分布维）求和
        ent = h if ent is None else ent + h
        n += 1
    if ent is None:
        return torch.tensor(0.0)
    return -PREREG["attn_entropy_reg"] * (ent / n)


def _train_epochs(model, X_t, y_t, tf_t, idx, lossf):
    """单模型在给定训练索引上训练 PREREG['epochs'] 轮（batch 内 SGD 洗牌不算时序泄漏）。"""
    import torch

    opt = torch.optim.Adam(model.parameters(), lr=PREREG["lr"])
    for _ep in range(PREREG["epochs"]):
        model.train()
        perm = np.random.permutation(len(idx))
        for s in range(0, len(perm), PREREG["batch_size"]):
            bidx = idx[perm[s : s + PREREG["batch_size"]]]
            logits = model(X_t[bidx], tf_t[bidx])
            loss = lossf(logits, y_t[bidx]) + attn_entropy_loss(model)
            # A5：NaN 防护——出现非有限损失立即失败，禁止带病训练（v1 全网 NaN 教训）
            if not torch.isfinite(loss):
                raise RuntimeError("[FAIL] 训练损失非有限（NaN/Inf），中止——检查特征 NaN 与标准化")
            opt.zero_grad()
            loss.backward()
            opt.step()


def _eval_model(model, X_t, tf_t, y_true, ret_true):
    """评估：准确率 + direction IC（P(UP) 与未来收益的 Spearman）。"""
    import torch
    from scipy.stats import spearmanr

    model.eval()
    with torch.no_grad():
        lv = model(X_t, tf_t)
        pred = lv.argmax(dim=1).numpy()
        prob_up = torch.softmax(lv, dim=1)[:, 1].numpy()
    acc = float(np.mean(pred == y_true))
    m = ~np.isnan(ret_true)
    ic = float(spearmanr(prob_up[m], ret_true[m]).statistic) if m.sum() >= 10 else 0.0
    if ic != ic:
        ic = 0.0
    return acc, ic, pred


def walk_forward_train(X, y, ret, meta, feat_cols):
    """Walk-Forward 5 折（A2 修复：真扩张窗，仅用历史训练，禁止随机打乱时序）；
    最近 20% 封板纯验证（由独立最终模型评估，A3：每折模型全新初始化）。"""
    import torch
    import torch.nn as nn

    np.random.seed(PREREG["seed"])

    n = len(X)
    order = np.argsort([m["ts"] for m in meta])  # 全局按时间排序
    X, y, ret = X[order], y[order], ret[order]

    n_test = max(1, int(n * PREREG["test_ratio"]))
    X_hold, y_hold, ret_hold = X[-n_test:], y[-n_test:], ret[-n_test:]
    X_tr, y_tr, ret_tr = X[:-n_test], y[:-n_test], ret[:-n_test]

    # 特征标准化（仅用训练段统计量，防泄漏；A5：NaN 列用 nanmean/nanstd，残余 NaN→0=列均值中性值）
    flat = X_tr.reshape(-1, X.shape[2])
    mu = np.nanmean(flat, axis=0)
    sd = np.nanstd(flat, axis=0) + 1e-8
    mu = np.where(np.isfinite(mu), mu, 0.0)
    sd = np.where(np.isfinite(sd), sd, 1.0)
    X_tr = np.nan_to_num((X_tr - mu) / sd, nan=0.0)
    X_hold = np.nan_to_num((X_hold - mu) / sd, nan=0.0)
    # A5：入口硬校验——v1 因 1W/1H 屏 ma200 列全 NaN 致全网权重 NaN，禁止复发
    assert np.isfinite(X_tr).all() and np.isfinite(X_hold).all(), "[FAIL] 特征含非有限值"

    tf_map = {"1W": 0, "1D": 1, "1H": 2}
    meta_sorted = [meta[i] for i in order]
    tf_all = np.array([tf_map[m["timeframe"]] for m in meta_sorted], dtype=np.int64)
    tf_tr, tf_hold = tf_all[:-n_test], tf_all[-n_test:]

    # 参数量红线校验（用临时模型）
    probe = build_model(X.shape[2])
    n_params = count_params(probe)
    del probe
    if n_params > PREREG["max_params"]:
        print(f"[REJECT] 参数量 {n_params} 超过 1M 红线")
        return None

    folds = PREREG["walk_forward_folds"]
    Xtr_t = torch.from_numpy(X_tr)
    tftr_t = torch.from_numpy(tf_tr)

    def _make_lossf(y_seg):
        # B3：类别权重 = 当前（折）训练段逆频率，时序安全
        cnt = np.bincount(y_seg, minlength=PREREG["n_classes"]).astype(np.float64)
        w = len(y_seg) / (PREREG["n_classes"] * np.maximum(cnt, 1.0))
        return nn.CrossEntropyLoss(weight=torch.from_numpy(w).float())

    # A2 真 Walk-Forward 扩张窗：训练段切成 folds+1 段，
    # 折 k 用 [0, edges[k]) 训练、[edges[k], edges[k+1]) 验证——仅用验证段之前的历史
    edges = np.linspace(0, len(X_tr), folds + 2).astype(int)
    fold_results = []
    for k in range(1, folds + 1):
        tr_idx = np.arange(0, edges[k])
        va_idx = np.arange(edges[k], edges[k + 1])
        if len(tr_idx) < 50 or len(va_idx) < 10:
            continue
        # A3：每折全新初始化模型（固定种子保证可复现），禁止跨折累计训练
        torch.manual_seed(PREREG["seed"])
        model = build_model(X.shape[2])
        _train_epochs(
            model, Xtr_t, torch.from_numpy(y_tr).long(), tftr_t, tr_idx, _make_lossf(y_tr[tr_idx])
        )
        acc, ic, _pred = _eval_model(
            model, Xtr_t[va_idx], tftr_t[va_idx], y_tr[va_idx], ret_tr[va_idx]
        )
        fold_results.append(
            {
                "fold": k - 1,
                "train_n": int(len(tr_idx)),
                "valid_n": int(len(va_idx)),
                "accuracy": acc,
                "direction_ic": ic,
            }
        )
        print(f"  [fold {k-1}] train={len(tr_idx)} valid={len(va_idx)} acc={acc:.4f} ic={ic:.4f}")

    # 最终模型：用全部训练段（80%）重训，用于封板纯验证与落盘
    torch.manual_seed(PREREG["seed"])
    final_model = build_model(X.shape[2])
    all_idx = np.arange(len(X_tr))
    _train_epochs(
        final_model, Xtr_t, torch.from_numpy(y_tr).long(), tftr_t, all_idx, _make_lossf(y_tr)
    )
    hold_acc, hold_ic, pred = _eval_model(
        final_model, torch.from_numpy(X_hold), torch.from_numpy(tf_hold), y_hold, ret_hold
    )

    return {
        "model": final_model,
        "n_params": n_params,
        "fold_results": fold_results,
        "wf_accuracy": (
            float(np.mean([f["accuracy"] for f in fold_results])) if fold_results else 0.0
        ),
        "wf_direction_ic": (
            float(np.mean([f["direction_ic"] for f in fold_results])) if fold_results else 0.0
        ),
        "holdout": {
            "n": int(n_test),
            "accuracy": hold_acc,
            "direction_ic": hold_ic,
            "class_dist": {
                "UP": int((pred == 1).sum()),
                "DOWN": int((pred == 2).sum()),
                "NEUTRAL": int((pred == 0).sum()),
            },
        },
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
    print(
        f"     标签分布: UP={int((y==1).sum())} DOWN={int((y==2).sum())} NEUTRAL={int((y==0).sum())}"
    )

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

    # 4) 基线对照与晋级判定（C1：同口径基线 baseline_metrics_v2.json）
    if not os.path.exists(BASELINE_PATH):
        print(
            "[REJECT] 同口径基线缺失，请先运行 p6_e1b_aligned_baseline.py 生成 baseline_metrics_v2.json"
        )
        return 1
    with open(BASELINE_PATH, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    b_acc = float(baseline["accuracy"])
    b_ic = float(baseline["direction_ic"])
    passed = (result["wf_accuracy"] >= b_acc) and (result["wf_direction_ic"] >= b_ic)

    import torch

    torch.save(
        {
            "state_dict": result["model"].state_dict(),
            "prereg": PREREG,
            "feature_cols": feat_cols,
            "n_params": result["n_params"],
        },
        MODEL_OUT,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P6 E2 拼接式 Encoder 训练（Walk-Forward 5 折）",
        "prereg": PREREG,
        "samples": {"windows": int(len(X)), "holdout": result["holdout"]["n"]},
        "model": {
            "n_params": result["n_params"],
            "within_1m_limit": result["n_params"] <= PREREG["max_params"],
        },
        "walk_forward": {
            "folds": result["fold_results"],
            "mean_accuracy": result["wf_accuracy"],
            "mean_direction_ic": result["wf_direction_ic"],
        },
        "holdout": result["holdout"],
        "baseline_comparison": {
            "baseline_source": "baseline_metrics_v2.json（C1 同口径：同数据/同标签/同 Walk-Forward 切分）",
            "baseline_accuracy": b_acc,
            "baseline_direction_ic": b_ic,
            "wf_accuracy": result["wf_accuracy"],
            "wf_direction_ic": result["wf_direction_ic"],
            "e2_passed": passed,
            "rule": "SPEC 红线 3（C1 口径）：Walk-Forward 准确率与方向 IC 均不低于同口径基线方可晋级 E3",
        },
        "note": "E2 训练记录：输出为趋势判别语义输入与建议，不产生交易信号；交易决策归 23 系统三步门禁",
    }
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                "walk_forward": report["walk_forward"],
                "holdout": report["holdout"],
                "baseline_comparison": report["baseline_comparison"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"[OK] E2 训练完成 -> {REPORT_OUT} / {MODEL_OUT}")
    print(
        f"     晋级判定: {'PASSED（可进入 E3 Shadow）' if passed else 'NOT_PASSED（未超基线，不进入 E3）'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
