"""P2-1a RED: BdsmSignalLevelClassifier — BDSM 做多三层置信度递进开仓判定.

SPEC: docs/superpowers/specs/2026-09-18-bdsm-tiered-confidence-open-spec.md v2.0 §2.2/§3
接线目标: three_factor_long 引擎（当前生产零引用）通过本分类器接入 _bdsm_independent_open。

铁律（spec §0.2）:
  R1 战略层方向过滤优先 — direction_state 禁多一律 None
  R2 置信度递进 = AND 叠加
  R4 FAIL-OPEN — 信号缺失/异常 → None（不开仓）
"""
import pytest


class TestBdsmSignalLevelClassifierImport:
    def test_module_exists(self):
        from dreambuddy_evolution.engines.bdsm_signal_level import (
            BdsmSignalLevelClassifier,
        )


class TestStrategicDirectionFilter:
    """R1: 战略层 direction_state 过滤。"""

    def _cls(self):
        from dreambuddy_evolution.engines.bdsm_signal_level import (
            BdsmSignalLevelClassifier,
        )
        return BdsmSignalLevelClassifier()

    @pytest.mark.parametrize("state", ["LONG_ONLY", "LONG_PREFER", "NEUTRAL"])
    def test_allowed_states_pass(self, state):
        result = self._cls().classify_long(
            direction_state=state,
            bds_score=0.5,
            three_factor_signal=False,
            trend_action="none",
        )
        assert result is not None

    @pytest.mark.parametrize("state", ["SHORT_ONLY", "SHORT_PREFER", "FREEZE"])
    def test_forbidden_states_blocked(self, state):
        result = self._cls().classify_long(
            direction_state=state,
            bds_score=0.5,
            three_factor_signal=True,
            trend_action="none",
        )
        assert result is None

    def test_none_direction_state_fail_open(self):
        assert (
            self._cls().classify_long(
                direction_state=None, bds_score=0.5,
                three_factor_signal=False, trend_action="none",
            )
            is None
        )

    def test_lowercase_state_normalized(self):
        result = self._cls().classify_long(
            direction_state="long_only",
            bds_score=0.5,
            three_factor_signal=False,
            trend_action="none",
        )
        assert result is not None


class TestLongTierProgression:
    """R2: AND 逐层叠加 — L1(bds>0) → L2(+三因子) → L3(+MA200)。"""

    def _cls(self):
        from dreambuddy_evolution.engines.bdsm_signal_level import (
            BdsmSignalLevelClassifier,
        )
        return BdsmSignalLevelClassifier()

    def test_l1_basic(self):
        result = self._cls().classify_long(
            direction_state="NEUTRAL",
            bds_score=0.5,
            three_factor_signal=False,
            trend_action="none",
        )
        assert result.level == "L1"

    def test_l2_with_three_factor(self):
        result = self._cls().classify_long(
            direction_state="LONG_ONLY",
            bds_score=0.5,
            three_factor_signal=True,
            trend_action="reduce50",
        )
        assert result.level == "L2"

    def test_l3_full_stack(self):
        result = self._cls().classify_long(
            direction_state="LONG_ONLY",
            bds_score=0.5,
            three_factor_signal=True,
            trend_action="none",
        )
        assert result.level == "L3"

    def test_bds_non_positive_returns_none(self):
        assert (
            self._cls().classify_long(
                direction_state="LONG_ONLY", bds_score=0.0,
                three_factor_signal=False, trend_action="none",
            )
            is None
        )
        assert (
            self._cls().classify_long(
                direction_state="LONG_ONLY", bds_score=-0.2,
                three_factor_signal=False, trend_action="none",
            )
            is None
        )


class TestPositionParams:
    """R3: 仓位参数表 — L1 0.05/3x / L2 0.08/3x / L3 0.12/5x，做多 is_trial=False。"""

    def _cls(self):
        from dreambuddy_evolution.engines.bdsm_signal_level import (
            BdsmSignalLevelClassifier,
        )
        return BdsmSignalLevelClassifier()

    def test_param_table(self):
        cls = self._cls()
        r1 = cls.classify_long("LONG_ONLY", 0.5, False, "reduce50")
        r2 = cls.classify_long("LONG_ONLY", 0.5, True, "reduce50")
        r3 = cls.classify_long("LONG_ONLY", 0.5, True, "none")
        assert (r1.position_pct, r1.leverage, r1.is_trial) == (0.05, 3, False)
        assert (r2.position_pct, r2.leverage, r2.is_trial) == (0.08, 3, False)
        assert (r3.position_pct, r3.leverage, r3.is_trial) == (0.12, 5, False)


class TestFailOpen:
    """R4: 信号缺失/异常 → 降级到满足的最高层级或 None。"""

    def _cls(self):
        from dreambuddy_evolution.engines.bdsm_signal_level import (
            BdsmSignalLevelClassifier,
        )
        return BdsmSignalLevelClassifier()

    def test_none_bds_fail_open(self):
        assert (
            self._cls().classify_long(
                direction_state="LONG_ONLY", bds_score=None,
                three_factor_signal=False, trend_action="none",
            )
            is None
        )

    def test_none_three_factor_stays_l1(self):
        result = self._cls().classify_long(
            direction_state="LONG_ONLY", bds_score=0.5,
            three_factor_signal=None, trend_action="none",
        )
        assert result.level == "L1"

    def test_bad_trend_action_stays_l2(self):
        result = self._cls().classify_long(
            direction_state="LONG_ONLY", bds_score=0.5,
            three_factor_signal=True, trend_action=None,
        )
        assert result.level == "L2"

    def test_trend_action_dict_entry_accepted(self):
        """trend_action 可传 coin_entry["trend_stop"] dict（polling_trader 现场形态）。"""
        result = self._cls().classify_long(
            direction_state="LONG_ONLY",
            bds_score=0.5,
            three_factor_signal=True,
            trend_action={"action": "none"},
        )
        assert result.level == "L3"
