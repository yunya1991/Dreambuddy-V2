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
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from core.agents import BullAgent, BearAgent, JudgeAgent
from core.bot_handler import CommandHandler
from core.config import AppConfig, load_config
from core.llm_adapter import create_llm_adapter
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
    models = config.debate.models

    # ─── LLM 适配器（按角色分档模型） ──────────────────────────
    debater_llm = create_llm_adapter(model_name=models.get("debater", "qwen-turbo"))
    judge_llm = create_llm_adapter(model_name=models.get("judge", "qwen-plus"))
    marketing_llm = create_llm_adapter(model_name=models.get("marketing", "qwen-plus"))
    quality_llm = create_llm_adapter(model_name=models.get("quality", "qwen-plus"))

    # ─── Agent ───────────────────────────────────────────────
    bull_agent = BullAgent(debater_llm)
    bear_agent = BearAgent(debater_llm)
    judge_agent = JudgeAgent(judge_llm) if config.debate.judge_enabled else None

    # ─── 营销 + 质量 ──────────────────────────────────────────
    marketing_extractor = MarketingExtractor(marketing_llm)
    quality_evaluator = QualityEvaluator(quality_llm)

    # ─── Telegram Bot ────────────────────────────────────────
    bull_tg = TelegramHTTPClient(token=config.telegram.bull_token)
    bear_tg = TelegramHTTPClient(token=config.telegram.bear_token)
    judge_tg = (
        TelegramHTTPClient(token=config.telegram.judge_token)
        if config.telegram.judge_token else None
    )

    telegram_dual_bot = TelegramDualBot(
        bull_bot=bull_tg, bear_bot=bear_tg, judge_bot=judge_tg,
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
    logger.info("配置加载完成: max_rounds=%d judge_enabled=%s",
                config.debate.max_rounds, config.debate.judge_enabled)

    app = build_app(config)
    logger.info("应用装配完成，启动 Telegram 监听器...")

    try:
        asyncio.run(app.listener.run())
    except KeyboardInterrupt:
        logger.info("收到中断信号，停止监听")
        app.listener.stop()


if __name__ == "__main__":
    main()
