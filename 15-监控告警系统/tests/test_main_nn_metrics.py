"""main_nn_metrics 语义快照单测（15 TD §14，取自 decisions payload）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_EXPORTER_DIR = Path(__file__).resolve().parents[1] / "exporter"
sys.path.insert(0, str(_EXPORTER_DIR))

from business_metrics_exporter import Collector  # noqa: E402

_CFG = Path(__file__).resolve().parents[1] / "config" / "monitoring.yaml"
_DOMAINS = Path(__file__).resolve().parents[1] / "config" / "domains.yaml"


def _decision(symbol: str, *, path_count: int, conflict: bool, locked: bool, freeze: bool) -> dict:
    paths = [
        {
            "path_id": f"ev:x:{symbol}:D3:hours:trend",
            "source": "11-bcrm-tactical",
            "direction": "long",
            "confidence": 0.9,
            "dimension": "D3",
        },
        {
            "path_id": f"ev:y:{symbol}:D1:days:trend",
            "source": "40-cycle",
            "direction": "short",
            "confidence": 0.05,
            "dimension": "D1",
        },
    ]
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "mode": "live",
        "confidence": 0.62,
        "payload": {
            "w4": {"conflict_flag": conflict, "total": 0.62, "direction": "long"},
            "dominance": {"overall_leader": "ev:y", "overall_fallback_argmax": True},
            "trigger_flap": {"locked": locked, "switches_in_window": 2},
            "constraint_freeze": freeze,
            "path_count": path_count,
            "paths": paths,
        },
    }


def test_semantic_snapshot_from_decisions(tmp_path: Path) -> None:
    runtime = tmp_path / "50-NN主矛盾评估器" / "runtime"
    runtime.mkdir(parents=True)
    rows = [
        _decision("BTC", path_count=4, conflict=True, locked=False, freeze=False),
        _decision("ETH", path_count=2, conflict=False, locked=True, freeze=True),
    ]
    (runtime / "decisions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    metrics = Collector(tmp_path, _CFG, _DOMAINS).main_nn_metrics()
    text = "\n".join(metrics)

    assert "dreambuddy_main_nn_decision_samples 2" in text
    assert "dreambuddy_main_nn_path_count 4" in text
    assert "dreambuddy_main_nn_contradiction_present 1" in text
    assert "dreambuddy_main_nn_dominance_fallback_ratio 1.0" in text
    assert "dreambuddy_main_nn_trigger_flap_locked_ratio 0.5" in text
    assert "dreambuddy_main_nn_constraint_freeze_ratio 0.5" in text
    assert "dreambuddy_main_nn_dimension_neutral_ratio 0.5" in text
    assert "dreambuddy_main_nn_evidence_sources_ok 2" in text


def test_p2_join_and_attach_ratios(tmp_path: Path) -> None:
    runtime = tmp_path / "50-NN主矛盾评估器" / "runtime"
    runtime.mkdir(parents=True)
    rows = [
        _decision(sym, path_count=1, conflict=False, locked=False, freeze=False)
        for sym in ("A", "B", "C", "D")
    ]
    (runtime / "decisions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    # join 源是 outbox（decisions.jsonl 不含 decision_id）
    (runtime / "live").mkdir(parents=True)
    outbox = [{"mode": "live", "decision_id": did} for did in ("D1", "D2", "D4")]
    (runtime / "live" / "outbox.jsonl").write_text(
        "\n".join(json.dumps(r) for r in outbox) + "\n", encoding="utf-8"
    )

    audit = tmp_path / "22-执行引擎中心" / "audit"
    audit.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat()
    fills = [
        {
            "ts": now,
            "decision_id": "D1",
            "order_placed": True,
            "request": {"sl_pct": 1.5, "tp_pct": 3.0},
        },
        {
            "ts": now,
            "decision_id": "D2",
            "order_placed": True,
            "request": {"sl_pct": 0, "tp_pct": 0},
        },
        {
            "ts": now,
            "decision_id": "D3",
            "order_placed": True,
            "request": {"sl_pct": 1.5, "tp_pct": 3.0},
        },
    ]
    (audit / "x1_live_fills.jsonl").write_text(
        "\n".join(json.dumps(r) for r in fills) + "\n", encoding="utf-8"
    )

    text = "\n".join(Collector(tmp_path, _CFG, _DOMAINS).main_nn_metrics())

    assert "dreambuddy_main_nn_decision_fill_join_ratio 0.6667" in text
    assert "dreambuddy_main_nn_fill_sltp_attach_ratio 0.6667" in text
