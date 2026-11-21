"""架构约束：平台词只出现在 adapters/，适配器齐备，fixture 齐全。"""

from __future__ import annotations

import unittest
from pathlib import Path

import _support
from adapters import ADAPTERS

PLATFORM_WORDS = (
    "12306",
    "damai",
    "大麦",
    "bilibili",
    "B站",
    "猫眼",
    "maoyan",
    "医院",
    "挂号",
    "签证",
    "车管所",
    "railway",
    "medical",
    "gov",
)


class ArchitectureTest(unittest.TestCase):
    def test_kernel_has_no_platform_words(self):
        scripts = Path(_support.COMPONENT_ROOT) / "skill" / "scripts"
        for path in scripts.rglob("*.py"):
            if "adapters" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            hits = [word for word in PLATFORM_WORDS if word in text]
            self.assertFalse(hits, "{} 出现平台词 {}".format(path.relative_to(scripts), hits))

    def test_adapters_registered(self):
        self.assertEqual(
            sorted(ADAPTERS), ["bilibili", "damai", "gov", "maoyan", "medical", "railway"]
        )

    def test_each_adapter_has_fixture(self):
        fixtures = Path(_support.COMPONENT_ROOT) / "tests" / "fixtures"
        for name in ADAPTERS:
            case = fixtures / name / "basic"
            for required in ("request.json", "response.txt", "expected.json"):
                self.assertTrue((case / required).is_file(), "{}/{}".format(name, required))

    def test_launchd_template_has_no_hardcoded_home(self):
        template = (
            Path(_support.COMPONENT_ROOT)
            / "skill"
            / "templates"
            / "com.reservation-assist.watch.plist.tpl"
        )
        text = template.read_text(encoding="utf-8")
        self.assertNotIn("/Users/", text)
        self.assertIn("__HOME__", text)
        self.assertIn("RA_ALLOW_SUBMIT", text)


if __name__ == "__main__":
    unittest.main()
