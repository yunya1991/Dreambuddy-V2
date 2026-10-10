"""test_main.py — build_app 工厂装配测试（TDD RED phase）

测试 P0-4：main.py 的 build_app(config) 工厂函数，
将 config 装配为完整的 DebateApp（含 listener + orchestrator + agents）。

build_app 应：
1. 用 debate.models 配置创建不同角色的 LLM 适配器
2. 创建 BullAgent / BearAgent / JudgeAgent（judge_enabled 控制）
3. 创建 MarketingExtractor / QualityEvaluator
4. 用 telegram.bull_token/bear_token/judge_token 创建 TelegramHTTPClient
5. 创建 TelegramDualBot
6. 创建 DebateOrchestrator
7. 创建 CommandHandler
8. 创建 TelegramListener 并返回
"""
from __future__ import annotations

import pytest

from core.config import AppConfig, DebateConfig, TelegramConfig
from core.listener import TelegramListener
from core.orchestrator import DebateOrchestrator
from core.telegram_bot import TelegramDualBot


def make_config(**overrides) -> AppConfig:
    """构造测试用 AppConfig。"""
    debate = DebateConfig(
        max_rounds=2, judge_enabled=True,
        models={"debater": "qwen-turbo", "judge": "qwen-plus",
                "marketing": "qwen-plus", "quality": "qwen-plus"},
    )
    telegram = TelegramConfig(
        bull_token="bull_token", bear_token="bear_token",
        judge_token="judge_token", allowed_chat_ids=[],
        message_interval_sec=1.0,
    )
    cfg = AppConfig(debate=debate, telegram=telegram)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# ─── build_app 基本装配测试 ──────────────────────────────────────

class TestBuildApp:

    def test_build_app_returns_listener(self, monkeypatch):
        """build_app 返回 TelegramListener 实例。"""
        import main

        # mock LLM 适配器创建（避免真实 API）
        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        cfg = make_config()
        app = main.build_app(cfg)
        assert isinstance(app.listener, TelegramListener)

    def test_build_app_wires_orchestrator(self, monkeypatch):
        """build_app 装配的 listener 内含 orchestrator。"""
        import main

        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        cfg = make_config()
        app = main.build_app(cfg)
        assert isinstance(app.orchestrator, DebateOrchestrator)

    def test_build_app_judge_disabled(self, monkeypatch):
        """judge_enabled=False 时不创建 judge_agent。"""
        import main

        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        cfg = make_config()
        cfg.debate.judge_enabled = False
        app = main.build_app(cfg)
        assert app.orchestrator.judge_agent is None

    def test_build_app_judge_enabled(self, monkeypatch):
        """judge_enabled=True 时创建 judge_agent。"""
        import main

        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        cfg = make_config()
        app = main.build_app(cfg)
        assert app.orchestrator.judge_agent is not None

    def test_build_app_telegram_dual_bot_has_bull_bear(self, monkeypatch):
        """TelegramDualBot 有 bull 和 bear bot。"""
        import main

        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        cfg = make_config()
        app = main.build_app(cfg)
        dual_bot = app.orchestrator.telegram_dual_bot
        assert isinstance(dual_bot, TelegramDualBot)
        assert dual_bot.bull is not None
        assert dual_bot.bear is not None

    def test_build_app_judge_token_null_no_judge_bot(self, monkeypatch):
        """judge_token=None 时 dual_bot.judge 为 None。"""
        import main

        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        cfg = make_config()
        cfg.telegram.judge_token = None
        app = main.build_app(cfg)
        assert app.orchestrator.telegram_dual_bot.judge is None


# ─── 辅助 ────────────────────────────────────────────────────────

class _FakeLLM:
    """模拟 LLMAdapter（不做真实调用）。"""

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int = 600) -> str:
        return '{"thesis": "test", "arguments": [], "quote": "", "confidence": 0.5}'
