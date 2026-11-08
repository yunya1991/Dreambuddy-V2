"""l1.trading.mcp 十工具契约测试（无真实交易/无外部状态）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells.l1_trading import server  # noqa: E402


def _payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def state_files(tmp_path, monkeypatch):
    signal = {
        "signal_id": "sig-1",
        "source": "23-evolution",
        "ts": "2026-11-08T00:00:00Z",
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "confidence": 0.72,
        "horizon": "hours",
        "risk_exposure_hint": 0.2,
        "expires_at": "2026-11-08T01:00:00Z",
        "mode": "live",
        "shadow": False,
        "payload": {
            "action": "long",
            "position_tier": "standard",
            "position_mult": 1.0,
            "regime": "expansion",
            "primary_contradiction": {
                "dimension": "valuation",
                "direction": "long",
                "strength": 0.8,
                "confidence": 0.7,
                "dimension_force_mod": 0.3,
                "causal_ate": 0.1,
            },
            "contradiction_shift": {"shifted_from": "a", "shifted_to": "b"},
            "cross_validation": {"consistent": True, "confidence_mult": 1.1},
            "elastic_result": {"position_mult": 1.0},
            "path": {
                "optimal_path": "P1",
                "hjb_value": 1.2,
                "path_score": 0.9,
                "resistance_vector": [0.1, 0.2],
            },
        },
    }
    bus = {
        "generated_at": "2026-11-08T00:00:00Z",
        "sources": ["bdsm"],
        "signal_count": 2,
        "signals": [
            {"symbol": "BTC", "direction": "neutral"},
            {"symbol": "ETH", "direction": "long"},
        ],
    }
    cycle = {
        "generated_at": "2026-11-08T00:00:00Z",
        "real_cycle": {"state": "plateau", "confidence": "high"},
        "technical_anchor": {"assets": {"BTC/USDT": {"above": True}}},
    }
    strategy = {
        "generated_at": "2026-11-08T00:00:00Z",
        "inputs": {"quadrant": "overheat"},
        "strategy_suggestion": {"stance": "防御性进攻", "position_band_pct": [30, 60]},
    }
    strategic = {
        "signal_id": "sig-43",
        "source": "strategic_extension",
        "strategic_tier": "attack",
    }
    training = {
        "status": "ok",
        "epochs": 100,
        "n_windows": 3000,
        "final_loss": 0.01,
        "best_val_loss": 0.009,
    }

    paths = {
        "SIGNAL_STATE_PATH": tmp_path / "23_signal_state.json",
        "SIGNAL_FALLBACK_PATH": tmp_path / "event_driven_state.json",
        "BUS_STATE_PATH": tmp_path / "bus_state.json",
        "CONSTRAINT_STATE_PATH": tmp_path / "macro_constraint.json",
        "CYCLE_STATE_PATH": tmp_path / "cycle_state.json",
        "STRATEGY_MAPPING_PATH": tmp_path / "strategy_mapping.json",
        "STRATEGIC_EXTENSION_PATH": tmp_path / "strategic_extension.json",
        "TRAINING_REPORT_PATH": tmp_path / "training_report.json",
        "PAPER_SAMPLES_PATH": tmp_path / "samples.jsonl",
    }
    _write(paths["SIGNAL_STATE_PATH"], signal)
    _write(paths["BUS_STATE_PATH"], bus)
    _write(paths["CYCLE_STATE_PATH"], cycle)
    _write(paths["STRATEGY_MAPPING_PATH"], strategy)
    _write(paths["STRATEGIC_EXTENSION_PATH"], strategic)
    _write(paths["TRAINING_REPORT_PATH"], training)
    paths["PAPER_SAMPLES_PATH"].write_text(
        '{"kind":"order_filled"}\n{"kind":"risk_rejected"}\n',
        encoding="utf-8",
    )
    for name, value in paths.items():
        monkeypatch.setattr(server, name, value)
    return paths


def test_tools_list_has_ten_tools():
    resp = server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in resp["result"]["tools"]}
    assert names == {
        "get_signal_state",
        "get_bus_state",
        "get_constraint_state",
        "get_cycle_state",
        "get_strategic_extension",
        "get_decision_diagnostics",
        "get_training_status",
        "get_positions",
        "get_balance",
        "forward_signal",
    }


def test_initialize_and_ping():
    init = server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == "l1.trading.mcp"
    ping = server._handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping["result"] == {}


def test_get_signal_state(state_files):
    payload = json.loads(server.get_signal_state({}))
    assert payload["ok"] is True
    assert payload["data"]["signal"]["source"] == "23-evolution"
    assert payload["data"]["fallback"] is False


def test_get_signal_state_falls_back_to_11(state_files):
    state_files["SIGNAL_STATE_PATH"].unlink()
    _write(
        state_files["SIGNAL_FALLBACK_PATH"],
        {
            "updated_at": "2026-11-08T00:00:00Z",
            "symbol": "BTC",
            "mode": "shadow",
        },
    )
    payload = json.loads(server.get_signal_state({}))
    assert payload["data"]["fallback"] is True
    assert payload["degraded"] is True


def test_get_bus_state_filters_symbol(state_files):
    payload = json.loads(server.get_bus_state({"symbol": "ETH", "limit": 10}))
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["signals"][0]["symbol"] == "ETH"


def test_get_constraint_state_missing_returns_components(state_files):
    payload = json.loads(server.get_constraint_state({}))
    assert payload["ok"] is False
    assert payload["data"]["available"] is False
    assert payload["data"]["components"]["cycle"]["available"] is True
    assert payload["data"]["components"]["strategic_extension"]["source"] == "strategic_extension"


def test_get_cycle_and_strategic_extension(state_files):
    cycle = json.loads(server.get_cycle_state({}))
    assert cycle["data"]["cycle"]["real_cycle"]["state"] == "plateau"
    strategic = json.loads(server.get_strategic_extension({}))
    assert strategic["data"]["strategic_extension"]["strategic_tier"] == "attack"


def test_get_decision_diagnostics_redacts_raw_fields(state_files):
    payload = json.loads(server.get_decision_diagnostics({}))
    diagnostics = payload["data"]["diagnostics"]
    assert diagnostics["primary_contradiction"]["dimension"] == "valuation"
    assert "dimension_force_mod" not in diagnostics["primary_contradiction"]
    assert "causal_ate" not in diagnostics["primary_contradiction"]
    assert "resistance_vector" not in diagnostics["path"]


def test_get_training_status(state_files):
    payload = json.loads(server.get_training_status({}))
    assert payload["ok"] is True
    assert payload["data"]["training"]["epochs"] == 100
    assert payload["data"]["paper_sample_count"] == 2


def test_get_positions_and_balance_proxy(state_files, monkeypatch):
    monkeypatch.setattr(
        server,
        "_call_l0",
        lambda tool, args: ({"count": 1, "positions": []}, False, "", ""),
    )
    positions = json.loads(server.get_positions({"symbol": "BTC-USDT-SWAP"}))
    balance = json.loads(server.get_balance({}))
    assert positions["data"]["execution"]["count"] == 1
    assert positions["meta"]["proxied_from"] == "l0.trade-exec.mcp"
    assert balance["ok"] is True


def test_forward_signal_happy_path(state_files, monkeypatch):
    calls = []

    def fake_call_l0(tool, args):
        calls.append((tool, args))
        return {"accepted": True}, False, "", ""

    monkeypatch.setattr(server, "_call_l0", fake_call_l0)
    payload = json.loads(server.forward_signal({}))
    assert payload["ok"] is True
    assert payload["data"]["signal_id"] == "sig-1"
    assert calls[0][0] == "ingest_signal"
    assert calls[0][1]["signal"]["source"] == "23-evolution"


@pytest.mark.parametrize(
    "patch",
    [
        {"source": "42"},
        {"mode": "paper"},
        {"shadow": True},
    ],
)
def test_forward_signal_rejects_invalid(state_files, monkeypatch, patch):
    from mcp_shells.l1_trading import server as srv

    signal = json.loads(state_files["SIGNAL_STATE_PATH"].read_text(encoding="utf-8"))
    signal.update(patch)
    payload = json.loads(srv.forward_signal({"signal": signal}))
    assert payload["ok"] is False
    assert payload["error_code"] == "conflict"
