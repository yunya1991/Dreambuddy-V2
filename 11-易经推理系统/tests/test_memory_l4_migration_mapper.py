import json
from pathlib import Path


def test_build_cross_market_migration_outputs_mapping_and_summary(tmp_path: Path):
    from scripts.memory_l4.migration_mapper import build_cross_market_migration

    source_items = [
        {
            "case_id": "TC_1",
            "inst_id": "BTC-USDT-SWAP",
            "environment_snapshot": {"regime": "RANGE_BOUND"},
        },
        {
            "case_id": "TC_2",
            "inst_id": "BTC-USDT-SWAP",
            "environment_snapshot": {"regime": "RANGE_BOUND"},
        },
        {
            "case_id": "TC_3",
            "inst_id": "ETH-USDT-SWAP",
            "environment_snapshot": {"regime": "BREAKOUT"},
        },
    ]
    episodes_by_case_id = {
        "TC_1": {"outcome": {"realized_pnl_pct": -1.2, "exit_reason": "stop_loss"}},
        "TC_2": {"outcome": {"realized_pnl_pct": -0.8, "exit_reason": "stop_loss"}},
        "TC_3": {"outcome": {"realized_pnl_pct": 0.5, "exit_reason": "take_profit"}},
    }

    out = build_cross_market_migration(
        snapshot_ts="2026-05-10T13:00:00+08:00",
        source_market="BTC",
        target_market="ETH",
        source_items=source_items,
        episodes_by_case_id=episodes_by_case_id,
        output_dir=tmp_path,
    )

    assert Path(out["mapping_table_path"]).exists()
    assert Path(out["artifact_path"]).exists()
    assert Path(out["summary_path"]).exists()

    mapping = json.loads(Path(out["mapping_table_path"]).read_text(encoding="utf-8"))
    assert mapping["source_market"] == "BTC"
    assert mapping["target_market"] == "ETH"
    assert len(mapping["mappings"]) == 1
    first = mapping["mappings"][0]
    assert first["source"]["regime"] == "RANGE_BOUND"
    assert first["source"]["risk_reason"] == "stop_loss"
    assert 0.0 <= first["migration_confidence"] <= 1.0
    assert first["support_count"] == 2

    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    assert summary["total_items"] == 3
    assert summary["eligible_items"] == 2
    assert summary["mappings_count"] == 1


def test_memory_engine_analyze_cross_market_migration(tmp_path: Path):
    from workflows.memory.memory_engine.engine import MemoryEngine

    cases = [
        {
            "case_id": "TC_1",
            "inst_id": "BTC-USDT-SWAP",
            "environment_snapshot": {"regime": "RANGE_BOUND"},
        }
    ]
    episodes_by_case_id = {
        "TC_1": {"outcome": {"realized_pnl_pct": -0.9, "exit_reason": "stop_loss"}}
    }

    memory = MemoryEngine(cases=cases)
    out = memory.analyze_cross_market_migration(
        snapshot_ts="2026-05-10T13:10:00+08:00",
        source_market="BTC",
        target_market="ETH",
        episodes_by_case_id=episodes_by_case_id,
        output_dir=tmp_path,
    )

    assert out["summary"]["mappings_count"] == 1
