"""P1 knowledge.ask 测试：答案结构化、引用、置信度、安全过滤、TTL 缓存。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import _support  # noqa: F401 - 注册 scripts 到 sys.path

import knowledge


class ParseAnswerTest(unittest.TestCase):
    def test_three_section_answer(self) -> None:
        raw = (
            "结论：会员购实名观演人可在开演前 48 小时前修改一次。\n"
            "依据：官方帮助中心「实名信息修改规则」；https://help.bilibili.com/xxx\n"
            "置信度：高"
        )
        parsed = knowledge.parse_answer(raw)
        self.assertIn("48 小时", parsed["answer"])
        self.assertGreaterEqual(len(parsed["citations"]), 1)
        self.assertEqual(parsed["citations"][0]["type"], "url")
        self.assertGreaterEqual(parsed["confidence"], 0.85)

    def test_plain_text_without_sections(self) -> None:
        parsed = knowledge.parse_answer("可能可以修改，建议咨询官方客服。")
        self.assertTrue(parsed["answer"].startswith("可能可以"))
        self.assertEqual(parsed["citations"], [])
        self.assertLessEqual(parsed["confidence"], 0.6)

    def test_numeric_confidence(self) -> None:
        parsed = knowledge.parse_answer("结论：可以改。\n依据：https://a.example/rule\n置信度：0.82")
        self.assertAlmostEqual(parsed["confidence"], 0.82, places=2)

    def test_low_confidence_word(self) -> None:
        parsed = knowledge.parse_answer("结论：可以改。\n置信度：低")
        self.assertAlmostEqual(parsed["confidence"], 0.4, places=2)

    def test_uncertainty_markers_lower_confidence(self) -> None:
        with_cite = knowledge.parse_answer("结论：可以改。\n依据：https://a.example/rule\n置信度：高")
        uncertain = knowledge.parse_answer(
            "结论：可能可以改。\n依据：https://a.example/rule\n置信度：高"
        )
        self.assertLess(uncertain["confidence"], with_cite["confidence"])

    def test_no_citation_caps_confidence(self) -> None:
        parsed = knowledge.parse_answer("结论：应该可以。\n置信度：高")
        self.assertLessEqual(parsed["confidence"], 0.6)

    def test_confidence_clamped(self) -> None:
        parsed = knowledge.parse_answer("结论：可以。\n置信度：1.0\n依据：https://a.example")
        self.assertLessEqual(parsed["confidence"], 0.95)


class SafetyTest(unittest.TestCase):
    def test_unsafe_actions_masked_and_flagged(self) -> None:
        raw = "结论：修改实名后立即提交订单并确认支付即可。\n置信度：高"
        parsed = knowledge.parse_answer(raw)
        self.assertTrue(parsed["unsafe_actions_detected"])
        self.assertNotIn("提交订单", parsed["answer"])
        self.assertNotIn("确认支付", parsed["answer"])
        self.assertLessEqual(parsed["confidence"], 0.3)

    def test_prompt_requests_sections_and_readonly(self) -> None:
        prompt = knowledge.build_prompt("会员购实名能改吗", app="bilibili")
        for token in ("结论", "依据", "置信度", "不要给可执行"):
            self.assertIn(token, prompt)
        self.assertIn("bilibili", prompt)


class EnvelopeTest(unittest.TestCase):
    def test_envelope_contract(self) -> None:
        env = knowledge.build_envelope("q", "结论：可以。\n依据：https://a.example\n置信度：中", app="bilibili")
        self.assertEqual(env["schema"], "knowledge.v1")
        self.assertEqual(env["side_effect"], "none")
        self.assertEqual(env["source"], "qianwen-app")
        self.assertFalse(env["cached"])
        for key in ("question", "app", "answer", "citations", "confidence", "asked_at"):
            self.assertIn(key, env)

    def test_cache_key_stable_and_app_scoped(self) -> None:
        a = knowledge.cache_key("问题", "bilibili")
        self.assertEqual(a, knowledge.cache_key("问题", "bilibili"))
        self.assertNotEqual(a, knowledge.cache_key("问题", "damai"))


class CacheStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_put_and_get(self) -> None:
        payload = {"schema": "knowledge.v1", "answer": "可以"}
        self.db.put_knowledge("k1", "bilibili", "q", payload, ttl_seconds=60)
        got = self.db.get_knowledge("k1")
        self.assertIsNotNone(got)
        self.assertTrue(got["cached"])
        self.assertEqual(got["answer"], "可以")

    def test_expired_is_miss(self) -> None:
        self.db.put_knowledge("k2", "", "q", {"answer": "x"}, ttl_seconds=1)
        later = int(__import__("time").time() * 1000) + 5000
        self.assertIsNone(self.db.get_knowledge("k2", now=later))

    def test_purge_removes_expired(self) -> None:
        self.db.put_knowledge("k3", "", "q", {"answer": "x"}, ttl_seconds=-1)
        result = self.db.purge()
        self.assertEqual(result["knowledge"], 1)


class KnowledgeAskTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MRA_STATE_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_ask_via_transport_and_cache_hit(self) -> None:
        fake = {"state": "done", "answer": "结论：可以改。\n依据：https://a.example\n置信度：高", "note": ""}
        with mock.patch("mra._consult_sync", return_value=fake) as transport:
            first = mra_ask({"question": "实名能改吗", "app": "bilibili"})
            second = mra_ask({"question": "实名能改吗", "app": "bilibili"})
        self.assertEqual(transport.call_count, 1)
        self.assertTrue(first["ok"])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertGreaterEqual(second["confidence"], 0.85)

    def test_ask_transport_failure(self) -> None:
        with mock.patch("mra._consult_sync", return_value={"state": "timeout", "answer": "", "note": "超时"}):
            result = mra_ask({"question": "q"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["note"], "超时")

    def test_ask_requires_question(self) -> None:
        with self.assertRaises(ValueError):
            mra_ask({"question": "   "})

    def test_no_cache_forces_transport(self) -> None:
        fake = {"state": "done", "answer": "结论：可以。", "note": ""}
        with mock.patch("mra._consult_sync", return_value=fake) as transport:
            mra_ask({"question": "q"})
            mra_ask({"question": "q", "no_cache": True})
        self.assertEqual(transport.call_count, 2)

    def test_consult_reuses_prior_answer_instead_of_failing(self) -> None:
        import hashlib

        import mra

        question = "会员购实名能改吗"
        fingerprint = hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]
        with mra.open_store() as db:
            db.enqueue_job(
                {
                    "adapter": "qianwen",
                    "task_id": "consult:{}".format(fingerprint),
                    "fingerprint": fingerprint,
                    "at": 0,
                    "target": {"target_id": "qianwen"},
                    "max_price": None,
                }
            )
            job = db.list_jobs()[0]
            db.add_result(job["_id"], "dev", "done", {"answer": "结论：可以改。\n置信度：高"})
        result = mra._consult_sync(question, timeout=1)
        self.assertEqual(result["state"], "done")
        self.assertTrue(result.get("reused"))
        self.assertIn("可以改", result["answer"])


    def test_consult_waits_on_inflight_job(self) -> None:
        """作业已入队但手机尚未回执时，继续等同一个 job，不立刻报幂等失败。"""
        import hashlib

        import mra

        question = "在途问题"
        fingerprint = hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]
        with mra.open_store() as db:
            db.enqueue_job(
                {
                    "adapter": "qianwen",
                    "task_id": "consult:{}".format(fingerprint),
                    "fingerprint": fingerprint,
                    "at": 0,
                    "target": {"target_id": "qianwen"},
                    "max_price": None,
                }
            )
        result = mra._consult_sync(question, timeout=1)
        self.assertEqual(result["state"], "timeout")
        self.assertNotIn("幂等去重", result.get("note", ""))


def mra_ask(params: dict) -> dict:
    """延迟导入 mra，避免测试收集阶段影响 sys.path。"""
    import mra

    return mra._knowledge_ask(params)


if __name__ == "__main__":
    unittest.main()
