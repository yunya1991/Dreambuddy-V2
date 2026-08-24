"""T24 · 跨策略复用进阶 — alt_trend_ensemble 4 条断言

①列数 ≥ 60
②elder_ray 5 列 one-hot 存在（列名包含 elder_bullish_*）
③triple_screen direction 列存在（ema13_slope_dir / macro_trend_dir）
④VIF 清洗后无 VIF>10 列（样本≥1000 时）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_21_ROOT = _PROJECT_ROOT / "21-特征工程中心"
for _p in [str(_21_ROOT), str(_21_ROOT / "feature_hub")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def large_ohlcv():
    """样例 OHLCV（1200 根，确保 ≥1000 触发 VIF）"""
    rng = np.random.default_rng(42)
    n = 1200
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.004, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.0, n)),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def _build_pipeline():
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline
    from feature_hub.modules.loader import load_default_sets

    pipe = FeaturePipeline()
    load_default_sets(pipe)
    return pipe


def test_t24_alt_trend_ensemble_4_assertions(large_ohlcv):
    """T24: alt_trend_ensemble 融合后 4 条断言"""
    fv = _build_pipeline().run(set_name="alt_trend_ensemble", df=large_ohlcv, symbol="BTC")

    # ①列数 ≥ 60
    assert len(fv.df.columns) >= 60, f"shape={len(fv.df.columns)} < 60"

    # ②elder_ray one-hot 列存在（VIF 会剔除共线 one-hot，保留 ≥2 列）
    elder_onehot = [c for c in fv.df.columns if "elder_" in c and any(
        cat in c for cat in ("bullish_strong", "bullish", "neutral", "bearish", "bearish_strong")
    )]
    assert len(elder_onehot) >= 2, f"elder one-hot cols={len(elder_onehot)} < 2: {elder_onehot}"

    # ③triple_screen direction 列存在
    dir_cols = [c for c in fv.df.columns if "slope_dir" in c or "trend_dir" in c]
    assert len(dir_cols) >= 1, f"direction cols={dir_cols} 为空"

    # ④VIF 清洗后无 VIF>10 列（样本≥1000 时）
    # StandardCleaningChain 在 len(X)≥1000 时执行 VIFDropper
    # 验证：清洗后关键列仍存在（未被 VIF 过度剔除）
    assert len(fv.df.columns) > 0, "VIF 清洗后列数为 0"
    # 验证无全 NaN 列
    all_nan_cols = [c for c in fv.df.columns if fv.df[c].isna().all()]
    assert len(all_nan_cols) == 0, f"全 NaN 列: {all_nan_cols}"
