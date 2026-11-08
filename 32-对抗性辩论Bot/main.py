"""main.py — 对抗性辩论 Bot 主入口

P0-4：装配所有组件并启动 Telegram 监听器。

装配流程：
1. 加载 config.yaml
2. 用 debate.models 配置创建不同角色的 LLM 适配器
3. 创建 BullAgent / BearAgent / JudgeAgent（judge_enabled 控制）
4. 创建 MarketingExtractor / QualityEvaluator
5. 用 telegram tokens 创建 TelegramHTTPClient（bull/bear/judge）
6. 创建 TelegramDualBot
7. 创建 DebateOrchestrator
8. 创建 CommandHandler
9. 创建 TelegramListener（用 bull bot 接收消息）
10. 启动长轮询
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from core.agents import BullAgent, BearAgent, JudgeAgent
from core.bot_handler import CommandHandler
from core.config import AppConfig, LLMConfig, load_config
from core.llm_compat import LLMSettings, create_llm_client
from core.listener import TelegramListener
from core.marketing import MarketingExtractor
from core.orchestrator import DebateOrchestrator
from core.quality import QualityEvaluator
from core.telegram_adapter import TelegramHTTPClient
from core.telegram_bot import TelegramDualBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("debate.main")


def create_llm_adapter(
    config: LLMConfig | dict | None = None,
    model_name: str | None = None,
):
    """创建 LLM 客户端（兼容旧 `create_llm_adapter` 调用点）。

    - config=LLMConfig：使用新配置（provider/base_url/api_key/timeout）
    - config=dict：显式 provider/model
    - config=None：自动探测（Anthropic 代理优先，其次 OpenAI 兼容）
    """
    if isinstance(config, LLMConfig):
        settings = LLMSettings(
            provider=config.provider,
            model=model_name,
            base_url=config.base_url,
            api_key=config.api_key,
            timeout_sec=config.timeout_sec,
            max_retries=config.max_retries,
            max_tokens=int(config.max_tokens.get("debater", 2000)),
        )
    elif isinstance(config, dict):
        settings = LLMSettings(
            provider=str(config.get("provider", "auto")),
            model=model_name or config.get("model"),
            base_url=config.get("base_url"),
            api_key=config.get("api_key"),
            timeout_sec=float(config.get("timeout_sec", 90.0)),
            max_retries=int(config.get("max_retries", 2)),
            max_tokens=int(config.get("max_tokens", 2000)),
        )
    else:
        settings = LLMSettings(model=model_name)
    return create_llm_client(settings)


@dataclass
class DebateApp:
    """装配完成的应用对象。"""

    listener: TelegramListener
    orchestrator: DebateOrchestrator
    command_handler: CommandHandler
    telegram_dual_bot: TelegramDualBot
    config: AppConfig


def build_app(config: AppConfig) -> DebateApp:
    """根据 config 装配完整应用。

    Args:
        config: AppConfig 配置

    Returns:
        DebateApp 实例
    """
    debate_models = config.debate.models
    llm_models = config.llm.models

    def _model(role: str, default: str) -> str:
        return llm_models.get(role) or debate_models.get(role) or default

    def _max_tokens(role: str, default: int) -> int:
        return int(config.llm.max_tokens.get(role, default))

    # ─── LLM 适配器（按角色分档模型；与 LangChain 解耦） ──────
    debater_llm = create_llm_adapter(config=config.llm, model_name=_model("debater", "qwen-turbo"))
    judge_llm = create_llm_adapter(config=config.llm, model_name=_model("judge", "qwen-plus"))
    marketing_llm = create_llm_adapter(
        config=config.llm, model_name=_model("marketing", "qwen-plus")
    )
    quality_llm = create_llm_adapter(config=config.llm, model_name=_model("quality", "qwen-plus"))

    # ─── Agent ───────────────────────────────────────────────
    profile = config.debate.profile
    bull_agent = BullAgent(
        debater_llm,
        max_tokens=_max_tokens("debater", 2000),
        profile=profile,
    )
    bear_agent = BearAgent(
        debater_llm,
        max_tokens=_max_tokens("debater", 2000),
        profile=profile,
    )
    judge_agent = (
        JudgeAgent(judge_llm, max_tokens=_max_tokens("judge", 1600), profile=profile)
        if config.debate.judge_enabled
        else None
    )

    # ─── 营销 + 质量 ──────────────────────────────────────────
    marketing_extractor = MarketingExtractor(
        marketing_llm,
        max_tokens=_max_tokens("marketing", 1000),
    )
    quality_evaluator = QualityEvaluator(
        quality_llm,
        max_tokens=_max_tokens("quality", 1000),
    )

    # ─── Telegram Bot ────────────────────────────────────────
    bull_tg = TelegramHTTPClient(token=config.telegram.bull_token)
    bear_tg = TelegramHTTPClient(token=config.telegram.bear_token)
    judge_tg = (
        TelegramHTTPClient(token=config.telegram.judge_token)
        if config.telegram.judge_token
        else None
    )

    telegram_dual_bot = TelegramDualBot(
        bull_bot=bull_tg,
        bear_bot=bear_tg,
        judge_bot=judge_tg,
        send_delay=config.telegram.message_interval_sec,
    )

    # ─── Orchestrator ────────────────────────────────────────
    pause_timeout = config.debate.pause_timeout_minutes * 60
    orchestrator = DebateOrchestrator(
        bull_agent=bull_agent,
        bear_agent=bear_agent,
        judge_agent=judge_agent,
        marketing_extractor=marketing_extractor,
        quality_evaluator=quality_evaluator,
        telegram_dual_bot=telegram_dual_bot,
        pause_timeout=pause_timeout,
        cross_examination=config.debate.cross_examination,
        profile=profile,
    )

    # ─── CommandHandler + Listener ───────────────────────────
    command_handler = CommandHandler(
        orchestrator=orchestrator,
        telegram_bot=telegram_dual_bot,
        config=config,
    )

    # Listener 用 bull bot 接收消息（bull 是主 bot）
    listener = TelegramListener(
        telegram_client=bull_tg,
        command_handler=command_handler,
    )

    return DebateApp(
        listener=listener,
        orchestrator=orchestrator,
        command_handler=command_handler,
        telegram_dual_bot=telegram_dual_bot,
        config=config,
    )


def main(config_path: str | None = None):
    """主入口：加载配置 → 装配 → 启动监听。"""
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent / "config.yaml")

    config = load_config(config_path)
    logger.info(
        "配置加载完成: max_rounds=%d judge_enabled=%s",
        config.debate.max_rounds,
        config.debate.judge_enabled,
    )

    app = build_app(config)
    logger.info("应用装配完成，启动 Telegram 监听器...")

    try:
        asyncio.run(app.listener.run())
    except KeyboardInterrupt:
        logger.info("收到中断信号，停止监听")
        app.listener.stop()


if __name__ == "__main__":
    main()
