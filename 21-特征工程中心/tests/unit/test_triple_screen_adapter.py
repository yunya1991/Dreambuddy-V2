"""T15 · TripleScreen Adapter 等价性测试（★T-G5 硬门槛）

验证 SklearnStyleAdapter(TrendFeatureEngineer).compute(ohlcv) 与
TrendFeatureEngineer.create_features(ohlcv) 逐列 diff < 1e-9。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "21-特征工程中心"))
sys.path.insert(0, str(_PROJECT_ROOT / "12-三屏趋势系统"))


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


def test_t15_triple_screen_adapter_equivalence():
    """Adapter 输出与直接调用 TrendFeatureEngineer.create_features 逐列 < ε=1e-9"""
    from feature_hub.adapters.sklearn_style_adapter import SklearnStyleAdapter

    try:
        from ml.feature_engineer import TrendFeatureEngineer
    except ImportError:
        # 12号目录可能不在path中
        sys.path.insert(0, str(_PROJECT_ROOT / "12-三屏趋势系统"))
        from ml.feature_engineer import TrendFeatureEngineer

    ohlcv = _make_ohlcv(300)

    # 直接调用
    direct = TrendFeatureEngineer(views=None).create_features(ohlcv)
    # 去除 label 列
    label_cols = [c for c in direct.columns if c.startswith("label_")]
    direct = direct.drop(columns=label_cols)

    # Adapter 调用
    adapter = SklearnStyleAdapter(TrendFeatureEngineer, views=None)
    adapted = adapter.compute(ohlcv)

    # 逐列比较
    common_cols = sorted(set(direct.columns) & set(adapted.columns))
    assert len(common_cols) > 0, "无公共列"

    for col in common_cols:
        diff = (direct[col] - adapted[col]).abs().max()
        assert diff < 1e-9, f"列 '{col}' 差异 {diff} 超过 ε=1e-9"
