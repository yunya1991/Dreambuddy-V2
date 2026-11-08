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
import sys
from pathlib import Path

from core.config import load_config
from core.llm_compat import LLMSettings, health_check
from core.models import DebateResult
from core.orchestrator import DebateOrchestrator
from core.review_runner import run_review_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("debate.cli")


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK，打印中文/emoji 会崩溃；统一为 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — 非 tty/旧 Python 忽略
            pass


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
    parser.add_argument("topic", nargs="?", default="", help="辩论话题")
    parser.add_argument("--rounds", type=int, default=2, help="辩论轮次（默认 2）")
    parser.add_argument("--background", default="", help="背景材料（可选）")
    parser.add_argument("--background-file", default=None, help="从文件读取背景材料（可选）")
    parser.add_argument(
        "--judge", dest="judge", action="store_true", default=True, help="启用裁判（默认）"
    )
    parser.add_argument("--no-judge", dest="judge", action="store_false", help="禁用裁判")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--output", default=None, help="将完整结果保存为 JSON 文件")
    parser.add_argument(
        "--provider", default=None, help="LLM provider：auto/anthropic/openai_compat/langchain"
    )
    parser.add_argument("--model", default=None, help="覆盖模型名")
    parser.add_argument("--doctor", action="store_true", help="只做 LLM 连通性自检，不运行辩论")
    parser.add_argument(
        "--json", action="store_true", help="输出结构化 JSON（评审模式，不含营销/质量）"
    )
    parser.add_argument(
        "--review", action="store_true", help="评审模式（等价于 --json，强调对抗评审）"
    )
    parser.add_argument(
        "--no-marketing", action="store_true", help="跳过营销素材/质量评分，直接输出评审 JSON"
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help="启用 Research Prepass（只读 L0 MCP + 本地代码检索）",
    )
    parser.add_argument(
        "--research-sources", default="", help="逗号分隔：unified_search,recall,code（默认全部）"
    )
    parser.add_argument("--research-max-items", type=int, default=8, help="最多引用条数（默认 8）")
    parser.add_argument(
        "--research-timeout", type=float, default=20.0, help="单源检索超时秒（默认 20）"
    )
    parser.add_argument(
        "--cross-exam", action="store_true", help="第 1 轮后启用双向交叉质询（v2.0-rc3 §4.2）"
    )
    parser.add_argument(
        "--profile",
        default=None,
        choices=["marketing", "technical", "signal"],
        help="角色 profile（默认：营销路径 marketing；评审路径 technical）",
    )
    parser.add_argument(
        "--no-adjudication", action="store_true", help="评审模式不生成 6 维 adjudication"
    )
    args = parser.parse_args(argv)
    if not args.doctor and not args.topic:
        parser.error("topic is required unless --doctor is used")
    return args


# ─── 运行辩论 ────────────────────────────────────────────────────


def run_cli(
    topic: str,
    rounds: int = 2,
    background: str = "",
    judge: bool = True,
    output: str | None = None,
    config_path: str | None = None,
    research: bool = False,
    research_sources: list[str] | None = None,
    research_max_items: int = 8,
    research_timeout: float = 20.0,
    cross_examination: bool = False,
    profile: str | None = None,
) -> DebateResult:
    """运行一场辩论并返回结果。

    Args:
        topic: 辩论话题
        rounds: 辩论轮次
        background: 背景材料
        judge: 是否启用裁判
        output: 结果 JSON 输出路径
        config_path: 配置文件路径
        research: 是否启用 Research Prepass
        research_sources: 限定来源
        research_max_items: 最大引用数
        research_timeout: 单源超时

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

    if research:
        from core.research import collect_research, merge_background

        brief = collect_research(
            topic,
            background,
            sources=research_sources,
            max_items=research_max_items,
            timeout=research_timeout,
        )
        background = merge_background(background, brief)

    # 构建组件（复用 main.build_app 的逻辑，但用 QuietTelegramBot）
    import main

    # 临时替换 create_llm_adapter 的导入在 main 中已存在
    models = config.llm.models or config.debate.models

    from core.agents import BearAgent, BullAgent, JudgeAgent
    from core.marketing import MarketingExtractor
    from core.quality import QualityEvaluator
    from core.telegram_bot import TelegramDualBot

    def _model(role: str, default: str) -> str:
        return models.get(role) or config.debate.models.get(role) or default

    def _max_tokens(role: str, default: int) -> int:
        return int(config.llm.max_tokens.get(role, default))

    debater_llm = main.create_llm_adapter(
        config=config.llm, model_name=_model("debater", "qwen-turbo")
    )
    judge_llm = main.create_llm_adapter(config=config.llm, model_name=_model("judge", "qwen-plus"))
    marketing_llm = main.create_llm_adapter(
        config=config.llm, model_name=_model("marketing", "qwen-plus")
    )
    quality_llm = main.create_llm_adapter(
        config=config.llm, model_name=_model("quality", "qwen-plus")
    )

    resolved_profile = profile or config.debate.profile
    bull_agent = BullAgent(
        debater_llm,
        max_tokens=_max_tokens("debater", 2000),
        profile=resolved_profile,
    )
    bear_agent = BearAgent(
        debater_llm,
        max_tokens=_max_tokens("debater", 2000),
        profile=resolved_profile,
    )
    judge_agent = (
        JudgeAgent(judge_llm, max_tokens=_max_tokens("judge", 1600), profile=resolved_profile)
        if judge
        else None
    )

    marketing_extractor = MarketingExtractor(
        marketing_llm,
        max_tokens=_max_tokens("marketing", 1000),
    )
    quality_evaluator = QualityEvaluator(
        quality_llm,
        max_tokens=_max_tokens("quality", 1000),
    )

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
        cross_examination=cross_examination,
        profile=resolved_profile,
    )

    # 运行辩论
    print(f"\n🎤 辩论话题：{topic}")
    print(f"🔄 轮次：{rounds} | 裁判：{'启用' if judge else '禁用'}")
    if background:
        print(f"📄 背景：{background[:100]}")

    result = asyncio.run(
        orchestrator.run(
            topic=topic,
            chat_id=0,
            max_rounds=rounds,
            background=background,
        )
    )

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
    _configure_stdio()
    args = parse_args()

    # CLI 模式不使用 Telegram，预置 dummy token 避免 env 解析失败
    os.environ.setdefault("TG_BULL_TOKEN", "dummy_bull")
    os.environ.setdefault("TG_BEAR_TOKEN", "dummy_bear")
    os.environ.setdefault("TG_JUDGE_TOKEN", "dummy_judge")

    config_path = args.config or str(Path(__file__).resolve().parent / "config.yaml")
    config = load_config(config_path)
    if args.provider:
        config.llm.provider = args.provider
    if args.model:
        for role in config.llm.models:
            config.llm.models[role] = args.model

    if args.doctor:
        settings = LLMSettings(
            provider=config.llm.provider,
            model=args.model or config.llm.models.get("debater"),
            base_url=config.llm.base_url,
            api_key=config.llm.api_key,
            timeout_sec=config.llm.timeout_sec,
            max_retries=config.llm.max_retries,
        )
        result = asyncio.run(health_check(settings))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    background = args.background or ""
    if args.background_file:
        file_text = Path(args.background_file).read_text(encoding="utf-8")
        background = (file_text + "\n\n" + background).strip()

    if args.json or args.review or args.no_marketing:
        import main as debate_main

        profile = args.profile or "technical"

        roles = config.llm.models or config.debate.models
        debater_llm = debate_main.create_llm_adapter(
            config=config.llm, model_name=roles.get("debater")
        )
        judge_llm = debate_main.create_llm_adapter(config=config.llm, model_name=roles.get("judge"))
        research_sources = [
            s.strip() for s in (args.research_sources or "").split(",") if s.strip()
        ] or None
        result = run_review_sync(
            args.topic,
            background=background,
            rounds=args.rounds,
            judge=args.judge,
            debater_llm=debater_llm,
            judge_llm=judge_llm,
            research=args.research,
            research_sources=research_sources,
            research_max_items=args.research_max_items,
            research_timeout=args.research_timeout,
            cross_examination=args.cross_exam,
            adjudication=not args.no_adjudication,
            profile=profile,
        )
        payload = result.to_dict()
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"\n💾 评审结果已保存到：{args.output}", file=sys.stderr)
        return

    research_sources = [
        s.strip() for s in (args.research_sources or "").split(",") if s.strip()
    ] or None
    run_cli(
        topic=args.topic,
        rounds=args.rounds,
        background=background,
        judge=args.judge,
        output=args.output,
        config_path=config_path,
        research=args.research,
        research_sources=research_sources,
        research_max_items=args.research_max_items,
        research_timeout=args.research_timeout,
        cross_examination=args.cross_exam,
        profile=args.profile or config.debate.profile,
    )


if __name__ == "__main__":
    main()
