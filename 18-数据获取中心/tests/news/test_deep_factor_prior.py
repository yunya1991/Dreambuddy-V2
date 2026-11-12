"""P1-D 深度文章组合因子（SPEC-EMERGENCE-FINANCIAL-ENV §8.3）单测。

覆盖：去 degraded / SPEC 字段契约 / 按源分层 / 弱证据隔离 / 缺正文与缺文件降级。
"""

from __future__ import annotations

import json
from pathlib import Path

from data_center.processing.deep_factor_prior import (
    COMPOSITE_VERSION,
    build_composite_prior,
    tier_of,
)

BULL_TEXT = "美联储降息预期升温，流动性宽松推动比特币上涨，ETF资金流入明显，机构入场。"
SPEC_FIELDS = {
    "dominant_factor",
    "direction",
    "horizon",
    "urgency",
    "impact",
    "composite_score",
    "source_mix",
    "article_count",
}


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path


def _corpus(tmp_path: Path, n: int, source: str = "sina_finance", text: str = BULL_TEXT):
    events, bodies = [], []
    for i in range(n):
        bid = f"body{i:04d}"
        events.append(
            {
                "event_id": f"ev{i:04d}",
                "source": source,
                "event_time": f"2026-11-{1 + i % 10:02d}T00:00:00Z",
                "available_at": f"2026-11-{1 + i % 10:02d}T00:00:00Z",
                "body_ref": f"bodies.jsonl#{bid}",
                "title": "t",
            }
        )
        bodies.append(
            {
                "id": bid,
                "source": source,
                "content_text": text,
                "fetch_ok": True,
                "date_published": "2026-11-01T00:00:00Z",
            }
        )
    return (
        _write_jsonl(tmp_path / "events.jsonl", events),
        _write_jsonl(tmp_path / "bodies.jsonl", bodies),
    )


def test_builds_non_degraded_composite_prior(tmp_path):
    ev, bo = _corpus(tmp_path, 40)
    out = tmp_path / "factor_prior.json"
    res = build_composite_prior(events_path=ev, bodies_path=bo, out_path=out)

    assert out.exists()
    assert res["version"] == COMPOSITE_VERSION
    assert res["degraded"] is False
    assert res["degraded_reason"] is None
    assert res["n_articles"] == 40
    assert res["n_sources"] == 1
    assert res["n_factors"] > 0
    assert res["as_of"] == "2026-11-10"

    top = res["factors"][0]
    assert SPEC_FIELDS <= set(top)
    assert top["dominant_factor"] == "macro.rate"
    assert sum(f["article_count"] for f in res["factors"]) == 40
    assert res["dims"].get("D1", 0) > 0
    # 快讯先验状态如实保留，不被组合因子覆盖
    assert res["newsflash"]["reason"] == "newsflash_prior_disabled_by_default"


def test_layers_by_source_tier(tmp_path):
    ev1, bo1 = _corpus(tmp_path, 40, source="wallstreetcn")
    ev2, bo2 = _corpus(tmp_path / "crypto", 40, source="odaily")
    bo = tmp_path / "bodies_all.jsonl"
    _write_jsonl(
        bo,
        [json.loads(line) for line in bo1.read_text().splitlines()]
        + [json.loads(line) for line in bo2.read_text().splitlines()],
    )
    ev = tmp_path / "events_all.jsonl"
    _write_jsonl(
        ev,
        [json.loads(line) for line in ev1.read_text().splitlines()]
        + [json.loads(line) for line in ev2.read_text().splitlines()],
    )
    res = build_composite_prior(events_path=ev, bodies_path=bo, out_path=tmp_path / "o.json")

    by = res["by_source"]
    assert set(by) == {"traditional_finance", "crypto"}
    assert by["traditional_finance"]["n_articles"] == 40
    assert by["crypto"]["n_articles"] == 40
    assert by["crypto"]["weak_evidence"] is False
    assert res["n_sources"] == 2


def test_weak_evidence_source_excluded_from_formal_factors(tmp_path):
    ev, bo = _corpus(tmp_path, 20, source="cls")  # 20 < 30
    res = build_composite_prior(events_path=ev, bodies_path=bo, out_path=tmp_path / "o.json")

    assert res["n_factors"] == 0
    assert res["degraded"] is True
    assert res["degraded_reason"] == "no_formal_factors"
    assert [w["source"] for w in res["weak_evidence_sources"]] == ["cls"]
    # 弱证据仍保留在分层报告里，不丢数据
    assert res["by_source"]["traditional_finance"]["weak_evidence"] is True


def test_missing_events_is_degraded(tmp_path):
    res = build_composite_prior(
        events_path=tmp_path / "nope.jsonl",
        bodies_path=tmp_path / "nope2.jsonl",
        out_path=tmp_path / "o.json",
    )
    assert res["degraded"] is True
    assert res["degraded_reason"] == "events_missing"
    assert json.loads((tmp_path / "o.json").read_text())["degraded"] is True


def test_events_without_body_do_not_produce_claims(tmp_path):
    ev = _write_jsonl(
        tmp_path / "events.jsonl",
        [{"event_id": "e1", "source": "cls", "body_ref": None, "event_time": "2026-11-01"}],
    )
    bo = _write_jsonl(tmp_path / "bodies.jsonl", [])
    res = build_composite_prior(events_path=ev, bodies_path=bo, out_path=tmp_path / "o.json")
    assert res["n_articles"] == 0
    assert res["n_without_body"] == 1
    assert res["degraded_reason"] == "no_dominance_claims"


def test_tier_of_mapping():
    assert tier_of("sina_finance") == "traditional_finance"
    assert tier_of("jin10") == "traditional_finance"
    assert tier_of("odaily") == "crypto"
    assert tier_of("unknown_feed") == "other"
    assert tier_of(None) == "other"
