#!/usr/bin/env python3
"""persona.py — 辩手人格画像系统 (C-Drive 内部)

SPEC v2.0-rc3 第三节：Persona 数据模型 + 7 预设 + 动态话题匹配。
Persona 为辩论赋予人格深度：性格特质、话术风格、背景故事、专业领域、安全约束。

位置：C-Drive 内部 (dream-harness-bridge/packages/python-server/persona.py)
被 DebateEngine (debate_engine.py) 使用，也可被 32-bot 通过 IPC 间接调用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Persona:
    """辩手人格画像。

    Attributes:
        name: 角色名称（如 "乐观分析师"）
        side: 立场 ('bull' | 'bear' | 'judge')
        traits: 性格特质列表
        speech_style: 话术风格描述
        backstory: 角色背景（影响论据来源偏好）
        expertise: 专业领域列表
        forbidden: 禁止行为（安全约束）
    """
    name: str
    side: str                          # 'bull' | 'bear' | 'judge'
    traits: list[str]
    speech_style: str
    backstory: str
    expertise: list[str]
    forbidden: list[str]

    def build_system_prompt(
        self,
        topic: str,
        opponent_thesis: Optional[str] = None,
        background: str = "",
        memories: Optional[list[str]] = None,
        strategy_weights: Optional[dict] = None,
        cold_start: bool = False,
    ) -> str:
        """基于 Persona 生成 system prompt。

        生成逻辑：
        1. 角色定位（bull/bear 用正反方，judge 用裁判）
        2. 人格特质
        3. 话术风格
        4. 背景故事 + 专业领域
        5. 禁止行为
        6. 对方论点（如有）
        7. 背景材料（如有）
        8. 历史记忆（如有）
        9. JSON 输出约束
        """
        # judge 特殊处理：中立裁判，不分正反方
        if self.side == "judge":
            parts = [
                f"你是{self.name}，中立裁判。你的职责：客观评判辩论质量，给出总结和洞察。",
                f"你的性格特点：{', '.join(self.traits)}。" if self.traits else "",
                f"说话风格：{self.speech_style}" if self.speech_style else "",
                f"背景：{self.backstory}，你的专业领域：{', '.join(self.expertise)}。" if self.backstory or self.expertise else "",
                f"绝对禁止：{', '.join(self.forbidden)}。" if self.forbidden else "",
            ]
            parts = [p for p in parts if p]  # 去空行
            if background:
                parts.append(f"背景信息：{background}")
            parts.append(
                '输出 JSON: {"summary": "...", "winner": "bull"|"bear"|"draw", '
                '"key_insights": ["...", "..."], "topic_angle": "话题升华"}'
            )
            return "\n".join(parts)

        # bull/bear 标准逻辑
        side_label = "正" if self.side == "bull" else "反"
        stance = "支持" if self.side == "bull" else "反对"
        parts = [
            f"你是{self.name}，{side_label}方辩手。你的立场：{stance}话题「{topic}」。",
            f"你的性格特点：{', '.join(self.traits)}。",
            f"说话风格：{self.speech_style}",
            f"背景：{self.backstory}，你的专业领域：{', '.join(self.expertise)}。",
            f"绝对禁止：{', '.join(self.forbidden)}。",
        ]

        # 注入正反方辩论策略（debate-pro-side / debate-con-side SKILL）
        if self.side == "bull":
            parts.append(
                "## 正方策略指导\n"
                "- 承担举证责任：建构自证成立的论证体系（prima facie）\n"
                "- 论点排列：最强论点放首位，梯级论证（claim→warrant→impact）\n"
                "- 预防性反驳：预判反方2-3个主要攻击，提前用1-2句回应\n"
                "- 定义博弈：选择公平但对正方有利的定义，概念清晰不留漏洞\n"
                "- 数据引用：至少2层证据支撑每个论点（数据+研究/专家）\n"
                "- 反方案应对(STOP)：Solvency缺陷+Theory理论+Offense攻击+Permutation兼行\n"
                "- 禁止：偷换概念、虚假证据、人身攻击、四辩引入新论据"
            )
        elif self.side == "bear":
            parts.append(
                "## 反方策略指导\n"
                "- 推翻举证：无需证明己方成立，只需正方不成立（presumption在反方）\n"
                "- 反驳四维：Logic逻辑(找因果跳跃/隐含假设) + Definitions定义(找歧义) "
                "+ Analogies类比(延伸到荒谬) + Evidence证据(反例/数据不足/误用)\n"
                "- 独立立论：不能只挑刺，需提出2+个正方论点之外的独立论据\n"
                "- 定义攻击：如正方定义偏颇，一辩中立即提出替代定义（后续不能补提）\n"
                "- 翻转引入：将正方开场例子翻转为支持反方的理由\n"
                "- 专属战术：Counterplan(替代方案) + Disadvantage(劣势论证) "
                "+ 价值翻转 + 拖延举证(质疑证据充分性) + Kritik(批判底层假设)\n"
                "- 质询策略：封闭式提问+追问暴露矛盾+两难问题+确认型提问\n"
                "- 禁止：纯破坏无建构、偷换概念、虚假证据、放弃定义权"
            )

        if opponent_thesis:
            parts.append(f"对方上一轮核心论点：{opponent_thesis}，请针对性反驳。")
        if background:
            parts.append(f"背景信息：{background}")
        if memories:
            parts.append(f"历史辩论中的有效论据（可引用）：{'; '.join(memories)}")

        # §5.6.1: 注入策略推荐 (基于历史胜率) — 仅 bull/bear, 非 judge
        if strategy_weights:
            sorted_sw = sorted(
                strategy_weights.items(),
                key=lambda x: x[1], reverse=True,
            )[:2]  # Top-2
            label = "[低置信度，仅供参考]" if cold_start else ""
            rec_lines = ["## 推荐策略（基于历史胜率）"]
            for strat, prob in sorted_sw:
                rec_lines.append(
                    f"- {strat} (胜率 {prob:.0%}) {label}")
            parts.append("\n".join(rec_lines))

        parts.append(
            '输出 JSON: {"thesis": "...", "arguments": ["...", "..."], '
            '"quote": "金句", "confidence": 0.0-1.0}'
        )
        return "\n".join(parts)


# ============================================================
# 7 预设 Persona 库
# ============================================================

_DEFAULT_FORBIDDEN = ["人身攻击", "使用未经验证的数据", "情绪化表述"]

PRESET_PERSONAS: dict[str, Persona] = {
    "乐观分析师": Persona(
        name="乐观分析师",
        side="bull",
        traits=["幽默", "数据驱动", "爱用比喻"],
        speech_style="轻松诙谐但不失逻辑，善用类比让复杂概念通俗易懂",
        backstory="前对冲基金分析师，经历过 2017 和 2021 两轮牛市",
        expertise=["宏观经济学", "链上分析", "市场心理学"],
        forbidden=_DEFAULT_FORBIDDEN,
    ),
    "谨慎风控师": Persona(
        name="谨慎风控师",
        side="bear",
        traits=["犀利", "逻辑严密", "引用历史"],
        speech_style="严谨克制，每个论点都有数据支撑，善于发现逻辑漏洞",
        backstory="十年风控老兵，见过太多泡沫破灭",
        expertise=["风险管理", "历史金融危机", "衍生品定价"],
        forbidden=_DEFAULT_FORBIDDEN,
    ),
    "中立裁判": Persona(
        name="中立裁判",
        side="judge",
        traits=["客观", "升华视角", "辩证思维"],
        speech_style="中立公正，善于提炼双方精华，升华讨论维度",
        backstory="资深辩论赛裁判，擅长总结和引导思考",
        expertise=["逻辑学", "辩论方法论", "批判性思维"],
        forbidden=_DEFAULT_FORBIDDEN,
    ),
    "技术乐观派": Persona(
        name="技术乐观派",
        side="bull",
        traits=["极客风格", "引用技术指标", "前瞻性"],
        speech_style="充满技术热情，善用技术分析指标论证",
        backstory="早期 AI 从业者，亲历技术突破的加速度",
        expertise=["AI 技术栈", "机器学习", "技术趋势分析"],
        forbidden=_DEFAULT_FORBIDDEN,
    ),
    "伦理审慎派": Persona(
        name="伦理审慎派",
        side="bear",
        traits=["哲学思辨", "引用伦理框架", "长期视角"],
        speech_style="深沉克制，善用哲学和伦理框架进行思辨",
        backstory="科技伦理研究员，关注技术的社会影响",
        expertise=["科技伦理", "哲学", "社会影响评估"],
        forbidden=_DEFAULT_FORBIDDEN,
    ),
    "加密老兵": Persona(
        name="加密老兵",
        side="bull",
        traits=["口语化", "经历多轮牛熊", "实战导向"],
        speech_style="接地气，用亲身经历讲故事，不玩虚的",
        backstory="2013 年入圈的老矿工，经历 Mt.Gox、94、312、519",
        expertise=["加密市场周期", "链上数据", "社区动态"],
        forbidden=_DEFAULT_FORBIDDEN,
    ),
    "传统金融人": Persona(
        name="传统金融人",
        side="bear",
        traits=["专业术语", "引用传统金融理论", "风险厌恶"],
        speech_style="专业严谨，善用传统金融理论框架分析",
        backstory="二十年华尔街老兵，CFA 持证人",
        expertise=["传统金融理论", "资产定价", "风险管理"],
        forbidden=_DEFAULT_FORBIDDEN,
    ),
}

# 默认正反方（通用场景）
DEFAULT_BULL = PRESET_PERSONAS["乐观分析师"]
DEFAULT_BEAR = PRESET_PERSONAS["谨慎风控师"]
DEFAULT_JUDGE = PRESET_PERSONAS["中立裁判"]

# 话题关键词 → Persona 映射
_KEYWORD_MAP: list[tuple[list[str], str, str]] = [
    # (关键词列表, bull_persona名, bear_persona名)
    (["BTC", "Crypto", "加密", "比特币", "以太坊", "ETH", "区块链", "数字货币"],
     "加密老兵", "传统金融人"),
    (["AI", "人工智能", "大模型", "LLM", "AGI", "机器学习", "深度学习", "GPT"],
     "技术乐观派", "伦理审慎派"),
]


def match_personas(
    topic: str,
    elo_registry: Optional[dict] = None,
    epsilon: float = 0.2,
) -> tuple[Persona, Persona]:
    """根据话题关键词自动匹配 Bull/Bear Persona。

    匹配规则：
    - "BTC/Crypto/加密/比特币/以太坊" → 加密老兵 vs 传统金融人
    - "AI/人工智能/大模型/LLM" → 技术乐观派 vs 伦理审慎派
    - 通用 → 乐观分析师 vs 谨慎风控师

    §5.6.2: 传入 elo_registry 时用 ε-贪心策略选择 Persona:
    - ε 概率随机探索 (选任意同类 Persona)
    - 1-ε 概率选 Elo 最高的

    Args:
        topic: 辩论话题
        elo_registry: {persona_name: elo_score}, None 时退化为原始匹配 (HC3)
        epsilon: 探索概率 (默认 0.2), ε=0 纯利用, ε=1 纯探索

    Returns:
        (bull_persona, bear_persona)
    """
    import random as _random

    # 关键词匹配确定 Persona 类型
    bull_name, bear_name = DEFAULT_BULL.name, DEFAULT_BEAR.name
    for keywords, bn, rn in _KEYWORD_MAP:
        for kw in keywords:
            if kw in topic:
                bull_name, bear_name = bn, rn
                break
        else:
            continue
        break

    # 无 elo_registry → 原始行为 (HC3 向后兼容)
    if elo_registry is None:
        return PRESET_PERSONAS[bull_name], PRESET_PERSONAS[bear_name]

    # §5.6.2: ε-贪心选择
    # 从所有同 side 的 Persona 中选
    bull_candidates = [p for p in PRESET_PERSONAS.values() if p.side == "bull"]
    bear_candidates = [p for p in PRESET_PERSONAS.values() if p.side == "bear"]

    def _select(candidates, default_name):
        if len(candidates) <= 1:
            return candidates[0] if candidates else PRESET_PERSONAS[default_name]
        if _random.random() < epsilon:
            # 探索: 随机选
            return _random.choice(candidates)
        else:
            # 利用: 选 Elo 最高的
            return max(
                candidates,
                key=lambda p: elo_registry.get(p.name, 1200),
            )

    bull = _select(bull_candidates, bull_name)
    bear = _select(bear_candidates, bear_name)
    return bull, bear
