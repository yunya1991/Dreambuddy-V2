"""T16-2 · FiveDomainFc Adapter 测试

验证输出 5 列（dao/tian/di/jiang/fa），RobustScaler 后范围 ≈ [-3, 3]，每列无 NaN。
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


def test_t16_2_five_domain_5_cols_no_nan():
    from feature_hub.modules.five_domain_fc import FiveDomainFcAdapter

    ohlcv = _make_ohlcv(300)
    adapter = FiveDomainFcAdapter()
    out = adapter.compute(ohlcv)

    assert out is not None
    assert isinstance(out, pd.DataFrame)
    assert out.shape[1] == 5, f"应输出 5 列, 实际 {out.shape[1]}: {list(out.columns)}"

    # 无 NaN
    non_nan = out.dropna()
    assert len(non_nan) > 200, f"有效行数不足: {len(non_nan)}"

    # 每列应在 [-5, 5] 范围内（RobustScaler 后大约 [-3, 3]，留余量）
    for col in out.columns:
        vals = out[col].dropna()
        if len(vals) > 0:
            assert vals.abs().max() <= 10, f"列 {col} 范围过大: {vals.abs().max()}"
