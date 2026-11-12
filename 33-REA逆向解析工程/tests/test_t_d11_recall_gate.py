"""SPEC-33-D T-D11 — 分析前 recall 命中去重（RED）

契约：
  - 指纹 = sha1(realpath|git_head|scope)[:12]，稳定且区分 scope / HEAD
  - recall_query 必须带 `rea-fp:<fp>` 标记，供下次记录时写回
  - decide：命中同指纹且 ≤7 天 → reuse（复用 snapshot_id，不再 submit）；
            指纹不同 / 超期 / 无时间戳 → reanalyze
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.rea_recall_gate import (
    FP_TAG,
    build_query,
    decide,
    fingerprint,
    record_marker,
)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def test_fingerprint_is_stable_and_short():
    first = fingerprint("/repo/33-REA", scope="summary", git_head="abc1234")
    second = fingerprint("/repo/33-REA", scope="summary", git_head="abc1234")

    assert first == second
    assert len(first) == 12


def test_fingerprint_differs_by_scope_and_head():
    base = fingerprint("/repo/33-REA", scope="summary", git_head="abc1234")

    assert base != fingerprint("/repo/33-REA", scope="architecture", git_head="abc1234")
    assert base != fingerprint("/repo/33-REA", scope="summary", git_head="def5678")


def test_query_and_record_marker_carry_fingerprint():
    fp = fingerprint("/repo/33-REA", scope="summary", git_head="abc1234")
    query = build_query("/repo/33-REA", "summary", fp)

    assert record_marker(fp) == f"{FP_TAG}{fp}"
    assert record_marker(fp) in query
    assert "33-REA" in query


def _hit(fp, age_hours=1, snapshot_id="SNAP-1"):
    return {
        "content": f"架构结论… {record_marker(fp)}",
        "promoted_at": (NOW - timedelta(hours=age_hours)).isoformat(),
        "snapshot_id": snapshot_id,
    }


def test_decide_reuses_matching_fingerprint_within_window():
    fp = fingerprint("/repo/33-REA", git_head="abc1234")
    result = decide([_hit(fp)], fp, now=NOW)

    assert result["decision"] == "reuse"
    assert result["snapshot_id"] == "SNAP-1"


def test_decide_reanalyzes_on_different_fingerprint():
    other = fingerprint("/repo/33-REA", git_head="def5678")
    result = decide([_hit(other)], fingerprint("/repo/33-REA", git_head="abc1234"), now=NOW)

    assert result["decision"] == "reanalyze"
    assert "指纹" in result["reason"]


def test_decide_reanalyzes_when_hit_expired():
    fp = fingerprint("/repo/33-REA", git_head="abc1234")
    result = decide([_hit(fp, age_hours=24 * 8)], fp, now=NOW, max_age_days=7)

    assert result["decision"] == "reanalyze"
    assert "过期" in result["reason"]


def test_decide_reanalyzes_when_hit_has_no_timestamp():
    fp = fingerprint("/repo/33-REA", git_head="abc1234")
    result = decide([{"content": record_marker(fp)}], fp, now=NOW)

    assert result["decision"] == "reanalyze"
