"""AI 验收官 / 预检 / 模型分档 / 卡住作业复位 的离线测试。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401 - 负责把 skill/scripts 加入 sys.path

import brain
import store as store_mod  # noqa: F401


class RoutingTest(unittest.TestCase):
    def test_route_tier_by_task(self):
        self.assertEqual(brain.route_tier("verify"), "strong")
        self.assertEqual(brain.route_tier("extract"), "fast")
        self.assertEqual(brain.route_tier("generic"), "standard")

    def test_simple_plan_downgrades_complex_plan_upgrades(self):
        self.assertEqual(brain.route_tier("plan", "查看作业"), "fast")
        self.assertEqual(
            brain.route_tier("plan", "帮我预约12月25日周杰伦内场最高1280元，然后同时还要顺便检查环境以及报告"),
            "strong",
        )


class PrecheckTest(unittest.TestCase):
    def test_dispatch_missing_fields(self):
        result = brain.precheck("dispatch", {"adapter": "bilibili", "target_id": "周杰伦"})
        self.assertFalse(result["ok"])
        self.assertIn("session", result["missing"])

    def test_dispatch_ok(self):
        result = brain.precheck(
            "dispatch", {"adapter": "bilibili", "target_id": "漫展", "session": "12月25日", "max_price": 300}
        )
        self.assertTrue(result["ok"])

    def test_consult_requires_question(self):
        self.assertFalse(brain.precheck("consult", {"question": "  "})["ok"])
        self.assertTrue(brain.precheck("consult", {"question": "点击无效怎么办"})["ok"])

    def test_precheck_plan_collects_problems(self):
        plan = {"steps": [{"action": "dispatch", "params": {"adapter": "bilibili"}}]}
        result = brain.precheck_plan(plan)
        self.assertFalse(result["ok"])
        self.assertEqual(result["problems"][0]["index"], 0)


class VerdictTest(unittest.TestCase):
    def test_normalize_qualified(self):
        verdict = brain.normalize_verdict({"qualified": True, "score": 120, "issues": "无"})
        self.assertTrue(verdict["qualified"])
        self.assertEqual(verdict["score"], 100)
        self.assertEqual(verdict["issues"], ["无"])

    def test_normalize_unqualified_legacy_keys(self):
        verdict = brain.normalize_verdict({"ok": False, "issues": ["空结果"]})
        self.assertFalse(verdict["qualified"])
        self.assertEqual(verdict["score"], 0)


class GuardTest(unittest.TestCase):
    def test_consult_question_exempt_from_keywords(self):
        plan = {"steps": [{"action": "consult", "params": {"question": "支付按钮点不动怎么办"}}]}
        guarded = brain.guard_plan(plan)
        self.assertEqual(len(guarded["plan"]["steps"]), 1)

    def test_dispatch_with_payment_word_rejected(self):
        plan = {"steps": [{"action": "dispatch", "params": {"target_id": "支付验证码"}}]}
        guarded = brain.guard_plan(plan)
        self.assertEqual(guarded["plan"]["steps"], [])
        self.assertEqual(guarded["rejected"][0]["reason"], "触碰红线关键词")

    def test_knowledge_ask_exempt_from_keywords(self):
        plan = {"steps": [{"action": "knowledge_ask", "params": {"question": "支付失败怎么排查"}}]}
        guarded = brain.guard_plan(plan)
        self.assertEqual(len(guarded["plan"]["steps"]), 1)

    def test_knowledge_ask_requires_question(self):
        self.assertFalse(brain.precheck("knowledge_ask", {"question": " "})["ok"])
        self.assertTrue(brain.precheck("knowledge_ask", {"question": "实名能改吗"})["ok"])


class StuckJobsTest(unittest.TestCase):
    def test_list_stuck_filters_by_age(self):
        db, tmp = _support.temp_store()
        try:
            hit = _support.sample_hit()
            db.enqueue_job(hit)
            job = db.list_jobs(state="pending")[0]
            db.mark_dispatched(job["_id"], "dev-1") if hasattr(db, "mark_dispatched") else None
            # 直接置为 dispatched 且 dispatched_at 很旧
            db.conn.execute(
                "UPDATE jobs SET state='dispatched', dispatched_at=?, updated_at=? WHERE id=?",
                (1_000, 1_000, job["_id"]),
            )
            self.assertEqual(len(db.list_stuck(60)), 1)
            self.assertEqual(db.list_stuck(0)[0]["_id"], job["_id"])
        finally:
            db.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
