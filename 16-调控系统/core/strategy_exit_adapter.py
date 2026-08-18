"""策略离场设计原则适配层

每个交易策略有自己的离场设计哲学和规则。
本模块为每个策略定义：
1. 策略离场设计原则（为什么这么设计）
2. 策略原生离场机制（自身已有的离场能力）
3. 宏观离场的适用边界（哪些可以干预，哪些不应该干预）
4. 策略专属的评估权重和调整因子

核心思想：宏观离场评估应该是"增强"而非"替代"策略原生离场机制。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ExitDesignPhilosophy(str, Enum):
    """离场设计哲学"""
    TREND_FOLLOWING = "trend_following"      # 趋势跟踪：让利润奔跑，截断亏损
    MEAN_REVERSION = "mean_reversion"        # 均值回归：高抛低吸，区间操作
    MARTINGALE = "martingale"                 # 马丁格尔：越跌越买，等反弹止盈
    FUNDAMENTAL = "fundamental"               # 基本面驱动：长期持有，价值投资
    SENTIMENT = "sentiment"                   # 情绪驱动：事件驱动，快进快出
    OSCILLATION = "oscillation"               # 震荡市：网格/波段操作


class MacroExitInfluenceLevel(str, Enum):
    """宏观离场对策略的影响级别"""
    DOMINANT = "dominant"        # 宏观主导：宏观信号权重 > 70%
    IMPORTANT = "important"      # 重要参考：宏观权重 40-60%
    SUPPLEMENTARY = "supplementary"  # 补充参考：宏观权重 20-35%
    MINIMAL = "minimal"          # 仅观察：宏观权重 < 15%，不直接干预
    NONE = "none"                # 不干预：完全由策略自身决定


@dataclass
class StrategyExitDesign:
    """策略离场设计原则"""
    
    strategy_id: str
    strategy_name: str
    philosophy: ExitDesignPhilosophy
    
    # 策略原生离场机制（自身已有的能力）
    native_exit_mechanisms: List[str] = field(default_factory=list)
    
    # 宏观离场适用边界
    macro_influence_level: MacroExitInfluenceLevel = MacroExitInfluenceLevel.SUPPLEMENTARY
    
    # 哪些场景下宏观可以干预
    macro_can_intervene: List[str] = field(default_factory=list)
    
    # 哪些场景下宏观不应该干预（策略自身设计）
    macro_should_not_intervene: List[str] = field(default_factory=list)
    
    # 技术信号权重（用于融合决策时的调整）
    technical_signal_weight: float = 0.5
    
    # 宏观信号权重
    macro_signal_weight: float = 0.5
    
    # 对 P0 硬退出的态度（是否接受宏观覆盖）
    allow_macro_override_p0: bool = False
    
    # 最大可接受的宏观干预减仓比例
    max_macro_reduce_fraction: float = 0.5
    
    # 置信度门槛（只有超过此门槛才执行离场建议）
    # P0 硬退出不受此限制（一票否决不可覆盖）
    confidence_threshold_close: float = 0.70   # 平仓建议需要更高置信度
    confidence_threshold_reduce: float = 0.60  # 减仓建议置信度门槛
    confidence_threshold_observe: float = 0.40  # 低于此值仅观察不输出建议
    
    # 评估合理性检查项
    rationality_checks: List[str] = field(default_factory=list)
    
    # 策略特性描述
    description: str = ""


# ==========================================
# 各策略离场设计定义
# ==========================================

STRATEGY_EXIT_DESIGNS: Dict[str, StrategyExitDesign] = {
    
    # ========== V15 马丁策略 ==========
    "v15_martin": StrategyExitDesign(
        strategy_id="v15_martin",
        strategy_name="V15 马丁策略",
        philosophy=ExitDesignPhilosophy.MARTINGALE,
        
        native_exit_mechanisms=[
            "V9 基线止盈：4% × vol_mult 全仓止盈",
            "MA200 趋势止损：大趋势反转强制平仓",
            "超时离场：持仓超过最佳时间后触发 ClassicExitSystem 评估",
            "加仓分层计时：无加仓48h / 加仓后24h（含12h黄金窗口）",
            "RAISE_TP：强反弹时提高止盈目标",
        ],
        
        macro_influence_level=MacroExitInfluenceLevel.MINIMAL,
        
        macro_can_intervene=[
            "大级别趋势反转确认（周线级别）→ 可建议提前止盈或减仓",
            "黑天鹅事件 / 极端风险 → 可建议紧急减仓",
            "宏观面极度恶化 → 可建议降低加仓节奏",
        ],
        
        macro_should_not_intervene=[
            "正常浮亏区间的马丁加仓（这是策略设计本身）",
            "止盈目标未达成前的常规波动",
            "P0 最大亏损限制（马丁策略的硬性风控底线）",
            "黄金窗口期内的持仓（加仓后的反弹概率最高期）",
        ],
        
        technical_signal_weight=0.8,
        macro_signal_weight=0.2,
        
        allow_macro_override_p0=False,
        max_macro_reduce_fraction=0.3,
        
        confidence_threshold_close=0.85,    # 马丁策略要求极高置信度才允许干预
        confidence_threshold_reduce=0.75,
        confidence_threshold_observe=0.50,
        
        rationality_checks=[
            "检查是否在黄金窗口期内 → 是则不建议离场",
            "检查浮亏是否在马丁正常区间内 → 是则属于策略设计",
            "检查加仓次数是否已达上限 → 已满则宏观权重可提升",
            "检查是否已触发超时评估 → 是则宏观可参与决策",
        ],
        
        description="""马丁策略的核心是'越跌越买，等反弹止盈'。
浮亏是策略的正常组成部分，不是错误。
宏观评估只能在极端情况下（大趋势反转、黑天鹅）提供辅助参考，
绝不能因为'浮亏太大'就建议平仓——那会把马丁策略变成亏损必砍的最差策略。
"""
    ),
    
    # ========== 三屏趋势系统 ==========
    "screen_trend": StrategyExitDesign(
        strategy_id="screen_trend",
        strategy_name="三屏趋势系统",
        philosophy=ExitDesignPhilosophy.TREND_FOLLOWING,
        
        native_exit_mechanisms=[
            "Screen 3 经典离场系统（ClassicExitSystem）",
            "ATR 动态止损/止盈（L1 技术离场）",
            "TSTP 时间止盈：持仓时间衰减止盈目标",
            "L2 共振离场：多技术指标共振",
            "RAISE_TP：趋势强劲时提高止盈",
        ],
        
        macro_influence_level=MacroExitInfluenceLevel.SUPPLEMENTARY,
        
        macro_can_intervene=[
            "宏观面重大变化 → 可调整持仓周期预期",
            "多币种宏观共振 → 可提升趋势判断置信度",
            "宏观风险预警 → 可收紧止损/降低止盈目标",
        ],
        
        macro_should_not_intervene=[
            "技术面明确的止损信号（趋势跟踪的铁律）",
            "正常的技术回调（趋势中的波动是正常的）",
            "P0 硬退出触发（风控底线不可动摇）",
        ],
        
        technical_signal_weight=0.7,
        macro_signal_weight=0.3,
        
        allow_macro_override_p0=False,
        max_macro_reduce_fraction=0.5,
        
        confidence_threshold_close=0.75,    # 趋势跟踪要求较高置信度
        confidence_threshold_reduce=0.65,
        confidence_threshold_observe=0.45,
        
        rationality_checks=[
            "检查技术面趋势是否完好 → 完好则宏观建议权重降低",
            "检查是否在趋势延续阶段 → 是则不建议过早离场",
            "检查宏观与技术是否同向 → 同向则增强置信度",
            "检查是否有明确的技术离场信号 → 有则以技术为主",
        ],
        
        description="""三屏趋势系统是纯技术面驱动的趋势跟踪策略。
离场决策以技术指标为准（Screen 3 经典离场系统）。
宏观分析作为补充参考，用于提升趋势判断的置信度，
或在极端宏观风险时提供预警，但不应替代技术离场信号。
"""
    ),
    
    # ========== 易经推理系统 ==========
    "yijing_bcrm": StrategyExitDesign(
        strategy_id="yijing_bcrm",
        strategy_name="易经推理系统",
        philosophy=ExitDesignPhilosophy.SENTIMENT,
        
        native_exit_mechanisms=[
            "卦象周期：恒卦（持仓）/ 归妹卦（离场）",
            "ClassicExitSystem 技术离场（3.0x ATR 止盈 / 2.0x ATR 止损）",
            "市态自适应：8种市态动态调整止盈止损",
            "变卦触发：卦象变化时重新评估",
        ],
        
        macro_influence_level=MacroExitInfluenceLevel.IMPORTANT,
        
        macro_can_intervene=[
            "宏观面验证卦象判断 → 同向则增强置信度",
            "宏观事件可能触发变卦 → 可提前预警",
            "多维度共振验证 → 提升决策可靠性",
        ],
        
        macro_should_not_intervene=[
            "卦象明确的离场信号（易经系统的核心规则）",
            "卦象周期内的正常波动（起卦后应有完整周期）",
            "P0 硬风控触发",
        ],
        
        technical_signal_weight=0.5,
        macro_signal_weight=0.5,
        
        allow_macro_override_p0=False,
        max_macro_reduce_fraction=0.5,
        
        confidence_threshold_close=0.70,    # 易经系统中等置信度门槛
        confidence_threshold_reduce=0.60,
        confidence_threshold_observe=0.40,
        
        rationality_checks=[
            "检查当前卦象阶段 → 早期不建议离场",
            "检查是否有变卦迹象 → 有则宏观权重提升",
            "检查宏观与卦象是否同向 → 同向则增强",
            "检查市态分类是否匹配 → 匹配度高则宏观权重可提升",
        ],
        
        description="""易经推理系统基于卦象周期和市态分类进行交易。
卦象有自身的周期规律，不应被轻易打断。
宏观分析可以作为'解卦'的辅助维度，
验证或质疑卦象判断，但不应直接替代卦象决策。
"""
    ),
    
    # ========== Agent A（LLM 原生驱动） ==========
    "agent_a": StrategyExitDesign(
        strategy_id="agent_a",
        strategy_name="Agent A（LLM 原生）",
        philosophy=ExitDesignPhilosophy.TREND_FOLLOWING,
        
        native_exit_mechanisms=[
            "L1 离场检查：ATR 动态止损 + 移动止损",
            "L2 智能离场：LLM 主动建议平仓",
            "LLM 调整止损止盈价位",
            "大师风格切换影响离场策略",
            "最大回撤 15% 强制保护",
        ],
        
        macro_influence_level=MacroExitInfluenceLevel.IMPORTANT,
        
        macro_can_intervene=[
            "LLM 可能遗漏的宏观风险 → 补充提醒",
            "多维度验证 LLM 判断 → 提升决策质量",
            "系统性风险预警 → 超越单币种视角",
        ],
        
        macro_should_not_intervene=[
            "明确的 L1 技术止损信号（自动化风控）",
            "LLM 已充分考虑的因素（避免重复分析）",
            "最大回撤保护触发（硬性风控）",
        ],
        
        technical_signal_weight=0.4,
        macro_signal_weight=0.6,
        
        allow_macro_override_p0=False,
        max_macro_reduce_fraction=0.6,
        
        confidence_threshold_close=0.70,    # Agent A 中等置信度
        confidence_threshold_reduce=0.55,
        confidence_threshold_observe=0.35,
        
        rationality_checks=[
            "检查 L1 止损是否已触发 → 触发则以技术为主",
            "检查 LLM 是否已有离场建议 → 有则对比分析",
            "检查当前大师风格 → 匹配宏观分析框架",
            "检查是否在连胜/连败状态 → 影响风险偏好",
        ],
        
        description="""Agent A 是 LLM 原生驱动的交易系统，
LLM 本身已经具备宏观分析能力（取决于大师风格）。
宏观调控系统的价值在于：
1. 提供更系统性的宏观框架（A1/A2/A3 多层分析）
2. 发现 LLM 可能遗漏的跨市场、跨周期信号
3. 作为第二意见验证 LLM 判断
"""
    ),
    
    # ========== Agent B（Dreambuddy 框架） ==========
    "agent_b": StrategyExitDesign(
        strategy_id="agent_b",
        strategy_name="Agent B（Dreambuddy 框架）",
        philosophy=ExitDesignPhilosophy.TREND_FOLLOWING,
        
        native_exit_mechanisms=[
            "A9 离场评估（动态链：full/standard/lean 三档）",
            "C1 技术指标离场",
            "F 链基本面离场（full 模式）",
            "A0 矛盾分析法",
            "A4 门禁系统（置信度门槛）",
            "L1/L2/L3 三层离场体系",
        ],
        
        macro_influence_level=MacroExitInfluenceLevel.DOMINANT,
        
        macro_can_intervene=[
            "全维度参与离场决策（Agent B 本身就是宏观+技术框架）",
            "提供更高维度的战略视角（跨系统、跨周期）",
            "统一协调多策略的宏观立场",
        ],
        
        macro_should_not_intervene=[
            "P0 硬风控底线",
            "已明确的技术止损信号",
        ],
        
        technical_signal_weight=0.4,
        macro_signal_weight=0.6,
        
        allow_macro_override_p0=False,
        max_macro_reduce_fraction=0.7,
        
        confidence_threshold_close=0.65,    # Agent B 宏观主导，门槛略低
        confidence_threshold_reduce=0.50,
        confidence_threshold_observe=0.30,
        
        rationality_checks=[
            "检查 Agent B 自身 A9 评估结果 → 对比分析",
            "检查当前执行模式（full/standard/lean）→ 匹配干预强度",
            "检查节点执行序列 → 理解当前决策逻辑",
            "检查置信度水平 → 低置信度时宏观权重提升",
        ],
        
        description="""Agent B 本身就是基于 Dreambuddy OS 框架的系统，
内置 A1-A9 完整分析链，宏观分析是其核心能力之一。
宏观调控系统对 Agent B 的价值在于：
1. 跨系统视角（看到其他策略的仓位和信号）
2. 更高层级的战略协调
3. 做梦部、历史档案等额外维度
"""
    ),
    
    # ========== Agent C（DreamOS 内核） ==========
    "agent_c": StrategyExitDesign(
        strategy_id="agent_c",
        strategy_name="Agent C（DreamOS 内核）",
        philosophy=ExitDesignPhilosophy.TREND_FOLLOWING,
        
        native_exit_mechanisms=[
            "SACG 四层内核动态调度",
            "A9 离场节点（按需调用）",
            "Reflector 反射决策（置信度不足重跑）",
            "动态 Token 预算管理",
            "节点注册表灵活组合",
        ],
        
        macro_influence_level=MacroExitInfluenceLevel.DOMINANT,
        
        macro_can_intervene=[
            "全维度参与（同 Agent B）",
            "OS 级别的协调和资源调度",
            "跨应用的全局视角",
        ],
        
        macro_should_not_intervene=[
            "P0 硬风控底线",
            "OS 内核的基本运行规则",
        ],
        
        technical_signal_weight=0.4,
        macro_signal_weight=0.6,
        
        allow_macro_override_p0=False,
        max_macro_reduce_fraction=0.7,
        
        confidence_threshold_close=0.65,    # Agent C 同 Agent B
        confidence_threshold_reduce=0.50,
        confidence_threshold_observe=0.30,
        
        rationality_checks=[
            "检查 DreamOS 节点执行结果 → 对比分析",
            "检查当前 SACG 各层状态 → 理解决策上下文",
            "检查预算模式 → 匹配干预深度",
            "检查反射决策次数 → 多次反射则宏观权重提升",
        ],
        
        description="""Agent C 基于 DreamOS 内核，比 Agent B 更灵活，
可以动态组合节点能力。宏观调控系统与其互补：
1. 提供跨系统的全局协调
2. 注入做梦部、历史档案等 DreamOS 外的能力
3. 作为 OS 之上的战略调控层
"""
    ),
}


def get_strategy_exit_design(strategy_id: str) -> StrategyExitDesign:
    """获取指定策略的离场设计原则"""
    return STRATEGY_EXIT_DESIGNS.get(
        strategy_id,
        StrategyExitDesign(
            strategy_id=strategy_id,
            strategy_name=f"未知策略({strategy_id})",
            philosophy=ExitDesignPhilosophy.TREND_FOLLOWING,
            description="未知策略，使用默认配置",
        )
    )


def evaluate_exit_rationality(
    strategy_id: str,
    position_info: dict,
    macro_analysis: dict,
    technical_signals: dict,
) -> dict:
    """评估离场建议的合理性（考虑策略自身设计）
    
    返回：
    - is_rational: 建议是否合理
    - adjusted_action: 调整后的动作
    - adjusted_confidence: 调整后的置信度
    - reasons: 调整原因
    - design_context: 策略设计背景说明
    """
    design = get_strategy_exit_design(strategy_id)
    
    reasons = []
    adjusted_confidence = macro_analysis.get("confidence", 0.5)
    adjusted_action = macro_analysis.get("suggested_action", "hold")
    is_rational = True
    
    # ==========================================
    # 1. 检查是否属于不应干预的场景
    # ==========================================
    pnl_pct = position_info.get("pnl_pct", 0)
    hold_hours = position_info.get("hold_hours", 0)
    addon_count = position_info.get("addon_count", 0)
    
    # 马丁策略特殊检查
    if design.philosophy == ExitDesignPhilosophy.MARTINGALE:
        # 浮亏状态下的马丁加仓是策略设计，不应该干预
        if pnl_pct < 0 and addon_count < 3 and adjusted_action in ["close", "reduce"]:
            is_rational = False
            adjusted_action = "hold"
            adjusted_confidence = min(adjusted_confidence, 0.3)
            reasons.append(
                f"马丁策略浮亏 {pnl_pct:.1f}% 属于正常设计，加仓 {addon_count}/3 次，"
                f"不应因浮亏建议离场（那会毁掉马丁策略）"
            )
        
        # 黄金窗口期检查（加仓后 12h 内）
        if addon_count > 0 and hold_hours < 12 and adjusted_action in ["close", "reduce"]:
            is_rational = False
            adjusted_action = "hold"
            adjusted_confidence = min(adjusted_confidence, 0.2)
            reasons.append(
                f"马丁加仓后 {hold_hours:.1f}h 处于黄金窗口期（反弹概率最高），"
                f"不应在此期间建议离场"
            )
    
    # ==========================================
    # 2. 检查 P0 硬退出
    # ==========================================
    p0_triggered = technical_signals.get("p0_triggered", False)
    if p0_triggered:
        if design.allow_macro_override_p0:
            reasons.append("P0 硬退出已触发，但策略允许宏观覆盖（需极高置信度）")
            if adjusted_confidence < 0.9:
                adjusted_action = "close"  # 置信度不够，还是执行 P0
                reasons.append("宏观置信度不足以覆盖 P0，执行硬退出")
        else:
            adjusted_action = "close"
            adjusted_confidence = 1.0
            reasons.append("P0 硬退出已触发，策略不允许宏观覆盖，强制执行平仓")
    
    # ==========================================
    # 3. 按策略权重调整置信度
    # ==========================================
    macro_weight = design.macro_signal_weight
    tech_weight = design.technical_signal_weight
    
    tech_confidence = technical_signals.get("confidence", 0.5)
    weighted_confidence = (
        adjusted_confidence * macro_weight + tech_confidence * tech_weight
    )
    
    reasons.append(
        f"策略{design.strategy_name}采用{design.philosophy.value}哲学，"
        f"宏观权重 {macro_weight:.0%}，技术权重 {tech_weight:.0%}，"
        f"加权后置信度 {weighted_confidence:.2f}"
    )
    
    adjusted_confidence = weighted_confidence
    
    # ==========================================
    # 4. 最大减仓比例限制
    # ==========================================
    if adjusted_action == "reduce":
        reduce_fraction = macro_analysis.get("reduce_fraction", 0.3)
        if reduce_fraction > design.max_macro_reduce_fraction:
            reduce_fraction = design.max_macro_reduce_fraction
            reasons.append(
                f"减仓比例受策略限制，从 {reduce_fraction:.0%} 降至 {design.max_macro_reduce_fraction:.0%}"
            )
    
    return {
        "strategy_id": strategy_id,
        "strategy_name": design.strategy_name,
        "philosophy": design.philosophy.value,
        "is_rational": is_rational,
        "original_action": macro_analysis.get("suggested_action", "hold"),
        "adjusted_action": adjusted_action,
        "original_confidence": macro_analysis.get("confidence", 0.5),
        "adjusted_confidence": adjusted_confidence,
        "reasons": reasons,
        "design_context": design.description,
        "macro_influence_level": design.macro_influence_level.value,
        "native_exit_mechanisms": design.native_exit_mechanisms,
        "macro_can_intervene": design.macro_can_intervene,
        "macro_should_not_intervene": design.macro_should_not_intervene,
    }


def get_all_strategy_designs() -> Dict[str, StrategyExitDesign]:
    """获取所有策略的离场设计"""
    return STRATEGY_EXIT_DESIGNS
