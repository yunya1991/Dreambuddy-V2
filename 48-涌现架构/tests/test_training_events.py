"""TrainingEvent 落盘与 48→40 网关的最小契约测试（RED 先行）。

覆盖：
1. record_event：append-only、event_id 幂等、FAIL-OPEN
2. backfill_from_decisions：50 decisions → TrainingEvent 字段映射、二次回填 0 新增
3. nn_feedback_gateway：事件聚合、缺口统计、写盘/读回、ENABLE_40_VIA_48 默认关
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "metrics") not in sys.path:
    sys.path.insert(0, str(_ROOT / "metrics"))

import nn_feedback_gateway as gw  # noqa: E402
import training_events as te  # noqa: E402


def _decision(signal_id: str = "50-nn|20261110T000000Z", **over) -> dict:
    d = {
        "signal_id": signal_id,
        "source": "50-nn",
        "ts": "2026-11-10T00:00:00Z",
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "confidence": 0.7,
        "horizon": "hours",
        "position_pct": 25.0,
        "mode": "shadow",
        "shadow": True,
        "payload": {
            "dominance": {"overall_leader": "ev:11-bcrm-tactical:BTC-USDT-SWAP:D3:hours:trend"},
            "execution": {"outcome": "paper", "allowed": True, "reason": "paper_only"},
            "w4": {"total": 0.7, "direction": "long", "conflict_flag": False},
            "paths": [{"path_id": "p1", "source": "11-bcrm-tactical"}],
        },
    }
    d.update(over)
    return d


def test_record_event_is_append_only_and_idempotent(tmp_path):
    path = tmp_path / "training_events.jsonl"
    ev = te.normalize_event(
        {
            "decision_id": "d-1",
            "source": "50-nn",
            "symbol": "BTC-USDT-SWAP",
            "ts": "2026-11-10T00:00:00Z",
            "decision": {"action": "long", "tier": "shadow"},
        }
    )
    r1 = te.record_event(ev, path=path)
    r2 = te.record_event(ev, path=path)
    assert r1["status"] == "recorded"
    assert r2["status"] == "duplicate"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["version"] == te.SCHEMA_VERSION


def test_backfill_maps_50_decision_and_is_idempotent(tmp_path):
    dec = tmp_path / "decisions.jsonl"
    dec.write_text(
        json.dumps(_decision(), ensure_ascii=False)
        + "\n"
        + json.dumps(_decision(), ensure_ascii=False)
        + "\n"
        + "{broken}\n",
        encoding="utf-8",
    )
    out = tmp_path / "training_events.jsonl"
    r1 = te.backfill_from_decisions(dec, out_path=out)
    assert r1["appended"] == 1
    assert r1["duplicates"] == 1
    assert r1["invalid"] == 1
    ev = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert ev["decision_id"] == "50-nn|20261110T000000Z"
    assert ev["decision"]["action"] == "long"
    assert ev["decision"]["primary_contradiction"].startswith("ev:11-bcrm-tactical")
    assert ev["execution"]["outcome"] == "paper"
    assert ev["provenance"]["producer"] == "50-nn"
    r2 = te.backfill_from_decisions(dec, out_path=out)
    assert r2["appended"] == 0


def test_gateway_aggregates_and_roundtrips(tmp_path):
    events = [
        te.normalize_event(
            {
                "decision_id": f"d-{i}",
                "source": "50-nn",
                "symbol": "BTC-USDT-SWAP",
                "ts": f"2026-11-10T0{i}:00:00Z",
                "decision": {"action": "long", "primary_contradiction": "c1"},
                "execution": {"outcome": "paper"} if i % 2 else {},
            }
        )
        for i in range(3)
    ]
    fb = gw.build_feedback(events, factor_prior={"degraded": True, "n_factors": 0})
    assert fb["source_window"]["n_events"] == 3
    assert fb["contradiction_priors"][0]["key"] == "c1"
    assert fb["quality"]["n_incomplete"] == 2
    out = tmp_path / "40_feedback.json"
    gw.write_feedback(fb, out_path=out)
    back = gw.load_feedback(out_path=out)
    assert back["gateway_version"] == gw.GATEWAY_VERSION
    assert back["source_window"]["n_events"] == 3


def test_gate_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("ENABLE_40_VIA_48", raising=False)
    assert gw.gate_enabled() is False
    monkeypatch.setenv("ENABLE_40_VIA_48", "1")
    assert gw.gate_enabled() is True


def test_dual_read_tolerance():
    direct = {"cycle": "up", "confidence": 0.8}
    via48 = {"cycle": "up", "confidence": 0.75}
    res = gw.verify_dual_read(direct, via48, tolerance=0.1)
    assert res["consistent"] is True
    assert res["diffs"]["confidence"] == pytest.approx(0.05)
