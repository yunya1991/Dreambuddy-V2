"""剪映适配器与视频命令测试（不访问网络、不连接手机）。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401

import mra
from phone_adapters import get_adapter


class JianyingAdapterTest(unittest.TestCase):
    def test_text_is_title_plus_body(self) -> None:
        command = get_adapter("jianying").describe({"note": {"title": "标题", "body": "正文"}})
        self.assertEqual(command["mode"], "text_to_video")
        self.assertEqual(command["text"], "标题\n正文")
        self.assertEqual(command["stop_before"], "upload")

    def test_text_truncated(self) -> None:
        command = get_adapter("jianying").describe({"note": {"title": "t", "body": "长" * 3000}})
        self.assertEqual(len(command["text"]), 2000)

    def test_parser_video_make(self) -> None:
        args = mra.build_parser().parse_args(["video", "make", "--note", "n.json"])
        self.assertEqual(args.video_cmd, "make")
        self.assertEqual(args.timeout, 900)

    def test_make_video_requires_text(self) -> None:
        with self.assertRaises(ValueError):
            mra._make_video({"title": "", "body": ""})


if __name__ == "__main__":
    unittest.main()
