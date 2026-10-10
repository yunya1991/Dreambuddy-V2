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
        if opponent_thesis:
            parts.append(f"对方上一轮核心论点：{opponent_thesis}，请针对性反驳。")
        if background:
            parts.append(f"背景信息：{background}")
        if memories:
            parts.append(f"历史辩论中的有效论据（可引用）：{'; '.join(memories)}")
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


def match_personas(topic: str) -> tuple[Persona, Persona]:
    """根据话题关键词自动匹配 Bull/Bear Persona。

    匹配规则：
    - "BTC/Crypto/加密/比特币/以太坊" → 加密老兵 vs 传统金融人
    - "AI/人工智能/大模型/LLM" → 技术乐观派 vs 伦理审慎派
    - 通用 → 乐观分析师 vs 谨慎风控师

    Returns:
        (bull_persona, bear_persona)
    """
    for keywords, bull_name, bear_name in _KEYWORD_MAP:
        for kw in keywords:
            if kw in topic:
                return PRESET_PERSONAS[bull_name], PRESET_PERSONAS[bear_name]
    return DEFAULT_BULL, DEFAULT_BEAR
