# R4-02: 50 训练门禁测试（临时目录注入，不读真实运行时文件）。
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import training_gate as tg


class TrainingGateTests(unittest.TestCase):
    def _gate(self, audit_dir):
        return tg.TrainingGate(audit_dir=audit_dir)

    def test_valid_weights_accepted_when_learning(self):
        with tempfile.TemporaryDirectory() as d:
            gate = self._gate(d)
            s = {"suggestion_id": "s-001", "type": "weights", "weights": {"D1": 1.2, "D2": 0.4}}
            r = gate.adjudicate(s, w6_state="learning")
            self.assertTrue(r["accepted"])
            self.assertEqual(r["reason_code"], "ok")
            self.assertEqual(r["source"], "50-training-gate")

    def test_cold_start_rejects_weights(self):
        with tempfile.TemporaryDirectory() as d:
            gate = self._gate(d)
            s = {"suggestion_id": "s-002", "type": "weights", "weights": {"D1": 1.0}}
            r = gate.adjudicate(s, w6_state="cold_start")
            self.assertFalse(r["accepted"])
            self.assertIn("w6_cold_start_weights_rejected", r["reason_code"])

    def test_weight_out_of_band_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            gate = self._gate(d)
            s = {"suggestion_id": "s-003", "type": "weights", "weights": {"D1": 2.0}}
            r = gate.adjudicate(s, w6_state="learning")
            self.assertFalse(r["accepted"])
            self.assertIn("weight_out_of_band", r["reason_code"])

    def test_relax_40_gate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            gate = self._gate(d)
            s = {"suggestion_id": "s-004", "type": "strategy", "relax_40_gate": True}
            r = gate.adjudicate(s, w6_state="learning")
            self.assertFalse(r["accepted"])
            self.assertIn("relax_40_gate_forbidden", r["reason_code"])

    def test_missing_id_or_unknown_type_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            gate = self._gate(d)
            r1 = gate.adjudicate({"type": "strategy"}, w6_state="learning")
            self.assertFalse(r1["accepted"])
            self.assertIn("missing_suggestion_id", r1["reason_code"])
            r2 = gate.adjudicate({"suggestion_id": "s-005", "type": "unknown"}, w6_state="learning")
            self.assertFalse(r2["accepted"])
            self.assertIn("unknown_suggestion_type", r2["reason_code"])

    def test_audit_written(self):
        with tempfile.TemporaryDirectory() as d:
            gate = self._gate(d)
            s = {"suggestion_id": "s-006", "type": "strategy"}
            gate.adjudicate(s, w6_state="learning")
            audit_path = Path(d) / "training_gate_audit.jsonl"
            self.assertTrue(audit_path.exists())
            lines = [ln for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertEqual(rec["suggestion_id"], "s-006")
            self.assertTrue(rec["accepted"])


if __name__ == "__main__":
    unittest.main()
