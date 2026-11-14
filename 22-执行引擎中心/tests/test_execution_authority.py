"""Phase 2：执行权落 22 验收测试。

覆盖三件事：
1. 执行权威不可用时，写操作 fail-closed（拒绝而非绕行 raw）。
2. 23 自进化域写操作经 22 TradeExecutionGateway 执行，不再直连 raw。
3. 23 域经网关下单仍保留 evo23 标签与 [23域] reason。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from executors.domain_clients import DomainTaggedOkxClient
from trade_execution_gateway import FailClosedOkxClient, TradeExecutionGateway

HERE = Path(__file__).resolve().parent


class _RawClient:
    def __init__(self):
        self.calls = []
        self.cfg = {"default_inst_id": "BTC-USDT-SWAP", "default_usdt_amount": 100.0}

    def place_order(self, **kwargs):
        self.calls.append(("place_order", kwargs))
        return {"ok": True, "order_id": "raw-1"}

    def place_stop_loss_take_profit(self, **kwargs):
        self.calls.append(("place_stop_loss_take_profit", kwargs))
        return {"ok": True, "algo_id": "raw-sltp"}

    def market_open_long(self, inst_id=None, usdt_amount=None, reason="", tag=""):
        self.calls.append(("market_open_long", inst_id, usdt_amount, reason, tag))
        return {"ok": True, "order_id": "raw-open"}

    def market_close_long(self, inst_id=None, reason="", tag=""):
        self.calls.append(("market_close_long", inst_id, reason, tag))
        return {"ok": True, "order_id": "raw-close"}

    def get_positions(self, inst_id=None):
        return {"ok": True, "positions": []}


def _stub_gateway(executed: bool = True):
    """最小网关替身：记录 submit 入参，返回可控 ExecutionResult。"""

    class _Res:
        def __init__(self):
            self.executed = executed
            self.passed = executed
            self.reason = "" if executed else "blocked_by_gateway"
            self.reason_code = "PASS" if executed else "BLOCKED"
            self.order_result = {"ok": True, "order_id": "gw-1"} if executed else None
            self.sltp_result = None

    class _Gw:
        def __init__(self):
            self.decisions = []

        def submit(self, decision):
            self.decisions.append(decision)
            return _Res()

    return _Gw()


# ── 1. fail-closed ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("place_order", {"inst_id": "BTC-USDT-SWAP", "side": "buy", "sz": 1}),
        ("market_open_long", {"inst_id": "BTC-USDT-SWAP", "usdt_amount": 100}),
        ("market_open_short", {"inst_id": "BTC-USDT-SWAP", "usdt_amount": 100}),
        ("market_close_long", {"inst_id": "BTC-USDT-SWAP"}),
        ("market_close_short", {"inst_id": "BTC-USDT-SWAP"}),
        ("reduce_position", {"inst_id": "BTC-USDT-SWAP", "pos_side": "long"}),
        (
            "place_stop_loss_take_profit",
            {"inst_id": "BTC-USDT-SWAP", "pos_side": "long", "stop_loss_px": 1.0},
        ),
    ],
)
def test_fail_closed_client_rejects_every_write(method, kwargs):
    raw = _RawClient()
    client = FailClosedOkxClient(raw)
    out = getattr(client, method)(**kwargs)
    assert out["ok"] is False
    assert out["reason_code"] == "EXECUTION_AUTHORITY_UNAVAILABLE"
    assert raw.calls == [], "执行权威不可用时禁止触达 raw 下单"


def test_fail_closed_client_passes_read_only_through():
    raw = _RawClient()
    client = FailClosedOkxClient(raw)
    assert client.get_positions("BTC-USDT-SWAP")["ok"] is True
    assert client.cfg["default_inst_id"] == "BTC-USDT-SWAP"


# ── 2. 23 域经 22 网关执行 ───────────────────────────────────────────


def test_evo_client_routes_through_gateway_not_raw():
    raw = _RawClient()
    gw = _stub_gateway()
    evo = DomainTaggedOkxClient(raw, gateway=gw)
    out = evo.market_open_long("BARD-USDT-SWAP", 300, reason="evolution_auto_long")
    assert out["ok"] is True
    assert raw.calls == [], "23 域不得直连 raw 下单"
    assert len(gw.decisions) == 1
    d = gw.decisions[0]
    assert d["source"] == "23-evolution"
    assert d["payload"]["tag"] == "evo23"
    assert d["reason"].startswith("[23域]")
    assert d.get("decision_id"), "23 域必须携带 decision_id"
    assert d.get("expires_at"), "23 域必须携带 expires_at"


def test_evo_client_gateway_rejection_is_returned_and_raw_untouched():
    raw = _RawClient()
    gw = _stub_gateway(executed=False)
    evo = DomainTaggedOkxClient(raw, gateway=gw)
    out = evo.place_order(inst_id="BARD-USDT-SWAP", side="buy", sz=1, pos_side="long")
    assert out["ok"] is False
    assert out["reason_code"] == "BLOCKED"
    assert raw.calls == []


def test_evo_client_keeps_shadow_audit_when_gateway_present():
    raw = _RawClient()
    shadow = _stub_gateway()
    gw = _stub_gateway()
    evo = DomainTaggedOkxClient(raw, shadow_gateway=shadow, gateway=gw)
    evo.market_close_long("BARD-USDT-SWAP", reason="evolution_exit")
    assert shadow.decisions and shadow.decisions[0]["source"] == "23-evolution"
    assert len(gw.decisions) == 1
    assert raw.calls == []


# ── 3. 网关侧 23 标签订单 ────────────────────────────────────────────


def test_gateway_tags_23_orders_with_evo23(tmp_path):
    raw = _RawClient()
    gw = TradeExecutionGateway(okx_client=raw, audit_path=tmp_path / "gw.jsonl")
    res = gw.submit(
        {
            "signal_id": "s-1",
            "decision_id": "dec-1",
            "source": "23-evolution",
            "symbol": "BARD-USDT-SWAP",
            "direction": "long",
            "confidence": 0.6,
            "action": "open",
            "sz": 2,
            "pos_side": "long",
            "reason": "[23域]evolution_auto_long",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
    )
    assert res.executed is True
    place = [c for c in raw.calls if c[0] == "place_order"]
    assert place and place[0][1]["tag"] == "evo23"


def test_gateway_tags_23_stop_loss_with_evo23(tmp_path):
    raw = _RawClient()
    gw = TradeExecutionGateway(okx_client=raw, audit_path=tmp_path / "gw.jsonl")
    res = gw.submit(
        {
            "signal_id": "s-2",
            "decision_id": "dec-2",
            "source": "23-evolution",
            "symbol": "BARD-USDT-SWAP",
            "direction": "long",
            "confidence": 0.6,
            "action": "stop_loss",
            "sz": 2,
            "pos_side": "long",
            "sl_px": 1.5,
            "reason": "[23域]evolution_stop_loss",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
    )
    assert res.executed is True
    sltp = [c for c in raw.calls if c[0] == "place_stop_loss_take_profit"]
    assert sltp and sltp[0][1]["tag"] == "evo23"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
