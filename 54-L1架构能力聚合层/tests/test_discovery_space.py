# -*- coding: utf-8 -*-
"""Discovery 搜索空间预注册校验（SPEC-54 §15.2 / B3）测试。"""

import os
import sys

import pytest
import yaml

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import discovery  # noqa: E402
from l1agg.methods import REGISTRY  # noqa: E402


def _raw():
    with open(discovery.SPACE_FILE, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _mutated(tmp_path, mutate):
    raw = _raw()
    mutate(raw)
    path = tmp_path / "space.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(path)


def test_space_loads_and_hashes_deterministically():
    space = discovery.load_space()
    assert space["version"] == 1
    assert space["seed"] == 42
    assert space["series"] == space["assets"] + space["macro"]
    assert len(space["series"]) == len(set(space["series"])) <= discovery.MAX_SERIES
    assert space["transforms"] == list(discovery.FIXED_TRANSFORMS)
    assert space["horizons"] == list(discovery.FIXED_HORIZONS)
    assert len(space["space_hash"]) == 64
    assert discovery.load_space()["space_hash"] == space["space_hash"]


def test_methods_are_registered_and_within_preregistered_subset():
    space = discovery.load_space()
    assert set(space["methods"]) == set(discovery.FIXED_METHODS)
    assert all(m in REGISTRY for m in space["methods"])


def test_assets_resolve_to_asset_pool_storage_keys():
    space = discovery.load_space()
    known = discovery._asset_storage_keys()
    assert set(space["assets"]) <= known


def test_estimates_report_truncation():
    space = discovery.load_space()
    est = space["estimates"]
    assert est["series"] == len(space["series"])
    assert est["pairs"] == discovery.pair_count(est["series"])
    assert est["total_units"] == est["single_units"] + est["pair_units"]
    # 预注册空间全量远超预算 → 发现器按固定枚举顺序确定性截断
    assert est["within_budget"] is False


def test_rejects_seed_change(tmp_path):
    path = _mutated(tmp_path, lambda raw: raw.__setitem__("seed", 43))
    with pytest.raises(discovery.DiscoverySpaceError, match="seed"):
        discovery.load_space(path)


def test_rejects_extra_transform(tmp_path):
    path = _mutated(tmp_path, lambda raw: raw["transforms"].append("log"))
    with pytest.raises(discovery.DiscoverySpaceError, match="transforms"):
        discovery.load_space(path)


def test_rejects_unregistered_or_out_of_subset_method(tmp_path):
    path = _mutated(tmp_path, lambda raw: raw["methods"].append("S11"))
    with pytest.raises(discovery.DiscoverySpaceError, match="预注册子集"):
        discovery.load_space(path)

    def swap(raw):
        raw["methods"][0] = "NOPE"

    path = _mutated(tmp_path, swap)
    with pytest.raises(discovery.DiscoverySpaceError, match="方法库"):
        discovery.load_space(path)


def test_rejects_unresolved_asset(tmp_path):
    path = _mutated(tmp_path, lambda raw: raw["series"]["assets"].append("NOT_A_SERIES"))
    with pytest.raises(discovery.DiscoverySpaceError, match="storage.sub_category"):
        discovery.load_space(path)


def test_rejects_duplicate_series(tmp_path):
    def dup(raw):
        raw["series"]["macro"].append(raw["series"]["assets"][0])

    path = _mutated(tmp_path, dup)
    with pytest.raises(discovery.DiscoverySpaceError, match="重复"):
        discovery.load_space(path)


def test_rejects_budget_above_cap(tmp_path):
    path = _mutated(tmp_path, lambda raw: raw["budget"].__setitem__("max_units", 6000))
    with pytest.raises(discovery.DiscoverySpaceError, match="单元预算"):
        discovery.load_space(path)


def test_rejects_disabled_fdr(tmp_path):
    path = _mutated(tmp_path, lambda raw: raw["fdr"].__setitem__("enabled", False))
    with pytest.raises(discovery.DiscoverySpaceError, match="FDR"):
        discovery.load_space(path)


def test_rejects_non_frozen_split(tmp_path):
    path = _mutated(tmp_path, lambda raw: raw["split"].__setitem__("screen_ratio", 0.8))
    with pytest.raises(discovery.DiscoverySpaceError, match="筛选段"):
        discovery.load_space(path)


def test_rejects_pairs_above_cap(tmp_path, monkeypatch):
    keys = [f"S{i:02d}" for i in range(26)]  # 26 序列 → 325 对 > 300
    monkeypatch.setattr(discovery, "_asset_storage_keys", lambda: set(keys))

    def wide(raw):
        raw["series"]["assets"] = keys
        raw["series"]["macro"] = []

    path = _mutated(tmp_path, wide)
    with pytest.raises(discovery.DiscoverySpaceError, match="双序列上限"):
        discovery.load_space(path)
