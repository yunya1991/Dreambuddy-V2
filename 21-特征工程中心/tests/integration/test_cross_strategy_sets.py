"""T17 · 跨策略3样例集合集成测试

验证 FeatureHub 跨策略复用能力：
  T17-1: btc_morph_v6 — BTC形态学4模块融合 → shape ≥ 40列，无 NaN
  T17-2: alt_trend_ensemble — 形态+Elder-ray+三屏跨域融合 → shape ≥ 60列，elder 5列one-hot存在
  T17-3: equity_classic_trend — 三屏+经典指标+五域 → shape ≥ 30列
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_21_ROOT = _PROJECT_ROOT / "21-特征工程中心"
for _p in [str(_21_ROOT), str(_21_ROOT / "feature_hub")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def btc_ohlcv():
    """样例 BTC 日线 OHLCV（300 根）"""
    rng = np.random.default_rng(42)
    n = 300
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.004, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.0, n)),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def _build_pipeline():
    """构建加载了 3 个样例集合的 FeaturePipeline"""
    from feature_hub.modules.loader import load_default_sets
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline

    pipe = FeaturePipeline()
    load_default_sets(pipe)
    return pipe


# ============================================================
# T17-1  btc_morph_v6 — BTC形态学 → shape ≥ 40，无 NaN
# ============================================================
def test_t17_1_btc_morph_v6(btc_ohlcv):
    fv = _build_pipeline().run(set_name="btc_morph_v6", df=btc_ohlcv, symbol="BTC")
    assert fv.df is not None
    assert len(fv.df.columns) >= 40, f"shape={len(fv.df.columns)} < 40"
    # 清洗后无 NaN
    nan_count = int(fv.df.isna().sum().sum())
    assert nan_count == 0, f"NaN={nan_count} > 0"
    assert fv.meta.get("set_name") == "btc_morph_v6"


# ============================================================
# T17-2  alt_trend_ensemble — 跨域融合 → shape ≥ 60，elder 5列存在
# ============================================================
def test_t17_2_alt_trend_ensemble(btc_ohlcv):
    fv = _build_pipeline().run(set_name="alt_trend_ensemble", df=btc_ohlcv, symbol="BTC")
    assert fv.df is not None
    assert len(fv.df.columns) >= 60, f"shape={len(fv.df.columns)} < 60"
    # elder_ray 5 列 one-hot 存在（带模块名前缀）
    elder_cols = [c for c in fv.df.columns if "elder_" in c and any(
        cat in c for cat in ("bullish_strong", "bullish", "neutral", "bearish", "bearish_strong")
    )]
    assert len(elder_cols) >= 5, f"elder one-hot cols={len(elder_cols)} < 5: {elder_cols}"


# ============================================================
# T17-3  equity_classic_trend — 三屏+经典+五域 → shape ≥ 30
# ============================================================
def test_t17_3_equity_classic_trend(btc_ohlcv):
    fv = _build_pipeline().run(set_name="equity_classic_trend", df=btc_ohlcv, symbol="AAPL")
    assert fv.df is not None
    assert len(fv.df.columns) >= 30, f"shape={len(fv.df.columns)} < 30"
