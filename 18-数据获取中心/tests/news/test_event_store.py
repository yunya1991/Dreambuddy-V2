"""历史事件库存储层测试 — SPEC-D1-NARRATIVE-PRIMITIVES §2.4 + D3 硬要求。

事件 schema 硬字段：
  event_id / event_type / asset_scope / trigger_ts / ts_precision /
  market_state / reaction / source / attribution
D3 硬要求：ts_onchain_visible（双时间戳）、unlock_pct_supply（解锁类必填）
"""

from data_center.processing.event_store import (
    EventStore,
    validate_event,
)

VALID_EVENT = {
    "event_id": "EV-test001",
    "event_type": "hack.cex",
    "asset_scope": ["BTC"],
    "trigger_ts": 1704844800,
    "ts_onchain_visible": 1704840000,
    "unlock_pct_supply": None,
    "ts_precision": "day",
    "market_state": {"regime": "bear"},
    "reaction": {"T+24h": -0.05, "T+7d": -0.12},
    "source": "article_backfill",
    "attribution": "strong",
}


def test_validate_valid_event():
    assert validate_event(VALID_EVENT) == []


def test_validate_missing_required():
    bad = {k: v for k, v in VALID_EVENT.items() if k != "trigger_ts"}
    errs = validate_event(bad)
    assert any("trigger_ts" in e for e in errs)


def test_validate_unlock_requires_pct_supply():
    ev = dict(VALID_EVENT)
    ev["event_type"] = "unlock.token"
    ev["unlock_pct_supply"] = None
    errs = validate_event(ev)
    assert any("unlock_pct_supply" in e for e in errs)


def test_validate_bad_ts_precision():
    ev = dict(VALID_EVENT, ts_precision="minute")
    errs = validate_event(ev)
    assert any("ts_precision" in e for e in errs)


def test_validate_bad_direction_type():
    ev = dict(VALID_EVENT, trigger_ts="not-a-ts")
    errs = validate_event(ev)
    assert errs


def test_store_roundtrip(tmp_path):
    """JSONL 追加 + 读取 + 幂等去重（event_id）。"""
    store = EventStore(tmp_path / "events.jsonl")
    store.add(VALID_EVENT)
    store.add(VALID_EVENT)  # 重复 id 不重复落盘
    store.add(dict(VALID_EVENT, event_id="EV-test002"))
    events = store.load()
    assert len(events) == 2
    assert {e["event_id"] for e in events} == {"EV-test001", "EV-test002"}


def test_store_rejects_invalid(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    ok = store.add({"event_id": "EV-bad"})
    assert ok is False
    assert store.load() == []


def test_store_failopen(tmp_path):
    """FAIL-OPEN：异常输入不抛。"""
    store = EventStore(tmp_path / "events.jsonl")
    assert store.add(None) is False
    assert store.add("garbage") is False
