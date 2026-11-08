"""B-01 / DEC-11: C→D 矛盾维度影子映射测试."""

from __future__ import annotations

from dreambuddy_evolution.core.cd_mapping import (
    C_TO_D_MAP,
    D_DIMENSIONS,
    attach_shadow,
    build_shadow,
    map_c_to_d,
)


class TestCDMapping:
    def test_all_c_to_d(self):
        assert map_c_to_d("C1") == "D2"
        assert map_c_to_d("C2") == "D4"
        assert map_c_to_d("C3") == "D3"
        assert map_c_to_d("C4") == "D1"

    def test_identity_dimensions(self):
        for dim in ("C6", "C7", "C8"):
            assert map_c_to_d(dim) == dim

    def test_news(self):
        assert map_c_to_d("news") == "NEWS"
        assert map_c_to_d(" news ") == "NEWS"

    def test_unknown_inputs_fail_open(self):
        assert map_c_to_d("C9") is None
        assert map_c_to_d(None) is None
        assert map_c_to_d(123) is None

    def test_shadow_payload(self):
        shadow = build_shadow("C4", direction="long", strength=0.7)
        assert shadow["c_dimension"] == "C4"
        assert shadow["d_dimension"] == "D1"
        assert shadow["mapped"] is True
        assert shadow["mapping_version"] == "cd-v1"
        assert shadow["direction"] == "long"
        assert shadow["strength"] == 0.7

    def test_shadow_unmapped(self):
        shadow = build_shadow("unknown")
        assert shadow["mapped"] is False
        assert shadow["d_dimension"] is None

    def test_all_targets_are_valid_d_dimensions(self):
        assert set(C_TO_D_MAP.values()) <= set(D_DIMENSIONS)

    def test_switch_defaults_off(self):
        from dreambuddy_evolution.agi_config import get_switch

        assert get_switch("enable_cd_shadow", False) is False

    def test_attach_shadow_disabled_keeps_production_fields(self):
        primary = {"dimension": "C4", "direction": "long", "strength": 0.8}
        result = attach_shadow(primary, enabled=False)
        assert result["dimension"] == "C4"
        assert "dimension_shadow" not in result

    def test_attach_shadow_enabled_does_not_change_dimension(self):
        primary = {"dimension": "C1", "direction": "short", "strength": 0.6}
        result = attach_shadow(primary, enabled=True)
        assert result["dimension"] == "C1"
        assert result["direction"] == "short"
        assert result["dimension_shadow"]["d_dimension"] == "D2"
        assert result["dimension_shadow"]["mapping_version"] == "cd-v1"

    def test_attach_shadow_ignores_non_dict(self):
        assert attach_shadow(None, enabled=True) is None
        assert attach_shadow("not-a-dict", enabled=True) == "not-a-dict"

    def test_identify_output_unchanged_with_shadow(self):
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )

        identifier = PrimaryContradictionIdentifier()
        paths = [
            {
                "path_id": "p1",
                "source": "bcrm",
                "direction": "long",
                "expected_return": 0.1,
                "confidence": 0.8,
                "resistance": 0.2,
            },
            {
                "path_id": "p2",
                "source": "strategic",
                "direction": "short",
                "expected_return": 0.05,
                "confidence": 0.3,
                "resistance": 0.7,
            },
        ]
        base = identifier.identify(paths, {}, {})
        shadowed = attach_shadow(dict(base), enabled=True)

        base_cmp = {k: v for k, v in base.items() if k != "dimension_shadow"}
        shadow_cmp = {k: v for k, v in shadowed.items() if k != "dimension_shadow"}
        assert shadow_cmp == base_cmp
        assert shadowed["dimension"] == base["dimension"]
        assert shadowed["dimension_shadow"]["d_dimension"] == map_c_to_d(base["dimension"])
