"""
交易能力域 — 策略意图类型

本模块定义交易领域特有的策略意图，属于 DreamOS 能力域层（capabilities/trading/）。
与操作系统内核层的对话意图（core/sense/dialogue_intent/）分离。

设计原则:
    - 策略意图回答"该用什么交易策略"（趋势跟随/均值回归/突破...）
    - 对话意图回答"用户想做什么"（查询/分析/交易/策略/风险/对话）
    - 对话意图 → 策略意图的映射由编排层完成

核心类型:
    - StrategyIntent     策略意图枚举（7 种交易策略）
    - get_strategy_definition()  获取策略意图定义
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List


class StrategyIntent(str, Enum):
    """交易策略意图（交易能力域特有）

    7 种预定义策略意图，决定 A/C/F 编排链的选择。
    注意：这是交易领域概念，不属于操作系统内核。
    """
    TREND_FOLLOWING = "TREND_FOLLOWING"        # 趋势跟随
    MEAN_REVERSION = "MEAN_REVERSION"          # 均值回归
    FUNDAMENTAL_PLAY = "FUNDAMENTAL_PLAY"      # 基本面驱动
    BREAKOUT = "BREAKOUT"                       # 突破
    KNOWLEDGE_MATCH = "KNOWLEDGE_MATCH"         # 知识库匹配
    DEEP_ANALYSIS = "DEEP_ANALYSIS"             # A系列深度分析
    CLASSIC_PIPELINE = "CLASSIC_PIPELINE"       # 经典交易流水线 C0-C8
    UNCERTAIN = "UNCERTAIN"                     # 不确定/需要澄清

    @classmethod
    def all_types(cls) -> List[str]:
        return [t.value for t in cls if t != cls.UNCERTAIN]


# 可扩展的自定义策略意图注册表
_custom_strategy_types: Dict[str, Dict[str, Any]] = {}


def register_strategy_type(type_id: str, definition: Dict[str, Any]) -> bool:
    """注册自定义策略意图类型

    Args:
        type_id: 策略意图类型 ID（全大写）
        definition: 定义（name / description / chain / priority / keywords）

    Returns:
        是否注册成功
    """
    if not type_id or not definition:
        return False
    _custom_strategy_types[type_id] = definition
    return True


def get_strategy_definition(intent_type: str) -> Dict[str, Any]:
    """获取策略意图类型定义"""
    standard = {
        "TREND_FOLLOWING": {
            "name": "趋势跟随",
            "description": "识别趋势行情，顺势操作",
            "chain": "A",
            "priority": 1,
            "keywords": ["趋势", "trend", "均线", "ma", "ema", "突破趋势", "顺势", "做多", "趋势跟随", "多头", "空头"],
        },
        "MEAN_REVERSION": {
            "name": "均值回归",
            "description": "识别超买超卖，逆向操作",
            "chain": "A",
            "priority": 2,
            "keywords": ["均值回归", "超买超卖", "超买", "超卖", "回调", "反弹", "rsi", "布林", "boll", "逆向", "做空", "抄底"],
        },
        "FUNDAMENTAL_PLAY": {
            "name": "基本面驱动",
            "description": "基于新闻/资金流/链上数据驱动",
            "chain": "F",
            "priority": 3,
            "keywords": ["新闻", "news", "资金", "funding", "链上", "onchain", "宏观"],
        },
        "BREAKOUT": {
            "name": "突破",
            "description": "识别关键位突破",
            "chain": "C",
            "priority": 2,
            "keywords": ["突破", "breakout", "阻力", "支撑", "新高", "新低"],
        },
        "KNOWLEDGE_MATCH": {
            "name": "知识库匹配",
            "description": "从历史模式/知识库中匹配",
            "chain": "A",
            "priority": 4,
            "keywords": ["模式", "历史", "教训", "lesson", "记忆"],
        },
        "DEEP_ANALYSIS": {
            "name": "深度分析(A系列)",
            "description": "A系列深度分析任务，委托 Harness 大模型 SKILL 桥接执行（A0矛盾论/A1深度调研/A2第一性原理）",
            "chain": "A",
            "priority": 1,
            "keywords": [
                "深度分析", "深度调研", "深度报告", "调研报告", "战略分析", "战略研究",
                "a系列", "a链", "a0", "a1", "a2", "a3",
                "矛盾论", "矛盾分析", "主要矛盾", "第一性原理", "六因子",
            ],
        },
        "CLASSIC_PIPELINE": {
            "name": "经典交易流水线",
            "description": "C0-C8 八阶段经典交易流水线：环境扫描→品种筛选→信号识别→回测验证→风险评估→参数优化→计划生成→执行监控→绩效归因",
            "chain": "C_CLASSIC",
            "priority": 1,
            "keywords": [
                "经典流水线", "classic pipeline", "c0-c8", "c0c8",
                "八阶段", "经典交易", "经典管线",
            ],
        },
        "UNCERTAIN": {
            "name": "不确定",
            "description": "需要更多信息或澄清",
            "chain": "",
            "priority": 99,
            "keywords": [],
        },
    }

    if intent_type in standard:
        return standard[intent_type]
    if intent_type in _custom_strategy_types:
        return _custom_strategy_types[intent_type]
    return standard["UNCERTAIN"]
