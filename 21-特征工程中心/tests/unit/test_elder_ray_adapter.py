"""T16-1 · Elder-ray Adapter 测试

验证输出 7 列：one-hot 5 列 + 差分 2 列，无 NaN。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "21-特征工程中心"))


def _make_ohlcv(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.004, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.0, n)),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def test_t16_1_elder_ray_7_cols_no_nan():
    from feature_hub.modules.elder_ray import ElderRayAdapter

    ohlcv = _make_ohlcv(300)
    adapter = ElderRayAdapter()
    out = adapter.compute(ohlcv)

    assert out is not None
    assert isinstance(out, pd.DataFrame)
    assert out.shape[1] == 7, f"应输出 7 列, 实际 {out.shape[1]}: {list(out.columns)}"
    # 无 NaN（跳过 EMA warmup 期）
    non_nan = out.dropna()
    assert len(non_nan) > 200, f"有效行数不足: {len(non_nan)}"
    # one-hot 列名包含 elder_
    elder_cols = [c for c in out.columns if c.startswith("elder_")]
    assert len(elder_cols) >= 5, f"elder_ 前缀列不足: {elder_cols}"
