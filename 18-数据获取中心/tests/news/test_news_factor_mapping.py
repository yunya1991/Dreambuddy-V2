"""P0-2 快讯 → 因子映射 — SPEC §2.10 / §2.9.2。

要求：9 类事件全覆盖、两套映射、版本号、真实语料覆盖率 ≥60%。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_center.processing.newsflash_events import (
    EVENT_TYPE_FACTOR_DIMS,
    MAPPING_VERSION,
    map_event_to_dims,
    map_event_to_factors,
    mapping_coverage,
)

NEWSFLASH = Path(__file__).resolve().parents[2] / "backfill" / "newsflash_history.jsonl"

NINE_TYPES = {
    "market_sentiment",
    "crypto_regulation",
    "token_milestone",
    "monetary_policy",
    "security_incident",
    "project_ecosystem",
    "us_policy",
    "geopolitics",
    "us_data",
}


def test_mapping_version_stable():
    assert MAPPING_VERSION.startswith("news-factor-")


def test_all_nine_event_types_mapped():
    assert set(EVENT_TYPE_FACTOR_DIMS) == NINE_TYPES


def test_v1_maps_market_sentiment_to_d4():
    dims, src = map_event_to_dims({"od_event_type": "market_sentiment"}, "v1")
    assert dims == ("D4",)
    assert src == "event_type"


def test_unknown_event_type_unmapped():
    dims, src = map_event_to_dims({"od_event_type": "no_such_type"}, "v1")
    assert dims == ()
    assert src == "event_type"


def test_v2_keyword_beats_event_type():
    rec = {"od_event_type": "token_milestone", "title": "现货 ETF 获批"}
    dims, src = map_event_to_dims(rec, "v2")
    assert src == "keyword"
    assert dims == ("D2",)


def test_v2_falls_back_to_own_table():
    rec = {"od_event_type": "project_ecosystem", "title": "某公链发布新版本"}
    dims, src = map_event_to_dims(rec, "v2")
    assert src == "event_type_v2"
    assert dims == ("D3",)


def test_factors_exclude_unavailable_series():
    fids, _ = map_event_to_factors({"od_event_type": "monetary_policy"}, "v1")
    assert fids
    assert all(f.startswith("macro.") for f in fids)


def _iter_records(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


@pytest.mark.parametrize("mapping", ["v1", "v2"])
def test_real_corpus_coverage_above_60pct(mapping):
    if not NEWSFLASH.exists():
        pytest.skip("newsflash 语料不存在")
    stats = mapping_coverage(_iter_records(NEWSFLASH), mapping)
    assert stats["total"] > 100_000
    assert stats["coverage"] >= 0.60, stats["unmapped_types"]
    assert stats["mapping_version"] == MAPPING_VERSION
