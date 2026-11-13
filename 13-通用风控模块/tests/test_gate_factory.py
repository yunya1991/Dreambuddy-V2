"""T-G1a：13 门禁工厂必须产出「带默认规则」的门禁实例。

背景：22 TradeExecutionGateway 曾经直接 `PreTradeGate()`（空注册表），
导致 `check()` 恒 PASS、风控空转。本测试锁定工厂契约：
    - 默认配置下规则数 ≥ 7
    - 规则真实生效（回撤/杠杆违约必须拒绝）
    - 配置缺失/异常时 fail-closed 回落代码默认值，绝不允许空表
"""

import json
import pathlib
import sys

RISK_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RISK_DIR))

from core.context import Direction, ReasonCode, RiskContext, Signal  # noqa: E402
from core.factory import create_gate, load_risk_config  # noqa: E402
from core.registry import RuleCategory  # noqa: E402

EXPECTED_GATE_RULES = {
    "daily_drawdown_circuit_breaker",
    "leverage_cap_check",
    "concurrent_position_limit",
    "consecutive_losses_limit",
    "blackout_period_check",
    "confidence_minimum",
    "drawdown_warning_degrade",
}


def _signal(confidence: float = 0.8, coin: str = "BTC-USDT-SWAP") -> Signal:
    return Signal(coin=coin, direction=Direction.LONG, confidence=confidence)


def test_create_gate_registers_default_rules():
    gate = create_gate()
    names = {r.name for r in gate.registry.get_enabled_rules(RuleCategory.GATE)}
    assert len(names) >= 7
    assert EXPECTED_GATE_RULES <= names


def test_create_gate_rejects_drawdown_circuit_breaker():
    gate = create_gate()
    ctx = RiskContext(total_equity=8900.0, max_daily_equity=10000.0)
    result = gate.check(_signal(), ctx)
    assert result.passed is False
    assert result.reason_code == ReasonCode.HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER


def test_create_gate_rejects_leverage_over_cap():
    gate = create_gate()
    result = gate.check(_signal(), RiskContext(total_equity=10000.0), {"leverage": 20})
    assert result.passed is False
    assert result.reason_code == ReasonCode.HARD_FAIL_LEVERAGE_EXCEEDS_CAP


def test_create_gate_rejects_low_confidence():
    gate = create_gate()
    result = gate.check(_signal(confidence=0.1), RiskContext(total_equity=10000.0))
    assert result.passed is False
    assert result.reason_code == ReasonCode.FAIL_LOW_DIM


def test_create_gate_passes_healthy_context_and_reports_rule_count():
    gate = create_gate()
    result = gate.check(_signal(), RiskContext(total_equity=10000.0))
    assert result.passed is True
    assert result.details.get("rules_evaluated", 0) >= 7


def test_load_risk_config_reads_gate_section():
    cfg = load_risk_config()
    assert isinstance(cfg.get("gate"), dict)
    assert "daily_drawdown_circuit_breaker" in cfg["gate"]


def test_create_gate_falls_back_when_config_file_missing(tmp_path):
    missing = tmp_path / "nope.json"
    gate = create_gate(config_path=missing)
    names = {r.name for r in gate.registry.get_enabled_rules(RuleCategory.GATE)}
    assert len(names) >= 7


def test_create_gate_falls_back_when_config_corrupted(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    gate = create_gate(config_path=bad)
    names = {r.name for r in gate.registry.get_enabled_rules(RuleCategory.GATE)}
    assert len(names) >= 7


def test_create_gate_accepts_inline_config():
    gate = create_gate(
        config={"gate": {"daily_drawdown_circuit_breaker": {"max_daily_drawdown_pct": 0.01}}}
    )
    result = gate.check(_signal(), RiskContext(total_equity=9800.0, max_daily_equity=10000.0))
    assert result.passed is False
    assert result.reason_code == ReasonCode.HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER


def test_default_config_file_is_valid_json():
    path = RISK_DIR / "config" / "risk_trading.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data.get("gate"), dict)
