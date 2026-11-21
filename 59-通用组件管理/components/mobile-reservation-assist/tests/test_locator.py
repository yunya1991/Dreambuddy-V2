"""P2 本地小模型定位兜底：选择器失效时按意图在节点树中重定位（规则优先，模型复核）。"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import _support
import gateway
import locator


def node(text="", desc="", cls="TextView", clickable=True, bounds=(0, 0, 200, 80)):
    return {"cls": cls, "text": text, "desc": desc, "clickable": clickable, "bounds": list(bounds)}


NODES = [
    node("我的"),
    node("会员购"),
    node("周杰伦 2026 巡回演唱会"),
    node("看台 680元"),
    node("立即支付", clickable=True),
]


class RuleRankingTest(unittest.TestCase):
    def test_exact_text_wins(self) -> None:
        result = locator.locate("会员购", NODES, use_model=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "rules")
        self.assertEqual(result["best"]["text"], "会员购")
        self.assertEqual(result["schema"], "locator.v1")

    def test_contains_beats_character_overlap(self) -> None:
        result = locator.locate("周杰伦演唱会", NODES, use_model=False)
        self.assertTrue(result["ok"])
        self.assertIn("周杰伦", result["best"]["text"])

    def test_non_clickable_penalised(self) -> None:
        nodes = [node("确认", clickable=False), node("确认订单页", clickable=True)]
        result = locator.locate("确认", nodes, use_model=False)
        self.assertTrue(result["best"]["clickable"])
        self.assertEqual(result["best"]["text"], "确认订单页")

    def test_no_match(self) -> None:
        result = locator.locate("完全不存在的东西", NODES, use_model=False)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["best"])
        self.assertEqual(result["reason"], "no_match")

    def test_best_carries_bounds_for_click(self) -> None:
        result = locator.locate("会员购", NODES, use_model=False)
        self.assertEqual(len(result["best"]["bounds"]), 4)
        self.assertGreaterEqual(result["best"]["index"], 0)

    def test_candidates_capped(self) -> None:
        result = locator.locate("看台", NODES, use_model=False)
        self.assertLessEqual(len(result["candidates"]), locator.TOP_N)


class GuardTest(unittest.TestCase):
    def test_forbidden_intent_rejected(self) -> None:
        for intent in ("确认支付", "提交订单", "锁座"):
            result = locator.locate(intent, NODES, use_model=False)
            self.assertFalse(result["ok"])
            self.assertEqual(result["source"], "guard")
            self.assertEqual(result["reason"], "forbidden_intent")
            self.assertIsNone(result["best"])

    def test_node_text_forbidden_not_selected(self) -> None:
        nodes = [node("立即支付"), node("我的")]
        result = locator.locate("支付", nodes, use_model=False)
        self.assertFalse(result["ok"])


class ModelFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clean = mock.patch.dict(
            os.environ,
            {"MRA_LOCAL_MODEL_URL": "", "MRA_LOCAL_MODEL_NAME": "", "MRA_LOCAL_MODEL_KEY": ""},
        )
        self.clean.start()

    def tearDown(self) -> None:
        self.clean.stop()

    def test_model_pick_used_when_valid(self) -> None:
        with mock.patch("locator._model_pick", return_value=2):
            result = locator.locate("那个演唱会", NODES)
        self.assertEqual(result["source"], "model")
        self.assertEqual(result["best"]["index"], 2)

    def test_model_pick_forbidden_falls_back_to_rules(self) -> None:
        with mock.patch("locator._model_pick", return_value=4):
            result = locator.locate("演唱会", NODES)
        self.assertEqual(result["source"], "rules")
        self.assertNotEqual(result["best"]["text"], "立即支付")

    def test_model_invalid_index_falls_back(self) -> None:
        with mock.patch("locator._model_pick", return_value=99):
            result = locator.locate("会员购", NODES)
        self.assertEqual(result["source"], "rules")

    def test_model_unconfigured_returns_none(self) -> None:
        self.assertIsNone(locator._model_pick("会员购", NODES))

    def test_model_exception_never_breaks_locate(self) -> None:
        with mock.patch("locator._model_pick", side_effect=RuntimeError("boom")):
            result = locator.locate("会员购", NODES, use_model=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "rules")


class LocateGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()
        self.server, self.thread = gateway.serve_in_thread(self.db, "tok", port=0)
        host, port = self.server.server_address[:2]
        self.base = "http://{}:{}".format(host, port)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.db.close()
        self._tmp.cleanup()

    def test_requires_token(self) -> None:
        status, _ = _post(self.base, {"intent": "会员购", "nodes": NODES})
        self.assertEqual(status, 401)

    def test_locate_ok(self) -> None:
        status, body = _post(
            self.base, {"intent": "会员购", "nodes": NODES, "use_model": False}, "tok"
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["best"]["text"], "会员购")

    def test_missing_intent(self) -> None:
        status, _ = _post(self.base, {"nodes": NODES}, "tok")
        self.assertEqual(status, 400)

    def test_missing_nodes(self) -> None:
        status, _ = _post(self.base, {"intent": "会员购", "nodes": []}, "tok")
        self.assertEqual(status, 400)


def _post(base: str, body: dict, token: str | None = None):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        base + "/locate",
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
