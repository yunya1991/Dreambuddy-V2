"""M2.1 · Contract + Errors 单元测试（TDD 先红→后绿）。

覆盖：
  T-contract-1  FeatureVector 字段齐全（df + meta）
  T-contract-2  FeatureSpec 字段齐全（name/version/enabled_sets/input_cols/output_cols）
  T-contract-3  LineageRecord 字段齐全（timestamp/module/input_cols/output_cols/dropped_cols/reasons）
  T-contract-4  LineageRecord 可序列化为 dict
  T-errors-1    FeatureError 继承 Exception
  T-errors-2    FeatureSetNotFound 继承 FeatureError 且携带 name 属性
  T-errors-3    FeatureSetNotFound 的 str 包含 name
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "21-特征工程中心"))


# ============================================================
# T-contract-1  FeatureVector
# ============================================================
def test_feature_vector_fields():
    from feature_hub.contract import FeatureVector

    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    meta = {"set_name": "test_set", "version": "1.0.0"}
    fv = FeatureVector(df=df, meta=meta)
    assert fv.df is df
    assert fv.meta == meta


# ============================================================
# T-contract-2  FeatureSpec
# ============================================================
def test_feature_spec_fields():
    from feature_hub.contract import FeatureSpec

    spec = FeatureSpec(
        name="morphology_core",
        version="2.1.0",
        enabled_sets=["btc_morph_v6"],
        input_cols=["open", "high", "low", "close", "volume"],
        output_cols=["atr_14", "adx_14"],
    )
    assert spec.name == "morphology_core"
    assert spec.version == "2.1.0"
    assert "btc_morph_v6" in spec.enabled_sets
    assert len(spec.input_cols) == 5
    assert len(spec.output_cols) == 2


# ============================================================
# T-contract-3  LineageRecord
# ============================================================
def test_lineage_record_fields():
    from feature_hub.contract import LineageRecord

    rec = LineageRecord(
        timestamp="2026-08-24T09:00:00",
        module="morphology_core",
        input_cols=["open", "high", "low", "close"],
        output_cols=["atr_14", "adx_14"],
        dropped_cols=["volume"],
        reasons=["VIF>10"],
    )
    assert rec.module == "morphology_core"
    assert rec.input_cols == ["open", "high", "low", "close"]
    assert rec.output_cols == ["atr_14", "adx_14"]
    assert rec.dropped_cols == ["volume"]
    assert rec.reasons == ["VIF>10"]


# ============================================================
# T-contract-4  LineageRecord 可序列化为 dict
# ============================================================
def test_lineage_record_to_dict():
    from feature_hub.contract import LineageRecord

    rec = LineageRecord(
        timestamp="2026-08-24T09:00:00",
        module="vif_dropper",
        input_cols=["a", "b", "c"],
        output_cols=["a"],
        dropped_cols=["b", "c"],
        reasons=["VIF>10", "VIF>10"],
    )
    d = rec.to_dict()
    assert isinstance(d, dict)
    assert d["module"] == "vif_dropper"
    assert d["dropped_cols"] == ["b", "c"]


# ============================================================
# T-errors-1  FeatureError 继承 Exception
# ============================================================
def test_feature_error_inheritance():
    from feature_hub.errors import FeatureError

    assert issubclass(FeatureError, Exception)


# ============================================================
# T-errors-2  FeatureSetNotFound 继承 FeatureError 且携带 name
# ============================================================
def test_feature_set_not_found():
    from feature_hub.errors import FeatureError, FeatureSetNotFound

    assert issubclass(FeatureSetNotFound, FeatureError)
    exc = FeatureSetNotFound("nonexistent_set")
    assert exc.name == "nonexistent_set"


# ============================================================
# T-errors-3  FeatureSetNotFound 的 str 包含 name
# ============================================================
def test_feature_set_not_found_str():
    from feature_hub.errors import FeatureSetNotFound

    exc = FeatureSetNotFound("missing_set")
    assert "missing_set" in str(exc)
