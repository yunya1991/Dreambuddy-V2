"""架构测试：平台专属信息只允许出现在 phone_adapters/，内核脚本零平台词。"""

from __future__ import annotations

import unittest

from _support import SCRIPTS

# 无歧义的平台标识（包名或专属中文名），不得出现在内核脚本
PLATFORM_TOKENS = [
    "12306",
    "cn.damai",
    "tv.danmaku.bili",
    "com.sankuai.movie",
    "com.MobileTicket",
    "大麦",
    "猫眼",
    "会员购",
]

CORE_SCRIPTS = [
    "mra.py",
    "ingest.py",
    "store.py",
    "gateway.py",
    "executor.py",
    "notify.py",
    "security.py",
]


class ArchitectureTest(unittest.TestCase):
    def test_core_scripts_have_no_platform_tokens(self) -> None:
        for name in CORE_SCRIPTS:
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            for token in PLATFORM_TOKENS:
                self.assertNotIn(token, text, "{} 出现平台词 {}".format(name, token))

    def test_phone_adapters_registry_six(self) -> None:
        import phone_adapters

        self.assertEqual(len(phone_adapters.ADAPTERS), 6)
        expected = {"railway", "damai", "bilibili", "maoyan", "medical", "gov"}
        self.assertEqual(set(phone_adapters.ADAPTERS), expected)


if __name__ == "__main__":
    unittest.main()
