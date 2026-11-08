"""工具模块 — DOM 断言、截图对比、网络请求捕获、桌面断言辅助工具"""

from .desktop_assertions import DesktopAssertions
from .dom_assertions import DOMAssertions
from .network_capture import NetworkCapture
from .screenshot_diff import (
    compare_screenshot_bytes,
    compare_screenshot_paths,
    save_diff_screenshot,
    save_diff_screenshot_paths,
)

__all__ = [
    "DOMAssertions",
    "compare_screenshot_bytes",
    "compare_screenshot_paths",
    "save_diff_screenshot",
    "save_diff_screenshot_paths",
    "NetworkCapture",
    "DesktopAssertions",
]
