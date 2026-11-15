# -*- coding: utf-8 -*-
"""方法基座固化单测（SPEC-54-L1交易层 §4.0 / §5.0；LT-G11 / LT-G12）。"""

import copy
import os
import sys
import tempfile

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import pytest  # noqa: E402
import yaml  # noqa: E402
from l1agg.methods import REGISTRY  # noqa: E402
from l1agg.methods.ranking import (  # noqa: E402
    BASELINE_CONFIG,
    REQUIRED_BASELINE_METHODS,
    REQUIRED_MECHANISMS,
    BaselineConfigError,
    assert_disjoint,
    blend_axis,
    load_baseline,
    load_rank_config,
    rank,
)


def _raw_config():
    with open(BASELINE_CONFIG, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_temp(payload):
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    yaml.safe_dump(payload, handle, allow_unicode=True)
    handle.close()
    return handle.name


def test_baseline_config_complete():
    base = load_baseline()
    assert base.method_ids == REQUIRED_BASELINE_METHODS
    assert base.mechanisms == REQUIRED_MECHANISMS
    assert base.version.startswith("bm-")
    assert base.axes["I37"] == "trend"


def test_baseline_methods_all_implemented():
    base = load_baseline()
    for method_id in base.method_ids:
        assert method_id in REGISTRY
        assert REGISTRY[method_id].implemented is True


def test_baseline_rejects_missing_method():
    payload = copy.deepcopy(_raw_config())
    payload["methods"] = [m for m in payload["methods"] if m["id"] != "I39"]
    path = _write_temp(payload)
    try:
        with pytest.raises(BaselineConfigError, match="基座方法集"):
            load_baseline(path)
    finally:
        os.unlink(path)


def test_baseline_rejects_disabled_mechanism():
    payload = copy.deepcopy(_raw_config())
    for item in payload["mechanisms"]:
        if item["key"] == "vintage":
            item["enabled"] = False
    path = _write_temp(payload)
    try:
        with pytest.raises(BaselineConfigError, match="基座机制禁止停用"):
            load_baseline(path)
    finally:
        os.unlink(path)


def test_rank_config_is_deterministic():
    cfg = load_rank_config()
    assert cfg.topk == 2
    assert cfg.window >= cfg.purge + cfg.embargo
    assert cfg.tie_break == "method_id"


def _candidate_ids(limit=5):
    base = load_baseline()
    out = []
    for spec in REGISTRY.values():
        if not spec.implemented or spec.method_id in base.method_ids:
            continue
        out.append(spec.method_id)
    return sorted(out)[:limit]


def test_rank_excludes_baseline_even_with_top_scores():
    reliability = dict.fromkeys(REQUIRED_BASELINE_METHODS, 999.0)
    for offset, method_id in enumerate(_candidate_ids(4)):
        reliability[method_id] = 1.0 - 0.1 * offset
    result = rank(reliability, as_of="2026-11-14")
    selected = [item["method_id"] for item in result["ranked"]]
    assert not set(selected) & set(REQUIRED_BASELINE_METHODS)
    assert set(result["excluded_baseline"]) >= set(REQUIRED_BASELINE_METHODS)
    assert result["baseline_version"] == load_baseline().version


def test_rank_topk_and_determinism():
    reliability = dict.fromkeys(_candidate_ids(5), 1.0)
    first = rank(reliability, as_of="2026-11-14")
    second = rank(reliability, as_of="2026-11-14")
    assert len(first["ranked"]) == 2
    assert first["method_rank_hash"] == second["method_rank_hash"]
    assert first["ranked"] == second["ranked"]


def test_rank_hash_changes_with_scores():
    ids = _candidate_ids(2)
    low = rank({ids[0]: 0.1, ids[1]: 0.2}, as_of="2026-11-14")
    high = rank({ids[0]: 0.9, ids[1]: 0.2}, as_of="2026-11-14")
    assert low["method_rank_hash"] != high["method_rank_hash"]


def test_rank_excludes_insufficient_sample():
    method_id = _candidate_ids(1)[0]
    spec = REGISTRY[method_id]
    result = rank(
        {method_id: 1.0},
        as_of="2026-11-14",
        sample_n={method_id: spec.min_n - 1},
    )
    assert method_id in result["excluded_insufficient"]
    assert method_id not in [item["method_id"] for item in result["ranked"]]


def test_assert_disjoint_raises_on_overlap():
    with pytest.raises(BaselineConfigError, match="相交"):
        assert_disjoint(["I37", "S01"], ["I37"])


def test_blend_axis_clips_sign_flip_and_oversize():
    within = blend_axis([1.0, -1.0, 0.5], [1.1, -0.9, 0.55])
    assert within["values"] == [1.1, -0.9, 0.55]
    assert within["clipped_any"] is False

    flip = blend_axis([1.0], [-1.2])
    assert flip["values"] == [1.0]
    assert flip["clipped"] == [0]

    oversize = blend_axis([1.0], [1.5])
    assert oversize["values"] == [1.0]
    assert oversize["clipped_any"] is True

    from_zero = blend_axis([0.0], [0.7])
    assert from_zero["values"] == [0.0]


def test_blend_axis_length_mismatch_raises():
    with pytest.raises(BaselineConfigError, match="轴数不一致"):
        blend_axis([1.0, 2.0], [1.0])
