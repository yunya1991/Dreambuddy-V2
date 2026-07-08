import json
import re
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_gate_result_to_dict_handles_none():
    from scripts.memory_l4.qmm.gate import GateResult

    gr = GateResult(
        backtest=None,
        overfitting=None,
        drift=None,
        passed=False,
        reason_codes=["INSUFFICIENT_DATA_FOR_GATE"],
    )
    data = gr.to_dict()
    assert data["passed"] is False
    assert data["reason_codes"] == ["INSUFFICIENT_DATA_FOR_GATE"]
    assert data["backtest"] is None
    assert data["overfitting"] is None
    assert data["drift"] is None


def test_update_gate_status_updates_snapshot(tmp_path, monkeypatch):
    from scripts.memory_l4.qmm.engine import _update_gate_status
    from scripts.memory_l4.qmm.gate import GateResult

    out_dir = tmp_path
    snapshot_path = out_dir / "qmm_snapshot_x.json"
    snapshot_path.write_text(json.dumps({"gate_status": "OFFLINE"}, ensure_ascii=False), encoding="utf-8")

    index_path = out_dir / "signals_index.json"
    index_path.write_text(
        json.dumps(
            {
                "gate_status": "OFFLINE",
                "output_file": str(snapshot_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    gr = GateResult(
        backtest=None,
        overfitting=None,
        drift=None,
        passed=False,
        reason_codes=["INSUFFICIENT_DATA_FOR_GATE"],
    )
    _update_gate_status(out_dir, gr)

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["gate_status"] == "FAILED"
    assert index["gate_results"]["passed"] is False

    snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snap["gate_status"] == "FAILED"
    assert snap["gate_results"]["passed"] is False


def test_data_version_format_and_increment(tmp_path, monkeypatch):
    from scripts.memory_l4.qmm import data_prep
    from scripts.memory_l4.qmm import paths

    monkeypatch.setattr(paths, "qmm_dir", lambda: tmp_path)

    dv1 = data_prep._compute_data_version([{"ts_start": "2026-05-13T00:00:00+08:00"}])
    dv2 = data_prep._compute_data_version([{"ts_start": "2026-05-13T00:00:00+08:00"}])

    assert re.match(r"^dv-\d{8}-\d{3}$", dv1)
    assert re.match(r"^dv-\d{8}-\d{3}$", dv2)
    assert dv1 != dv2
    assert (tmp_path / "data_version_state.json").exists()
