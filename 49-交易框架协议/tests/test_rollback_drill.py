"""M0-05 rollback drill tests."""

from __future__ import annotations

from rollback_drill import run_drill


class TestRollbackDrill:
    def test_shadow_mode_drill_passes(self):
        report = run_drill(skip_pipeline=True)
        assert report["overall"] == "pass"
        ids = {check["id"] for check in report["checks"]}
        assert {
            "contract_integrity",
            "switch_rollback",
            "production_unchanged_with_shadow_switches",
            "execution_rights_default_paper",
        } <= ids

    def test_switches_reset_after_drill(self):
        from dreambuddy_evolution.agi_config import get_switch

        run_drill(skip_pipeline=True)
        assert get_switch("enable_cd_shadow", False) is False
        assert get_switch("enable_d2_oi_liq", False) is False
