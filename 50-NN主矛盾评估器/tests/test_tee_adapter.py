# R3-04: 22 层 tee_core paper 执行适配器测试（全 mock，不读真实运行时文件，不触真实 22 层）。
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import tee_adapter as ta


class _FakeEngine:
    def __init__(self, receipt=None, exc=None):
        self._receipt = receipt
        self._exc = exc
        self.calls = []

    def execute(self, parent_req):
        self.calls.append(parent_req)
        if self._exc is not None:
            raise self._exc
        return self._receipt


_RECEIPT = {
    "ts_epoch_ms": 1730000000000,
    "parent": {"inst_id": "BTC"},
    "estimate": {},
    "router": {},
    "algo": {},
    "kill_switch": {},
    "fail_open": {"triggered": False},
    "exec": {},
    "children": [],
}


class TeeAdapterTests(unittest.TestCase):
    def test_neutral_skips_execution(self):
        out = ta.execute_decision({"direction": "neutral", "symbol": "BTC", "confidence": 0.8})
        self.assertFalse(out["ok"])
        self.assertIsNone(out["receipt"])
        self.assertEqual(out["reason"], "neutral_no_execution")
        self.assertEqual(out["source"], "22-tee-core")

    def test_module_load_failed_fail_safe(self):
        orig = ta._load_engine_cls
        ta._load_engine_cls = lambda: None
        try:
            out = ta.execute_decision({"direction": "long", "symbol": "BTC", "confidence": 0.8})
        finally:
            ta._load_engine_cls = orig
        self.assertFalse(out["ok"])
        self.assertIsNone(out["receipt"])
        self.assertEqual(out["reason"], "tee_module_load_failed")
        self.assertEqual(out["source"], "22-tee-core")

    def test_receipt_passthrough(self):
        engine = _FakeEngine(receipt=dict(_RECEIPT))
        decision = {
            "direction": "long",
            "symbol": "BTC",
            "confidence": 0.8,
            "signal_id": "sig-001",
            "position_pct": 5.0,
        }
        out = ta.execute_decision(decision, engine=engine, equity=10000.0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "22-tee-core")
        self.assertEqual(out["receipt"]["parent"]["inst_id"], "BTC")
        self.assertEqual(len(engine.calls), 1)
        req = engine.calls[0]
        self.assertEqual(req["inst_id"], "BTC")
        self.assertEqual(req["side"], "buy")
        self.assertEqual(req["sz"], 500.0)
        self.assertEqual(req["source"], "50-nn")
        self.assertEqual(req["tag"], "50-nn-paper")
        self.assertEqual(req["metadata"]["signal_id"], "sig-001")
        self.assertEqual(req["metadata"]["position_pct"], 5.0)

    def test_engine_exception_fail_safe(self):
        engine = _FakeEngine(exc=RuntimeError("boom"))
        out = ta.execute_decision({"direction": "short", "symbol": "ETH", "confidence": 0.6}, engine=engine)
        self.assertFalse(out["ok"])
        self.assertIsNone(out["receipt"])
        self.assertTrue(out["reason"].startswith("tee_adapter_exception:"))
        self.assertEqual(out["source"], "22-tee-core")

    def test_build_parent_req_field_mapping(self):
        decision = {
            "direction": "short",
            "symbol": "ETH",
            "confidence": 0.7,
            "signal_id": "sig-002",
            "position_pct": 3.0,
            "shadow": True,
        }
        req = ta.build_parent_req(decision, equity=10000.0)
        self.assertEqual(req["inst_id"], "ETH")
        self.assertEqual(req["side"], "sell")
        self.assertEqual(req["sz"], 300.0)
        self.assertEqual(req["td_mode"], "isolated")
        self.assertEqual(req["pos_side"], "net")
        self.assertEqual(req["source"], "50-nn")
        self.assertEqual(req["reason"], "sig-002")
        self.assertEqual(req["metadata"]["confidence"], 0.7)
        self.assertEqual(req["metadata"]["shadow"], True)


if __name__ == "__main__":
    unittest.main()
