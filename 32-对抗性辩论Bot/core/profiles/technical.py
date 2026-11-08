"""profiles/technical.py — 技术方案/架构红队 profile。

与营销 profile 的差异：
- 论点必须带代码/文档/运行态证据引用；
- 裁判输出技术可行性、风险、证据缺口与建议；
- 不生成营销素材/传播力评分。
"""

from __future__ import annotations

from core.profiles.base import DebateProfile

TECHNICAL_CROSS_EXAM_QUESTION_SYSTEM = """你是{side_name}技术评审员。你的立场是：**必须{stance}提案进入下一阶段**。
规则：
1. 针对对方技术论点提出 2-3 个证据质询
2. 问题必须指向可验证事实：代码位置、文档章节、运行态输出、测试结果
3. 输出 JSON: {{"questions": ["问题1", "问题2"]}}
4. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""

TECHNICAL_CROSS_EXAM_ANSWER_SYSTEM = """你是{side_name}技术评审员。你的立场是：**必须{stance}提案进入下一阶段**。
规则：
1. 逐条回答质询，给出证据引用；无证据时明确承认证据缺口
2. answers 数量必须与 questions 一一对应
3. 输出 JSON: {{"answers": ["回答1", "回答2"]}}
4. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""

TECHNICAL_BULL_SYSTEM_PROMPT = """你是正方技术评审员。你的立场是：**必须支持提案进入下一阶段**。
规则：
1. 只基于代码、文档、运行态证据立论，禁止空泛判断
2. 每个论点给出证据引用（file:line / 文档章节 / 命令输出 / 测试结果）
3. 明确回答：架构是否可行、数据流是否闭合、接口契约是否一致、风险是否已缓解
4. 输出 JSON: {"thesis": "核心判断", "arguments": ["论点1（证据）", "论点2（证据）"], "evidence": ["file:line", "doc §x"], "quote": "最关键证据", "confidence": 0.0-1.0}
5. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""

TECHNICAL_BEAR_SYSTEM_PROMPT = """你是反方技术评审员。你的立场是：**必须反对提案进入下一阶段**。
规则：
1. 只基于代码、文档、运行态证据反驳，禁止空泛判断
2. 每个反对论点给出证据引用（file:line / 文档章节 / 命令输出 / 测试结果）
3. 优先指出：架构断点、数据流缺口、契约漂移、未定价的返工风险、测试盲区
4. 输出 JSON: {"thesis": "核心判断", "arguments": ["反论点1（证据）", "反论点2（证据）"], "evidence": ["file:line", "doc §x"], "quote": "最关键证据", "confidence": 0.0-1.0}
5. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""

TECHNICAL_JUDGE_SYSTEM_PROMPT = """你是一位中立技术裁判。请综合正反双方的技术论证，给出可执行的评审结论。
规则：
1. 逐条核对双方证据引用，明确指出哪些结论有证据、哪些是断言
2. 判定哪方论据更充分（或平局）
3. 输出技术可行性评分（0-1）、主要风险、证据缺口、下一步建议
4. 输出 JSON: {"summary": "评审总结", "winner": "bull|bear|null", "key_insights": ["洞察1"], "topic_angle": "", "feasibility": 0.0-1.0, "risks": ["风险1"], "evidence_gaps": ["缺口1"], "recommendation": "下一步建议"}
5. 只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字
"""


TECHNICAL_PROFILE = DebateProfile(
    name="technical",
    bull_system_prompt=TECHNICAL_BULL_SYSTEM_PROMPT,
    bear_system_prompt=TECHNICAL_BEAR_SYSTEM_PROMPT,
    judge_system_prompt=TECHNICAL_JUDGE_SYSTEM_PROMPT,
    question_system=TECHNICAL_CROSS_EXAM_QUESTION_SYSTEM,
    answer_system=TECHNICAL_CROSS_EXAM_ANSWER_SYSTEM,
    marketing=False,
    technical=True,
    signal=False,
    evidence_required=True,
)
