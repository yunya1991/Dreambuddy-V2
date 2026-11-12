"""factor_gate 单元测试：五态 verdict + §7.6.2 每条短路 + 记账/预注册/绕过留痕。"""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "registry"))

import factor_gate as fg  # noqa: E402


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """把 runtime 与预注册文件重定向到临时目录，避免污染仓库。"""
    monkeypatch.setattr(fg, "RUNTIME_DIR", tmp_path / "runtime")
    prereg = tmp_path / "factor_preregistration.json"
    prereg.write_text(
        json.dumps({"factors": {"F1": {"hypothesis": "情绪极值反向"}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(fg, "PREREG_PATH", prereg)
    return fg


def _seed(fg_mod, factor_id="F1", n_obs=300):
    return fg_mod.record_trial(factor_id, horizon=3, ic=0.05, t_stat=3.5, n_obs=n_obs)


def test_leakage_short_circuits_everything(gate):
    # 即使无 trials，前视污染也优先判 falsified
    res = gate.assert_gate("F1", 3, ic=0.1, t_stat=5.0, n_obs=500, leakage_ok=False)
    assert res["verdict"] == "falsified"
    assert res["reasons"] == ["lookahead_detected"]
    assert res["gate_version"] == "v1"


def test_no_trials_is_not_preregistered(gate):
    res = gate.assert_gate("F1", 3, ic=0.1, t_stat=5.0, n_obs=500, dsr=0.3, pbo=0.2)
    assert res["verdict"] == "insufficient_data"
    assert res["reasons"] == ["not_preregistered"]


def test_bypass_allows_missing_trials_and_logs(gate):
    res = gate.assert_gate(
        "F1", 3, ic=0.1, t_stat=5.0, n_obs=500, dsr=0.3, pbo=0.2, allow_without_trials=True
    )
    assert res["verdict"] == "candidate"
    log = gate.RUNTIME_DIR / "gate_bypass_log.jsonl"
    assert log.is_file()
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["factor_id"] == "F1"
    assert rows[0]["git_sha"]


def test_n_obs_below_250(gate):
    _seed(gate, n_obs=36)
    res = gate.assert_gate("F1", 3, ic=0.1, t_stat=5.0, n_obs=36, dsr=0.3, pbo=0.2)
    assert res["verdict"] == "insufficient_data"
    assert res["reasons"] == ["n_obs=36<250"]


def test_t_stat_threshold(gate):
    _seed(gate)
    res = gate.assert_gate("F1", 3, ic=0.1, t_stat=2.5, n_obs=300, dsr=0.3, pbo=0.2)
    assert res["verdict"] == "inconclusive"
    assert res["reasons"] == ["t=2.5<=3"]


def test_pbo_overfit(gate):
    _seed(gate)
    res = gate.assert_gate("F1", 3, ic=0.1, t_stat=4.0, n_obs=300, dsr=0.3, pbo=0.62)
    assert res["verdict"] == "falsified"
    assert res["reasons"] == ["pbo=0.62"]


def test_dsr_non_positive(gate):
    _seed(gate)
    res = gate.assert_gate("F1", 3, ic=0.1, t_stat=4.0, n_obs=300, dsr=-0.11, pbo=0.2)
    assert res["verdict"] == "falsified"
    assert res["reasons"] == ["dsr=-0.11"]


def test_missing_dsr_is_inconclusive(gate):
    _seed(gate)
    res = gate.assert_gate("F1", 3, ic=0.1, t_stat=4.0, n_obs=300, dsr=None, pbo=0.2)
    assert res["verdict"] == "inconclusive"
    assert res["reasons"] == ["dsr_missing"]


def test_pass_all_is_candidate(gate):
    _seed(gate)
    res = gate.assert_gate("F1", 3, ic=0.05, t_stat=3.5, n_obs=300, dsr=0.6, pbo=0.1)
    assert res["verdict"] == "candidate"
    assert res["reasons"] == ["pass_all"]
    assert res["trial_id"].startswith("T-")


def test_weak_ic_is_candidate_weak(gate):
    _seed(gate)
    res = gate.assert_gate("F1", 3, ic=0.01, t_stat=3.5, n_obs=300, dsr=0.6, pbo=0.1)
    assert res["verdict"] == "candidate_weak"
    assert res["reasons"][0] == "pass_all"


def test_verdict_always_in_enum(gate):
    _seed(gate)
    cases = [
        {"leakage_ok": False},
        {},
        {"n_obs": 10},
        {"t_stat": 0.1},
        {"pbo": 0.9},
        {"dsr": -1.0},
        {},
    ]
    for extra in cases:
        kwargs = {"ic": 0.1, "t_stat": 4.0, "n_obs": 300, "dsr": 0.5, "pbo": 0.2}
        kwargs.update(extra)
        assert gate.assert_gate("F1", 3, **kwargs)["verdict"] in gate.VERDICTS


def test_record_trial_appends_with_sequence(gate):
    first = _seed(gate)
    second = _seed(gate)
    assert first["trial_id"].endswith("-0001")
    assert second["trial_id"].endswith("-0002")
    assert (first["n_trials_so_far"], second["n_trials_so_far"]) == (1, 2)
    assert gate.count_trials() == 2
    assert gate.count_trials("F1") == 2
    assert gate.count_trials("F2") == 0
    row = json.loads(
        (gate.RUNTIME_DIR / "trials.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    for key in (
        "trial_id",
        "factor_id",
        "horizon",
        "params",
        "n_obs",
        "ic",
        "t_stat",
        "p_value",
        "script",
        "git_sha",
        "ran_at",
        "n_trials_so_far",
    ):
        assert key in row


def test_register_factor_requires_preregistration(gate):
    assert gate.register_factor("F1")["preregistered"] is True
    with pytest.raises(gate.FactorGateError):
        gate.register_factor("NOT_REGISTERED")
    with pytest.raises(gate.FactorGateError):
        gate.register_factor("F1", prereg_path=gate.RUNTIME_DIR / "missing.json")


def test_write_verdict_persists_gate_result(gate):
    _seed(gate)
    rec = gate.write_verdict(
        "F1", 3, ic=0.05, t_stat=3.5, n_obs=300, dsr=0.6, pbo=0.1, script="x.py"
    )
    assert rec["verdict"] == "candidate"
    path = gate.RUNTIME_DIR / "factor_verdicts.jsonl"
    saved = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert saved[-1]["verdict"] == "candidate"
    assert saved[-1]["gate_version"] == "v1"
    assert saved[-1]["trial_id"] == rec["trial_id"]
