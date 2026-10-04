"""用户行为模拟层单元测试"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.user_simulator import UserSimulator


@pytest.fixture
def simulator():
    config = {
        "user_simulation": {
            "mouse_move_delay": {"min": 1, "max": 2},
            "typing_delay": {"min": 1, "max": 2},
            "pre_click_delay": {"min": 1, "max": 2},
            "scroll_step": {"min": 10, "max": 20},
            "scroll_interval": {"min": 1, "max": 2},
            "bezier_points": 5,
        }
    }
    return UserSimulator(config)


class TestUserSimulator:
    """用户模拟器测试"""

    def test_init_config(self, simulator):
        assert simulator._config["bezier_points"] == 5

    def test_random_delay_within_range(self, simulator):
        # 验证随机延迟在配置范围内
        delays = []
        for _ in range(100):
            start = time.time()
            simulator._random_delay("mouse_move_delay")
            elapsed = (time.time() - start) * 1000
            delays.append(elapsed)

        # 由于 scale=1.0，延迟应在 min-max 范围内（允许少量误差）
        assert min(delays) >= 0
        assert max(delays) < 10  # 应该很小

    def test_random_delay_scale(self, simulator):
        # 验证 scale 参数生效
        start = time.time()
        simulator._random_delay("typing_delay", scale=0.01)
        elapsed = (time.time() - start) * 1000
        assert elapsed < 5  # scale=0.01 应该非常快

    def test_random_think_time(self):
        start = time.time()
        UserSimulator.random_think_time(0.01, 0.02)
        elapsed = time.time() - start
        assert 0.01 <= elapsed <= 0.05  # 允许少量误差

    def test_human_type_with_mock(self, simulator):
        # 模拟 locator
        mock_locator = MagicMock()

        simulator.human_type(mock_locator, "hello", clear_first=True)

        # 验证 fill("") 被调用（清空）
        mock_locator.fill.assert_called_once_with("")
        # 验证 type 被调用 5 次（每个字符一次）
        assert mock_locator.type.call_count == 5
        mock_locator.type.assert_any_call("h", delay=0)
        mock_locator.type.assert_any_call("e", delay=0)
        mock_locator.type.assert_any_call("l", delay=0)
        mock_locator.type.assert_any_call("o", delay=0)

    def test_human_fill_form(self, simulator):
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.wait_for = MagicMock()
        mock_page.locator.return_value = mock_locator

        fields = {"#name": "test", "#email": "test@example.com"}
        simulator.human_fill_form(mock_page, fields)

        # 验证每个字段都被填写
        assert mock_page.locator.call_count == 2

    def test_human_scroll_down(self, simulator):
        mock_page = MagicMock()
        simulator.human_scroll(mock_page, direction="down", distance=100, duration=0.01)
        # 验证 mouse.wheel 被调用
        assert mock_page.mouse.wheel.call_count > 0
        # 验证向下滚动（delta_y > 0）
        for call in mock_page.mouse.wheel.call_args_list:
            assert call[0][1] > 0  # delta_y

    def test_human_scroll_up(self, simulator):
        mock_page = MagicMock()
        simulator.human_scroll(mock_page, direction="up", distance=100, duration=0.01)
        for call in mock_page.mouse.wheel.call_args_list:
            assert call[0][1] < 0  # delta_y < 0

    def test_human_scroll_left(self, simulator):
        mock_page = MagicMock()
        simulator.human_scroll(mock_page, direction="left", distance=100, duration=0.01)
        for call in mock_page.mouse.wheel.call_args_list:
            assert call[0][0] < 0  # delta_x < 0

    def test_human_scroll_right(self, simulator):
        mock_page = MagicMock()
        simulator.human_scroll(mock_page, direction="right", distance=100, duration=0.01)
        for call in mock_page.mouse.wheel.call_args_list:
            assert call[0][0] > 0  # delta_x > 0

    def test_move_mouse_with_curve(self, simulator):
        mock_page = MagicMock()
        simulator._move_mouse_with_curve(mock_page, 500, 500)
        # 验证 mouse.move 被调用多次（贝塞尔曲线点数）
        assert mock_page.mouse.move.call_count == simulator._config["bezier_points"]
