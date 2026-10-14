"""
Shadow 自动放量门禁 TDD 测试
SPEC-Shadow验证自动放量门禁.md §10 #1-#12 + spawn 正/反向
"""
from __future__ import annotations

import json
from datetime import date

import pytest

SWITCH = "enable_causal_historical_samples"
GATE_SWITCH = "enable_shadow_auto_activation"


@pytest.fixture(autouse=True)
def _no_real_spawn(monkeypatch):
    """禁止测试起真实评估子进程（DML≈35s）；返回调用计数 spy。"""
    from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
    calls = {"n": 0}

    def _fake(self):
        calls["n"] += 1
        return True

    monkeypatch.setattr(ShadowActivationGate, "_spawn_evaluator", _fake, raising=True)
    return calls


def _gate(tmp_path, switch=SWITCH):
    from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
    return ShadowActivationGate(switch, state_dir=tmp_path)


def _obs(date_s, gate_state="B", n=1000, method="causalml_dml",
         ate=0.0, lb=-0.01, ub=0.01):
    return {"date": date_s, "gate_state": gate_state, "ate": ate, "lb": lb,
            "ub": ub, "source": "bootstrap", "n": n, "method": method}


def _seed_days(gate, days, gate_state="B"):
    for i in range(days):
        assert gate.record(_obs(f"2026-01-{i + 1:02d}", gate_state=gate_state))


def test_defaults():
    from dreambuddy_evolution.agi_config import AGI_SWITCHES
    assert AGI_SWITCHES["enable_causal_historical_samples"] is False
    assert AGI_SWITCHES["enable_shadow_auto_activation"] is True


class TestShadowActivationGate:
    def test_1_insufficient_days_no_activation(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True)
        set_switch(SWITCH, False)
        g = _gate(tmp_path)
        _seed_days(g, 6, "A")
        assert g.maybe_activate() is False
        assert get_switch(SWITCH, False) is False

    def test_2_seven_days_no_positive_no_activation(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True)
        set_switch(SWITCH, False)
        g = _gate(tmp_path)
        _seed_days(g, 7, "B")
        assert g.maybe_activate() is False
        assert get_switch(SWITCH, False) is False

    def test_3_seven_days_with_positive_activates(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True)
        set_switch(SWITCH, False)
        g = _gate(tmp_path)
        _seed_days(g, 6, "B")
        assert g.record(_obs("2026-01-07", "A", ate=0.06, lb=0.03, ub=0.09))
        assert g.maybe_activate() is True
        assert get_switch(SWITCH, False) is True
        state = json.loads((tmp_path / f"{SWITCH}.json").read_text(encoding="utf-8"))
        assert state["activated_at"]

    def test_4_same_date_dedup(self, tmp_path):
        g = _gate(tmp_path)
        assert g.record(_obs("2026-01-01", "B"))
        assert g.record(_obs("2026-01-01", "A"))
        ev = g.evaluate()
        assert ev["valid_days"] == 1
        assert ev["has_positive"] is True

    def test_5_small_n_rejected(self, tmp_path):
        g = _gate(tmp_path)
        assert g.record(_obs("2026-01-01", "A", n=499)) is False
        assert g.evaluate()["valid_days"] == 0

    def test_6_invalid_method_rejected(self, tmp_path):
        g = _gate(tmp_path)
        assert g.record(_obs("2026-01-01", method="error")) is False
        assert g.record(_obs("2026-01-02", method="insufficient_samples")) is False
        assert g.evaluate()["valid_days"] == 0

    def test_7_reconcile_activates(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True)
        set_switch(SWITCH, False)
        state = {"switch": SWITCH, "activated_at": "2026-10-14T18:00:00+08:00",
                 "min_days": 7, "min_n": 500, "observations": []}
        (tmp_path / f"{SWITCH}.json").write_text(json.dumps(state), encoding="utf-8")
        g = _gate(tmp_path)
        assert g.reconcile_from_disk() is True
        assert get_switch(SWITCH, False) is True

    def test_8_corrupt_state_failopen(self, tmp_path):
        from dreambuddy_evolution.agi_config import get_switch, set_switch
        set_switch(GATE_SWITCH, True)
        set_switch(SWITCH, False)
        (tmp_path / f"{SWITCH}.json").write_text("{not json", encoding="utf-8")
        g = _gate(tmp_path)
        assert g.maybe_activate() is False
        assert get_switch(SWITCH, False) is False

    def test_9_gate_switch_off_no_spawn(self, tmp_path, _no_real_spawn):
        from dreambuddy_evolution.agi_config import set_switch
        set_switch(GATE_SWITCH, False)
        set_switch(SWITCH, False)
        g = _gate(tmp_path)
        assert g.maybe_activate() is False
        assert _no_real_spawn["n"] == 0

    def test_10_no_spawn_when_today_has_obs(self, tmp_path, _no_real_spawn):
        from dreambuddy_evolution.agi_config import set_switch
        set_switch(GATE_SWITCH, True)
        set_switch(SWITCH, False)
        g = _gate(tmp_path)
        assert g.record(_obs(date.today().isoformat(), "B"))
        g.maybe_activate()
        assert _no_real_spawn["n"] == 0

    def test_10b_spawns_once_when_no_obs_today(self, tmp_path, _no_real_spawn):
        from dreambuddy_evolution.agi_config import set_switch
        set_switch(GATE_SWITCH, True)
        set_switch(SWITCH, False)
        g = _gate(tmp_path)
        g.maybe_activate()
        assert _no_real_spawn["n"] == 1
        g.maybe_activate()  # last_eval_attempt_date 已是今天 → 不再 spawn
        assert _no_real_spawn["n"] == 1

    def test_11_target_already_on_idempotent(self, tmp_path):
        from dreambuddy_evolution.agi_config import set_switch
        set_switch(GATE_SWITCH, True)
        set_switch(SWITCH, True)
        g = _gate(tmp_path)
        _seed_days(g, 7, "A")
        assert g.maybe_activate() is False

    def test_12_valid_observation_does_not_persist_method(self, tmp_path):
        """schema 不含 method；持久化时剥离（SPEC §4）."""
        g = _gate(tmp_path)
        assert g.record(_obs("2026-01-01", "B"))
        state = json.loads((tmp_path / f"{SWITCH}.json").read_text(encoding="utf-8"))
        assert "method" not in state["observations"][0]
