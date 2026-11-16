# -*- coding: utf-8 -*-
"""T5/T7：L1 新闻检索执行器 `exec_news_search` 契约测试（SPEC-41-L1 §7/§9）。

覆盖 4 条硬约束：
  1. 0 命中禁止编造（必须输出覆盖数与未分类占比）
  2. topic=other / 未解析出 topic 时不过滤（回显 topic_filter=none）
  3. 产物缺失 FAIL-OPEN（degraded=true，不抛异常）
  4. 窗口三级 24h / 168h / 720h 与数据源选择
另含 T7 无匹配话术与 EXECUTORS 注册、legacy 标记。
"""

import json
import os
import sys

import pytest

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "3.1-FRONTEND", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import data_query_executor as dqe  # noqa: E402
import l1_route_signal as lrs  # noqa: E402


def _digest_item(title, ts, topic="other", label="中性", importance=60.0):
    return {
        "id": title[:8],
        "ts": ts,
        "title": title,
        "topic": topic,
        "event_type": "macro_other",
        "sentiment": {"label": label, "score": 0.1},
        "importance": importance,
        "origin": "jin10",
        "source_count": 1,
        "dup_count": 0,
    }


def _digest(items, coverage=None):
    return {
        "schema": "news_digest/v1",
        "window_days": 30,
        "coverage": coverage if coverage is not None else {"2026-11-14": len(items)},
        "topic_dist": {"other": len(items)},
        "stats": {"items": len(items), "total": len(items)},
        "items": items,
    }


def _hot(items):
    return {
        "schema": "hot_news/v1",
        "top": [
            {
                "title": t,
                "published_at": ts,
                "topic": topic,
                "sentiment": {"label": label},
                "importance": imp,
            }
            for t, ts, topic, label, imp in items
        ],
        "stats": {"topic_dist": {"other": len(items)}},
    }


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """把两个产物路径指向临时文件，返回写入函数。"""

    def _wire(digest_payload=None, hot_payload=None):
        d = tmp_path / "news_digest.json"
        h = tmp_path / "hot_news.json"
        if digest_payload is None:
            d.unlink(missing_ok=True)
        else:
            d.write_text(json.dumps(digest_payload, ensure_ascii=False), encoding="utf-8")
        if hot_payload is None:
            h.unlink(missing_ok=True)
        else:
            h.write_text(json.dumps(hot_payload, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(dqe, "_NEWS_DIGEST_PATH", str(d))
        monkeypatch.setattr(dqe, "_HOT_NEWS_PATH", str(h))

    return _wire


def test_zero_hit_does_not_fabricate(wire):
    wire(_digest([_digest_item("某公司发布季度财报", "2026-11-14T02:00:00Z", importance=88.0)]))
    r = dqe.exec_news_search("以太坊相关的新闻")
    assert r["success"] is True
    assert r["data"]["matched"] == 0
    assert r["data"]["items"] == []
    assert "未检索到" in r["answer"]
    assert "未分类" in r["answer"]  # 必须透出覆盖质量，而不是编造条目
    assert "某公司发布季度财报" not in r["answer"]


def test_topic_other_does_not_filter(wire):
    wire(
        _digest(
            [
                _digest_item("某公司发布季度财报", "2026-11-14T02:00:00Z", topic="other"),
                _digest_item("某地发生地震", "2026-11-14T03:00:00Z", topic="other"),
            ]
        )
    )
    r = dqe.exec_news_search("最近有什么新闻")
    assert r["data"]["topic_filter"] == "none"
    assert r["data"]["matched"] == 2


def test_missing_artifact_fails_open(wire):
    wire(None, None)
    r = dqe.exec_news_search("最近有什么新闻")
    assert r["success"] is True
    assert r["degraded"] is True
    assert r["data"]["matched"] == 0
    assert r["data"]["items"] == []
    assert "产物缺失" in r["data"]["coverage_note"]


@pytest.mark.parametrize(
    "query,window_h,source",
    [
        ("今天有什么新闻", 24, "hot_news"),
        ("最近有什么新闻", 168, "news_digest"),
        ("上周的新闻", 720, "news_digest"),
        ("这个月都有哪些消息", 720, "news_digest"),
    ],
)
def test_window_three_tiers(wire, query, window_h, source):
    wire(
        _digest([_digest_item("某公司发布季度财报", "2026-11-14T02:00:00Z")]),
        _hot([("某公司发布季度财报", "2026-11-15T01:00:00Z", "earnings", "中性", 80.0)]),
    )
    r = dqe.exec_news_search(query)
    assert r["data"]["window_h"] == window_h
    assert r["data"]["source"] == source


def test_coverage_note_surfaces_collection_gap(wire):
    wire(
        _digest(
            [_digest_item("某公司发布季度财报", "2026-11-14T02:00:00Z")],
            coverage={"2026-11-09": 0, "2026-11-14": 1},
        )
    )
    r = dqe.exec_news_search("最近有什么新闻")
    assert "2026-11-09" in r["data"]["coverage_note"]
    assert "采集异常" in r["data"]["coverage_note"]


def test_t7_no_match_phrase_is_honest(wire):
    """T7：`以太坊相关的新闻` 无命中时必须如实说没有，不得编造。"""
    wire(
        _digest([_digest_item("美联储维持利率不变", "2026-11-14T02:00:00Z", topic="rates_policy")])
    )
    r = dqe.exec_news_search("以太坊相关的新闻")
    assert r["data"]["matched"] == 0
    assert "以太坊" in r["answer"]
    assert "未检索到" in r["answer"]


def test_registered_in_executors():
    assert lrs.EXECUTORS["event_listing"] is dqe.exec_news_search


def test_legacy_executor_marked(monkeypatch):
    monkeypatch.setattr(dqe.dc_pg, "fetch_records", lambda *a, **k: [])
    r = dqe.exec_event_listing("最近有什么新闻")
    assert r["legacy"] is True


class _EmptyRecallL0:
    """recall 恒空：模拟云端「认知库无新闻问法」。"""

    def fetch_context(self, scope, params=None):
        return {
            "ok": True,
            "data": [],
            "source": "fake",
            "timestamp": "",
            "degraded": False,
            "meta": {"reason": "no_hit"},
        }


def test_event_listing_bypasses_recall_gate(wire, monkeypatch):
    """A 方案回归：recall_empty 时新闻检索仍须 L1 直答（不再交 L2 静默丢弃）。"""
    wire(
        _digest([_digest_item("以太坊突破 4000 美元", "2026-11-15T02:00:00Z", topic="crypto_reg")])
    )
    monkeypatch.setattr(lrs, "get_l0", lambda: _EmptyRecallL0())

    out = lrs.route_query("以太坊 最近新闻")

    assert out["handled"] is True
    assert out["route_signal"]["decision"] == "L1_DIRECT"
    assert out["route_signal"]["reasons"] == [lrs.R_EXECUTOR_AVAILABILITY]
    assert out["data"]["matched"] == 1


def test_event_listing_is_not_deterministic_registry():
    """锁住分类边界：产物检索型 ≠ 确定性单维输出（DETERMINISTIC_INTENTS 不得混入）。"""
    assert "event_listing" in lrs.EXECUTOR_AVAILABILITY_INTENTS
    assert "event_listing" not in lrs.DETERMINISTIC_INTENTS
