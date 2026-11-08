"""B-08: 自票上限 / 独立矛盾证据 shadow 测试."""

from __future__ import annotations

import copy
import json

from dreambuddy_evolution.core.self_vote_guard import (
    EXTERNAL_SOURCES,
    SELF_SOURCES,
    compute_self_vote_shadow,
)


def _path(path_id, source, direction, confidence):
    return {
        "path_id": path_id,
        "source": source,
        "direction": direction,
        "confidence": confidence,
        "expected_return": 0.1,
        "resistance": 0.2,
    }


class TestSelfVoteGuard:
    def test_self_only_would_cap(self):
        paths = [
            _path("p1", "l2_gene", "long", 0.8),
            _path("p2", "synthesized", "long", 0.7),
        ]
        shadow = compute_self_vote_shadow(paths, {"direction": "long"}, enabled=True)
        assert shadow["available"] is True
        assert shadow["self_vote_ratio"] == 1.0
        assert shadow["independent_evidence"] is False
        assert shadow["would_cap"] is True
        assert "self_vote_ratio_above_cap" in shadow["reasons"]

    def test_external_aligned_prevents_cap(self):
        paths = [
            _path("p1", "l2_gene", "long", 0.8),
            _path("p2", "synthesized", "long", 0.7),
            _path("p3", "bcrm", "long", 0.7),
        ]
        shadow = compute_self_vote_shadow(paths, {"direction": "long"}, enabled=True)
        assert shadow["independent_evidence"] is True
        assert shadow["would_cap"] is False
        assert shadow["external_sources"] == ["bcrm"]

    def test_external_opposite_does_not_help(self):
        paths = [
            _path("p1", "l2_gene", "long", 0.9),
            _path("p2", "synthesized", "long", 0.8),
            _path("p3", "bcrm", "short", 0.9),
        ]
        shadow = compute_self_vote_shadow(paths, {"direction": "long"}, enabled=True)
        assert shadow["independent_evidence"] is False
        assert shadow["would_cap"] is True

    def test_below_cap(self):
        paths = [
            _path("p1", "l2_gene", "long", 0.2),
            _path("p2", "bcrm", "long", 0.9),
        ]
        shadow = compute_self_vote_shadow(paths, {"direction": "long"}, enabled=True)
        assert shadow["self_vote_ratio"] < shadow["cap_ratio"]
        assert shadow["would_cap"] is False

    def test_neutral_primary_does_not_cap(self):
        paths = [_path("p1", "l2_gene", "long", 0.9)]
        shadow = compute_self_vote_shadow(paths, {"direction": "neutral"}, enabled=True)
        assert shadow["would_cap"] is False
        assert "primary_direction_neutral" in shadow["reasons"]

    def test_min_external_confidence(self):
        paths = [
            _path("p1", "l2_gene", "long", 0.9),
            _path("p2", "bcrm", "long", 0.4),
        ]
        shadow = compute_self_vote_shadow(
            paths,
            {"direction": "long"},
            enabled=True,
            min_external_confidence=0.5,
        )
        assert shadow["independent_evidence"] is False

    def test_custom_cap(self):
        paths = [_path("p1", "l2_gene", "long", 0.9)]
        assert (
            compute_self_vote_shadow(paths, {"direction": "long"}, enabled=True, cap_ratio=1.0)[
                "would_cap"
            ]
            is False
        )

    def test_unknown_source_is_external(self):
        paths = [
            _path("p1", "l2_gene", "long", 0.9),
            _path("p2", "mystery", "long", 0.8),
        ]
        shadow = compute_self_vote_shadow(paths, {"direction": "long"}, enabled=True)
        assert "mystery" in shadow["external_sources"]
        assert shadow["independent_evidence"] is True

    def test_disabled_returns_none(self):
        assert compute_self_vote_shadow([], enabled=False) is None

    def test_invalid_inputs(self):
        assert compute_self_vote_shadow(None, enabled=True)["available"] is False
        assert compute_self_vote_shadow([], enabled=True)["available"] is False
        assert compute_self_vote_shadow([1, 2], enabled=True)["available"] is False

    def test_audit_jsonl(self, tmp_path):
        audit_path = tmp_path / "self_vote_audit.jsonl"
        paths = [_path("p1", "l2_gene", "long", 0.9)]
        shadow = compute_self_vote_shadow(
            paths,
            {"direction": "long"},
            enabled=True,
            audit_path=str(audit_path),
        )
        assert shadow["would_cap"] is True
        lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["method"] == "self-vote-guard-v1"
        assert record["would_cap"] is True

    def test_does_not_mutate_paths(self):
        paths = [_path("p1", "l2_gene", "long", 0.9)]
        before = copy.deepcopy(paths)
        compute_self_vote_shadow(paths, {"direction": "long"}, enabled=True)
        assert paths == before

    def test_sets_and_switch_defaults(self):
        from dreambuddy_evolution.agi_config import get_switch

        assert "l2_gene" in SELF_SOURCES
        assert "bcrm" in EXTERNAL_SOURCES
        assert get_switch("enable_self_vote_shadow", False) is False
        assert get_switch("enable_self_vote_cap", False) is False
