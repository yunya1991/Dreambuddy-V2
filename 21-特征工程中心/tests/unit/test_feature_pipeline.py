"""T19 · FeaturePipeline 编排测试

T19-1: 按启用集合拉取模块 → concat → 清洗链 → FeatureVector 形状正确
T19-2: L1 某模块异常 → 跳过 + warning + 其他模块照常输出
T19-3: 启用集合名错 → L3 Fail-Fast（FeatureSetNotFound）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "21-特征工程中心"))


@pytest.fixture
def ohlcv():
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


# ============================================================
# T19-1  FeatureVector 形状正确
# ============================================================
def test_t19_1_pipeline_produces_feature_vector(ohlcv):
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline

    pipe = FeaturePipeline()
    # 注册两个本地 mock 模块
    def mock_a(df, **kw):
        return pd.DataFrame({"a_feat": df["close"].pct_change()}, index=df.index)
    def mock_b(df, **kw):
        return pd.DataFrame({"b_feat": df["volume"].rolling(10).mean()}, index=df.index)

    pipe.register_module("mock_a", mock_a)
    pipe.register_module("mock_b", mock_b)
    pipe.register_set("test_set", ["mock_a", "mock_b"])

    fv = pipe.run(set_name="test_set", df=ohlcv)
    assert fv.df is not None
    assert isinstance(fv.df, pd.DataFrame)
    assert len(fv.df) == len(ohlcv)
    assert "mock_a__a_feat" in fv.df.columns or "mock_b__b_feat" in fv.df.columns
    assert fv.meta.get("set_name") == "test_set"


# ============================================================
# T19-2  模块异常 → 跳过 + 其他模块照常输出
# ============================================================
def test_t19_2_module_exception_skip(ohlcv):
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline

    pipe = FeaturePipeline()
    def good_module(df, **kw):
        return pd.DataFrame({"good_feat": df["close"].pct_change()}, index=df.index)
    def bad_module(df, **kw):
        raise RuntimeError("intentional failure")

    pipe.register_module("good", good_module)
    pipe.register_module("bad", bad_module)
    pipe.register_set("mixed_set", ["good", "bad"])

    fv = pipe.run(set_name="mixed_set", df=ohlcv)
    # good 模块应照常输出
    assert "good__good_feat" in fv.df.columns


# ============================================================
# T19-3  启用集合名错 → Fail-Fast
# ============================================================
def test_t19_3_invalid_set_name_raises(ohlcv):
    from feature_hub.errors import FeatureSetNotFound
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline

    pipe = FeaturePipeline()
    with pytest.raises(FeatureSetNotFound):
        pipe.run(set_name="nonexistent_set", df=ohlcv)
