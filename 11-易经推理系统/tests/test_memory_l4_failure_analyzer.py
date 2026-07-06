import json
from pathlib import Path


def test_analyze_failure_memory_builds_artifacts(tmp_path: Path):
    from scripts.memory_l4.failure_analyzer import analyze_failure_memory

    cases = [
        {
            "case_id": "TC_1",
            "inst_id": "BTC-USDT-SWAP",
            "environment_snapshot": {"regime": "RANGE_BOUND"},
            "execution": {"episode_refs": [{"path": "episodes/e1.json"}]},
        },
        {
            "case_id": "TC_2",
            "inst_id": "BTC-USDT-SWAP",
            "environment_snapshot": {"regime": "RANGE_BOUND"},
            "execution": {"episode_refs": [{"path": "episodes/e2.json"}]},
        },
        {
            "case_id": "TC_3",
            "inst_id": "ETH-USDT-SWAP",
            "environment_snapshot": {"regime": "BREAKOUT"},
            "execution": {"episode_refs": [{"path": "episodes/e3.json"}]},
        },
    ]
    episodes_by_case_id = {
        "TC_1": {"outcome": {"realized_pnl_pct": -1.2, "exit_reason": "stop_loss"}},
        "TC_2": {"outcome": {"realized_pnl_pct": -0.8, "exit_reason": "stop_loss"}},
        "TC_3": {"outcome": {"realized_pnl_pct": 1.1, "exit_reason": "take_profit"}},
    }

    out = analyze_failure_memory(
        snapshot_ts="2026-05-10T10:00:00+08:00",
        cases=cases,
        episodes_by_case_id=episodes_by_case_id,
        output_dir=tmp_path,
    )

    assert Path(out["risk_signals_path"]).exists()
    assert Path(out["distill_candidates_path"]).exists()
    assert Path(out["summary_path"]).exists()

    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    assert summary["failed_cases"] == 2
    assert summary["risk_signals_count"] == 1
    assert summary["reason_counts"]["stop_loss"] == 2

    distills = json.loads(Path(out["distill_candidates_path"]).read_text(encoding="utf-8"))
    assert len(distills) == 1
    assert distills[0]["kind"] == "risk_signal"
    assert distills[0]["supporting_case_ids"] == ["TC_1", "TC_2"]


def test_analyze_failure_memory_prefers_realized_over_unrealized(tmp_path: Path):
    from scripts.memory_l4.failure_analyzer import analyze_failure_memory

    cases = [
        {
            "case_id": "TC_1",
            "inst_id": "BTC-USDT-SWAP",
            "environment_snapshot": {"regime": "RANGE_BOUND"},
            "execution": {"episode_refs": [{"path": "episodes/e1.json"}]},
        }
    ]
    episodes_by_case_id = {
        "TC_1": {
            "outcome": {
                "realized_pnl_pct": 0.3,
                "unrealized_pnl_pct": -1.0,
                "exit_reason": "late_exit",
            }
        }
    }

    out = analyze_failure_memory(
        snapshot_ts="2026-05-10T11:00:00+08:00",
        cases=cases,
        episodes_by_case_id=episodes_by_case_id,
        output_dir=tmp_path,
    )
    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    assert summary["failed_cases"] == 0
    assert summary["risk_signals_count"] == 0
