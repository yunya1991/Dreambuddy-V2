"""train_lgbm_calibrator_v4.py — Phase 1：用 FeatureRegistry v4 特征池训练 LGBMCalibrator

用法：
    python train_lgbm_calibrator_v4.py \
        --csv BTC_1D_full.csv \
        --out-dir artifacts/lgbm_calibrator_btc_v4 \
        [--feature-set btc_morphology_v4] \
        [--forward-days 20] [--lookback 252] \
        [--num-leaves 31] [--max-depth 8] \
        [--reg-alpha 0.5] [--reg-lambda 2.0]

产出：
    <out-dir>/
        calibrator.joblib   # LGBMCalibrator 完整实例（含 LGBM model）
        schema.json         # feature_names_in_order / regime_order / n_features / n_classes / hyperparams
        train_report.json   # 训练概况：样本数、类别分布、Top-1 acc、Macro F1 估计
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

_THIS_FILE = Path(__file__).resolve()
_BCRM2_DIR = _THIS_FILE.parent
_MEMORY_L4_DIR = _BCRM2_DIR.parent
if str(_MEMORY_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_MEMORY_L4_DIR))


# ================================================================
# 训练核心
# ================================================================
def _load_csv(csv_path: Path) -> pd.DataFrame:
    from bcrm2.run_evolution_pipeline import _read_csv  # 复用
    return _read_csv(csv_path)


def _build_features(df: pd.DataFrame, feature_set: str) -> pd.DataFrame:
    """调用 FeatureRegistry.compute_all(enabled_set=...) 批量计算特征。

    返回 DataFrame，列 = feature_names_in_order。
    """
    # 显式 import 所有 v4/v5/v6 涉及的特征模块，触发 FeatureRegistry.register
    import importlib as _il
    for _mod_name in ("classic_experience_features", "ma200_cycle_features",
                       "multi_timeframe_features", "rolling_regime_stats",
                       "sector_beta_pool"):
        try:
            _il.import_module(f"bcrm2.{_mod_name}")
        except Exception:
            pass
    from bcrm2.feature_registry import FeatureRegistry
    feats_df, _gua_map = FeatureRegistry.compute_all(df, enabled_set=feature_set, verbose=False)
    if not isinstance(feats_df, pd.DataFrame):
        raise TypeError(f"FeatureRegistry.compute_all(enabled_set={feature_set!r}) 返回不是 DataFrame：{type(feats_df)}")
    return feats_df


def _build_labels(df: pd.DataFrame, forward_days: int, lookback: int) -> pd.Series:
    from bcrm2.labels.regime_labeler import generate_8state_label
    y = generate_8state_label(df, forward_days=forward_days, lookback=lookback)
    return y


def train(
    csv_path: Path,
    out_dir: Path,
    feature_set: str = "btc_morphology_v5",
    forward_days: int = 20,
    lookback: int = 252,
    num_leaves: int = 31,
    max_depth: int = 8,
    reg_alpha: float = 0.5,
    reg_lambda: float = 2.0,
    n_estimators: int = 200,
    learning_rate: float = 0.05,
    random_state: int = 42,
) -> Tuple[Path, dict]:
    """训练 LGBMCalibrator 并落盘。返回 (out_dir, report_dict)。"""
    # 1) 数据
    print(f"[train] 读取 {csv_path}", flush=True)
    df = _load_csv(csv_path)
    print(f"[train] 数据形状 {df.shape}，区间 {df.index[0]} → {df.index[-1]}", flush=True)

    # 2) 特征
    print(f"[train] 计算特征集 {feature_set}", flush=True)
    X = _build_features(df, feature_set)
    print(f"[train] 特征形状 {X.shape}，列 {list(X.columns)[:5]}... 共 {len(X.columns)} 列", flush=True)
    if X.shape[1] < 3:  # pragma: no cover
        raise RuntimeError(f"特征仅 {X.shape[1]} 列，数量异常（需 ≥ 3）")

    # 3) 标签
    print(f"[train] 生成 8 态标签（forward={forward_days}d lookback={lookback}d）", flush=True)
    y = _build_labels(df, forward_days, lookback)

    # 4) 对齐有效行
    aligned_idx = X.index.intersection(y.index)
    valid_mask = y.reindex(aligned_idx).notna() & X.reindex(aligned_idx).notna().all(axis=1)
    valid_idx = aligned_idx[valid_mask]
    if len(valid_idx) < 100:
        raise RuntimeError(
            f"有效训练样本仅 {len(valid_idx)} < 100。请扩大 CSV 长度或减小 lookback/forward_days。"
        )
    X_train = X.reindex(valid_idx)
    y_train = y.reindex(valid_idx)
    print(f"[train] 有效训练样本 {len(X_train)}，y 分布：", flush=True)
    dist = y_train.value_counts().sort_index()
    for k, v in dist.items():
        print(f"        {k:22s} {int(v):5d}  {100*v/len(y_train):5.1f}%", flush=True)

    # 5) 训练
    from bcrm2.lgbm_calibrator import LGBMCalibrator
    from bcrm2.labels.regime_labeler import REGIME_ORDER
    schema_path = out_dir / "schema.json"
    cal = LGBMCalibrator(random_state=random_state)
    print(f"[train] fit 开始：n_estimators={n_estimators} lr={learning_rate} "
          f"num_leaves={num_leaves} max_depth={max_depth} L1={reg_alpha} L2={reg_lambda}", flush=True)
    cal.fit(
        X_train, y_train, schema_path=str(schema_path),
        num_leaves=num_leaves, max_depth=max_depth,
        reg_alpha=reg_alpha, reg_lambda=reg_lambda,
        n_estimators=n_estimators, learning_rate=learning_rate,
        regime_order=list(REGIME_ORDER),
    )

    # 6) 保存
    saved = cal.save(str(out_dir))
    print(f"[train] 模型已保存 → {saved}", flush=True)

    # 7) 训练报告（Top-1 acc / confusion 概要）
    # 注意：这里用训练集评估只是 smoke-level 展示，真实评估走 WalkForward（Spec §Phase3）
    # 这里用 LGBM 原生 predict_proba 做 argmax（非 calibrate 输出）
    p_lgbm = cal._model.predict_proba(X_train.values) if cal._model is not None else None
    top1_cls = None
    if p_lgbm is not None:
        top1_idx = p_lgbm.argmax(axis=1)
        top1_cls = np.array([cal.regime_order[i] for i in top1_idx])
        acc = (top1_cls == y_train.values.astype(str)).mean()

        # Macro F1（sklearn，避免无依赖硬算）
        try:
            from sklearn.metrics import f1_score
            macro_f1 = float(f1_score(y_train.values.astype(str), top1_cls, average="macro", zero_division=0))
        except Exception:  # pragma: no cover
            macro_f1 = float("nan")
    else:  # pragma: no cover
        acc = float("nan")
        macro_f1 = float("nan")

    report = {
        "csv": str(csv_path),
        "feature_set": feature_set,
        "n_samples": int(len(X_train)),
        "n_features": int(X.shape[1]),
        "regime_order": list(cal.regime_order),
        "label_distribution": {str(k): int(v) for k, v in dist.items()},
        "train_top1_acc": round(float(acc), 4) if top1_cls is not None else None,
        "train_macro_f1": round(float(macro_f1), 4) if top1_cls is not None else None,
        "hyperparams": {
            "num_leaves": num_leaves, "max_depth": max_depth,
            "reg_alpha": reg_alpha, "reg_lambda": reg_lambda,
            "n_estimators": n_estimators, "learning_rate": learning_rate,
            "random_state": random_state,
        },
        "output_dir": str(saved),
    }
    (out_dir / "train_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[train] 报告 → {out_dir / 'train_report.json'}", flush=True)
    if top1_cls is not None:
        print(f"[train] 训练集 Top-1 Acc={acc:.3f}  Macro F1={macro_f1:.3f}", flush=True)
    return out_dir, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Train LGBMCalibrator v4 (FeatureRegistry × LGBM log-odds mix)")
    ap.add_argument("--csv", required=True, help="BTC 日线 OHLCV CSV")
    ap.add_argument("--out-dir", required=True, help="输出目录（存放 calibrator.joblib / schema.json / train_report.json）")
    ap.add_argument("--feature-set", default="btc_morphology_v5",
                    help="FeatureRegistry 启用集（默认 btc_morphology_v5 = morphology_core + ma200_cycle + multi_timeframe，LGBM 特征池仅含前 3 模块，不含 rolling_regime_stats/sector_beta_pool 以防标签泄露）")
    ap.add_argument("--forward-days", type=int, default=20, help="三重障碍前瞻天数（y 标签生成）")
    ap.add_argument("--lookback", type=int, default=252, help="三重障碍回看窗口")
    ap.add_argument("--num-leaves", type=int, default=31)
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--reg-alpha", type=float, default=0.5, help="L1 正则")
    ap.add_argument("--reg-lambda", type=float, default=2.0, help="L2 正则")
    ap.add_argument("--n-estimators", type=int, default=200)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    csv_p = Path(args.csv).expanduser().resolve()
    out_p = Path(args.out_dir).expanduser().resolve()
    if not csv_p.exists():
        print(f"[error] CSV 不存在: {csv_p}", file=sys.stderr)
        return 2
    try:
        train(
            csv_path=csv_p,
            out_dir=out_p,
            feature_set=args.feature_set,
            forward_days=args.forward_days,
            lookback=args.lookback,
            num_leaves=args.num_leaves,
            max_depth=args.max_depth,
            reg_alpha=args.reg_alpha,
            reg_lambda=args.reg_lambda,
            n_estimators=args.n_estimators,
            learning_rate=args.learning_rate,
            random_state=args.seed,
        )
    except Exception as e:
        print(f"[train] FAILED：{e}", file=sys.stderr)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
