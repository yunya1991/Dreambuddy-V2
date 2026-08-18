"""
F2 资金流分析节点
调用基本面分析系统获取资金流数据
遵循"调用的不重复建设"原则

API 路径: 10-经典指标系统/ml_trade_service.py
- /fundamental/flows/brief/latest - 资金流简报
- /fundamental/flows/regime/latest - 资金流Regime

模块路径: core.modules.fundamental_api
"""

from typing import Dict, Any
from pathlib import Path

try:
    from core.modules.fundamental_api import FundamentalAPIClient
    _FUND_OK = True
except ImportError:
    _FUND_OK = False
    FundamentalAPIClient = None


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 F2 资金流分析
    
    优先调用基本面分析系统 API，失败时使用本地降级
    
    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据
    
    Returns:
        {
            "node": "F2_资金流",
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "data": {...资金流详情...},
            "source": "fundamental_api" | "local_fallback"
        }
    """
    reasoning = []
    coin = mkt.get("coin", "BTC")
    funding = mkt.get("funding_rate", 0)
    
    # ── 调用基本面 API ─────────────────────────────────────────────
    source = "local_fallback"
    fund_data = None
    
    if _FUND_OK:
        try:
            client = FundamentalAPIClient()
            if client.is_available():
                fund_data = client.get_fund_flows(coin)
                source = "fundamental_api"
                reasoning.append(f"[F2资金流] 数据源: 基本面分析系统 API")
            else:
                reasoning.append(f"[F2资金流] 数据源: 本地代理（基本面系统不可用）")
        except Exception as e:
            reasoning.append(f"[F2资金流] 数据源: 本地代理（{str(e)[:30]}）")
    else:
        reasoning.append(f"[F2资金流] 数据源: 本地代理（模块未加载）")
    
    # ── 资金费率分析 ───────────────────────────────────────────────
    # 正费率 = 多头付费 = 多头拥挤 = 偏空信号
    # 负费率 = 空头付费 = 空头拥挤 = 偏多信号
    funding_bps = funding * 10000  # 转换为bps
    
    if funding < -0.0005:  # -5bps以下
        direction = "LONG"
        confidence = 0.60
        reasoning.append(f"  ✅ 资金费率 {funding_bps:.2f}bps，空头拥挤，偏多")
    elif funding > 0.0005:  # +5bps以上
        direction = "SHORT"
        confidence = 0.60
        reasoning.append(f"  🔴 资金费率 {funding_bps:.2f}bps，多头拥挤，偏空")
    elif funding < 0:
        direction = "LONG"
        confidence = 0.52
        reasoning.append(f"  ➡️  资金费率 {funding_bps:.2f}bps，轻微偏多")
    elif funding > 0:
        direction = "SHORT"
        confidence = 0.52
        reasoning.append(f"  ➡️  资金费率 {funding_bps:.2f}bps，轻微偏空")
    else:
        direction = "HOLD"
        confidence = 0.45
        reasoning.append(f"  ⚖️  资金费率中性，无明确方向")
    
    # ── OI 变化（如有 API 数据） ──────────────────────────────────
    if fund_data and fund_data.oi_change != 0:
        oi_chg = fund_data.oi_change
        if oi_chg > 0.05:
            reasoning.append(f"  📈 OI变化: +{oi_chg*100:.1f}%，资金流入")
        elif oi_chg < -0.05:
            reasoning.append(f"  📉 OI变化: {oi_chg*100:.1f}%，资金流出")
    
    # ── ETF 资金流（如有 API 数据） ──────────────────────────────
    if fund_data and fund_data.etf_flow != 0:
        reasoning.append(f"  💵 ETF资金流: {fund_data.etf_flow:+.2f}M")
    
    # 使用 API 数据修正置信度
    if fund_data and fund_data.strength > 0:
        confidence = max(confidence, fund_data.strength)
        if fund_data.direction != "NEUTRAL":
            direction = "LONG" if fund_data.direction in ("INFLOW", "BULL") else "SHORT"
    
    return {
        "node": "F2_资金流",
        "direction": direction,
        "confidence": round(confidence, 3),
        "rationale": reasoning,
        "source": source,
        "data": {
            "coin": coin,
            "funding_rate": funding,
            "funding_bps": round(funding_bps, 4),
            "source": source,
            "api_data": {
                "direction": fund_data.direction if fund_data else None,
                "etf_flow": fund_data.etf_flow if fund_data else None,
                "oi_change": fund_data.oi_change if fund_data else None,
                "strength": fund_data.strength if fund_data else None,
            } if fund_data else None,
        }
    }


def f2_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
