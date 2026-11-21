"""P2 多设备并发：设备心跳、作业设备亲和、并发认领、掉线回收。"""

from __future__ import annotations

import threading
import time
import unittest

import _support
import gateway
import store as store_mod


def seed_job(db, task_id="t1", preferred_device="", at=None):
    return db.enqueue_job(
        {
            "adapter": "bilibili",
            "task_id": task_id,
            "fingerprint": "fp-" + task_id,
            "at": int(at or time.time() * 1000),
            "target": {"target_id": "x"},
            "max_price": None,
            "preferred_device": preferred_device,
        }
    )


class DeviceRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_touch_and_list_online(self) -> None:
        self.db.touch_device("dev-1", "polling")
        devices = self.db.list_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], "dev-1")
        self.assertTrue(devices[0]["online"])

    def test_offline_by_heartbeat_age(self) -> None:
        old = int(time.time() * 1000) - 120000
        self.db.touch_device("dev-1", "polling", at=old)
        devices = self.db.list_devices(offline_after=60)
        self.assertFalse(devices[0]["online"])

    def test_touch_upserts_last_seen(self) -> None:
        old = int(time.time() * 1000) - 120000
        self.db.touch_device("dev-1", "polling", at=old)
        self.db.touch_device("dev-1", "idle")
        devices = self.db.list_devices(offline_after=60)
        self.assertTrue(devices[0]["online"])
        self.assertEqual(devices[0]["last_state"], "idle")


class ClaimTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_device_affinity(self) -> None:
        seed_job(self.db, "t1", preferred_device="dev-1")
        seed_job(self.db, "t2")
        dev2 = self.db.claim_pending("dev-2", limit=10)
        self.assertEqual([job["task_id"] for job in dev2], ["t2"])
        dev1 = self.db.claim_pending("dev-1", limit=10)
        self.assertEqual([job["task_id"] for job in dev1], ["t1"])

    def test_claim_increments_attempts(self) -> None:
        seed_job(self.db, "t1")
        claimed = self.db.claim_pending("dev-1")[0]
        self.assertEqual(claimed["_attempts"], 1)

    def test_claim_atomic_across_instances(self) -> None:
        for index in range(6):
            seed_job(self.db, "t{}".format(index))
        other = store_mod.Store(self.db.path)
        claimed: list[list[dict]] = []
        barrier = threading.Barrier(2)

        def run(db) -> None:
            barrier.wait()
            claimed.append(db.claim_pending("dev-" + str(id(db) % 10), limit=6))

        threads = [threading.Thread(target=run, args=(conn,)) for conn in (self.db, other)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        other.close()
        ids = [job["_id"] for batch in claimed for job in batch]
        self.assertEqual(len(ids), 6)
        self.assertEqual(len(set(ids)), 6)

    def test_does_not_exceed_limit(self) -> None:
        for index in range(5):
            seed_job(self.db, "t{}".format(index))
        self.assertEqual(len(self.db.claim_pending("dev-1", limit=2)), 2)


class RequeueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_stale_device_job_requeued(self) -> None:
        seed_job(self.db, "t1")
        self.db.claim_pending("dev-1")
        old = int(time.time() * 1000) - 300000
        self.db.touch_device("dev-1", "polling", at=old)
        result = self.db.requeue_stale(device_ttl_seconds=60)
        self.assertEqual(result["reset"], [1])
        self.assertEqual(self.db.get_job(1)["_state"], "pending")

    def test_fresh_device_not_requeued(self) -> None:
        seed_job(self.db, "t1")
        self.db.claim_pending("dev-1")
        self.db.touch_device("dev-1", "polling")
        result = self.db.requeue_stale(device_ttl_seconds=60)
        self.assertEqual(result["reset"], [])
        self.assertEqual(self.db.get_job(1)["_state"], "dispatched")

    def test_order_evidence_goes_unknown(self) -> None:
        seed_job(self.db, "t1")
        self.db.claim_pending("dev-1")
        self.db.add_result(1, "dev-1", "done", {"order_id": "B123"})
        old = int(time.time() * 1000) - 300000
        self.db.touch_device("dev-1", "polling", at=old)
        result = self.db.requeue_stale(device_ttl_seconds=60)
        self.assertEqual(result["order_unknown"], [1])
        self.assertEqual(self.db.get_job(1)["_state"], "order_unknown")

    def test_attempts_exhausted_fails(self) -> None:
        seed_job(self.db, "t1")
        old = int(time.time() * 1000) - 300000
        result = {}
        for _ in range(2):
            self.db.claim_pending("dev-1")
            self.db.touch_device("dev-1", "polling", at=old)
            result = self.db.requeue_stale(device_ttl_seconds=60, max_attempts=2)
        self.assertEqual(result["failed"], [1])
        self.assertEqual(self.db.get_job(1)["_state"], "failed")


class DeviceGatewayTest(unittest.TestCase):
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

    def test_commands_registers_device(self) -> None:
        status, _ = _get(self.base, "/commands?device_id=dev-9", "tok")
        self.assertEqual(status, 200)
        self.assertTrue(self.db.list_devices()[0]["online"])

    def test_commands_requeues_stale_job(self) -> None:
        seed_job(self.db, "t1")
        _get(self.base, "/commands?device_id=dev-1", "tok")
        old = int(time.time() * 1000) - 300000
        self.db.touch_device("dev-1", "polling", at=old)
        status, body = _get(self.base, "/commands?device_id=dev-2", "tok")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["jobs"]), 1)
        self.assertEqual(self.db.get_job(1)["_state"], "dispatched")
        self.assertEqual(self.db.get_job(1)["_device_id"], "dev-2")

    def test_results_updates_heartbeat(self) -> None:
        seed_job(self.db, "t1")
        self.db.claim_pending("dev-1")
        _post(self.base, {"job_id": 1, "device_id": "dev-1", "state": "ok", "detail": {}}, "tok")
        self.assertTrue(self.db.list_devices()[0]["online"])


def _get(base: str, path: str, token: str):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(base + path)
    req.add_header("X-MRA-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _post(base: str, body: dict, token: str):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        base + "/results",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    req.add_header("X-MRA-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


if __name__ == "__main__":
    unittest.main()
