"""agent-browser 第三引擎单元测试

测试覆盖：
1. AgentBrowserRunner 构造与配置解析
2. _step_to_args 原生命令风格 YAML → CLI 参数映射
3. run_command subprocess 调用与错误处理（mock subprocess）
4. run_task 多步执行 + bail-on-error
5. run_batch JSON batch 模式
6. run_task_from_yaml 端到端场景解析
7. _run_verification 集成（agent-browser snapshot/screenshot/network）

设计要点：
- 不实际启动浏览器，所有 subprocess.run 用 unittest.mock.patch 替换
- 验证 CLI 命令拼装正确性（命令名 + 参数顺序 + session 注入）
- 测试与 test_ai_agent.py 风格一致（unittest.TestCase）

三引擎架构（线2 = 本模块）：
- 线1 脚本引擎：scenario_runner + user_simulator（YAML 驱动）
- 线2 agent-browser 引擎：本模块（GLM-5.2 通过 Bash 编排，零 LLM token）
- 线3 AI 引擎：ai_agent.py（Browser Use + Qwen VL）
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
class TestAgentBrowserRunnerConstruction(unittest.TestCase):
    """AgentBrowserRunner 初始化与配置解析测试"""

    def test_init_default_session_name(self):
        """默认 session 名来自 config['agent_browser']['default_session']"""
        from core.agent_browser_runner import AgentBrowserRunner
        config = {"agent_browser": {"default_session": "real_env_test"}}
        runner = AgentBrowserRunner(config)
        self.assertEqual(runner._default_session, "real_env_test")

    def test_init_explicit_session_overrides_config(self):
        """显式 session_name 覆盖 config 默认值"""
        from core.agent_browser_runner import AgentBrowserRunner
        config = {"agent_browser": {"default_session": "from_config"}}
        runner = AgentBrowserRunner(config, session_name="override")
        self.assertEqual(runner._session_name, "override")

    def test_init_default_timeout(self):
        """默认 timeout=30s"""
        from core.agent_browser_runner import AgentBrowserRunner
        runner = AgentBrowserRunner({})
        self.assertEqual(runner._timeout, 30)

    def test_init_executable_default(self):
        """默认 executable='agent-browser'（已在 PATH）"""
        from core.agent_browser_runner import AgentBrowserRunner
        runner = AgentBrowserRunner({})
        self.assertEqual(runner._executable, "agent-browser")

    def test_init_config_values(self):
        """从 config['agent_browser'] 读取所有字段"""
        from core.agent_browser_runner import AgentBrowserRunner
        config = {
            "agent_browser": {
                "executable": "/usr/local/bin/agent-browser",
                "default_session": "my_session",
                "timeout": 60,
                "headless": False,
                "auto_verify": False,
            }
        }
        runner = AgentBrowserRunner(config)
        self.assertEqual(runner._executable, "/usr/local/bin/agent-browser")
        self.assertEqual(runner._default_session, "my_session")
        self.assertEqual(runner._timeout, 60)
        self.assertFalse(runner._headless)
        self.assertFalse(runner._auto_verify)

    def test_init_headless_default_true(self):
        """默认 headless=True"""
        from core.agent_browser_runner import AgentBrowserRunner
        runner = AgentBrowserRunner({})
        self.assertTrue(runner._headless)


# =============================================================================
# 2. _step_to_args 原生命令风格 YAML → CLI 参数映射
# =============================================================================
class TestStepToArgs(unittest.TestCase):
    """原生命令风格 YAML step → agent-browser CLI 参数映射"""

    def setUp(self):
        from core.agent_browser_runner import AgentBrowserRunner
        self.runner = AgentBrowserRunner({})

    def test_open_command(self):
        """open: url → ['open', url]"""
        step = {"open": "https://example.com/login"}
        self.assertEqual(self.runner._step_to_args(step), ["open", "https://example.com/login"])

    def test_snapshot_interactive(self):
        """snapshot: {interactive: true} → ['snapshot', '-i']"""
        step = {"snapshot": {"interactive": True}}
        self.assertEqual(self.runner._step_to_args(step), ["snapshot", "-i"])

    def test_snapshot_plain(self):
        """snapshot: {} → ['snapshot']"""
        step = {"snapshot": {}}
        self.assertEqual(self.runner._step_to_args(step), ["snapshot"])

    def test_click_command(self):
        """click: {ref: '@e1'} → ['click', '@e1']"""
        step = {"click": {"ref": "@e1"}}
        self.assertEqual(self.runner._step_to_args(step), ["click", "@e1"])

    def test_fill_command(self):
        """fill: {ref: '@e1', value: 'text'} → ['fill', '@e1', 'text']"""
        step = {"fill": {"ref": "@e1", "value": "user@example.com"}}
        self.assertEqual(
            self.runner._step_to_args(step),
            ["fill", "@e1", "user@example.com"],
        )

    def test_wait_load_networkidle(self):
        """wait: {load: networkidle} → ['wait', '--load', 'networkidle']"""
        step = {"wait": {"load": "networkidle"}}
        self.assertEqual(self.runner._step_to_args(step), ["wait", "--load", "networkidle"])

    def test_wait_text(self):
        """wait: {text: 'Welcome'} → ['wait', '--text', 'Welcome']"""
        step = {"wait": {"text": "Welcome"}}
        self.assertEqual(self.runner._step_to_args(step), ["wait", "--text", "Welcome"])

    def test_wait_selector_with_state(self):
        """wait: {selector: '#spinner', state: hidden} → ['wait', '#spinner', '--state', 'hidden']"""
        step = {"wait": {"selector": "#spinner", "state": "hidden"}}
        self.assertEqual(
            self.runner._step_to_args(step),
            ["wait", "#spinner", "--state", "hidden"],
        )

    def test_screenshot_command(self):
        """screenshot: out.png → ['screenshot', 'out.png']"""
        step = {"screenshot": "out.png"}
        self.assertEqual(self.runner._step_to_args(step), ["screenshot", "out.png"])

    def test_get_url(self):
        """get: url → ['get', 'url']"""
        step = {"get": "url"}
        self.assertEqual(self.runner._step_to_args(step), ["get", "url"])

    def test_get_text_with_ref(self):
        """get: {what: text, ref: '@e1'} → ['get', 'text', '@e1']"""
        step = {"get": {"what": "text", "ref": "@e1"}}
        self.assertEqual(self.runner._step_to_args(step), ["get", "text", "@e1"])

    def test_unknown_step_raises(self):
        """未知 step 抛出 ValueError"""
        with self.assertRaises(ValueError) as ctx:
            self.runner._step_to_args({"unknown_command": "foo"})
        self.assertIn("unknown_command", str(ctx.exception))


# =============================================================================
# 3. _build_command 命令拼装
# =============================================================================
class TestBuildCommand(unittest.TestCase):
    """CLI 命令拼装（executable + session + args）"""

    def test_command_with_session_injection(self):
        """默认 session 注入到 executable 后"""
        from core.agent_browser_runner import AgentBrowserRunner
        runner = AgentBrowserRunner(
            {"agent_browser": {"default_session": "my_sess"}},
        )
        cmd = runner._build_command(["open", "https://example.com"])
        self.assertEqual(cmd, ["agent-browser", "--session-name", "my_sess", "open", "https://example.com"])

    def test_command_with_explicit_session(self):
        """显式 session 覆盖默认"""
        from core.agent_browser_runner import AgentBrowserRunner
        runner = AgentBrowserRunner(
            {"agent_browser": {"default_session": "default"}},
        )
        cmd = runner._build_command(["snapshot", "-i"], session="explicit")
        self.assertEqual(cmd, ["agent-browser", "--session-name", "explicit", "snapshot", "-i"])

    def test_command_no_session_when_disabled(self):
        """default_session 为空且无显式 session 时不注入"""
        from core.agent_browser_runner import AgentBrowserRunner
        runner = AgentBrowserRunner({})  # 无配置
        runner._default_session = None
        cmd = runner._build_command(["snapshot"])
        self.assertEqual(cmd, ["agent-browser", "snapshot"])


# =============================================================================
# 4. run_command subprocess 调用
# =============================================================================
class TestRunCommand(unittest.TestCase):
    """run_command 调用 subprocess.run 并解析结果"""

    def setUp(self):
        from core.agent_browser_runner import AgentBrowserRunner
        self.runner = AgentBrowserRunner({"agent_browser": {"default_session": "test"}})

    @patch("core.agent_browser_runner.subprocess.run")
    def test_run_command_success(self, mock_run):
        """成功执行：exit_code=0，stdout 写入 step"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="@e1 [input type='email']\n@e2 [input type='password']",
            stderr="",
        )
        step = self.runner.run_command(["snapshot", "-i"])
        self.assertEqual(step.exit_code, 0)
        self.assertIn("@e1", step.stdout)
        self.assertEqual(step.stderr, "")
        # 验证 subprocess.run 调用参数
        called_args = mock_run.call_args
        cmd = called_args.args[0]
        self.assertEqual(cmd[0], "agent-browser")
        self.assertIn("snapshot", cmd)
        self.assertIn("-i", cmd)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_run_command_failure(self, mock_run):
        """命令失败：exit_code!=0，stderr 写入 step"""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error: element @e1 not found",
        )
        step = self.runner.run_command(["click", "@e99"])
        self.assertEqual(step.exit_code, 1)
        self.assertIn("element @e1 not found", step.stderr)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_run_command_timeout(self, mock_run):
        """超时：exit_code=-1，stderr 含 Timeout"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="agent-browser", timeout=1)
        step = self.runner.run_command(["wait", "--load", "networkidle"], timeout=1)
        self.assertEqual(step.exit_code, -1)
        self.assertIn("Timeout", step.stderr)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_run_command_uses_text_mode(self, mock_run):
        """subprocess.run 调用必须 capture_output + text=True"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.runner.run_command(["snapshot"])
        kwargs = mock_run.call_args.kwargs
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))


# =============================================================================
# 5. run_task 多步执行 + bail-on-error
# =============================================================================
class TestRunTask(unittest.TestCase):
    """run_task 多步执行逻辑"""

    def setUp(self):
        from core.agent_browser_runner import AgentBrowserRunner
        self.runner = AgentBrowserRunner({"agent_browser": {"default_session": "test"}})

    @patch("core.agent_browser_runner.subprocess.run")
    def test_run_task_all_pass(self, mock_run):
        """所有步骤通过：passed=True，4 个 step"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        steps = [
            {"open": "https://example.com"},
            {"snapshot": {"interactive": True}},
            {"fill": {"ref": "@e1", "value": "user@example.com"}},
            {"click": {"ref": "@e3"}},
        ]
        result = self.runner.run_task(steps)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.steps), 4)
        self.assertEqual(mock_run.call_count, 4)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_run_task_bail_on_error(self, mock_run):
        """步骤失败时停止后续步骤（bail-on-error）"""
        # 第2步失败
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="element not found"),
            MagicMock(returncode=0, stdout="", stderr=""),  # 不应执行
        ]
        steps = [
            {"open": "https://example.com"},
            {"click": {"ref": "@e99"}},  # 失败
            {"snapshot": {"interactive": True}},  # 不应执行
        ]
        result = self.runner.run_task(steps)
        self.assertFalse(result.passed)
        self.assertEqual(len(result.steps), 2)  # 只执行 2 步
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(result.steps[-1].exit_code, 1)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_run_task_duration_recorded(self, mock_run):
        """记录总耗时"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = self.runner.run_task([{"open": "https://example.com"}])
        self.assertGreaterEqual(result.duration_ms, 0)


# =============================================================================
# 6. run_task_from_yaml 端到端场景解析
# =============================================================================
class TestRunTaskFromYAML(unittest.TestCase):
    """run_task_from_yaml 解析场景并执行"""

    def setUp(self):
        from core.agent_browser_runner import AgentBrowserRunner
        self.runner = AgentBrowserRunner({"agent_browser": {"default_session": "test"}})

    @patch("core.agent_browser_runner.subprocess.run")
    def test_yaml_scenario_executed(self, mock_run):
        """YAML 场景被正确解析并执行"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scenario = {
            "name": "form submit",
            "mode": "agent_browser",
            "session": "form_test",
            "steps": [
                {"open": "https://example.com/login"},
                {"snapshot": {"interactive": True}},
                {"fill": {"ref": "@e1", "value": "user@example.com"}},
                {"click": {"ref": "@e3"}},
                {"wait": {"load": "networkidle"}},
            ],
        }
        result = self.runner.run_task_from_yaml(scenario)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.steps), 5)
        # 验证 session 被正确传入
        first_call_cmd = mock_run.call_args_list[0].args[0]
        self.assertIn("--session-name", first_call_cmd)
        self.assertIn("form_test", first_call_cmd)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_yaml_no_steps_returns_failure(self, mock_run):
        """YAML 缺少 steps 字段返回失败"""
        scenario = {"name": "empty", "mode": "agent_browser"}
        result = self.runner.run_task_from_yaml(scenario)
        self.assertFalse(result.passed)
        self.assertIn("steps", result.error)
        mock_run.assert_not_called()


# =============================================================================
# 7. run_batch JSON batch 模式
# =============================================================================
class TestRunBatch(unittest.TestCase):
    """run_batch 通过 stdin 传 JSON 数组"""

    def setUp(self):
        from core.agent_browser_runner import AgentBrowserRunner
        self.runner = AgentBrowserRunner({"agent_browser": {"default_session": "test"}})

    @patch("core.agent_browser_runner.subprocess.run")
    def test_batch_json_input(self, mock_run):
        """batch 模式传入 JSON 字符串到 stdin"""
        mock_run.return_value = MagicMock(returncode=0, stdout='[{"ok":true}]', stderr="")
        steps = [
            ["open", "https://example.com"],
            ["snapshot", "-i"],
        ]
        result = self.runner.run_batch(steps)
        self.assertTrue(result.passed)
        # 验证 stdin 收到 JSON
        call_kwargs = mock_run.call_args.kwargs
        self.assertIn("input", call_kwargs)
        parsed = json.loads(call_kwargs["input"])
        self.assertEqual(parsed, steps)
        # 验证命令含 batch --json
        cmd = mock_run.call_args.args[0]
        self.assertIn("batch", cmd)
        self.assertIn("--json", cmd)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_batch_bail_on_error(self, mock_run):
        """batch 失败时 passed=False"""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="batch failed")
        result = self.runner.run_batch([["open", "https://example.com"]])
        self.assertFalse(result.passed)
        self.assertIn("batch failed", result.steps[0].stderr)


# =============================================================================
# 8. _run_verification 三重验证集成
# =============================================================================
class TestVerificationIntegration(unittest.TestCase):
    """_run_verification 用 agent-browser snapshot/screenshot/network 做验证"""

    def setUp(self):
        from core.agent_browser_runner import AgentBrowserRunner
        self.runner = AgentBrowserRunner({"agent_browser": {"default_session": "test"}})

    @patch("core.agent_browser_runner.subprocess.run")
    def test_dom_verification_via_snapshot(self, mock_run):
        """DOM 断言：调用 snapshot -i，从 stdout 检查 selector"""
        # 模拟 snapshot 输出含 .dashboard 元素
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="@e1 [div class='dashboard']\n@e2 [button]",
            stderr="",
        )
        assertions = {
            "dom": [{"selector": ".dashboard", "action": "exists"}],
        }
        result = self.runner._run_verification(assertions)
        self.assertTrue(result.passed)
        # 验证调用了 snapshot 命令
        called_cmd = mock_run.call_args.args[0]
        self.assertIn("snapshot", called_cmd)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_dom_verification_missing_element(self, mock_run):
        """DOM 断言失败：snapshot 输出不含目标 selector"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="@e1 [button]\n@e2 [input]",
            stderr="",
        )
        assertions = {
            "dom": [{"selector": ".dashboard", "action": "exists"}],
        }
        result = self.runner._run_verification(assertions)
        self.assertFalse(result.passed)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_url_contains_verification(self, mock_run):
        """url_contains 断言：调用 get url，从 stdout 检查"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://example.com/dashboard", stderr="",
        )
        assertions = {"url_contains": "/dashboard"}
        result = self.runner._run_verification(assertions)
        self.assertTrue(result.passed)
        called_cmd = mock_run.call_args.args[0]
        self.assertIn("get", called_cmd)
        self.assertIn("url", called_cmd)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_url_contains_verification_failed(self, mock_run):
        """url_contains 断言失败"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://example.com/login", stderr="",
        )
        assertions = {"url_contains": "/dashboard"}
        result = self.runner._run_verification(assertions)
        self.assertFalse(result.passed)

    @patch("core.agent_browser_runner.subprocess.run")
    def test_no_assertions_returns_passed(self, mock_run):
        """无 assertions 时验证层跳过（passed=True, error=None）"""
        result = self.runner._run_verification(None)
        self.assertTrue(result.passed)
        mock_run.assert_not_called()


# =============================================================================
# 9. AgentBrowserResult 数据类
# =============================================================================
class TestAgentBrowserResult(unittest.TestCase):
    """AgentBrowserResult / AgentBrowserStep 数据类"""

    def test_step_default(self):
        from core.agent_browser_runner import AgentBrowserStep
        step = AgentBrowserStep(
            command="agent-browser snapshot", exit_code=0,
            stdout="...", stderr="", duration_ms=10.0,
        )
        self.assertEqual(step.exit_code, 0)
        self.assertEqual(step.duration_ms, 10.0)

    def test_result_default(self):
        from core.agent_browser_runner import AgentBrowserResult
        result = AgentBrowserResult(
            task="form submit", passed=True, steps=[], duration_ms=100.0,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.task, "form submit")
        self.assertIsNone(result.verification)
        self.assertIsNone(result.error)

    def test_result_to_dict(self):
        from core.agent_browser_runner import AgentBrowserResult, AgentBrowserStep
        step = AgentBrowserStep(
            command="agent-browser open https://example.com",
            exit_code=0, stdout="", stderr="", duration_ms=50.0,
        )
        result = AgentBrowserResult(
            task="t", passed=True, steps=[step], duration_ms=100.0,
        )
        d = result.to_dict()
        self.assertEqual(d["task"], "t")
        self.assertTrue(d["passed"])
        self.assertEqual(len(d["steps"]), 1)
        self.assertEqual(d["steps"][0]["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
