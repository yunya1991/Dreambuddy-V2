# -*- coding: utf-8 -*-
"""gen_news_digest 契约测试（SPEC-41-L1-新闻意图检索 §6.3）。

守住 P3 执行器依赖的三条硬约束：schema 版本、coverage 逐日覆盖、去重语义。
"""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gen_news_digest.py"

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def _load_module():
    spec = importlib.util.spec_from_file_location("gen_news_digest", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(title, ts, origin="jin10", score=-0.8, etype="macro_other", topic=None):
    row = {
        "source": "events.jsonl",
        "raw": title,
        "timestamp": ts,
        "origin": origin,
        "symbol": "MACRO",
        "sentiment": {"score": score, "confidence": 0.9, "model": "ProsusAI/finbert"},
        "event": {"type": etype},
    }
    if topic:
        row["topic"] = topic
    return row


def test_schema_and_coverage_cover_every_day():
    mod = _load_module()
    rows = [_row("美联储维持利率不变", "2026-11-15T02:00:00Z")]
    payload = mod.build_news_digest(rows, now=NOW, window_days=7)
    assert payload["schema"] == "news_digest/v1"
    assert payload["window_days"] == 7
    assert len(payload["coverage"]) == 7
    assert payload["coverage"]["2026-11-15"] == 1
    assert payload["coverage"]["2026-11-10"] == 0  # 缺失日补 0
    assert payload["stats"]["total"] == 1


def test_dedup_keeps_earliest_and_counts_dup_and_sources():
    mod = _load_module()
    rows = [
        _row("美联储维持利率不变", "2026-11-15T02:00:00Z", origin="jin10"),
        _row("美联储维持利率不变", "2026-11-15T03:00:00Z", origin="cls"),
        _row("美联储维持利率不变！", "2026-11-15T04:00:00Z", origin="jin10"),
    ]
    payload = mod.build_news_digest(rows, now=NOW, window_days=7)
    assert payload["stats"]["total"] == 3
    assert payload["stats"]["dedup_saved"] == 2
    assert payload["stats"]["items"] == 1
    item = payload["items"][0]
    assert item["ts"] == "2026-11-15T02:00:00Z"  # 保留最早
    assert item["dup_count"] == 2
    assert item["source_count"] == 2  # jin10 + cls


def test_window_and_scope_filters():
    mod = _load_module()
    rows = [
        _row("窗口内事件", "2026-11-14T00:00:00Z"),
        _row("窗口外事件", (NOW - timedelta(days=40)).isoformat().replace("+00:00", "Z")),
        {**_row("非 events 源", "2026-11-14T00:00:00Z"), "source": "trader.log"},
        {**_row("无 event 块", "2026-11-14T00:00:00Z"), "event": None},
    ]
    payload = mod.build_news_digest(rows, now=NOW, window_days=30)
    titles = [i["title"] for i in payload["items"]]
    assert titles == ["窗口内事件"]


def test_write_is_idempotent_atomic(tmp_path):
    mod = _load_module()
    src = tmp_path / "semantic.jsonl"
    src.write_text(
        json.dumps(_row("以太坊跌破1800美元", "2026-11-14T20:54:46Z"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "news_digest.json"
    first = mod.write_news_digest(str(src), str(out), now=NOW, window_days=30)
    second = mod.write_news_digest(str(src), str(out), now=NOW, window_days=30)
    assert first["items"] == second["items"]
    assert not (tmp_path / "news_digest.json.tmp").exists()
    assert json.loads(out.read_text(encoding="utf-8"))["stats"]["items"] == 1
