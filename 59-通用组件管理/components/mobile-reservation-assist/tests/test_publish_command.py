"""一键发布命令测试：双平台串联与单平台发布（不连接手机、不访问网络）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock

import _support  # noqa: F401

import mra

NOTE = {"title": "黄金理财破净？拆解下跌底层逻辑", "body": "正文", "topics": ["黄金理财"]}


def _note_file() -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(NOTE, handle, ensure_ascii=False)
    handle.close()
    return handle.name


class PublishCommandTest(unittest.TestCase):
    def test_parser_defaults(self) -> None:
        args = mra.build_parser().parse_args(["publish"])
        self.assertEqual(args.to, "all")
        self.assertFalse(args.publish)
        self.assertEqual(args.timeout, 900)

    def test_douyin_only_uses_video_chain(self) -> None:
        path = _note_file()
        with mock.patch.object(mra, "_make_video", return_value={"state": "done", "video": "v.mp4"}) as video, \
                mock.patch.object(mra, "_post_note") as post, mock.patch.object(mra, "_chain") as chain:
            code = mra.cmd_publish(mra.build_parser().parse_args(["publish", "--to", "douyin", "--note", path]))
        self.assertEqual(code, 0)
        video.assert_called_once()
        post.assert_not_called()
        chain.assert_not_called()

    def test_xhs_only_posts_note(self) -> None:
        path = _note_file()
        with mock.patch.object(mra, "_post_note", return_value={"state": "done"}) as post, \
                mock.patch.object(mra, "_make_video") as video:
            code = mra.cmd_publish(mra.build_parser().parse_args(["publish", "--to", "xhs", "--note", path]))
        self.assertEqual(code, 0)
        post.assert_called_once()
        video.assert_not_called()

    def test_all_without_note_runs_chain_then_video(self) -> None:
        def fake_chain(namespace, out=None):
            if out is not None:
                out.update({"note": NOTE, "note_path": "/tmp/note.json"})
            return 0

        with mock.patch.object(mra, "_chain", side_effect=fake_chain) as chain, \
                mock.patch.object(mra, "_make_video", return_value={"state": "done", "video": "v.mp4"}) as video:
            code = mra.cmd_publish(mra.build_parser().parse_args(["publish", "--to", "all", "--publish"]))
        self.assertEqual(code, 0)
        chain.assert_called_once()
        video.assert_called_once()
        self.assertEqual(video.call_args.args[0]["title"], NOTE["title"])
        self.assertTrue(video.call_args.args[2])

    def test_default_does_not_publish(self) -> None:
        path = _note_file()
        with mock.patch.object(mra, "_make_video", return_value={"state": "done"}) as video, \
                mock.patch.object(mra, "_post_note", return_value={"state": "pending_human"}) as post:
            mra.cmd_publish(mra.build_parser().parse_args(["publish", "--to", "all", "--note", path]))
        self.assertFalse(video.call_args.args[2])
        self.assertFalse(post.call_args.args[2])

    def test_chain_failure_skips_publish_code(self) -> None:
        guard = mock.Mock(return_value={"ok": False, "rounds": 1, "transcript": []})
        with mock.patch.object(mra, "_chain", return_value=mra.EXIT_GATE), \
                mock.patch.object(mra, "_make_video") as video, \
                mock.patch.object(mra, "_constitution_guard", guard):
            code = mra.cmd_publish(mra.build_parser().parse_args(["publish", "--to", "all"]))
        self.assertEqual(code, mra.EXIT_GATE)
        video.assert_not_called()
        guard.assert_called_once()


if __name__ == "__main__":
    unittest.main()
