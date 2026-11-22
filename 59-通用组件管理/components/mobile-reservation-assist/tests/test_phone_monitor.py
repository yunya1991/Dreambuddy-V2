"""埋点与监控测试：记录、规则检测、千问接管接线（不连真机、不调大模型）。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

import _support  # noqa: F401

import mra
import phone_monitor


class MonitorBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get("MRA_STATE_DIR")
        os.environ["MRA_STATE_DIR"] = self.tmp

    def tearDown(self) -> None:
        if self.old is None:
            os.environ.pop("MRA_STATE_DIR", None)
        else:
            os.environ["MRA_STATE_DIR"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)


class RecordTailTest(MonitorBase):
    def test_record_and_tail(self) -> None:
        phone_monitor.record("s1", "xiaohongshu", True, trace_id="t1", page_text="首页")
        events = phone_monitor.tail(10, "t1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "xiaohongshu")
        self.assertTrue(events[0]["ok"])

    def test_tail_filters_trace(self) -> None:
        phone_monitor.record("s1", "a", True, trace_id="t1")
        phone_monitor.record("s2", "b", True, trace_id="t2")
        self.assertEqual([item["trace_id"] for item in phone_monitor.tail(10, "t2")], ["t2"])

    def test_summary(self) -> None:
        phone_monitor.record("s1", "a", True, trace_id="t1")
        phone_monitor.record("s1", "b", False, trace_id="t1")
        info = phone_monitor.summary(phone_monitor.tail(10))
        self.assertEqual(info["events"], 2)
        self.assertEqual(info["failed"], 1)


class DetectTest(MonitorBase):
    def test_no_anomaly(self) -> None:
        events = [
            {"trace_id": "t", "action": "a", "ok": True, "page_text": "首页"},
            {"trace_id": "t", "action": "b", "ok": True, "page_text": "详情"},
        ]
        self.assertEqual(phone_monitor.detect(events), [])

    def test_repeat_failure(self) -> None:
        events = [
            {"trace_id": "t", "action": "tap", "ok": False, "page_text": "A"},
            {"trace_id": "t", "action": "tap", "ok": False, "page_text": "B"},
        ]
        rules = [item["rule"] for item in phone_monitor.detect(events)]
        self.assertIn("repeat_failure", rules)

    def test_terminal_failure(self) -> None:
        events = [{"trace_id": "t", "action": "douyin_publish", "ok": False, "error": "无按钮"}]
        rules = [item["rule"] for item in phone_monitor.detect(events)]
        self.assertIn("terminal_failure", rules)

    def test_timeout(self) -> None:
        events = [{"trace_id": "t", "action": "jianying", "ok": False, "state": "timeout"}]
        rules = [item["rule"] for item in phone_monitor.detect(events)]
        self.assertIn("timeout", rules)

    def test_page_stuck(self) -> None:
        events = [
            {"trace_id": "t", "action": "a", "ok": False, "page_text": "同一页"},
            {"trace_id": "t", "action": "b", "ok": False, "page_text": "同一页"},
            {"trace_id": "t", "action": "c", "ok": False, "page_text": "同一页"},
        ]
        rules = [item["rule"] for item in phone_monitor.detect(events)]
        self.assertIn("page_stuck", rules)

    def test_page_empty(self) -> None:
        events = [
            {"trace_id": "t", "action": "a", "ok": True, "page_text": ""},
            {"trace_id": "t", "action": "b", "ok": True, "page_text": ""},
        ]
        rules = [item["rule"] for item in phone_monitor.detect(events)]
        self.assertIn("page_empty", rules)

    def test_pkg_does_not_trigger_page_empty(self) -> None:
        events = [
            {"trace_id": "cli", "action": "pkg", "ok": True, "page_text": ""},
            {"trace_id": "cli", "action": "open_app", "ok": True, "page_text": ""},
        ]
        rules = [item["rule"] for item in phone_monitor.detect(events)]
        self.assertNotIn("page_empty", rules)

    def test_anomaly_has_evidence(self) -> None:
        events = [{"trace_id": "t", "action": "douyin_publish", "ok": False, "error": "x"}]
        anomaly = phone_monitor.detect(events)[0]
        self.assertTrue(anomaly["evidence"])
        self.assertEqual(anomaly["trace_id"], "t")


class WatchCommandTest(MonitorBase):
    def test_clean_returns_ok(self) -> None:
        phone_monitor.record("s", "jianying", True, trace_id="t1", page_text="首页")
        self.assertEqual(mra.cmd_watch(mra.build_parser().parse_args(["watch"])), mra.EXIT_OK)

    def test_anomaly_triggers_guard(self) -> None:
        phone_monitor.record("s", "jianying", False, trace_id="t2", error="卡住")
        phone_monitor.record("s", "jianying", False, trace_id="t2", error="仍卡住")
        guard = mock.Mock(return_value={"ok": True, "rounds": 1, "transcript": []})
        with mock.patch.object(mra, "_constitution_guard", guard):
            code = mra.cmd_watch(mra.build_parser().parse_args(["watch", "--heal", "--limit", "20"]))
        self.assertEqual(code, mra.EXIT_GATE)
        guard.assert_called_once()

    def test_no_heal_skips_guard(self) -> None:
        phone_monitor.record("s", "jianying", False, trace_id="t3", error="卡住")
        phone_monitor.record("s", "jianying", False, trace_id="t3", error="仍卡住")
        guard = mock.Mock()
        with mock.patch.object(mra, "_constitution_guard", guard):
            mra.cmd_watch(mra.build_parser().parse_args(["watch"]))
        guard.assert_not_called()

    def test_verify_uses_brain(self) -> None:
        fake = mock.Mock()
        fake.available.return_value = True
        fake.verify.return_value = {"qualified": True, "reason": ""}
        with mock.patch.object(mra, "brain", fake):
            code = mra.cmd_watch(mra.build_parser().parse_args(["watch", "--verify", "发布抖音视频"]))
        self.assertEqual(code, mra.EXIT_OK)
        fake.verify.assert_called_once()

    def test_verify_without_brain(self) -> None:
        fake = mock.Mock()
        fake.available.return_value = False
        with mock.patch.object(mra, "brain", fake):
            code = mra.cmd_watch(mra.build_parser().parse_args(["watch", "--verify", "发布抖音视频"]))
        self.assertEqual(code, mra.EXIT_GATE)


class TraceJobTest(MonitorBase):
    def test_run_phone_job_records_event(self) -> None:
        hit = {"adapter": "jianying", "task_id": "video:make:1"}
        with mock.patch.object(mra.phone_driver, "use_local_driver", return_value=True), \
                mock.patch.object(mra.phone_driver, "run_local_job", return_value={"state": "done", "detail": {}}):
            mra._run_phone_job(hit, timeout=5)
        events = phone_monitor.tail(5, "video:make:1")
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["ok"])
        self.assertEqual(events[0]["action"], "jianying")

    def test_pending_human_is_not_failure(self) -> None:
        hit = {"adapter": "jianying", "task_id": "video:make:2"}
        with mock.patch.object(mra.phone_driver, "use_local_driver", return_value=True), \
                mock.patch.object(mra.phone_driver, "run_local_job", return_value={"state": "pending_human", "detail": {}}):
            mra._run_phone_job(hit, timeout=5)
        self.assertTrue(phone_monitor.tail(5, "video:make:2")[0]["ok"])


if __name__ == "__main__":
    unittest.main()
