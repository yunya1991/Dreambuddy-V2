"""中文开关命令：只验证解析与暂停语义，不触碰真实状态库。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401 - 负责把 scripts/ 加入 sys.path
import ra


class SwitchCliTest(unittest.TestCase):
    def test_chinese_commands_parse(self):
        parser = ra.build_parser()
        self.assertEqual(parser.parse_args(["开启预约"]).func.__name__, "cmd_start")
        self.assertEqual(parser.parse_args(["关闭预约"]).func.__name__, "cmd_stop")
        self.assertEqual(parser.parse_args(["状态"]).func.__name__, "cmd_switch_status")

    def test_english_aliases_parse(self):
        parser = ra.build_parser()
        self.assertEqual(parser.parse_args(["start"]).func.__name__, "cmd_start")
        self.assertEqual(parser.parse_args(["stop"]).func.__name__, "cmd_stop")

    def test_synonym_aliases_parse(self):
        parser = ra.build_parser()
        self.assertEqual(parser.parse_args(["开始预约"]).func.__name__, "cmd_start")
        self.assertEqual(parser.parse_args(["停止预约"]).func.__name__, "cmd_stop")


if __name__ == "__main__":
    unittest.main()
