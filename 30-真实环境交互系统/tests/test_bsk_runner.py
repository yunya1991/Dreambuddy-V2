"""bsk 第四引擎单元测试 — 腾讯 BrowserSkill CLI 包装

测试覆盖：
1. BskRunner 构造与配置解析
2. _step_to_args 原生命令风格 YAML → bsk CLI 参数映射（重点覆盖 bsk 独特命令）
3. _build_command 命令拼装（含 --json 全局 flag + session）
4. run_command subprocess 调用与错误处理（mock subprocess）
5. run_task 多步执行 + bail-on-error + callback hook
6. run_task_from_yaml 端到端场景解析
7. _run_verification 集成（snapshot/observe/get-html/network）
8. BskResult/BskStep 数据类

设计要点：
- 不实际启动浏览器，所有 subprocess.run 用 unittest.mock.patch 替换
- 验证 CLI 命令拼装正确性（命令名 + 参数顺序 + --json + session）
- 测试与 test_agent_browser_runner.py 风格一致（unittest.TestCase）

四引擎架构（线4 = 本模块）：
- 线1 脚本引擎：scenario_runner + user_simulator（YAML + Playwright）
- 线2 agent-browser 引擎：agent_browser_runner（GLM-5.2 + CLI）
- 线3 AI 引擎：ai_agent.py（Browser Use + Qwen VL）
- 线4 bsk 引擎：本模块（腾讯 BrowserSkill CLI，DSH 原生）

bsk CLI v0.3.2 路径：/Users/zhangjiangtao/.local/bin/bsk
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# 1. 构造与配置
# =============================================================================
class TestBskRunnerConstruction(unittest.TestCase):
    """BskRunner 初始化与配置解析"""

    def test_init_default_session_name(self):
        """默认 session 来自 config['bsk']['default_session']"""
        from core.bsk_runner import BskRunner
        config = {"bsk": {"default_session": "real_env_test"}}
        runner = BskRunner(config)
        self.assertEqual(runner._default_session, "real_env_test")

    def test_init_explicit_session_overrides_config(self):
        """显式 session_name 覆盖 config"""
        from core.bsk_runner import BskRunner
        config = {"bsk": {"default_session": "from_config"}}
        runner = BskRunner(config, session_name="override")
        self.assertEqual(runner._session_name, "override")

    def test_init_default_timeout(self):
        """默认 timeout=120s（bsk 命令默认 120000ms）"""
        from core.bsk_runner import BskRunner
        runner = BskRunner({})
        self.assertEqual(runner._timeout, 120)

    def test_init_executable_default(self):
        """默认 executable='bsk'（已在 PATH）"""
        from core.bsk_runner import BskRunner
        runner = BskRunner({})
        self.assertEqual(runner._executable, "bsk")

    def test_init_config_values(self):
        """从 config['bsk'] 读取所有字段"""
        from core.bsk_runner import BskRunner
        config = {
            "bsk": {
                "executable": "/usr/local/bin/bsk",
                "default_session": "my_sess",
                "timeout": 60,
                "json_output": False,
                "auto_verify": False,
            }
        }
        runner = BskRunner(config)
        self.assertEqual(runner._executable, "/usr/local/bin/bsk")
        self.assertEqual(runner._default_session, "my_sess")
        self.assertEqual(runner._timeout, 60)
        self.assertFalse(runner._json_output)
        self.assertFalse(runner._auto_verify)

    def test_init_json_output_default_true(self):
        """默认 json_output=True（bsk --json 输出结构化数据）"""
        from core.bsk_runner import BskRunner
        runner = BskRunner({})
        self.assertTrue(runner._json_output)


# =============================================================================
# 2. _step_to_args 原生命令风格 YAML → bsk CLI 参数映射
# =============================================================================
class TestStepToArgs(unittest.TestCase):
    """YAML step → bsk CLI 参数映射"""

    def setUp(self):
        from core.bsk_runner import BskRunner
        self.runner = BskRunner({})

    def test_navigate_command(self):
        """navigate: url → ['navigate', url]"""
        step = {"navigate": "https://example.com/login"}
        self.assertEqual(self.runner._step_to_args(step), ["navigate", "https://example.com/login"])

    def test_navigate_back(self):
        """navigate-back: {} → ['navigate-back']"""
        self.assertEqual(self.runner._step_to_args({"navigate-back": {}}), ["navigate-back"])

    def test_navigate_forward(self):
        """navigate-forward: {} → ['navigate-forward']"""
        self.assertEqual(self.runner._step_to_args({"navigate-forward": {}}), ["navigate-forward"])

    def test_reload(self):
        """reload: {} → ['reload']"""
        self.assertEqual(self.runner._step_to_args({"reload": {}}), ["reload"])

    def test_snapshot_plain(self):
        """snapshot: {} → ['snapshot']"""
        self.assertEqual(self.runner._step_to_args({"snapshot": {}}), ["snapshot"])

    def test_observe_command(self):
        """observe: {} → ['observe']（bsk 独特：语义化 VOM 观察）"""
        self.assertEqual(self.runner._step_to_args({"observe": {}}), ["observe"])

    def test_screenshot_with_path(self):
        """screenshot: {path: 'out.png'} → ['screenshot', '--path', 'out.png']"""
        step = {"screenshot": {"path": "out.png"}}
        result = self.runner._step_to_args(step)
        self.assertEqual(result[0], "screenshot")
        self.assertIn("--path", result)
        self.assertIn("out.png", result)

    def test_click_command(self):
        """click: {ref: '@e1'} → ['click', '@e1']"""
        step = {"click": {"ref": "@e1"}}
        self.assertEqual(self.runner._step_to_args(step), ["click", "@e1"])

    def test_hover_command(self):
        """hover: {ref: '@e1'} → ['hover', '@e1']（bsk 独特）"""
        step = {"hover": {"ref": "@e1"}}
        self.assertEqual(self.runner._step_to_args(step), ["hover", "@e1"])

    def test_fill_command(self):
        """fill: {ref: '@e1', value: 'text'} → ['fill', '@e1', 'text']"""
        step = {"fill": {"ref": "@e1", "value": "user@example.com"}}
        self.assertEqual(self.runner._step_to_args(step), ["fill", "@e1", "user@example.com"])

    def test_press_command(self):
        """press: {key: 'Enter'} → ['press', 'Enter']（bsk 独特）"""
        step = {"press": {"key": "Enter"}}
        self.assertEqual(self.runner._step_to_args(step), ["press", "Enter"])

    def test_select_command(self):
        """select: {ref: '@e1', value: 'opt1'} → ['select', '@e1', 'opt1']（bsk 独特）"""
        step = {"select": {"ref": "@e1", "value": "opt1"}}
        self.assertEqual(self.runner._step_to_args(step), ["select", "@e1", "opt1"])

    def test_focus_command(self):
        """focus: {ref: '@e1'} → ['focus', '@e1']（bsk 独特）"""
        step = {"focus": {"ref": "@e1"}}
        self.assertEqual(self.runner._step_to_args(step), ["focus", "@e1"])

    def test_blur_command(self):
        """blur: {ref: '@e1'} → ['blur', '@e1']（bsk 独特）"""
        step = {"blur": {"ref": "@e1"}}
        self.assertEqual(self.runner._step_to_args(step), ["blur", "@e1"])

    def test_scroll_to_command(self):
        """scroll-to: {ref: '@e1'} → ['scroll-to', '@e1']（bsk 独特）"""
        step = {"scroll-to": {"ref": "@e1"}}
        self.assertEqual(self.runner._step_to_args(step), ["scroll-to", "@e1"])

    def test_wait_for_navigation(self):
        """wait-for-navigation: {} → ['wait-for-navigation']"""
        self.assertEqual(self.runner._step_to_args({"wait-for-navigation": {}}), ["wait-for-navigation"])

    def test_wait_ms(self):
        """wait-ms: {ms: 500} → ['wait-ms', '500']"""
        step = {"wait-ms": {"ms": 500}}
        self.assertEqual(self.runner._step_to_args(step), ["wait-ms", "500"])

    def test_console_command(self):
        """console: {} → ['console']（bsk 独特：读控制台日志）"""
        self.assertEqual(self.runner._step_to_args({"console": {}}), ["console"])

    def test_network_command(self):
        """network: {} → ['network']"""
        self.assertEqual(self.runner._step_to_args({"network": {}}), ["network"])

    def test_get_html_plain(self):
        """get-html: {} → ['get-html']（bsk 独特）"""
        self.assertEqual(self.runner._step_to_args({"get-html": {}}), ["get-html"])

    def test_get_html_with_ref(self):
        """get-html: {ref: '@e1'} → ['get-html', '@e1']"""
        step = {"get-html": {"ref": "@e1"}}
        self.assertEqual(self.runner._step_to_args(step), ["get-html", "@e1"])

    def test_emulate_command(self):
        """emulate: {device: 'iPhone 14'} → ['emulate', '--device', 'iPhone 14']（bsk 独特）"""
        step = {"emulate": {"device": "iPhone 14"}}
        result = self.runner._step_to_args(step)
        self.assertEqual(result[0], "emulate")
        self.assertIn("--device", result)
        self.assertIn("iPhone 14", result)

    def test_request_help_command(self):
        """request-help: {prompt: '请完成验证码'} → ['request-help', '--prompt', '请完成验证码']（bsk 独特：反爬虫关键）"""
        step = {"request-help": {"prompt": "请完成验证码"}}
        result = self.runner._step_to_args(step)
        self.assertEqual(result[0], "request-help")
        self.assertIn("--prompt", result)
        self.assertIn("请完成验证码", result)

    def test_evaluate_command(self):
        """evaluate: {expression: 'document.title'} → ['evaluate', 'document.title']（bsk 独特）"""
        step = {"evaluate": {"expression": "document.title"}}
        self.assertEqual(self.runner._step_to_args(step), ["evaluate", "document.title"])

    def test_unknown_step_raises(self):
        """未知 step 抛出 ValueError"""
        with self.assertRaises(ValueError) as ctx:
            self.runner._step_to_args({"unknown_command": "foo"})
        self.assertIn("unknown_command", str(ctx.exception))


# =============================================================================
# 3. _build_command 命令拼装（含 --json + session）
# =============================================================================
class TestBuildCommand(unittest.TestCase):
    """bsk CLI 命令拼装"""

    def test_command_with_json_and_session(self):
        """--json 全局 flag + session 注入"""
        from core.bsk_runner import BskRunner
        runner = BskRunner({"bsk": {"default_session": "my_sess"}})
        cmd = runner._build_command(["snapshot"])
        # 期望：['bsk', '--json', 'snapshot'] 或带 session
        self.assertEqual(cmd[0], "bsk")
        self.assertIn("--json", cmd)
        self.assertIn("snapshot", cmd)

    def test_command_no_session_when_disabled(self):
        """default_session 为空且无显式 session 时不注入"""
        from core.bsk_runner import BskRunner
        runner = BskRunner({})
        runner._default_session = None
        runner._session_name = None
        cmd = runner._build_command(["snapshot"])
        self.assertEqual(cmd[0], "bsk")
        self.assertIn("--json", cmd)
        self.assertNotIn("--session", cmd)

    def test_command_no_json_when_disabled(self):
        """json_output=False 时不注入 --json"""
        from core.bsk_runner import BskRunner
        runner = BskRunner({"bsk": {"json_output": False}})
        cmd = runner._build_command(["snapshot"])
        self.assertNotIn("--json", cmd)


# =============================================================================
# 4. run_command subprocess 调用
# =============================================================================
class TestRunCommand(unittest.TestCase):
    """run_command 调用 subprocess.run 并解析结果"""

    def setUp(self):
        from core.bsk_runner import BskRunner
        self.runner = BskRunner({"bsk": {"default_session": "test"}})

    @patch("core.bsk_runner.subprocess.run")
    def test_run_command_success(self, mock_run):
        """成功执行：exit_code=0"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"ok":true,"ref":"@e1"}', stderr="",
        )
        step = self.runner.run_command(["snapshot"])
        self.assertEqual(step.exit_code, 0)
        self.assertIn("@e1", step.stdout)
        # 验证 subprocess.run 调用
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], "bsk")

    @patch("core.bsk_runner.subprocess.run")
    def test_run_command_failure(self, mock_run):
        """命令失败：exit_code!=0"""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error: element not found",
        )
        step = self.runner.run_command(["click", "@e99"])
        self.assertEqual(step.exit_code, 1)
        self.assertIn("element not found", step.stderr)

    @patch("core.bsk_runner.subprocess.run")
    def test_run_command_timeout(self, mock_run):
        """超时：exit_code=-1"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bsk", timeout=1)
        step = self.runner.run_command(["wait-for-navigation"], timeout=1)
        self.assertEqual(step.exit_code, -1)
        self.assertIn("Timeout", step.stderr)

    @patch("core.bsk_runner.subprocess.run")
    def test_run_command_text_mode(self, mock_run):
        """subprocess.run 必须 capture_output + text=True"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.runner.run_command(["snapshot"])
        kwargs = mock_run.call_args.kwargs
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))


# =============================================================================
# 5. run_task 多步执行 + bail-on-error + callback
# =============================================================================
class TestRunTask(unittest.TestCase):
    """run_task 多步执行"""

    def setUp(self):
        from core.bsk_runner import BskRunner
        self.runner = BskRunner({"bsk": {"default_session": "test"}})

    @patch("core.bsk_runner.subprocess.run")
    def test_run_task_all_pass(self, mock_run):
        """所有步骤通过"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        steps = [
            {"navigate": "https://example.com"},
            {"snapshot": {}},
            {"fill": {"ref": "@e1", "value": "user@example.com"}},
            {"click": {"ref": "@e3"}},
        ]
        result = self.runner.run_task(steps)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.steps), 4)
        self.assertEqual(mock_run.call_count, 4)

    @patch("core.bsk_runner.subprocess.run")
    def test_run_task_bail_on_error(self, mock_run):
        """步骤失败时停止后续"""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="failed"),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        steps = [
            {"navigate": "https://example.com"},
            {"click": {"ref": "@e99"}},
            {"snapshot": {}},
        ]
        result = self.runner.run_task(steps)
        self.assertFalse(result.passed)
        self.assertEqual(len(result.steps), 2)
        self.assertEqual(mock_run.call_count, 2)

    @patch("core.bsk_runner.subprocess.run")
    def test_run_task_callback_hook(self, mock_run):
        """callback hook 可中断任务"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        callback = MagicMock(side_effect=[True, False])  # 第二次返回 False
        steps = [
            {"navigate": "https://example.com"},
            {"snapshot": {}},
            {"click": {"ref": "@e1"}},  # 不应执行
        ]
        result = self.runner.run_task(steps, callback=callback)
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(mock_run.call_count, 2)  # 第三步不执行


# =============================================================================
# 6. run_task_from_yaml 端到端场景
# =============================================================================
class TestRunTaskFromYAML(unittest.TestCase):
    """run_task_from_yaml"""

    def setUp(self):
        from core.bsk_runner import BskRunner
        self.runner = BskRunner({"bsk": {"default_session": "test"}})

    @patch("core.bsk_runner.subprocess.run")
    def test_yaml_scenario_executed(self, mock_run):
        """YAML 场景被解析执行"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scenario = {
            "name": "bsk form test",
            "mode": "bsk",
            "session": "form_test",
            "steps": [
                {"navigate": "https://example.com/login"},
                {"snapshot": {}},
                {"fill": {"ref": "@e1", "value": "user@example.com"}},
                {"click": {"ref": "@e3"}},
                {"wait-for-navigation": {}},
            ],
        }
        result = self.runner.run_task_from_yaml(scenario)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.steps), 5)

    def test_yaml_no_steps_returns_failure(self):
        """YAML 缺 steps 字段返回失败"""
        scenario = {"name": "empty", "mode": "bsk"}
        result = self.runner.run_task_from_yaml(scenario)
        self.assertFalse(result.passed)
        self.assertIn("steps", result.error)


# =============================================================================
# 7. _run_verification 验证集成
# =============================================================================
class TestVerificationIntegration(unittest.TestCase):
    """_run_verification 用 bsk snapshot/observe/get-html/network 验证"""

    def setUp(self):
        from core.bsk_runner import BskRunner
        self.runner = BskRunner({"bsk": {"default_session": "test"}})

    @patch("core.bsk_runner.subprocess.run")
    def test_dom_verification_via_snapshot(self, mock_run):
        """DOM 断言：调用 snapshot，从 stdout 检查 selector"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='@e1 [div class="dashboard"]\n@e2 [button]',
            stderr="",
        )
        assertions = {"dom": [{"selector": ".dashboard", "action": "exists"}]}
        result = self.runner._run_verification(assertions)
        self.assertTrue(result.passed)
        called_cmd = mock_run.call_args.args[0]
        self.assertIn("snapshot", called_cmd)

    @patch("core.bsk_runner.subprocess.run")
    def test_dom_verification_missing_element(self, mock_run):
        """DOM 断言失败"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='@e1 [button]\n@e2 [input]',
            stderr="",
        )
        assertions = {"dom": [{"selector": ".dashboard", "action": "exists"}]}
        result = self.runner._run_verification(assertions)
        self.assertFalse(result.passed)

    @patch("core.bsk_runner.subprocess.run")
    def test_url_contains_verification(self, mock_run):
        """url_contains：用 navigate 后检查页面 url（用 get-html 或 snapshot 间接）"""
        # bsk 没有 get url 命令，用 evaluate 'location.href' 替代
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"result":"https://example.com/dashboard"}',
            stderr="",
        )
        assertions = {"url_contains": "/dashboard"}
        result = self.runner._run_verification(assertions)
        self.assertTrue(result.passed)
        called_cmd = mock_run.call_args.args[0]
        self.assertIn("evaluate", called_cmd)

    @patch("core.bsk_runner.subprocess.run")
    def test_console_verification(self, mock_run):
        """console 断言：检查浏览器控制台日志（bsk 独特）"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='[{"level":"error","text":"Uncaught TypeError"}]',
            stderr="",
        )
        assertions = {"console_no_errors": True}
        result = self.runner._run_verification(assertions)
        self.assertFalse(result.passed)  # 有 error 所以失败
        called_cmd = mock_run.call_args.args[0]
        self.assertIn("console", called_cmd)

    def test_no_assertions_returns_passed(self):
        """无 assertions 时验证层跳过"""
        result = self.runner._run_verification(None)
        self.assertTrue(result.passed)


# =============================================================================
# 8. 数据类
# =============================================================================
class TestBskResult(unittest.TestCase):
    """BskResult / BskStep 数据类"""

    def test_step_default(self):
        from core.bsk_runner import BskStep
        step = BskStep(
            command="bsk snapshot", exit_code=0,
            stdout="...", stderr="", duration_ms=10.0,
        )
        self.assertEqual(step.exit_code, 0)

    def test_result_default(self):
        from core.bsk_runner import BskResult
        result = BskResult(
            task="form submit", passed=True, steps=[], duration_ms=100.0,
        )
        self.assertTrue(result.passed)
        self.assertIsNone(result.verification)
        self.assertIsNone(result.error)

    def test_result_to_dict(self):
        from core.bsk_runner import BskResult, BskStep
        step = BskStep(
            command="bsk navigate https://example.com",
            exit_code=0, stdout="", stderr="", duration_ms=50.0,
        )
        result = BskResult(
            task="t", passed=True, steps=[step], duration_ms=100.0,
        )
        d = result.to_dict()
        self.assertEqual(d["task"], "t")
        self.assertTrue(d["passed"])
        self.assertEqual(len(d["steps"]), 1)


if __name__ == "__main__":
    unittest.main()
