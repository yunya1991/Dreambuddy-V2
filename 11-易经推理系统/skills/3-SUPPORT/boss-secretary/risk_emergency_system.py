"""
老板秘书 - 风险预判与紧急响应系统
Risk Prediction & Emergency Response System

功能:
1. 风险预判 - 第一性原理+假设验证的风险推演
2. 紧急响应 - 10分钟无响应自动召集顾问团队

版本: v3.0
日期: 2026-04-18
"""

import json
import yaml
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import copy


# ============================================================
# 常量定义
# ============================================================

SKILL_DIR = Path.home() / ".workbuddy/skills/boss-secretary"
RISK_DIR = SKILL_DIR / "risk"
URGENT_DIR = SKILL_DIR / "urgent"

RISK_DIR.mkdir(parents=True, exist_ok=True)
URGENT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 数据结构
# ============================================================

class RiskLevel(Enum):
    """风险等级"""
    CRITICAL = "critical"    # 灾难性
    HIGH = "high"            # 高风险
    MEDIUM = "medium"       # 中风险
    LOW = "low"              # 低风险
    MINIMAL = "minimal"      # 极低风险


class UrgencyLevel(Enum):
    """紧急程度"""
    CRITICAL = "critical"    # 十万火急
    HIGH = "high"            # 紧急
    MEDIUM = "medium"        # 一般紧急
    LOW = "low"              # 不太紧急


class FirstPrincipleCategory(Enum):
    """第一性原理类别"""
    MARKET = "market"                    # 市场本质
    RISK = "risk"                       # 风险本质
    EXECUTION = "execution"              # 执行本质
    CAPITAL = "capital"                 # 资本本质
    INFORMATION = "information"         # 信息本质
    PSYCHOLOGY = "psychology"           # 心理本质


@dataclass
class RiskHypothesis:
    """风险假设"""
    id: str
    description: str                     # 假设描述
    category: FirstPrincipleCategory    # 所属类别
    probability: float                   # 成立概率 0-1
    impact: RiskLevel                   # 影响等级
    evidence: List[str] = field(default_factory=list)      # 支持证据
    counter_evidence: List[str] = field(default_factory=list)  # 反面证据
    verification_method: str = ""        # 验证方法
    verification_result: Optional[str] = None  # 验证结果
    status: str = "pending"              # pending/confirmed/rejected/neutral"


@dataclass
class RiskScenario:
    """风险场景"""
    id: str
    name: str                            # 场景名称
    description: str                     # 场景描述
    probability: float                   # 场景概率
    impact: RiskLevel                   # 影响等级
    trigger_conditions: List[str] = field(default_factory=list)  # 触发条件
    hypotheses: List[RiskHypothesis] = field(default_factory=list)  # 包含的假设
    risk_score: float = 0.0             # 风险评分
    indicators: Dict[str, Any] = field(default_factory=dict)  # 监控指标
    countermeasures: List[str] = field(default_factory=list)  # 对策
    priority: int = 0                    # 处理优先级


@dataclass
class RiskAssessment:
    """风险评估结果"""
    timestamp: str
    context: str                         # 评估上下文
    scenarios: List[RiskScenario]        # 考虑的场景
    primary_risk: Optional[RiskScenario] = None  # 主要风险
    overall_score: float = 0.0          # 整体风险评分
    risk_level: RiskLevel = RiskLevel.LOW
    first_principle_analysis: str = ""   # 第一性原理分析
    guidance: List[str] = field(default_factory=list)  # 指导建议
    monitoring_plan: Dict[str, Any] = field(default_factory=dict)  # 监控计划


@dataclass
class UrgentTask:
    """紧急任务"""
    task_id: str
    created_at: str
    description: str                     # 任务描述
    urgency_level: UrgencyLevel
    reason: str                          # 触发原因
    boss_message: str = ""               # 老板原消息
    time_elapsed_minutes: float = 0.0   # 距老板发消息的分钟数
    status: str = "monitoring"          # monitoring/triggered/resolved
    advisor_responses: List[Dict] = field(default_factory=list)  # 顾问响应
    resolution: str = ""                # 解决方案
    resolution_time: Optional[str] = None


@dataclass
class AdvisorResponse:
    """顾问响应"""
    advisor: str                         # 顾问名称
    role: str                            # 角色
    response_time: str
    analysis: str                        # 分析
    suggestions: List[str] = field(default_factory=list)
    risk_control_principles: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)


# ============================================================
# 第一性原理分析框架
# ============================================================

FIRST_PRINCIPLES_FRAMEWORK = {
    FirstPrincipleCategory.MARKET: {
        "name": "市场本质",
        "core_questions": [
            "价格发现的本质是什么？",
            "供需关系如何驱动价格？",
            "市场效率的边界在哪里？",
            "谁是市场的主要参与者？",
            "信息不对称如何影响价格？"
        ],
        "risk_questions": [
            "当前价格是否反映真实供需？",
            "是否存在流动性陷阱？",
            "大户动向是否已反映在价格中？",
            "监管政策如何影响市场结构？"
        ],
        "key_assumptions": [
            "市场不是完全有效的",
            "价格包含预期但会偏离",
            "流动性不是无限的",
            "信息传播有延迟"
        ]
    },
    FirstPrincipleCategory.RISK: {
        "name": "风险本质",
        "core_questions": [
            "风险的根源是什么？",
            "什么决定了风险的边界？",
            "如何量化不可量化的风险？",
            "风险管理的第一原则是什么？",
            "杠杆如何放大风险？"
        ],
        "risk_questions": [
            "最坏情况是什么？",
            "损失是否在可承受范围内？",
            "是否有尾部风险对冲？",
            "风险管理流程是否被遵守？"
        ],
        "key_assumptions": [
            "损失一定会发生",
            "小概率事件不等于不发生",
            "杠杆会放大一切",
            "过度自信是风险的来源"
        ]
    },
    FirstPrincipleCategory.EXECUTION: {
        "name": "执行本质",
        "core_questions": [
            "订单如何被成交？",
            "什么决定了执行质量？",
            "滑点的本质是什么？",
            "延迟如何影响决策？",
            "最优执行的标准是什么？"
        ],
        "risk_questions": [
            "订单能否在预期价格成交？",
            "市场冲击有多大？",
            "是否会出现流动性枯竭？",
            "交易成本是否侵蚀利润？"
        ],
        "key_assumptions": [
            "订单一定会成交",
            "滑点是不可避免的",
            "流动性是动态变化的",
            "技术故障随时可能发生"
        ]
    },
    FirstPrincipleCategory.CAPITAL: {
        "name": "资本本质",
        "core_questions": [
            "资本如何保值增值？",
            "仓位大小的决定因素是什么？",
            "资金管理的核心原则是什么？",
            "回撤控制的边界在哪里？",
            "资本效率如何衡量？"
        ],
        "risk_questions": [
            "剩余资本是否充足？",
            "仓位是否超过风险承受？",
            "是否需要减仓？",
            "资金使用效率如何？"
        ],
        "key_assumptions": [
            "保住本金是第一位的",
            "仓位大小与风险成正比",
            "回撤不是线性的",
            "资本有时间成本"
        ]
    },
    FirstPrincipleCategory.INFORMATION: {
        "name": "信息本质",
        "core_questions": [
            "什么信息最重要？",
            "信息噪声与信号如何区分？",
            "信息的时效性如何？",
            "信息源的可信度如何评估？",
            "何时应该忽略信息？"
        ],
        "risk_questions": [
            "是否存在信息过载？",
            "是否在追逐过时信息？",
            "是否被噪音误导？",
            "信息是否被正确解读？"
        ],
        "key_assumptions": [
            "不是所有信息都有价值",
            "信息存在时滞",
            "噪音多于信号",
            "过度解读是危险的"
        ]
    },
    FirstPrincipleCategory.PSYCHOLOGY: {
        "name": "心理本质",
        "core_questions": [
            "交易心理的敌人是谁？",
            "什么是过度自信？",
            "损失厌恶如何影响决策？",
            "群体行为如何形成？",
            "纪律为何难以遵守？"
        ],
        "risk_questions": [
            "是否在情绪化交易？",
            "是否在追涨杀跌？",
            "是否违背了交易计划？",
            "是否受到群体影响？"
        ],
        "key_assumptions": [
            "情绪是最大的敌人",
            "从众心理是危险的",
            "纪律比预测更重要",
            "承认错误是进步的标志"
        ]
    }
}


# ============================================================
# 传统金融风险控制原则
# ============================================================

TRADITIONAL_RISK_PRINCIPLES = {
    "capital_preservation": {
        "name": "资本保全原则",
        "description": "本金安全高于一切，宁可错过机会也不能亏损",
        "rules": [
            "单笔交易亏损不超过总资金的2%",
            "日亏损不超过总资金的5%",
            "周亏损不超过总资金的10%",
            "连续亏损3次必须停止交易"
        ],
        "emergency_rules": [
            "回撤15%时强制降仓50%",
            "回撤20%时只允许平仓不允许开仓",
            "回撤30%时启动全面审查"
        ]
    },
    "risk_diversification": {
        "name": "风险分散原则",
        "description": "不要把所有鸡蛋放在一个篮子里",
        "rules": [
            "单一标的仓位不超过总资金的30%",
            "单一方向持仓不超过总资金的50%",
            "相关性强资产要降低配置",
            "保持10-20%现金储备"
        ],
        "emergency_rules": [
            "相关性飙升时立即降低仓位",
            "市场异常时要提高现金比例"
        ]
    },
    "position_sizing": {
        "name": "仓位管理原则",
        "description": "根据风险确定仓位，而非根据盈利预期",
        "rules": [
            "根据止损幅度计算仓位",
            "高风险机会小仓位",
            "低风险机会适当加仓",
            "金字塔式加仓"
        ],
        "emergency_rules": [
            "波动率飙升时缩小仓位",
            "流动性紧张时降低仓位"
        ]
    },
    "stop_loss_discipline": {
        "name": "止损纪律原则",
        "description": "止损是风险管理的核心，必须严格执行",
        "rules": [
            "入场即设定止损",
            "止损幅度不超过5%",
            "止损后不要立即反向",
            "止损是成本，不是损失"
        ],
        "emergency_rules": [
            "触及止损立即执行",
            "不允许临时修改止损",
            "止损后强制冷却期"
        ]
    },
    "liquidity_management": {
        "name": "流动性管理原则",
        "description": "确保在任何时候都能以合理价格退出",
        "rules": [
            "只交易日均成交量>1000万的标的",
            "单笔交易不超过日成交量的1%",
            "避免交易流动性差的时段",
            "预留足够保证金"
        ],
        "emergency_rules": [
            "流动性枯竭时停止开仓",
            "价差扩大时缩小单笔规模"
        ]
    },
    "trend_following": {
        "name": "趋势跟随原则",
        "description": "顺势而为，不要逆势操作",
        "rules": [
            "只在趋势方向开仓",
            "突破确认后再入场",
            "不要猜顶摸底",
            "趋势破坏时离场"
        ],
        "emergency_rules": [
            "趋势破坏立即止损",
            "横盘整理不重仓"
        ]
    }
}


# ============================================================
# 紧急清单与应对策略
# ============================================================

URGENT_CHECKLISTS = {
    "market_crash": {
        "name": "市场暴跌应对",
        "trigger_conditions": [
            "BTC 1小时跌幅 > 10%",
            "市场恐慌指数飙升",
            "交易所出现故障",
            "重大监管政策出台"
        ],
        "checklist": [
            "□ 立即检查所有持仓的止损设置",
            "□ 评估当前仓位是否超出风险承受",
            "□ 检查各交易所连接状态",
            "□ 确认账户保证金充足",
            "□ 评估流动性状况",
            "□ 关闭所有高风险策略",
            "□ 提高止损优先级",
            "□ 通知相关人员"
        ],
        "actions": [
            "优先保护本金，考虑减仓",
            "不要恐慌性抛售",
            "等待市场企稳",
            "如有对冲工具考虑使用"
        ],
        "advisors_to_activate": ["risk_control", "execution", "operations"]
    },
    "liquidity_crisis": {
        "name": "流动性危机应对",
        "trigger_conditions": [
            "买卖价差急剧扩大",
            "大单无法成交",
            "交易所提币延迟",
            "OTC溢价异常"
        ],
        "checklist": [
            "□ 检查所有挂单状态",
            "□ 评估可退出的头寸",
            "□ 确认资金可用性",
            "□ 准备切换交易所",
            "□ 检查OTC渠道",
            "□ 评估延期风险"
        ],
        "actions": [
            "优先使用市价单确保成交",
            "分批小额成交避免冲击",
            "接受合理滑点",
            "必要时接受小幅亏损"
        ],
        "advisors_to_activate": ["execution", "risk_control", "compliance"]
    },
    "system_failure": {
        "name": "系统故障应对",
        "trigger_conditions": [
            "交易所API连接失败",
            "订单无法发出",
            "数据延迟严重",
            "自动化策略异常"
        ],
        "checklist": [
            "□ 确认故障范围（单一还是全局）",
            "□ 检查网络连接",
            "□ 评估手动执行可行性",
            "□ 暂停所有自动化策略",
            "□ 准备备用方案",
            "□ 通知技术团队"
        ],
        "actions": [
            "立即切换到备用通道",
            "无法执行时手动监控",
            "记录所有异常",
            "事后复盘分析"
        ],
        "advisors_to_activate": ["operations", "execution", "compliance"]
    },
    "position_overload": {
        "name": "仓位过载应对",
        "trigger_conditions": [
            "单边行情导致仓位接近上限",
            "追加保证金需求激增",
            "账户风险率下降",
            "可用资金接近零"
        ],
        "checklist": [
            "□ 计算当前实际杠杆",
            "□ 评估是否触发强平线",
            "□ 检查保证金率",
            "□ 计算最优减仓方案",
            "□ 准备减仓清单",
            "□ 确认执行顺序"
        ],
        "actions": [
            "优先减仓高风险持仓",
            "考虑对冲保护",
            "不要幻想市场反转",
            "果断执行减仓计划"
        ],
        "advisors_to_activate": ["risk_control", "execution", "research"]
    },
    "news_event": {
        "name": "突发新闻应对",
        "trigger_conditions": [
            "重大政策宣布",
            "黑天鹅事件",
            "交易所公告",
            "大户异动"
        ],
        "checklist": [
            "□ 确认新闻真实性",
            "□ 评估影响程度和时间",
            "□ 检查相关持仓",
            "□ 评估是否需要止损",
            "□ 准备应对方案"
        ],
        "actions": [
            "不要急于行动，先观察",
            "评估新闻的实质影响",
            "遵守原有止损计划",
            "避免情绪化反应"
        ],
        "advisors_to_activate": ["research", "risk_control", "market_intel"]
    },
    "drawdown_exceeded": {
        "name": "回撤超限应对",
        "trigger_conditions": [
            "日回撤超过5%",
            "周回撤超过10%",
            "连续3日亏损",
            "最大回撤记录刷新"
        ],
        "checklist": [
            "□ 停止所有新开仓",
            "□ 评估亏损原因",
            "□ 检查风控流程执行",
            "□ 重新评估策略有效性",
            "□ 准备复盘材料"
        ],
        "actions": [
            "强制进入冷却期",
            "缩小仓位或暂停交易",
            "全面复盘亏损原因",
            "调整策略后再战"
        ],
        "advisors_to_activate": ["risk_control", "compliance", "hr"]
    }
}


# ============================================================
# 顾问团队配置
# ============================================================

ADVISOR_TEAM = {
    "risk_control": {
        "name": "风控顾问",
        "role": "风险控制专家",
        "skills": ["risk_analysis", "position_management", "scenario_planning"],
        "responsibilities": [
            "评估风险等级",
            "提供止损建议",
            "制定仓位调整方案",
            "监控整体风险暴露"
        ],
        "response_template": "基于风险控制原则，我建议：\n1. 当前风险等级：{risk_level}\n2. 建议仓位：{suggested_position}%\n3. 建议止损：{suggested_stop_loss}%\n4. 风险控制措施：{measures}"
    },
    "execution": {
        "name": "执行顾问",
        "role": "交易执行专家",
        "skills": ["order_execution", "liquidity_analysis", "slippage_optimization"],
        "responsibilities": [
            "评估执行可行性",
            "优化下单策略",
            "分析流动性状况",
            "提供成交预期"
        ],
        "response_template": "基于执行分析：\n1. 当前流动性：{liquidity_status}\n2. 建议执行方式：{execution_method}\n3. 预期滑点：{expected_slippage}%\n4. 分批建议：{split_recommendation}"
    },
    "market_intel": {
        "name": "市场情报顾问",
        "role": "市场分析专家",
        "skills": ["market_analysis", "trend_identification", "sentiment_analysis"],
        "responsibilities": [
            "分析市场趋势",
            "识别关键支撑阻力",
            "评估市场情绪",
            "提供宏观视角"
        ],
        "response_template": "市场分析：\n1. 趋势判断：{trend}\n2. 关键位置：{key_levels}\n3. 情绪指标：{sentiment}\n4. 操作建议：{action}"
    },
    "research": {
        "name": "研究顾问",
        "role": "策略研究专家",
        "skills": ["strategy_analysis", "backtesting", "performance_attribution"],
        "responsibilities": [
            "评估策略有效性",
            "分析收益来源",
            "提供优化建议",
            "识别策略失效信号"
        ],
        "response_template": "策略分析：\n1. 当前策略表现：{performance}\n2. 收益归因：{attribution}\n3. 问题诊断：{diagnosis}\n4. 优化建议：{optimization}"
    },
    "operations": {
        "name": "运营顾问",
        "role": "系统运营专家",
        "skills": ["system_health", "automation", "incident_response"],
        "responsibilities": [
            "监控系统状态",
            "处理技术问题",
            "协调各方资源",
            "确保流程正常"
        ],
        "response_template": "运营状态：\n1. 系统健康度：{health_status}\n2. 自动化状态：{automation_status}\n3. 建议操作：{suggestions}\n4. 后续步骤：{next_steps}"
    },
    "compliance": {
        "name": "合规顾问",
        "role": "合规审查专家",
        "skills": ["compliance_check", "audit", "regulatory_analysis"],
        "responsibilities": [
            "检查操作合规性",
            "识别潜在违规风险",
            "提供合规建议",
            "记录审计日志"
        ],
        "response_template": "合规审查：\n1. 合规状态：{compliance_status}\n2. 风险点：{risk_points}\n3. 建议：{recommendations}\n4. 需要记录：{records}"
    }
}


# ============================================================
# 风险预判推演引擎
# ============================================================

class RiskPredictionEngine:
    """风险预判推演引擎 - 基于第一性原理"""

    def __init__(self):
        self.framework = FIRST_PRINCIPLES_FRAMEWORK
        self.scenarios = self._initialize_default_scenarios()

    def _initialize_default_scenarios(self) -> List[RiskScenario]:
        """初始化默认风险场景"""
        scenarios = []

        # 场景1: 市场暴跌
        s1 = RiskScenario(
            id="market_crash",
            name="市场暴跌",
            description="市场出现恐慌性抛售，价格急剧下跌",
            trigger_conditions=[
                "BTC 1小时跌幅 > 10%",
                "市场恐慌指数 > 80",
                "主流币种普跌 > 15%"
            ],
            hypotheses=[],
            probability=0.1,
            impact=RiskLevel.CRITICAL,
            risk_score=0.0,
            indicators={
                "btc_1h_change": 0,
                "fear_greed_index": 50,
                "liquidity_score": 10
            },
            countermeasures=[
                "立即检查止损设置",
                "评估仓位风险",
                "准备减仓计划",
                "通知风控部门"
            ],
            priority=1
        )
        scenarios.append(s1)

        # 场景2: 流动性枯竭
        s2 = RiskScenario(
            id="liquidity_crisis",
            name="流动性枯竭",
            description="市场深度急剧下降，买卖价差扩大",
            trigger_conditions=[
                "买卖价差 > 正常水平5倍",
                "1%冲击成本 > 0.5%",
                "大单成交率 < 50%"
            ],
            hypotheses=[],
            probability=0.15,
            impact=RiskLevel.HIGH,
            risk_score=0.0,
            indicators={
                "bid_ask_spread": 0,
                "market_depth": 0,
                "impact_cost": 0
            },
            countermeasures=[
                "停止大额挂单",
                "改用市价单",
                "降低单笔规模",
                "分散成交时间"
            ],
            priority=2
        )
        scenarios.append(s2)

        # 场景3: 杠杆清算
        s3 = RiskScenario(
            id="leverage_liquidation",
            name="杠杆清算风险",
            description="高杠杆持仓面临清算风险",
            trigger_conditions=[
                "持仓保证金率 < 150%",
                "价格接近强平价",
                "账户风险率 < 150%"
            ],
            hypotheses=[],
            probability=0.2,
            impact=RiskLevel.CRITICAL,
            risk_score=0.0,
            indicators={
                "margin_ratio": 200,
                "distance_to_liquidation": 0,
                "total_leverage": 0
            },
            countermeasures=[
                "追加保证金",
                "降低杠杆",
                "减仓控制风险",
                "设置预警提醒"
            ],
            priority=1
        )
        scenarios.append(s3)

        # 场景4: 系统故障
        s4 = RiskScenario(
            id="system_failure",
            name="系统故障",
            description="交易系统或交易所出现技术故障",
            trigger_conditions=[
                "API响应时间 > 5秒",
                "订单错误率 > 5%",
                "数据延迟 > 30秒"
            ],
            hypotheses=[],
            probability=0.1,
            impact=RiskLevel.HIGH,
            risk_score=0.0,
            indicators={
                "api_latency": 0,
                "error_rate": 0,
                "data_latency": 0
            },
            countermeasures=[
                "切换备用通道",
                "暂停自动化策略",
                "启用手动监控",
                "联系技术支持"
            ],
            priority=2
        )
        scenarios.append(s4)

        # 场景5: 策略失效
        s5 = RiskScenario(
            id="strategy_failure",
            name="策略失效",
            description="当前策略连续亏损，暗示可能失效",
            trigger_conditions=[
                "连续亏损 > 5次",
                "胜率下降 > 20%",
                "盈亏比恶化 > 30%"
            ],
            hypotheses=[],
            probability=0.15,
            impact=RiskLevel.MEDIUM,
            risk_score=0.0,
            indicators={
                "consecutive_losses": 0,
                "win_rate": 0.5,
                "profit_loss_ratio": 1.0
            },
            countermeasures=[
                "降低策略仓位",
                "增加策略多样性",
                "复盘分析原因",
                "考虑策略轮换"
            ],
            priority=3
        )
        scenarios.append(s5)

        return scenarios

    def analyze_first_principles(self, context: str) -> str:
        """从第一性原理角度分析上下文"""
        analysis_parts = []

        # 按类别分析
        for category, info in FIRST_PRINCIPLES_FRAMEWORK.items():
            analysis_parts.append(f"\n### {info['name']}")
            analysis_parts.append("核心问题:")
            for q in info['core_questions'][:2]:  # 只取前2个
                analysis_parts.append(f"- {q}")
            analysis_parts.append("关键假设:")
            for a in info['key_assumptions'][:2]:
                analysis_parts.append(f"- {a}")

        return "\n".join(analysis_parts)

    def build_hypotheses(self, context: str, indicators: Dict[str, Any]) -> List[RiskHypothesis]:
        """根据上下文和指标构建假设"""
        hypotheses = []

        # BTC相关假设
        if "btc" in context.lower() or "bitcoin" in context.lower():
            h = RiskHypothesis(
                id="h_btc_vol",
                description="BTC波动性将持续高企",
                category=FirstPrincipleCategory.MARKET,
                probability=0.6,
                impact=RiskLevel.HIGH,
                evidence=["当前VIX处于高位", "宏观不确定性增加"],
                counter_evidence=["市场已大幅回调", "波动率可能均值回归"],
                verification_method="监控BOLL通道宽度和VIX指数",
                status="pending"
            )
            hypotheses.append(h)

            h2 = RiskHypothesis(
                id="h_btc_liquidity",
                description="BTC流动性将下降",
                category=FirstPrincipleCategory.EXECUTION,
                probability=0.4,
                impact=RiskLevel.MEDIUM,
                evidence=["成交量下降趋势", "做市商减少"],
                counter_evidence=["交易所数量增加", "场外流动性充沛"],
                verification_method="监控买卖价差和深度",
                status="pending"
            )
            hypotheses.append(h2)

        # 仓位相关假设
        if "position" in context.lower() or "仓位" in context:
            h3 = RiskHypothesis(
                id="h_position_overload",
                description="当前仓位超出风险承受",
                category=FirstPrincipleCategory.CAPITAL,
                probability=0.3,
                impact=RiskLevel.HIGH,
                evidence=["当前持仓接近上限", "保证金率下降"],
                counter_evidence=["风控未触发", "账户风险率正常"],
                verification_method="检查保证金率和风险敞口",
                status="pending"
            )
            hypotheses.append(h3)

        # 市场情绪假设
        if "fear" in context.lower() or "恐慌" in context or "greed" in context.lower():
            h4 = RiskHypothesis(
                id="h_sentiment_extreme",
                description="市场情绪走向极端",
                category=FirstPrincipleCategory.PSYCHOLOGY,
                probability=0.5,
                impact=RiskLevel.MEDIUM,
                evidence=["恐惧贪婪指数接近极值", "社交媒体情绪极端"],
                counter_evidence=["估值处于历史中枢", "机构持续买入"],
                verification_method="监控恐惧贪婪指数和资金流向",
                status="pending"
            )
            hypotheses.append(h4)

        return hypotheses

    def verify_hypothesis(self, hypothesis: RiskHypothesis, data: Dict[str, Any]) -> RiskHypothesis:
        """验证假设"""
        # 简化验证逻辑
        verification_result = f"基于当前数据验证："

        # 检查证据
        if hypothesis.evidence:
            supporting = len(hypothesis.evidence)
            opposing = len(hypothesis.counter_evidence)

            if supporting > opposing:
                hypothesis.probability = min(1.0, hypothesis.probability + 0.1)
                hypothesis.verification_result = f"证据支持，概率上调至 {hypothesis.probability:.0%}"
                hypothesis.status = "confirmed"
            elif opposing > supporting:
                hypothesis.probability = max(0.0, hypothesis.probability - 0.1)
                hypothesis.verification_result = f"证据反对，概率下调至 {hypothesis.probability:.0%}"
                hypothesis.status = "rejected"
            else:
                hypothesis.verification_result = f"证据平衡，维持概率 {hypothesis.probability:.0%}"
                hypothesis.status = "neutral"

        # 检查数据中的具体指标
        for key, value in data.items():
            if key in str(hypothesis.evidence).lower():
                hypothesis.verification_result += f"\n- {key}={value} 支持该假设"

        return hypothesis

    def calculate_risk_score(self, scenario: RiskScenario, hypotheses: List[RiskHypothesis]) -> float:
        """计算风险评分"""
        # 基础分 = 概率 × 影响
        base_score = scenario.probability * self._impact_to_score(scenario.impact)

        # 假设验证调整
        hypothesis_factor = 0.0
        for h in hypotheses:
            if h.status == "confirmed":
                hypothesis_factor += 0.1
            elif h.status == "rejected":
                hypothesis_factor -= 0.1

        # 最终评分
        final_score = base_score * (1 + hypothesis_factor)
        return min(100.0, max(0.0, final_score))

    def _impact_to_score(self, impact: RiskLevel) -> float:
        """影响等级转分数"""
        mapping = {
            RiskLevel.CRITICAL: 100,
            RiskLevel.HIGH: 70,
            RiskLevel.MEDIUM: 40,
            RiskLevel.LOW: 20,
            RiskLevel.MINIMAL: 5
        }
        return mapping.get(impact, 0)

    def generate_guidance(self, assessment: RiskAssessment) -> List[str]:
        """生成指导建议"""
        guidance = []

        # 基于第一性原理的建议
        guidance.append("【第一性原理】")
        guidance.append("1. 资本保全：确保本金安全，亏损不超过2%")
        guidance.append("2. 顺势而为：不要逆势操作，等趋势确认")
        guidance.append("3. 风险管理：止损是成本，不是损失")

        # 基于评估结果的建议
        if assessment.risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]:
            guidance.append("\n【紧急建议】")
            guidance.append("1. 提高止损优先级")
            guidance.append("2. 考虑减仓观望")
            guidance.append("3. 暂停新开仓")
        elif assessment.risk_level == RiskLevel.MEDIUM:
            guidance.append("\n【谨慎建议】")
            guidance.append("1. 关注仓位变化")
            guidance.append("2. 严格执行止损")
            guidance.append("3. 避免过度交易")

        # 监控计划
        guidance.append("\n【监控指标】")
        guidance.append("1. 密切关注市场情绪变化")
        guidance.append("2. 定时检查持仓状态")
        guidance.append("3. 保持通讯畅通")

        return guidance

    def assess(self, context: str, indicators: Dict[str, Any] = None) -> RiskAssessment:
        """执行完整风险评估"""
        indicators = indicators or {}

        # 1. 第一性原理分析
        fp_analysis = self.analyze_first_principles(context)

        # 2. 构建假设
        hypotheses = self.build_hypotheses(context, indicators)

        # 3. 验证假设
        verified_hypotheses = []
        for h in hypotheses:
            vh = self.verify_hypothesis(h, indicators)
            verified_hypotheses.append(vh)

        # 4. 场景推演
        scenarios = copy.deepcopy(self.scenarios)
        for s in scenarios:
            # 更新场景概率
            for h in verified_hypotheses:
                if h.category.value in s.id:
                    s.probability = (s.probability + h.probability) / 2
            # 计算风险评分
            s.risk_score = self.calculate_risk_score(s, verified_hypotheses)
            s.hypotheses = verified_hypotheses

        # 5. 找出主要风险
        primary_risk = max(scenarios, key=lambda s: s.risk_score)

        # 6. 整体评分
        overall_score = sum(s.risk_score for s in scenarios) / len(scenarios)

        # 7. 风险等级
        if overall_score >= 70:
            risk_level = RiskLevel.CRITICAL
        elif overall_score >= 50:
            risk_level = RiskLevel.HIGH
        elif overall_score >= 30:
            risk_level = RiskLevel.MEDIUM
        elif overall_score >= 10:
            risk_level = RiskLevel.LOW
        else:
            risk_level = RiskLevel.MINIMAL

        # 8. 生成指导
        assessment = RiskAssessment(
            timestamp=datetime.now().isoformat(),
            context=context,
            scenarios=scenarios,
            primary_risk=primary_risk,
            overall_score=overall_score,
            risk_level=risk_level,
            first_principle_analysis=fp_analysis,
            guidance=[]
        )
        assessment.guidance = self.generate_guidance(assessment)

        return assessment

    def format_report(self, assessment: RiskAssessment) -> str:
        """格式化评估报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("🔮 风险预判推演报告")
        lines.append("=" * 60)
        lines.append(f"时间: {assessment.timestamp}")
        lines.append(f"上下文: {assessment.context}")
        lines.append("")

        # 风险概览
        risk_emoji = {
            RiskLevel.CRITICAL: "🔴",
            RiskLevel.HIGH: "🟠",
            RiskLevel.MEDIUM: "🟡",
            RiskLevel.LOW: "🟢",
            RiskLevel.MINIMAL: "⚪"
        }
        lines.append(f"📊 整体风险评分: {assessment.overall_score:.1f}/100")
        lines.append(f"⚠️  风险等级: {risk_emoji[assessment.risk_level]} {assessment.risk_level.value.upper()}")
        lines.append("")

        # 主要风险
        if assessment.primary_risk:
            lines.append(f"🎯 主要风险: {assessment.primary_risk.name}")
            lines.append(f"   风险评分: {assessment.primary_risk.risk_score:.1f}")
            lines.append(f"   影响: {assessment.primary_risk.impact.value}")
            lines.append("")

        # 场景分析
        lines.append("📋 风险场景分析:")
        for s in sorted(assessment.scenarios, key=lambda x: x.risk_score, reverse=True)[:3]:
            lines.append(f"\n  【{s.name}】")
            lines.append(f"     概率: {s.probability:.0%}")
            lines.append(f"     影响: {s.impact.value}")
            lines.append(f"     评分: {s.risk_score:.1f}")
            if s.countermeasures:
                lines.append(f"     对策: {' | '.join(s.countermeasures[:2])}")

        # 第一性原理分析
        lines.append("")
        lines.append("🧠 第一性原理分析:")
        lines.append(assessment.first_principle_analysis[:500])

        # 指导建议
        lines.append("")
        lines.append("💡 指导建议:")
        for g in assessment.guidance[:8]:
            lines.append(f"  {g}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


# ============================================================
# 紧急响应系统
# ============================================================

class EmergencyResponseSystem:
    """紧急响应系统 - 10分钟无响应自动召集顾问"""

    def __init__(self):
        self.advisors = ADVISOR_TEAM
        self.checklists = URGENT_CHECKLISTS
        self.risk_principles = TRADITIONAL_RISK_PRINCIPLES
        self.pending_tasks: Dict[str, UrgentTask] = {}
        self.response_log = URGENT_DIR / "response_log.yaml"

    def is_urgent(self, message: str) -> Tuple[bool, UrgencyLevel, str]:
        """判断消息是否紧急"""
        urgent_keywords = {
            UrgencyLevel.CRITICAL: [
                "暴跌", "崩盘", "爆仓", "清算", "止损", "紧急",
                "立即", "马上", "完了", "亏", "止损"
            ],
            UrgencyLevel.HIGH: [
                "风险", "危险", "止损", "平仓", "仓位",
                "市场", "行情", "回调", "回撤"
            ],
            UrgencyLevel.MEDIUM: [
                "怎么办", "怎么处理", "建议", "看看",
                "要不要", "是否应该"
            ]
        }

        # 检查紧急程度
        for level in [UrgencyLevel.CRITICAL, UrgencyLevel.HIGH, UrgencyLevel.MEDIUM]:
            for keyword in urgent_keywords.get(level, []):
                if keyword in message:
                    return True, level, f"检测到关键词: {keyword}"

        return False, UrgencyLevel.LOW, "未检测到紧急关键词"

    def should_trigger_escalation(self, task: UrgentTask) -> bool:
        """判断是否应触发升级"""
        # 10分钟无响应
        if task.time_elapsed_minutes >= 10:
            return True

        # 或者消息极其紧急
        if task.urgency_level == UrgencyLevel.CRITICAL:
            return True

        return False

    def activate_advisors(self, task: UrgentTask) -> List[AdvisorResponse]:
        """召集顾问团队"""
        responses = []

        # 确定需要激活的顾问
        advisors_to_activate = []
        for crisis_type, checklist in self.checklists.items():
            if self._match_crisis(task.description, checklist):
                advisors_to_activate.extend(checklist['advisors_to_activate'])

        # 去重
        advisors_to_activate = list(set(advisors_to_activate))

        # 召集每位顾问
        for advisor_key in advisors_to_activate:
            if advisor_key in self.advisors:
                advisor_info = self.advisors[advisor_key]
                response = self._generate_advisor_response(
                    advisor_key, advisor_info, task
                )
                responses.append(response)

        # 如果没有匹配，召集核心顾问
        if not responses:
            for key in ["risk_control", "execution", "market_intel"]:
                if key in self.advisors:
                    advisor_info = self.advisors[key]
                    response = self._generate_advisor_response(
                        key, advisor_info, task
                    )
                    responses.append(response)

        return responses

    def _match_crisis(self, description: str, checklist: dict) -> bool:
        """匹配危机类型"""
        desc_lower = description.lower()
        for keyword in checklist.get('trigger_conditions', []):
            if keyword.lower() in desc_lower:
                return True
        return False

    def _generate_advisor_response(
        self, advisor_key: str, advisor_info: dict, task: UrgentTask
    ) -> AdvisorResponse:
        """生成顾问响应"""
        response = AdvisorResponse(
            advisor=advisor_info['name'],
            role=advisor_info['role'],
            response_time=datetime.now().isoformat(),
            analysis="",
            suggestions=[],
            risk_control_principles=[],
            action_items=[]
        )

        # 根据顾问类型生成分析
        if advisor_key == "risk_control":
            response = self._generate_risk_control_response(response, task)
        elif advisor_key == "execution":
            response = self._generate_execution_response(response, task)
        elif advisor_key == "market_intel":
            response = self._generate_market_intel_response(response, task)
        elif advisor_key == "operations":
            response = self._generate_operations_response(response, task)
        elif advisor_key == "compliance":
            response = self._generate_compliance_response(response, task)

        return response

    def _generate_risk_control_response(
        self, response: AdvisorResponse, task: UrgentTask
    ) -> AdvisorResponse:
        """生成风控顾问响应"""
        response.analysis = f"""
基于传统金融风险管理原则，对当前情况进行评估：

【资本保全原则】
- 当前回撤风险：需要立即评估
- 建议仓位调整：降低20-30%风险敞口
- 止损设置：必须严格执行预设止损线

【风险分散原则】
- 检查相关资产配置
- 评估系统性风险暴露
- 考虑对冲保护

【仓位管理原则】
- 根据波动率调整仓位
- 高风险时期缩小头寸
- 避免过度集中

【止损纪律原则】
- 触及止损立即执行
- 不允许临时修改
- 止损是成本，不是损失
"""

        response.risk_control_principles = [
            "资本保全优先",
            "严格执行止损",
            "仓位与风险匹配",
            "保持风险敞口可控"
        ]

        response.suggestions = [
            "1. 立即检查所有持仓的止损设置",
            "2. 评估当前仓位是否超出风险承受",
            "3. 如有必要，考虑减仓20%观望",
            "4. 保持充足保证金缓冲",
            "5. 等待市场企稳后再操作"
        ]

        response.action_items = [
            "□ 检查止损单状态",
            "□ 计算实际风险敞口",
            "□ 评估账户风险率",
            "□ 准备减仓预案"
        ]

        return response

    def _generate_execution_response(
        self, response: AdvisorResponse, task: UrgentTask
    ) -> AdvisorResponse:
        """生成执行顾问响应"""
        response.analysis = f"""
基于交易执行最佳实践：

【流动性管理】
- 当前市场流动性：需要评估
- 建议：分批成交，避免冲击
- 大单拆分：建议拆分为10笔以内

【执行策略】
- 限价单优先于市价单
- 避免在波动剧烈时执行
- 分散成交时间

【滑点控制】
- 预期滑点：0.1%-0.5%
- 建议使用TWAP/VWAP策略
- 接受合理滑点范围
"""

        response.risk_control_principles = [
            "流动性优先",
            "分批执行",
            "滑点可控"
        ]

        response.suggestions = [
            "1. 使用限价单，分批成交",
            "2. 监控市场深度",
            "3. 接受合理滑点（<0.5%）",
            "4. 如流动性不足，改用市价单"
        ]

        response.action_items = [
            "□ 检查市场深度",
            "□ 准备限价单",
            "□ 监控成交进度"
        ]

        return response

    def _generate_market_intel_response(
        self, response: AdvisorResponse, task: UrgentTask
    ) -> AdvisorResponse:
        """生成市场情报顾问响应"""
        response.analysis = f"""
基于市场分析框架：

【趋势判断】
- 当前趋势：需要确认
- 支撑位：待识别
- 阻力位：待识别

【情绪评估】
- 市场情绪：谨慎观望
- 恐慌/贪婪指数：偏恐慌
- 建议：不要在恐慌时做决策

【关键价位】
- 密切关注近期低点支撑
- 关注成交量变化
- 等待企稳信号
"""

        response.risk_control_principles = [
            "顺势而为",
            "不猜底摸顶",
            "等待确认信号"
        ]

        response.suggestions = [
            "1. 等待趋势企稳",
            "2. 不要在恐慌时抛售",
            "3. 关注关键技术位",
            "4. 保持冷静，按计划执行"
        ]

        response.action_items = [
            "□ 识别关键支撑阻力",
            "□ 监控趋势变化",
            "□ 等待企稳信号"
        ]

        return response

    def _generate_operations_response(
        self, response: AdvisorResponse, task: UrgentTask
    ) -> AdvisorResponse:
        """生成运营顾问响应"""
        response.analysis = f"""
基于系统运营原则：

【系统状态】
- 交易系统：正常
- 数据通道：正常
- 自动化策略：待确认

【协调事项】
- 各部门状态同步
- 紧急联系人通知
- 应急预案准备
"""

        response.risk_control_principles = [
            "系统稳定优先",
            "信息同步",
            "协调各方"
        ]

        response.suggestions = [
            "1. 确认所有系统正常",
            "2. 通知相关人员",
            "3. 暂停非必要自动化",
            "4. 准备备用方案"
        ]

        response.action_items = [
            "□ 检查系统健康",
            "□ 通知紧急联系人",
            "□ 暂停高风险策略"
        ]

        return response

    def _generate_compliance_response(
        self, response: AdvisorResponse, task: UrgentTask
    ) -> AdvisorResponse:
        """生成合规顾问响应"""
        response.analysis = f"""
基于合规审查原则：

【合规检查】
- 操作是否符合流程：是
- 是否需要记录：是
- 风险提示是否到位：待确认

【审计要求】
- 所有决策需记录
- 保留完整日志
- 事后需要复盘
"""

        response.risk_control_principles = [
            "合规第一",
            "记录完整",
            "可追溯"
        ]

        response.suggestions = [
            "1. 记录所有操作决策",
            "2. 保存完整日志",
            "3. 事后进行合规审查",
            "4. 完善风控流程"
        ]

        response.action_items = [
            "□ 记录决策过程",
            "□ 保存操作日志",
            "□ 准备事后报告"
        ]

        return response

    def get_checklist(self, crisis_type: str) -> Optional[dict]:
        """获取应对清单"""
        return self.checklists.get(crisis_type)

    def format_escalation_report(
        self, task: UrgentTask, responses: List[AdvisorResponse]
    ) -> str:
        """格式化升级报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("🚨 紧急响应报告 - 顾问团队召集")
        lines.append("=" * 60)
        lines.append(f"触发时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"紧急程度: {task.urgency_level.value.upper()}")
        lines.append(f"触发原因: {task.reason}")
        lines.append("")

        # 老板原消息
        lines.append("📩 老板消息:")
        lines.append(f"  \"{task.boss_message}\"")
        lines.append(f"  (已等待 {task.time_elapsed_minutes:.0f} 分钟)")
        lines.append("")

        # 顾问响应
        lines.append("👥 顾问团队响应:")
        for resp in responses:
            lines.append(f"\n--- {resp.advisor} ({resp.role}) ---")
            lines.append(resp.analysis.strip())
            if resp.action_items:
                lines.append("\n行动清单:")
                for item in resp.action_items:
                    lines.append(f"  {item}")

        # 风险控制原则
        lines.append("")
        lines.append("⚖️ 传统金融风险控制原则:")
        for key, principle in self.risk_principles.items():
            lines.append(f"\n【{principle['name']}】")
            lines.append(f"  {principle['description']}")
            for rule in principle.get('rules', [])[:2]:
                lines.append(f"  • {rule}")

        # 应对清单
        lines.append("")
        lines.append("📋 紧急应对清单:")
        for crisis_type, checklist in self.checklists.items():
            if self._match_crisis(task.description, checklist):
                lines.append(f"\n【{checklist['name']}】")
                for action in checklist['checklist'][:5]:
                    lines.append(f"  {action}")
                lines.append("\n应对措施:")
                for action in checklist['actions'][:3]:
                    lines.append(f"  • {action}")

        lines.append("")
        lines.append("=" * 60)
        lines.append("💡 秘书建议:")
        lines.append("基于顾问团队分析，建议：")
        lines.append("1. 优先确保资本安全")
        lines.append("2. 严格执行止损纪律")
        lines.append("3. 保持冷静，不要恐慌")
        lines.append("4. 等待趋势明朗后再操作")
        lines.append("")
        lines.append("如需进一步帮助，请回复「继续」或「详细分析」")
        lines.append("=" * 60)

        return "\n".join(lines)


# ============================================================
# 主入口函数
# ============================================================

def run_risk_prediction(context: str, indicators: Dict[str, Any] = None) -> str:
    """运行风险预判分析"""
    engine = RiskPredictionEngine()
    assessment = engine.assess(context, indicators or {})
    return engine.format_report(assessment)


def check_urgency_and_escalate(
    message: str,
    time_elapsed: float = 0.0,
    auto_trigger: bool = False
) -> Tuple[bool, str]:
    """检查紧急程度并返回是否需要升级"""
    system = EmergencyResponseSystem()

    # 检查紧急性
    is_urgent, level, reason = system.is_urgent(message)

    if not is_urgent:
        return False, "消息不紧急，无需升级"

    # 创建任务
    task = UrgentTask(
        task_id=f"urgent_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        created_at=datetime.now().isoformat(),
        description=message,
        urgency_level=level,
        reason=reason,
        boss_message=message,
        time_elapsed_minutes=time_elapsed
    )

    # 检查是否触发升级
    should_escalate = system.should_trigger_escalation(task)

    if should_escalate or auto_trigger:
        # 召集顾问
        responses = system.activate_advisors(task)
        report = system.format_escalation_report(task, responses)
        return True, report

    return False, f"紧急程度: {level.value}, 等待时间: {time_elapsed:.0f}分钟"


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("🧪 测试风险预判系统")
    print("-" * 40)

    # 测试1: 风险预判
    print("\n【测试1: 风险预判】")
    result = run_risk_prediction(
        "BTC当前105000，担心行情暴跌，仓位较重",
        {"btc_price": 105000, "position_ratio": 0.8}
    )
    print(result[:2000])

    # 测试2: 紧急检测
    print("\n【测试2: 紧急检测】")
    emergency_system = EmergencyResponseSystem()
    is_urgent, level, reason = emergency_system.is_urgent("行情暴跌怎么办？")
    print(f"紧急: {is_urgent}, 级别: {level.value}, 原因: {reason}")

    # 测试3: 升级触发
    print("\n【测试3: 升级触发】")
    should_escalate, report = check_urgency_and_escalate(
        "BTC暴跌了！我的仓位要爆了！",
        time_elapsed=12,  # 12分钟无响应
        auto_trigger=True
    )
    print(f"触发升级: {should_escalate}")
    if should_escalate:
        print(report[:3000])
