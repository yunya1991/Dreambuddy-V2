"""CLI 宪法测试：问千问 → 大模型验证 → 仍失败继续问，以及发布链路的自动接入。"""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock

import _support  # noqa: F401

import mra

NOTE = {"title": "标题", "body": "正文"}


def _note_file() -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(NOTE, handle, ensure_ascii=False)
    handle.close()
    return handle.name


def _fake_brain(steps):
    fake = mock.Mock()
    fake.available.return_value = True
    fake.plan.return_value = {"intent": "排障", "steps": steps}
    fake.guard_plan.return_value = {"plan": {"intent": "排障", "steps": steps}, "rejected": []}
    return fake


class ConstitutionGuardTest(unittest.TestCase):
    def test_first_round_resolves(self) -> None:
        with mock.patch.object(mra, "_consult_sync", return_value={"state": "done", "answer": "点击右上角导出"}), \
                mock.patch.object(mra, "brain", _fake_brain([{"action": "tap", "params": {"text": "导出"}}])):
            result = mra._constitution_guard("video_make", "没找到导出按钮")
        self.assertTrue(result["ok"])
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(result["steps"][0]["action"], "tap")

    def test_retries_after_verification_fails(self) -> None:
        answered = []

        def consult(question, timeout=150):
            answered.append(question)
            return {"state": "done", "answer": "再试试重启 App"}

        with mock.patch.object(mra, "_consult_sync", side_effect=consult), \
                mock.patch.object(mra, "brain", _fake_brain([])):
            result = mra._constitution_guard("xhs_chain", "发布页没有按钮", rounds=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(len(answered), 2)
        # 第二轮提问必须带上上一轮建议与验证结论
        self.assertIn("上一轮千问建议", answered[1])
        self.assertIn("大模型验证结论", answered[1])

    def test_stops_when_qianwen_empty(self) -> None:
        with mock.patch.object(mra, "_consult_sync", return_value={"state": "timeout", "answer": "", "note": "超时"}):
            result = mra._constitution_guard("video_make", "卡住", rounds=3)
        self.assertFalse(result["ok"])
        self.assertEqual(result["rounds"], 1)

    def test_without_brain_advice_is_unusable(self) -> None:
        fake = mock.Mock()
        fake.available.return_value = False
        with mock.patch.object(mra, "_consult_sync", return_value={"state": "done", "answer": "重启手机"}), \
                mock.patch.object(mra, "brain", fake):
            result = mra._constitution_guard("video_make", "卡住", rounds=1)
        self.assertFalse(result["ok"])
        self.assertIn("大模型未配置", json.dumps(result, ensure_ascii=False))

    def test_transcript_records_every_round(self) -> None:
        with mock.patch.object(mra, "_consult_sync", return_value={"state": "done", "answer": "建议 A"}), \
                mock.patch.object(mra, "brain", _fake_brain([{"action": "screen", "params": {}}])):
            result = mra._constitution_guard("publish_all", "失败")
        sources = [item["source"] for item in result["transcript"]]
        self.assertEqual(sources, ["qianwen", "verify"])


class PublishConstitutionWiringTest(unittest.TestCase):
    def test_failure_triggers_guard(self) -> None:
        path = _note_file()
        guard = mock.Mock(return_value={"ok": True, "rounds": 1, "transcript": []})
        with mock.patch.object(mra, "_make_video", return_value={"state": "failed"}), \
                mock.patch.object(mra, "_constitution_guard", guard):
            code = mra.cmd_publish(mra.build_parser().parse_args(["publish", "--to", "douyin", "--note", path]))
        self.assertEqual(code, mra.EXIT_GATE)
        guard.assert_called_once()

    def test_no_heal_disables_guard(self) -> None:
        path = _note_file()
        guard = mock.Mock()
        with mock.patch.object(mra, "_make_video", return_value={"state": "failed"}), \
                mock.patch.object(mra, "_constitution_guard", guard):
            mra.cmd_publish(
                mra.build_parser().parse_args(["publish", "--to", "douyin", "--note", path, "--no-heal"])
            )
        guard.assert_not_called()

    def test_success_does_not_trigger_guard(self) -> None:
        path = _note_file()
        guard = mock.Mock()
        with mock.patch.object(mra, "_make_video", return_value={"state": "done", "video": "v.mp4"}), \
                mock.patch.object(mra, "_constitution_guard", guard):
            code = mra.cmd_publish(mra.build_parser().parse_args(["publish", "--to", "douyin", "--note", path]))
        self.assertEqual(code, 0)
        guard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
