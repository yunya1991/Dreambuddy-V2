"""场景运行引擎单元测试"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scenario_runner import ScenarioRunner, ScenarioResult, StepResult


@pytest.fixture
def runner():
    config = {
        "scenarios": {
            "default_timeout": 60,
            "retry_count": 0,
        }
    }
    simulator = MagicMock()
    verifier = MagicMock()
    return ScenarioRunner(config, simulator, verifier)


class TestScenarioRunner:
    """场景运行引擎测试"""

    def test_load_scenario(self, runner, tmp_path):
        scenario = {
            "name": "test",
            "description": "test scenario",
            "steps": [
                {"name": "step1", "action": "wait", "seconds": 0},
            ],
        }
        scenario_file = tmp_path / "test.yaml"
        with open(scenario_file, "w") as f:
            yaml.dump(scenario, f)

        loaded = runner.load_scenario(str(scenario_file))
        assert loaded["name"] == "test"
        assert len(loaded["steps"]) == 1

    def test_load_scenario_not_found(self, runner):
        with pytest.raises(FileNotFoundError):
            runner.load_scenario("/nonexistent/path.yaml")

    def test_load_scenario_invalid_format(self, runner, tmp_path):
        scenario_file = tmp_path / "invalid.yaml"
        with open(scenario_file, "w") as f:
            f.write("- not a dict\n- just a list\n")

        with pytest.raises(ValueError, match="Invalid scenario format"):
            runner.load_scenario(str(scenario_file))

    def test_load_scenario_no_steps(self, runner, tmp_path):
        scenario_file = tmp_path / "nosteps.yaml"
        with open(scenario_file, "w") as f:
            yaml.dump({"name": "test"}, f)

        with pytest.raises(ValueError, match="must contain 'steps'"):
            runner.load_scenario(str(scenario_file))

    def test_run_simple_scenario(self, runner):
        mock_page = MagicMock()
        scenario = {
            "name": "simple",
            "description": "simple test",
            "steps": [
                {"name": "wait", "action": "wait", "seconds": 0.01},
            ],
        }

        result = runner.run(mock_page, scenario)
        assert result.name == "simple"
        assert result.passed is True
        assert len(result.steps) == 1
        assert result.steps[0].passed is True

    def test_run_failed_step(self, runner):
        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("Navigation failed")

        scenario = {
            "name": "failed",
            "description": "failed test",
            "steps": [
                {"name": "navigate", "action": "navigate", "url": "http://test.com"},
            ],
        }

        result = runner.run(mock_page, scenario)
        assert result.passed is False
        assert result.steps[0].passed is False
        assert result.steps[0].error is not None

    def test_run_unknown_action(self, runner):
        mock_page = MagicMock()
        scenario = {
            "name": "unknown",
            "description": "unknown action",
            "steps": [
                {"name": "unknown", "action": "unknown_action"},
            ],
        }

        result = runner.run(mock_page, scenario)
        assert result.passed is False
        assert "Unknown action" in result.steps[0].error

    def test_run_fail_fast(self, runner):
        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("fail")

        scenario = {
            "name": "failfast",
            "steps": [
                {"name": "step1", "action": "navigate", "url": "http://test.com", "fail_fast": True},
                {"name": "step2", "action": "wait", "seconds": 0.01},
            ],
        }

        result = runner.run(mock_page, scenario)
        assert len(result.steps) == 1  # 只执行了第一个步骤

    def test_run_no_fail_fast(self, runner):
        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("fail")

        scenario = {
            "name": "nofailfast",
            "steps": [
                {"name": "step1", "action": "navigate", "url": "http://test.com", "fail_fast": False},
                {"name": "step2", "action": "wait", "seconds": 0.01},
            ],
        }

        result = runner.run(mock_page, scenario)
        assert len(result.steps) == 2  # 两个步骤都执行了

    def test_run_with_retry(self, runner):
        mock_page = MagicMock()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("first fail")
            return None

        mock_page.goto.side_effect = side_effect

        scenario = {
            "name": "retry",
            "retry": 1,
            "steps": [
                {"name": "navigate", "action": "navigate", "url": "http://test.com"},
            ],
        }

        result = runner.run(mock_page, scenario)
        assert result.passed is True
        assert call_count[0] == 2  # 第一次失败，第二次成功

    def test_step_navigate(self, runner):
        mock_page = MagicMock()
        step = {"name": "nav", "action": "navigate", "url": "http://test.com"}
        runner._step_navigate(mock_page, step)
        mock_page.goto.assert_called_once_with(
            "http://test.com", wait_until="networkidle", timeout=30000
        )

    def test_step_click_human(self, runner):
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.bounding_box.return_value = {"x": 10, "y": 10, "width": 100, "height": 30}
        mock_page.locator.return_value = mock_locator

        step = {"name": "click", "action": "click", "selector": "button", "human": True}
        runner._step_click(mock_page, step)

        # human_click 应该被调用
        runner._simulator.human_click.assert_called_once()

    def test_step_type_human(self, runner):
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        step = {"name": "type", "action": "type", "selector": "input", "text": "hello", "human": True}
        runner._step_type(mock_page, step)

        runner._simulator.human_type.assert_called_once_with(mock_locator, "hello")

    def test_step_screenshot(self, runner):
        mock_page = MagicMock()
        step = {"name": "shot", "action": "screenshot", "path": "/tmp/test.png", "full_page": True}
        runner._step_screenshot(mock_page, step)
        mock_page.screenshot.assert_called_once_with(path="/tmp/test.png", full_page=True)


class TestScenarioResult:
    """场景结果数据类测试"""

    def test_scenario_result_creation(self):
        result = ScenarioResult(name="test", description="desc", passed=True)
        assert result.name == "test"
        assert result.passed is True
        assert result.steps == []

    def test_step_result_creation(self):
        step = StepResult(name="step", action="click", passed=True, duration_ms=100.0)
        assert step.name == "step"
        assert step.passed is True
        assert step.duration_ms == 100.0
