#!/usr/bin/env python3
"""
ETH 持仓离场分析脚本。

用 ClassicExitSystem 分析当前 ETH 持仓，
分别模拟 hold、reduce、提高止盈、平仓四种操作的依据。
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from scripts.memory_l4.classic_exit_system import (
    ClassicExitSystem,
    PositionState as ExitPositionState,
    ExitAction,
    ExitConfig,
)
from scripts.memory_l4.okx_simulated import OKXSimulatedClient
from scripts.memory_l4.yijing_trainer import _load_kline_from_okx


def get_eth_position():
    """获取 ETH 持仓信息"""
    client = OKXSimulatedClient()
    result = client.get_positions("ETH-USDT-SWAP")
    if not result.get("ok"):
        return None
    positions = [p for p in result.get("positions", []) if float(p.get("pos", 0)) > 0]
    if not positions:
        return None
    return positions[0]


def get_eth_klines(limit=200):
    """获取 ETH K线数据"""
    return _load_kline_from_okx("ETH-USDT-SWAP", "1H", limit)


def build_exit_state(pos, kline_data, atr_pct=0.01):
    """构建离场状态"""
    entry_price = float(pos.get("avg_px", 0))
    current_price = float(pos.get("mark_px", pos.get("last", 0)))
    upl_ratio = (current_price - entry_price) / entry_price if pos.get("pos_side") == "long" \
        else (entry_price - current_price) / entry_price
    
    # 计算持仓时间（用最后一根K线的时间近似）
    position_age_sec = 3600  # 假设持仓1小时（新开仓）
    # 如果有开仓时间则用开仓时间
    open_time = pos.get("cTime", pos.get("openTime", 0))
    try:
        open_time = float(open_time)
        if open_time > 1000000000000:
            open_time = open_time / 1000
        if open_time > 1000000000:  # 合理的时间戳
            position_age_sec = time.time() - open_time
    except (ValueError, TypeError):
        pass
    
    # 限制持仓时间在合理范围内（避免显示异常）
    position_age_sec = max(3600, min(position_age_sec, 86400 * 2))
    
    return ExitPositionState(
        coin="ETH",
        side=pos.get("pos_side", "long"),
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=position_age_sec,
        unrealized_pnl_pct=upl_ratio,
        leverage=3.0,
        atr_pct=atr_pct,
        mfe_pnl_pct=max(0.0, upl_ratio),
    )


def analyze_exit_scenarios():
    """分析四种离场场景"""
    print("=" * 80)
    print("ETH 持仓离场分析")
    print("=" * 80)
    
    # 获取持仓
    pos = get_eth_position()
    if not pos:
        print("\n❌ 没有 ETH 持仓")
        return
    
    print(f"\n📊 持仓信息:")
    print(f"  方向: {pos.get('pos_side')}")
    print(f"  入场价: {pos.get('avg_px')}")
    print(f"  标记价: {pos.get('mark_px')}")
    print(f"  持仓量: {pos.get('pos')}")
    print(f"  未实现盈亏: {pos.get('upl')} USDT ({pos.get('uplRatio')}%)")
    
    # 获取K线
    kline_data = get_eth_klines(200)
    print(f"\n📈 K线数据: {len(kline_data)} 根1H K线")
    
    # 计算ATR
    closes = [float(k['c']) for k in kline_data]
    highs = [float(k['h']) for k in kline_data]
    lows = [float(k['l']) for k in kline_data]
    
    tr_values = []
    for i in range(1, len(kline_data)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_values.append(tr)
    atr = sum(tr_values[-14:]) / 14 if len(tr_values) >= 14 else 0
    atr_pct = atr / closes[-1] if closes[-1] > 0 else 0.01
    
    print(f"  ATR: {atr:.2f} ({atr_pct*100:.2f}%)")
    
    # 构建K线格式
    candles_1h = [
        {
            "t": k.get("ts", 0),
            "o": float(k.get("o", 0)),
            "h": float(k.get("h", 0)),
            "l": float(k.get("l", 0)),
            "c": float(k.get("c", 0)),
            "v": float(k.get("v", 0)),
        }
        for k in kline_data
    ]
    
    # 初始化离场系统
    exit_cfg = ExitConfig(
        l0_max_hold_sec=172800,
        l0_max_loss_pct=-0.05,
        tb_enabled=True,
        tb_sl_atr_mult=1.5,
        tb_tp_atr_mult=3.0,
        tb_sl_min_pct=0.02,
        tb_tp_min_pct=0.04,
        trailing_enabled=True,
        trailing_arm_profit_pct=0.04,
        trailing_retrace_pct=0.02,
        tstp_enabled=True,
        l1_enabled=True,
        l2_close_threshold=0.75,
        l2_reduce_threshold=0.55,
        apply_leverage_to_thresholds=False,
        inflight_cooldown_sec=180,
    )
    exit_system = ClassicExitSystem(config=exit_cfg)
    
    # 构建离场状态
    exit_pos = build_exit_state(pos, kline_data, atr_pct)
    
    print(f"\n⚙️  离场状态:")
    print(f"  入场价: {exit_pos.entry_price:.2f}")
    print(f"  当前价: {exit_pos.current_price:.2f}")
    print(f"  浮盈: {exit_pos.unrealized_pnl_pct*100:.2f}%")
    print(f"  持仓时间: {exit_pos.position_age_sec/3600:.1f} 小时")
    print(f"  杠杆: {exit_pos.leverage}x")
    
    # 执行离场评估
    print(f"\n{'='*80}")
    print(f"📊 离场系统评估结果 (实际决策)")
    print(f"{'='*80}")
    
    exit_decision = exit_system.evaluate_full(
        pos=exit_pos,
        candles_1h=candles_1h,
        regime="chop",
    )
    
    print(f"\n  决策动作: {exit_decision.action.value}")
    print(f"  原因: {exit_decision.reason}")
    print(f"  优先级: {exit_decision.priority.value}")
    print(f"  置信度: {exit_decision.confidence:.2f}")
    
    if exit_decision.action == ExitAction.REDUCE:
        print(f"  减仓比例: {exit_decision.reduce_frac:.0%}")
    elif exit_decision.action == ExitAction.RAISE_TP:
        print(f"  新止盈价: {exit_decision.new_tp_price:.2f}")
        print(f"  新止盈比例: {exit_decision.new_tp_pct*100:.2f}%")
    
    if exit_decision.features:
        f = exit_decision.features
        print(f"\n  📐 特征分析:")
        print(f"    持有风险 (hold_risk): {f.hold_risk:.2f}")
        print(f"    持有价值 (hold_value): {f.hold_value:.2f}")
        print(f"    RSI: {f.rsi:.2f}")
        print(f"    ADX: {f.adx:.2f}")
        print(f"    MACD柱: {f.macd_hist:.4f}")
        print(f"    波动率 (atr_pct): {f.atr_pct*100:.2f}%")
        print(f"    趋势形态: {f.trend_shape.value}")
        print(f"    震荡指标 (chop): {f.chop:.2f}")
        print(f"    动量方向: {'向上' if f.mom_dir > 0 else '向下' if f.mom_dir < 0 else '中性'}")
        print(f"    成交量方向: {'放量' if f.vol_dir > 0 else '缩量' if f.vol_dir < 0 else '中性'}")
    
    # 场景1: HOLD - 为什么应该持有
    print(f"\n{'='*80}")
    print(f"🔍 场景1: 为什么应该 HOLD（持有）")
    print(f"{'='*80}")
    
    hold_reasons = []
    if exit_decision.action == ExitAction.HOLD:
        hold_reasons.append(f"离场系统当前决策就是 HOLD")
    
    if exit_pos.unrealized_pnl_pct < 0.04:
        hold_reasons.append("浮盈低于 4%，移动止盈尚未触发")
    if exit_pos.unrealized_pnl_pct > -0.05:
        hold_reasons.append("跌幅未超过 5% 硬止损")
    if exit_pos.position_age_sec < 172800:
        hold_reasons.append(f"持仓时间 {exit_pos.position_age_sec/3600:.1f}h < 48h 最大持有期")
    if hasattr(exit_decision.features, 'hold_value') and exit_decision.features:
        if exit_decision.features.hold_value > 0.4:
            hold_reasons.append(f"持有价值评分 {exit_decision.features.hold_value:.2f} 较高")
    
    for i, reason in enumerate(hold_reasons, 1):
        print(f"  {i}. {reason}")
    
    # 场景2: REDUCE - 什么情况下会减仓
    print(f"\n{'='*80}")
    print(f"📉 场景2: 什么情况下会 REDUCE（减仓）")
    print(f"{'='*80}")
    
    reduce_reasons = [
        "L2 趋势衰减: 当趋势强度下降到 55% 以下时，减仓 30-50%",
        "移动止盈回撤触发: 盈利超过 4% 后回撤 2%，触发部分止盈",
        "震荡市风险: 震荡市中达到中等盈利时，锁定部分利润",
        "持仓时间过长: 接近最大持有期但还想保留部分仓位",
    ]
    
    for i, reason in enumerate(reduce_reasons, 1):
        print(f"  {i}. {reason}")
    
    # 模拟减仓场景
    print(f"\n  模拟: 如果触发减仓 30%")
    reduce_pct = 0.3
    pos_usdt = float(pos.get('notionalUsd', 0))
    reduce_usdt = pos_usdt * reduce_pct
    print(f"    减仓前: {pos_usdt:.2f} USDT")
    print(f"    减仓量: {reduce_usdt:.2f} USDT ({reduce_pct*100:.0f}%)")
    print(f"    减仓后: {pos_usdt - reduce_usdt:.2f} USDT")
    print(f"    锁定利润: {float(pos.get('upl', 0)) * reduce_pct:.2f} USDT")
    
    # 场景3: RAISE_TP - 什么情况下会提高止盈
    print(f"\n{'='*80}")
    print(f"📈 场景3: 什么情况下会 RAISE_TP（提高止盈）")
    print(f"{'='*80}")
    
    raise_tp_reasons = [
        "趋势增强: 当 L2 趋势强度 > 75% 时，提高止盈目标",
        "突破关键阻力: 价格突破前高或关键阻力位",
        "量价配合: 成交量放大配合价格上涨",
        "移动止盈: 盈利持续扩大，跟踪止损上移",
    ]
    
    for i, reason in enumerate(raise_tp_reasons, 1):
        print(f"  {i}. {reason}")
    
    # 模拟提高止盈
    current_tp = exit_pos.entry_price * (1 + 3 * atr_pct)  # 初始3xATR
    new_tp = exit_pos.entry_price * (1 + 4 * atr_pct)  # 提高到4xATR
    print(f"\n  模拟: 止盈从 3xATR 提高到 4xATR")
    print(f"    原止盈价: {current_tp:.2f} ({(current_tp/exit_pos.entry_price-1)*100:.2f}%)")
    print(f"    新止盈价: {new_tp:.2f} ({(new_tp/exit_pos.entry_price-1)*100:.2f}%)")
    print(f"    提高幅度: {(new_tp - current_tp):.2f} ({(new_tp/current_tp-1)*100:.2f}%)")
    
    # 场景4: CLOSE - 什么情况下会平仓
    print(f"\n{'='*80}")
    print(f"🚪 场景4: 什么情况下会 CLOSE（平仓）")
    print(f"{'='*80}")
    
    close_reasons = [
        f"硬止损: 亏损达到 5%（当前浮盈 {exit_pos.unrealized_pnl_pct*100:.2f}%）",
        f"ATR止损: 价格跌破 1.5xATR 止损位",
        "趋势反转: L2 趋势完全反转（强度 > 75% 反向）",
        "信号反转: BCRM 推理出反向高置信度信号",
        "时间止损: 持仓超过 48 小时仍未达到目标",
        "移动止盈触发: 盈利后大幅回撤，触发追踪止盈",
    ]
    
    for i, reason in enumerate(close_reasons, 1):
        print(f"  {i}. {reason}")
    
    # 计算当前止损止盈位
    sl_price = exit_pos.entry_price * (1 - 1.5 * atr_pct)
    tp_price = exit_pos.entry_price * (1 + 3 * atr_pct)
    print(f"\n  当前止损止盈:")
    print(f"    止损价: {sl_price:.2f} ({(sl_price/exit_pos.entry_price-1)*100:.2f}%)")
    print(f"    止盈价: {tp_price:.2f} ({(tp_price/exit_pos.entry_price-1)*100:.2f}%)")
    print(f"    距离止损: {(exit_pos.current_price/sl_price-1)*100:.2f}%")
    print(f"    距离止盈: {(tp_price/exit_pos.current_price-1)*100:.2f}%")
    
    # 总结建议
    print(f"\n{'='*80}")
    print(f"💡 综合建议")
    print(f"{'='*80}")
    
    if exit_decision.action == ExitAction.HOLD:
        print(f"\n  当前建议: 继续持有 (HOLD)")
        print(f"  依据: {exit_decision.reason}")
        print(f"  置信度: {exit_decision.confidence:.2f}")
    elif exit_decision.action == ExitAction.REDUCE:
        print(f"\n  当前建议: 减仓 (REDUCE)")
        print(f"  依据: {exit_decision.reason}")
        print(f"  减仓比例: {exit_decision.reduce_frac:.0%}")
    elif exit_decision.action == ExitAction.RAISE_TP:
        print(f"\n  当前建议: 提高止盈 (RAISE_TP)")
        print(f"  依据: {exit_decision.reason}")
        print(f"  新止盈: {exit_decision.new_tp_price:.2f}")
    else:
        print(f"\n  当前建议: 平仓 (CLOSE)")
        print(f"  依据: {exit_decision.reason}")
    
    print(f"\n{'='*80}")


if __name__ == '__main__':
    analyze_exit_scenarios()
