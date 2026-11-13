"""T-G1b：22 Gateway 必须使用「带规则」的 13 门禁，且审计可追溯。

验收点：
    - `_create_gate()` 产出规则数 ≥ 7 的门禁（非空表）
    - 回撤熔断违约的开仓信号被 Gateway 拒绝，且不下单
    - 审计记录包含 rules_evaluated / rule_name / reason_code
"""

import json
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

import trade_execution_gateway as gw_mod  # noqa: E402
from trade_execution_gateway import TradeExecutionGateway, _create_gate  # noqa: E402


class _FakeOkx:
    def __init__(self):
        self.calls = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "order_id": "fake-1"}


def _sig(**kw) -> dict:
    base = {
        "signal_id": "sig-gate-active-1",
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


def test_create_gate_has_real_rules():
    gate = _create_gate()
    assert gate is not None
    assert len(gate.registry.get_enabled_rules()) >= 7


def test_gateway_rejects_open_when_daily_drawdown_breached(tmp_path):
    modules = gw_mod._load_13_modules()
    assert modules is not None
    _, _, RiskContext, _ = modules
    ctx = RiskContext(total_equity=8900.0, max_daily_equity=10000.0)

    raw = _FakeOkx()
    audit = tmp_path / "gateway.jsonl"
    gw = TradeExecutionGateway(okx_client=raw, risk_context=ctx, audit_path=str(audit))

    result = gw.submit(_sig())

    assert result.passed is False
    assert result.executed is False
    assert result.reason_code == "HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER"
    assert raw.calls == []

    rec = json.loads(audit.read_text(encoding="utf-8").strip())
    assert rec["risk_decision"] == "reject"
    assert rec["reason_code"] == "HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER"
    assert rec["rules_evaluated"] >= 1
    assert rec["rule_name"] == "daily_drawdown_circuit_breaker"


def test_gateway_allows_open_when_healthy_and_audits_rules_evaluated(tmp_path):
    modules = gw_mod._load_13_modules()
    assert modules is not None
    _, _, RiskContext, _ = modules
    ctx = RiskContext(total_equity=10000.0)

    raw = _FakeOkx()
    audit = tmp_path / "gateway.jsonl"
    gw = TradeExecutionGateway(okx_client=raw, risk_context=ctx, audit_path=str(audit))

    result = gw.submit(_sig())

    assert result.passed is True
    assert result.executed is True
    assert len(raw.calls) == 1

    rec = json.loads(audit.read_text(encoding="utf-8").strip())
    assert rec["risk_decision"] == "allow"
    assert rec["rules_evaluated"] >= 7
