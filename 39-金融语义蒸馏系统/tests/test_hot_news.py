"""SPEC-20261113：热点新闻影响力榜（topic / 去重 / importance / 产物契约）。"""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gen_semantic_events.py"
NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)


def load_module():
    spec = importlib.util.spec_from_file_location("gse_hot_news_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(
    trace_id,
    title,
    minutes_ago=60,
    source="events.jsonl",
    etype="macro_other",
    score=0.6,
    confidence=0.9,
    origin="jin10",
    symbol="MACRO",
    **extra,
):
    ts = (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sentiment = (
        None
        if score is None
        else {
            "score": score,
            "confidence": confidence,
            "model": "finbert-tone-chinese",
            "half_life_h": 24,
        }
    )
    out = {
        "term": title[:80],
        "timestamp": ts,
        "symbol": symbol,
        "values": [],
        "raw": title,
        "source": source,
        "origin": origin,
        "sentiment": sentiment,
        "event": {"type": etype, "surprise": None, "surprise_unit": None},
        "trace_id": trace_id,
    }
    out.update(extra)
    return out


def test_topic_priority_first_rule_wins():
    mod = load_module()
    # 「美联储」在 rates_policy 表序最前，即使同时命中 CPI
    assert mod.topic_of("美联储：CPI 同比 3.2%，低于预期") == "rates_policy"
    assert mod.topic_of("英伟达发布新款 AI 芯片") == "tech_ai"
    assert mod.topic_of("某公司发布一般性公告") == "other"


def test_corroboration_curve_matches_spec():
    mod = load_module()
    assert mod.corroboration_from_source_count(1) == 0.5
    assert mod.corroboration_from_source_count(2) == 0.815
    assert mod.corroboration_from_source_count(3) == 1.0
    assert mod.corroboration_from_source_count(9) == 1.0


def test_dedupe_merges_cross_source_boilerplate():
    mod = load_module()
    rows = [
        row(
            "t1",
            "财联社11月13日电，美联储维持利率不变，符合预期",
            minutes_ago=120,
            origin="cls",
            etype="rate_decision",
        ),
        row(
            "t2",
            "据纽约时报：美联储维持利率不变，符合预期",
            minutes_ago=60,
            origin="sina_finance",
            etype="rate_decision",
        ),
    ]
    payload = mod.build_hot_news(rows, now=NOW)

    assert payload["stats"]["total"] == 2
    assert payload["stats"]["clusters"] == 1
    assert payload["stats"]["dedup_saved"] == 1
    assert len(payload["top"]) == 1
    item = payload["top"][0]
    assert item["source_count"] == 2
    assert item["dup_count"] == 1
    # 簇代表必须是簇内已打分成员（importance 最高者）
    assert item["event_id"] in {"t1", "t2"}
    assert item["importance"] > 0


def test_dedupe_merges_rewrite_via_ratio():
    mod = load_module()
    rows = [
        row("t1", "美联储正处于招聘的完美风暴", minutes_ago=90),
        row("t2", "美联储正处在招聘的完美风暴", minutes_ago=30),
    ]
    payload = mod.build_hot_news(rows, now=NOW)
    assert payload["stats"]["clusters"] == 1
    assert len(payload["top"]) == 1


def test_dedupe_does_not_merge_different_statements():
    mod = load_module()
    rows = [
        row("t1", "美联储戴利：AI 将带来价格压力", minutes_ago=90),
        row("t2", "美联储戴利：AI 对劳动力市场影响有限", minutes_ago=30),
    ]
    payload = mod.build_hot_news(rows, now=NOW)
    assert payload["stats"]["clusters"] == 2
    assert len(payload["top"]) == 2


def test_importance_monotonic_by_recency_and_type():
    mod = load_module()
    newer, _ = mod.importance(
        published_at="2026-11-13T11:00:00Z",
        etype="rate_decision",
        sentiment={"score": 0.5, "confidence": 0.9, "half_life_h": 24},
        origin="jin10",
        now=NOW,
    )
    older, _ = mod.importance(
        published_at="2026-11-13T00:00:00Z",
        etype="rate_decision",
        sentiment={"score": 0.5, "confidence": 0.9, "half_life_h": 24},
        origin="jin10",
        now=NOW,
    )
    assert newer > older

    strong, _ = mod.importance(
        published_at="2026-11-13T11:00:00Z",
        etype="rate_decision",
        sentiment={"score": 0.5, "confidence": 0.9, "half_life_h": 24},
        origin="jin10",
        now=NOW,
    )
    weak, _ = mod.importance(
        published_at="2026-11-13T11:00:00Z",
        etype="macro_other",
        sentiment={"score": 0.5, "confidence": 0.9, "half_life_h": 24},
        origin="jin10",
        now=NOW,
    )
    assert strong > weak


def test_unscored_event_never_enters_top():
    mod = load_module()
    payload = mod.build_hot_news([row("t1", "美联储维持利率不变", score=None)], now=NOW)
    assert payload["top"] == []
    assert payload["stats"]["total"] == 1
    assert payload["stats"]["unscored"] == 1
    assert payload["stats"]["scored"] == 0
    assert payload["degraded"] is True


def test_trader_log_rows_are_excluded():
    mod = load_module()
    legacy = {
        "term": "BTC",
        "timestamp": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbol": "BTC",
        "values": [],
        "raw": "BTC",
        "source": "trader.log",
    }
    payload = mod.build_hot_news([legacy], now=NOW)
    assert payload["stats"]["total"] == 0
    assert payload["top"] == []


def test_old_line_without_ranking_fields_is_recomputed():
    mod = load_module()
    legacy = row("t-old", "美联储逆回购接纳 1 个对手方 2.5 亿美元", origin=None)
    payload = mod.build_hot_news([legacy], now=NOW)
    assert len(payload["top"]) == 1
    item = payload["top"][0]
    assert item["recomputed"] is True
    assert item["topic"] == "rates_policy"
    assert item["importance"] > 0
    assert item["source_url"] is None


def test_atomic_write_produces_parseable_json(tmp_path):
    mod = load_module()
    semantic = tmp_path / "semantic.jsonl"
    out = tmp_path / "hot_news.json"
    semantic.write_text(
        "\n".join(
            json.dumps(r, ensure_ascii=False) for r in [row("t1", "美联储维持利率不变，符合预期")]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = mod.write_hot_news(semantic_path=str(semantic), out_path=str(out), now=NOW)

    assert payload["generated_at"] == "2026-11-13T12:00:00Z"
    assert json.loads(out.read_text(encoding="utf-8"))["top"][0]["event_id"] == "t1"
    assert not (tmp_path / "hot_news.json.tmp").exists()


def test_title_short_keeps_short_and_truncates_long():
    mod = load_module()
    assert mod.title_short("美联储维持利率不变") == "美联储维持利率不变"
    short = mod.title_short(
        "美联储在固定利率逆回购操作中总计接纳了1个对手方的2.5亿美元资金规模创下历史新高"
    )
    assert len(short) <= 41
    assert short.endswith("…")
    # 硬截断不得把英文/数字切成半截：省略号前应是中文字符
    assert not short[-2].isascii()
