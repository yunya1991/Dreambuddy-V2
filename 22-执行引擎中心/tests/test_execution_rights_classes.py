"""执行权类级授权 + 竞争单出口（2026-11-22 扩池）。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from trade_execution_gateway import TradeExecutionGateway  # noqa: E402


@pytest.fixture(autouse=True)
def _enable_rights(monkeypatch):
    monkeypatch.setenv("EXECUTION_RIGHTS_ENFORCE", "1")


class _Okx:
    def __init__(self, positions=None, exc: Exception | None = None):
        self.positions = positions or []
        self.exc = exc

    def get_positions(self, inst_id=None):
        if self.exc is not None:
            raise self.exc
        rows = list(self.positions)
        if inst_id:
            rows = [r for r in rows if not r.get("inst_id") or r.get("inst_id") == inst_id]
        return {"ok": True, "positions": rows}


def _sig(symbol: str, source: str = "23-evolution", action: str = "open"):
    return SimpleNamespace(symbol=symbol, source=source, action=action, pos_side="long")


class _NoLedger:
    """账本无归属信息（走交易所兜底）。"""

    def active_domain_holders(self, inst_id, pos_side=None):
        return []


def _gw(okx=None, ledger=None):
    gw = TradeExecutionGateway(
        okx_client=okx or _Okx(), audit_path=Path("/tmp/gw-rights-test.jsonl")
    )
    gw._ledger = ledger if ledger is not None else _NoLedger()
    gw._ledger_ready = True  # 阻止懒加载打开生产库
    return gw


def _rules():
    return {
        "defaults": {"outcome": "paper"},
        "classes": {"crypto": {"outcome": "live:23-gateway", "source": "23-evolution"}},
        "symbols": {
            "AVAX-USDT-SWAP": {
                "outcome": "live:50-bypass",
                "asset_class": "crypto",
                "shared_outcomes": {"23-evolution": "live:23-gateway"},
            },
            "BTC-USDT-SWAP": {"outcome": "live:23-gateway", "asset_class": "crypto"},
        },
    }


def test_shared_outcomes_allows_both_23_and_50(monkeypatch):
    gw = _gw()
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert gw._execution_rights_denied(_sig("AVAX-USDT-SWAP", "23-evolution")) == ""
    assert gw._execution_rights_denied(_sig("AVAX-USDT-SWAP", "50-nn")) == ""


def test_shared_outcomes_still_blocks_other_sources(monkeypatch):
    gw = _gw()
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    deny = gw._execution_rights_denied(_sig("AVAX-USDT-SWAP", "11-yijing"))
    assert "single_outlet_denied" in deny


def test_class_rules_apply_when_symbol_not_listed(monkeypatch):
    gw = _gw()
    rules = _rules()
    rules["symbols"] = {}
    monkeypatch.setattr(gw, "_load_execution_rights", lambda: rules)
    assert gw._execution_rights_denied(_sig("AVAX-USDT-SWAP", "23-evolution")) == ""
    assert "single_outlet_denied" in gw._execution_rights_denied(_sig("AVAX-USDT-SWAP", "50-nn"))


def test_symbol_entry_overrides_class(monkeypatch):
    gw = _gw()
    rules = _rules()
    rules["classes"] = {"crypto": {"outcome": "live:50-bypass"}}
    monkeypatch.setattr(gw, "_load_execution_rights", lambda: rules)
    assert gw._execution_rights_denied(_sig("BTC-USDT-SWAP", "23-evolution")) == ""
    assert "single_outlet_denied" in gw._execution_rights_denied(_sig("BTC-USDT-SWAP", "50-nn"))


def test_unknown_class_falls_back_to_paper(monkeypatch):
    gw = _gw()
    rules = _rules()
    monkeypatch.setattr(gw, "_load_execution_rights", lambda: rules)
    # 未登记的 ZZZ 无类可归 → defaults.paper，不误放行 live
    assert gw._execution_rights_denied(_sig("ZZZ-USDT-SWAP", "23-evolution")) == ""


def test_close_always_allowed(monkeypatch):
    gw = _gw()
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    rules = _rules()
    rules["symbols"] = {"BTC-USDT-SWAP": {"outcome": "disabled"}}
    monkeypatch.setattr(gw, "_load_execution_rights", lambda: rules)
    assert gw._execution_rights_denied(_sig("BTC-USDT-SWAP", "23-evolution", "close")) == ""


def test_shared_outlet_blocks_when_position_exists(monkeypatch):
    gw = _gw(_Okx([{"inst_id": "AVAX-USDT-SWAP", "pos": 2.0}]))
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert "symbol_already_open" in gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP"))


def test_shared_outlet_allows_when_flat(monkeypatch):
    gw = _gw(_Okx([]))
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP")) == ""


def test_shared_outlet_fail_open_on_query_error(monkeypatch):
    gw = _gw(_Okx(exc=RuntimeError("network")))
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP")) == ""


class _StubLedger:
    def __init__(self, owners=None, exc: Exception | None = None, raw=None):
        self.owners = owners or []
        self.exc = exc
        self.raw = raw or []

    def active_domain_holders(self, inst_id, pos_side=None):
        if self.exc:
            raise self.exc
        return list(self.owners)

    def list_positions(self):
        return list(self.raw)


def test_shared_outlet_blocks_unknown_domain_ledger_row(monkeypatch):
    """线上 10:20 事故：CVX 有仓但无域归属（网关外开仓），仍被放行叠加。"""
    gw = _gw(_Okx([]), _StubLedger([], raw=[{"inst_id": "AVAX-USDT-SWAP", "qty": 99.0}]))
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert "unknown_domain" in gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP"))


def test_shared_outlet_exchange_rows_filtered_by_symbol(monkeypatch):
    gw = _gw(_Okx([{"inst_id": "ETH-USDT-SWAP", "pos": 5.0}]), _StubLedger([]))
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP")) == ""


def test_shared_outlet_blocks_other_domain_holder(monkeypatch):
    gw = _gw(_Okx([]), _StubLedger(["50"]))
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    deny = gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP", "23-evolution"))
    assert "symbol_held_by_other_domain" in deny and "50" in deny


def test_shared_outlet_allows_same_domain_add_on(monkeypatch):
    gw = _gw(_Okx([{"inst_id": "AVAX-USDT-SWAP", "pos": 2.0}]), _StubLedger(["23"]))
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP", "23-evolution")) == ""


def test_shared_outlet_ledger_error_falls_back_to_exchange(monkeypatch):
    gw = _gw(_Okx([{"inst_id": "AVAX-USDT-SWAP", "pos": 1.0}]), _StubLedger(exc=RuntimeError("db")))
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert "symbol_already_open" in gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP"))


def test_shared_outlet_real_ledger_domain_ownership(tmp_path, monkeypatch):
    """真实账本：50 已持 → 23 拒绝；23 已持 → 23 放行（加仓）。"""
    sys.path.insert(0, str(HERE))
    from position_ledger import PositionLedger  # noqa: E402

    led = PositionLedger(tmp_path / "ledger.db")
    led.record_fill("AVAX-USDT-SWAP", "long", "open", 2.0, 10.0, domain="50", source="50-nn")

    gw = _gw(_Okx([]), led)
    monkeypatch.setattr(gw, "_load_execution_rights", _rules)
    assert "symbol_held_by_other_domain" in gw._shared_outlet_blocked(_sig("AVAX-USDT-SWAP"))

    led.record_fill("BTC-USDT-SWAP", "long", "open", 1.0, 100.0, domain="23", source="23-evolution")
    assert gw._shared_outlet_blocked(_sig("BTC-USDT-SWAP")) == ""


def test_real_registry_expansion():
    gw = _gw()
    assert gw._execution_rights_denied(_sig("AVAX-USDT-SWAP", "23-evolution")) == ""
    assert gw._execution_rights_denied(_sig("AVAX-USDT-SWAP", "50-nn")) == ""
    assert gw._execution_rights_denied(_sig("TLT-USDT-SWAP", "23-evolution")) == ""
    assert "single_outlet_denied" in gw._execution_rights_denied(
        _sig("AVAX-USDT-SWAP", "11-yijing")
    )
