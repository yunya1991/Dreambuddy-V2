"""u2 本地通道测试：路由、剪映/抖音流程与失败问千问（不连接真机）。"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import _support  # noqa: F401

import mra
import phone_driver
from phone_driver import runner


class _Node:
    """最小控件替身：只支持 click/exists。"""

    exists = True

    def __init__(self, driver, label):
        self.driver = driver
        self.label = label

    def click(self):
        self.driver.clicked.append(self.label)
        return True


class FakeDriver:
    """与 U2Driver 同接口的内存替身。"""

    def __init__(self, missing=(), page="", media="", fill_ok=True):
        self.missing = set(missing)
        self.page = page
        self.media = media
        self.fill_ok = fill_ok
        self.clicked: list[str] = []
        self.started: list[str] = []

    def app_start(self, package):
        self.started.append(package)

    def app_restart(self, package):
        self.started.append(package)

    def dismiss(self, labels=(), rounds=3):
        return []

    def wait(self, label, timeout=8):
        return None if label in self.missing else _Node(self, label)

    def find(self, label):
        return None if label in self.missing else _Node(self, label)

    def tap_any(self, labels, timeout=6):
        for label in labels:
            if label in self.missing:
                continue
            self.clicked.append(label)
            return label
        return ""

    def fill(self, value, hint=""):
        self.clicked.append("fill")
        return self.fill_ok

    def fill_all(self, values):
        self.clicked.append("fill_all")
        return [True] * len(values)

    def swipe_up(self, scale=0.72):
        self.clicked.append("swipe_up")
        return True

    def page_text(self, limit=1200):
        return self.page

    def screenshot(self, tag="u2"):
        return "/tmp/{}.png".format(tag)

    def latest_media(self, suffix=".mp4"):
        return self.media

    def press(self, key):
        return True

    def hide_keyboard(self):
        return True

    def restore_ime(self):
        return True

    def _dismiss_ime_picker(self):
        return False

    def fill_fields(self, pairs):
        self.clicked.append("fill_fields")
        return [True] * len(pairs)

    def tap_xy(self, x, y):
        self.clicked.append("xy")
        return True

    def d(self, **kwargs):
        return _Node(self, "d")


class RoutingTest(unittest.TestCase):
    def test_non_local_adapters_stay_on_gateway(self) -> None:
        for adapter in ("xiaohongshu", "railway", "qianwen", "news"):
            self.assertFalse(phone_driver.use_local_driver(adapter))

    def test_gateway_mode_keeps_old_channel(self) -> None:
        with mock.patch.dict(os.environ, {"MRA_PHONE_DRIVER": "gateway"}):
            self.assertFalse(phone_driver.use_local_driver("jianying"))

    def test_u2_mode_forces_local(self) -> None:
        with mock.patch.dict(os.environ, {"MRA_PHONE_DRIVER": "u2"}):
            self.assertTrue(phone_driver.use_local_driver("jianying"))
            self.assertTrue(phone_driver.use_local_driver("douyin"))

    def test_run_phone_job_routes_jianying_to_local(self) -> None:
        with mock.patch.object(phone_driver, "use_local_driver", return_value=True), mock.patch.object(
            phone_driver, "run_local_job", return_value={"state": "done"}
        ) as local:
            result = mra._run_phone_job({"adapter": "jianying", "text": "文案"}, timeout=5)
        self.assertEqual(result["state"], "done")
        local.assert_called_once()

    def test_run_phone_job_keeps_gateway_for_xhs(self) -> None:
        with mock.patch.object(phone_driver, "run_local_job") as local, mock.patch.object(
            mra, "open_store"
        ) as store:
            store.return_value.__enter__.return_value.enqueue_job.return_value = False
            store.return_value.__enter__.return_value._fetchone.return_value = None
            result = mra._run_phone_job({"adapter": "xiaohongshu", "task_id": "t1"}, timeout=1)
        self.assertEqual(result["state"], "failed")
        local.assert_not_called()


class JianyingFlowTest(unittest.TestCase):
    def test_make_video_success(self) -> None:
        driver = FakeDriver(page="保存成功", media="/sdcard/DCIM/Camera/a.mp4")
        with mock.patch("time.sleep", return_value=None):
            result = runner.run_local_job({"adapter": "jianying", "text": "标题\n正文"}, driver=driver)
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["detail"]["video"], "/sdcard/DCIM/Camera/a.mp4")
        self.assertIn("图文成片", driver.clicked)
        self.assertIn("生成视频", driver.clicked)
        self.assertEqual(driver.started, ["com.lemon.lv"])

    def test_make_video_missing_entry_asks_qwen_once(self) -> None:
        driver = FakeDriver(missing={"图文成片", "文字成片"}, page="首页 开始创作")
        with mock.patch("time.sleep", return_value=None), mock.patch.object(
            runner, "consult_qwen", return_value="点底部剪辑后再找图文成片"
        ) as consult:
            result = runner.run_local_job({"adapter": "jianying", "text": "文案"}, driver=driver)
        self.assertEqual(result["state"], "needs_human")
        self.assertEqual(result["detail"]["step"], "jy_entry")
        self.assertIn("点底部剪辑", result["detail"]["consult"])
        consult.assert_called_once()

    def test_make_video_empty_text_does_not_touch_phone(self) -> None:
        driver = FakeDriver()
        result = runner.run_local_job({"adapter": "jianying", "text": "   "}, driver=driver)
        self.assertEqual(result["state"], "error")
        self.assertEqual(driver.started, [])


class DouyinFlowTest(unittest.TestCase):
    def test_post_stops_before_publish(self) -> None:
        driver = FakeDriver(page="全部\n添加标题\n添加作品描述")
        note = {"title": "财经观察", "body": "正文", "topics": ["财经"]}
        with mock.patch("time.sleep", return_value=None):
            result = runner.run_local_job(
                {"adapter": "douyin", "note": note, "media": "video", "publish_authorized": False},
                driver=driver,
            )
        self.assertEqual(result["state"], "needs_human")
        self.assertIn("发作品", result["detail"]["note"])
        self.assertNotIn("发作品", driver.clicked)
        self.assertTrue(result["detail"]["filled"]["title"])

    def test_post_publish_authorized_clicks_button(self) -> None:
        driver = FakeDriver(page="全部\n添加标题\n发布成功")
        with mock.patch("time.sleep", return_value=None):
            result = runner.run_local_job(
                {"adapter": "douyin", "note": {"title": "t", "body": "b"},
                 "publish_authorized": True},
                driver=driver,
            )
        self.assertEqual(result["state"], "done")
        self.assertIn("发作品", driver.clicked)


if __name__ == "__main__":
    unittest.main()
