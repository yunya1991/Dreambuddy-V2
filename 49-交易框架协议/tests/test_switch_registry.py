"""M0-04 switch registry tests."""
from __future__ import annotations

from validate_switches import load_registry, validate


class TestSwitchRegistry:
    def test_registry_validates(self):
        assert validate() == []

    def test_expected_switches_present(self):
        names = {entry["name"] for entry in load_registry()["switches"]}
        assert {
            "enable_cd_shadow",
            "enable_dominance_shadow",
            "enable_attention_a_dim",
            "enable_a_dim_c_to_3",
            "enable_primary_contradiction_detector",
            "enable_event_contradiction_shadow",
            "enable_w6_monitor",
            "enable_d2_oi_liq",
            "enable_self_vote_shadow",
            "enable_self_vote_cap",
        } <= names

    def test_all_defaults_false(self):
        assert all(
            entry["default"] is False
            for entry in load_registry()["switches"]
        )