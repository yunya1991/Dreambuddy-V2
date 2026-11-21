"""网关测试（含 FakeAgent 全链路）：鉴权、认领派发、回执落库。"""

from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request

import _support
import gateway


def _get(base: str, path: str, token: str | None = None) -> tuple[int, dict]:
    url = base + path
    req = urllib.request.Request(url)
    if token:
        req.add_header("X-MRA-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _post(base: str, path: str, body: dict, token: str | None = None) -> tuple[int, dict]:
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


class GatewayTest(unittest.TestCase):
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

    def test_health_no_token(self) -> None:
        status, body = _get(self.base, "/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_commands_requires_token(self) -> None:
        status, _ = _get(self.base, "/commands?device_id=dev-1")
        self.assertEqual(status, 401)

    def test_full_loop_fake_agent(self) -> None:
        # 入队一个作业
        self.db.enqueue_job(_support.sample_hit())

        # FakeAgent 拉取
        status, body = _get(self.base, "/commands?device_id=dev-1", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)
        command = body["jobs"][0]
        self.assertEqual(command["stop_before"], "payment")
        job_id = command["job_id"]
        self.assertEqual(self.db.get_job(job_id)["_state"], "dispatched")

        # FakeAgent 回执 ok
        status, body = _post(
            self.base,
            "/results",
            {"job_id": job_id, "device_id": "dev-1", "state": "ok", "detail": {"order_ref": "R1"}},
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["state"], "done")
        self.assertEqual(self.db.get_job(job_id)["_state"], "done")

    def test_results_requires_token(self) -> None:
        self.db.enqueue_job(_support.sample_hit())
        job = self.db.list_jobs()[0]
        status, _ = _post(self.base, "/results", {"job_id": job["_id"], "state": "ok"})
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
