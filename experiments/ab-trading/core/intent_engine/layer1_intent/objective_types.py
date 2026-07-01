#!/usr/bin/env python3
"""
目标类型体系 (Objective Types)

位置: experiments/ab-trading/core/intent_engine/layer1_intent/objective_types.py

9种目标类型，每种预定义复杂度和OKR模式，作为Layer 2的输入。
"""

OBJECTIVE_TYPES = {
    'market_query': {
        'name': '行情查询',
        'complexity': 'simple',
        'okr_mode': 'single',
        'domain': 'trading',
        'description': '简单的行情数据查询',
        'priority': 3,
        'keywords': [
            '行情', '价格', '涨跌', '走势', '现在', '多少钱',
            'price', 'quote', 'market', 'current',
        ],
        'default_clarify_needed': False,
    },

    'trend_analysis': {
        'name': '趋势分析',
        'complexity': 'standard',
        'okr_mode': 'single',
        'domain': 'analysis',
        'description': '单维度趋势分析',
        'priority': 5,
        'keywords': [
            '分析', '趋势', '方向', '看涨', '看跌',
            'trend', 'analysis', 'direction',
        ],
        'default_clarify_needed': False,
    },
    'deep_analysis': {
        'name': '深度分析',
        'complexity': 'deep',
        'okr_mode': 'multi',
        'domain': 'analysis',
        'description': '多维度综合分析',
        'priority': 7,
        'keywords': [
            '深度分析', '全面分析', '综合分析', '详细研究',
            '研究', '全面', '详细', '完整',
            'deep analysis', 'comprehensive analysis', 'in-depth research',
        ],
        'default_clarify_needed': False,
    },

    'trading_decision': {
        'name': '交易决策',
        'complexity': 'standard',
        'okr_mode': 'single',
        'domain': 'trading',
        'description': '完整的交易决策流程',
        'priority': 8,
        'keywords': [
            '交易决策', '买入', '卖出', '做多', '做空', '开仓', '入场', '可以买',
            'buy', 'sell', 'long', 'short', 'enter', 'trading decision',
        ],
        'default_clarify_needed': False,
    },
    'exit_evaluation': {
        'name': '离场评估',
        'complexity': 'standard',
        'okr_mode': 'single',
        'domain': 'trading',
        'description': '持仓离场评估',
        'priority': 8,
        'keywords': [
            '离场', '出场', '止盈', '止损', '平仓',
            'exit', 'close', 'take profit', 'stop loss',
        ],
        'default_clarify_needed': False,
    },
    'strategy_design': {
        'name': '策略设计',
        'complexity': 'deep',
        'okr_mode': 'multi',
        'domain': 'trading',
        'description': '完整交易策略设计',
        'priority': 9,
        'keywords': [
            '交易策略', '策略设计', '策略', '设计', '参数', '回测', '优化',
            'trading strategy', 'strategy', 'design', 'backtest', 'optimize',
        ],
        'default_clarify_needed': False,
    },

    'risk_assessment': {
        'name': '风险评估',
        'complexity': 'standard',
        'okr_mode': 'single',
        'domain': 'risk',
        'description': '风险评估与管理',
        'priority': 7,
        'keywords': [
            '风险', '风控', '评估', '仓位', '杠杆',
            'risk', 'risk management', 'position', 'leverage',
        ],
        'default_clarify_needed': False,
    },

    'portfolio_review': {
        'name': '组合回顾',
        'complexity': 'deep',
        'okr_mode': 'multi',
        'domain': 'portfolio',
        'description': '投资组合综合回顾',
        'priority': 6,
        'keywords': [
            '持仓', '组合', '收益', '回顾', '总结',
            'portfolio', 'holding', 'review', 'summary',
        ],
        'default_clarify_needed': False,
    },

    'three_screen_trade': {
        'name': '三屏交易分析',
        'complexity': 'standard',
        'okr_mode': 'single',
        'domain': 'trading',
        'description': 'Elder三屏交易体系分析',
        'priority': 8,
        'keywords': [
            '三屏交易', '三屏交易法', '三屏体系', '三屏',
            '周线', '日线', '日内',
            'three screen', 'elder triple screen', 'elder',
        ],
        'default_clarify_needed': False,
    },
}


def get_objective_type(obj_type: str) -> dict:
    """获取目标类型定义"""
    return OBJECTIVE_TYPES.get(obj_type, {})


def list_objective_types() -> list:
    """列出所有支持的目标类型"""
    return list(OBJECTIVE_TYPES.keys())


def search_objective_types(keyword: str) -> list:
    """按关键词搜索目标类型"""
    results = []
    keyword = keyword.lower()
    for obj_id, obj_def in OBJECTIVE_TYPES.items():
        if keyword in obj_def['name'].lower():
            results.append(obj_id)
            continue
        for kw in obj_def['keywords']:
            if keyword in kw.lower():
                results.append(obj_id)
                break
    return results
