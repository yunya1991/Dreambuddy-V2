"""
F5 宏观分析节点
获取宏观数据：VIX + 股市 + 美联储指标 + 通胀 + 国债利差

数据源: 18-数据获取中心/data_center.db (fred + yfinance + econ_calendar)
FAIL-OPEN: DataCenterClient 不可用时返回中性

SKILL.md 调用路径: experiments/ab-trading/core/nodes/f5_macro
"""

from typing import Dict, Any

try:
    from core.modules.data_center_adapter import get_data_center_client
    _DC_OK = True
except ImportError:
    _DC_OK = False


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 F5 宏观分析

    优先从数据采集中心获取宏观数据（VIX/SPY/CPI/PPI/FEDFUNDS/M2），
    失败时返回中性。

    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据

    Returns:
        {
            "node": "F5_宏观",
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "data": {...宏观详情...},
            "source": "data_center" | "local_fallback"
        }
    """
    reasoning = []
    coin = mkt.get("coin", "BTC")
    source = "local_fallback"
    macro = None

    if _DC_OK:
        try:
            client = get_data_center_client()
            if client.is_available():
                macro = client.get_macro()
                source = "data_center"
                reasoning.append(f"[F5宏观] 数据源: 数据采集中心")

                # VIX
                if macro.vix is not None:
                    reasoning.append(f"  📊 VIX: {macro.vix:.2f}")
                # SPY
                if macro.spy_price is not None:
                    reasoning.append(f"  📈 SPY: {macro.spy_price:.2f}")
                # 黄金
                if macro.gld_price is not None:
                    reasoning.append(f"  🥇 GLD: {macro.gld_price:.2f}")
                # CPI
                if macro.cpi is not None:
                    reasoning.append(f"  💵 CPI: {macro.cpi:.1f}")
                # 联邦基金利率
                if macro.fed_funds_rate is not None:
                    reasoning.append(f"  🏦 联邦基金利率: {macro.fed_funds_rate:.2f}%")
                # M2
                if macro.m2 is not None:
                    reasoning.append(f"  💰 M2: {macro.m2:.1f}B")
                # 10年-2年利差
                if macro.treasury_yield_10y_2y is not None:
                    reasoning.append(f"  📉 10Y-2Y利差: {macro.treasury_yield_10y_2y:.2f}%")
            else:
                reasoning.append(f"[F5宏观] 数据源: 本地（数据采集中心不可用）")
        except Exception as e:
            reasoning.append(f"[F5宏观] 数据源: 本地（{str(e)[:30]}）")
    else:
        reasoning.append(f"[F5宏观] 数据源: 本地（模块未加载）")

    # ── 宏观方向判断 ──────────────────────────────────────────────
    direction = "HOLD"
    conf = 0.45

    if macro:
        # VIX < 20 = 低波动 = 风险偏好 = 偏多
        # VIX > 30 = 高波动 = 风险规避 = 偏空
        if macro.vix is not None:
            if macro.vix < 18:
                direction = "LONG"
                conf = 0.55
                reasoning.append(f"  ✅ VIX {macro.vix:.1f} < 18，风险偏好高，偏多")
            elif macro.vix > 30:
                direction = "SHORT"
                conf = 0.55
                reasoning.append(f"  🔴 VIX {macro.vix:.1f} > 30，风险规避，偏空")
            else:
                reasoning.append(f"  ⚖️  VIX {macro.vix:.1f} 正常区间")

        # 联邦基金利率
        # 高利率 = 流动性紧 = 偏空
        # 低利率 = 流动性松 = 偏多
        if macro.fed_funds_rate is not None:
            if macro.fed_funds_rate > 4.5:
                reasoning.append(f"  🔴 联邦基金利率 {macro.fed_funds_rate:.2f}% > 4.5%，流动性紧")
                if direction == "HOLD":
                    direction = "SHORT"
                    conf = 0.48
            elif macro.fed_funds_rate < 2.0:
                reasoning.append(f"  ✅ 联邦基金利率 {macro.fed_funds_rate:.2f}% < 2.0%，流动性松")
                if direction == "HOLD":
                    direction = "LONG"
                    conf = 0.50

        # 10年-2年利差倒挂 = 衰退信号
        if macro.treasury_yield_10y_2y is not None:
            if macro.treasury_yield_10y_2y < 0:
                reasoning.append(f"  ⚠️ 10Y-2Y利差倒挂 ({macro.treasury_yield_10y_2y:.2f}%)，衰退信号")

        # SPY 趋势
        if macro.spy_price is not None:
            if macro.spy_price > 550:
                reasoning.append(f"  ✅ SPY {macro.spy_price:.0f} 高位，风险资产偏好")

    return {
        "node": "F5_宏观",
        "direction": direction,
        "confidence": round(conf, 3),
        "rationale": reasoning,
        "source": source,
        "data": {
            "coin": coin,
            "source": source,
            "vix": macro.vix if macro else None,
            "spy_price": macro.spy_price if macro else None,
            "gld_price": macro.gld_price if macro else None,
            "cpi": macro.cpi if macro else None,
            "ppi": macro.ppi if macro else None,
            "fed_funds_rate": macro.fed_funds_rate if macro else None,
            "m2": macro.m2 if macro else None,
            "treasury_yield_10y_2y": macro.treasury_yield_10y_2y if macro else None,
            "fed_balance_sheet": macro.fed_balance_sheet if macro else None,
        }
    }


def f5_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
