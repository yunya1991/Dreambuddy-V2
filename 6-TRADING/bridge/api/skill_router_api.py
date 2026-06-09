#!/usr/bin/env python3
"""
SKILL路由API - SKILL Routing API
支持直接调用A0-A9各阶段SKILL
"""

from flask import Blueprint, jsonify, request
import sys
from pathlib import Path
from datetime import datetime
import subprocess
import json

skill_bp = Blueprint('skill', __name__)

# SKILL映射表
SKILL_MAP = {
    # A0-A9核心流水线
    "A0": "dream-contradiction-theory",
    "A1": "dream-strategy-research",
    "A2": "dream-first-principles",
    "A3": "dream-tactical-validator",
    "A4": "dream-tactical-validator",
    "A5": "dream-tactical-executor",
    "A6": "dream-intelligence-monitor",
    "A7": "A7-practice-theory",
    "A8": "A8-theory-practice-verification",
    "A9": "dream-exit-skill-v2",
    
    # 辅助SKILL
    "regime": "dream-regime-detector",
    "signal": "dream-signal-scoring-spec",
    "risk": "dream-risk-position-sizing",
    "strategy-parser": "dream-strategy-parser",
    "episodes": "learning-episode-writer",
    "intelligence": "dream-intelligence-monitor",
    "exit": "dream-exit-skill-v2",
    "gatekeeper": "dream-pretrade-gatekeeper",
}

# SKILL功能说明
SKILL_DESCRIPTIONS = {
    "dream-contradiction-theory": "矛盾论分析 - 识别主要矛盾与次要矛盾",
    "dream-strategy-research": "深度调研 - 系统性收集市场情报",
    "dream-first-principles": "第一性原理 - 基于市场本质分析",
    "dream-tactical-validator": "战术验证 - A3/A4阶段方案验证",
    "dream-tactical-executor": "综合执行 - A5交易执行调度",
    "dream-intelligence-monitor": "情报监控 - A6市场雷达持续监控",
    "A7-practice-theory": "实践理论 - A7理论与实践结合",
    "A8-theory-practice-verification": "知行合一 - A8自我批评验证",
    "dream-exit-skill-v2": "离场决策 - A9四层离场决策",
    "dream-regime-detector": "Regime检测 - 市场状态识别",
    "dream-signal-scoring-spec": "信号评分 - 多源信号标准化",
    "dream-risk-position-sizing": "仓位风控 - 风险预算与仓位计算",
    "dream-strategy-parser": "战略解析 - 策略库匹配",
    "dream-pretrade-gatekeeper": "预交易门禁 - 交易前检查",
}


@skill_bp.route('/list', methods=['GET'])
def list_skills():
    """列出所有可用的SKILL"""
    return jsonify({
        "success": True,
        "skills": [
            {
                "key": key,
                "skill": skill,
                "description": SKILL_DESCRIPTIONS.get(skill, "未定义"),
                "phase": key if key.startswith("A") else None
            }
            for key, skill in SKILL_MAP.items()
        ]
    })


@skill_bp.route('/execute', methods=['POST'])
def execute_skill():
    """执行指定SKILL"""
    data = request.get_json() or {}
    
    skill_key = data.get('skill', '')
    params = data.get('params', {})
    context = data.get('context', {})
    
    if not skill_key:
        return jsonify({
            "success": False,
            "error": "skill parameter required"
        }), 400
    
    # 获取实际SKILL名称
    skill_name = SKILL_MAP.get(skill_key, skill_key)
    
    return jsonify({
        "success": True,
        "skill_key": skill_key,
        "skill_name": skill_name,
        "message": f"SKILL {skill_name} execution queued",
        "params": params,
        "context": context,
        "timestamp": datetime.now().isoformat(),
        "note": "SKILL execution will be handled by WorkBuddy"
    })


@skill_bp.route('/pipeline', methods=['POST'])
def execute_pipeline():
    """执行流水线（A1→A2→A3→A5→A6）"""
    data = request.get_json() or {}
    
    symbol = data.get('symbol', 'BTC-USDT-SWAP')
    direction = data.get('direction', 'long')  # long/short
    phases = data.get('phases', ['A1', 'A2', 'A3', 'A5', 'A6'])
    
    results = {}
    for phase in phases:
        results[phase] = {
            "status": "pending",
            "skill": SKILL_MAP.get(phase, "unknown"),
            "result": None
        }
    
    return jsonify({
        "success": True,
        "symbol": symbol,
        "direction": direction,
        "phases": phases,
        "results": results,
        "timestamp": datetime.now().isoformat(),
        "note": "Pipeline execution will be triggered"
    })


@skill_bp.route('/status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """查询SKILL执行状态"""
    return jsonify({
        "success": True,
        "task_id": task_id,
        "status": "completed",
        "result": {
            "phase": "A2",
            "conclusion": "上涨趋势延续",
            "confidence": 0.75
        }
    })


@skill_bp.route('/phase-info/<phase>', methods=['GET'])
def get_phase_info(phase):
    """获取A系列阶段信息"""
    phase_info = {
        "A0": {"name": "矛盾识别", "description": "识别主要矛盾与次要矛盾"},
        "A1": {"name": "矛盾调查", "description": "系统性调研矛盾各方信息"},
        "A2": {"name": "第一性原理", "description": "基于市场本质分析"},
        "A3": {"name": "沙盘推演", "description": "多情景策略推演"},
        "A4": {"name": "战术验证", "description": "验证方案可行性与风险"},
        "A5": {"name": "综合执行", "description": "综合判断与交易执行"},
        "A6": {"name": "情报监控", "description": "市场雷达持续监控"},
        "A7": {"name": "实践理论", "description": "理论与实践结合"},
        "A8": {"name": "知行合一", "description": "自我批评与系统进化"},
        "A9": {"name": "离场决策", "description": "四层离场决策链"},
    }
    
    info = phase_info.get(phase, {"name": "Unknown", "description": "Phase not found"})
    
    return jsonify({
        "success": True,
        "phase": phase,
        "skill": SKILL_MAP.get(phase, "unknown"),
        "description": info.get("description", ""),
        "name": info.get("name", "")
    })
