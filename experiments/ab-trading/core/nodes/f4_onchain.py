"""
F4 链上分析节点
获取链上数据：BTC 基础指标 + 周期信号 + 底部信号

数据源: 18-数据获取中心/data_center.db (mempool + blockchain_info + panewslab cycle + theblockbeats)
FAIL-OPEN: DataCenterClient 不可用时返回中性

SKILL.md 调用路径: experiments/ab-trading/core/nodes/f4_onchain
"""

from typing import Dict, Any

try:
    from core.modules.data_center_adapter import get_data_center_client
    _DC_OK = True
except ImportError:
    _DC_OK = False


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 F4 链上分析

    优先从数据采集中心获取链上数据（MVRV/Puell Multiple/周期信号/底部信号），
    失败时返回中性。

    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据

    Returns:
        {
            "node": "F4_链上",
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "data": {...链上详情...},
            "source": "data_center" | "local_fallback"
        }
    """
    reasoning = []
    coin = mkt.get("coin", "BTC")
    source = "local_fallback"
    onchain = None

    if _DC_OK:
        try:
            client = get_data_center_client()
            if client.is_available():
                onchain = client.get_onchain()
                source = "data_center"
                reasoning.append(f"[F4链上] 数据源: 数据采集中心")

                # 链上基础
                if onchain.total_btc > 0:
                    reasoning.append(f"  ⛓️  BTC 总量: {onchain.total_btc/1e6:.2f}M")
                if onchain.market_cap_usd > 0:
                    reasoning.append(f"  💰 市值: ${onchain.market_cap_usd/1e9:.2f}B")
                if onchain.tip_height > 0:
                    reasoning.append(f"  📦 区块高度: {int(onchain.tip_height)}")
                if onchain.difficulty_progress_pct > 0:
                    reasoning.append(f"  ⛏️  难度进度: {onchain.difficulty_progress_pct:.1f}%")

                # 周期信号
                if onchain.cycle_hit_ratio is not None:
                    reasoning.append(f"  📅 周期信号命中比: {onchain.cycle_hit_ratio:.2f}%")
                if onchain.mvrv_value is not None:
                    reasoning.append(f"  📊 MVRV: {onchain.mvrv_value:.3f}")
                if onchain.puell_multiple is not None:
                    reasoning.append(f"  ⚡ Puell Multiple: {onchain.puell_multiple:.3f}")

                # 底部信号
                if onchain.bottom_signal_status:
                    reasoning.append(f"  📉 底部信号: {onchain.bottom_signal_status}")
            else:
                reasoning.append(f"[F4链上] 数据源: 本地（数据采集中心不可用）")
        except Exception as e:
            reasoning.append(f"[F4链上] 数据源: 本地（{str(e)[:30]}）")
    else:
        reasoning.append(f"[F4链上] 数据源: 本地（模块未加载）")

    # ── 链上方向判断 ──────────────────────────────────────────────
    direction = "HOLD"
    conf = 0.45

    if onchain:
        # MVRV < 1.0 = 低估 = 偏多
        # MVRV > 3.0 = 高估 = 偏空
        if onchain.mvrv_value is not None:
            if onchain.mvrv_value < 1.0:
                direction = "LONG"
                conf = 0.58
                reasoning.append(f"  ✅ MVRV {onchain.mvrv_value:.2f} < 1.0，低估偏多")
            elif onchain.mvrv_value > 3.0:
                direction = "SHORT"
                conf = 0.58
                reasoning.append(f"  🔴 MVRV {onchain.mvrv_value:.2f} > 3.0，高估偏空")
            else:
                reasoning.append(f"  ⚖️  MVRV {onchain.mvrv_value:.2f} 正常区间")

        # Puell Multiple < 0.5 = 矿工收入低 = 底部信号 = 偏多
        # Puell Multiple > 4.0 = 矿工收入高 = 顶部信号 = 偏空
        if onchain.puell_multiple is not None:
            if onchain.puell_multiple < 0.5:
                direction = "LONG"
                conf = max(conf, 0.55)
                reasoning.append(f"  ✅ Puell {onchain.puell_multiple:.2f} < 0.5，底部偏多")
            elif onchain.puell_multiple > 4.0:
                direction = "SHORT"
                conf = max(conf, 0.55)
                reasoning.append(f"  🔴 Puell {onchain.puell_multiple:.2f} > 4.0，顶部偏空")

        # 周期信号命中比
        if onchain.cycle_hit_ratio is not None:
            if onchain.cycle_hit_ratio > 50:
                reasoning.append(f"  📈 周期命中 {onchain.cycle_hit_ratio:.1f}% > 50%，底部信号强")
                if direction == "HOLD":
                    direction = "LONG"
                    conf = 0.50
            elif onchain.cycle_hit_ratio < 20:
                reasoning.append(f"  📉 周期命中 {onchain.cycle_hit_ratio:.1f}% < 20%，底部信号弱")

    return {
        "node": "F4_链上",
        "direction": direction,
        "confidence": round(conf, 3),
        "rationale": reasoning,
        "source": source,
        "data": {
            "coin": coin,
            "source": source,
            "total_btc": onchain.total_btc if onchain else None,
            "market_cap_usd": onchain.market_cap_usd if onchain else None,
            "tip_height": onchain.tip_height if onchain else None,
            "cycle_hit_ratio": onchain.cycle_hit_ratio if onchain else None,
            "mvrv_value": onchain.mvrv_value if onchain else None,
            "puell_multiple": onchain.puell_multiple if onchain else None,
            "bottom_signal_status": onchain.bottom_signal_status if onchain else None,
        }
    }


def f4_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
