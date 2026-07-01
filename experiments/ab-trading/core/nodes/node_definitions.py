#!/usr/bin/env python3
"""
节点元数据定义

位置: experiments/ab-trading/core/nodes/node_definitions.py

所有节点的规范化元数据定义：
- 输入输出Schema
- 超时、重试、降级策略
- 适用范围
- 与模块ID的映射

设计原则:
- 集中管理，便于维护
- 与模块注册表对齐 (node_id ↔ module_id)
- 每个节点都有完整的元数据描述
"""

from .node_registry import (
    NodeInfo,
    IOSchema,
    NodeRetryPolicy,
    NodeFallbackPolicy,
)


# ============================================================
# 节点定义列表
# ============================================================

def get_all_node_definitions() -> list:
    """获取所有节点定义

    Returns:
        List[Dict] - 节点定义字典列表，可直接转为 NodeInfo
    """
    return [
        # ========================================
        # C 链：技术/量化层
        # ========================================
        {
            "node_id": "classic-indicator-scan",
            "name": "C1 技术扫描",
            "description": "经典指标系统技术扫描，多维度技术指标分析",
            "version": "1.0",
            "chain": "C",
            "module_id": "classic-indicator-scan",
            "category": "classic_indicators",
            "node_type": "local_node",
            "timeout_ms": 10000,
            "estimated_tokens": 0,
            "estimated_latency_ms": 500,
            "confidence_range": [30.0, 75.0],
            "input_schema": {
                "required_fields": ["mkt"],
                "optional_fields": ["memory", "data"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据（价格、成交量、各种指标）",
                    "memory": "记忆/上下文数据",
                    "data": "附加数据",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                },
                "field_descriptions": {
                    "direction": "方向 (long/short/hold)",
                    "confidence": "置信度 (0-1)",
                    "rationale": "分析理由列表",
                    "data": "详细数据",
                },
            },
            "retry_policy": {
                "enabled": False,
                "max_retries": 2,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": None,
                "fallback_type": "local",
                "fallback_reason": "本地实现，零外部依赖",
            },
            "applicable_stages": ["analysis", "execution"],
            "applicable_intents": ["tech_analysis", "market_scan"],
            "market_conditions": ["all"],
            "tags": ["technical", "indicators", "scan"],
            "legacy_id": "C1_技术扫描",
        },

        # ========================================
        # A 链：分析/决策层
        # ========================================
        {
            "node_id": "dream-contradiction-theory",
            "name": "A0 矛盾论",
            "description": "矛盾论分析框架：资金面、情绪面、技术面多维度矛盾分析",
            "version": "2.0",
            "chain": "A",
            "module_id": "dream-contradiction-theory",
            "category": "analysis_core",
            "node_type": "skill_node",
            "timeout_ms": 30000,
            "estimated_tokens": 2000,
            "estimated_latency_ms": 5000,
            "confidence_range": [40.0, 85.0],
            "input_schema": {
                "required_fields": ["mkt"],
                "optional_fields": ["memory", "data", "a0"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                    "a0": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据",
                    "memory": "记忆数据",
                    "data": "输入数据",
                    "a0": "已有A0分析结果（可选）",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "dominant_force", "main_contradiction"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "dominant_force": "str",
                    "main_contradiction": "str",
                },
                "field_descriptions": {
                    "direction": "多空方向",
                    "confidence": "置信度",
                    "rationale": "分析理由",
                    "dominant_force": "主导力量",
                    "main_contradiction": "主要矛盾",
                },
            },
            "retry_policy": {
                "enabled": True,
                "max_retries": 2,
                "retry_on": ["timeout", "llm_error"],
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": "classic-indicator-scan",
                "fallback_type": "degrade",
                "fallback_reason": "A0不可用时降级到C1技术扫描",
            },
            "applicable_stages": ["analysis", "research", "strategy"],
            "applicable_intents": ["contradiction_analysis", "market_analysis"],
            "market_conditions": ["all"],
            "tags": ["contradiction", "analysis", "multi-dimension"],
            "legacy_id": "A0_矛盾论",
        },

        {
            "node_id": "dream-research-v2",
            "name": "A1 调研",
            "description": "深度调研分析：基本面、技术面、情绪面综合调研",
            "version": "2.0",
            "chain": "A",
            "module_id": "dream-research-v2",
            "category": "analysis_core",
            "node_type": "skill_node",
            "timeout_ms": 45000,
            "estimated_tokens": 4000,
            "estimated_latency_ms": 10000,
            "confidence_range": [45.0, 80.0],
            "input_schema": {
                "required_fields": ["mkt"],
                "optional_fields": ["memory", "data"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据",
                    "memory": "记忆数据",
                    "data": "调研主题/方向",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "research_findings"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "research_findings": "list",
                },
                "field_descriptions": {
                    "direction": "调研结论方向",
                    "confidence": "置信度",
                    "rationale": "调研理由",
                    "research_findings": "调研发现",
                },
            },
            "retry_policy": {
                "enabled": True,
                "max_retries": 2,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": "dream-contradiction-theory",
                "fallback_type": "degrade",
                "fallback_reason": "A1不可用时降级到A0矛盾论",
            },
            "applicable_stages": ["research", "analysis"],
            "applicable_intents": ["research", "deep_analysis"],
            "market_conditions": ["all"],
            "tags": ["research", "fundamental", "comprehensive"],
            "legacy_id": "A1_调研(含A0)",
        },

        {
            "node_id": "dream-first-principles",
            "name": "A2 第一性原理分析",
            "description": "第一性原理分析：阻力最小路径、MA轨迹法、矛盾处理2.0、逆向信号补偿",
            "version": "2.0",
            "chain": "A",
            "module_id": "dream-first-principles",
            "category": "analysis_core",
            "node_type": "skill_node",
            "timeout_ms": 60000,
            "estimated_tokens": 5000,
            "estimated_latency_ms": 15000,
            "confidence_range": [50.0, 90.0],
            "input_schema": {
                "required_fields": ["mkt"],
                "optional_fields": ["memory", "data", "a0"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                    "a0": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据",
                    "memory": "记忆数据",
                    "data": "附加数据",
                    "a0": "A0前置分析结果",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "path_analysis", "ma_trajectory"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "path_analysis": "dict",
                    "ma_trajectory": "dict",
                },
                "field_descriptions": {
                    "direction": "分析结论方向",
                    "confidence": "置信度",
                    "rationale": "分析理由",
                    "path_analysis": "阻力最小路径分析",
                    "ma_trajectory": "MA轨迹分析",
                },
            },
            "retry_policy": {
                "enabled": True,
                "max_retries": 2,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": "dream-contradiction-theory",
                "fallback_type": "degrade",
                "fallback_reason": "A2不可用时降级到A0矛盾论",
            },
            "applicable_stages": ["analysis", "strategy"],
            "applicable_intents": ["first_principles", "deep_analysis", "trend_analysis"],
            "market_conditions": ["all"],
            "tags": ["first_principles", "path_analysis", "ma_trend", "core"],
            "legacy_id": "A2_分析(含A0)",
        },

        {
            "node_id": "dream-strategy-engine",
            "name": "A3 策略设计",
            "description": "策略引擎：根据分析结果设计交易策略",
            "version": "1.0",
            "chain": "A",
            "module_id": "dream-strategy-engine",
            "category": "strategy",
            "node_type": "skill_node",
            "timeout_ms": 45000,
            "estimated_tokens": 3000,
            "estimated_latency_ms": 8000,
            "confidence_range": [40.0, 80.0],
            "input_schema": {
                "required_fields": ["mkt", "data"],
                "optional_fields": ["memory", "analysis_result"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                    "analysis_result": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据",
                    "memory": "记忆数据",
                    "data": "策略参数",
                    "analysis_result": "前置分析结果",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "strategy_plan"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "strategy_plan": "dict",
                },
                "field_descriptions": {
                    "direction": "策略方向",
                    "confidence": "置信度",
                    "rationale": "策略理由",
                    "strategy_plan": "策略计划详情",
                },
            },
            "retry_policy": {
                "enabled": True,
                "max_retries": 2,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": "dream-first-principles",
                "fallback_type": "degrade",
                "fallback_reason": "策略引擎不可用时降级到A2分析",
            },
            "applicable_stages": ["strategy", "execution"],
            "applicable_intents": ["strategy_design", "trade_plan"],
            "market_conditions": ["all"],
            "tags": ["strategy", "trading", "plan"],
            "legacy_id": "A3_策略设计(含A0)",
        },

        {
            "node_id": "dream-gate-v2",
            "name": "A4 门禁",
            "description": "交易门禁：风险评估、条件检查、是否执行",
            "version": "2.0",
            "chain": "A",
            "module_id": "dream-gate-v2",
            "category": "risk",
            "node_type": "skill_node",
            "timeout_ms": 20000,
            "estimated_tokens": 1500,
            "estimated_latency_ms": 3000,
            "confidence_range": [50.0, 85.0],
            "input_schema": {
                "required_fields": ["mkt", "data"],
                "optional_fields": ["memory", "strategy_result"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                    "strategy_result": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据",
                    "memory": "记忆数据",
                    "data": "门禁参数",
                    "strategy_result": "策略结果",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "passed", "block_reason"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "passed": "bool",
                    "block_reason": "str",
                },
                "field_descriptions": {
                    "direction": "门禁方向 (pass/block)",
                    "confidence": "置信度",
                    "rationale": "判断理由",
                    "passed": "是否通过",
                    "block_reason": "阻断原因",
                },
            },
            "retry_policy": {
                "enabled": False,
                "max_retries": 1,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": None,
                "fallback_type": "conservative",
                "fallback_reason": "门禁不可用时保守处理（默认阻断）",
            },
            "applicable_stages": ["gate", "execution"],
            "applicable_intents": ["risk_check", "gate_keep"],
            "market_conditions": ["all"],
            "tags": ["risk", "gate", "control"],
            "legacy_id": "A4_门禁",
        },

        {
            "node_id": "dream-exit-skill-v2",
            "name": "A9 离场评估",
            "description": "离场评估：止盈止损、出场时机判断",
            "version": "2.0",
            "chain": "A",
            "module_id": "dream-exit-skill-v2",
            "category": "exit",
            "node_type": "skill_node",
            "timeout_ms": 30000,
            "estimated_tokens": 2500,
            "estimated_latency_ms": 5000,
            "confidence_range": [45.0, 85.0],
            "input_schema": {
                "required_fields": ["mkt", "data"],
                "optional_fields": ["memory", "position"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                    "position": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据",
                    "memory": "记忆数据",
                    "data": "持仓信息",
                    "position": "当前持仓",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "exit_signal", "exit_price"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "exit_signal": "str",
                    "exit_price": "float",
                },
                "field_descriptions": {
                    "direction": "离场方向 (exit/hold)",
                    "confidence": "置信度",
                    "rationale": "离场理由",
                    "exit_signal": "离场信号类型",
                    "exit_price": "建议离场价格",
                },
            },
            "retry_policy": {
                "enabled": True,
                "max_retries": 2,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": "classic-indicator-scan",
                "fallback_type": "degrade",
                "fallback_reason": "A9不可用时降级到技术指标判断",
            },
            "applicable_stages": ["exit", "monitoring"],
            "applicable_intents": ["exit_evaluation", "stop_loss", "take_profit"],
            "market_conditions": ["all"],
            "tags": ["exit", "risk", "trading"],
            "legacy_id": "A9_离场评估",
        },

        # ========================================
        # F 链：基本面层
        # ========================================
        {
            "node_id": "fundamental-news-analysis",
            "name": "F1 新闻分析",
            "description": "新闻资讯分析：市场新闻、事件驱动分析",
            "version": "1.0",
            "chain": "F",
            "module_id": "fundamental-news-analysis",
            "category": "news",
            "node_type": "local_node",
            "timeout_ms": 15000,
            "estimated_tokens": 0,
            "estimated_latency_ms": 2000,
            "confidence_range": [25.0, 65.0],
            "input_schema": {
                "required_fields": ["mkt"],
                "optional_fields": ["memory", "data"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据",
                    "memory": "记忆数据",
                    "data": "新闻数据",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "news_sentiment"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "news_sentiment": "str",
                },
                "field_descriptions": {
                    "direction": "新闻影响方向",
                    "confidence": "置信度",
                    "rationale": "分析理由",
                    "news_sentiment": "新闻情绪",
                },
            },
            "retry_policy": {
                "enabled": False,
                "max_retries": 1,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": None,
                "fallback_type": "neutral",
                "fallback_reason": "新闻不可用时中性处理",
            },
            "applicable_stages": ["analysis", "research"],
            "applicable_intents": ["news_analysis", "event_driven"],
            "market_conditions": ["all"],
            "tags": ["news", "fundamental", "event"],
            "legacy_id": "F1_新闻",
        },

        {
            "node_id": "fundamental-fund-flow",
            "name": "F2 资金流分析",
            "description": "资金流分析：主力资金、北向资金、资金流向追踪",
            "version": "1.0",
            "chain": "F",
            "module_id": "fundamental-fund-flow",
            "category": "fund_flow",
            "node_type": "local_node",
            "timeout_ms": 10000,
            "estimated_tokens": 0,
            "estimated_latency_ms": 1000,
            "confidence_range": [30.0, 70.0],
            "input_schema": {
                "required_fields": ["mkt"],
                "optional_fields": ["memory", "data"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据（含资金流数据）",
                    "memory": "记忆数据",
                    "data": "附加数据",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "flow_direction"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "flow_direction": "str",
                },
                "field_descriptions": {
                    "direction": "资金流方向",
                    "confidence": "置信度",
                    "rationale": "分析理由",
                    "flow_direction": "资金流向 (inflow/outflow)",
                },
            },
            "retry_policy": {
                "enabled": False,
                "max_retries": 1,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": None,
                "fallback_type": "neutral",
                "fallback_reason": "资金流数据不可用时中性处理",
            },
            "applicable_stages": ["analysis", "monitoring"],
            "applicable_intents": ["fund_flow", "capital_analysis"],
            "market_conditions": ["all"],
            "tags": ["fund_flow", "capital", "fundamental"],
            "legacy_id": "F2_资金流",
        },

        {
            "node_id": "fundamental-sentiment",
            "name": "F3 情绪分析",
            "description": "市场情绪分析：恐慌贪婪指数、情绪指标分析",
            "version": "1.0",
            "chain": "F",
            "module_id": "fundamental-sentiment",
            "category": "sentiment",
            "node_type": "local_node",
            "timeout_ms": 10000,
            "estimated_tokens": 0,
            "estimated_latency_ms": 1000,
            "confidence_range": [25.0, 65.0],
            "input_schema": {
                "required_fields": ["mkt"],
                "optional_fields": ["memory", "data"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据（含情绪指标）",
                    "memory": "记忆数据",
                    "data": "附加数据",
                },
            },
            "output_schema": {
                "required_fields": ["direction", "confidence"],
                "optional_fields": ["rationale", "data", "sentiment_index"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "sentiment_index": "float",
                },
                "field_descriptions": {
                    "direction": "情绪方向",
                    "confidence": "置信度",
                    "rationale": "分析理由",
                    "sentiment_index": "情绪指数 (0-100)",
                },
            },
            "retry_policy": {
                "enabled": False,
                "max_retries": 1,
            },
            "fallback_policy": {
                "enabled": True,
                "fallback_node_id": None,
                "fallback_type": "neutral",
                "fallback_reason": "情绪数据不可用时中性处理",
            },
            "applicable_stages": ["analysis", "monitoring"],
            "applicable_intents": ["sentiment_analysis", "market_sentiment"],
            "market_conditions": ["all"],
            "tags": ["sentiment", "psychology", "fundamental"],
            "legacy_id": "F3_情绪",
        },

        # ========================================
        # 其他：潜意识层
        # ========================================
        {
            "node_id": "dream-oneirology",
            "name": "做梦部",
            "description": "潜意识/梦境分析：非线性思维、创意生成、反直觉思考",
            "version": "1.0",
            "chain": "G",
            "module_id": "dream-oneirology",
            "category": "subconscious",
            "node_type": "skill_node",
            "timeout_ms": 30000,
            "estimated_tokens": 2000,
            "estimated_latency_ms": 8000,
            "confidence_range": [20.0, 60.0],
            "input_schema": {
                "required_fields": ["data"],
                "optional_fields": ["mkt", "memory"],
                "field_types": {
                    "mkt": "dict",
                    "memory": "dict",
                    "data": "dict",
                },
                "field_descriptions": {
                    "mkt": "市场数据",
                    "memory": "记忆数据",
                    "data": "做梦主题/问题",
                },
            },
            "output_schema": {
                "required_fields": [],
                "optional_fields": ["direction", "confidence", "rationale", "data", "dream_content"],
                "field_types": {
                    "direction": "str",
                    "confidence": "float",
                    "rationale": "list[str]",
                    "data": "dict",
                    "dream_content": "str",
                },
                "field_descriptions": {
                    "direction": "直觉方向（仅供参考）",
                    "confidence": "置信度（较低）",
                    "rationale": "梦境解析",
                    "dream_content": "梦境内容",
                },
            },
            "retry_policy": {
                "enabled": False,
                "max_retries": 1,
            },
            "fallback_policy": {
                "enabled": False,
                "fallback_node_id": None,
                "fallback_type": "none",
                "fallback_reason": "做梦部是可选模块，不可用时跳过",
            },
            "applicable_stages": ["research", "creativity"],
            "applicable_intents": ["dream", "creativity", "counter_intuitive"],
            "market_conditions": ["all"],
            "tags": ["subconscious", "creativity", "dream"],
            "legacy_id": "做梦部",
        },
    ]


# ============================================================
# 旧ID → 新ID映射
# ============================================================

LEGACY_TO_NEW_ID = {
    "C1_技术扫描": "classic-indicator-scan",
    "A0_矛盾论": "dream-contradiction-theory",
    "A1_调研(含A0)": "dream-research-v2",
    "A2_分析(含A0)": "dream-first-principles",
    "A3_策略设计(含A0)": "dream-strategy-engine",
    "A4_门禁": "dream-gate-v2",
    "A9_离场评估": "dream-exit-skill-v2",
    "F1_新闻": "fundamental-news-analysis",
    "F2_资金流": "fundamental-fund-flow",
    "F3_情绪": "fundamental-sentiment",
    "做梦部": "dream-oneirology",
}

NEW_TO_LEGACY_ID = {v: k for k, v in LEGACY_TO_NEW_ID.items()}


def map_legacy_id(legacy_id: str) -> str:
    """旧ID转新ID（找不到则原样返回）"""
    return LEGACY_TO_NEW_ID.get(legacy_id, legacy_id)


def map_new_id(new_id: str) -> str:
    """新ID转旧ID（找不到则原样返回）"""
    return NEW_TO_LEGACY_ID.get(new_id, new_id)


__all__ = [
    "get_all_node_definitions",
    "LEGACY_TO_NEW_ID",
    "NEW_TO_LEGACY_ID",
    "map_legacy_id",
    "map_new_id",
]
