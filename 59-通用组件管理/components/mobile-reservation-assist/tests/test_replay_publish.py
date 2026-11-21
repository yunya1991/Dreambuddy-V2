"""行为回放：按 golden 轨迹重跑「剪映 → 抖音发布」，校验每一步动作可复现。

golden 来自真机一次完整成功轨迹（用户确认已发布），
本测试同时校验操作说明文档里的动作表与实际执行顺序一致。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest import mock

import _support  # noqa: F401

from phone_driver import runner

GOLDEN = _support.TESTS_DIR / "golden" / "jianying_douyin_publish.json"
REFERENCE = _support.COMPONENT / "skill" / "references" / "jianying-douyin-publishing.md"


class _Node:
    exists = True

    def __init__(self, driver, label):
        self.driver = driver
        self.label = label

    def click(self):
        self.driver.clicked.append(self.label)
        return True


class ReplayDriver:
    """按真实页面阶段返回文本的驱动替身，不连接真机。"""

    def __init__(self, video: str):
        self.video = video
        self.clicked: list[str] = []
        self.started: list[str] = []

    def app_restart(self, package):
        self.started.append(package)

    def app_start(self, package):
        self.started.append(package)

    def dismiss(self, labels=(), rounds=3):
        return []

    def wait(self, label, timeout=8):
        return _Node(self, label)

    def find(self, label):
        return _Node(self, label)

    def tap_any(self, labels, timeout=6):
        label = list(labels)[0]
        self.clicked.append(label)
        return label

    def fill(self, value, hint=""):
        self.clicked.append("fill")
        return True

    def fill_fields(self, pairs):
        self.clicked.append("fill_fields")
        return [True] * len(pairs)

    def swipe_up(self, scale=0.72):
        return True

    def press(self, key):
        return True

    def tap_xy(self, x, y):
        return True

    def hide_keyboard(self):
        return True

    def restore_ime(self):
        return True

    def _dismiss_ime_picker(self):
        return False

    def screenshot(self, tag="u2"):
        return "/tmp/{}.png".format(tag)

    def latest_media(self, suffix=".mp4"):
        return self.video

    def page_text(self, limit=1200):
        published = any(item in self.clicked for item in ("发作品", "发布", "发布作品"))
        if "分享到抖音" in self.clicked:
            return "发布成功" if published else "添加作品标题 添加作品描述 发布"
        if "图文成片" in self.clicked:
            return "视频比例 9:16 生成视频 导出 1080P 保存成功 分享到抖音"
        return "开始创作 图文成片"


class PublishReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_every_step_replays_in_order(self) -> None:
        driver = ReplayDriver(self.golden["video"])
        note = self.golden["note_input"]
        hit = {
            "adapter": "jianying",
            "text": note["title"] + "\n" + note["body"],
            "note": note,
            "share_douyin": True,
        }
        with mock.patch("time.sleep", return_value=None):
            result = runner.run_local_job(hit, driver=driver)
        actions = [step["action"] for step in result["detail"]["steps"]]
        self.assertEqual(actions, [step["action"] for step in self.golden["steps"]])
        self.assertEqual(result["state"], self.golden["expected_state"])
        self.assertTrue(all(step["ok"] for step in result["detail"]["steps"]))
        self.assertEqual(driver.started, ["com.lemon.lv"])

    def test_reference_doc_matches_golden(self) -> None:
        document = REFERENCE.read_text(encoding="utf-8")
        documented = re.findall(r"\|\s*\d+\s*\|\s*`((?:jy|douyin)_[a-z_]+)`", document)
        self.assertEqual(documented, [step["action"] for step in self.golden["steps"]])

    def test_golden_shape(self) -> None:
        self.assertEqual(self.golden["schema"], "publish.replay.v1")
        self.assertEqual(self.golden["flow"], "jianying_to_douyin")
        self.assertEqual(len(self.golden["steps"]), 12)


if __name__ == "__main__":
    unittest.main()
