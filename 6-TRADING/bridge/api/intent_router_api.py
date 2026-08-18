#!/usr/bin/env python3
"""
意图路由API - Intent Routing API
分析用户自然语言输入，智能路由到对应SKILL
"""

from flask import Blueprint, jsonify, request
import re
from datetime import datetime

intent_bp = Blueprint('intent', __name__)

# 意图关键词映射
INTENT_PATTERNS = {
    # 市场分析意图
    "market_analysis": {
        "keywords": ["分析", "市场", "行情", "趋势", "走势", "怎么看", "分析一下"],
        "skills": ["A1", "A2", "regime"],
        "priority": 1
    },
    # 交易执行意图
    "trade_execution": {
        "keywords": ["买入", "做多", "开多", "卖出", "做空", "开空", "买", "卖", "建仓", "平仓"],
        "skills": ["A5", "A9"],
        "priority": 2
    },
    # 风险控制意图
    "risk_control": {
        "keywords": ["止损", "止盈", "风控", "仓位", "风险", "限制亏损"],
        "skills": ["A9", "risk"],
        "priority": 3
    },
    # 情报监控意图
    "intelligence": {
        "keywords": ["监控", "关注", "警报", "提醒", "通知", "监视"],
        "skills": ["A6", "intelligence"],
        "priority": 1
    },
    # 策略设计意图
    "strategy_design": {
        "keywords": ["策略", "方案", "计划", "怎么操作", "策略设计"],
        "skills": ["A3", "A4", "strategy-parser"],
        "priority": 1
    },
    # 信号查询意图
    "signal_query": {
        "keywords": ["信号", "指标", "技术", "MACD", "RSI", "均线"],
        "skills": ["signal", "regime"],
        "priority": 1
    },
    # 矛盾分析意图
    "contradiction": {
        "keywords": ["矛盾", "冲突", "对立", "多空"],
        "skills": ["A0", "A1"],
        "priority": 1
    },
    # 复盘意图
    "review": {
        "keywords": ["复盘", "总结", "回顾", "反思", "评估"],
        "skills": ["A7", "A8", "episodes"],
        "priority": 2
    },
    # 离场意图
    "exit": {
        "keywords": ["离场", "退出", "结束", "平仓", "止损", "止盈"],
        "skills": ["A9", "exit"],
        "priority": 3
    }
}

# 币种提取模式
SYMBOL_PATTERNS = [
    r"(BTC|比特币)",
    r"(ETH|以太坊|以太)",
    r"(SOL|Solana)",
    r"(DOGE|狗狗币)",
    r"(XRP|瑞波)",
    r"(ADA|艾达)",
]

# 方向提取模式
DIRECTION_PATTERNS = [
    (r"(做多|买入|买多|开多|多头|多)", "long"),
    (r"(做空|卖出|卖空|开空|空头|空)", "short"),
]


def extract_symbol(text: str) -> str:
    """从文本中提取交易币种"""
    for pattern in SYMBOL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            symbol_map = {
                "BTC": "BTC-USDT-SWAP",
                "比特币": "BTC-USDT-SWAP",
                "ETH": "ETH-USDT-SWAP",
                "以太坊": "ETH-USDT-SWAP",
                "以太": "ETH-USDT-SWAP",
                "SOL": "SOL-USDT-SWAP",
                "DOGE": "DOGE-USDT-SWAP",
                "XRP": "XRP-USDT-SWAP",
                "ADA": "ADA-USDT-SWAP",
            }
            keyword = match.group(1)
            return symbol_map.get(keyword, keyword + "-USDT-SWAP")
    return "BTC-USDT-SWAP"  # 默认


def extract_direction(text: str) -> str:
    """从文本中提取交易方向"""
    for pattern, direction in DIRECTION_PATTERNS:
        if re.search(pattern, text):
            return direction
    return None


def detect_intent(text: str) -> dict:
    """检测用户意图"""
    text_lower = text.lower()
    
    intent_scores = {}
    for intent_name, intent_info in INTENT_PATTERNS.items():
        score = 0
        matched_keywords = []
        for keyword in intent_info["keywords"]:
            if keyword.lower() in text_lower:
                score += 1
                matched_keywords.append(keyword)
        
        if score > 0:
            intent_scores[intent_name] = {
                "score": score,
                "keywords": matched_keywords,
                "skills": intent_info["skills"],
                "priority": intent_info["priority"]
            }
    
    if not intent_scores:
        return {
            "primary_intent": "unknown",
            "confidence": 0,
            "skills": [],
            "message": "无法识别意图，请明确描述您的需求"
        }
    
    # 按分数和优先级排序
    sorted_intents = sorted(
        intent_scores.items(),
        key=lambda x: (x[1]["score"], -x[1]["priority"]),
        reverse=True
    )
    
    primary = sorted_intents[0]
    
    return {
        "primary_intent": primary[0],
        "confidence": min(primary[1]["score"] * 0.3, 0.95),
        "keywords_matched": primary[1]["keywords"],
        "skills": primary[1]["skills"],
        "all_intents": intent_scores,
        "message": f"识别到 {primary[0]} 意图"
    }


@intent_bp.route('/route', methods=['POST'])
def route_intent():
    """意图路由主入口"""
    data = request.get_json() or {}
    user_input = data.get('text', '') or data.get('message', '') or data.get('input', '')
    
    if not user_input:
        return jsonify({
            "success": False,
            "error": "text/message/input parameter required"
        }), 400
    
    # 提取关键信息
    symbol = extract_symbol(user_input)
    direction = extract_direction(user_input)
    
    # 检测意图
    intent_result = detect_intent(user_input)
    
    # 构建路由结果
    route_result = {
        "success": True,
        "user_input": user_input,
        "intent": intent_result,
        "extracted": {
            "symbol": symbol,
            "direction": direction
        },
        "routing": {
            "primary_skill": intent_result["skills"][0] if intent_result["skills"] else None,
            "all_skills": intent_result["skills"],
            "suggested_action": get_action_suggestion(intent_result["primary_intent"])
        },
        "timestamp": datetime.now().isoformat()
    }
    
    return jsonify(route_result)


@intent_bp.route('/batch', methods=['POST'])
def batch_route():
    """批量意图路由"""
    data = request.get_json() or {}
    inputs = data.get('inputs', [])
    
    if not inputs:
        return jsonify({
            "success": False,
            "error": "inputs array required"
        }), 400
    
    results = []
    for text in inputs:
        results.append({
            "input": text,
            "result": route_intent_inner(text)
        })
    
    return jsonify({
        "success": True,
        "count": len(results),
        "results": results
    })


def route_intent_inner(text: str) -> dict:
    """内部意图路由函数"""
    symbol = extract_symbol(text)
    direction = extract_direction(text)
    intent_result = detect_intent(text)
    
    return {
        "symbol": symbol,
        "direction": direction,
        "intent": intent_result["primary_intent"],
        "confidence": intent_result["confidence"],
        "skills": intent_result["skills"]
    }


def get_action_suggestion(intent: str) -> str:
    """根据意图获取建议操作"""
    suggestions = {
        "market_analysis": "建议执行 A1调研 + A2第一性原理 分析",
        "trade_execution": "建议执行 A5综合执行 模块",
        "risk_control": "建议执行 A9离场决策 + 仓位风控",
        "intelligence": "建议执行 A6情报监控",
        "strategy_design": "建议执行 A3战术验证 + 战略解析",
        "signal_query": "建议查询 Regime检测 + 信号评分",
        "contradiction": "建议执行 A0矛盾识别 + A1矛盾调查",
        "review": "建议执行 A7实践理论 + Episodes记录",
        "exit": "建议执行 A9离场决策",
        "unknown": "请明确描述您的需求"
    }
    return suggestions.get(intent, "无法确定操作建议")


@intent_bp.route('/examples', methods=['GET'])
def get_examples():
    """获取各意图的示例"""
    return jsonify({
        "success": True,
        "examples": {
            "market_analysis": ["BTC现在行情怎么样", "分析一下以太坊走势", "市场趋势如何"],
            "trade_execution": ["买入1手BTC", "做空ETH", "开多10张SOL"],
            "risk_control": ["设置止损", "止盈怎么设", "仓位多少合适"],
            "intelligence": ["帮我监控BTC价格", "价格到了提醒我", "开启警报"],
            "strategy_design": ["给我一个交易策略", "怎么操作比较好", "制定方案"],
            "signal_query": ["现在有哪些信号", "MACD怎么看", "RSI指标"],
            "contradiction": ["多空矛盾在哪", "分析主要矛盾"],
            "review": ["复盘一下", "总结这笔交易", "反思最近的操作"]
        }
    })
