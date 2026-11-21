"""P1 mra explore 测试：录制会话 + 快照 + 适配器草案（只含 L3 登记工具）。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import _support
import explore
import gateway
import phone_tools


def node(text="", desc="", cls="TextView", clickable=False, bounds=(0, 0, 100, 40)):
    return {
        "cls": cls,
        "text": text,
        "desc": desc,
        "clickable": clickable,
        "bounds": list(bounds),
    }


def snap(seq, nodes, pkg="tv.danmaku.bili", activity=".MainActivity", text=""):
    return {
        "seq": seq,
        "package": pkg,
        "activity": activity,
        "page_text": text or " | ".join(n["text"] for n in nodes if n["text"]),
        "screenshot": "agent_debug/explore_{}.png".format(seq),
        "nodes": nodes,
    }


def fixture_snapshots():
    return [
        snap(1, [node("会员购", clickable=True), node("我的")], activity=".MainActivity"),
        snap(
            2,
            [node("搜索"), node("周杰伦", cls="EditText"), node("演出")],
            activity=".SearchActivity",
            text="搜索 周杰伦 演出",
        ),
        snap(
            3,
            [node("2026-12-01 19:30", clickable=True), node("上海 梅赛德斯")],
            activity=".DetailActivity",
            text="2026-12-01 19:30 上海 梅赛德斯",
        ),
        snap(
            4,
            [node("看台 680元", clickable=True), node("内场 1280元", clickable=True)],
            activity=".TierActivity",
            text="看台 680元 内场 1280元",
        ),
        snap(
            5,
            [node("确认订单", clickable=True), node("立即支付", clickable=True)],
            activity=".OrderActivity",
            text="确认订单 立即支付 380 元",
        ),
    ]


class StoreExploreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_create_get_active_stop(self) -> None:
        exp_id = self.db.create_exploration("bilibili", "买演唱会票", "dev-1")
        exp = self.db.get_exploration(exp_id)
        self.assertEqual(exp["state"], "recording")
        self.assertEqual(self.db.get_active_exploration("dev-1")["_id"], exp_id)
        self.db.stop_exploration(exp_id)
        self.assertIsNone(self.db.get_active_exploration("dev-1"))
        self.assertEqual(self.db.get_exploration(exp_id)["state"], "stopped")

    def test_snapshot_seq_and_order(self) -> None:
        exp_id = self.db.create_exploration("bilibili", "g")
        first = self.db.add_snapshot(exp_id, package="p", activity="a", page_text="t", nodes=[node("x")])
        second = self.db.add_snapshot(exp_id, package="p", activity="a", page_text="t2", nodes=[])
        self.assertEqual(first["seq"], 1)
        self.assertEqual(second["seq"], 2)
        rows = self.db.list_snapshots(exp_id)
        self.assertEqual([r["seq"] for r in rows], [1, 2])
        self.assertTrue(rows[0]["signature"])

    def test_duplicate_signature_flagged(self) -> None:
        exp_id = self.db.create_exploration("bilibili", "g")
        self.db.add_snapshot(exp_id, package="p", activity="a", page_text="t", nodes=[node("x")])
        dup = self.db.add_snapshot(exp_id, package="p", activity="a", page_text="t", nodes=[node("x")])
        self.assertTrue(dup["duplicate"])

    def test_list_and_state_filter(self) -> None:
        a = self.db.create_exploration("bilibili", "g1")
        self.db.create_exploration("damai", "g2")
        self.db.stop_exploration(a)
        self.assertEqual(len(self.db.list_explorations()), 2)
        self.assertEqual(len(self.db.list_explorations("stopped")), 1)


class SignatureTest(unittest.TestCase):
    def test_stable_and_sensitive(self) -> None:
        a = explore.page_signature("p", "a", [node("会员购")])
        self.assertEqual(a, explore.page_signature("p", "a", [node("会员购")]))
        self.assertNotEqual(a, explore.page_signature("p", "a", [node("会员购", "desc")]))


class DraftTest(unittest.TestCase):
    def setUp(self) -> None:
        self.exploration = {"_id": 7, "app": "bilibili", "goal": "买周杰伦演唱会门票", "state": "stopped"}
        self.snapshots = fixture_snapshots()

    def test_steps_inferred_in_order(self) -> None:
        draft = explore.build_draft(self.exploration, self.snapshots)
        actions = [step["action"] for step in draft["steps"]]
        self.assertEqual(actions[0], "open_app")
        self.assertIn("search", actions)
        self.assertIn("select_session", actions)
        self.assertIn("select_tier", actions)
        self.assertEqual(actions[-2:], ["goto_order_page", "stop"])
        self.assertTrue(draft["ready"])

    def test_all_steps_use_registered_tools(self) -> None:
        draft = explore.build_draft(self.exploration, self.snapshots)
        for step in draft["steps"]:
            self.assertIn(step["action"], phone_tools.TOOLS)
            self.assertFalse(phone_tools.TOOLS[step["action"]].forbidden)

    def test_steps_carry_selector_evidence(self) -> None:
        draft = explore.build_draft(self.exploration, self.snapshots)
        search = [s for s in draft["steps"] if s["action"] == "search"][0]
        self.assertEqual(search["evidence"]["selector"]["type"], "text")
        self.assertEqual(search["params"]["value"], "周杰伦")

    def test_assertions_follow_snapshots(self) -> None:
        draft = explore.build_draft(self.exploration, self.snapshots)
        self.assertEqual(len(draft["assertions"]), len(self.snapshots))
        for item in draft["assertions"]:
            self.assertTrue(item["signature"])
            self.assertTrue(item["expect"])

    def test_payment_nodes_never_become_steps(self) -> None:
        draft = explore.build_draft(self.exploration, self.snapshots)
        blob = "".join(str(step) for step in draft["steps"])
        for token in ("支付", "提交订单", "锁座"):
            self.assertNotIn(token, blob)
        self.assertTrue(any("支付" in w for w in draft["warnings"]))

    def test_empty_snapshots_not_ready(self) -> None:
        draft = explore.build_draft(self.exploration, [])
        self.assertFalse(draft["ready"])
        self.assertTrue(draft["warnings"])

    def test_duplicate_snapshots_skipped(self) -> None:
        same = [self.snapshots[0], dict(self.snapshots[0], seq=2)]
        draft = explore.build_draft(self.exploration, same)
        self.assertEqual(len(draft["assertions"]), 1)


class RenderTest(unittest.TestCase):
    def test_render_adapter_compiles_and_is_safe(self) -> None:
        draft = explore.build_draft(
            {"_id": 7, "app": "bilibili", "goal": "买票", "state": "stopped"}, fixture_snapshots()
        )
        source = explore.render_adapter(draft)
        compile(source, "draft.py", "exec")
        self.assertIn("BasePhoneAdapter", source)
        self.assertIn("build_step", source)
        self.assertNotIn("payment", source.lower())
        self.assertNotIn("submit_order", source)


class ExploreGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()
        self.token = "test-token"
        self.server, self.thread = gateway.serve_in_thread(self.db, self.token, port=0)
        host, port = self.server.server_address[:2]
        self.base = "http://{}:{}".format(host, port)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.db.close()
        self._tmp.cleanup()

    def test_explore_requires_token(self) -> None:
        status, _ = _support_http_get(self.base, "/explore?device_id=dev-1")
        self.assertEqual(status, 401)

    def test_active_exploration_returned(self) -> None:
        exp_id = self.db.create_exploration("bilibili", "g", "dev-1")
        status, body = _support_http_get(self.base, "/explore?device_id=dev-1", self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body["exploration"]["_id"], exp_id)
        self.assertGreaterEqual(body["interval_ms"], 500)

    def test_snapshot_upload(self) -> None:
        exp_id = self.db.create_exploration("bilibili", "g", "dev-1")
        status, body = _support_http_post(
            self.base,
            "/snapshots",
            {"exploration_id": exp_id, "device_id": "dev-1", "package": "p",
             "activity": "a", "page_text": "搜索", "nodes": [node("搜索")]},
            self.token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["seq"], 1)
        self.assertEqual(len(self.db.list_snapshots(exp_id)), 1)

    def test_snapshot_requires_exploration(self) -> None:
        status, _ = _support_http_post(
            self.base, "/snapshots", {"device_id": "dev-1", "nodes": []}, self.token
        )
        self.assertEqual(status, 400)

    def test_snapshot_rejected_after_stop(self) -> None:
        exp_id = self.db.create_exploration("bilibili", "g")
        self.db.stop_exploration(exp_id)
        status, body = _support_http_post(
            self.base, "/snapshots", {"exploration_id": exp_id, "nodes": []}, self.token
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "exploration_not_recording")


class ExploreCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MRA_STATE_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_start_stop_draft_flow(self) -> None:
        import mra

        started = mra._explore_start({"app": "bilibili", "goal": "买票", "device_id": "dev-1"})
        exp_id = started["exploration"]["_id"]
        for item in fixture_snapshots():
            mra._explore_snapshot(exp_id, item)
        stopped = mra._explore_stop({"exploration_id": exp_id})
        self.assertEqual(stopped["snapshots"], 5)
        draft = mra._explore_draft({"exploration_id": exp_id, "out": ""})
        self.assertTrue(draft["ready"])
        self.assertEqual(draft["steps"][0]["action"], "open_app")

    def test_draft_requires_snapshots(self) -> None:
        import mra

        exp_id = mra._explore_start({"app": "bilibili", "goal": "买票"})["exploration"]["_id"]
        mra._explore_stop({"exploration_id": exp_id})
        with self.assertRaises(ValueError):
            mra._explore_draft({"exploration_id": exp_id})

    def test_start_reuses_active_recording(self) -> None:
        import mra

        first = mra._explore_start({"app": "bilibili", "goal": "买票", "device_id": "dev-1"})
        second = mra._explore_start({"app": "bilibili", "goal": "买票", "device_id": "dev-1"})
        self.assertTrue(second["reused"])
        self.assertEqual(first["exploration"]["_id"], second["exploration"]["_id"])


def _support_http_get(base: str, path: str, token: str | None = None):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(base + path)
    if token:
        req.add_header("X-MRA-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _support_http_post(base: str, path: str, body: dict, token: str | None = None):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("X-MRA-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


if __name__ == "__main__":
    unittest.main()
