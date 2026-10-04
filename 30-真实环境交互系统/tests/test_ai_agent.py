"""AI Agent 引擎单元测试

测试覆盖：
1. AgentResult 数据类
2. AIAgentRunner 初始化和配置处理
3. llm_factory 的配置校验逻辑
4. 三重验证集成逻辑（mock Page）

注意：不依赖真实 browser-use 安装，所有 Browser Use 相关调用用 mock。
端到端真实测试在 browser-use 安装后通过 cli.py ai-run 进行。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAgentResult(unittest.TestCase):
    """AgentResult 数据类测试"""

    def test_default_values(self):
        from core.ai_agent import AgentResult
        result = AgentResult(task="test task", passed=True)
        self.assertEqual(result.task, "test task")
        self.assertTrue(result.passed)
        self.assertIsNone(result.final_result)
        self.assertEqual(result.steps, [])
        self.assertEqual(result.duration_ms, 0.0)
        self.assertIsNone(result.verification)
        self.assertIsNone(result.error)

    def test_to_dict(self):
        from core.ai_agent import AgentResult
        result = AgentResult(
            task="打开 example.com",
            passed=True,
            final_result="页面标题是 Example Domain",
            duration_ms=1500.0,
        )
        d = result.to_dict()
        self.assertEqual(d["task"], "打开 example.com")
        self.assertTrue(d["passed"])
        self.assertEqual(d["final_result"], "页面标题是 Example Domain")
        self.assertEqual(d["duration_ms"], 1500.0)
        self.assertEqual(d["screenshot_count"], 0)


class TestLLMFactory(unittest.TestCase):
    """LLM 工厂测试"""

    def test_validate_qwen_with_api_key(self):
        """Qwen provider 配置正确（有 API key）"""
        from core.llm_factory import validate_llm_config
        config = {"llm": {"provider": "qwen", "model": "qwen-vl-max"}}
        with patch.dict(os.environ, {"ALIBABA_CLOUD": "sk-test-key"}):
            is_valid, msg = validate_llm_config(config)
        self.assertTrue(is_valid)
        self.assertIn("qwen", msg)

    def test_validate_qwen_without_api_key(self):
        """Qwen provider 缺少 API key"""
        from core.llm_factory import validate_llm_config
        config = {"llm": {"provider": "qwen"}}
        # 清除环境变量
        env_backup = {k: v for k, v in os.environ.items()
                      if k in ("ALIBABA_CLOUD", "DASHSCOPE_API_KEY")}
        for k in env_backup:
            del os.environ[k]
        try:
            is_valid, msg = validate_llm_config(config)
            self.assertFalse(is_valid)
            self.assertIn("API key", msg)
        finally:
            os.environ.update(env_backup)

    def test_validate_unsupported_provider(self):
        """不支持的 provider"""
        from core.llm_factory import validate_llm_config
        config = {"llm": {"provider": "unknown_provider"}}
        is_valid, msg = validate_llm_config(config)
        self.assertFalse(is_valid)
        self.assertIn("Unsupported", msg)

    def test_validate_openai(self):
        """OpenAI provider"""
        from core.llm_factory import validate_llm_config
        config = {"llm": {"provider": "openai"}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            is_valid, _ = validate_llm_config(config)
        self.assertTrue(is_valid)

    def test_default_qwen_model(self):
        """默认 Qwen 模型是 qwen-vl-max（Browser Use 官方推荐）"""
        from core.llm_factory import _PROVIDER_DEFAULTS
        self.assertEqual(_PROVIDER_DEFAULTS["qwen"]["model"], "qwen-vl-max")
        self.assertTrue(_PROVIDER_DEFAULTS["qwen"]["use_vision"])

    def test_get_use_vision_qwen(self):
        """Qwen 默认启用视觉"""
        from core.llm_factory import get_use_vision
        config = {"llm": {"provider": "qwen"}}
        self.assertTrue(get_use_vision(config))

    def test_get_use_vision_ollama(self):
        """Ollama 默认不启用视觉"""
        from core.llm_factory import get_use_vision
        config = {"llm": {"provider": "ollama"}}
        self.assertFalse(get_use_vision(config))

    def test_get_use_vision_explicit_override(self):
        """显式配置覆盖默认"""
        from core.llm_factory import get_use_vision
        config = {"llm": {"provider": "qwen", "use_vision": False}}
        self.assertFalse(get_use_vision(config))


class TestAIAgentRunnerInit(unittest.TestCase):
    """AIAgentRunner 初始化测试"""

    def test_init_default(self):
        """默认初始化"""
        from core.ai_agent import AIAgentRunner
        config = {
            "ai_agent": {"max_steps": 30},
            "llm": {"provider": "qwen"},
        }
        runner = AIAgentRunner(config, browser_use_browser=None)
        self.assertEqual(runner._max_steps, 30)
        self.assertIsNone(runner._browser)
        self.assertIsNone(runner._llm)  # 懒初始化

    def test_init_default_max_steps(self):
        """默认 max_steps=50"""
        from core.ai_agent import AIAgentRunner
        runner = AIAgentRunner({}, browser_use_browser=None)
        self.assertEqual(runner._max_steps, 50)

    def test_get_current_page_no_browser(self):
        """无 Browser 时返回 None"""
        from core.ai_agent import AIAgentRunner
        runner = AIAgentRunner({}, browser_use_browser=None)
        # _get_current_page 现在是 async 方法
        import asyncio
        self.assertIsNone(asyncio.run(runner._get_current_page()))

    def test_get_current_page_with_mock_browser(self):
        """用 mock Browser 测试 Page 获取"""
        from core.ai_agent import AIAgentRunner
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_browser = MagicMock()
        mock_browser.browser_context = mock_context

        runner = AIAgentRunner({}, browser_use_browser=mock_browser)
        import asyncio
        page = asyncio.run(runner._get_current_page())
        self.assertEqual(page, mock_page)

    def test_get_current_page_fallback_to_context(self):
        """fallback 到 context 属性"""
        from core.ai_agent import AIAgentRunner
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_browser = MagicMock()
        # browser_context 不存在，但有 context
        del mock_browser.browser_context
        mock_browser.context = mock_context

        runner = AIAgentRunner({}, browser_use_browser=mock_browser)
        import asyncio
        page = asyncio.run(runner._get_current_page())
        self.assertEqual(page, mock_page)


class TestAIAgentRunWithMockLLM(unittest.TestCase):
    """用 mock LLM 测试 run_task 流程"""

    @patch("core.ai_agent.create_llm")
    def test_run_task_llm_init_failure(self, mock_create_llm):
        """LLM 初始化失败时返回失败结果"""
        from core.ai_agent import AIAgentRunner
        mock_create_llm.side_effect = ValueError("API key missing")

        runner = AIAgentRunner(
            {"llm": {"provider": "qwen"}},
            browser_use_browser=None,
        )
        import asyncio
        result = asyncio.run(runner.run_task("test task"))

        self.assertFalse(result.passed)
        self.assertIn("LLM init failed", result.error)

    @patch("core.ai_agent.create_llm")
    @patch("core.ai_agent.get_use_vision", return_value=True)
    def test_run_task_browser_use_not_installed(self, mock_vision, mock_create_llm):
        """browser-use 未安装时返回明确错误"""
        mock_llm = MagicMock()
        mock_create_llm.return_value = mock_llm

        # 模拟 import browser_use 失败
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "browser_use":
                raise ImportError("No module named 'browser_use'")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = mock_import
        try:
            from core.ai_agent import AIAgentRunner
            runner = AIAgentRunner(
                {"llm": {"provider": "qwen"}, "ai_agent": {"max_steps": 10}},
                browser_use_browser=None,
            )
            import asyncio
            result = asyncio.run(runner.run_task("test task"))

            self.assertFalse(result.passed)
            self.assertIn("browser-use", result.error)
        finally:
            builtins.__import__ = original_import


class TestVerificationIntegration(unittest.TestCase):
    """三重验证集成测试"""

    @patch("core.ai_agent.create_llm")
    def test_verification_no_browser_returns_failure(self, mock_create_llm):
        """无 Browser 时验证层返回失败（降级为未执行）"""
        from core.ai_agent import AIAgentRunner, AgentResult
        from core.result_verifier import VerificationResult
        mock_create_llm.return_value = MagicMock()

        runner = AIAgentRunner(
            {"llm": {"provider": "qwen"}},
            browser_use_browser=None,
        )
        import asyncio
        result = asyncio.run(runner._run_verification({"dom": []}))

        self.assertIsNotNone(result)
        self.assertFalse(result.passed)
        self.assertIn("Cannot access", result.error)


if __name__ == "__main__":
    unittest.main()
