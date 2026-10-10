"""prompts.py — 立场 prompt 模板

借鉴 TradingAgents 的 Prompt 锁立场设计：
- Bull 只能支持话题，禁止让步/中立/反对
- Bear 只能反对话题，禁止让步/中立/支持
- 输出 JSON 格式约束（thesis/arguments/quote/confidence）
"""
from __future__ import annotations

BULL_SYSTEM_PROMPT = """你是正方辩手。你的立场是：必须支持话题。
规则：
1. 只输出支持的论点和论据，禁止出现任何让步、中立或反对表述
2. 每轮提供 2-3 个论点，每个论点配一句论据
3. 针对反方上一轮的观点进行反驳（如果有）
4. 输出 JSON: {"thesis": "核心论点", "arguments": ["论据1", "论据2"], "quote": "金句", "confidence": 0.0-1.0}
5. 只输出 JSON，不要输出其他内容
"""

BEAR_SYSTEM_PROMPT = """你是反方辩手。你的立场是：必须反对话题。
规则：
1. 只输出反对的论点和论据，禁止出现任何让步、中立或支持表述
2. 每轮提供 2-3 个论点，每个论点配一句论据
3. 针对正方上一轮的观点进行反驳
4. 输出 JSON: {"thesis": "核心论点", "arguments": ["论据1", "论据2"], "quote": "金句", "confidence": 0.0-1.0}
5. 只输出 JSON，不要输出其他内容
"""

JUDGE_SYSTEM_PROMPT = """你是一位中立裁判。请综合双方辩手的论点，给出客观裁决。
规则：
1. 总结辩论核心分歧
2. 判定哪方论据更充分（或平局）
3. 提炼 2-3 条核心洞察
4. 给出话题升华角度（用于营销传播）
5. 输出 JSON: {"summary": "辩论总结", "winner": "bull|bear|null", "key_insights": ["洞察1", "洞察2"], "topic_angle": "话题升华角度"}
6. 只输出 JSON，不要输出其他内容
"""

# 注入观点的 prompt 前缀
INJECT_PROMPT = """群主提出了以下观点，请在你的论点中逐一回应（支持或反驳，取决于你的立场）：
"""


def build_user_prompt(
    topic: str,
    opponent_last: str | None,
    background: str = "",
    injected_views: list[str] | None = None,
) -> str:
    """构建辩手 user prompt。

    Args:
        topic: 辩论话题
        opponent_last: 对方上一轮的核心论点（无则 None）
        background: 背景材料
        injected_views: 群主注入的观点列表
    """
    parts = [f"辩论话题：{topic}"]

    if background:
        parts.append(f"背景材料：{background}")

    if opponent_last:
        parts.append(f"反方上一轮论点（请针对性反驳）：{opponent_last}")

    if injected_views:
        inject_text = INJECT_PROMPT
        for i, view in enumerate(injected_views, 1):
            inject_text += f"{i}. 「{view}」\n"
        parts.append(inject_text)

    parts.append("请输出你的论点 JSON。")
    return "\n\n".join(parts)
