"""线5 computer_use 引擎单元测试 — trae 电脑控制（双模式）

测试覆盖：
1. ComputerUseRunner 构造与配置解析
2. build_plan（A 模式 YAML → prompt 列表）
3. parse_step_response（subagent 文本 → ComputerUseStep）
4. run_task_from_yaml A 模式 plan_only=True（仅生成 plan）
5. run_task_from_yaml A 模式 plan_only=False（报错提示需 trae 介入）
6. run_task_from_yaml B 模式 desktop_native（mock pyautogui/osascript）
7. DesktopAssertions 独立测试（file_exists/file_contains/terminal_contains/ui_visual_match）
8. ComputerUseStep/ComputerUseResult to_dict 序列化

设计要点：
- 不实际操作桌面，pyautogui/subprocess 用 unittest.mock.patch 替换
- 验证 YAML → prompt 映射正确性
- 验证模式 A 仅生成 plan 不执行
- 验证模式 B 直接调 pyautogui/osascript
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# 1. 构造与配置
# =============================================================================
class TestComputerUseRunnerConstruction(unittest.TestCase):
    """ComputerUseRunner 初始化与配置解析"""

    def test_init_default_config(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        self.assertEqual(runner._subagent_type, "computer_use")
        self.assertEqual(runner._step_timeout, 60)
        self.assertEqual(runner._visual_threshold, 0.05)
        self.assertEqual(runner._pyautogui_confidence, 0.8)
        self.assertEqual(runner._osascript_path, "/usr/bin/osascript")
        self.assertTrue(runner._auto_verify)

    def test_init_from_config(self):
        from core.computer_use_runner import ComputerUseRunner
        config = {
            "computer_use": {
                "subagent_type": "my_subagent",
                "step_timeout": 30,
                "screenshot_dir": "/tmp/custom_cu",
                "auto_verify": False,
                "visual_threshold": 0.1,
                "plan_only": True,
            },
            "desktop_native": {
                "pyautogui_confidence": 0.9,
                "osascript_path": "/opt/osascript",
            },
        }
        runner = ComputerUseRunner(config)
        self.assertEqual(runner._subagent_type, "my_subagent")
        self.assertEqual(runner._step_timeout, 30)
        self.assertEqual(runner._screenshot_dir, "/tmp/custom_cu")
        self.assertFalse(runner._auto_verify)
        self.assertEqual(runner._visual_threshold, 0.1)
        self.assertEqual(runner._pyautogui_confidence, 0.9)
        self.assertEqual(runner._osascript_path, "/opt/osascript")

    def test_screenshot_dir_created(self):
        from core.computer_use_runner import ComputerUseRunner
        with tempfile.TemporaryDirectory() as tmp:
            sd = os.path.join(tmp, "cu_shots")
            runner = ComputerUseRunner({"computer_use": {"screenshot_dir": sd}})
            self.assertTrue(Path(sd).exists())


# =============================================================================
# 2. build_plan（A 模式）
# =============================================================================
class TestBuildPlan(unittest.TestCase):
    """A 模式 YAML → 自然语言 prompt 列表"""

    def test_build_plan_basic(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        yaml_dict = {
            "default_app": "Google Chrome",
            "steps": [
                {"activate": {"app": "Google Chrome"}},
                {"click": {"target": "刷新按钮", "expect": "页面重新加载"}},
                {"type": {"target": "地址栏", "text": "http://localhost:3001/dashboard"}},
                {"screenshot": {"path": "/tmp/cu_step1.png"}},
                {"open_app": {"name": "Terminal"}},
            ],
        }
        plan = runner.build_plan(yaml_dict)
        self.assertEqual(len(plan), 5)
        for i, entry in enumerate(plan, 1):
            self.assertEqual(entry["step_index"], i)
            self.assertIn("prompt", entry)
            self.assertIn("action", entry)
        # activate 步骤
        self.assertIn("Google Chrome", plan[0]["prompt"])
        # click 步骤含 expect
        self.assertEqual(plan[1]["expect"], "页面重新加载")
        # type 步骤
        self.assertIn("http://localhost:3001/dashboard", plan[2]["prompt"])
        # screenshot 步骤含路径
        self.assertIn("/tmp/cu_step1.png", plan[3]["prompt"])
        # open_app 步骤
        self.assertIn("Terminal", plan[4]["prompt"])

    def test_build_plan_empty_steps(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        plan = runner.build_plan({})
        self.assertEqual(plan, [])

    def test_build_plan_unknown_step_fallback(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        plan = runner.build_plan({"steps": [{"unknown_action": {"x": 1}}]})
        self.assertEqual(len(plan), 1)
        self.assertIn("原始 YAML", plan[0]["prompt"])


# =============================================================================
# 3. parse_step_response
# =============================================================================
class TestParseStepResponse(unittest.TestCase):
    """解析 subagent 文本响应"""

    def test_parse_success_keyword(self):
        from core.computer_use_runner import ComputerUseRunner, ComputerUseStep
        runner = ComputerUseRunner({})
        step = {"click": {"target": "刷新按钮"}}
        s = runner.parse_step_response("操作成功完成 success", step)
        self.assertTrue(s.success)
        self.assertEqual(s.mode, "computer_use")
        self.assertIsNone(s.error)

    def test_parse_failure_keyword(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        step = {"click": {"target": "刷新按钮"}}
        s = runner.parse_step_response("操作失败 fail: 元素未找到", step)
        self.assertFalse(s.success)
        self.assertEqual(s.error, "parse_fail_or_subagent_reported_failure")

    def test_parse_screenshot_path_extraction(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        step = {"screenshot": {"path": "/tmp/x.png"}}
        s = runner.parse_step_response("截图已保存 /tmp/cu_step1.png 完成", step)
        self.assertEqual(s.screenshot_path, "/tmp/cu_step1.png")

    def test_parse_empty_response(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        s = runner.parse_step_response("", {"click": {"target": "x"}})
        self.assertFalse(s.success)


# =============================================================================
# 4-5. run_task_from_yaml A 模式
# =============================================================================
class TestRunTaskFromYamlComputerUseMode(unittest.TestCase):
    """A 模式：plan_only=True 仅生成 plan；plan_only=False 报错"""

    def test_a_mode_plan_only_true_returns_plan(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        scenario = {
            "name": "跨应用测试",
            "mode": "computer_use",
            "steps": [{"activate": {"app": "Google Chrome"}}],
            "assertions": [{"file_exists": {"path": "/tmp/x"}}],
        }
        result = runner.run_task_from_yaml(scenario, plan_only=True)
        self.assertTrue(result.passed)
        self.assertEqual(result.mode, "computer_use")
        self.assertEqual(len(result.plan), 1)
        self.assertEqual(result.steps, [])

    def test_a_mode_plan_only_false_errors(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        scenario = {
            "name": "跨应用测试",
            "mode": "computer_use",
            "steps": [{"activate": {"app": "Google Chrome"}}],
        }
        result = runner.run_task_from_yaml(scenario, plan_only=False)
        self.assertFalse(result.passed)
        self.assertIsNotNone(result.error)
        self.assertIn("trae", result.error)
        self.assertEqual(len(result.plan), 1)  # plan 仍生成供 trae 用

    def test_a_mode_empty_steps_returns_error(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        result = runner.run_task_from_yaml({"name": "x", "mode": "computer_use", "steps": []})
        self.assertFalse(result.passed)
        self.assertIn("steps", result.error)


# =============================================================================
# 6. run_task_from_yaml B 模式
# =============================================================================
class TestRunTaskFromYamlDesktopNativeMode(unittest.TestCase):
    """B 模式：mock pyautogui/osascript，验证调用"""

    def test_b_mode_open_app_calls_subprocess_open(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        scenario = {
            "name": "跨应用测试",
            "mode": "desktop_native",
            "steps": [{"open_app": {"name": "Google Chrome"}}],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = runner.run_task_from_yaml(scenario)
            self.assertTrue(result.passed)
            self.assertEqual(len(result.steps), 1)
            self.assertTrue(result.steps[0].success)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[:3], ["open", "-a", "Google Chrome"])

    def test_b_mode_screenshot_uses_pyautogui(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({"computer_use": {"screenshot_dir": "/tmp/test_cu_shots"}})
        scenario = {
            "name": "截图测试",
            "mode": "desktop_native",
            "steps": [{"screenshot": {"path": "/tmp/test_cu_step.png"}}],
        }
        with patch.dict(sys.modules, {"pyautogui": MagicMock()}):
            import pyautogui
            img_mock = MagicMock()
            img_mock.save = MagicMock()
            pyautogui.screenshot = MagicMock(return_value=img_mock)
            result = runner.run_task_from_yaml(scenario)
            self.assertTrue(result.passed)
            pyautogui.screenshot.assert_called_once()
            img_mock.save.assert_called_once_with("/tmp/test_cu_step.png")

    def test_b_mode_bail_on_step_failure(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        scenario = {
            "name": "失败测试",
            "mode": "desktop_native",
            "steps": [
                {"open_app": {"name": "Google Chrome"}},
                {"click_image": {"image": "/tmp/nonexistent.png"}},
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            with patch.dict(sys.modules, {"pyautogui": MagicMock()}):
                import pyautogui
                pyautogui.locateOnScreen = MagicMock(return_value=None)
                result = runner.run_task_from_yaml(scenario)
                # 第一步失败（returncode=1），bail-out，第二步不执行
                self.assertFalse(result.passed)
                self.assertEqual(len(result.steps), 1)
                self.assertFalse(result.steps[0].success)

    def test_b_mode_with_file_assertion(self):
        from core.computer_use_runner import ComputerUseRunner
        runner = ComputerUseRunner({})
        # 创建临时文件作为断言目标
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("execution_complete\n")
            tmp_path = f.name
        try:
            scenario = {
                "name": "带验证",
                "mode": "desktop_native",
                "steps": [{"open_app": {"name": "Terminal"}}],
                "assertions": [
                    {"file_exists": {"path": tmp_path}},
                    {"file_contains": {"path": tmp_path, "text": "execution_complete"}},
                ],
            }
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                result = runner.run_task_from_yaml(scenario)
                self.assertTrue(result.passed)
                self.assertIsNotNone(result.verification)
                self.assertTrue(result.verification.passed)
        finally:
            os.unlink(tmp_path)


# =============================================================================
# 7. DesktopAssertions 独立测试
# =============================================================================
class TestDesktopAssertions(unittest.TestCase):
    """DesktopAssertions 静态方法集"""

    def test_file_exists_true(self):
        from utils.desktop_assertions import DesktopAssertions
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp_path = f.name
        try:
            r = DesktopAssertions.file_exists(tmp_path)
            self.assertTrue(r.passed)
            self.assertEqual(r.name, "file_exists")
        finally:
            os.unlink(tmp_path)

    def test_file_exists_false(self):
        from utils.desktop_assertions import DesktopAssertions
        r = DesktopAssertions.file_exists("/tmp/__nonexistent_file_xyz123__.txt")
        self.assertFalse(r.passed)
        self.assertIsNotNone(r.error)

    def test_file_contains_true(self):
        from utils.desktop_assertions import DesktopAssertions
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world execution_complete done")
            tmp_path = f.name
        try:
            r = DesktopAssertions.file_contains(tmp_path, "execution_complete")
            self.assertTrue(r.passed)
        finally:
            os.unlink(tmp_path)

    def test_file_contains_false_text_not_found(self):
        from utils.desktop_assertions import DesktopAssertions
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            tmp_path = f.name
        try:
            r = DesktopAssertions.file_contains(tmp_path, "execution_complete")
            self.assertFalse(r.passed)
        finally:
            os.unlink(tmp_path)

    def test_file_contains_file_not_found(self):
        from utils.desktop_assertions import DesktopAssertions
        r = DesktopAssertions.file_contains("/tmp/__nope__.txt", "x")
        self.assertFalse(r.passed)
        self.assertIn("not found", r.error)

    def test_file_size_gt(self):
        from utils.desktop_assertions import DesktopAssertions
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("x" * 100)
            tmp_path = f.name
        try:
            r = DesktopAssertions.file_size_gt(tmp_path, 50)
            self.assertTrue(r.passed)
            r2 = DesktopAssertions.file_size_gt(tmp_path, 200)
            self.assertFalse(r2.passed)
        finally:
            os.unlink(tmp_path)

    def test_terminal_contains_with_subagent_response(self):
        from utils.desktop_assertions import DesktopAssertions
        r = DesktopAssertions.terminal_contains(
            "execution_complete",
            subagent_response="some output execution_complete done",
        )
        self.assertTrue(r.passed)
        self.assertIn("mode", r.details)
        self.assertEqual(r.details["mode"], "computer_use_subagent")

    def test_terminal_contains_subagent_text_not_found(self):
        from utils.desktop_assertions import DesktopAssertions
        r = DesktopAssertions.terminal_contains(
            "execution_complete",
            subagent_response="nothing relevant here",
        )
        self.assertFalse(r.passed)

    def test_terminal_contains_osascript_mode(self):
        from utils.desktop_assertions import DesktopAssertions
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="some output execution_complete done", stderr=""
            )
            r = DesktopAssertions.terminal_contains("execution_complete")
            self.assertTrue(r.passed)
            self.assertEqual(r.details["mode"], "osascript")
            mock_run.assert_called_once()

    def test_ui_visual_match_identical_images(self):
        """两张相同截图 diff_score=0，passed=True"""
        from utils.desktop_assertions import DesktopAssertions
        # 用 PIL 生成两张相同的小图
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL not installed")
        with tempfile.TemporaryDirectory() as tmp:
            p1 = os.path.join(tmp, "a.png")
            p2 = os.path.join(tmp, "b.png")
            Image.new("RGB", (10, 10), (255, 0, 0)).save(p1)
            Image.new("RGB", (10, 10), (255, 0, 0)).save(p2)
            r = DesktopAssertions.ui_visual_match(p1, p2, threshold=0.05)
            self.assertTrue(r.passed)
            self.assertEqual(r.details["diff_score"], 0.0)

    def test_ui_visual_match_different_images(self):
        """两张完全不同截图 diff_score 高，passed=False"""
        from utils.desktop_assertions import DesktopAssertions
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL not installed")
        with tempfile.TemporaryDirectory() as tmp:
            p1 = os.path.join(tmp, "a.png")
            p2 = os.path.join(tmp, "b.png")
            Image.new("RGB", (10, 10), (0, 0, 0)).save(p1)
            Image.new("RGB", (10, 10), (255, 255, 255)).save(p2)
            r = DesktopAssertions.ui_visual_match(p1, p2, threshold=0.05)
            self.assertFalse(r.passed)
            self.assertGreater(r.details["diff_score"], 0.5)

    def test_ui_visual_match_missing_current(self):
        from utils.desktop_assertions import DesktopAssertions
        r = DesktopAssertions.ui_visual_match("/tmp/__nope1__.png", "/tmp/__nope2__.png")
        self.assertFalse(r.passed)
        self.assertIsNotNone(r.error)


# =============================================================================
# 8. 数据类 to_dict
# =============================================================================
class TestDataclassesToDict(unittest.TestCase):
    """ComputerUseStep / ComputerUseResult to_dict 序列化"""

    def test_step_to_dict(self):
        from core.computer_use_runner import ComputerUseStep
        step = ComputerUseStep(
            step={"click": {"target": "x"}},
            mode="computer_use",
            success=True,
            output="done",
            screenshot_path="/tmp/x.png",
            duration_ms=100.0,
        )
        d = step.to_dict()
        self.assertEqual(d["mode"], "computer_use")
        self.assertTrue(d["success"])
        self.assertEqual(d["screenshot_path"], "/tmp/x.png")
        self.assertEqual(d["duration_ms"], 100.0)

    def test_result_to_dict(self):
        from core.computer_use_runner import ComputerUseResult, ComputerUseStep
        from core.result_verifier import VerificationResult
        r = ComputerUseResult(
            task="测试",
            passed=True,
            mode="computer_use",
            steps=[ComputerUseStep(step={"x": 1}, mode="computer_use", success=True)],
            plan=[{"step_index": 1, "prompt": "test"}],
            duration_ms=200.0,
            verification=VerificationResult(name="verification", passed=True),
        )
        d = r.to_dict()
        self.assertEqual(d["task"], "测试")
        self.assertTrue(d["passed"])
        self.assertEqual(d["mode"], "computer_use")
        self.assertEqual(len(d["steps"]), 1)
        self.assertEqual(len(d["plan"]), 1)
        self.assertIsNotNone(d["verification"])
        self.assertTrue(d["verification"]["passed"])

    def test_result_to_dict_no_verification(self):
        from core.computer_use_runner import ComputerUseResult
        r = ComputerUseResult(task="x", passed=False, mode="desktop_native", error="boom")
        d = r.to_dict()
        self.assertIsNone(d["verification"])
        self.assertEqual(d["error"], "boom")


# =============================================================================
# 入口
# =============================================================================
if __name__ == "__main__":
    unittest.main()
