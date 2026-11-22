"""推特定时队列测试：入队、原子认领、收敛、取消、时间解析、run-due。"""

from __future__ import annotations

import hashlib
import time
import unittest
from datetime import datetime, timedelta, timezone

import _support  # noqa: F401 - 注册 scripts 到 sys.path

import twitter as twitter_mod


class TwitterQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()
        self.now = int(time.time() * 1000)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_enqueue_and_list(self) -> None:
        future = self.now + 3600 * 1000
        post_id = self.db.enqueue_twitter_post("第一条推文", future, ["/tmp/a.png"])
        self.assertGreater(post_id, 0)
        posts = self.db.list_twitter_posts()
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["state"], "pending")
        self.assertEqual(posts[0]["media"], ["/tmp/a.png"])
        self.assertEqual(self.db.count_twitter_posts("pending"), 1)

    def test_empty_text_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.db.enqueue_twitter_post("   ", self.now)

    def test_claim_only_due_once(self) -> None:
        self.db.enqueue_twitter_post("到点", self.now - 1000)
        claimed = self.db.claim_due_twitter_post(self.now)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["state"], "posting")
        self.assertEqual(claimed["attempts"], 1)
        # 同一秒内不得重复认领
        self.assertIsNone(self.db.claim_due_twitter_post(self.now))

    def test_claim_skips_future(self) -> None:
        self.db.enqueue_twitter_post("未来", self.now + 600 * 1000)
        self.assertIsNone(self.db.claim_due_twitter_post(self.now))

    def test_finish_done_and_failed(self) -> None:
        first = self.db.enqueue_twitter_post("成功", self.now - 1000)
        self.db.claim_due_twitter_post(self.now)
        done = self.db.finish_twitter_post(first, "done", tweet_url="https://x.com/u/1")
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["tweet_url"], "https://x.com/u/1")

        second = self.db.enqueue_twitter_post("失败", self.now - 1000)
        self.db.claim_due_twitter_post(self.now)
        failed = self.db.finish_twitter_post(second, "failed", error="网络异常")
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["last_error"], "网络异常")
        # 非 posting 状态不可再收敛
        self.assertIsNone(self.db.finish_twitter_post(second, "done"))

    def test_cancel_pending_only(self) -> None:
        post_id = self.db.enqueue_twitter_post("取消我", self.now + 1000)
        cancelled = self.db.cancel_twitter_post(post_id)
        self.assertEqual(cancelled["state"], "cancelled")
        with self.assertRaises(ValueError):
            self.db.cancel_twitter_post(post_id)

    def test_cancel_posting_rejected(self) -> None:
        post_id = self.db.enqueue_twitter_post("发布中", self.now - 1000)
        self.db.claim_due_twitter_post(self.now)
        with self.assertRaises(ValueError):
            self.db.cancel_twitter_post(post_id)

    def test_recover_stale_marks_failed(self) -> None:
        self.db.enqueue_twitter_post("中断", self.now - 1000)
        self.db.claim_due_twitter_post(self.now)
        # 未超时不回收
        self.assertEqual(self.db.recover_stale_twitter(seconds=900, now=self.now), 0)
        later = self.now + 901 * 1000
        self.assertEqual(self.db.recover_stale_twitter(seconds=900, now=later), 1)
        posts = self.db.list_twitter_posts("failed")
        self.assertEqual(len(posts), 1)
        self.assertIn("人工核对", posts[0]["last_error"])

    def test_run_due_success_and_failure(self) -> None:
        self.db.enqueue_twitter_post("成功一", self.now - 2000)
        self.db.enqueue_twitter_post("失败一", self.now - 1000)
        calls = []

        def poster(text, media):
            calls.append(text)
            if text == "失败一":
                return {"ok": False, "error": "X 拒绝", "url": ""}
            return {"ok": True, "error": "", "url": "https://x.com/u/1"}

        results = twitter_mod.run_due(self.db, poster, limit=5, now=self.now)
        self.assertEqual(len(results), 2)
        self.assertEqual([item["ok"] for item in results], [True, False])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.db.count_twitter_posts("done"), 1)
        self.assertEqual(self.db.count_twitter_posts("failed"), 1)
        # 已发出的不得再次认领
        self.assertIsNone(self.db.claim_due_twitter_post(self.now))

    def test_run_due_poster_exception_marks_failed(self) -> None:
        self.db.enqueue_twitter_post("异常", self.now - 1000)

        def poster(text, media):
            raise RuntimeError("浏览器崩溃")

        results = twitter_mod.run_due(self.db, poster, limit=1, now=self.now)
        self.assertFalse(results[0]["ok"])
        self.assertIn("浏览器崩溃", results[0]["error"])
        self.assertEqual(self.db.count_twitter_posts("failed"), 1)


class TwitterScheduleParseTest(unittest.TestCase):
    def test_in_relative(self) -> None:
        now = datetime(2026, 11, 21, 10, 0, tzinfo=twitter_mod.CN_TZ)
        self.assertEqual(
            twitter_mod.parse_schedule(in_="30m", now=now),
            int((now + timedelta(minutes=30)).timestamp() * 1000),
        )
        self.assertEqual(
            twitter_mod.parse_schedule(in_="2h", now=now),
            int((now + timedelta(hours=2)).timestamp() * 1000),
        )

    def test_at_datetime(self) -> None:
        now = datetime(2026, 11, 21, 10, 0, tzinfo=twitter_mod.CN_TZ)
        expected = int(datetime(2026, 11, 22, 9, 30, tzinfo=twitter_mod.CN_TZ).timestamp() * 1000)
        self.assertEqual(twitter_mod.parse_schedule(at="2026-11-22 09:30", now=now), expected)
        self.assertEqual(twitter_mod.parse_schedule(at="2026-11-22T09:30", now=now), expected)

    def test_at_clock_rolls_to_tomorrow(self) -> None:
        now = datetime(2026, 11, 21, 10, 0, tzinfo=twitter_mod.CN_TZ)
        expected = int(datetime(2026, 11, 22, 9, 0, tzinfo=twitter_mod.CN_TZ).timestamp() * 1000)
        self.assertEqual(twitter_mod.parse_schedule(at="09:00", now=now), expected)

    def test_at_relative_day_prefix(self) -> None:
        now = datetime(2026, 11, 21, 10, 0, tzinfo=twitter_mod.CN_TZ)
        tomorrow = int(datetime(2026, 11, 22, 9, 0, tzinfo=twitter_mod.CN_TZ).timestamp() * 1000)
        day_after = int(datetime(2026, 11, 23, 9, 0, tzinfo=twitter_mod.CN_TZ).timestamp() * 1000)
        self.assertEqual(twitter_mod.parse_schedule(at="明天 09:00", now=now), tomorrow)
        self.assertEqual(twitter_mod.parse_schedule(at="后天 09:00", now=now), day_after)
        self.assertEqual(twitter_mod.parse_schedule(at="今天 11:00", now=now),
                         int(datetime(2026, 11, 21, 11, 0, tzinfo=twitter_mod.CN_TZ).timestamp() * 1000))

    def test_invalid(self) -> None:
        with self.assertRaises(ValueError):
            twitter_mod.parse_schedule(in_="soon")
        with self.assertRaises(ValueError):
            twitter_mod.parse_schedule(at="2026/13/40 99:99")
        with self.assertRaises(ValueError):
            twitter_mod.parse_schedule(at="2026-11-22 09:30", in_="1h")


class TwitterChromeCookieTest(unittest.TestCase):
    """Chrome cookie 解密与 Playwright 结构映射（不依赖真实 Chrome）。"""

    KEY = b"0123456789abcdef"
    HOST = ".x.com"

    def _encrypt(self, plaintext: bytes, prefix_hash: bool = True) -> bytes:
        from Crypto.Cipher import AES

        body = (hashlib.sha256(self.HOST.encode()).digest() if prefix_hash else b"") + plaintext
        pad = 16 - len(body) % 16
        body += bytes([pad]) * pad
        return b"v10" + AES.new(self.KEY, AES.MODE_CBC, b" " * 16).encrypt(body)

    def test_decrypt_with_host_hash_prefix(self) -> None:
        blob = self._encrypt(b"auth-token-value")
        self.assertEqual(twitter_mod.decrypt_cookie(blob, self.HOST, self.KEY), "auth-token-value")

    def test_decrypt_legacy_without_prefix(self) -> None:
        blob = self._encrypt("中文cookie".encode(), prefix_hash=False)
        self.assertEqual(twitter_mod.decrypt_cookie(blob, self.HOST, self.KEY), "中文cookie")

    def test_decrypt_plaintext_passthrough(self) -> None:
        self.assertEqual(twitter_mod.decrypt_cookie(b"plain", self.HOST, self.KEY), "plain")
        self.assertEqual(twitter_mod.decrypt_cookie(b"", self.HOST, self.KEY), "")

    def test_playwright_cookie_mapping(self) -> None:
        row = {
            "host_key": self.HOST,
            "name": "auth_token",
            "encrypted_value": self._encrypt(b"token"),
            "path": "/",
            "expires_utc": 13_400_000_000_000_000,  # 约 2425 年
            "is_secure": 1,
            "is_httponly": 1,
            "samesite": 1,
        }
        cookie = twitter_mod._playwright_cookie(row, self.KEY, now=1_700_000_000)
        self.assertEqual(cookie["name"], "auth_token")
        self.assertEqual(cookie["domain"], self.HOST)
        self.assertEqual(cookie["sameSite"], "Lax")
        self.assertEqual(cookie["expires"], int(13_400_000_000_000_000 / 1_000_000 - 11_644_473_600))
        self.assertTrue(cookie["httpOnly"] and cookie["secure"])

    def test_expired_cookie_skipped(self) -> None:
        row = {
            "host_key": self.HOST,
            "name": "old",
            "encrypted_value": self._encrypt(b"old"),
            "path": "/",
            "expires_utc": 13_000_000_000_000_000,
            "is_secure": 1,
            "is_httponly": 0,
            "samesite": -1,
        }
        self.assertIsNone(twitter_mod._playwright_cookie(row, self.KEY, now=9_999_999_999))


class TwitterPlanTest(unittest.TestCase):
    """大模型计划白名单：twitter_* 动作与参数预检。"""

    def setUp(self) -> None:
        import brain

        self.brain = brain

    def test_twitter_actions_whitelisted(self) -> None:
        for action in ("twitter_post", "twitter_schedule", "twitter_list", "twitter_status"):
            self.assertIn(action, self.brain.ALLOWED_ACTIONS)

    def test_guard_keeps_twitter_and_rejects_unknown(self) -> None:
        plan = {
            "intent": "发推",
            "steps": [
                {"action": "twitter_post", "params": {"text": "hello"}},
                {"action": "twitter_publish_now", "params": {}},
            ],
        }
        guarded = self.brain.guard_plan(plan)
        self.assertEqual([s["action"] for s in guarded["plan"]["steps"]], ["twitter_post"])
        self.assertEqual(len(guarded["rejected"]), 1)

    def test_precheck_requires_content(self) -> None:
        self.assertFalse(self.brain.precheck("twitter_post", {})["ok"])
        self.assertTrue(self.brain.precheck("twitter_post", {"text": "ok"})["ok"])
        self.assertFalse(self.brain.precheck("twitter_schedule", {"text": "ok"})["ok"])
        self.assertTrue(self.brain.precheck("twitter_schedule", {"text": "ok", "at": "09:00"})["ok"])
        self.assertTrue(self.brain.precheck("twitter_schedule", {"text": "ok", "in": "30m"})["ok"])


if __name__ == "__main__":
    unittest.main()
