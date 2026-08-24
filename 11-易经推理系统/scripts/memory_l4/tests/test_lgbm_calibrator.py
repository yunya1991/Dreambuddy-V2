"""Phase 1 TDD 测试 · LGBMCalibrator 概率校正器

覆盖验收：
  T11) test_lgbm_calibrator_fusion_effect      — 用合成不平衡 8 态数据 fit；p_out 对 p_gauss 的 JS 散度 ≥ 0.02（证明融合真的生效而非 0.4 权重被淹）；
                                                  p_out 所有帧 Σ=1；shape = (n,8)。
  T13d) test_lgbm_schema_mismatch_must_raise    — schema 存的列顺序/列数与推理传入不同 → 必须抛 ValueError（静默 reindex/fillna 都禁止）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))

REGIME_ORDER = [
    "RANGE_BOUND", "CONSOLIDATION", "ACCUMULATION",
    "RECOVERY_MILD", "TREND_UP_MILD", "TREND_UP_STRONG",
    "FOMO_RALLY", "VOLATILE_DROP",
]


# ================================================================
# 辅助：构造合成 (X, y) 和 p_gauss
# ================================================================
def _make_synthetic_X_y(n=800):
    rng = np.random.default_rng(42)
    # 8 个聚类中心，每类 100 条
    n_per = n // 8
    centers = np.array([
        [0.0, 0.0],      # RANGE_BOUND
        [-1.0, -0.5],    # CONSOLIDATION
        [-2.0, +0.2],    # ACCUMULATION
        [+0.5, +1.0],    # RECOVERY_MILD
        [+1.5, +1.5],    # TREND_UP_MILD
        [+2.5, +2.0],    # TREND_UP_STRONG
        [+3.0, +3.5],    # FOMO_RALLY
        [-2.5, -2.0],    # VOLATILE_DROP
    ], dtype=float)
    feats = []
    labels = []
    for i, (lx, ly) in enumerate(centers):
        x = rng.normal(loc=lx, scale=0.7, size=n_per)
        y = rng.normal(loc=ly, scale=0.7, size=n_per)
        feats.append(np.c_[x, y, x*y, x**2, y**2])   # 5 特征
        labels.extend([REGIME_ORDER[i]] * n_per)
    X = np.vstack(feats)
    X_df = pd.DataFrame(X, columns=[f"feat_{k}" for k in range(X.shape[1])])
    # 加一些随机列模拟 LGBM pool 的特征（防止 overfit）
    for j in range(8):
        X_df[f"noise_{j}"] = rng.normal(0, 1, len(X_df))
    y_s = pd.Series(labels)
    # 构造 p_gauss：8 态概率分布，故意和真实聚类反一点，这样融合后能看出差异
    p_gauss = np.ones((n, 8), dtype=float) / 8.0
    for i in range(8):
        # 给 RANGE_BOUND 中心类别一个假的"偏向 CONSOLIDATION"偏移，让 LGBM 能校正过来
        if i == 0:
            p_gauss[i*n_per:(i+1)*n_per, 0] = 0.45
            p_gauss[i*n_per:(i+1)*n_per, 1] = 0.35  # 错放偏 1
        elif i == 6:  # FOMO_RALLY 高斯偏成 TREND_UP_STRONG
            p_gauss[i*n_per:(i+1)*n_per, 6] = 0.40
            p_gauss[i*n_per:(i+1)*n_per, 5] = 0.35
        else:
            p_gauss[i*n_per:(i+1)*n_per, i] = 0.40
    # 归一
    p_gauss = p_gauss / p_gauss.sum(1, keepdims=True)
    return X_df, y_s, p_gauss


def _js_divergence(p: np.ndarray, q: np.ndarray) -> float:
    eps = 1e-12
    m = 0.5 * (p + q)
    def kld(a, b):
        return (a * np.log((a + eps) / (b + eps))).sum(axis=1)
    js = 0.5 * kld(p, m) + 0.5 * kld(q, m)
    return float(js.mean())


# ================================================================
# T11) 融合生效
# ================================================================
def test_lgbm_calibrator_fusion_effect():
    from bcrm2.lgbm_calibrator import LGBMCalibrator
    X, y, p_gauss = _make_synthetic_X_y()
    cal = LGBMCalibrator()
    with tempfile.TemporaryDirectory() as td:
        schema_path = Path(td) / "schema.json"
        cal.fit(X, y, schema_path=str(schema_path))
        # schema 必须存在且是 JSON
        assert schema_path.exists()
        sc = json.loads(schema_path.read_text())
        assert sc["feature_names_in_order"] == list(X.columns), "schema 保存的列顺序必须严格 == fit 时顺序"
        # 推理
        p_out = cal.calibrate(p_gauss, X)
        assert p_out.shape == (len(X), 8), f"shape 应为 (n,8)，实际 {p_out.shape}"
        sums = p_out.sum(axis=1)
        assert np.allclose(sums, 1.0, atol=1e-6), f"p_out 不归一：sum min/max={sums.min():.5f}/{sums.max():.5f}"
        js = _js_divergence(p_gauss, p_out)
        assert js >= 0.02, f"融合 JS 散度={js:.4f} < 0.02，融合没有真正生效（权重淹了？）"


# ================================================================
# T13d) schema 不匹配必须抛 ValueError（列顺序/列数/缺失列）
# ================================================================
def test_lgbm_schema_mismatch_must_raise():
    from bcrm2.lgbm_calibrator import LGBMCalibrator
    X, y, p_gauss = _make_synthetic_X_y(n=160)
    cal = LGBMCalibrator()
    with tempfile.TemporaryDirectory() as td:
        schema_path = Path(td) / "schema.json"
        cal.fit(X, y, schema_path=str(schema_path))
        # 1) 列顺序翻转 → ValueError
        X_rev = X.iloc[:, ::-1].copy()
        with pytest.raises(ValueError, match="schema.*col"):
            cal.calibrate(p_gauss, X_rev)
        # 2) 少 1 列 → ValueError
        X_less = X.iloc[:, :-1].copy()
        with pytest.raises(ValueError, match="schema.*col"):
            cal.calibrate(p_gauss, X_less)
        # 3) 多 1 列 → ValueError
        X_more = X.copy()
        X_more["extra_col"] = 0.0
        with pytest.raises(ValueError, match="schema.*col"):
            cal.calibrate(p_gauss, X_more)
        # 4) 正确的列顺序 → 不抛错
        cal.calibrate(p_gauss, X)
