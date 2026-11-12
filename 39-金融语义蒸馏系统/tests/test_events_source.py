"""P0-A：39 语义层接 canonical EventRecord + 9 域 FinBERT 打分服务。"""

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gen_semantic_events.py"

EVENT = {
    "event_id": "EV-20261111-0001",
    "type": "cpi",
    "title": "美国 10 月 CPI 同比 3.2%，低于预期 3.4%",
    "body": "核心 CPI 同比 3.3%，前值 3.4%。",
    "symbols": ["US500", "TLT"],
    "surprise": -0.2,
    "surprise_unit": "ppt",
    "event_time": "2026-11-11T12:30:00Z",
    "available_at": "2026-11-11T12:30:03Z",
}

GOOD_SCORE = {
    "score": 0.62,
    "confidence": 0.81,
    "model": "finbert-tone-chinese",
    "half_life_h": 24,
}


def load_module():
    spec = importlib.util.spec_from_file_location("gse_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_single_event_emits_sentiment_block(tmp_path):
    mod = load_module()
    events = tmp_path / "events.jsonl"
    out = tmp_path / "semantic.jsonl"
    write_jsonl(events, [EVENT])

    emitted, skipped = mod.emit_from_events(events, out, scorer=lambda text, hl: dict(GOOD_SCORE))

    assert (len(emitted), skipped) == (1, 0)
    line = read_jsonl(out)[0]
    assert line["sentiment"]["score"] == 0.62
    assert line["sentiment"]["confidence"] == 0.81
    assert line["sentiment"]["model"] == "finbert-tone-chinese"
    assert line["sentiment"]["half_life_h"] == 24
    assert line["event"] == {"type": "cpi", "surprise": -0.2, "surprise_unit": "ppt"}
    assert line["trace_id"] == EVENT["event_id"]
    assert line["timestamp"] == EVENT["available_at"]
    assert line["symbol"] == "US500"
    assert line["source"] == "events.jsonl"


def test_sentiment_null_is_legal(tmp_path):
    mod = load_module()
    events = tmp_path / "events.jsonl"
    out = tmp_path / "semantic.jsonl"
    write_jsonl(events, [EVENT])

    mod.emit_from_events(events, out, scorer=lambda text, hl: None)

    line = read_jsonl(out)[0]
    assert line["sentiment"] is None
    assert line["values"] == []
    assert line["event"]["type"] == "cpi"


def test_old_lines_untouched_and_idempotent(tmp_path):
    mod = load_module()
    events = tmp_path / "events.jsonl"
    out = tmp_path / "semantic.jsonl"
    write_jsonl(events, [EVENT])
    legacy = {
        "raw": "旧行",
        "source": "trader.log",
        "symbol": "BTC",
        "term": "BTC",
        "timestamp": "2026-01-01T00:00:00Z",
        "values": [],
    }
    original = json.dumps(legacy, ensure_ascii=False)
    out.write_text(original + "\n", encoding="utf-8")

    mod.emit_from_events(events, out, scorer=lambda text, hl: dict(GOOD_SCORE))
    first_run = out.read_text(encoding="utf-8")
    assert first_run.splitlines()[0] == original
    assert len(first_run.splitlines()) == 2

    emitted, skipped = mod.emit_from_events(events, out, scorer=lambda text, hl: dict(GOOD_SCORE))
    assert (len(emitted), skipped) == (0, 1)
    assert out.read_text(encoding="utf-8") == first_run


def test_timestamp_falls_back_to_event_time(tmp_path):
    mod = load_module()
    events = tmp_path / "events.jsonl"
    out = tmp_path / "semantic.jsonl"
    ev = dict(EVENT)
    ev.pop("available_at")
    write_jsonl(events, [ev])

    mod.emit_from_events(events, out, scorer=lambda text, hl: None)
    assert read_jsonl(out)[0]["timestamp"] == EVENT["event_time"]


def test_model_name_is_normalized_to_four_values():
    mod = load_module()
    assert mod._normalize_model("yiyanghkust/finbert-tone-chinese") == "finbert-tone-chinese"
    assert mod._normalize_model("ProsusAI/finbert") == "ProsusAI/finbert"
    assert mod._normalize_model("rule_fallback") == "rule_fallback"
    assert mod._normalize_model(None) == "unavailable"
    # 本地路径含用户名 zh... 不得误判为中文模型（P0-C E2E 实测 bug）
    local_en = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析/models/finbert"
    assert mod._normalize_model(local_en) == "ProsusAI/finbert"
    assert mod._normalize_model("/models/finbert-zh") == "finbert-tone-chinese"


def test_missing_events_file_is_noop(tmp_path):
    mod = load_module()
    out = tmp_path / "semantic.jsonl"
    emitted, skipped = mod.emit_from_events(
        tmp_path / "absent.jsonl", out, scorer=lambda t, h: None
    )
    assert (emitted, skipped) == ([], 0)
    assert not out.exists()


def test_body_ref_resolved_from_bodies_store(tmp_path):
    """P1-A：中文财经源正文外置，body_ref 必须能解析回正文再打分。"""
    mod = load_module()
    events = tmp_path / "events.jsonl"
    out = tmp_path / "semantic.jsonl"
    bodies = tmp_path / "bodies.jsonl"
    ev = {k: v for k, v in EVENT.items() if k != "body"}
    ev["body_ref"] = "bodies.jsonl#abc123"
    write_jsonl(events, [ev])
    write_jsonl(bodies, [{"id": "abc123", "content_text": "美联储降息，美股收涨。"}])

    seen = {}

    def scorer(text, half_life):
        seen["text"] = text
        return dict(GOOD_SCORE)

    mod.emit_from_events(events, out, scorer=scorer, bodies_path=str(bodies))
    assert "美联储降息" in seen["text"]
    assert read_jsonl(out)[0]["sentiment"]["score"] == 0.62
