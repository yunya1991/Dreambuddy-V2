"""Phase 1 TDD 测试 · FeatureRegistry v4

覆盖验收：
  T13 a) test_v4_enabled_sets_exist      — ENABLED_SETS 中存在 btc_morphology_v4 / v4_layer1 两个 set
  T13 b) test_v4_rolling_stats_columns   — rolling_regime_stats 模块输出列 ≥ 12，且包含 L_p90_252d / T_p90_252d / regime_entropy_20d
  T13 c) test_v4_build_feature_schema    — build_feature_schema(set='btc_morphology_v4') 返回 dict；
                                           schema['groups']['lgbm_pool'] 仅包含基础三模块；
                                           feature_names_in_order 非空且无重复。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))


# ================================================================
# Fixtures
# ================================================================
@pytest.fixture
def synth_df() -> pd.DataFrame:
    """500 根合成 OHLCV（含趋势段/震荡段/熊市段）"""
    rng = np.random.default_rng(1)
    n = 500
    t1 = np.linspace(100, 200, 150)
    t2 = np.linspace(200, 205, 150)
    t3 = np.linspace(205, 140, 200)
    close = np.concatenate([t1, t2, t3]) * (1 + rng.normal(0, 0.012, n))
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open":  close * (1 + rng.normal(0, 0.004, n)),
        "high":  close * (1 + np.abs(rng.normal(0, 0.011, n))),
        "low":   close * (1 - np.abs(rng.normal(0, 0.011, n))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.2, n)),
    }, index=idx)


# ================================================================
# T13a) v4 ENABLED_SETS 存在
# ================================================================
def test_v4_enabled_sets_exist():
    from bcrm2 import feature_registry as fr
    assert hasattr(fr, "ENABLED_SETS"), "ENABLED_SETS 未定义"
    assert "btc_morphology_v4" in fr.ENABLED_SETS, "缺少 btc_morphology_v4 set"
    assert "btc_morphology_v4_layer1" in fr.ENABLED_SETS, "缺少 btc_morphology_v4_layer1 set"
    base = fr.ENABLED_SETS["btc_morphology_v4"]
    layer1 = fr.ENABLED_SETS["btc_morphology_v4_layer1"]
    assert "rolling_regime_stats" in base, "btc_morphology_v4 必须包含 rolling_regime_stats"
    assert "rolling_regime_stats" in layer1
    assert "sector_beta_pool" in layer1, "v4_layer1 必须包含 sector_beta_pool"


# ================================================================
# T13b) rolling_regime_stats 输出列齐全
# ================================================================
def test_v4_rolling_stats_columns(synth_df: pd.DataFrame):
    from bcrm2.rolling_regime_stats import RollingRegimeStats
    rrs = RollingRegimeStats()
    out = rrs.compute(synth_df)
    assert isinstance(out, pd.DataFrame), "RollingRegimeStats.compute 必须返回 DataFrame"
    assert len(out) == len(synth_df), "行数必须对齐输入"
    assert out.shape[1] >= 12, f"rolling_regime_stats 列数应 ≥ 12，实际 {out.shape[1]}"
    required_cols = ["L_p90_252d", "T_p90_252d", "regime_entropy_20d", "consensus_ma_20d",
                     "L_std_60d", "T_std_60d", "volume_zscore_252d"]
    missing = [c for c in required_cols if c not in out.columns]
    assert not missing, f"缺失核心列：{missing}"


# ================================================================
# T13c) build_feature_schema 正确分组 & 非空 & 无重复
# ================================================================
def test_v4_build_feature_schema(synth_df: pd.DataFrame):
    from bcrm2 import feature_registry as fr
    cls = fr.FeatureRegistry
    assert hasattr(cls, "build_feature_schema"), "FeatureRegistry 类未实现 build_feature_schema classmethod"
    schema = cls.build_feature_schema(set_name="btc_morphology_v4")
    assert isinstance(schema, dict), "schema 必须是 dict"
    assert schema.get("schema_version") == "feature.v4"
    groups = schema.get("groups", {})
    lgbm_pool = groups.get("lgbm_pool", [])
    assert "morphology_core" in lgbm_pool and "ma200_cycle" in lgbm_pool and "multi_timeframe" in lgbm_pool
    assert "rolling_regime_stats" not in lgbm_pool, "rolling_regime_stats 必须排除 LGBM 池（标签泄露风险）"
    assert "sector_beta_pool" not in lgbm_pool, "sector_beta_pool 必须排除 LGBM 池"
    names = schema.get("feature_names_in_order", [])
    assert len(names) >= 20, "lgbm_pool 三基础模块合并列数必须 ≥ 20"
    assert len(set(names)) == len(names), "feature_names_in_order 不能有重复列（Schema 严格性要求）"
