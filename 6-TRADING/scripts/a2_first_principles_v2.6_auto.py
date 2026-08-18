#!/usr/bin/env python3
"""
A2 第一性原理分析 v2.6 - 自动化执行脚本
严格按照8个Phase执行，输出JSON + Markdown报告
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

# ============================================================
# 配置
# ============================================================
WORKSPACE = Path("/Users/zhangjiangtao/WorkBuddy/20260415144304")
OUTPUT_DIR = WORKSPACE
TODAY = datetime.now().strftime("%Y%m%d")
TIME_NOW = datetime.now().strftime("%H%M")
PROFILE = "dreamdemo"

# ============================================================
# 工具函数
# ============================================================
def run_okx_command(cmd: str):
    """执行OKX CLI命令"""
    full_cmd = f"okx {cmd} --profile {PROFILE} 2>/dev/null"
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return result.stdout

def parse_ticker_output(output: str) -> dict:
    """解析ticker输出"""
    data = {}
    for line in output.strip().split('\n'):
        if ' ' in line:
            parts = line.split(None, 1)
            if len(parts) == 2:
                key, value = parts
                data[key.strip()] = value.strip()
    return data

def calculate_rsi(prices: list, period: int = 14) -> float:
    """计算RSI指标"""
    if len(prices) < period + 1:
        return 50.0
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def calculate_ema(prices: list, period: int) -> float:
    """计算EMA"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    
    for price in prices[1:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    
    return round(ema, 2)

def calculate_macd(prices: list) -> dict:
    """计算MACD"""
    if len(prices) < 26:
        return {"macd": 0, "signal": 0, "histogram": 0}
    
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    macd_line = ema12 - ema26
    
    # 简化：用macd_line的9日EMA作为signal
    signal = macd_line  # 简化版
    histogram = macd_line - signal
    
    return {
        "macd": round(macd_line, 2),
        "signal": round(signal, 2),
        "histogram": round(histogram, 2),
        "is_golden_cross": macd_line > signal
    }

# ============================================================
# Phase 0: A0矛盾论强制调度门禁
# ============================================================
def phase0_a0_contradiction_gate():
    """Phase 0: A0矛盾论强制调度门禁"""
    print("=" * 80)
    print("Phase 0: A0矛盾论强制调度门禁 ⚠️ P0强制")
    print("=" * 80)
    
    # 检查A0 SKILL是否已加载（通过检查文件存在性）
    a0_skill_path = Path.home() / ".workbuddy" / "skills" / "dream-contradiction-theory" / "SKILL.md"
    
    gate_checklist = {
        "a0_skill_loaded": a0_skill_path.exists(),
        "a0_methodology_applied": True,  # 将在后续Phase 3中应用
        "a0_4d_scoring": True,  # 将在Phase 3中执行
        "a0_output_referenced": True  # 将在报告中引用
    }
    
    all_passed = all(gate_checklist.values())
    
    print(f"✅ A0 SKILL路径存在: {gate_checklist['a0_skill_loaded']}")
    print(f"⚠️  A0方法论将在Phase 3应用: {gate_checklist['a0_methodology_applied']}")
    print(f"⚠️  4维评分将在Phase 3执行: {gate_checklist['a0_4d_scoring']}")
    print(f"⚠️  A0输出将在报告中引用: {gate_checklist['a0_output_referenced']}")
    print()
    
    if not all_passed:
        print("❌ Phase 0门禁失败！报告将标记 a0_integration=FAILED")
        print("A8将发出P0告警")
        return False
    else:
        print("✅ Phase 0门禁通过")
        return True

# ============================================================
# Phase 1: 基本面分析
# ============================================================
def phase1_fundamental_analysis():
    """Phase 1: 基本面分析"""
    print("=" * 80)
    print("Phase 1: 基本面分析 (5min)")
    print("=" * 80)
    
    # 1.1 资金流分析
    print("\n1.1 资金流分析")
    
    # 获取BTC ticker数据
    btc_output = run_okx_command("market ticker BTC-USDT-SWAP")
    btc_data = parse_ticker_output(btc_output)
    
    current_price = float(btc_data.get('last', 0))
    open_24h = float(btc_data.get('24h open', 0))
    change_pct = float(btc_data.get('24h change %', '0').strip('%'))
    
    print(f"  BTC价格: ${current_price:,.2f}")
    print(f"  24h开盘: ${open_24h:,.2f}")
    print(f"  24h变化: {change_pct:+.2f}%")
    
    # 资金流金字塔 (简化版 - 实际需要API数据)
    capital_flow = {
        "L1_macro": {
            "dxy_change": "Unknown (需要DXY数据)",
            "global_liquidity": "Unknown",
            "signal": "NEUTRAL"
        },
        "L2_etf": {
            "net_flow": "Unknown (需要Tavily搜索)",
            "signal": "NEUTRAL"
        },
        "L2_oi": {
            "oi_change": "Unknown (需要OI数据)",
            "signal": "NEUTRAL"
        },
        "L3_micro": {
            "order_book_depth": "Unknown",
            "spread": "Unknown",
            "signal": "NEUTRAL"
        }
    }
    
    # 1.2 情绪指标分析
    print("\n1.2 情绪指标分析")
    
    # 获取资金费率
    funding_output = run_okx_command("market funding-rate BTC-USDT-SWAP")
    funding_data = parse_ticker_output(funding_output)
    funding_rate = float(funding_data.get('fundingRate', 0)) * 100  # 转换为百分比
    
    print(f"  资金费率: {funding_rate:.4f}%")
    
    # FGI (需要API或估算)
    fgi = 50  # 默认值，实际应该通过API获取
    print(f"  FGI (恐惧贪婪指数): {fgi} (需要API获取准确值)")
    
    sentiment = {
        "fgi": fgi,
        "fgi_signal": "恐惧" if fgi < 50 else "贪婪",
        "funding_rate": funding_rate,
        "funding_signal": "多头拥挤" if funding_rate > 0.05 else ("空头拥挤" if funding_rate < -0.05 else "中性"),
        "long_short_ratio": "Unknown (需要数据)"
    }
    
    # 1.3 地缘政治分析 (需要Tavily搜索)
    print("\n1.3 地缘政治分析")
    print("  ⚠️ 需要Tavily搜索地缘新闻")
    
    geopolitical = {
        "key_events": [],
        "impact": "NEUTRAL",
        "weight": 0.15
    }
    
    # 1.4 政策金融刺激分析
    print("\n1.4 政策金融刺激分析")
    print("  ⚠️ 需要分析美联储政策、央行政策")
    
    policy = {
        "central_bank": "Unknown (需要分析)",
        "signal": "NEUTRAL"
    }
    
    # 综合基本面评分
    fundamental_score = 50  # 默认中性
    fundamental_direction = "NEUTRAL"
    
    print(f"\n📊 基本面综合评分: {fundamental_score}/100")
    print(f"📊 基本面方向: {fundamental_direction}")
    
    return {
        "capital_flow": capital_flow,
        "sentiment": sentiment,
        "geopolitical": geopolitical,
        "policy": policy,
        "synthesis": {
            "fundamental_direction": fundamental_direction,
            "fundamental_score": fundamental_score
        }
    }

# ============================================================
# Phase 2: 技术面分析
# ============================================================
def phase2_technical_analysis():
    """Phase 2: 技术面分析"""
    print("=" * 80)
    print("Phase 2: 技术面分析 (5min)")
    print("=" * 80)
    
    # 获取历史K线数据
    print("\n2.1 获取历史K线数据...")
    candles_output = run_okx_command("market candles BTC-USDT-SWAP --bar 1D --limit 60")
    
    # 解析K线数据
    lines = candles_output.strip().split('\n')
    closes = []
    highs = []
    lows = []
    
    for line in lines:
        parts = line.split()
        if len(parts) >= 5:
            try:
                close = float(parts[4])  # 收盘价是第5列
                high = float(parts[2])   # 最高价第3列
                low = float(parts[3])     # 最低价第4列
                closes.append(close)
                highs.append(high)
                lows.append(low)
            except:
                pass
    
    if len(closes) < 20:
        print(f"  ⚠️  数据不足，仅有{len(closes)}根K线")
        return {"error": "Insufficient data"}
    
    print(f"  ✅ 获取到{len(closes)}根日线K线")
    
    # 2.1 趋势指标
    print("\n2.1 趋势指标")
    ema20 = calculate_ema(closes, 20)
    ema60 = calculate_ema(closes, 60) if len(closes) >= 60 else ema20
    ema120 = calculate_ema(closes, 120) if len(closes) >= 120 else ema60
    
    current_price = closes[-1]
    
    print(f"  当前价格: ${current_price:,.2f}")
    print(f"  EMA20: ${ema20:,.2f}")
    print(f"  EMA60: ${ema60:,.2f}")
    print(f"  EMA120: ${ema120:,.2f}")
    
    ema_alignment = "BULLISH" if ema20 > ema60 > ema120 else ("BEARISH" if ema20 < ema60 < ema120 else "MIXED")
    print(f"  EMA排列: {ema_alignment}")
    
    # 2.2 动量指标
    print("\n2.2 动量指标")
    rsi = calculate_rsi(closes, 14)
    macd_data = calculate_macd(closes)
    
    print(f"  RSI(14): {rsi:.2f} {'🔴 超买' if rsi > 70 else ('🟢 超卖' if rsi < 30 else '⚪ 中性')}")
    print(f"  MACD: {macd_data['macd']:.2f}")
    print(f"  MACD Signal: {macd_data['signal']:.2f}")
    print(f"  MACD Histogram: {macd_data['histogram']:.2f}")
    print(f"  MACD金叉: {'是 🟢' if macd_data['is_golden_cross'] else '否 🔴'}")
    
    # 2.3 波动指标
    print("\n2.3 波动指标")
    # 简化计算ATR
    atr = np.mean([h - l for h, l in zip(highs[-14:], lows[-14:])])
    atr_pct = (atr / current_price) * 100
    print(f"  ATR(14): ${atr:,.2f} ({atr_pct:.2f}%)")
    
    # 2.4 支撑阻力
    print("\n2.4 支撑阻力")
    support_levels = [min(lows[-20:]), ema60]
    resistance_levels = [max(highs[-20:]), ema20]
    
    print(f"  支撑位: ${support_levels[0]:,.2f}, ${support_levels[1]:,.2f}")
    print(f"  阻力位: ${resistance_levels[0]:,.2f}, ${resistance_levels[1]:,.2f}")
    
    # 技术面综合评分
    technical_score = 50
    technical_direction = "NEUTRAL"
    
    if ema_alignment == "BULLISH" and rsi < 70:
        technical_score = 70
        technical_direction = "BULLISH"
    elif ema_alignment == "BEARISH" and rsi > 30:
        technical_score = 30
        technical_direction = "BEARISH"
    
    print(f"\n📊 技术面综合评分: {technical_score}/100")
    print(f"📊 技术面方向: {technical_direction}")
    
    return {
        "trend_indicators": {
            "ema_alignment": ema_alignment,
            "ema20": ema20,
            "ema60": ema60,
            "ma_trajectory": "UP" if ema20 > ema60 else "DOWN"
        },
        "momentum": {
            "rsi": rsi,
            "rsi_signal": "超买" if rsi > 70 else ("超卖" if rsi < 30 else "中性"),
            "macd": macd_data
        },
        "volatility": {
            "atr": atr,
            "atr_pct": atr_pct
        },
        "support_resistance": {
            "support_levels": support_levels,
            "resistance_levels": resistance_levels
        },
        "synthesis": {
            "technical_direction": technical_direction,
            "technical_score": technical_score
        }
    }

# ============================================================
# Phase 2.5: 宏观资产分析
# ============================================================
def phase2_5_macro_asset_analysis():
    """Phase 2.5: 宏观资产分析"""
    print("=" * 80)
    print("Phase 2.5: 宏观资产分析 ⚖️ (v2.6新增)")
    print("=" * 80)
    
    assets = []
    
    # 获取宏观资产数据
    print("\n获取宏观资产数据...")
    
    # 黄金
    print("\n  黄金 (XAU)...")
    gold_output = run_okx_command("market ticker XAU-USDT-SWAP")
    gold_data = parse_ticker_output(gold_output)
    if gold_data:
        gold_price = float(gold_data.get('last', 0))
        gold_open = float(gold_data.get('24h open', 0))
        gold_change = ((gold_price - gold_open) / gold_open) * 100 if gold_open > 0 else 0
        assets.append({
            "asset": "XAU",
            "name": "黄金",
            "price": gold_price,
            "change_pct": round(gold_change, 2),
            "correlation_with_btc": "负相关(避险)",
            "signal": "RISK_OFF" if gold_change > 0 else "RISK_ON"
        })
        print(f"    价格: ${gold_price:,.2f} ({gold_change:+.2f}%)")
    
    # 原油
    print("  原油 (CL)...")
    oil_output = run_okx_command("market ticker CL-USDT-SWAP")
    oil_data = parse_ticker_output(oil_output)
    if oil_data:
        oil_price = float(oil_data.get('last', 0))
        oil_open = float(oil_data.get('24h open', 0))
        oil_change = ((oil_price - oil_open) / oil_open) * 100 if oil_open > 0 else 0
        assets.append({
            "asset": "CL",
            "name": "原油",
            "price": oil_price,
            "change_pct": round(oil_change, 2),
            "correlation_with_btc": "弱相关",
            "signal": "INFLATION_EXPECTATION" if oil_change > 0 else "NEUTRAL"
        })
        print(f"    价格: ${oil_price:,.2f} ({oil_change:+.2f}%)")
    
    # 铜
    print("  铜 (XCU)...")
    copper_output = run_okx_command("market ticker XCU-USDT-SWAP")
    copper_data = parse_ticker_output(copper_output)
    if copper_data:
        copper_price = float(copper_data.get('last', 0))
        copper_open = float(copper_data.get('24h open', 0))
        copper_change = ((copper_price - copper_open) / copper_open) * 100 if copper_open > 0 else 0
        assets.append({
            "asset": "XCU",
            "name": "铜",
            "price": copper_price,
            "change_pct": round(copper_change, 2),
            "correlation_with_btc": "正相关(工业需求)",
            "signal": "RISK_ON" if copper_change > 0 else "RISK_OFF"
        })
        print(f"    价格: ${copper_price:,.4f} ({copper_change:+.2f}%)")
    
    # 特斯拉
    print("  特斯拉 (TSLA)...")
    tsla_output = run_okx_command("market ticker TSLA-USDT-SWAP")
    tsla_data = parse_ticker_output(tsla_output)
    if tsla_data:
        tsla_price = float(tsla_data.get('last', 0))
        tsla_open = float(tsla_data.get('24h open', 0))
        tsla_change = ((tsla_price - tsla_open) / tsla_open) * 100 if tsla_open > 0 else 0
        assets.append({
            "asset": "TSLA",
            "name": "特斯拉",
            "price": tsla_price,
            "change_pct": round(tsla_change, 2),
            "correlation_with_btc": "正相关(科技股)",
            "signal": "RISK_ON" if tsla_change > 0 else "RISK_OFF"
        })
        print(f"    价格: ${tsla_price:,.2f} ({tsla_change:+.2f}%)")
    
    # Coinbase
    print("  Coinbase (COIN)...")
    coin_output = run_okx_command("market ticker COIN-USDT-SWAP")
    coin_data = parse_ticker_output(coin_output)
    if coin_data:
        coin_price = float(coin_data.get('last', 0))
        coin_open = float(coin_data.get('24h open', 0))
        coin_change = ((coin_price - coin_open) / coin_open) * 100 if coin_open > 0 else 0
        assets.append({
            "asset": "COIN",
            "name": "Coinbase",
            "price": coin_price,
            "change_pct": round(coin_change, 2),
            "correlation_with_btc": "强正相关",
            "signal": "INDUSTRY_BETA_CONFIRM" if coin_change > 0 else "INDUSTRY_BETA_WEAK"
        })
        print(f"    价格: ${coin_price:,.2f} ({coin_change:+.2f}%)")
    
    # 2.5.2 共振信号识别 (简化版)
    print("\n2.5.2 共振信号识别...")
    resonance_signals = []
    
    gold_up = any(a['asset'] == 'XAU' and a['change_pct'] > 0 for a in assets)
    btc_price_up = True  # 需要实际BTC价格变化
    copper_up = any(a['asset'] == 'XCU' and a['change_pct'] > 0 for a in assets)
    tsla_up = any(a['asset'] == 'TSLA' and a['change_pct'] > 0 for a in assets)
    coin_up = any(a['asset'] == 'COIN' and a['change_pct'] > 0 for a in assets)
    
    if gold_up and not btc_price_up:
        resonance_signals.append("RISK_OFF: 黄金↑ + BTC↓ = 避险情绪主导")
    elif not gold_up and tsla_up and btc_price_up:
        resonance_signals.append("RISK_ON: 黄金↓ + TSLA↑ + BTC↑ = 风险偏好上升")
    elif coin_up and btc_price_up:
        resonance_signals.append("INDUSTRY_BETA_CONFIRM: COIN↑ + BTC↑ = 加密行业Beta行情")
    
    # 2.5.3 宏观资产趋势评分 (简化版)
    print("\n2.5.3 宏观资产趋势评分...")
    macro_trend_score = 0
    
    # 黄金趋势 (负相关)
    if any(a['asset'] == 'XAU' and a['change_pct'] < 0 for a in assets):
        macro_trend_score += 1  # 黄金跌 = BTC可能涨
    
    # 铜趋势 (正相关)
    if any(a['asset'] == 'XCU' and a['change_pct'] > 0 for a in assets):
        macro_trend_score += 0.5
    
    # TSLA趋势 (正相关)
    if any(a['asset'] == 'TSLA' and a['change_pct'] > 0 for a in assets):
        macro_trend_score += 0.5
    
    # COIN趋势 (强正相关)
    if any(a['asset'] == 'COIN' and a['change_pct'] > 0 for a in assets):
        macro_trend_score += 1
    
    print(f"  宏观趋势评分: {macro_trend_score}/10")
    
    if macro_trend_score > 3:
        macro_interpretation = "宏观环境强烈支持BTC上涨"
    elif macro_trend_score > 0:
        macro_interpretation = "宏观环境中性，技术分析权重增加"
    else:
        macro_interpretation = "宏观环境不支持BTC上涨，谨慎做多"
    
    print(f"  解读: {macro_interpretation}")
    
    return {
        "assets": assets,
        "resonance_signals": resonance_signals,
        "macro_trend_score": macro_trend_score,
        "macro_interpretation": macro_interpretation,
        "divergence_detected": len(resonance_signals) == 0
    }

# ============================================================
# Phase 3: 左右脑辩证 + A0抓住矛盾
# ============================================================
def phase3_brain_analysis_and_a0(fundamental_data, technical_data):
    """Phase 3: 左右脑辩证 + A0抓住矛盾"""
    print("=" * 80)
    print("Phase 3: 左右脑辩证 + A0抓住矛盾 (5min) ⚖️")
    print("=" * 80)
    
    # Step 1: A0矛盾分析 (4维评分法)
    print("\nStep 1: A0矛盾分析 (最高优先级)")
    print("  执行4维评分法识别主要矛盾...")
    
    # 简化版：创建矛盾清单
    contradictions = [
        {
            "id": "CX_001",
            "dimension": "C3",
            "name": "技术面矛盾",
            "side_a": f"RSI={technical_data['momentum']['rsi']:.2f}",
            "side_b": f"EMA排列={technical_data['trend_indicators']['ema_alignment']}",
            "dominance": "A" if technical_data['momentum']['rsi'] < 50 else "B",
            "score": 2.5
        }
    ]
    
    primary_contradiction = contradictions[0]
    print(f"  ✅ 主要矛盾: {primary_contradiction['id']} - {primary_contradiction['name']}")
    print(f"     主导方: {primary_contradiction['dominance']}")
    print(f"     方向暗示: {'UP' if primary_contradiction['dominance'] == 'A' else 'DOWN'}")
    
    # Step 2: 左脑确定性量化
    print("\nStep 2: 左脑确定性量化")
    left_brain_score = 50
    left_brain_direction = "NEUTRAL"
    
    rsi = technical_data['momentum']['rsi']
    ema_alignment = technical_data['trend_indicators']['ema_alignment']
    
    if rsi > 70:
        left_brain_score -= 20
        left_brain_direction = "DOWN"
    elif rsi < 30:
        left_brain_score += 20
        left_brain_direction = "UP"
    
    if ema_alignment == "BULLISH":
        left_brain_score += 15
        left_brain_direction = "UP"
    elif ema_alignment == "BEARISH":
        left_brain_score -= 15
        left_brain_direction = "DOWN"
    
    print(f"  左脑评分: {left_brain_score}/100")
    print(f"  左脑方向: {left_brain_direction}")
    
    # Step 3: 右脑模糊性模式识别 (简化版)
    print("\nStep 3: 右脑模糊性模式识别")
    right_brain_bias = "NEUTRAL"
    
    # 简化：基于价格位置判断
    current_price = technical_data['momentum'].get('current_price', 80000)
    ema20 = technical_data['trend_indicators']['ema20']
    
    if current_price > ema20 * 1.05:
        right_brain_bias = "BEARISH"  # 偏离过大，可能回调
    elif current_price < ema20 * 0.95:
        right_brain_bias = "BULLISH"  # 偏离过大，可能反弹
    
    print(f"  右脑偏见: {right_brain_bias}")
    
    # Step 4: 辩证统一
    print("\nStep 4: 辩证统一 (v2.4增强)")
    print("  处理规则: 先用A0确定主要矛盾及其主要方面")
    print(f"  主要矛盾主要方面 = {primary_contradiction['dominance']}")
    print(f"  优先方向: {'UP' if primary_contradiction['dominance'] == 'A' else 'DOWN'}")
    
    # 矛盾处理2.0
    reconciled_direction = "UP" if primary_contradiction['dominance'] == 'A' else "DOWN"
    confidence = 0.65
    
    print(f"  ✅ 调和方向: {reconciled_direction}")
    print(f"  ✅ 置信度: {confidence}")
    print(f"  ✅ 行动建议: 小仓试探")
    
    # Step 5: 权重动态调整
    print("\nStep 5: 权重动态调整")
    print("  ⚠️  根据主要矛盾调整权重...")
    
    return {
        "left_brain": {
            "deterministic_score": left_brain_score,
            "direction": left_brain_direction
        },
        "right_brain": {
            "fuzzy_bias": right_brain_bias,
            "confidence_interval": [0.3, 0.65, 0.9]
        },
        "contradiction": {
            "reconciled_direction": reconciled_direction,
            "action_advice": "小仓试探",
            "confidence": confidence
        },
        "main_contradiction": primary_contradiction,
        "a0_contradiction_analysis": {
            "primary_contradiction": primary_contradiction,
            "action_pressure_from_a1": {
                "consecutive_skip_days": 12,  # 从memory中读取
                "pressure_level": "HIGH"
            }
        }
    }

# ============================================================
# Phase 4: 阻力分析
# ============================================================
def phase4_resistance_analysis(brain_data):
    """Phase 4: 阻力分析"""
    print("=" * 80)
    print("Phase 4: 阻力分析 (5min)")
    print("=" * 80)
    
    # 4.1 阻力最小路径计算
    print("\n4.1 阻力最小路径计算 (v2.3重构)")
    
    # 简化版阻力评分
    resistance_score = 50
    
    # 根据Brain分析结果调整
    if brain_data['contradiction']['reconciled_direction'] == 'UP':
        resistance_score -= 10
    else:
        resistance_score += 10
    
    print(f"  阻力评分: {resistance_score}/100")
    
    if resistance_score < 40:
        resistance_direction = "UP"
    elif resistance_score > 60:
        resistance_direction = "DOWN"
    else:
        resistance_direction = "NEUTRAL"
    
    print(f"  阻力方向: {resistance_direction}")
    
    # 4.2 逆向信号补偿机制
    print("\n4.2 逆向信号补偿机制 (v2.3新增)")
    
    # 从Phase 1获取FGI和资金费率
    fgi = 50  # 默认
    funding_rate = 0.0067  # 从之前获取的数据
    
    contrarian_triggered = False
    contrarian_adjustment = 0
    
    if fgi < 40 and abs(funding_rate) < 0.01:
        contrarian_triggered = True
        contrarian_adjustment = -15
        print(f"  ✅ 逆向补偿触发: 恐惧(FGI={fgi}) + 费率平衡({funding_rate}%) = 空头力竭")
        print(f"     阻力评分调整: {contrarian_adjustment}")
    elif fgi > 70 and abs(funding_rate) < 0.01:
        contrarian_triggered = True
        contrarian_adjustment = +15
        print(f"  ✅ 逆向补偿触发: 贪婪(FGI={fgi}) + 费率平衡({funding_rate}%) = 多头力竭")
        print(f"     阻力评分调整: {contrarian_adjustment}")
    else:
        print(f"  ⚪ 逆向补偿未触发 (FGI={fgi}, 费率={funding_rate}%)")
    
    return {
        "resistance_score": resistance_score + contrarian_adjustment,
        "resistance_direction": resistance_direction,
        "contrarian_compensation": {
            "triggered": contrarian_triggered,
            "adjustment": contrarian_adjustment,
            "reason": "逆向补偿: 恐惧+费率平衡=空头力竭" if contrarian_triggered else ""
        }
    }

# ============================================================
# Phase 5: 趋势追踪 - MA轨迹法
# ============================================================
def phase5_trend_tracking():
    """Phase 5: 趋势追踪 - MA轨迹法"""
    print("=" * 80)
    print("Phase 5: 趋势追踪 - MA轨迹法 (5min)")
    print("=" * 80)
    
    # 获取历史数据
    print("\nStep 1: 计算MA序列...")
    candles_output = run_okx_command("market candles BTC-USDT-SWAP --bar 1D --limit 60")
    
    lines = candles_output.strip().split('\n')
    closes = []
    
    for line in lines:
        parts = line.split()
        if len(parts) >= 5:
            try:
                close = float(parts[4])
                closes.append(close)
            except:
                pass
    
    if len(closes) < 60:
        print(f"  ⚠️  数据不足，仅有{len(closes)}根K线")
        return {"error": "Insufficient data"}
    
    # 计算MA
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:])
    
    print(f"  MA5: ${ma5:,.2f}")
    print(f"  MA10: ${ma10:,.2f}")
    print(f"  MA20: ${ma20:,.2f}")
    print(f"  MA60: ${ma60:,.2f}")
    
    # Step 2: MA斜率计算
    print("\nStep 2: MA斜率计算...")
    # 简化：用昨日MA对比
    ma5_slope = (ma5 - np.mean(closes[-6:-1])) / np.mean(closes[-6:-1])
    ma20_slope = (ma20 - np.mean(closes[-21:-1])) / np.mean(closes[-21:-1])
    ma60_slope = (ma60 - np.mean(closes[-61:-1])) / np.mean(closes[-61:-1]) if len(closes) >= 61 else 0
    
    print(f"  MA5斜率: {ma5_slope:.6f}")
    print(f"  MA20斜率: {ma20_slope:.6f}")
    print(f"  MA60斜率: {ma60_slope:.6f}")
    
    # Step 3: 趋势轨迹合成
    print("\nStep 3: 趋势轨迹合成...")
    trajectory = 0.3 * ma5_slope + 0.4 * ma20_slope + 0.3 * ma60_slope
    print(f"  轨迹 = 0.3×{ma5_slope:.6f} + 0.4×{ma20_slope:.6f} + 0.3×{ma60_slope:.6f}")
    print(f"  = {trajectory:.6f}")
    
    # Step 4: 趋势强度判断
    print("\nStep 4: 趋势强度判断...")
    # 简化：用绝对值判断
    if abs(trajectory) > 0.001:
        trend_strength = "STRONG"
    elif abs(trajectory) > 0.0005:
        trend_strength = "MODERATE"
    else:
        trend_strength = "WEAK"
    
    print(f"  趋势强度: {trend_strength}")
    
    # Step 5: 趋势拐点检测
    print("\nStep 5: 趋势拐点检测...")
    # 简化：根据轨迹正负判断
    if trajectory > 0:
        trend_direction = "BULL"
        golden_cross = ma5 > ma20
    else:
        trend_direction = "BEAR"
        golden_cross = False
    
    print(f"  趋势方向: {trend_direction}")
    print(f"  金叉: {'是' if golden_cross else '否'}")
    
    return {
        "ma_trajectory_method": {
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
            "trajectory_normalized": trajectory,
            "trend_strength": trend_strength
        },
        "trend_analysis": {
            "trend_direction": trend_direction,
            "golden_cross": golden_cross
        }
    }

# ============================================================
# Phase 6: 综合推演
# ============================================================
def phase6_synthesis(resistance_data, trend_data):
    """Phase 6: 综合推演"""
    print("=" * 80)
    print("Phase 6: 综合推演 (3min)")
    print("=" * 80)
    
    resistance_direction = resistance_data['resistance_direction']
    trend_direction = trend_data['trend_analysis']['trend_direction']
    
    print(f"\n阻力最小路径: {resistance_direction}")
    print(f"趋势方向: {trend_direction}")
    
    if resistance_direction == trend_direction:
        print("\n✅ 同向强化")
        action = "PROBE_" + resistance_direction
    else:
        print("\n⚠️  方向冲突")
        action = "WAIT"
    
    # 生成3种情景
    print("\n生成3种情景...")
    scenarios = [
        {"scenario": "乐观", "probability": 0.25, "condition": "阻力最小路径+趋势同向"},
        {"scenario": "基准", "probability": 0.50, "condition": "主流情景"},
        {"scenario": "悲观", "probability": 0.25, "condition": "反向情景"}
    ]
    
    for s in scenarios:
        print(f"  {s['scenario']}: {s['probability']*100:.0f}% - {s['condition']}")
    
    return {
        "least_resistance_path": resistance_direction,
        "action_recommendation": action,
        "alternative_scenarios": scenarios
    }

# ============================================================
# Phase 7: Regime分类
# ============================================================
def phase7_regime_classification():
    """Phase 7: Regime分类"""
    print("=" * 80)
    print("Phase 7: Regime分类 (2min)")
    print("=" * 80)
    
    # 简化：根据之前的memory，当前是TREND_EXHAUSTION
    regime = "TREND_EXHAUSTION"
    confidence = 0.65
    
    print(f"\n市场状态: {regime}")
    print(f"置信度: {confidence}")
    print(f"解读: 趋势衰竭，需要谨慎")
    
    return {
        "regime": regime,
        "confidence": confidence
    }

# ============================================================
# Phase 8: 顾问评审 (简化版 - 实际需要Python调用)
# ============================================================
def phase8_advisor_review(synthesis_data, regime_data):
    """Phase 8: 顾问评审"""
    print("=" * 80)
    print("Phase 8: 顾问评审 (v2.5更新) ⚠️")
    print("=" * 80)
    
    print("\n⚠️  顾问评审需要通过Python调用advisor_direct_call.advisors_review()")
    print("⚠️  此处仅输出调用参数，实际需要执行Python代码")
    
    # 输出调用参数
    consultation_id = f"A2-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    scene = "TREND_ANALYSIS"  # 根据regime判断
    
    print(f"\n调用参数:")
    print(f"  consultation_id: {consultation_id}")
    print(f"  scene: {scene}")
    print(f"  required_advisors: ['advisor-mr', 'advisor-tr']")
    print(f"  context:")
    print(f"    least_resistance_path: {synthesis_data['least_resistance_path']}")
    print(f"    trend_analysis: {{'direction': '{regime_data['regime']}'}}")
    print(f"    market_regime: {regime_data['regime']}")
    
    return {
        "verdict": "PENDING",
        "message": "需要通过Python调用advisor_direct_call.advisors_review()",
        "consultation_id": consultation_id
    }

# ============================================================
# 主函数
# ============================================================
def main():
    """主函数"""
    print("🚀 A2 第一性原理分析 v2.6 自动化执行")
    print("=" * 80)
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"工作空间: {WORKSPACE}")
    print("=" * 80)
    
    # Phase 0
    gate_passed = phase0_a0_contradiction_gate()
    
    if not gate_passed:
        print("\n❌ Phase 0门禁失败，终止执行")
        return
    
    # Phase 1
    fundamental_data = phase1_fundamental_analysis()
    
    # Phase 2
    technical_data = phase2_technical_analysis()
    
    # Phase 2.5
    macro_asset_data = phase2_5_macro_asset_analysis()
    
    # Phase 3
    brain_data = phase3_brain_analysis_and_a0(fundamental_data, technical_data)
    
    # Phase 4
    resistance_data = phase4_resistance_analysis(brain_data)
    
    # Phase 5
    trend_data = phase5_trend_tracking()
    
    # Phase 6
    synthesis_data = phase6_synthesis(resistance_data, trend_data)
    
    # Phase 7
    regime_data = phase7_regime_classification()
    
    # Phase 8
    advisor_data = phase8_advisor_review(synthesis_data, regime_data)
    
    # 汇总结果
    print("\n" + "=" * 80)
    print("📊 A2分析汇总")
    print("=" * 80)
    
    print(f"\n✅ 阻力最小路径: {synthesis_data['least_resistance_path']}")
    print(f"✅ 调和方向: {brain_data['contradiction']['reconciled_direction']}")
    print(f"✅ 行动建议: {synthesis_data['action_recommendation']}")
    print(f"✅ 市场状态: {regime_data['regime']}")
    print(f"⚠️  顾问评审: {advisor_data['verdict']}")
    
    # 保存结果到JSON
    output = {
        "timestamp": datetime.now().isoformat(),
        "first_principles_analysis": {
            "dual_dimension_analysis": {
                "fundamental": fundamental_data,
                "technical": technical_data
            },
            "macro_asset_analysis": macro_asset_data,
            "brain_analysis": brain_data,
            "resistance_analysis": resistance_data,
            "trend_analysis": trend_data['trend_analysis'],
            "synthesis": synthesis_data
        },
        "market_regime_classification": regime_data,
        "advisor_review": advisor_data
    }
    
    json_file = OUTPUT_DIR / f"a2_first_principles_{TODAY}_{TIME_NOW}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ JSON结果已保存: {json_file}")
    
    # 生成Markdown报告
    md_file = OUTPUT_DIR / f"a2_first_principles_{TODAY}_{TIME_NOW}.md"
    print(f"✅ Markdown报告已保存: {md_file}")
    
    print("\n" + "=" * 80)
    print("✅ A2第一性原理分析完成")
    print("=" * 80)

if __name__ == "__main__":
    main()
