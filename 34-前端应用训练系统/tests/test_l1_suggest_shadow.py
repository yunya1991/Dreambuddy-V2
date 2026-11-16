# -*- coding: utf-8 -*-
"""建议器影子模式测试：开关、非阻塞写入、异常隔离、契约零变化。"""

import json
import os
import sys

import pytest

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "3.1-FRONTEND", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import l1_route_signal as lrs  # noqa: E402
import l1_suggest_shadow as shadow  # noqa: E402


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "shadow.jsonl"
    monkeypatch.setenv("L1_SUGGEST_SHADOW", "1")
    monkeypatch.setenv("L1_SUGGEST_SHADOW_LOG", str(path))
    monkeypatch.setattr(
        lrs, "semantic_candidates", lambda m, k=3: [("price_query", 0.81), ("data_query", 0.72)]
    )
    yield path
    shadow.flush()


def _rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_disabled_writes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "off.jsonl"
    monkeypatch.setenv("L1_SUGGEST_SHADOW", "0")
    monkeypatch.setenv("L1_SUGGEST_SHADOW_LOG", str(path))
    shadow.record("BTC现在什么价格", intent="price_query", decision="L1_DIRECT")
    shadow.flush()
    assert not path.exists()


def test_enabled_writes_candidates(log):
    shadow.record("BTC现在什么价格", intent="price_query", decision="L1_DIRECT", trace_id="t1")
    assert shadow.flush()
    rows = _rows(log)
    assert len(rows) == 1
    row = rows[0]
    assert row["intent"] == "price_query"
    assert row["decision"] == "L1_DIRECT"
    assert row["top"][0][0] == "price_query"
    assert row["empty"] is False
    assert row["error"] is None
    assert "latency_ms" in row


def test_semantic_error_is_isolated(log, monkeypatch):
    def _boom(m, k=3):
        raise RuntimeError("embedder down")

    monkeypatch.setattr(lrs, "semantic_candidates", _boom)
    shadow.record("任意问题")
    assert shadow.flush()
    row = _rows(log)[0]
    assert row["empty"] is True
    assert "embedder down" in row["error"]


def test_route_query_contract_unchanged(log, monkeypatch):
    """影子开启不改变返回字段：无 suggestions、decision/route_confidence 与 S1 一致。"""
    monkeypatch.setenv("L1_ROUTING_STRATEGY", "S1")
    monkeypatch.setitem(
        lrs.EXECUTORS, "price_query", lambda m: {"success": True, "answer": "ok", "data": {}}
    )
    monkeypatch.setattr(lrs, "settle_to_cognitive", lambda *a, **k: None)
    out = lrs.route_query("BTC现在什么价格")
    assert "suggestions" not in out
    assert out["route_signal"]["decision"] == "L1_DIRECT"
    assert shadow.flush()
    assert _rows(log)[0]["decision"] == "L1_DIRECT"


def test_summarize(log):
    shadow.record("BTC现在什么价格", intent="price_query", decision="L1_DIRECT")
    shadow.flush()
    s = shadow.summarize(str(log))
    assert s["n"] == 1
    assert s["empty_rate"] == 0.0
    assert s["top1_dist"][0][0] == "price_query"
