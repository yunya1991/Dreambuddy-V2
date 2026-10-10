"""multi_scenario_test.py — 多场景集成测试

用模拟 LLM（真实感辩论内容）跑多个话题，验证完整 pipeline：
agents → orchestrator → marketing → quality

测试场景：
1. BTC 是数字黄金（加密货币）
2. AI 会取代程序员（科技）
3. 远程办公优于办公室（职场）
4. 电动车将全面替代燃油车（汽车）

验证要点：
- 双方立场锁定（Bull 只支持 / Bear 只反对）
- 轮次控制（max_rounds）
- 结构化 JSON 解析（Argument/Verdict）
- 营销素材提取（金句/标签/精华/短文案/标题）
- 质量评分（S/A/B/C 分级）
- 状态机流转正确
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

# 确保 core 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.agents import BullAgent, BearAgent, JudgeAgent
from core.config import AppConfig, DebateConfig, TelegramConfig
from core.marketing import MarketingExtractor
from core.models import Argument, Turn, Verdict
from core.orchestrator import DebateOrchestrator
from core.quality import QualityEvaluator
from core.telegram_bot import TelegramDualBot

logging.basicConfig(level=logging.WARNING)  # 测试时只看警告


# ─── 模拟 LLM 客户端 ─────────────────────────────────────────────

class ScenarioLLM:
    """模拟 LLM，根据 prompt 内容返回不同角色的真实感输出。

    通过检测 system_prompt 中的关键词判断角色，返回对应 JSON。
    每次调用返回的内容略有不同，模拟真实多轮辩论。
    """

    def __init__(self, topic: str):
        self.topic = topic
        self.bull_round = 0
        self.bear_round = 0

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int = 600) -> str:
        # 判断角色
        if "正方" in system_prompt or "支持" in system_prompt:
            return self._bull_response()
        if "反方" in system_prompt or "反对" in system_prompt:
            return self._bear_response()
        if "裁判" in system_prompt or "综合" in system_prompt:
            return self._judge_response()
        if "营销" in system_prompt or "文案" in system_prompt:
            return self._marketing_response()
        # 质量评估
        return self._quality_response()

    def _bull_response(self) -> str:
        self.bull_round += 1
        responses = [
            {
                "thesis": f"{self.topic} 是未来趋势，支持者众多",
                "arguments": [
                    f"历史数据表明{self.topic}相关领域增长迅速",
                    "技术成熟度不断提升，应用场景持续扩大",
                    "政策面持续利好，资本纷纷涌入",
                ],
                "quote": f"趋势不可阻挡，{self.topic}将重塑行业格局",
                "confidence": 0.85,
            },
            {
                "thesis": f"{self.topic} 的核心优势无可替代",
                "arguments": [
                    "效率提升显著，ROI 远超传统方案",
                    "用户体验质的飞跃，留存率创新高",
                    "生态系统日趋完善，网络效应显现",
                ],
                "quote": "不是要不要做的问题，而是做多快的问题",
                "confidence": 0.82,
            },
        ]
        idx = min(self.bull_round - 1, len(responses) - 1)
        return json.dumps(responses[idx], ensure_ascii=False)

    def _bear_response(self) -> str:
        self.bear_round += 1
        responses = [
            {
                "thesis": f"{self.topic} 被过度炒作，泡沫终将破裂",
                "arguments": [
                    "估值严重脱离基本面，缺乏盈利支撑",
                    "技术瓶颈尚未突破，落地场景有限",
                    "监管风险上升，合规成本高企",
                ],
                "quote": "当所有人都在谈论时，就是该撤退的时候",
                "confidence": 0.78,
            },
            {
                "thesis": f"{self.topic} 面临根本性挑战",
                "arguments": [
                    "替代方案层出不穷，竞争白热化",
                    "用户增长见顶，获客成本飙升",
                    "核心技术护城河不深，易被复制",
                ],
                "quote": "繁华背后是脆弱的根基",
                "confidence": 0.75,
            },
        ]
        idx = min(self.bear_round - 1, len(responses) - 1)
        return json.dumps(responses[idx], ensure_ascii=False)

    def _judge_response(self) -> str:
        return json.dumps({
            "summary": f"双方围绕{self.topic}展开了激烈交锋。正方从趋势、效率、生态等维度论证其必然性，反方则从估值、技术瓶颈、监管风险等角度提出质疑。综合来看，{self.topic}具备长期潜力但短期存在泡沫风险。",
            "winner": "bull",
            "key_insights": [
                "正方在趋势判断上更具说服力",
                "反方对短期风险的警示值得重视",
                "核心分歧在于技术成熟度的预期",
            ],
            "topic_angle": "从'技术成熟度曲线'视角看，{self.topic}正处于期望膨胀期向幻灭低谷期过渡的关键节点，理性看待才能把握真正机会",
        }, ensure_ascii=False)

    def _marketing_response(self) -> str:
        return json.dumps({
            "copies": [
                f"🔥 {self.topic}，是风口还是泡沫？一场精彩辩论告诉你答案！",
                f"💡 正方：趋势不可挡 | 反方：泡沫终破裂  你站哪边？",
                f"🎯 关于{self.topic}的真相，看完这场辩论你就懂了",
            ],
            "title": f"{self.topic}：未来已来还是泡沫将至？正反方激辩",
        }, ensure_ascii=False)

    def _quality_response(self) -> str:
        return json.dumps({
            "conflict_intensity": 8.0,
            "topic_elevation": 7.0,
            "copy_convertibility": 8.5,
            "highlights": [
                "双方论点针锋相对，冲突感强",
                "金句频出，适合二次传播",
            ],
            "suggestions": [
                "可增加数据支撑提升说服力",
            ],
        }, ensure_ascii=False)


# ─── 静默 Telegram Bot ──────────────────────────────────────────

class QuietBot:
    async def send_message(self, chat_id: int, text: str) -> dict:
        return {"message_id": 0}


# ─── 场景测试 ────────────────────────────────────────────────────

SCENARIOS = [
    {"topic": "BTC 是数字黄金", "rounds": 2, "judge": True},
    {"topic": "AI 会取代程序员", "rounds": 2, "judge": True},
    {"topic": "远程办公优于办公室", "rounds": 1, "judge": False},
    {"topic": "电动车将全面替代燃油车", "rounds": 3, "judge": True},
]


def build_orchestrator(topic: str, judge_enabled: bool) -> DebateOrchestrator:
    """为指定话题构建 orchestrator（使用模拟 LLM）。"""
    llm = ScenarioLLM(topic)
    bull = BullAgent(llm)
    bear = BearAgent(llm)
    judge = JudgeAgent(llm) if judge_enabled else None
    marketing = MarketingExtractor(llm)
    quality = QualityEvaluator(llm)
    telegram = TelegramDualBot(
        bull_bot=QuietBot(), bear_bot=QuietBot(),
        judge_bot=QuietBot() if judge_enabled else None,
    )
    return DebateOrchestrator(
        bull_agent=bull, bear_agent=bear, judge_agent=judge,
        marketing_extractor=marketing, quality_evaluator=quality,
        telegram_dual_bot=telegram,
    )


async def run_scenario(scenario: dict) -> dict:
    """运行单个场景，返回测试结果。"""
    topic = scenario["topic"]
    rounds = scenario["rounds"]
    judge_enabled = scenario["judge"]

    orchestrator = build_orchestrator(topic, judge_enabled)
    result = await orchestrator.run(
        topic=topic, chat_id=0, max_rounds=rounds, background="",
    )

    # 验证
    checks = {
        "topic_matches": result.topic == topic,
        "transcript_count": len(result.transcript),
        "expected_transcript": rounds * 2 + (1 if judge_enabled else 0),
        "all_bull_stand_support": all(
            "支持" in t.content.thesis or "趋势" in t.content.thesis
            for t in result.transcript if t.speaker == "bull"
        ),
        "all_bear_stand_oppose": all(
            "反对" in t.content.thesis or "泡沫" in t.content.thesis
            for t in result.transcript if t.speaker == "bear"
        ),
        "verdict_present": (result.verdict is not None) == judge_enabled,
        "material_has_quotes": len(result.material.quotes) > 0,
        "material_has_hashtags": len(result.material.hashtags) > 0,
        "material_has_title": bool(result.material.debate_title),
        "quality_grade_valid": result.quality_score.grade in ("S", "A", "B", "C"),
        "status_completed": result.status == "completed",
    }

    return {
        "topic": topic,
        "rounds": rounds,
        "judge": judge_enabled,
        "checks": checks,
        "all_passed": all(checks.values()),
        "result": result,
    }


async def main():
    print("=" * 60)
    print("🎭 多场景辩论 Bot 集成测试")
    print("=" * 60)

    results = []
    for scenario in SCENARIOS:
        print(f"\n▶ 场景: {scenario['topic']} (轮次={scenario['rounds']}, 裁判={'是' if scenario['judge'] else '否'})")
        res = await run_scenario(scenario)
        results.append(res)

        # 打印检查结果
        for check_name, passed in res["checks"].items():
            status = "✅" if passed else "❌"
            val = "" if isinstance(passed, bool) else f" = {passed}"
            print(f"  {status} {check_name}{val}")

        # 打印质量评分
        q = res["result"].quality_score
        print(f"  📊 质量: {q.overall}/10 等级: {q.grade}")

        # 打印营销素材摘要
        m = res["result"].material
        print(f"  📣 标题: {m.debate_title}")
        if m.quotes:
            print(f"  💬 金句数: {len(m.quotes)}")
        if m.hashtags:
            print(f"  🏷️ 标签: {' '.join(m.hashtags[:3])}")

        overall = "✅ 通过" if res["all_passed"] else "❌ 失败"
        print(f"  结果: {overall}")

    # 汇总
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r["all_passed"])
    total = len(results)
    print(f"📋 汇总: {passed}/{total} 场景通过")

    # 打印失败详情
    for r in results:
        if not r["all_passed"]:
            failed = [k for k, v in r["checks"].items() if not v]
            print(f"  ❌ {r['topic']}: {failed}")

    print("=" * 60)

    # 保存详细结果
    output_path = Path(__file__).parent / "scenario_test_result.json"
    detailed = []
    for r in results:
        detailed.append({
            "topic": r["topic"],
            "rounds": r["rounds"],
            "judge": r["judge"],
            "checks": r["checks"],
            "all_passed": r["all_passed"],
            "result": r["result"].to_dict(),
        })
    output_path.write_text(
        json.dumps(detailed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"💾 详细结果已保存: {output_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
