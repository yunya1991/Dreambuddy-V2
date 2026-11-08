# R3-03: 16 层 PACA 建议适配器测试（全 mock，不读真实运行时文件，不触真实 16 层）。
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import paca_adapter as pa


class _FakeAllocator:
    def __init__(self, advice=None, exc=None):
        self._advice = advice
        self._exc = exc
        self.calls = []

    def get_allocation_advice(self, coin, source_tag, equity):
        self.calls.append((coin, source_tag, equity))
        if self._exc is not None:
            raise self._exc
        return self._advice


_ADVICE = {
    "position_pct": 0.08,
    "expansion_mult": 1.0,
    "final_position_pct": 0.08,
    "position_usdt": 800.0,
    "kelly_f": 0.12,
    "mode": "shadow",
    "fallback_used": False,
    "reason": "ok",
    "constraint_envelope": None,
}


class PacaAdapterTests(unittest.TestCase):
    def test_advice_passthrough(self):
        allocator = _FakeAllocator(advice=dict(_ADVICE))
        decision = {"direction": "long", "symbol": "BTC", "confidence": 0.8}
        out = pa.get_advice(decision, allocator=allocator, equity=10000.0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "16-paca")
        self.assertEqual(out["advice"]["position_pct"], 0.08)
        self.assertEqual(out["advice"]["mode"], "shadow")
        self.assertEqual(len(allocator.calls), 1)
        coin, source_tag, equity = allocator.calls[0]
        self.assertEqual(coin, "BTC")
        self.assertEqual(source_tag, "50-nn")
        self.assertEqual(equity, 10000.0)

    def test_module_load_failed_fallback(self):
        orig = pa._load_allocator
        pa._load_allocator = lambda: None
        try:
            out = pa.get_advice({"direction": "long", "symbol": "BTC", "confidence": 0.8})
        finally:
            pa._load_allocator = orig
        self.assertFalse(out["ok"])
        self.assertIsNone(out["advice"])
        self.assertEqual(out["reason"], "paca_module_load_failed")
        self.assertEqual(out["source"], "16-paca")

    def test_allocator_exception_fallback(self):
        allocator = _FakeAllocator(exc=RuntimeError("boom"))
        out = pa.get_advice(
            {"direction": "long", "symbol": "BTC", "confidence": 0.8}, allocator=allocator
        )
        self.assertFalse(out["ok"])
        self.assertIsNone(out["advice"])
        self.assertTrue(out["reason"].startswith("paca_adapter_exception:"))
        self.assertEqual(out["source"], "16-paca")

    def test_advisory_does_not_mutate_decision(self):
        allocator = _FakeAllocator(advice=dict(_ADVICE))
        decision = {"direction": "long", "symbol": "BTC", "confidence": 0.8, "position_pct": 5.0}
        snapshot = copy.deepcopy(decision)
        out = pa.get_advice(decision, allocator=allocator)
        self.assertTrue(out["ok"])
        self.assertEqual(decision, snapshot)


if __name__ == "__main__":
    unittest.main()
