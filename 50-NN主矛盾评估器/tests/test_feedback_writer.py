# R4-03: 48 反馈样本写入适配器测试（临时目录 + mock sink，不读真实运行时文件）。
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import feedback_writer as fw


_DECISION = {
    "signal_id": "sig-001",
    "symbol": "BTC",
    "direction": "long",
    "confidence": 0.8,
    "position_pct": 5.0,
    "shadow": True,
}
_RISK = {"passed": True, "reason_code": "", "position_modifier": 1.0}
_PACA = {"ok": True, "advice": {"final_position_pct": 0.1, "fallback_used": True}}
_EXEC = {
    "ok": True,
    "receipt": {
        "parent": {"parent_id": "abc123"},
        "_audit_status": "OK_WRITTEN",
        "fail_open": {"triggered": False},
    },
}


class FeedbackWriterTests(unittest.TestCase):
    def test_build_sample_field_mapping(self):
        s = fw.build_feedback_sample(_DECISION, risk_result=_RISK, paca_result=_PACA, exec_result=_EXEC)
        self.assertEqual(s["sample_id"], "sig-001")
        self.assertEqual(s["decision_id"], "sig-001")
        self.assertEqual(s["symbol"], "BTC")
        self.assertEqual(s["direction"], "long")
        self.assertTrue(s["risk"]["passed"])
        self.assertEqual(s["paca"]["final_position_pct"], 0.1)
        self.assertTrue(s["paca"]["fallback_used"])
        self.assertEqual(s["exec"]["parent_id"], "abc123")
        self.assertEqual(s["exec"]["audit_status"], "OK_WRITTEN")
        self.assertFalse(s["exec"]["fail_open_triggered"])
        self.assertEqual(s["source"], "50-nn")
        self.assertEqual(s["dest"], "48-emergence")

    def test_buffered_write(self):
        with tempfile.TemporaryDirectory() as d:
            w = fw.FeedbackWriter(buffer_dir=d)
            s = fw.build_feedback_sample(_DECISION)
            r = w.write(s)
            self.assertTrue(r["written"])
            self.assertEqual(r["delivery"], "buffered")
            path = Path(d) / "feedback_samples.jsonl"
            self.assertTrue(path.exists())
            rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(rec["sample_id"], "sig-001")
            self.assertEqual(rec["delivery"], "buffered")

    def test_dedup_on_reload_and_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            w = fw.FeedbackWriter(buffer_dir=d)
            s = fw.build_feedback_sample(_DECISION)
            self.assertTrue(w.write(s)["written"])
            r2 = w.write(fw.build_feedback_sample(_DECISION))
            self.assertFalse(r2["written"])
            self.assertTrue(r2["deduped"])
            # 重载（模拟重启）后仍去重
            w2 = fw.FeedbackWriter(buffer_dir=d)
            r3 = w2.write(fw.build_feedback_sample(_DECISION))
            self.assertFalse(r3["written"])
            self.assertTrue(r3["deduped"])

    def test_sink_delivery(self):
        delivered = []
        def sink(sample):
            delivered.append(sample)
            return True
        w = fw.FeedbackWriter(sink=sink)
        s = fw.build_feedback_sample(_DECISION)
        r = w.write(s)
        self.assertTrue(r["written"])
        self.assertEqual(r["delivery"], "delivered")
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["sample_id"], "sig-001")

    def test_sink_rejected(self):
        w = fw.FeedbackWriter(sink=lambda sample: False)
        r = w.write(fw.build_feedback_sample(_DECISION))
        self.assertFalse(r["written"])
        self.assertEqual(r["reason"], "sink_rejected")

    def test_replay_to_sink(self):
        with tempfile.TemporaryDirectory() as d:
            w = fw.FeedbackWriter(buffer_dir=d)
            w.write(fw.build_feedback_sample(_DECISION))
            other = dict(_DECISION)
            other["signal_id"] = "sig-002"
            w.write(fw.build_feedback_sample(other))
            got = []
            out = w.replay_to_sink(lambda s: got.append(s) or True)
            self.assertEqual(out["replayed"], 2)
            self.assertEqual(out["failed"], 0)
            self.assertEqual(len(got), 2)

    def test_missing_sample_id_rejected(self):
        w = fw.FeedbackWriter(buffer_dir=None)
        r = w.write({"direction": "long"})
        self.assertFalse(r["written"])
        self.assertEqual(r["reason"], "missing_sample_id")


if __name__ == "__main__":
    unittest.main()
