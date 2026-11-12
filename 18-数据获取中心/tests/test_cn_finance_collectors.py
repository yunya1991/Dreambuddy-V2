"""P1-A：四个中文财经源采集器 + 正文存储 + 限频熔断（离线单测）。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from data_center.collectors.tradefin import (
    cls_telegraph_collector as cls,
)
from data_center.collectors.tradefin import (
    jin10_collector as jin10,
)
from data_center.collectors.tradefin import (
    sina_finance_collector as sina,
)
from data_center.collectors.tradefin import (
    wallstreetcn_collector as wsc,
)
from data_center.collectors.tradefin._classify import classify
from data_center.collectors.tradefin._guard import CircuitOpen, SourceGuard
from data_center.collectors.tradefin._util import cn_time_iso, split_title_body
from data_center.events.body_store import (
    BodyContractError,
    append_bodies,
    load_bodies,
    make_body_id,
    normalize_body,
    resolve_body_ref,
)
from data_center.events.store import EventContractError, normalize_event

NOW = datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc)  # 北京 2026-11-12 00:00


# ── 契约 / 工具 ─────────────────────────────────────────────


def test_cn_time_converted_from_beijing_to_utc():
    assert cn_time_iso("2026-11-11 23:42:05") == "2026-11-11T15:42:05Z"


def test_split_title_body_prefers_bracket_title():
    title, body = split_title_body("【美联储降息25个基点】美股三大指数收涨。")
    assert title == "美联储降息25个基点"
    assert "美股三大指数收涨" in body


def test_classify_uses_rate_decision_over_fomc_and_maps_leaders():
    assert classify("美联储宣布降息25个基点")[0] == "rate_decision"
    etype, symbols = classify("英伟达发布财报，营收超预期", "数据中心业务增长")
    assert etype == "earnings"
    assert symbols == ["NVDA"]
    assert classify("国际金价创历史新高")[1] == ["XAU"]
    assert classify("A股三大指数集体收涨")[1] == ["MACRO"]


def test_body_contract_rejects_naive_time_and_is_idempotent(tmp_path):
    row = {
        "id": "b1",
        "source": "sina_finance",
        "url": "https://example.com/1",
        "title": "t",
        "content_text": "正文",
        "date_published": "2026-11-11T15:00:00Z",
        "fetched_at": "2026-11-11T16:00:00Z",
    }
    target = tmp_path / "bodies.jsonl"
    assert append_bodies([row], target) == (1, 0)
    assert append_bodies([row], target) == (0, 1)
    assert resolve_body_ref("bodies.jsonl#b1", load_bodies(target)) == "正文"

    bad = dict(row, id="b2", date_published="2026-11-11 15:00:00")
    with pytest.raises(BodyContractError):
        normalize_body(bad)


# ── 新浪财经 ────────────────────────────────────────────────


def _sina_item(text="【美联储降息25个基点】美股收涨。", when="2026-11-11 23:00:00"):
    return {
        "id": 1,
        "rich_text": text,
        "create_time": when,
        "update_time": when,
        "docurl": "https://finance.sina.com.cn/7x24/2026-11-11/doc-1.shtml",
        "tag": [{"name": "美联储"}],
    }


def test_sina_items_to_result_contract_and_body():
    result = sina.items_to_result([_sina_item()], days=3, now=NOW)
    assert len(result.events) == 1 and len(result.bodies) == 1
    ev, body = result.events[0], result.bodies[0]
    assert ev["type"] == "rate_decision"
    assert ev["available_at"] == "2026-11-11T15:00:00Z"
    assert body["id"] == make_body_id(sina.SOURCE, ev["source_url"], ev["available_at"])
    assert ev["body_ref"] == f"bodies.jsonl#{body['id']}"
    normalize_event(ev)  # 不抛异常即满足 canonical 契约


def test_sina_jsonp_and_window_filter():
    payload = (
        'callback({"result":{"data":{"feed":{"list":['
        + (
            '{"id":1,"rich_text":"旧闻","create_time":"2026-10-01 10:00:00"},'
            '{"id":2,"rich_text":"【金价新高】现货黄金突破4000美元。",'
            '"create_time":"2026-11-11 22:00:00","docurl":"https://finance.sina.com.cn/a"}'
        )
        + "]}}}});"
    )
    items = sina.parse_feed(payload)
    result = sina.items_to_result(items, days=3, now=NOW)
    assert [e["title"] for e in result.events] == ["金价新高"]
    assert result.events[0]["symbols"] == ["XAU"]


# ── 华尔街见闻 ──────────────────────────────────────────────


def test_wsc_lives_and_articles_with_detail():
    live_payload = {
        "data": {
            "items": [
                {
                    "id": 11,
                    "title": "",
                    "content": "<p>美联储主席鲍威尔：通胀仍需观察。</p>",
                    "content_text": "美联储主席鲍威尔：通胀仍需观察。",
                    "display_time": 1794400000,
                    "uri": "https://wallstreetcn.com/livenews/11",
                }
            ]
        }
    }
    lives = wsc.lives_to_result(wsc.parse_lives(live_payload), days=3, now=NOW)
    assert len(lives.events) == 1 and lives.events[0]["type"] == "fomc"

    articles_payload = {
        "data": {
            "items": [
                {
                    "id": 99,
                    "title": "深度：黄金定价框架重估",
                    "content_short": "摘要",
                    "display_time": 1794400000,
                    "uri": "https://wallstreetcn.com/articles/99",
                }
            ]
        }
    }
    calls = []

    def detail(article_id):
        calls.append(article_id)
        return "正文第一段\n正文第二段"

    arts = wsc.articles_to_result(
        wsc.parse_articles(articles_payload),
        days=3,
        now=NOW,
        detail_fetcher=detail,
    )
    assert calls == [99]
    assert arts.bodies[0]["content_text"].startswith("正文第一段")
    assert arts.events[0]["quality"] == "B"

    # 正文已入库 → 不再请求详情
    known = {arts.bodies[0]["id"]}
    again = wsc.articles_to_result(
        wsc.parse_articles(articles_payload),
        days=3,
        now=NOW,
        detail_fetcher=detail,
        known_body_ids=known,
    )
    assert calls == [99]
    assert again.bodies == []


# ── 财联社 ──────────────────────────────────────────────────


def test_cls_sign_algorithm_known_answer():
    assert cls.make_sign({"app": "CailianpressWeb", "os": "web", "rn": "50", "sv": "7.7.5"}) == (
        "afb8e5191c71b02d9f8c2a45270ab3e5"
    )


def test_cls_roll_to_result():
    payload = {
        "data": {
            "roll_data": [
                {
                    "id": 123456,
                    "title": "",
                    "content": "【央行开展5000亿元MLF操作】利率维持不变。",
                    "ctime": 1794400000,
                },
                {"id": 1, "content": "广告", "ctime": 1794400000, "is_ad": 1},
            ]
        }
    }
    result = cls.items_to_result(cls.parse_roll(payload), days=3, now=NOW)
    assert len(result.events) == 1
    assert result.events[0]["source_url"] == "https://www.cls.cn/detail/123456"
    assert result.events[0]["type"] == "macro_other"
    normalize_event(result.events[0])


# ── 金十 ────────────────────────────────────────────────────


def test_jin10_flash_to_result():
    payload = {
        "data": [
            {
                "id": "202611112300001",
                "time": "2026-11-11 23:00:00",
                "important": 1,
                "type": 0,
                "data": {"title": "【美国10月CPI同比3.1%】低于预期", "content": ""},
            },
            {
                "id": "ad",
                "time": "2026-11-11 23:01:00",
                "data": {"content": "开户广告"},
                "extras": {"ad": 1},
            },
        ]
    }
    result = jin10.items_to_result(jin10.parse_flash(payload), days=2, now=NOW)
    assert len(result.events) == 1
    ev = result.events[0]
    assert ev["type"] == "cpi"
    assert ev["confidence"] == 0.75
    assert ev["available_at"] == "2026-11-11T15:00:00Z"
    normalize_event(ev)


# ── 限频 / 熔断 ─────────────────────────────────────────────


def test_guard_opens_at_thirty_percent_and_persists(tmp_path):
    clock = [1000.0]
    kwargs = {
        "min_interval": 0,
        "window": 10,
        "min_samples": 4,
        "cooldown_s": 60,
        "state_dir": tmp_path,
        "clock": lambda: clock[0],
        "sleep": lambda _s: None,
    }
    guard = SourceGuard("demo", **kwargs)
    for ok in (False, False, True, False):  # 3/4 = 75%
        guard.record(ok)
    assert guard.is_open
    assert guard.failure_rate == 0.75

    reloaded = SourceGuard("demo", **kwargs)
    assert reloaded.is_open
    with pytest.raises(CircuitOpen):
        reloaded.before_request()

    clock[0] += 61  # 冷却结束
    reloaded.before_request()
    assert not reloaded.is_open


def test_guard_does_not_open_below_threshold(tmp_path):
    guard = SourceGuard(
        "ok",
        min_interval=0,
        window=10,
        min_samples=4,
        cooldown_s=60,
        state_dir=tmp_path,
        clock=lambda: 1000.0,
        sleep=lambda _s: None,
    )
    for ok in (True, True, True, False):  # 25% < 30%
        guard.record(ok)
    assert not guard.is_open
    assert guard.stats()["failure_rate"] == 0.25


# ── 事件契约汇总 ────────────────────────────────────────────


def test_all_sources_emit_valid_event_records():
    events = (
        sina.items_to_result([_sina_item()], days=3, now=NOW).events
        + wsc.lives_to_result(
            [{"content_text": "欧洲央行维持利率不变", "display_time": 1794400000}],
            days=3,
            now=NOW,
        ).events
        + cls.items_to_result(
            [{"id": 1, "content": "证监会立案调查某公司", "ctime": 1794400000}],
            days=3,
            now=NOW,
        ).events
        + jin10.items_to_result(
            [{"id": "x", "time": "2026-11-11 23:00:00", "data": {"content": "非农数据超预期"}}],
            days=2,
            now=NOW,
        ).events
    )
    assert len(events) == 4
    for ev in events:
        with pytest.raises(EventContractError):
            normalize_event(dict(ev, available_at=""))
        normalize_event(ev)
