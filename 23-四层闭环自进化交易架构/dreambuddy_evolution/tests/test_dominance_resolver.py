"""B-02 / DEC-12: 成对支配解析器测试."""

from __future__ import annotations

from dreambuddy_evolution.core.dominance_resolver import (
    METHOD_VERSION,
    resolve,
    resolve_shadow,
)


def _path(path_id, direction, score, **kwargs):
    return {
        "path_id": path_id,
        "source": kwargs.get("source", "test"),
        "direction": direction,
        "score": score,
        "confidence": kwargs.get("confidence", 0.8),
        "expected_return": kwargs.get("expected_return", 0.1),
        "resistance": kwargs.get("resistance", 0.2),
        "continuation_score": kwargs.get("continuation_score", 0.5),
    }


class TestDominanceResolver:
    def test_single_path(self):
        result = resolve([_path("a", "long", 0.9)], primary_contradiction={"direction": "long"})
        assert result["method"] == METHOD_VERSION
        assert result["dominant_path_id"] == "a"
        assert result["agreement"] is False  # production_path_id 未传入

    def test_same_direction_higher_strength_wins(self):
        paths = [
            _path("strong", "long", 0.9),
            _path("weak", "long", 0.3),
        ]
        result = resolve(paths, primary_contradiction={"direction": "neutral"})
        assert result["dominant_path_id"] == "strong"
        assert result["matrix"]["strong"]["weak"] > 0
        assert result["matrix"]["weak"]["strong"] < 0

    def test_primary_direction_overrides_raw_score(self):
        paths = [
            _path("raw_high_short", "short", 0.9),
            _path("aligned_long", "long", 0.3),
        ]
        result = resolve(paths, primary_contradiction={"direction": "long"})
        assert result["dominant_path_id"] == "aligned_long"
        assert result["matrix"]["aligned_long"]["raw_high_short"] > 0

    def test_matrix_is_antisymmetric(self):
        paths = [
            _path("a", "long", 0.9),
            _path("b", "short", 0.5),
            _path("c", "neutral", 0.2),
        ]
        result = resolve(paths, primary_contradiction={"direction": "long"})
        matrix = result["matrix"]
        for left in ("a", "b", "c"):
            for right in ("a", "b", "c"):
                if left == right:
                    continue
                assert matrix[left][right] == -matrix[right][left]

    def test_copeland_dominant(self):
        paths = [
            _path("a", "long", 0.9),
            _path("b", "long", 0.5),
            _path("c", "long", 0.1),
        ]
        result = resolve(paths, primary_contradiction={"direction": "neutral"})
        assert result["dominant_path_id"] == "a"
        assert result["copeland"]["a"] == 2

    def test_backtest_argmax_vs_dominance(self):
        """构造 argmax 选错、dominance 选对的场景."""
        paths = [
            _path("argmax_short", "short", 0.9),
            _path("aligned_long", "long", 0.3),
        ]
        production = max(paths, key=lambda item: item["score"])["path_id"]
        result = resolve(
            paths,
            primary_contradiction={"direction": "long"},
            production_path_id=production,
        )
        assert production == "argmax_short"
        assert result["dominant_path_id"] == "aligned_long"
        assert result["agreement"] is False
        assert len(result["pairwise"]) == 1
        assert result["pairwise"][0]["winner"] == "aligned_long"
        assert "alignment_delta" in result["pairwise"][0]["reasons"]

    def test_empty_and_invalid_inputs(self):
        assert resolve([]) is None
        assert resolve(None) is None
        assert resolve("not-a-list") is None

    def test_missing_fields_fail_open(self):
        result = resolve([{"path_id": "a"}, {"path_id": "b", "direction": "long"}])
        assert result is not None
        assert result["dominant_path_id"] in ("a", "b")

    def test_resolve_shadow_disabled(self):
        paths = [_path("a", "long", 0.9)]
        assert resolve_shadow(paths, enabled=False) is None

    def test_shadow_agreement_flag(self):
        paths = [_path("a", "long", 0.9), _path("b", "short", 0.3)]
        result = resolve_shadow(
            paths,
            primary_contradiction={"direction": "long"},
            production_path_id="a",
            enabled=True,
        )
        assert result["dominant_path_id"] == "a"
        assert result["agreement"] is True

    def test_switch_defaults_off(self):
        from dreambuddy_evolution.agi_config import get_switch

        assert get_switch("enable_dominance_shadow", False) is False
