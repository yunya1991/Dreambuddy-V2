"""SPEC-54 R3b：卡片配置持久化的存储层单测（临时库，不触真实数据）。"""

from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS = os.path.join(_REPO, "3.1-FRONTEND", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import cards_config as cc  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "DB_PATH", str(tmp_path / "visual_cards.db"))
    return cc


def _panel(key: str, capability_id: str = "D-A11", **args):
    return {"panel_key": key, "capability_id": capability_id, "args": args}


def test_get_empty_does_not_create_db(store):
    result = store.get_config("u1")
    assert result == {"ok": True, "code": "ok", "items": [], "count": 0}
    assert not os.path.exists(store.DB_PATH)


def test_put_then_get_roundtrip(store):
    put = store.put_config(
        {"user": "u1", "tab": "all", "panels": [_panel("D-A11|BTC", symbol="BTC")]}
    )
    assert put["code"] == "ok" and put["count"] == 1

    got = store.get_config("u1")
    assert got["count"] == 1
    item = got["items"][0]
    assert item["tab_id"] == "all"
    assert item["capability_id"] == "D-A11"
    assert item["args"] == {"symbol": "BTC"}


def test_put_is_snapshot_replace(store):
    store.put_config(
        {
            "user": "u1",
            "tab": "all",
            "panels": [_panel("a"), _panel("b"), _panel("c")],
        }
    )
    store.put_config({"user": "u1", "tab": "all", "panels": [_panel("b")]})

    assert [item["panel_key"] for item in store.get_config("u1")["items"]] == ["b"]


def test_users_and_tabs_are_isolated(store):
    store.put_config({"user": "u1", "tab": "all", "panels": [_panel("a")]})
    store.put_config({"user": "u1", "tab": "mine", "panels": [_panel("b")]})
    store.put_config({"user": "u2", "tab": "all", "panels": [_panel("c")]})

    assert store.get_config("u1")["count"] == 2
    assert [i["panel_key"] for i in store.get_config("u1", "all")["items"]] == ["a"]
    assert [i["panel_key"] for i in store.get_config("u2")["items"]] == ["c"]


def test_args_too_large_is_rejected(store):
    big = "x" * (cc.MAX_ARGS_BYTES + 16)
    result = store.put_config({"user": "u1", "tab": "all", "panels": [_panel("a", blob=big)]})
    assert result["code"] == "payload_too_large"
    assert store.get_config("u1")["count"] == 0


def test_panel_count_limit(store):
    panels = [_panel(f"p{i}") for i in range(cc.MAX_PANELS + 1)]
    result = store.put_config({"user": "u1", "tab": "all", "panels": panels})
    assert result["code"] == "payload_too_large"


@pytest.mark.parametrize(
    "payload",
    [
        {"user": "", "tab": "all", "panels": []},
        {"user": "u1", "tab": "", "panels": []},
        {"user": "u1", "tab": "all", "panels": "not-a-list"},
        {"user": "u1", "tab": "all", "panels": [{"capability_id": "D-A11"}]},
        {"user": "u1", "tab": "all", "panels": [{"panel_key": "a", "args": []}]},
    ],
)
def test_invalid_payloads(store, payload):
    assert store.put_config(payload)["code"] == "invalid_params"
