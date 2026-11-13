"""13 只读影子校验模式（shadow_only）测试。

场景：13→16→22→11 链路只属于神经网络系统；23 自进化域下单不经过该链路，
但保留 13 只读校验并落审计（source=23-evolution），且**绝不执行下单**。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_GW_DIR = Path(__file__).resolve().parents[1]
if str(_GW_DIR) not in sys.path:
    sys.path.insert(0, str(_GW_DIR))

import trade_execution_gateway as gw_mod  # noqa: E402
from trade_execution_gateway import TradeExecutionGateway  # noqa: E402


class _RawClient:
    def __init__(self):
        self.calls = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "ord_id": "raw-1"}


class _FakeGate:
    def __init__(self, passed: bool = False):
        self._passed = passed
        self.calls = []

    def check(self, signal, ctx):
        self.calls.append((signal, ctx))
        return type(
            "Check",
            (),
            {
                "passed": self._passed,
                "reason_code": type("RC", (), {"value": "TEST_REASON"})(),
                "message": "fake check",
                "position_modifier": 0.8,
            },
        )()


class _Signal:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _RiskContext:
    def __init__(self, total_equity: float = 0.0):
        self.total_equity = total_equity


class _Direction:
    LONG = "long"
    SHORT = "short"


@pytest.fixture()
def shadow_gw(tmp_path, monkeypatch):
    gate = _FakeGate(passed=False)
    monkeypatch.setattr(
        gw_mod,
        "_load_13_modules",
        lambda: (lambda *a, **k: gate, _Signal, _RiskContext, _Direction),
    )
    raw = _RawClient()
    audit = tmp_path / "gateway.jsonl"
    gw = TradeExecutionGateway(okx_client=raw, audit_path=str(audit), shadow_only=True)
    # 绕过 _submit_shadow 内部对 13 模块的二次构造
    gw._gate = gate
    return gw, raw, audit, gate


def test_shadow_only_never_executes(shadow_gw):
    gw, raw, _audit, _gate = shadow_gw
    result = gw.submit(
        {
            "signal_id": "23-evolution|t1",
            "source": "23-evolution",
            "symbol": "BARD-USDT-SWAP",
            "direction": "long",
            "confidence": 0.6,
            "action": "open",
            "reason": "[23域]evolution_auto_long",
        }
    )
    assert result.executed is False
    assert raw.calls == []


def test_shadow_only_audits_with_domain_source(shadow_gw):
    gw, _raw, audit, _gate = shadow_gw
    gw.submit(
        {
            "signal_id": "23-evolution|t2",
            "source": "23-evolution",
            "symbol": "BARD-USDT-SWAP",
            "direction": "long",
            "confidence": 0.6,
            "action": "open",
            "reason": "[23域]evolution_auto_long",
        }
    )
    records = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines() if x]
    assert records
    rec = records[-1]
    assert rec["shadow_only"] is True
    assert rec["executed"] is False
    assert rec["source"] == "23-evolution"
    assert rec["risk_decision"] == "reject"
    assert rec["reason_code"] == "SHADOW_TEST_REASON"


def test_shadow_only_runs_13_check(shadow_gw):
    gw, _raw, _audit, gate = shadow_gw
    gw.submit(
        {
            "signal_id": "23-evolution|t3",
            "source": "23-evolution",
            "symbol": "BARD-USDT-SWAP",
            "direction": "short",
            "confidence": 0.6,
            "action": "open",
        }
    )
    assert len(gate.calls) == 1


def test_shadow_only_skips_neutral(tmp_path, monkeypatch):
    monkeypatch.setattr(gw_mod, "_load_13_modules", lambda: None)
    raw = _RawClient()
    gw = TradeExecutionGateway(
        okx_client=raw, audit_path=str(tmp_path / "g.jsonl"), shadow_only=True
    )
    result = gw.submit(
        {
            "signal_id": "23-evolution|t4",
            "source": "23-evolution",
            "symbol": "X-USDT-SWAP",
            "direction": "neutral",
            "action": "hold",
        }
    )
    assert result.executed is False
    assert result.reason_code == "SHADOW_NEUTRAL_NO_EXECUTION"
    assert raw.calls == []
