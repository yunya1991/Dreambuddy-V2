#!/usr/bin/env python3
"""
全量模式测试：TOKEN_BUDGET=30000, auto_escalation=False
绕过 CLASSIC 回退，直接走 BAC 架构 + LLM 驱动链路
"""
import os, sys, json
sys.path.insert(0, '.')

os.environ['TOKEN_BUDGET'] = '30000'

from agents.agent_b_runner import load_memory, fetch_market_context
from core.intent_gateway import detect_intent
from core.chain_planner import ChainPlanner
from core.chain_router import ChainRouter
from execution.aster_spot import HyperliquidClient

client = HyperliquidClient('b')
mkt = fetch_market_context(client)
memory = load_memory()

# 设置 regime
mkt['regime'] = (
    'TREND_UP'   if mkt.get('change_24h', 0) > 2 else
    'TREND_DOWN' if mkt.get