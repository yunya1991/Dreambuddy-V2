# R3-02: 13 层风控接线适配器测试（全 mock，不读真实运行时文件，不触真实 13 层）。
import enum
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import risk_gate_adapter as rga


class _ReasonCode(enum.Enum):
    OK = "OK"
    LEVERAGE_CAP = "LEVERAGE_CAP"


class _FakeResult:
    def __init__(self, passed, message="ok", reason_code=_ReasonCode.OK, position_modifier=1.0):
        self.passed = passed
        self.message = message
        self.reason_code = reason_code
        self.position_modifier = position_modifier


class _FakeGate:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = []

    def check(self, signal, context):
        self.calls.append((signal, context))
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeSignal:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeRiskContext:
    def __init__(self, total_equity=10000.0):
        self.total_equity = total_equity


class _FakeDirection:
    LONG = "LONG"
    SHORT = "SHORT"


class RiskGateAdapterTests(unittest.TestCase):
    def _patch_modules(self, gate):
        orig = rga._load_13_modules
        rga._load_13_modules = lambda: (_FakeGate, _FakeSignal, _FakeRiskContext, _FakeDirection)
        self.addCleanup(setattr, rga, "_load_13_modules", orig)
        return gate

    def test_neutral_skips_execution(self):
        out = rga.check_decision({"direction": "neutral", "symbol": "BTC", "confidence": 0.8})
        self.assertFalse(out["passed"])
        self.assertEqual(out["reason"], "neutral_no_execution")
        self.assertEqual(out["position_modifier"], 1.0)
        self.assertEqual(out["source"], "13-pre-trade-gate")

    def test_module_load_failed_fail_closed(self):
        orig = rga._load_13_modules
        rga._load_13_modules = lambda: None
        try:
            out = rga.check_decision({"direction": "long", "symbol": "BTC", "confidence": 0.8})
        finally:
            rga._load_13_modules = orig
        self.assertFalse(out["passed"])
        self.assertEqual(out["reason"], "risk_module_load_failed")
        self.assertEqual(out["source"], "13-pre-trade-gate")

    def test_gate_pass_maps_fields(self):
        gate = self._patch_modules(_FakeGate(result=_FakeResult(True, "ok", _ReasonCode.OK, 0.5)))
        decision = {
            "direction": "long",
            "symbol": "BTC",
            "confidence": 0.8,
            "signal_id": "sig-001",
            "position_pct": 5.0,
            "shadow": True,
        }
        out = rga.check_decision(decision, gate=gate)
        self.assertTrue(out["passed"])
        self.assertEqual(out["reason"], "ok")
        self.assertEqual(out["reason_code"], "OK")
        self.assertEqual(out["position_modifier"], 0.5)
        self.assertEqual(out["source"], "13-pre-trade-gate")
        self.assertEqual(len(gate.calls), 1)
        sig, ctx = gate.calls[0]
        self.assertEqual(sig.coin, "BTC")
        self.assertEqual(sig.direction, "LONG")
        self.assertEqual(sig.confidence, 0.8)
        self.assertEqual(sig.strategy, "50-nn")
        self.assertEqual(sig.metadata["signal_id"], "sig-001")
        self.assertEqual(sig.metadata["position_pct"], 5.0)
        self.assertEqual(ctx.total_equity, 10000.0)

    def test_gate_block_fail_closed(self):
        gate = self._patch_modules(
            _FakeGate(
                result=_FakeResult(False, "leverage cap exceeded", _ReasonCode.LEVERAGE_CAP, 1.0)
            )
        )
        out = rga.check_decision(
            {"direction": "short", "symbol": "ETH", "confidence": 0.6}, gate=gate
        )
        self.assertFalse(out["passed"])
        self.assertEqual(out["reason"], "leverage cap exceeded")
        self.assertEqual(out["reason_code"], "LEVERAGE_CAP")

    def test_gate_exception_fail_closed(self):
        self._patch_modules(_FakeGate(exc=RuntimeError("boom")))
        out = rga.check_decision({"direction": "long", "symbol": "BTC", "confidence": 0.8})
        self.assertFalse(out["passed"])
        self.assertTrue(out["reason"].startswith("risk_gate_exception:"))
        self.assertEqual(out["source"], "13-pre-trade-gate")


if __name__ == "__main__":
    unittest.main()
