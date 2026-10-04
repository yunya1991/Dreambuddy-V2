"""用户行为模拟层 — 模拟真实用户的鼠标和键盘行为

核心设计：
- 鼠标移动：使用贝塞尔曲线生成自然轨迹，带随机抖动
- 键盘输入：每个字符间随机延迟，模拟真实打字节奏
- 点击：移动到目标 → 短暂停留 → 按下 → 释放
- 滚动：分步滚动，带随机步长和间隔

反检测特性：
- 不使用 Playwright 的 element.click()（会被检测为自动化）
- 使用 mouse.move() + mouse.down() + mouse.up() 模拟真实点击
- 添加微小的坐标偏移和时间抖动
"""
from __future__ import annotations

import logging
import random
import time
from typing import Optional, Tuple

from playwright.sync_api import Page, Locator

logger = logging.getLogger("real_env.user_simulator")


class UserSimulator:
    """用户行为模拟器 — 在真实浏览器中模拟人类操作"""

    def __init__(self, config: dict):
        self._config = config.get("user_simulation", {})

    # ------------------------------------------------------------------
    # 鼠标行为
    # ------------------------------------------------------------------
    def human_click(self, page: Page, locator: Locator,
                    button: str = "left", click_count: int = 1) -> None:
        """模拟真实人类点击。

        流程：获取元素位置 → 贝塞尔曲线移动 → 短暂停留 → 按下 → 释放
        """
        box = locator.bounding_box()
        if box is None:
            # fallback: 直接点击
            logger.warning("Element bounding box not found, using direct click")
            locator.click()
            return

        # 计算目标点（元素中心 + 随机偏移）
        target_x = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
        target_y = box["y"] + box["height"] / 2 + random.uniform(-3, 3)

        # 贝塞尔曲线移动到目标
        self._move_mouse_with_curve(page, target_x, target_y)

        # 短暂停留（模拟人类犹豫）
        self._random_delay("pre_click_delay")

        # 按下并释放
        page.mouse.down(button=button)
        time.sleep(random.uniform(0.02, 0.08))  # 按下停留
        page.mouse.up(button=button)

        if click_count > 1:
            for _ in range(click_count - 1):
                time.sleep(random.uniform(0.1, 0.2))
                page.mouse.down(button=button)
                time.sleep(random.uniform(0.02, 0.08))
                page.mouse.up(button=button)

        logger.debug("Human click at (%.1f, %.1f)", target_x, target_y)

    def human_hover(self, page: Page, locator: Locator) -> None:
        """模拟鼠标悬停。"""
        box = locator.bounding_box()
        if box is None:
            locator.hover()
            return

        target_x = box["x"] + box["width"] / 2 + random.uniform(-5, 5)
        target_y = box["y"] + box["height"] / 2 + random.uniform(-5, 5)
        self._move_mouse_with_curve(page, target_x, target_y)

    def human_drag(self, page: Page, source: Locator, target: Locator) -> None:
        """模拟拖拽操作。"""
        src_box = source.bounding_box()
        tgt_box = target.bounding_box()
        if src_box is None or tgt_box is None:
            source.drag_to(target)
            return

        src_x = src_box["x"] + src_box["width"] / 2
        src_y = src_box["y"] + src_box["height"] / 2
        tgt_x = tgt_box["x"] + tgt_box["width"] / 2
        tgt_y = tgt_box["y"] + tgt_box["height"] / 2

        # 移动到源
        self._move_mouse_with_curve(page, src_x, src_y)
        self._random_delay("pre_click_delay")

        # 按下
        page.mouse.down()
        time.sleep(random.uniform(0.05, 0.15))

        # 拖拽到目标（分段移动，模拟真实拖拽）
        steps = random.randint(8, 15)
        for i in range(1, steps + 1):
            t = i / steps
            # 加入贝塞尔曲线偏移
            ctrl_x = (src_x + tgt_x) / 2 + random.uniform(-20, 20)
            ctrl_y = (src_y + tgt_y) / 2 + random.uniform(-20, 20)
            x = (1 - t) ** 2 * src_x + 2 * (1 - t) * t * ctrl_x + t ** 2 * tgt_x
            y = (1 - t) ** 2 * src_y + 2 * (1 - t) * t * ctrl_y + t ** 2 * tgt_y
            page.mouse.move(x, y)
            time.sleep(random.uniform(0.01, 0.03))

        # 释放
        time.sleep(random.uniform(0.05, 0.15))
        page.mouse.up()

    def _move_mouse_with_curve(self, page: Page, target_x: float, target_y: float) -> None:
        """使用贝塞尔曲线移动鼠标到目标位置。"""
        # 获取当前鼠标位置（近似：从视口中心开始）
        current_x = random.uniform(100, 800)
        current_y = random.uniform(100, 600)

        # 生成贝塞尔曲线控制点
        ctrl_x = (current_x + target_x) / 2 + random.uniform(-100, 100)
        ctrl_y = (current_y + target_y) / 2 + random.uniform(-100, 100)

        # 沿曲线移动
        points = self._config.get("bezier_points", 20)
        for i in range(1, points + 1):
            t = i / points
            x = (1 - t) ** 2 * current_x + 2 * (1 - t) * t * ctrl_x + t ** 2 * target_x
            y = (1 - t) ** 2 * current_y + 2 * (1 - t) * t * ctrl_y + t ** 2 * target_y
            # 加入微小抖动
            x += random.uniform(-1, 1)
            y += random.uniform(-1, 1)
            page.mouse.move(x, y)
            self._random_delay("mouse_move_delay", scale=0.1)

    # ------------------------------------------------------------------
    # 键盘行为
    # ------------------------------------------------------------------
    def human_type(self, locator: Locator, text: str, clear_first: bool = True) -> None:
        """模拟真实人类打字。

        每个字符间随机延迟，模拟真实打字节奏。
        """
        if clear_first:
            locator.click()
            locator.fill("")  # 清空

        for char in text:
            locator.type(char, delay=0)  # 单次输入单个字符
            # 随机延迟模拟打字节奏
            self._random_delay("typing_delay")

        logger.debug("Human typed %d characters", len(text))

    def human_fill_form(self, page: Page, fields: dict) -> None:
        """填写表单，fields 为 {选择器: 值} 的字典。"""
        for selector, value in fields.items():
            locator = page.locator(selector)
            locator.wait_for(state="visible", timeout=10000)
            self.human_type(locator, str(value))
            time.sleep(random.uniform(0.3, 0.8))  # 字段间停顿

    def human_press(self, page: Page, key: str) -> None:
        """模拟按键。"""
        page.keyboard.press(key)
        self._random_delay("typing_delay", scale=0.5)

    # ------------------------------------------------------------------
    # 滚动行为
    # ------------------------------------------------------------------
    def human_scroll(self, page: Page, direction: str = "down",
                     distance: Optional[int] = None, duration: float = 1.0) -> None:
        """模拟真实滚动。

        Args:
            direction: "up" | "down" | "left" | "right"
            distance: 滚动距离（像素），None 则随机
            duration: 滚动总时长（秒）
        """
        if distance is None:
            distance = random.randint(
                self._config.get("scroll_step", {}).get("min", 100),
                self._config.get("scroll_step", {}).get("max", 300),
            )

        # 分步滚动
        steps = random.randint(3, 8)
        step_distance = distance / steps
        step_duration = duration / steps

        for _ in range(steps):
            if direction == "down":
                page.mouse.wheel(0, step_distance)
            elif direction == "up":
                page.mouse.wheel(0, -step_distance)
            elif direction == "right":
                page.mouse.wheel(step_distance, 0)
            elif direction == "left":
                page.mouse.wheel(-step_distance, 0)

            self._random_delay("scroll_interval", scale=step_duration)

    def human_scroll_to_element(self, page: Page, locator: Locator) -> None:
        """滚动到元素可见位置。"""
        locator.scroll_into_view_if_needed()
        time.sleep(random.uniform(0.3, 0.6))

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _random_delay(self, config_key: str, scale: float = 1.0) -> None:
        """根据配置生成随机延迟。"""
        delay_cfg = self._config.get(config_key, {"min": 30, "max": 100})
        min_ms = delay_cfg.get("min", 30)
        max_ms = delay_cfg.get("max", 100)
        delay_ms = random.uniform(min_ms, max_ms) * scale
        time.sleep(delay_ms / 1000.0)

    @staticmethod
    def random_think_time(min_sec: float = 0.5, max_sec: float = 2.0) -> None:
        """模拟人类思考时间。"""
        time.sleep(random.uniform(min_sec, max_sec))
