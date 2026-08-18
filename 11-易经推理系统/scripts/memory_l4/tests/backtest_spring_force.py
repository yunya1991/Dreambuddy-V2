#!/usr/bin/env python3
"""弹簧力场多空过滤器回测脚本（Phase D 形态差异化过滤版）

目标：验证 Phase D 4维度形态判定 + 差异化做空过滤能否有效提升做空胜率

方法：
1. 取 BTC 日线历史数据（OKX API）
2. 在每个交易日生成模拟信号：
   - 做多信号：价格突破 MA20 + 成交量放大
   - 做空信号：价格跌破 MA20 + 成交量放大
3. 对每个做空信号，用 Phase D _regime_short_filter 判定是否允许
4. 对比 "无过滤做空" vs "Phase D 过滤后做空" 的胜率/盈亏
5. 按 market_regime 分组分析各形态下的做空表现
"""

import json
import sys
import os
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from pathlib import Path

# 确保可以 import 项目模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.yijing_trainer import _load_kline_from_okx


def fetch_btc_daily_closes(limit: int = 1500) -> list:
    """获取 BTC 日线收盘价（分页获取，OKX 单次最多 300 根）"""
    from scripts.memory_l4.okx_simulated import OKXSimulatedClient

    client = OKXSimulatedClient()
    all_candles = []

    # 分页：每次取 300 根，用最后一条的 ts 作为 before 参数往前翻
    page_limit = 300
    before_ts = None
    remaining = limit

    while remaining > 0:
        params = {"instId": "BTC-USDT-SWAP", "bar": "1D", "limit": str(min(page_limit, remaining))}
        if before_ts:
            params["before"] = str(before_ts)

        r = client._get("/api/v5/market/candles", params, auth=False)
        if r.get("code") != "0":
            print(f"OKX API 错误: {r.get('msg', 'unknown')}")
            break

        candles = r.get("data", [])
        if not candles:
            break

        for d in candles:
            all_candles.append({
                "ts": int(d[0]),
                "c": float(d[4]),
                "o": float(d[1]),
                "h": float(d[2]),
                "l": float(d[3]),
                "vol": float(d[5]),
            })

        # 下一页：用最旧一条的 ts 作为 before
        before_ts = int(candles[-1][0])
        remaining -= len(candles)

        if len(candles) < page_limit:
            break  # 没有更多数据了

    if not all_candles:
        print("无法获取 BTC K线数据")
        return []

    # 按时间排序（newest first）
    all_candles.sort(key=lambda x: x["ts"], reverse=True)
    closes = [c["c"] for c in all_candles]
    print(f"  分页获取 {len(all_candles)} 根日线")
    return closes


def generate_signals(closes: list, lookback: int = 20) -> list:
    """生成模拟多空信号（多种信号源增加样本量）

    信号逻辑：
    A) MA20 交叉信号（趋势跟随）
       - 做多：价格从 MA20 下方突破到上方
       - 做空：价格从 MA20 上方跌破到下方

    B) RSI 超买超卖信号（反转）
       - 做多：RSI(14) < 30（超卖反弹）
       - 做空：RSI(14) > 70（超买回落）

    C) 突破信号
       - 做多：价格突破近 20 日新高
       - 做空：价格跌破近 20 日新低

    Returns:
        list of (index, direction, price, ma_value, signal_type)
    """
    signals = []
    if len(closes) < lookback + 2:
        return signals

    for i in range(lookback + 1, len(closes) - 1):
        price = closes[i]
        prev_price = closes[i+1]
        # MA(lookback)
        ma = sum(closes[i:i+lookback]) / lookback
        prev_ma = sum(closes[i+1:i+1+lookback]) / lookback

        # A) MA20 交叉
        if prev_price <= prev_ma and price > ma:
            signals.append((i, "long", price, ma, "ma_cross"))
        if prev_price >= prev_ma and price < ma:
            signals.append((i, "short", price, ma, "ma_cross"))

        # B) RSI(14) 超买超卖
        rsi_period = 14
        if len(closes) - i >= rsi_period + 1:
            changes = [closes[j] - closes[j+1] for j in range(i, i+rsi_period)]
            gains = [c for c in changes if c > 0]
            losses = [-c for c in changes if c < 0]
            avg_gain = sum(gains) / rsi_period if gains else 0
            avg_loss = sum(losses) / rsi_period if losses else 0.001
            rsi = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 100

            if rsi > 70:
                signals.append((i, "short", price, ma, "rsi_overbought"))
            if rsi < 30:
                signals.append((i, "long", price, ma, "rsi_oversold"))

        # C) 突破信号（20 日高低点）
        if len(closes) - i >= lookback:
            recent_high = max(closes[i+1:i+1+lookback])
            recent_low = min(closes[i+1:i+1+lookback])
            if price > recent_high:
                signals.append((i, "long", price, ma, "breakout_high"))
            if price < recent_low:
                signals.append((i, "short", price, ma, "breakout_low"))

    return signals


def calculate_hold_pnl(closes: list, entry_idx: int, direction: str, hold_days: int = 5) -> tuple:
    """计算持有 hold_days 天后的盈亏

    closes 是 newest first，所以 entry_idx 的未来是 entry_idx - hold_days
    """
    entry_price = closes[entry_idx]
    exit_idx = entry_idx - hold_days
    if exit_idx < 0:
        exit_idx = 0
    exit_price = closes[exit_idx]

    if direction == "long":
        pnl_pct = (exit_price - entry_price) / entry_price
    else:  # short
        pnl_pct = (entry_price - exit_price) / entry_price

    return pnl_pct, exit_price


def run_backtest():
    """主回测函数（Phase D 形态差异化过滤版）"""
    print("=" * 80)
    print("弹簧力场多空过滤器回测（Phase D 形态差异化过滤）")
    print("=" * 80)

    # 1. 获取数据
    print("\n[1] 获取 BTC 日线数据...")
    closes = fetch_btc_daily_closes(limit=1500)
    if len(closes) < 300:
        print(f"数据不足: {len(closes)} 根 K线")
        return
    print(f"  获取 {len(closes)} 根日线，价格范围: {min(closes):.0f} ~ {max(closes):.0f}")

    # 2. 生成信号
    print("\n[2] 生成模拟多空信号...")
    signals = generate_signals(closes, lookback=20)
    long_signals = [(i, d, p, m, st) for i, d, p, m, st in signals if d == "long"]
    short_signals = [(i, d, p, m, st) for i, d, p, m, st in signals if d == "short"]
    print(f"  总信号数: {len(signals)} (做多: {len(long_signals)}, 做空: {len(short_signals)})")

    if not short_signals:
        print("  无做空信号，无法回测做空过滤")
        return

    # 3. 准备 PollingTrader 实例（绕过 __init__）
    from scripts.memory_l4.polling_trader import PollingTrader
    with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
        trader = PollingTrader.__new__(PollingTrader)
    trader._log = MagicMock()
    trader._btc_trend_cache = {"ts": 0, "result": None}
    trader._us_index_trend_cache = {"ts": 0, "result": None}
    trader.short_confidence_threshold = 0.70
    trader.confidence_threshold = 0.70

    # 4. 逐笔计算弹簧力场 + Phase D 形态判定
    print("\n[3] 逐笔计算弹簧力场 + Phase D 形态判定...")

    # 结果字段:
    # (idx, price, score, F_total, F_net, F_inter, U_short, U_total, slope,
    #  regime, TR, CV, F_dot, allow_short, filter_reason, pnl_pct, valid_bd, sig_type)
    results_short = []

    for idx, direction, price, ma_val, sig_type in short_signals:
        # 取到 idx 位置为止的 closes（包含 idx）
        sub_closes = closes[idx:]
        if len(sub_closes) < 210:
            continue
        sub_closes = sub_closes[:1500]

        trader._btc_trend_cache = {"ts": 0, "result": None}

        res = trader._calc_5ma_spring_force(sub_closes, tier="daily_btc")
        score = res["bearish_score"]
        F_total = res.get("F_total", res.get("F_net", 0))
        F_net = res.get("F_net", 0)
        F_inter = res.get("F_inter_net", 0)
        U_total = res.get("U_potential", 0)
        U_short = res.get("U_short", 0)
        slope = res.get("slope_avg", 0)
        valid_bd = res.get("valid_breakdown", False)
        F_dot = res.get("F_dot", 0.0)
        regime = res.get("market_regime", "RANGING")
        TR = res.get("trend_ratio", 0.0)
        CV = res.get("cv_dispersion", 0.0)

        # Phase D: 用 _regime_short_filter 判定
        allow_short, filter_reason = trader._regime_short_filter(
            regime=regime,
            score=score,
            U=U_short,
            F_dot=F_dot,
            valid_bd=valid_bd,
        )

        # 计算持有 5 天的盈亏
        pnl_pct, _ = calculate_hold_pnl(closes, idx, "short", hold_days=5)

        results_short.append((idx, price, score, F_total, F_net, F_inter,
                              U_short, U_total, slope, regime, TR, CV, F_dot,
                              allow_short, filter_reason, pnl_pct, valid_bd, sig_type))

    # 做多信号也计算 regime（用于对称验证）
    results_long = []
    for idx, direction, price, ma_val, sig_type in long_signals:
        sub_closes = closes[idx:]
        if len(sub_closes) < 210:
            continue
        sub_closes = sub_closes[:1500]
        trader._btc_trend_cache = {"ts": 0, "result": None}

        res = trader._calc_5ma_spring_force(sub_closes, tier="daily_btc")
        score = res["bearish_score"]
        F_total = res.get("F_total", res.get("F_net", 0))
        regime = res.get("market_regime", "RANGING")
        strict_bull = res.get("strict_bullish", False)
        U_short = res.get("U_short", 0)

        pnl_pct, _ = calculate_hold_pnl(closes, idx, "long", hold_days=5)

        results_long.append((idx, price, score, F_total, regime, strict_bull,
                             U_short, pnl_pct, sig_type))

    # 5. 分析做空回测结果
    print("\n" + "=" * 80)
    print("[4] 做空回测结果分析（Phase D 形态差异化过滤）")
    print("=" * 80)

    regime_order = ["TREND_BULL", "STRONG_TREND_BEAR", "TREND_BEAR",
                    "MEAN_REVERTING", "RANGING"]

    if not results_short:
        print("  无有效做空信号样本")
    else:
        # 5a) 无过滤（全部做空）
        all_short = results_short
        all_wins = [r for r in all_short if r[15] > 0]
        all_losses = [r for r in all_short if r[15] <= 0]
        all_pnl = sum(r[15] for r in all_short)
        all_winrate = len(all_wins) / len(all_short) * 100 if all_short else 0

        print(f"\n  --- 无过滤（全部做空）---")
        print(f"  信号数: {len(all_short)}")
        print(f"  胜率: {all_winrate:.1f}% ({len(all_wins)}胜 / {len(all_losses)}负)")
        print(f"  累计盈亏: {all_pnl*100:.2f}%")
        print(f"  平均盈亏: {all_pnl/len(all_short)*100:.3f}%")

        # 5b) Phase D 过滤后
        filtered_short = [r for r in results_short if r[13]]  # allow_short=True
        if filtered_short:
            filt_wins = [r for r in filtered_short if r[15] > 0]
            filt_losses = [r for r in filtered_short if r[15] <= 0]
            filt_pnl = sum(r[15] for r in filtered_short)
            filt_winrate = len(filt_wins) / len(filtered_short) * 100 if filtered_short else 0

            print(f"\n  --- Phase D 形态过滤后做空 ---")
            print(f"  信号数: {len(filtered_short)} (过滤掉 {len(all_short) - len(filtered_short)} 个)")
            print(f"  胜率: {filt_winrate:.1f}% ({len(filt_wins)}胜 / {len(filt_losses)}负)")
            print(f"  累计盈亏: {filt_pnl*100:.2f}%")
            print(f"  平均盈亏: {filt_pnl/len(filtered_short)*100:.3f}%")

            # 过滤效果
            delta_winrate = filt_winrate - all_winrate
            delta_pnl = filt_pnl - all_pnl
            print(f"\n  --- 过滤效果 ---")
            print(f"  胜率提升: {delta_winrate:+.1f}%")
            print(f"  盈亏改善: {delta_pnl*100:+.2f}%")
        else:
            print(f"\n  Phase D 过滤后: 全部 {len(all_short)} 个做空信号被过滤")

        # 5c) 按 market_regime 分组（Phase D 核心分析）
        print(f"\n  --- 按 market_regime 分组 ---")
        for regime_name in regime_order:
            group = [r for r in results_short if r[9] == regime_name]
            if not group:
                continue
            wins = [r for r in group if r[15] > 0]
            pnl = sum(r[15] for r in group)
            wr = len(wins) / len(group) * 100
            avg_tr = sum(r[10] for r in group) / len(group)
            avg_cv = sum(r[11] for r in group) / len(group)
            avg_slope = sum(r[8] for r in group) / len(group)
            avg_u_short = sum(r[6] for r in group) / len(group)
            avg_fdot = sum(r[12] for r in group) / len(group)
            allowed = len([r for r in group if r[13]])
            print(f"  {regime_name:20s}: n={len(group):3d} 胜率={wr:5.1f}% 累计={pnl*100:+7.2f}% "
                  f"允许做空={allowed:3d} TR={avg_tr:.3f} CV={avg_cv:.4f} "
                  f"slope={avg_slope:+.3f}% U_s={avg_u_short:.5f} F_dot={avg_fdot:+.4f}")

        # 5d) 按 bearish_score 分组
        print(f"\n  --- 按 bearish_score 分组 ---")
        for score_name in ["STRONG", "NORMAL", "WEAK", "NONE"]:
            group = [r for r in results_short if r[2] == score_name]
            if not group:
                continue
            wins = [r for r in group if r[15] > 0]
            pnl = sum(r[15] for r in group)
            wr = len(wins) / len(group) * 100
            avg_f = sum(r[3] for r in group) / len(group)
            avg_u = sum(r[6] for r in group) / len(group)
            print(f"  {score_name:6s}: n={len(group):3d} 胜率={wr:5.1f}% 累计={pnl*100:+7.2f}% "
                  f"avg_F={avg_f:+.3f} avg_U_s={avg_u:.5f}")

        # 5e) 被过滤掉的做空信号
        blocked = [r for r in results_short if not r[13]]
        if blocked:
            blocked_wins = [r for r in blocked if r[15] > 0]
            blocked_pnl = sum(r[15] for r in blocked)
            blocked_wr = len(blocked_wins) / len(blocked) * 100 if blocked else 0
            print(f"\n  --- 被过滤掉的做空信号 ---")
            print(f"  数量: {len(blocked)}")
            print(f"  其中盈利: {len(blocked_wins)} (胜率 {blocked_wr:.1f}%)")
            print(f"  被过滤信号的累计盈亏: {blocked_pnl*100:+.2f}%")
            if blocked_wr < 50:
                print(f"  ✓ 过滤掉的信号胜率 < 50%，过滤方向正确")
            else:
                print(f"  ✗ 过滤掉的信号胜率 >= 50%，可能过滤过度")

            # 被过滤信号按 regime 分布
            print(f"\n  --- 被过滤信号按 regime 分布 ---")
            for regime_name in regime_order:
                group = [r for r in blocked if r[9] == regime_name]
                if group:
                    print(f"  {regime_name:20s}: {len(group):3d} 个被过滤")

    # 6. 分析做多回测结果
    print("\n" + "=" * 80)
    print("[5] 做多回测结果分析（对称验证）")
    print("=" * 80)

    if not results_long:
        print("  无有效做多信号样本")
    else:
        all_long = results_long
        all_wins_l = [r for r in all_long if r[7] > 0]
        all_pnl_l = sum(r[7] for r in all_long)
        all_wr_l = len(all_wins_l) / len(all_long) * 100 if all_long else 0

        print(f"\n  --- 无过滤（全部做多）---")
        print(f"  信号数: {len(all_long)}")
        print(f"  胜率: {all_wr_l:.1f}% ({len(all_wins_l)}胜)")
        print(f"  累计盈亏: {all_pnl_l*100:.2f}%")

        # 按 regime 分组做多
        print(f"\n  --- 按 market_regime 分组做多 ---")
        for regime_name in regime_order:
            group = [r for r in results_long if r[3] == regime_name]
            if not group:
                continue
            wins = [r for r in group if r[7] > 0]
            pnl = sum(r[7] for r in group)
            wr = len(wins) / len(group) * 100
            print(f"  {regime_name:20s}: n={len(group):3d} 胜率={wr:5.1f}% 累计={pnl*100:+7.2f}%")

    # 7. Phase D 核心指标分析
    print("\n" + "=" * 80)
    print("[6] Phase D 4维度指标分析（做空）")
    print("=" * 80)

    if results_short:
        # TR 分析
        print(f"\n  --- 趋势强度比 TR 分析 ---")
        for tr_range in [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]:
            group = [r for r in results_short if tr_range[0] <= r[10] < tr_range[1]]
            if not group:
                continue
            wins = [r for r in group if r[15] > 0]
            pnl = sum(r[15] for r in group)
            wr = len(wins) / len(group) * 100
            print(f"  TR [{tr_range[0]:.1f}, {tr_range[1]:.1f}): n={len(group):3d} 胜率={wr:5.1f}% 累计={pnl*100:+7.2f}%")

        # CV 分析
        print(f"\n  --- 均线发散度 CV 分析 ---")
        for cv_range in [(0.0, 0.01), (0.01, 0.02), (0.02, 0.03), (0.03, 0.05), (0.05, 1.0)]:
            group = [r for r in results_short if cv_range[0] <= r[11] < cv_range[1]]
            if not group:
                continue
            wins = [r for r in group if r[15] > 0]
            pnl = sum(r[15] for r in group)
            wr = len(wins) / len(group) * 100
            print(f"  CV [{cv_range[0]:.3f}, {cv_range[1]:.3f}): n={len(group):3d} 胜率={wr:5.1f}% 累计={pnl*100:+7.2f}%")

        # Slope 分析
        print(f"\n  --- 斜率强度分析 ---")
        for sl_range in [(-1.0, -0.03), (-0.03, -0.01), (-0.01, 0.01), (0.01, 0.03), (0.03, 1.0)]:
            group = [r for r in results_short if sl_range[0] <= r[8] < sl_range[1]]
            if not group:
                continue
            wins = [r for r in group if r[15] > 0]
            pnl = sum(r[15] for r in group)
            wr = len(wins) / len(group) * 100
            print(f"  slope [{sl_range[0]:+.3f}, {sl_range[1]:+.3f}): n={len(group):3d} 胜率={wr:5.1f}% 累计={pnl*100:+7.2f}%")

        # F_dot 分析
        print(f"\n  --- F_dot 趋势加速度分析 ---")
        for fd_range in [(-1.0, -0.01), (-0.01, -0.005), (-0.005, -0.002), (-0.002, 0.0), (0.0, 0.01), (0.01, 1.0)]:
            group = [r for r in results_short if fd_range[0] <= r[12] < fd_range[1]]
            if not group:
                continue
            wins = [r for r in group if r[15] > 0]
            pnl = sum(r[15] for r in group)
            wr = len(wins) / len(group) * 100
            print(f"  F_dot [{fd_range[0]:+.4f}, {fd_range[1]:+.4f}): n={len(group):3d} 胜率={wr:5.1f}% 累计={pnl*100:+7.2f}%")

        # U_short 分析
        print(f"\n  --- U_short 超卖分析 ---")
        for u_range in [(0.0, 0.001), (0.001, 0.002), (0.002, 0.005), (0.005, 0.01), (0.01, 1.0)]:
            group = [r for r in results_short if u_range[0] <= r[6] < u_range[1]]
            if not group:
                continue
            wins = [r for r in group if r[15] > 0]
            pnl = sum(r[15] for r in group)
            wr = len(wins) / len(group) * 100
            print(f"  U_short [{u_range[0]:.4f}, {u_range[1]:.4f}): n={len(group):3d} 胜率={wr:5.1f}% 累计={pnl*100:+7.2f}%")

    # 8. 综合结论
    print("\n" + "=" * 80)
    print("[7] 综合结论")
    print("=" * 80)

    if results_short:
        # 过滤前后的核心对比
        all_wr = len([r for r in results_short if r[15] > 0]) / len(results_short) * 100
        filtered = [r for r in results_short if r[13]]
        filt_wr = len([r for r in filtered if r[15] > 0]) / len(filtered) * 100 if filtered else 0

        print(f"\n  Phase D 做空过滤效果:")
        print(f"    过滤前胜率: {all_wr:.1f}% (n={len(results_short)})")
        print(f"    过滤后胜率: {filt_wr:.1f}% (n={len(filtered)})")
        print(f"    胜率变化: {filt_wr - all_wr:+.1f}%")

        # 各 regime 下的做空胜率
        print(f"\n  各 regime 下做空胜率:")
        for regime_name in regime_order:
            group = [r for r in results_short if r[9] == regime_name]
            if not group:
                continue
            wins = [r for r in group if r[15] > 0]
            wr = len(wins) / len(group) * 100
            allowed = len([r for r in group if r[13]])
            print(f"    {regime_name:20s}: n={len(group):3d} 胜率={wr:5.1f}% 允许做空={allowed}")

    print("\n" + "=" * 80)
    print("回测完成")
    print("=" * 80)


if __name__ == "__main__":
    run_backtest()
