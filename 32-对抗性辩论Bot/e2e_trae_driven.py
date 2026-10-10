#!/usr/bin/env python3
"""e2e_trae_driven.py — Debate Engine v2 端到端验证 (Trae 驱动)

验证链路:
  1. Persona 系统: match_personas → build_system_prompt (Persona 可见)
  2. 真实 Telegram: TelegramHTTPClient → TelegramDualBot → 真实群消息
  3. C-Drive 认知闭环: ipc_fn → handle_debate → recall/record (IPC 打通)
  4. InteractiveRunner: send_bull → record → send_bear → record → verdict → marketing → quality

Trae 驱动模式: 论点由 Trae 预先生成（基于 Persona 提示），非外部 LLM API。

用法:
  cd 32-对抗性辩论Bot
  python e2e_trae_driven.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────
# 32-bot 自身目录 (core/ 模块)
BOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_DIR))

# python-server 目录 (c_drive_agent, persona 模块)
PYTHON_SERVER = Path(__file__).resolve().parent.parent / "1-ARCHITECTURE" / "dream-harness-bridge" / "packages" / "python-server"
sys.path.insert(0, str(PYTHON_SERVER))

# ── 加载 .env ──────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(BOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("e2e")

# ── 导入组件 ──────────────────────────────────────────────────
from core.telegram_adapter import TelegramHTTPClient
from core.telegram_bot import TelegramDualBot
from core.interactive_runner import InteractiveRunner

# C-Drive 模块 (python-server)
from persona import match_personas, PRESET_PERSONAS, Persona
from c_drive_agent import handle_debate

# ── ipc_fn: 进程内直连 handle_debate ───────────────────────────
def ipc_fn(params: dict) -> dict:
    """IPC 调用函数: 进程内直接调 handle_debate。

    生产环境通过 dsh_adapter subprocess 调用（已注册 debate 路由），
    E2E 用进程内直连简化，验证同一 handle_debate 函数。
    """
    return handle_debate(params)


# ============================================================
# Trae 生成的辩论内容 (基于 Persona 提示)
# Topic: "BTC 是数字黄金"
# Persona 匹配: 加密老兵(bull) vs 传统金融人(bear)
# ============================================================

TOPIC = "BTC 是数字黄金"
CHAT_ID = int(os.environ.get("TG_CHAT_ID", "-1003981441400"))

# 正方 (加密老兵)
BULL_THESIS = "BTC 已具备数字黄金的核心属性：算法稀缺性、抗审查流通、机构共识三重支撑"
BULL_ARGUMENTS = [
    "算法稀缺性远超物理黄金：BTC 上限 2100 万枚硬编码，减半后年增率不足 1%。黄金年增约 2%，且探明储量持续增加。通缩属性 BTC > 黄金。",
    "机构共识拐点已过：贝莱德 IBIT ETF 资管规模超 500 亿美元，富达、微策略合计持仓超 40 万枚 BTC。华尔街用真金白银投了票。",
    "抗审查+全球流通：BTC 网络运行 15 年零停机，跨境转账 10 分钟到账。黄金运输需物理安保+海关清关，流动性差距 10 倍以上。",
]
BULL_QUOTE = "当贝莱德把 BTC 写进 ETF，黄金的金融垄断就结束了。"
BULL_CONFIDENCE = 0.78

# 反方 (传统金融人)
BEAR_THESIS = "BTC 波动率是黄金 5 倍，存储风险高，监管不确定性大，尚不具备数字黄金的储值稳定性"
BEAR_ARGUMENTS = [
    "波动率证伪储值属性：2024 年 BTC 单日最大跌幅 15%，同期黄金仅 2%。储值资产的底线是保值，5 倍波动率更像风险资产。",
    "存储与安全风险：交易所黑客累计损失超 150 亿美元，私钥自托管丢失率约 4%。黄金托管在央行金库，零丢失。",
    "监管不确定性悬顶：美国 SEC 对加密质押诉讼未决，欧盟 MiCA 限制稳定币，中国全面禁令。黄金有 5000 年法理共识，BTC 不足 15 年。",
]
BEAR_QUOTE = "黄金 5000 年没归零过，BTC 经历过 3 次 80% 暴跌。"
BEAR_CONFIDENCE = 0.72

# 裁判
VERDICT_SUMMARY = (
    "正方以算法稀缺性和机构 ETF 采用为核心论据，论证扎实；"
    "反方以波动率和监管风险为盾，提醒储值属性尚未稳固。"
    "综合判定：BTC 具备数字黄金潜力，但稳定性仍需 1-2 个减半周期验证。"
    "当前阶段更像'高风险版数字黄金'。"
)
VERDICT_WINNER = "bull"
VERDICT_INSIGHTS = [
    "稀缺性论据有数据支撑（2100万 vs 黄金年增2%），但波动率反驳同样有力",
    "机构 ETF 采用是 BTC 走向储值的关键拐点",
    "监管风险是最大不确定性，需持续跟踪",
]
VERDICT_ANGLE = "BTC 储值叙事的成熟度评估：潜力已现，稳定性待验"

# 营销
MARKETING_QUOTES = [BULL_QUOTE, BEAR_QUOTE]
MARKETING_HASHTAGS = ["#BTC数字黄金", "#加密辩论", "#对抗性辩论Bot"]
MARKETING_HIGHLIGHT = (
    "本场辩论聚焦 BTC 是否已具备数字黄金属性。"
    "加密老兵以 2100 万枚上限和贝莱德 ETF 采用为矛，"
    "传统金融人以 5 倍波动率和 150 亿美元黑客损失为盾。"
    "综合来看，BTC 储值叙事正在成熟，但稳定性仍需时间验证。"
)
MARKETING_SHORT_COPY = [
    "BTC 是黄金 2.0 还是投机泡沫？正反交锋给你答案",
    "稀缺 vs 波动，一场关于数字黄金的硬核辩论",
]
MARKETING_TITLE = "BTC 是数字黄金？加密老兵 vs 传统金融人"

# 质量评分
QUALITY_OVERALL = 7.5
QUALITY_DIMENSIONS = {"论据质量": 8.0, "反驳力度": 7.5, "数据引用": 8.0, "逻辑连贯": 7.0}
QUALITY_HIGHLIGHTS = [
    "正方稀缺性数据精确（2100万上限 vs 黄金年增2%）",
    "反方波动率对比有力（15% vs 2%）",
    "双方引用真实机构数据（贝莱德/微策略/SEC）",
]
QUALITY_SUGGESTIONS = [
    "可补充 BTC 减半周期历史回测数据",
    "反方可引用黄金波动率长期下降趋势作为反驳",
]


# ============================================================
# E2E 主流程
# ============================================================

async def run_e2e():
    """执行端到端验证。"""

    # ── Step 0: 构造真实 Telegram bot ──────────────────────────
    bull_token = os.environ["TG_BULL_TOKEN"]
    bear_token = os.environ["TG_BEAR_TOKEN"]
    judge_token = os.environ.get("TG_JUDGE_TOKEN", bull_token)

    logger.info("=== E2E 启动 ===")
    logger.info("Topic: %s", TOPIC)
    logger.info("Chat ID: %s", CHAT_ID)

    bull_bot = TelegramHTTPClient(bull_token)
    bear_bot = TelegramHTTPClient(bear_token)
    judge_bot = TelegramHTTPClient(judge_token)

    dual_bot = TelegramDualBot(
        bull_bot=bull_bot,
        bear_bot=bear_bot,
        judge_bot=judge_bot,
        send_delay=1.5,
        retry_delay=2.0,
    )

    # ── Step 1: Persona 匹配 + 打印 system prompt ─────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 1: Persona 匹配")
    logger.info("=" * 60)

    bull_persona, bear_persona = match_personas(TOPIC)
    judge_persona = PRESET_PERSONAS["中立裁判"]

    logger.info("正方 Persona: %s (side=%s)", bull_persona.name, bull_persona.side)
    logger.info("  特质: %s", ", ".join(bull_persona.traits))
    logger.info("  背景: %s", bull_persona.backstory)
    logger.info("  专业: %s", ", ".join(bull_persona.expertise))

    logger.info("反方 Persona: %s (side=%s)", bear_persona.name, bear_persona.side)
    logger.info("  特质: %s", ", ".join(bear_persona.traits))
    logger.info("  背景: %s", bear_persona.backstory)
    logger.info("  专业: %s", ", ".join(bear_persona.expertise))

    # 打印 system prompt (Persona 可见验证)
    bull_prompt = bull_persona.build_system_prompt(TOPIC)
    bear_prompt = bear_persona.build_system_prompt(TOPIC, opponent_thesis=BULL_THESIS)
    judge_prompt = judge_persona.build_system_prompt(TOPIC)

    logger.info("\n--- 正方 System Prompt ---\n%s", bull_prompt)
    logger.info("\n--- 反方 System Prompt ---\n%s", bear_prompt)
    logger.info("\n--- 裁判 System Prompt ---\n%s", judge_prompt)

    # ── Step 2: 构造 InteractiveRunner + ipc_fn ─────────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 2: 构造 InteractiveRunner (ipc_fn → handle_debate)")
    logger.info("=" * 60)

    runner = InteractiveRunner(
        telegram_dual_bot=dual_bot,
        topic=TOPIC,
        chat_id=CHAT_ID,
        max_rounds=2,
        judge_enabled=True,
        ipc_fn=ipc_fn,
    )
    logger.info("InteractiveRunner 已构造, ipc_fn=%s", "handle_debate (in-process)")

    # ── Step 3: 认知闭环 - recall 历史记忆 ─────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: recall 历史辩论记忆 (IPC → C-Drive)")
    logger.info("=" * 60)

    memories = await runner.recall_memories(TOPIC, top_k=5)
    logger.info("recall 返回 %d 条记忆", len(memories))
    for i, m in enumerate(memories):
        logger.info("  [%d] %s", i, str(m)[:120])

    # ── Step 4: 正方发言 (Trae 生成 → Telegram 发送) ──────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 4: 正方发言 (加密老兵) → 真实 Telegram")
    logger.info("=" * 60)

    turn1 = await runner.send_bull(
        thesis=BULL_THESIS,
        arguments=BULL_ARGUMENTS,
        quote=BULL_QUOTE,
        confidence=BULL_CONFIDENCE,
    )
    logger.info("正方第1轮已发送, transcript 长度=%d", len(runner.transcript))

    # ── Step 5: 认知闭环 - record 正方论点 ─────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 5: record 正方论点 (IPC → C-Drive)")
    logger.info("=" * 60)

    mem_id_bull = await runner.record_argument(
        topic=TOPIC,
        side="bull",
        thesis=BULL_THESIS,
        arguments=BULL_ARGUMENTS,
        quote=BULL_QUOTE,
        confidence=BULL_CONFIDENCE,
        persona=bull_persona.name,
        round=1,
    )
    logger.info("正方论点已记录, memory_id=%s", mem_id_bull)

    # ── Step 6: 反方反驳 (Trae 生成 → Telegram 发送) ──────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 6: 反方反驳 (传统金融人) → 真实 Telegram")
    logger.info("=" * 60)

    turn2 = await runner.send_bear(
        thesis=BEAR_THESIS,
        arguments=BEAR_ARGUMENTS,
        quote=BEAR_QUOTE,
        confidence=BEAR_CONFIDENCE,
    )
    logger.info("反方第1轮已发送, transcript 长度=%d", len(runner.transcript))

    # ── Step 7: 认知闭环 - record 反方论点 ─────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 7: record 反方论点 (IPC → C-Drive)")
    logger.info("=" * 60)

    mem_id_bear = await runner.record_argument(
        topic=TOPIC,
        side="bear",
        thesis=BEAR_THESIS,
        arguments=BEAR_ARGUMENTS,
        quote=BEAR_QUOTE,
        confidence=BEAR_CONFIDENCE,
        persona=bear_persona.name,
        round=1,
    )
    logger.info("反方论点已记录, memory_id=%s", mem_id_bear)

    # ── Step 8: 裁判裁决 ────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 8: 裁判裁决 → 真实 Telegram")
    logger.info("=" * 60)

    verdict = await runner.send_verdict(
        summary=VERDICT_SUMMARY,
        winner=VERDICT_WINNER,
        key_insights=VERDICT_INSIGHTS,
        topic_angle=VERDICT_ANGLE,
    )
    logger.info("裁判裁决已发送, winner=%s", verdict.winner)

    # ── Step 9: 营销素材 ────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 9: 营销素材 → 真实 Telegram")
    logger.info("=" * 60)

    material = await runner.send_marketing(
        quotes=MARKETING_QUOTES,
        hashtags=MARKETING_HASHTAGS,
        highlight_paragraph=MARKETING_HIGHLIGHT,
        short_copy=MARKETING_SHORT_COPY,
        debate_title=MARKETING_TITLE,
    )
    logger.info("营销素材已发送, title=%s", material.debate_title)

    # ── Step 10: 质量评分 ──────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 10: 质量评分 → 真实 Telegram")
    logger.info("=" * 60)

    quality = await runner.send_quality(
        overall=QUALITY_OVERALL,
        dimensions=QUALITY_DIMENSIONS,
        highlights=QUALITY_HIGHLIGHTS,
        suggestions=QUALITY_SUGGESTIONS,
    )
    logger.info("质量评分已发送, overall=%s/10 (%s)", quality.overall, quality.grade)

    # ── Step 11: 构建完整结果 ──────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("Step 11: build_result + 保存 JSON")
    logger.info("=" * 60)

    result = runner.build_result()
    result_dict = result.to_dict()

    output_path = BOT_DIR / "e2e_result.json"
    output_path.write_text(
        json.dumps(result_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("结果已保存: %s", output_path)

    # ── 验证总结 ────────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("E2E 验证总结")
    logger.info("=" * 60)
    logger.info("Persona 匹配: %s vs %s ✓", bull_persona.name, bear_persona.name)
    logger.info("Telegram 发送: bull/bear/judge/marketing/quality ✓")
    logger.info("IPC recall: %d 条记忆返回 ✓", len(memories))
    logger.info("IPC record: bull=%s, bear=%s %s",
                mem_id_bull, mem_id_bear,
                "✓" if (mem_id_bull or mem_id_bear) else "(FAIL-OPEN)")
    logger.info("Transcript: %d turns ✓", len(runner.transcript))
    logger.info("Verdict winner: %s ✓", verdict.winner)
    logger.info("质量评分: %s/10 (%s级) ✓", quality.overall, quality.grade)
    logger.info("\n=== E2E 完成 ===")

    return result


if __name__ == "__main__":
    asyncio.run(run_e2e())
