import json
import random
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _case(i: int, *, ts: str, pnl: float, x: float, y: float, regime: str = "RANGE_BOUND"):
    return {
        "case_id": f"TC_{i:06d}",
        "ts_start": ts,
        "environment_snapshot": {"regime": regime},
        "quadrant": {"x": x, "y": y},
        "decision_outcome": {"pnl_pct": pnl, "drawdown": abs(pnl) * 0.3},
    }


def _cases(n: int, *, seed: int, ts_base: str = "2026-05-13T00:00:00+08:00"):
    rnd = random.Random(seed)
    base = ts_base.replace("00:00:00", "00:00:00")
    out = []
    for i in range(n):
        pnl = rnd.uniform(-2.0, 2.0)
        x = rnd.uniform(-1.0, 1.0)
        y = rnd.uniform(0.0, 1.0)
        mm = i % 60
        ts = base.replace("00:00:00", f"00:{mm:02d}:00")
        out.append(_case(i, ts=ts, pnl=pnl, x=x, y=y, regime="RANGE_BOUND" if i % 2 == 0 else "TRENDING"))
    return out


def test_stress_multi_round_run_qmm_with_gate(tmp_path, monkeypatch):
    from scripts.memory_l4.qmm import paths
    from scripts.memory_l4.qmm import engine
    from scripts.memory_l4.qmm import gate
    from scripts.memory_l4.qmm.engine import run_qmm_with_gate

    monkeypatch.setattr(paths, "qmm_dir", lambda: tmp_path)
    monkeypatch.setattr(engine, "qmm_dir", lambda: tmp_path)
    monkeypatch.setattr(gate, "qmm_dir", lambda: tmp_path)

    for seed in range(10):
        cases = _cases(60, seed=seed)
        out, gate = run_qmm_with_gate(cases, distills=[], config=None, gate_config={"n_folds": 3, "min_train": 10, "min_test": 5})

        assert out.data_version
        assert re.match(r"^dv-\d{8}-\d{3}$", out.data_version)

        index_path = tmp_path / "signals_index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert index["gate_status"] in {"PASSED", "FAILED"}
        assert index["gate_results"]["passed"] in {True, False}

        snapshot_path = Path(index["output_file"])
        assert snapshot_path.exists()
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert snapshot["gate_status"] == index["gate_status"]
        assert snapshot["gate_results"]["passed"] == index["gate_results"]["passed"]


def test_stress_large_batch_run_qmm(tmp_path, monkeypatch):
    from scripts.memory_l4.qmm import paths
    from scripts.memory_l4.qmm import engine
    from scripts.memory_l4.qmm.engine import run_qmm

    monkeypatch.setattr(paths, "qmm_dir", lambda: tmp_path)
    monkeypatch.setattr(engine, "qmm_dir", lambda: tmp_path)
    cases = _cases(1200, seed=123)
    out = run_qmm(cases, distills=[], config=None)

    assert re.match(r"^dv-\d{8}-\d{3}$", out.data_version)
    index_path = tmp_path / "signals_index.json"
    assert index_path.exists()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    snapshot_path = Path(index["output_file"])
    assert snapshot_path.exists()


def test_scenario_out_of_order_timestamps(tmp_path, monkeypatch):
    from scripts.memory_l4.qmm import paths
    from scripts.memory_l4.qmm import engine
    from scripts.memory_l4.qmm.engine import run_qmm

    monkeypatch.setattr(paths, "qmm_dir", lambda: tmp_path)
    monkeypatch.setattr(engine, "qmm_dir", lambda: tmp_path)
    cases = _cases(40, seed=9)
    random.Random(9).shuffle(cases)
    out = run_qmm(cases, distills=[], config=None)
    assert len(out.evidence_refs) <= 10


def test_scenario_bad_numeric_input_raises(tmp_path, monkeypatch):
    from scripts.memory_l4.qmm import paths
    from scripts.memory_l4.qmm import engine
    from scripts.memory_l4.qmm.engine import run_qmm

    monkeypatch.setattr(paths, "qmm_dir", lambda: tmp_path)
    monkeypatch.setattr(engine, "qmm_dir", lambda: tmp_path)
    cases = _cases(5, seed=1)
    cases[0]["quadrant"]["x"] = "not-a-number"

    try:
        run_qmm(cases, distills=[], config=None)
        assert False
    except ValueError:
        assert True
