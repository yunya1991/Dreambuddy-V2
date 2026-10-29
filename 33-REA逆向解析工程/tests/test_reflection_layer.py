"""P4 反思层 + P5 批评自循环测试。

覆盖：R1-R3 三级反思、纸上谈兵检测、批评可信度、
观察期推进、客观回滚条件。
"""

import os
import tempfile
import unittest

from core.reflection.reflection_layer import ReflectionLayer
from core.reflection.critic_loop import CriticLoop, OBSERVATION_PERIOD
from core.reflection.replay_simulator import ReplayPool


class TestReflectionLayer(unittest.TestCase):
    def test_clean_report_passes(self):
        report = {
            "decisions": [{"direction": "top-down", "evidence_refs": ["ev1"]}],
            "cost": {"calls": 10},
            "conclusions": [
                {"claim": "模块A依赖模块B", "confidence": 0.9, "evidence_refs": ["ev2"]},
            ],
        }
        critique = ReflectionLayer().reflect(report)
        self.assertTrue(critique["pass"])
        self.assertEqual(critique["critical_count"], 0)

    def test_paper_talk_detection_critical(self):
        report = {
            "conclusions": [
                {"claim": "声称已分析但无证据", "confidence": 0.9, "evidence_refs": []},
            ],
        }
        critique = ReflectionLayer().reflect(report)
        self.assertFalse(critique["pass"])
        self.assertEqual(critique["critical_count"], 1)
        self.assertEqual(critique["findings"][0]["level"], "R3")
        self.assertIn("evidence", critique["findings"][0])

    def test_r1_missing_evidence_warning(self):
        report = {
            "decisions": [{"direction": "bottom-up", "evidence_refs": []}],
            "path_conflict": {"topic": "t", "adjudication_basis": ""},
        }
        critique = ReflectionLayer().reflect(report)
        r1 = [f for f in critique["findings"] if f["level"] == "R1"]
        self.assertEqual(len(r1), 2)
        self.assertTrue(all(f["severity"] == "WARNING" for f in r1))

    def test_r2_over_analysis(self):
        report = {"cost": {"calls": 500}, "conclusions": []}
        critique = ReflectionLayer().reflect(report)
        r2 = [f for f in critique["findings"] if f["level"] == "R2"]
        self.assertEqual(len(r2), 1)
        self.assertIn("过度分析", r2[0]["message"])

    def test_all_findings_carry_evidence(self):
        report = {
            "decisions": [{"direction": "x", "evidence_refs": []}],
            "cost": {"calls": 999},
            "conclusions": [{"claim": "c", "confidence": 0.1, "evidence_refs": []}],
        }
        critique = ReflectionLayer().reflect(report)
        self.assertTrue(critique["findings"])
        for f in critique["findings"]:
            self.assertIn("evidence", f)
            self.assertIn("evidence_id", f["evidence"])


class TestCriticLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rea_critic_test_")
        self.pool = ReplayPool(os.path.join(self.tmp, "pool"))

    def test_propose_without_pool_stays_proposed(self):
        loop = CriticLoop(pool=None)
        p = loop.propose("矛盾A", "假说A")
        self.assertEqual(p.status, "proposed")
        self.assertFalse(p.independently_verified)
        self.assertAlmostEqual(p.credibility, 0.5)

    def test_observation_period_adoption(self):
        loop = CriticLoop(pool=self.pool)
        p = loop.propose("矛盾A", "假说A", self_score=0.6)
        # 池不可评估时保持 proposed；直接置为 observing 测试观察期
        p.status = "observing"
        r1 = loop.record_task(p.proposal_id, 80.0, 1.0, 10)
        self.assertEqual(r1["status"], "observing")
        r2 = loop.record_task(p.proposal_id, 80.0, 1.0, 10)
        self.assertEqual(r2["status"], "observing")
        r3 = loop.record_task(p.proposal_id, 80.0, 1.0, 10)
        self.assertEqual(r3["status"], "adopted")
        self.assertEqual(p.observed_tasks, OBSERVATION_PERIOD)

    def test_rollback_on_poe_drop(self):
        loop = CriticLoop(pool=self.pool)
        p = loop.propose("矛盾A", "假说A")
        p.status = "observing"
        loop.record_task(p.proposal_id, 80.0, 1.0, 10)  # 建基线
        r = loop.record_task(p.proposal_id, 60.0, 1.0, 10)  # 降 20 分 > 15
        self.assertTrue(r["rolled_back"])
        self.assertEqual(p.status, "rolled_back")

    def test_rollback_on_evidence_drop(self):
        loop = CriticLoop(pool=self.pool)
        p = loop.propose("矛盾A", "假说A")
        p.status = "observing"
        loop.record_task(p.proposal_id, 80.0, 1.0, 10)
        r = loop.record_task(p.proposal_id, 85.0, 0.9, 10)  # 完整度下降
        self.assertTrue(r["rolled_back"])
        self.assertEqual(r["reason"], "evidence completeness dropped")

    def test_rollback_on_cost_rise(self):
        loop = CriticLoop(pool=self.pool)
        p = loop.propose("矛盾A", "假说A")
        p.status = "observing"
        loop.record_task(p.proposal_id, 80.0, 1.0, 10)
        r = loop.record_task(p.proposal_id, 80.0, 1.0, 20)  # 成本升 100% > 50%
        self.assertTrue(r["rolled_back"])
        self.assertEqual(r["reason"], "cost rose over threshold")


if __name__ == "__main__":
    unittest.main()
