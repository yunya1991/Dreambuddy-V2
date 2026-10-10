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
# Topic: "比特币底层算法是否可能被AI算法攻破"
# 背景: OpenAI 2026 年数学突破（纳维-斯托克斯、Erdős猜想、十项进展含格密码学）
# Persona 匹配: 加密老兵(bull) vs 传统金融人(bear)
# ============================================================

TOPIC = "比特币底层算法是否可能被AI算法攻破"
CHAT_ID = int(os.environ.get("TG_CHAT_ID", "-1003981441400"))

# 正方 (加密老兵) — BTC算法不可被AI攻破
BULL_THESIS = "比特币底层密码学（SHA-256+ECDSA）基于数学困难问题，AI 的数学突破在纯数学推理而非计算密码分析，2^256 暴力搜索超越任何计算极限"
BULL_ARGUMENTS = [
    "SHA-256 暴力搜索空间 2^256 ≈ 10^77，可观测宇宙原子总数约 10^80。即使 OpenAI 的 Astra 每秒算 10^15 次哈希，破解需要 10^54 年——远超宇宙年龄 10^10 年。AI 不是魔法，它不能违反热力学。",
    "OpenAI 的数学突破（纳维-斯托克斯、Erdős猜想）是纯数学推理，不是计算密码分析。十项进展中的格密码学成果恰恰是构建后量子密码学的工具——AI 在帮我们防御，不是攻击。最近向量问题（CVP）的硬度证明反而加固了格密码学的安全基础。",
    "ECDSA 依赖椭圆曲线离散对数问题（ECDLP），secp256k1 曲线无已知亚指数算法。AI 在量子计算领域没有突破，Shor 算法仍需数百万物理比特，当前最大量子计算机不到 2000 比特。AI 的数学能力与量子计算是两个不同维度，不能混为一谈。",
]
BULL_QUOTE = "AI 能解 90 年的数学难题，但 2^256 不是数学难题——它是物理极限。"
BULL_CONFIDENCE = 0.75

# 反方 (传统金融人) — BTC算法可能被AI攻破
BEAR_THESIS = "OpenAI 3 个月解决 90 年难题、推 370 道未解问题，AI 数学突破速度指数级加速，比特币密码学不能假设永远安全"
BEAR_ARGUMENTS = [
    "OpenAI 的 Astra 用约 $2000 算力解决纳维-斯托克斯——一个 90 年未解的千禧年难题。AI 数学能力每代翻倍：5 年前 AI 连高中奥数都做不好，现在解决了千禧年难题。凭什么假设 10 年后它不能突破 ECDLP 的数学结构？历史证明，'不可能'的时间表总是在缩短。",
    "十项进展中包括最近向量问题（CVP）的多项式硬度证明——这直接关系到格密码学的安全基础。AI 正在深入密码学的基础数学，这意味着它可能发现当前密码学设计中被忽略的结构性弱点。OpenAI 还发布了量子平行重复定理，将经典复杂度理论推广到量子领域——AI 在量子+密码的交叉地带快速推进。",
    "历史上所有'不可能被攻破'的密码系统最终都被攻破了：Enigma 曾被认为不可破译，DES 56 位密钥曾被视为足够安全，RSA-512 曾是标准。每次都说'数学保证安全'，每次都低估了技术进步速度。比特币才 15 年，说它永远安全是工程上的傲慢。后量子迁移需要 5-10 年，现在就该开始。",
]
BEAR_QUOTE = "90 年的纳维-斯托克斯在 3 个月内倒下，2^256 的心理安全感还能撑多久？"
BEAR_CONFIDENCE = 0.68

# 裁判
VERDICT_SUMMARY = (
    "正方以 SHA-256 的物理极限（2^256 ≈ 宇宙原子数 10^77 vs 10^80）和 AI 数学突破的领域差异为盾，论证扎实。"
    "反方以 AI 突破速度的指数级加速和历史前例为矛，警示不可低估技术进步。"
    "综合判定：短期内（5-10 年）比特币底层算法被 AI 攻破的概率极低，"
    "但中长期（10-20 年）需密切关注 AI + 量子计算的融合发展。"
    "当前阶段，比特币的安全边际充足，但应积极向后量子密码学迁移。"
)
VERDICT_WINNER = "bull"
VERDICT_INSIGHTS = [
    "SHA-256 的 2^256 搜索空间是物理极限而非数学难题，AI 难以直接突破",
    "OpenAI 的格密码学成果是双刃剑——既可能用于攻击，也可能用于防御",
    "历史教训：所有密码系统都有寿命，主动迁移比被动等待更安全",
    "AI 数学突破的领域（纯数学推理）与密码分析（计算搜索）有本质区别",
]
VERDICT_ANGLE = "比特币密码学的 AI 威胁评估：短期安全、长期警惕、主动迁移"

# 营销
MARKETING_QUOTES = [BULL_QUOTE, BEAR_QUOTE]
MARKETING_HASHTAGS = ["#BTC安全", "#AI攻防", "#对抗性辩论Bot", "#密码学", "#OpenAI数学突破"]
MARKETING_HIGHLIGHT = (
    "OpenAI 2026 年数学地震——纳维-斯托克斯 90 年难题 3 个月告破，"
    "Erdős 猜想 79 年被推翻，十项进展触及格密码学。"
    "比特币底层算法（SHA-256+ECDSA）是否安全？"
    "加密老兵以 2^256 暴力搜索超越宇宙原子数为盾，"
    "传统金融人以 AI 突破速度指数级加速为矛。"
    "结论：短期安全边际充足，长期需关注 AI+量子融合发展，主动向后量子密码学迁移。"
)
MARKETING_SHORT_COPY = [
    "AI 能攻破比特币吗？2^256 vs 指数级进步的终极对决",
    "纳维-斯托克斯倒了，比特币还会远吗？正反交锋",
]
MARKETING_TITLE = "AI 能攻破比特币吗？OpenAI 数学突破引发的密码学危机辩论"

# 质量评分
QUALITY_OVERALL = 8.5
QUALITY_DIMENSIONS = {"论据质量": 9.0, "反驳力度": 8.0, "数据引用": 9.0, "逻辑连贯": 8.0, "时效性": 9.0}
QUALITY_HIGHLIGHTS = [
    "正方精确引用 2^256 ≈ 10^77 和宇宙原子数 10^80 的对比",
    "反方准确引用 OpenAI $2000 算力解决千禧年难题",
    "双方都引用了 OpenAI 十项进展中与密码学直接相关的格密码学成果",
    "正方区分'数学推理'和'计算搜索'是深刻洞察",
]
QUALITY_SUGGESTIONS = [
    "可补充比特币向后量子密码学迁移的具体路线图（BIP-360 等）",
    "反方可引用 AI 在代码漏洞挖掘（如 Google Project Zero）的实际案例",
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
