"""50 自有 source 映射表测试（不得退化为 23 的键）。"""

from __future__ import annotations

from core.mappings import (
    EXTERNAL_SOURCES,
    SOURCE_DIM_MAP,
    SOURCE_TF_MAP,
    SOURCE_WEIGHT_MAP,
    intent_of,
    normalize_source,
    role_of,
)

REQUIRED_SOURCES = {
    "11-bcrm",
    "11-bdsm",
    "11-washout",
    "11-event-arbitrage",
    "11-bcrm-tactical",
    "29-event",
    "40-cycle",
    "43-strategic",
    "23-contradiction",
}


def test_all_required_sources_mapped():
    assert REQUIRED_SOURCES <= set(SOURCE_DIM_MAP)
    assert REQUIRED_SOURCES <= set(SOURCE_TF_MAP)
    assert REQUIRED_SOURCES <= set(SOURCE_WEIGHT_MAP)


def test_no_23_legacy_keys():
    for legacy in ("bcrm", "bdsm", "strategic", "cycle", "event"):
        assert legacy not in SOURCE_DIM_MAP


def test_external_weights_sum_to_one():
    total = sum(SOURCE_WEIGHT_MAP[source] for source in EXTERNAL_SOURCES)
    assert abs(total - 1.0) < 1e-9


def test_roles():
    assert role_of("40-cycle") == "macro_force"
    assert role_of("43-strategic") == "macro_force"
    assert role_of("40-divergence") == "macro_force"
    assert role_of("29-event") == "self_mirror"
    assert role_of("23-contradiction") == "self_mirror"
    assert role_of("11-bdsm") == "external"
    assert role_of("unknown") == "unknown"


def test_alias_normalization():
    assert normalize_source("bdsm") == "11-bdsm"
    assert normalize_source("bcrm-tactical") == "11-bcrm-tactical"
    assert normalize_source("11-bdsm") == "11-bdsm"


def test_intent_defaults():
    assert intent_of("11-washout", None) == "reversal"
    assert intent_of("11-event-arbitrage", None) == "event_shock"
    assert intent_of("11-bdsm", None) == "trend"
    assert intent_of("11-bdsm", "event_shock") == "event_shock"
