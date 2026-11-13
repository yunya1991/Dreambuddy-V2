"""Tests for TradeExecutionGateway (T1 / AC-1 / AC-6).

TR-1.1: Gateway calls 13 PreTradeGate.check(); 13 returns reject → no order placed.
TR-1.2: 13 unavailable → open rejected, close allowed (fail-closed).
TR-1.3: audit log contains decision_id / risk_decision / reason.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from trade_execution_gateway import (  # noqa: E402
    FinalDecisionSignal,
    RiskGatedOkxClient,
    TradeExecutionGateway,
)


class _FakeOkx:
    def __init__(self) -> None:
        self.calls = []
        self.sltp_calls = []
        self.order_result = None
        self.last_px = 50000.0
        self.ct_val = 0.01
        self.ct_mult = 1.0
        self.has_instrument = True
        self.cfg = {
            "default_inst_id": "BTC-USDT-SWAP",
            "default_usdt_amount": 500.0,
            "td_mode": "isolated",
        }
        self.positions = []

    def get_ticker(self, inst_id):
        return {"ok": True, "last": self.last_px, "bid": self.last_px, "ask": self.last_px}

    def get_instrument(self, inst_id):
        if not self.has_instrument:
            return {"ok": False}
        return {
            "ok": True,
            "ct_val": self.ct_val,
            "ct_mult": self.ct_mult,
            "lot_sz": 0.01,
        }

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        if self.order_result is not None:
            return self.order_result
        return {"ok": True, "order_id": "fake-1", **kwargs}

    def place_stop_loss_take_profit(self, **kwargs):
        self.sltp_calls.append(kwargs)
        return {"ok": True, "order_id": "fake-sltp-1", **kwargs}

    def _usdt_to_sz(self, inst_id, usdt_amount):
        return float(usdt_amount) / (self.last_px * self.ct_val)

    def get_positions(self, inst_id):
        return {"ok": True, "positions": list(self.positions)}

    def market_open_long(self, inst_id=None, usdt_amount=None, reason=""):
        inst_id = inst_id or self.cfg["default_inst_id"]
        usdt_amount = usdt_amount or self.cfg["default_usdt_amount"]
        return self.place_order(
            inst_id=inst_id,
            side="buy",
            ord_type="market",
            sz=self._usdt_to_sz(inst_id, usdt_amount),
            pos_side="long",
            reason=reason or "open_long",
        )

    def market_open_short(self, inst_id=None, usdt_amount=None, reason=""):
        inst_id = inst_id or self.cfg["default_inst_id"]
        usdt_amount = usdt_amount or self.cfg["default_usdt_amount"]
        return self.place_order(
            inst_id=inst_id,
            side="sell",
            ord_type="market",
            sz=self._usdt_to_sz(inst_id, usdt_amount),
            pos_side="short",
            reason=reason or "open_short",
        )

    def market_close_long(self, inst_id=None, reason=""):
        inst_id = inst_id or self.cfg["default_inst_id"]
        pos = next(p for p in self.positions if p["pos_side"] == "long")
        return self.place_order(
            inst_id=inst_id,
            side="sell",
            ord_type="market",
            sz=pos["pos"],
            pos_side="long",
            reason=reason or "close_long",
        )

    def market_close_short(self, inst_id=None, reason=""):
        inst_id = inst_id or self.cfg["default_inst_id"]
        pos = next(p for p in self.positions if p["pos_side"] == "short")
        return self.place_order(
            inst_id=inst_id,
            side="buy",
            ord_type="market",
            sz=pos["pos"],
            pos_side="short",
            reason=reason or "close_short",
        )

    def reduce_position(self, inst_id=None, pos_side="long", reduce_ratio=0.5, reason=""):
        inst_id = inst_id or self.cfg["default_inst_id"]
        pos = next(p for p in self.positions if p["pos_side"] == pos_side)
        reduce_sz = int(pos["pos"] * reduce_ratio)
        result = self.place_order(
            inst_id=inst_id,
            side="sell" if pos_side == "long" else "buy",
            ord_type="market",
            sz=reduce_sz,
            pos_side=pos_side,
            reason=reason or "reduce",
        )
        result["original_pos"] = pos["pos"]
        result["reduce_sz"] = reduce_sz
        return result


class _FakeAllocator:
    def __init__(self, advice=None, events=None):
        self.advice = advice
        self.events = events if events is not None else []

    def get_allocation_advice(self, **kwargs):
        self.events.append("16")
        if isinstance(self.advice, Exception):
            raise self.advice
        return self.advice


class _FakeTee:
    def __init__(self, result=None, events=None, shadow_mode=False):
        self.result = result
        self.events = events if events is not None else []
        self.calls = []
        self.shadow_mode = shadow_mode

    def execute_market_compat(self, **kwargs):
        self.events.append("22")
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _allow(position_modifier=1.0):
    return SimpleNamespace(
        passed=True,
        reason_code="PASS",
        message="all_gates_passed",
        position_modifier=position_modifier,
    )


def _sig(**kw) -> dict:
    base = {
        "signal_id": "sig-001",
        "source": "11-yijing",
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "confidence": 0.8,
        "action": "open",
        "sz": 0.01,
        "reason": "test",
    }
    base.update(kw)
    return base


def test_tr1_1_reject_blocks_order():
    """13 返回 reject 时不下单。"""
    fake_okx = _FakeOkx()
    gw = TradeExecutionGateway(okx_client=fake_okx)

    # mock 13 gate.check to return reject
    class _RejectResult:
        passed = False
        reason_code = "HARD_FAIL_STRATEGY_EXCLUDED"
        message = "strategy excluded"
        position_modifier = 1.0

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _RejectResult()
        result = gw.submit(_sig())

    assert result.passed is False
    assert result.executed is False
    assert fake_okx.calls == []  # no order placed
    assert "STRATEGY_EXCLUDED" in result.reason_code


def test_tr1_2_fail_closed_open_rejected_close_allowed():
    """13 不可用时开仓 reject、平仓 allow。"""
    fake_okx = _FakeOkx()
    gw = TradeExecutionGateway(okx_client=fake_okx)

    # force 13 load to fail
    with patch("trade_execution_gateway._load_13_modules", return_value=None):
        # open → reject
        r_open = gw.submit(_sig(action="open"))
        assert r_open.passed is False
        assert r_open.executed is False
        assert "OPEN_REJECTED" in r_open.reason_code

        # close → allow
        r_close = gw.submit(_sig(action="close"))
        assert r_close.passed is True
        assert r_close.executed is True
        assert "CLOSE_ALLOWED" in r_close.reason_code
        assert len(fake_okx.calls) == 1


def test_tr1_3_audit_log_contains_fields():
    """审计日志含 decision_id(signal_id) / risk_decision / reason。"""
    fake_okx = _FakeOkx()
    with tempfile.TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "gateway.jsonl"
        gw = TradeExecutionGateway(okx_client=fake_okx, audit_path=audit_path)
        gw.submit(_sig(signal_id="sig-audit-1"))

        lines = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 1
        rec = lines[0]
        assert rec["signal_id"] == "sig-audit-1"
        assert rec["risk_decision"] in ("allow", "reject")
        assert "reason_code" in rec and rec["reason_code"]


def test_neutral_no_execution():
    """neutral 方向不进执行链。"""
    fake_okx = _FakeOkx()
    gw = TradeExecutionGateway(okx_client=fake_okx)
    r = gw.submit(_sig(direction="neutral"))
    assert r.passed is False
    assert r.executed is False
    assert r.reason_code == "NEUTRAL_NO_EXECUTION"
    assert fake_okx.calls == []


def test_from_dict_maps_inst_id_to_symbol():
    """FinalDecisionSignal.from_dict 兼容 inst_id 字段。"""
    sig = FinalDecisionSignal.from_dict({"inst_id": "ETH-USDT-SWAP", "direction": "short"})
    assert sig.symbol == "ETH-USDT-SWAP"
    assert sig.direction == "short"


def test_t13_runs_13_16_22_in_order_and_caps_size():
    """13→16→22 顺序正确；16 只做上限约束，不放大调用方仓位。

    equity=10000, pct=0.2, px=50000, ct_val=0.01 → 合约面值 500 USDT
    cap = 2000/500 = 4 张。调用方 sz=0.01 张（约 5 USDT）不得被放大到 4 张。
    """
    events = []
    fake_okx = _FakeOkx()
    allocator = _FakeAllocator({"final_position_pct": 0.2}, events)
    tee = _FakeTee({"ok": True, "order_id": "tee-1"}, events)
    gw = TradeExecutionGateway(
        okx_client=fake_okx,
        risk_context=SimpleNamespace(total_equity=10000.0),
        capital_allocator=allocator,
        tee_engine=tee,
    )

    with patch.object(gw, "_gate") as gate:
        gate.check.side_effect = lambda *_: events.append("13") or _allow(0.5)
        result = gw.submit(_sig(sz=0.01))

    assert events == ["13", "16", "22"]
    # 16 cap=4 张 > 调用方 0.01 张，不放大；13 position_modifier=0.5 再乘
    assert tee.calls[0]["sz"] == 0.005
    assert fake_okx.calls == []
    assert result.executed is True
    assert result.order_result["order_id"] == "tee-1"


def test_t13_allocator_cap_limits_oversized_order():
    """调用方仓位超过 16 上限时，按合约面值换算成张数后截断。"""
    fake_okx = _FakeOkx()
    allocator = _FakeAllocator({"final_position_pct": 0.2})
    gw = TradeExecutionGateway(
        okx_client=fake_okx,
        risk_context=SimpleNamespace(total_equity=10000.0),
        capital_allocator=allocator,
    )

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        gw.submit(_sig(sz=10.0))

    # cap = 10000 * 0.2 / (50000 * 0.01) = 4 张
    assert fake_okx.calls[0]["sz"] == 4.0


def test_t13_missing_contract_info_skips_sizing():
    """无法取得合约面值时不做定容，保持调用方 sz（FAIL-OPEN）。"""
    fake_okx = _FakeOkx()
    fake_okx.has_instrument = False
    allocator = _FakeAllocator({"final_position_pct": 0.2})
    gw = TradeExecutionGateway(
        okx_client=fake_okx,
        risk_context=SimpleNamespace(total_equity=10000.0),
        capital_allocator=allocator,
    )

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        gw.submit(_sig(sz=10.0))

    assert fake_okx.calls[0]["sz"] == 10.0


def test_t13_allocator_failure_uses_caller_size():
    fake_okx = _FakeOkx()
    tee = _FakeTee({"ok": True, "order_id": "tee-1"})
    gw = TradeExecutionGateway(
        okx_client=fake_okx,
        capital_allocator=_FakeAllocator(RuntimeError("16 unavailable")),
        tee_engine=tee,
    )

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        result = gw.submit(_sig(sz=0.01))

    assert result.executed is True
    assert tee.calls[0]["sz"] == 0.01


def test_t13_tee_failure_falls_back_to_raw_client():
    fake_okx = _FakeOkx()
    tee = _FakeTee({"ok": False, "error": "22 unavailable"})
    gw = TradeExecutionGateway(okx_client=fake_okx, tee_engine=tee)

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        result = gw.submit(_sig())

    assert result.executed is True
    assert result.order_result["order_id"] == "fake-1"
    assert len(fake_okx.calls) == 1


def test_raw_order_failure_is_not_executed_or_misreported_as_risk_reject():
    fake_okx = _FakeOkx()
    fake_okx.order_result = {"ok": False, "error": "insufficient margin"}
    gw = TradeExecutionGateway(okx_client=fake_okx)
    client = RiskGatedOkxClient(fake_okx, gw)

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        result = gw.submit(_sig())
        proxied = client.place_order(inst_id="BTC-USDT-SWAP", side="buy", pos_side="long", sz=0.01)

    assert result.passed is True
    assert result.executed is False
    assert result.reason_code == "ORDER_FAILED"
    assert result.order_result["error"] == "insufficient margin"
    assert proxied["ok"] is False
    assert proxied["error"] == "insufficient margin"
    assert "rejected" not in proxied


def test_t13_shadow_tee_records_but_still_places_raw_order():
    """shadow 只记录决策差异，真实下单必须仍走 raw client（防吞单）。"""
    fake_okx = _FakeOkx()
    tee = _FakeTee({"ok": True, "state": "live", "ord_id": "shadow-abc"}, shadow_mode=True)
    gw = TradeExecutionGateway(okx_client=fake_okx, tee_engine=tee)

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        result = gw.submit(_sig())

    assert result.executed is True
    assert len(fake_okx.calls) == 1
    assert result.order_result["order_id"] == "fake-1"


def test_t13_tee_receives_limit_price_and_ord_type():
    fake_okx = _FakeOkx()
    tee = _FakeTee({"ok": True, "order_id": "tee-1"})
    gw = TradeExecutionGateway(okx_client=fake_okx, tee_engine=tee)

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        gw.submit(_sig(px=50000.0))

    req = tee.calls[0]
    assert req["px"] == 50000.0
    assert req["ord_type"] == "limit"


def test_stop_loss_take_profit_uses_algo_order_and_position_modifier():
    fake_okx = _FakeOkx()
    gw = TradeExecutionGateway(okx_client=fake_okx)

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow(0.5)
        result = gw.submit(_sig(action="stop_loss", sz=2.0, sl_px=90000.0, tp_px=110000.0))

    assert result.executed is True
    assert fake_okx.calls == []
    assert len(fake_okx.sltp_calls) == 1
    assert fake_okx.sltp_calls[0]["sz"] == 1.0
    assert fake_okx.sltp_calls[0]["stop_loss_px"] == 90000.0
    assert fake_okx.sltp_calls[0]["take_profit_px"] == 110000.0


def test_risk_gated_market_open_cannot_bypass_13():
    """raw 的高层绑定方法不得绕过代理，否则开仓会跳过 13。"""
    fake_okx = _FakeOkx()
    gw = TradeExecutionGateway(okx_client=fake_okx)
    client = RiskGatedOkxClient(fake_okx, gw)
    reject = SimpleNamespace(
        passed=False,
        reason_code="RISK_REJECT",
        message="blocked by 13",
        position_modifier=1.0,
    )

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = reject
        result = client.market_open_long(usdt_amount=500.0, reason="high_level_open")

    assert result["ok"] is False
    assert result["rejected"] is True
    assert result["reason_code"] == "RISK_REJECT"
    assert fake_okx.calls == []
    assert gate.check.call_count == 1


def test_risk_gated_high_level_open_runs_13_then_22():
    events = []
    fake_okx = _FakeOkx()
    tee = _FakeTee({"ok": True, "order_id": "tee-high-level"}, events)
    gw = TradeExecutionGateway(okx_client=fake_okx, tee_engine=tee)
    client = RiskGatedOkxClient(fake_okx, gw)

    with patch.object(gw, "_gate") as gate:
        gate.check.side_effect = lambda *_: events.append("13") or _allow()
        result = client.market_open_short(usdt_amount=500.0)

    assert events == ["13", "22"]
    assert result["order_id"] == "tee-high-level"
    assert tee.calls[0]["side"] == "sell"
    assert tee.calls[0]["sz"] == 1.0
    assert fake_okx.calls == []


def test_risk_gated_close_and_reduce_stay_on_gateway_chain():
    fake_okx = _FakeOkx()
    fake_okx.positions = [
        {"pos_side": "long", "pos": 10},
        {"pos_side": "short", "pos": 4},
    ]
    gw = TradeExecutionGateway(okx_client=fake_okx)
    client = RiskGatedOkxClient(fake_okx, gw)

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        close_long = client.market_close_long(reason="close_via_gateway")
        close_short = client.market_close_short(reason="close_via_gateway")
        reduced = client.reduce_position(
            pos_side="short", reduce_ratio=0.5, reason="reduce_via_gateway"
        )

    assert close_long["ok"] is True
    assert close_short["ok"] is True
    assert reduced["reduce_sz"] == 2
    assert reduced["original_pos"] == 4
    assert gate.check.call_count == 3
    actions = [call.args[0].metadata["action"] for call in gate.check.call_args_list]
    assert actions == ["close", "close", "reduce"]
    assert [(c["side"], c["sz"]) for c in fake_okx.calls] == [
        ("sell", 10),
        ("buy", 4),
        ("buy", 2),
    ]


def test_attached_sltp_after_open_success():
    """开仓成功后，sig 带 sl_px/tp_px → 自动补 SL/TP 条件单。

    等价于原始 okx_client.execute_bcrm_signal 的 "开仓→成功→补 SL/TP" 逻辑。
    """
    fake_okx = _FakeOkx()
    gw = TradeExecutionGateway(okx_client=fake_okx)

    sig = FinalDecisionSignal(
        signal_id="sltp-1",
        source="test",
        symbol="BTC-USDT-SWAP",
        direction="long",
        action="open",
        sz=0.01,
        pos_side="long",
        sl_px=48000.0,
        tp_px=55000.0,
    )
    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        result = gw.submit(sig)

    assert result.executed is True
    assert len(fake_okx.calls) == 1  # 主市价单
    assert len(fake_okx.sltp_calls) == 1  # 自动补 SL/TP
    sltp = fake_okx.sltp_calls[0]
    assert sltp["inst_id"] == "BTC-USDT-SWAP"
    assert sltp["pos_side"] == "long"
    assert sltp["stop_loss_px"] == 48000.0
    assert sltp["take_profit_px"] == 55000.0
    assert result.sltp_result is not None
    assert result.sltp_result["ok"] is True


def test_attached_sltp_not_triggered_on_close_or_takeover():
    """close/reduce/stop_loss/take_profit 动作 → 不自动补 SL/TP。"""
    fake_okx = _FakeOkx()
    fake_okx.positions = [{"pos_side": "long", "pos": 10}]
    gw = TradeExecutionGateway(okx_client=fake_okx)

    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        result_close = gw.submit(
            FinalDecisionSignal(
                signal_id="close-1",
                source="test",
                symbol="BTC-USDT-SWAP",
                direction="long",
                action="close",
                sz=10,
                pos_side="long",
                sl_px=48000.0,
                tp_px=55000.0,
            )
        )
        result_tp = gw.submit(
            FinalDecisionSignal(
                signal_id="tp-1",
                source="test",
                symbol="BTC-USDT-SWAP",
                direction="long",
                action="take_profit",
                sz=5,
                pos_side="long",
                tp_px=55000.0,
            )
        )

    assert result_close.executed is True
    assert result_close.sltp_result is None  # close 不补
    assert result_tp.executed is True
    assert result_tp.sltp_result is None  # take_profit 本身就是 SL/TP 类，跳过
    assert (
        len(fake_okx.sltp_calls) == 1
    )  # 只有 take_profit 自己那笔（来自 _place_order 的 SL/TP 分支）


def test_attached_sltp_failure_does_not_taint_main_order():
    """主单成功但 SL/TP 补单失败 → 主单 executed=True 不受影响，仅日志告警。"""
    fake_okx = _FakeOkx()
    gw = TradeExecutionGateway(okx_client=fake_okx)
    fake_okx.sltp_calls = []

    def _bad_sltp(**kwargs):
        raise RuntimeError("sltp api broken")

    fake_okx.place_stop_loss_take_profit = _bad_sltp

    sig = FinalDecisionSignal(
        signal_id="sltp-fail-1",
        source="test",
        symbol="BTC-USDT-SWAP",
        direction="long",
        action="open",
        sz=0.01,
        pos_side="long",
        sl_px=48000.0,
        tp_px=55000.0,
    )
    with patch.object(gw, "_gate") as gate:
        gate.check.return_value = _allow()
        result = gw.submit(sig)

    assert result.executed is True  # 主单仍算成功
    assert result.sltp_result is not None
    assert result.sltp_result["ok"] is False
    assert "sltp api broken" in result.sltp_result["error"]
