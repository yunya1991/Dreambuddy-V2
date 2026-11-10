#!/usr/bin/env python3
"""P6 C1 同口径基线：LightGBM 在与 E2 完全相同的数据/标签/Walk-Forward 切分下重测。
依据：docs/PROPOSAL-E2-PREREG-CHANGE-v0.1.md C1 项（2026-11-11 用户拍板）——
  E1 旧基线（BTC 单资产日线、162 样本 eval 32、acc 0.75）与 E2 任务口径不对等，
  红线 3 的比较对象替换为本脚本产出的同口径基线（baseline_metrics_v2.json）。
口径对齐声明：
  - 数据管道：复用 p6_e2_train_encoder 的 load_tokens / build_labels / make_windows
    （同 token 序列 v2 特征、同按屏标签阈值、同前瞻窗口）
  - 切分：全局按时间排序 → 最近 20% 封板 → 训练段扩张窗 5 折（与 E2 逐边一致）
  - 类别权重：class_weight="balanced"（对齐 E2 B3 的折训练段逆频率语义）
  - 指标：accuracy + direction IC（P(UP) 与未来收益 Spearman，与 E2 同定义）
模型差异说明：LightGBM 原生处理 NaN，无需标准化（树模型对单调变换不变），
  窗口展平 (seq_len × n_features) 输入——这是模型特性差异，非口径差异。
红线：基线仅作 E2 晋级判定参照，不产生交易信号。
"""

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
BASE = os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统")
sys.path.insert(0, os.path.join(BASE, "scripts"))
sys.path.insert(0, os.path.join(_DREAMBUDDY_ROOT, "18-数据获取中心"))

from p6_e2_train_encoder import PREREG, build_labels, load_tokens, make_windows  # noqa: E402

OUT_PATH = os.path.join(BASE, "baseline_metrics_v2.json")

# LightGBM 超参（一次性预注册，冻结）
LGB_PARAMS = {
    "n_estimators": 200,
    "num_leaves": 31,
    "learning_rate": 0.05,
    "class_weight": "balanced",
    "random_state": PREREG["seed"],
    "verbose": -1,
}


def main() -> int:
    import lightgbm as lgb
    from scipy.stats import spearmanr

    tokens = load_tokens()
    labeled = build_labels(tokens)
    if labeled.empty:
        print("[FAIL] 无有效标注样本")
        return 1
    X, y, ret, meta, feat_cols = make_windows(labeled)
    print(f"[OK] 同口径窗口样本: {len(X)}（特征 {len(feat_cols)} 列，窗口 {PREREG['seq_len']}）")

    n = len(X)
    order = np.argsort([m["ts"] for m in meta])
    X, y, ret = X[order], y[order], ret[order]

    n_test = max(1, int(n * PREREG["test_ratio"]))
    X_hold, y_hold, ret_hold = X[-n_test:], y[-n_test:], ret[-n_test:]
    X_tr, y_tr, ret_tr = X[:-n_test], y[:-n_test], ret[:-n_test]

    def _flat(a):
        return a.reshape(len(a), -1)

    def _train_eval(tr_idx, va_idx):
        clf = lgb.LGBMClassifier(**LGB_PARAMS)
        clf.fit(_flat(X_tr[tr_idx]), y_tr[tr_idx])
        prob = clf.predict_proba(_flat(X_tr[va_idx]))
        up_col = list(clf.classes_).index(1)
        pred = clf.classes_[np.argmax(prob, axis=1)]
        acc = float(np.mean(pred == y_tr[va_idx]))
        m = ~np.isnan(ret_tr[va_idx])
        ic = (
            float(spearmanr(prob[:, up_col][m], ret_tr[va_idx][m]).statistic)
            if m.sum() >= 10
            else 0.0
        )
        return acc, (ic if ic == ic else 0.0)

    # 与 E2 完全一致的扩张窗 5 折
    folds = PREREG["walk_forward_folds"]
    edges = np.linspace(0, len(X_tr), folds + 2).astype(int)
    fold_results = []
    for k in range(1, folds + 1):
        tr_idx = np.arange(0, edges[k])
        va_idx = np.arange(edges[k], edges[k + 1])
        if len(tr_idx) < 50 or len(va_idx) < 10:
            continue
        acc, ic = _train_eval(tr_idx, va_idx)
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

    # 封板段（参考指标，晋级判定以 Walk-Forward 为准）
    clf = lgb.LGBMClassifier(**LGB_PARAMS)
    clf.fit(_flat(X_tr), y_tr)
    prob = clf.predict_proba(_flat(X_hold))
    up_col = list(clf.classes_).index(1)
    pred = clf.classes_[np.argmax(prob, axis=1)]
    hold_acc = float(np.mean(pred == y_hold))
    m = ~np.isnan(ret_hold)
    hold_ic = float(spearmanr(prob[:, up_col][m], ret_hold[m]).statistic) if m.sum() >= 10 else 0.0

    wf_acc = float(np.mean([f["accuracy"] for f in fold_results])) if fold_results else 0.0
    wf_ic = float(np.mean([f["direction_ic"] for f in fold_results])) if fold_results else 0.0

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P6 C1 同口径基线（LightGBM，对齐 E2 数据/标签/切分）",
        "protocol": {
            "data": "token_sequence.parquet v2（3 资产 × 3 屏），标签按屏阈值（B1），前瞻窗口同 PREREG",
            "split": "时间排序 → 最近 20% 封板 → 训练段扩张窗 5 折（与 E2 逐边一致）",
            "lgb_params": LGB_PARAMS,
            "nan_policy": "LightGBM 原生处理（树模型对单调变换不变，不标准化）",
        },
        "samples": {"windows": int(n), "holdout": int(n_test)},
        "walk_forward": {
            "folds": fold_results,
            "mean_accuracy": wf_acc,
            "mean_direction_ic": wf_ic,
        },
        "holdout": {"n": int(n_test), "accuracy": hold_acc, "direction_ic": hold_ic},
        "accuracy": wf_acc,  # 晋级判定字段（与 E2 baseline_comparison 消费对齐）
        "direction_ic": wf_ic,
        "note": "C1 同口径基线：替代 E1 旧口径（BTC 单资产日线 32 评估样本 acc 0.75），"
        "作为红线 3 的比较对象；不产生交易信号",
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[OK] 同口径基线 -> {OUT_PATH}")
    print(
        f"     Walk-Forward: acc={wf_acc:.4f} ic={wf_ic:.4f} | 封板: acc={hold_acc:.4f} ic={hold_ic:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
