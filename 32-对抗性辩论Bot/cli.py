"""cli.py — 手动触发辩论的 CLI 调试入口

P1：不依赖 Telegram，直接在终端运行一场辩论并查看输出。
便于本地调试 LLM 输出、prompt 效果、营销素材生成等。

用法：
    python cli.py "BTC 是数字黄金"
    python cli.py "BTC 是数字黄金" --rounds 3 --no-judge
    python cli.py "BTC 是数字黄金" --background "BTC 2024年减半" --output result.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from core.config import AppConfig, load_config
from core.models import DebateResult
from core.orchestrator import DebateOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("debate.cli")


# ─── 静默 Telegram Bot（CLI 模式不发真实消息） ───────────────────

class QuietTelegramBot:
    """CLI 模式用：实现 TelegramBotClient Protocol，不发真实消息，仅打印。"""

    def __init__(self, role: str = ""):
        self.role = role

    async def send_message(self, chat_id: int, text: str) -> dict:
        role_name = {"bull": "正方", "bear": "反方", "judge": "裁判"}.get(self.role, self.role)
        print(f"\n{'='*50}")
        print(f"【{role_name}】")
        print(f"{'='*50}")
        print(text)
        return {"message_id": 0}


# ─── argparse ────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数。"""
    parser = argparse.ArgumentParser(
        description="对抗性辩论 Bot — 手动触发辩论（调试用）",
    )
    parser.add_argument("topic", help="辩论话题")
    parser.add_argument("--rounds", type=int, default=2,
                        help="辩论轮次（默认 2）")
    parser.add_argument("--background", default="",
                        help="背景材料（可选）")
    parser.add_argument("--judge", dest="judge", action="store_true",
                        default=True, help="启用裁判（默认）")
    parser.add_argument("--no-judge", dest="judge", action="store_false",
                        help="禁用裁判")
    parser.add_argument("--config", default=None,
                        help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--output", default=None,
                        help="将完整结果保存为 JSON 文件")
    return parser.parse_args(argv)


# ─── 运行辩论 ────────────────────────────────────────────────────

def run_cli(topic: str, rounds: int = 2, background: str = "",
            judge: bool = True, output: str | None = None,
            config_path: str | None = None) -> DebateResult:
    """运行一场辩论并返回结果。

    Args:
        topic: 辩论话题
        rounds: 辩论轮次
        background: 背景材料
        judge: 是否启用裁判
        output: 结果 JSON 输出路径
        config_path: 配置文件路径

    Returns:
        DebateResult
    """
    # 加载配置（CLI 模式不使用 Telegram，预置 dummy token 避免 env 解析失败）
    os.environ.setdefault("TG_BULL_TOKEN", "dummy_bull")
    os.environ.setdefault("TG_BEAR_TOKEN", "dummy_bear")
    os.environ.setdefault("TG_JUDGE_TOKEN", "dummy_judge")

    if config_path is None:
        config_path = str(Path(__file__).resolve().parent / "config.yaml")
    config = load_config(config_path)

    # 用 CLI 参数覆盖配置
    config.debate.max_rounds = rounds
    config.debate.judge_enabled = judge

    # 构建组件（复用 main.build_app 的逻辑，但用 QuietTelegramBot）
    import main

    # 临时替换 create_llm_adapter 的导入在 main 中已存在
    models = config.debate.models

    from core.agents import BullAgent, BearAgent, JudgeAgent
    from core.marketing import MarketingExtractor
    from core.quality import QualityEvaluator
    from core.telegram_bot import TelegramDualBot

    debater_llm = main.create_llm_adapter(model_name=models.get("debater", "qwen-turbo"))
    judge_llm = main.create_llm_adapter(model_name=models.get("judge", "qwen-plus"))
    marketing_llm = main.create_llm_adapter(model_name=models.get("marketing", "qwen-plus"))
    quality_llm = main.create_llm_adapter(model_name=models.get("quality", "qwen-plus"))

    bull_agent = BullAgent(debater_llm)
    bear_agent = BearAgent(debater_llm)
    judge_agent = JudgeAgent(judge_llm) if judge else None

    marketing_extractor = MarketingExtractor(marketing_llm)
    quality_evaluator = QualityEvaluator(quality_llm)

    # CLI 模式用静默 bot（不发真实 Telegram 消息）
    telegram_dual_bot = TelegramDualBot(
        bull_bot=QuietTelegramBot("bull"),
        bear_bot=QuietTelegramBot("bear"),
        judge_bot=QuietTelegramBot("judge") if judge else None,
    )

    orchestrator = DebateOrchestrator(
        bull_agent=bull_agent,
        bear_agent=bear_agent,
        judge_agent=judge_agent,
        marketing_extractor=marketing_extractor,
        quality_evaluator=quality_evaluator,
        telegram_dual_bot=telegram_dual_bot,
        pause_timeout=config.debate.pause_timeout_minutes * 60,
    )

    # 运行辩论
    print(f"\n🎤 辩论话题：{topic}")
    print(f"🔄 轮次：{rounds} | 裁判：{'启用' if judge else '禁用'}")
    if background:
        print(f"📄 背景：{background[:100]}")

    result = asyncio.run(orchestrator.run(
        topic=topic, chat_id=0, max_rounds=rounds, background=background,
    ))

    # 打印营销素材
    _print_marketing(result)

    # 打印质量评分
    _print_quality(result)

    # 保存 JSON
    if output:
        output_path = Path(output)
        output_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n💾 完整结果已保存到：{output_path}")

    return result


def _print_marketing(result: DebateResult):
    """打印营销素材。"""
    m = result.material
    print(f"\n{'='*50}")
    print("📣 营销素材")
    print(f"{'='*50}")
    print(f"标题：{m.debate_title}")
    if m.quotes:
        print("金句：")
        for q in m.quotes:
            print(f"  • {q}")
    if m.hashtags:
        print(f"标签：{' '.join(m.hashtags)}")
    if m.short_copy:
        print("短文案：")
        for c in m.short_copy:
            print(f"  - {c}")


def _print_quality(result: DebateResult):
    """打印质量评分。"""
    q = result.quality_score
    print(f"\n{'='*50}")
    print("📊 质量评估")
    print(f"{'='*50}")
    print(f"综合分：{q.overall} / 10  等级：{q.grade}")
    print(f"规则分：{q.rule_score}  LLM 分：{q.llm_score}")
    if q.highlights:
        print("亮点：" + "；".join(q.highlights))
    if q.suggestions:
        print("建议：" + "；".join(q.suggestions))


# ─── 主入口 ──────────────────────────────────────────────────────

def main():
    args = parse_args()
    run_cli(
        topic=args.topic,
        rounds=args.rounds,
        background=args.background,
        judge=args.judge,
        output=args.output,
        config_path=args.config,
    )


if __name__ == "__main__":
    main()
