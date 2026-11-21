"""P2 视觉兜底：无障碍树不可用时，用 OCR 文本块（含坐标）重定位目标。"""

from __future__ import annotations

import unittest

import _support
import gateway
import vision


def block(text, bounds=(0, 0, 200, 80), confidence=0.95):
    return {"text": text, "bounds": list(bounds) if bounds else None, "confidence": confidence}


BLOCKS = [
    block("我的", (0, 1800, 200, 1880)),
    block("会员购", (40, 300, 300, 380)),
    block("立即支付", (400, 1600, 700, 1680)),
]


class OcrRankingTest(unittest.TestCase):
    def test_best_block_and_index(self) -> None:
        result = vision.locate("会员购", BLOCKS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["schema"], "vision.v1")
        self.assertEqual(result["source"], "ocr")
        self.assertEqual(result["best"]["text"], "会员购")
        self.assertEqual(result["best"]["block_index"], 1)
        self.assertEqual(len(result["best"]["bounds"]), 4)

    def test_low_confidence_filtered(self) -> None:
        blocks = [block("会员购", confidence=0.2), block("我的")]
        result = vision.locate("会员购", blocks)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_match")

    def test_missing_bounds_filtered(self) -> None:
        blocks = [block("会员购", bounds=None), block("会员中心", (0, 0, 100, 50))]
        result = vision.locate("会员购", blocks)
        self.assertEqual(result["best"]["text"], "会员中心")

    def test_invalid_bounds_filtered(self) -> None:
        blocks = [block("会员购", bounds=(0, 0, 0, 0)), block("会员购", (5, 5, 105, 55))]
        result = vision.locate("会员购", blocks)
        self.assertEqual(result["best"]["block_index"], 1)

    def test_confidence_weighting(self) -> None:
        blocks = [block("会员购", (0, 0, 10, 10), 0.6), block("会员购", (20, 20, 30, 30), 0.99)]
        result = vision.locate("会员购", blocks)
        self.assertEqual(result["best"]["block_index"], 1)
        self.assertGreater(result["best"]["score"], 0.9)

    def test_no_blocks(self) -> None:
        self.assertFalse(vision.locate("会员购", [])["ok"])


class OcrGuardTest(unittest.TestCase):
    def test_forbidden_intent(self) -> None:
        result = vision.locate("确认支付", BLOCKS)
        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "guard")

    def test_payment_block_never_selected(self) -> None:
        result = vision.locate("支付", BLOCKS)
        self.assertFalse(result["ok"])


class VisionGatewayTest(unittest.TestCase):
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
        status, _ = _post(self.base, {"intent": "会员购", "blocks": BLOCKS})
        self.assertEqual(status, 401)

    def test_locate_ok(self) -> None:
        status, body = _post(self.base, {"intent": "会员购", "blocks": BLOCKS}, "tok")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["best"]["text"], "会员购")

    def test_missing_intent(self) -> None:
        status, _ = _post(self.base, {"blocks": BLOCKS}, "tok")
        self.assertEqual(status, 400)

    def test_missing_blocks(self) -> None:
        status, _ = _post(self.base, {"intent": "会员购", "blocks": []}, "tok")
        self.assertEqual(status, 400)


def _post(base: str, body: dict, token: str | None = None):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        base + "/vision/locate",
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
