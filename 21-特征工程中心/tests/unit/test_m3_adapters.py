"""T23 · 剩余 Adapter 补完测试

T23-1: Classic Indicators — 3类资产输出≥10列 + 两次调用等价
T23-2: Martin Features — 5列（DD/martin_level/grid_profit）+ 等价
T23-3: Fundamental Ratios — ≥8列 无NaN + 等价
T23-4: commodity_safe_haven 集合存在
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


def _make_ohlcv(n: int = 300, base_price: float = 50000) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = base_price * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.004, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.0, n)),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


# ============================================================
# T23-1  Classic Indicators — ≥10列 + 等价
# ============================================================
@pytest.mark.parametrize("asset,base", [("BTC", 50000), ("COIN", 200), ("XAU", 2000)])
def test_t23_1_classic_indicators(asset, base):
    from feature_hub.modules.classic_indicators import compute

    ohlcv = _make_ohlcv(300, base)
    feats = compute(ohlcv)

    assert len(feats.columns) >= 10, f"columns={len(feats.columns)} < 10"
    # 两次调用等价
    feats2 = compute(ohlcv)
    for col in feats.columns:
        diff = (feats[col] - feats2[col]).abs().max()
        assert diff < 1e-9, f"列 {col} 两次调用不等价: diff={diff}"


# ============================================================
# T23-2  Martin Features — 5列 + 等价
# ============================================================
def test_t23_2_martin_features():
    from feature_hub.modules.martin_features import compute

    ohlcv = _make_ohlcv(300)
    feats = compute(ohlcv)

    assert len(feats.columns) >= 5, f"columns={len(feats.columns)} < 5"
    for must in ("drawdown_depth", "martin_level", "grid_profit"):
        assert must in feats.columns, f"缺列 {must}"
    # 等价
    feats2 = compute(ohlcv)
    for col in feats.columns:
        diff = (feats[col] - feats2[col]).abs().max()
        assert diff < 1e-9, f"列 {col} 不等价: diff={diff}"


# ============================================================
# T23-3  Fundamental Ratios — ≥8列 无NaN + 等价
# ============================================================
@pytest.mark.parametrize("asset,base", [("COIN", 200), ("MSTR", 1500)])
def test_t23_3_fundamental_ratios(asset, base):
    from feature_hub.modules.fundamental_ratios import compute

    ohlcv = _make_ohlcv(300, base)
    feats = compute(ohlcv)

    assert len(feats.columns) >= 8, f"columns={len(feats.columns)} < 8"
    # 清洗后无 NaN（前N行有NaN是正常的，只检查后200行）
    nan_count = int(feats.iloc[200:].isna().sum().sum())
    assert nan_count == 0, f"后200行 NaN={nan_count} > 0"
    # 等价
    feats2 = compute(ohlcv)
    for col in feats.columns:
        diff = (feats[col] - feats2[col]).abs().max()
        assert diff < 1e-9, f"列 {col} 不等价: diff={diff}"


# ============================================================
# T23-4  commodity_safe_haven 集合存在
# ============================================================
def test_t23_4_commodity_safe_haven_set():
    from feature_hub.modules.loader import _load_yaml_sets

    sets = _load_yaml_sets()
    assert "commodity_safe_haven" in sets, f"commodity_safe_haven 未在集合中: {list(sets.keys())}"
    modules = sets["commodity_safe_haven"]
    assert "classic_indicators" in modules
    assert "five_domain_fc" in modules
    assert "elder_ray" in modules
