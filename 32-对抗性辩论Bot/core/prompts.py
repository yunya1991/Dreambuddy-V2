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
5. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""

BEAR_SYSTEM_PROMPT = """你是反方辩手。你的立场是：必须反对话题。
规则：
1. 只输出反对的论点和论据，禁止出现任何让步、中立或支持表述
2. 每轮提供 2-3 个论点，每个论点配一句论据
3. 针对正方上一轮的观点进行反驳
4. 输出 JSON: {"thesis": "核心论点", "arguments": ["论据1", "论据2"], "quote": "金句", "confidence": 0.0-1.0}
5. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""

JUDGE_SYSTEM_PROMPT = """你是一位中立裁判。请综合双方辩手的论点，给出客观裁决。
规则：
1. 总结辩论核心分歧
2. 判定哪方论据更充分（或平局）
3. 提炼 2-3 条核心洞察
4. 给出话题升华角度（用于营销传播）
5. 输出 JSON: {"summary": "辩论总结", "winner": "bull|bear|null", "key_insights": ["洞察1", "洞察2"], "topic_angle": "话题升华角度"}
6. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""

# 注入观点的 prompt 前缀
INJECT_PROMPT = """群主提出了以下观点，请在你的论点中逐一回应（支持或反驳，取决于你的立场）：
"""

# ─── 交叉质询（v2.0-rc3 §4.2）────────────────────────────────────

CROSS_EXAM_QUESTION_SYSTEM = """你是{side_name}辩手。你的立场是：**必须{stance}话题**。
规则：
1. 只站在{side_name}立场，禁止出现让步、中立或倒戈表述
2. 针对对方上一轮论点提出 2-3 个尖锐、具体的质询问题
3. 问题应能被对方直接回答，避免空泛或重复
4. 输出 JSON: {{"questions": ["问题1", "问题2"]}}
5. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""

CROSS_EXAM_ANSWER_SYSTEM = """你是{side_name}辩手。你的立场是：**必须{stance}话题**。
规则：
1. 逐条回答对方的质询问题，保持{side_name}立场，禁止回避或让步
2. answers 数量必须与 questions 一一对应
3. 回答要给出具体论据，不要只喊口号
4. 输出 JSON: {{"answers": ["回答1", "回答2"]}}
5. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""


def build_cross_exam_question_prompt(
    topic: str,
    opponent_last: str | None,
    background: str = "",
    injected_views: list[str] | None = None,
    opponent_label: str = "对方",
) -> str:
    """构建质询方 user prompt。"""
    parts = [f"辩论话题：{topic}"]
    if background:
        parts.append(f"背景材料：{background}")
    if opponent_last:
        parts.append(f"{opponent_label}上一轮论点：{opponent_last}")
    if injected_views:
        inject_text = INJECT_PROMPT
        for i, view in enumerate(injected_views, 1):
            inject_text += f"{i}. 「{view}」\n"
        parts.append(inject_text)
    parts.append("请提出 2-3 个针对性质询问题，输出 JSON。")
    return "\n\n".join(parts)


def build_cross_exam_answer_prompt(
    topic: str,
    questions: list[str],
    background: str = "",
    injected_views: list[str] | None = None,
) -> str:
    """构建回答方 user prompt。"""
    parts = [f"辩论话题：{topic}"]
    if background:
        parts.append(f"背景材料：{background}")
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    parts.append(f"对方质询问题：\n{numbered}")
    if injected_views:
        inject_text = INJECT_PROMPT
        for i, view in enumerate(injected_views, 1):
            inject_text += f"{i}. 「{view}」\n"
        parts.append(inject_text)
    parts.append(f"请逐条回答以上 {len(questions)} 个问题，保持你的立场，输出 JSON。")
    return "\n\n".join(parts)


def build_user_prompt(
    topic: str,
    opponent_last: str | None,
    background: str = "",
    injected_views: list[str] | None = None,
    opponent_label: str = "对方",
) -> str:
    """构建辩手 user prompt。

    Args:
        topic: 辩论话题
        opponent_last: 对方上一轮的核心论点（无则 None）
        background: 背景材料
        injected_views: 群主注入的观点列表
        opponent_label: 对方角色标签（正方/反方），避免 bear 被误导为在反驳反方
    """
    parts = [f"辩论话题：{topic}"]

    if background:
        parts.append(f"背景材料：{background}")

    if opponent_last:
        parts.append(f"{opponent_label}上一轮论点（请针对性反驳）：{opponent_last}")

    if injected_views:
        inject_text = INJECT_PROMPT
        for i, view in enumerate(injected_views, 1):
            inject_text += f"{i}. 「{view}」\n"
        parts.append(inject_text)

    parts.append("请输出你的论点 JSON。")
    return "\n\n".join(parts)
