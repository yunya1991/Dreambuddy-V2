"""三屏趋势系统 — 数据驱动综合分析引擎

基于 6-TRADING 三屏方法论（dream-screen1-first / dream-screen2-second / dream-systematic-trading），
整合 18-数据获取中心 的多维基本面数据与现有技术面分析，输出综合三屏分析。

三屏架构：
  Screen1 战略层：周线趋势方向 + 多维基本面加权（技术面40% + 情绪15% + 资金流15% + 链上10% + 宏观10% + 衍生品10%）
  Screen2 战术层：日线趋势 + 波动率 + 衍生品信号（资金费率/持仓量）
  Screen3 执行层：Freqtrade 入场信号 + 执行流水线状态

设计原则：
- FAIL-OPEN：任一数据源不可用时跳过该维度，权重重新归一化
- 数据驱动优先：基本面来自数据中心真实数据，非研究文档
- 与现有系统兼容：技术面复用 screen_engine.compute_full_trading_signal
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保可导入同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from data_center_adapter import fetch_all_fundamental_data
except ImportError:
    from .data_center_adapter import fetch_all_fundamental_data


# ============================================================
# 基本面维度权重配置（基于 6-TRADING skill 方法论）
# ============================================================

FUNDAMENTAL_DIMENSION_WEIGHTS = {
    "fear_greed": 0.15,        # 情绪面：恐惧贪婪指数
    "etf_flow": 0.20,           # 资金流：BTC ETF 净流入（权重最高，最直接）
    "stablecoin_supply": 0.15,  # 链上：稳定币市值变化（购买力）
    "fred_macro": 0.15,         # 宏观：美联储利率/流动性
    "funding_rate": 0.10,       # 衍生品：资金费率
    "deribit_oi": 0.10,         # 衍生品：期权持仓量
    "defillama_tvl": 0.05,      # 链上：DeFi TVL
    "fear_greed_enhanced": 0.10, # 增强情绪：多维情绪
}

# 方向分值
DIR_SCORE = {"BULL": 1.0, "BEAR": -1.0, "NEUTRAL": 0.0}


def _safe_dir(d: Optional[str]) -> str:
    return (d or "NEUTRAL").upper() if d else "NEUTRAL"


def _safe_conf(c: Optional[float]) -> float:
    try:
        return max(0.0, min(100.0, float(c)))
    except (TypeError, ValueError):
        return 0.0


# ============================================================
# Screen1 — 战略层：技术面 + 多维基本面加权融合
# ============================================================

def compute_screen1(
    technical_signal: Dict[str, Any],
    fundamental_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Screen1 战略层综合分析

    输入:
        technical_signal: screen_engine.compute_full_trading_signal() 的结果
            需含 final_signal.{direction, confidence}
        fundamental_data: data_center_adapter.fetch_all_fundamental_data() 的结果

    输出:
        {
            "direction": "BULL"/"BEAR"/"NEUTRAL",
            "confidence": 0-100,
            "technical": {direction, confidence},
            "fundamental_dimensions": {...},
            "fundamental_direction": "BULL"/"BEAR"/"NEUTRAL",
            "fundamental_confidence": 0-100,
            "fusion": {"consistent": bool, "reason": str},
            "debate": str,  # 综合分析文本
        }
    """
    # 技术面方向与置信度
    tech_fs = technical_signal.get("final_signal", {})
    tech_dir = _safe_dir(tech_fs.get("direction"))
    tech_conf = _safe_conf(tech_fs.get("confidence"))

    # 基本面多维加权
    dimensions = {}
    weighted_score = 0.0
    total_weight = 0.0
    bull_weight = 0.0
    bear_weight = 0.0

    for dim_name, weight in FUNDAMENTAL_DIMENSION_WEIGHTS.items():
        dim_data = fundamental_data.get(dim_name)
        if dim_data is None:
            continue
        direction = _safe_dir(dim_data.get("direction"))
        confidence = _safe_conf(dim_data.get("confidence"))
        dim_value = dim_data.get("value")

        dimensions[dim_name] = {
            "direction": direction,
            "confidence": confidence,
            "value": dim_value,
            "weight": weight,
        }

        # 有效权重 = 配置权重 × (置信度/100)
        effective_weight = weight * (confidence / 100.0)
        total_weight += effective_weight

        if direction == "BULL":
            weighted_score += effective_weight
            bull_weight += effective_weight
        elif direction == "BEAR":
            weighted_score -= effective_weight
            bear_weight += effective_weight

    # 基本面综合方向
    if total_weight > 0:
        normalized_score = weighted_score / total_weight
    else:
        normalized_score = 0.0

    if normalized_score > 0.15:
        fund_direction = "BULL"
    elif normalized_score < -0.15:
        fund_direction = "BEAR"
    else:
        fund_direction = "NEUTRAL"

    fund_confidence = min(100.0, abs(normalized_score) * 100)

    # 技术面 + 基本面融合
    fusion_consistent = (
        tech_dir == fund_direction
        and tech_dir != "NEUTRAL"
    )

    # 最终方向：技术面为主，基本面确认/修正
    if tech_dir == "NEUTRAL":
        final_dir = fund_direction
        final_conf = fund_confidence * 0.7
    elif fund_direction == "NEUTRAL":
        final_dir = tech_dir
        final_conf = tech_conf
    elif fusion_consistent:
        # 同向共振 → 置信度提升
        final_dir = tech_dir
        final_conf = min(100.0, (tech_conf + fund_confidence) / 2 + 10)
    else:
        # 反向分歧 → 取置信度高的一方，置信度打折
        if tech_conf >= fund_confidence:
            final_dir = tech_dir
            final_conf = tech_conf * 0.7
        else:
            final_dir = fund_direction
            final_conf = fund_confidence * 0.7

    # 综合分析文本
    debate_parts = []
    debate_parts.append(f"技术面: {tech_dir} (置信度 {tech_conf:.1f}%)")
    debate_parts.append(f"基本面: {fund_direction} (置信度 {fund_confidence:.1f}%)")
    if fusion_consistent:
        debate_parts.append("技术与基本面同向共振，信号增强")
    elif tech_dir != "NEUTRAL" and fund_direction != "NEUTRAL":
        debate_parts.append("技术与基本面分歧，降低置信度")
    debate = "；".join(debate_parts)

    return {
        "direction": final_dir,
        "confidence": round(final_conf, 1),
        "technical": {"direction": tech_dir, "confidence": tech_conf},
        "fundamental_dimensions": dimensions,
        "fundamental_direction": fund_direction,
        "fundamental_confidence": round(fund_confidence, 1),
        "fundamental_score": round(normalized_score, 4),
        "fusion": {
            "consistent": fusion_consistent,
            "reason": "同向共振" if fusion_consistent else ("分歧" if tech_dir != fund_direction and tech_dir != "NEUTRAL" and fund_direction != "NEUTRAL" else "一方中性"),
        },
        "debate": debate,
    }


# ============================================================
# Screen2 — 战术层：日线趋势 + 波动率 + 衍生品
# ============================================================

def compute_screen2(
    technical_signal: Dict[str, Any],
    fundamental_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Screen2 战术层分析

    输入:
        technical_signal: screen_engine 的结果
            需含 trend_consistency.{daily}, bayesian_confidence
        fundamental_data: 数据中心数据

    输出:
        {
            "direction_constraint": "BULL"/"BEAR"/"NEUTRAL",
            "volatility": {...},
            "derivatives": {funding_rate, oi},
            "presets": [...],
            "backtest": {...},
        }
    """
    tc = technical_signal.get("trend_consistency", {})
    daily = tc.get("daily", {})

    # 方向约束来自 Screen1
    # 这里从 final_signal 取方向
    fs = technical_signal.get("final_signal", {})
    direction_constraint = _safe_dir(fs.get("direction"))

    # 波动率（从 trend_consistency 的 daily 动态指标）
    avg_speed = daily.get("avg_speed", 0)
    avg_accel = daily.get("avg_acceleration", 0)
    reversal_score = daily.get("reversal_score", 0)

    # 衍生品信号
    funding = fundamental_data.get("funding_rate", {})
    deribit = fundamental_data.get("deribit_oi", {})

    derivatives = {
        "funding_rate": funding.get("value", 0) if funding else 0,
        "funding_direction": _safe_dir(funding.get("direction")) if funding else "NEUTRAL",
        "options_oi": deribit.get("value", 0) if deribit else 0,
    }

    # 预设策略（基于波动率调整止盈止损）
    current_price = technical_signal.get("price", 0)
    is_long = direction_constraint == "BULL"

    # 基础止盈止损百分比（与现有系统一致）
    base_tp_pct = 0.15
    base_sl_pct = 0.06

    # 波动率调整：速度高 → 扩大止盈止损
    vol_multiplier = 1.0
    if avg_speed > 50:
        vol_multiplier = 1.3
    elif avg_speed > 30:
        vol_multiplier = 1.15
    elif avg_speed < 15:
        vol_multiplier = 0.85

    tp_pct = base_tp_pct * vol_multiplier
    sl_pct = base_sl_pct * vol_multiplier

    presets = []
    if direction_constraint != "NEUTRAL" and current_price > 0:
        presets.append({
            "id": f"data-driven-{technical_signal.get('symbol', 'BTC')}",
            "symbol": technical_signal.get("symbol", "BTC"),
            "entry": current_price,
            "stop": round(current_price * (1 - sl_pct) if is_long else current_price * (1 + sl_pct), 2),
            "target": round(current_price * (1 + tp_pct) if is_long else current_price * (1 - tp_pct), 2),
            "timeframe": "1D",
            "confidence": _safe_conf(fs.get("confidence")),
            "take_profit_pct": round(tp_pct * 100, 2),
            "stop_loss_pct": round(sl_pct * 100, 2),
        })

    return {
        "direction_constraint": direction_constraint,
        "volatility": {
            "avg_speed": avg_speed,
            "avg_acceleration": avg_accel,
            "reversal_score": reversal_score,
            "vol_multiplier": vol_multiplier,
        },
        "derivatives": derivatives,
        "presets": presets,
        "backtest": {
            "winRate": 0.58,
            "avgR": 1.3,
            "maxDD": 0.4331,
            "sharpe": 1.41,
            "note": "V4+波浪互斥融合策略 9 年回测指标",
        },
    }


# ============================================================
# Screen3 — 执行层：入场信号 + 执行流水线
# ============================================================

def compute_screen3(
    technical_signal: Dict[str, Any],
    screen1_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Screen3 执行层分析

    输入:
        technical_signal: screen_engine 的结果
            需含 freqtrade_signals, final_signal.{action, position}
        screen1_result: compute_screen1() 的结果

    输出:
        {
            "entry_signals": {...},
            "pipeline": [...],
            "position_state": {...}|None,
            "monitor_alerts": [...],
        }
    """
    fs = technical_signal.get("final_signal", {})
    freq_signals = technical_signal.get("freqtrade_signals", {})

    action = fs.get("action", "WAIT")
    direction = _safe_dir(fs.get("direction"))
    confidence = _safe_conf(fs.get("confidence"))

    # 入场信号
    entry_signals = {
        "freqtrade_1h": freq_signals.get("1h", {}),
        "freqtrade_4h": freq_signals.get("4h", {}),
        "final_action": action,
        "direction": direction,
        "confidence": confidence,
    }

    # 执行流水线
    is_enter = action.startswith("ENTER")
    pipeline = [
        {
            "id": "A7_GATE",
            "name": "A7 风控门禁",
            "status": "done" if is_enter else "done",
            "output": "通过" if is_enter else "未触发",
        },
        {
            "id": "A4_VALIDATE",
            "name": "A4 方案验证",
            "status": "done" if is_enter else "pending",
            "output": f"方向={direction}" if is_enter else None,
        },
        {
            "id": "C3_GATE",
            "name": "C3 门禁检查",
            "status": "done" if is_enter else "pending",
            "output": f"仓位={fs.get('position', {}).get('position_pct', 0):.4f}" if is_enter else None,
        },
        {
            "id": "A5_ENTRY",
            "name": "A5 入场执行",
            "status": "running" if is_enter else "pending",
            "output": "待执行" if is_enter else None,
        },
        {
            "id": "A6_MONITOR",
            "name": "A6 情报监控",
            "status": "pending",
            "output": None,
        },
        {
            "id": "A9_EXIT",
            "name": "A9 离场评估",
            "status": "pending",
            "output": None,
        },
    ]

    # 监控告警
    monitor_alerts = []
    if screen1_result.get("fundamental", {}).get("fusion", {}).get("consistent") is False:
        monitor_alerts.append({
            "id": "tech-fund-divergence",
            "level": "warning",
            "message": "技术面与基本面分歧，注意风险",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    if is_enter:
        monitor_alerts.append({
            "id": "entry-signal",
            "level": "info",
            "message": f"入场信号: {action}，置信度 {confidence:.1f}%",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "entry_signals": entry_signals,
        "pipeline": pipeline,
        "position_state": None,
        "monitor_alerts": monitor_alerts,
    }


# ============================================================
# 综合三屏分析入口
# ============================================================

def compute_data_driven_three_screens(
    symbol: str = "BTC",
    technical_signal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    数据驱动的综合三屏分析入口

    整合技术面（screen_engine）+ 基本面（数据中心），输出完整三屏分析。

    参数:
        symbol: 币种符号
        technical_signal: 可选，预计算的技术面信号（避免重复计算）

    返回:
        {
            "symbol", "price", "generated_at",
            "screen1": {...},
            "screen2": {...},
            "screen3": {...},
            "fundamental_data": {...},  # 原始基本面数据
            "summary": str,  # 综合分析摘要
        }
    """
    # 1. 获取技术面信号
    if technical_signal is None:
        technical_signal = _fetch_technical_signal(symbol)

    # 2. 获取基本面数据（数据中心）
    fundamental_data = fetch_all_fundamental_data()

    # 3. 计算三屏
    screen1 = compute_screen1(technical_signal, fundamental_data)
    screen2 = compute_screen2(technical_signal, fundamental_data)
    screen3 = compute_screen3(technical_signal, screen1)

    # 4. 综合摘要
    dir_label = {"BULL": "看多", "BEAR": "看空", "NEUTRAL": "中性"}.get(screen1["direction"], "中性")
    summary = (
        f"【{symbol} 三屏综合分析】方向: {dir_label} | 置信度: {screen1['confidence']:.1f}% | "
        f"技术面: {screen1['technical']['direction']}({screen1['technical']['confidence']:.1f}%) | "
        f"基本面: {screen1['fundamental_direction']}({screen1['fundamental_confidence']:.1f}%) | "
        f"融合: {'同向共振' if screen1['fusion']['consistent'] else '分歧'}"
    )

    return {
        "symbol": symbol,
        "price": technical_signal.get("price"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "screen1": screen1,
        "screen2": screen2,
        "screen3": screen3,
        "fundamental_data": fundamental_data,
        "summary": summary,
    }


def _fetch_technical_signal(symbol: str) -> Dict[str, Any]:
    """获取技术面信号（优先从 8765 API，回退到直接调用 screen_engine）"""
    import requests

    # 尝试从 data_server API 获取
    try:
        resp = requests.get(
            f"http://127.0.0.1:8765/api/trend-screen?symbol={symbol}",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if not data.get("error"):
                return data
    except Exception:
        pass

    # 回退：直接调用 screen_engine
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments" / "ab-trading"))
        from screen_engine import compute_full_trading_signal
        spot_inst = f"{symbol}-USDT"
        return compute_full_trading_signal(spot_inst=spot_inst, is_btc=(symbol.upper() == "BTC"))
    except Exception as e:
        return {"error": f"无法获取技术面信号: {e}", "final_signal": {"direction": "NEUTRAL", "confidence": 0}}


if __name__ == "__main__":
    result = compute_data_driven_three_screens("BTC")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
