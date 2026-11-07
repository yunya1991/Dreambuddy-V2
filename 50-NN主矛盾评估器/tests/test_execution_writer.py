"""R0-08: execution_writer（执行权 + Mandate + kill-switch + 审计）。"""

from __future__ import annotations

import json

from adapters.execution_writer import (
    is_kill_switch_on,
    load_rights,
    resolve_outcome,
    validate_execution,
)


def test_load_rights_has_fifty_domain(tmp_path):
    p = tmp_path / "rights.json"
    p.write_text(
        json.dumps(
            {
                "fifty_nn_domain": {
                    "default_outcome": "paper",
                    "mandate_required_for_live": True,
                }
            }
        ),
        encoding="utf-8",
    )
    rights = load_rights(str(p))
    assert rights["fifty_nn_domain"]["default_outcome"] == "paper"


def test_default_outcome_is_paper(tmp_path):
    p = tmp_path / "rights.json"
    p.write_text(json.dumps({"fifty_nn_domain": {"default_outcome": "paper"}}), encoding="utf-8")
    assert resolve_outcome("UNKNOWN-SWAP", json.loads(p.read_text())) == "paper"


def test_symbol_override(tmp_path):
    rights = {
        "fifty_nn_domain": {"default_outcome": "paper"},
        "symbols": {"BTC-USDT-SWAP": {"outcome": "paper"}},
    }
    assert resolve_outcome("BTC-USDT-SWAP", rights) == "paper"


def test_kill_switch_blocks(monkeypatch, tmp_path):
    monkeypatch.setenv("50_KILL_SWITCH", "1")
    rights = {"fifty_nn_domain": {"default_outcome": "paper"}}
    decision = {"signal_id": "d1", "symbol": "BTC-USDT-SWAP"}
    result = validate_execution(decision, rights)
    assert result["outcome"] == "disabled"
    assert result["allowed"] is False


def test_no_mandate_downgrades_live_to_paper(tmp_path, monkeypatch):
    monkeypatch.delenv("50_KILL_SWITCH", raising=False)
    rights = {
        "fifty_nn_domain": {"default_outcome": "live:50-bypass", "mandate_required_for_live": True}
    }
    decision = {"signal_id": "d2", "symbol": "BTC-USDT-SWAP"}
    result = validate_execution(decision, rights, mandate=None)
    assert result["outcome"] == "paper"
    assert result["decision"]["execution_rights"] == "paper"


def test_mandate_allows_live(monkeypatch):
    monkeypatch.delenv("50_KILL_SWITCH", raising=False)
    rights = {
        "fifty_nn_domain": {"default_outcome": "live:50-bypass", "mandate_required_for_live": True}
    }
    decision = {"signal_id": "d3", "symbol": "BTC-USDT-SWAP"}
    result = validate_execution(decision, rights, mandate="m-50-001")
    assert result["outcome"] == "live:50-bypass"
    assert result["decision"]["mandate_id"] == "m-50-001"


def test_kill_switch_helper(monkeypatch):
    monkeypatch.setenv("50_KILL_SWITCH", "1")
    assert is_kill_switch_on() is True
    monkeypatch.setenv("50_KILL_SWITCH", "0")
    assert is_kill_switch_on() is False
