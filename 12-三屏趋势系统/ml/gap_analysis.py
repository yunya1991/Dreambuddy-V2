"""策略 vs 买入持有：深度差距分析

核心问题：策略平均收益167% vs 买入持有451%，差距在哪里？

分析维度：
1. 牛市参与度：策略在牛市中持仓了多少天？捕获了多少涨幅？
2. 信号延迟：从趋势开始到策略建仓隔了多久？
3. 趋势过滤代价：过滤掉了多少本该盈利的信号？
4. 熊市防护：策略在熊市中减少了多少回撤？
5. 顶底识别：策略是否在接近顶部时减仓、接近底部时建仓？
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd

from data.market_data import fetch_historical_candles
from backtest.engine import BacktestEngine
from backtest.strategy import LeastResistanceStrategy


def fetch_real_data(inst_id, days=730):
    candles = fetch_historical_candles(inst_id, bar="1D", days=days)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def classify_regime(prices):
    close = prices["close"]
    ma200 = close.rolling(window=200, min_periods=200).mean()
    ma50 = close.rolling(window=50, min_periods=50).mean()
    ma200_slope = ma200.pct_change(periods=20)
    regime = pd.Series("sideways", index=prices.index)
    regime[(close > ma200) & (ma50 > ma200) & (ma200_slope > 0)] = "bull"
    regime[(close < ma200) & (ma50 < ma200) & (ma200_slope < 0)] = "bear"
    regime.iloc[:200] = "sideways"
    return regime, ma200, ma50


def analyze_symbol(name, prices):
    print(f"\n{'='*80}")
    print(f"  {name} 深度差距分析")
    print(f"{'='*80}")

    n = len(prices)
    regime, ma200, ma50 = classify_regime(prices)

    # 运行策略
    strategy = LeastResistanceStrategy(
        warmup_periods=min(80, n-10), update_step=1,
        min_holding_bars=15, signal_confirm_bars=4,
        max_position=1.0, enable_trend_filter=True, bear_short_only=True,
    )
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    signals = strategy.generate_signals(prices)
    result = engine.run(prices["close"], signals)

    positions = signals.values
    close = prices["close"].values
    daily_ret = pd.Series(close).pct_change().fillna(0).values
    bh_ret = (close[-1] / close[0] - 1) * 100
    strat_ret = result["metrics"]["total_return_pct"]

    print(f"\n  买入持有: {bh_ret:+.2f}%")
    print(f"  策略收益: {strat_ret:+.2f}%")
    print(f"  差距: {bh_ret - strat_ret:+.2f}pp")

    # === 1. 牛市参与度分析 ===
    print(f"\n--- 1. 牛市参与度分析 ---")
    for r_name in ["bull", "bear", "sideways"]:
        mask = (regime == r_name).values
        days = mask.sum()
        if days == 0:
            continue

        # 买入持有在该状态的收益
        regime_close = close[mask]
        bh_regime = (regime_close[-1] / regime_close[0] - 1) * 100

        # 策略在该状态的收益
        regime_pos = positions[mask]
        regime_ret = daily_ret[mask]
        strategy_daily = regime_pos[:-1] * regime_ret[1:]
        strat_regime = ((1 + pd.Series(strategy_daily)).prod() - 1) * 100

        # 持仓统计
        long_days = (regime_pos > 0.01).sum()
        short_days = (regime_pos < -0.01).sum()
        flat_days = (np.abs(regime_pos) <= 0.01).sum()
        avg_pos = np.abs(regime_pos[regime_pos != 0]).mean() if (regime_pos != 0).any() else 0

        # 捕获率
        capture = strat_regime / bh_regime * 100 if bh_regime != 0 else 0

        r_label = {"bull": "牛市", "bear": "熊市", "sideways": "震荡"}[r_name]
        print(f"\n  {r_label} ({days}天):")
        print(f"    买入持有: {bh_regime:+.2f}%")
        print(f"    策略收益: {strat_regime:+.2f}%")
        print(f"    捕获率:   {capture:.1f}%")
        print(f"    多头: {long_days}天({long_days/days*100:.0f}%) 空头: {short_days}天({short_days/days*100:.0f}%) 空仓: {flat_days}天({flat_days/days*100:.0f}%)")
        print(f"    平均仓位: {avg_pos:.3f}")

    # === 2. 信号延迟分析 ===
    print(f"\n--- 2. 信号延迟分析 ---")

    # 找到牛市开始点（regime从非bull变bull）
    regime_vals = regime.values
    bull_starts = []
    bear_starts = []
    for i in range(1, n):
        if regime_vals[i] == "bull" and regime_vals[i-1] != "bull":
            bull_starts.append(i)
        if regime_vals[i] == "bear" and regime_vals[i-1] != "bear":
            bear_starts.append(i)

    print(f"  牛市开始次数: {len(bull_starts)}")
    for idx, start in enumerate(bull_starts[:5]):
        # 找到策略首次建仓做多
        first_long = None
        for j in range(start, min(start + 200, n)):
            if positions[j] > 0.01:
                first_long = j
                break

        delay = first_long - start if first_long else -1
        start_price = close[start]
        long_price = close[first_long] if first_long else 0
        price_change = (long_price / start_price - 1) * 100 if first_long else 0

        start_date = prices.index[start].strftime('%Y-%m-%d')
        long_date = prices.index[first_long].strftime('%Y-%m-%d') if first_long else "N/A"

        print(f"    #{idx+1} 牛市开始: {start_date} (价格{start_price:.0f})")
        print(f"        策略建仓: {long_date} (价格{long_price:.0f})")
        print(f"        延迟: {delay}天, 错过涨幅: {price_change:.2f}%")

    print(f"\n  熊市开始次数: {len(bear_starts)}")
    for idx, start in enumerate(bear_starts[:5]):
        # 找到策略首次做空或清仓
        first_short = None
        for j in range(start, min(start + 200, n)):
            if positions[j] < -0.01 or abs(positions[j]) <= 0.01:
                first_short = j
                break

        delay = first_short - start if first_short else -1
        start_price = close[start]
        short_price = close[first_short] if first_short else 0
        price_change = (short_price / start_price - 1) * 100 if first_short else 0

        start_date = prices.index[start].strftime('%Y-%m-%d')
        short_date = prices.index[first_short].strftime('%Y-%m-%d') if first_short else "N/A"

        print(f"    #{idx+1} 熊市开始: {start_date} (价格{start_price:.0f})")
        print(f"        策略减仓/做空: {short_date} (价格{short_price:.0f})")
        print(f"        延迟: {delay}天, 期间跌幅: {price_change:.2f}%")

    # === 3. 趋势过滤代价 ===
    print(f"\n--- 3. 趋势过滤代价分析 ---")
    stats = strategy.get_stats()
    filter_blocks = stats.get("trend_filter_blocks", 0)
    print(f"  趋势过滤拦截次数: {filter_blocks}")

    # === 4. 仓位与收益的时间分布 ===
    print(f"\n--- 4. 收益时间分布 ---")

    # 按年统计
    yearly_data = []
    for year in range(prices.index[0].year, prices.index[-1].year + 1):
        year_mask = prices.index.year == year
        if year_mask.sum() < 10:
            continue

        year_mask_arr = year_mask.values if hasattr(year_mask, 'values') else year_mask
        year_pos = positions[year_mask_arr]
        year_ret = daily_ret[year_mask_arr]
        year_strategy = year_pos[:-1] * year_ret[1:]
        year_strat_ret = ((1 + pd.Series(year_strategy)).prod() - 1) * 100

        year_close = close[year_mask_arr]
        year_bh = (year_close[-1] / year_close[0] - 1) * 100

        year_long = (year_pos > 0.01).sum()
        year_short = (year_pos < -0.01).sum()
        year_flat = (np.abs(year_pos) <= 0.01).sum()
        year_total = year_mask_arr.sum()

        yearly_data.append({
            "year": year,
            "bh": year_bh,
            "strategy": year_strat_ret,
            "long_pct": year_long / year_total * 100,
            "short_pct": year_short / year_total * 100,
            "flat_pct": year_flat / year_total * 100,
        })

    print(f"  {'年份':>6} {'买入持有':>10} {'策略':>10} {'差距':>10} | {'多头%':>6} {'空头%':>6} {'空仓%':>6}")
    print(f"  {'-'*70}")
    for yd in yearly_data:
        gap = yd["strategy"] - yd["bh"]
        print(f"  {yd['year']:>6} {yd['bh']:>+9.2f}% {yd['strategy']:>+9.2f}% {gap:>+9.2f}pp | "
              f"{yd['long_pct']:>5.1f}% {yd['short_pct']:>5.1f}% {yd['flat_pct']:>5.1f}%")

    # === 5. 关键时段分析 ===
    print(f"\n--- 5. 关键问题定位 ---")

    # 找到买入持有涨幅最大的时段，看策略在做什么
    rolling_bh = pd.Series(close).pct_change(periods=90).rolling(window=90).mean()
    best_period = rolling_bh.idxmax()
    if best_period and best_period < n:
        start_idx = max(0, best_period - 90)
        end_idx = min(n, best_period + 90)
        period_bh = (close[end_idx-1] / close[start_idx] - 1) * 100
        period_pos = positions[start_idx:end_idx]
        period_ret = daily_ret[start_idx:end_idx]
        period_strat = ((1 + pd.Series(period_pos[:-1] * period_ret[1:])).prod() - 1) * 100
        period_long = (period_pos > 0.01).sum()
        period_flat = (np.abs(period_pos) <= 0.01).sum()

        start_date = prices.index[start_idx].strftime('%Y-%m-%d')
        end_date = prices.index[end_idx-1].strftime('%Y-%m-%d')
        print(f"  最佳90天窗口: {start_date} ~ {end_date}")
        print(f"    买入持有: {period_bh:+.2f}%")
        print(f"    策略收益: {period_strat:+.2f}%")
        print(f"    多头: {period_long}天 空仓: {period_flat}天")

    # 空仓时间统计
    total_flat = (np.abs(positions) <= 0.01).sum()
    total_long = (positions > 0.01).sum()
    total_short = (positions < -0.01).sum()
    print(f"\n  总体仓位分布:")
    print(f"    多头: {total_long}天 ({total_long/n*100:.1f}%)")
    print(f"    空头: {total_short}天 ({total_short/n*100:.1f}%)")
    print(f"    空仓: {total_flat}天 ({total_flat/n*100:.1f}%)")

    # 空仓期间的涨幅
    flat_mask = np.abs(positions) <= 0.01
    if flat_mask.sum() > 0:
        flat_ret = daily_ret[flat_mask]
        flat_bh = ((1 + pd.Series(flat_ret)).prod() - 1) * 100
        print(f"    空仓期间买入持有收益: {flat_bh:+.2f}%")
        print(f"    → 空仓错过了{flat_bh:+.2f}%的涨幅" if flat_bh > 0 else f"    → 空仓避开了{abs(flat_bh):.2f}%的跌幅")

    return {
        "symbol": name,
        "bh_return": bh_ret,
        "strategy_return": strat_ret,
        "gap": bh_ret - strat_ret,
        "total_long_pct": total_long / n * 100,
        "total_short_pct": total_short / n * 100,
        "total_flat_pct": total_flat / n * 100,
    }


def main():
    print("=" * 80)
    print("  策略 vs 买入持有：深度差距分析")
    print("=" * 80)

    symbols = [("BTC-USDT", "BTC"), ("ETH-USDT", "ETH")]

    all_results = []
    for inst_id, name in symbols:
        prices = fetch_real_data(inst_id, days=730)
        if prices.empty:
            continue
        r = analyze_symbol(name, prices)
        all_results.append(r)

    print(f"\n\n{'='*80}")
    print(f"  核心问题总结")
    print(f"{'='*80}")

    for r in all_results:
        print(f"\n  {r['symbol']}:")
        print(f"    买入持有: {r['bh_return']:+.2f}%")
        print(f"    策略:     {r['strategy_return']:+.2f}%")
        print(f"    差距:     {r['gap']:+.2f}pp")
        print(f"    多头时间: {r['total_long_pct']:.1f}%")
        print(f"    空仓时间: {r['total_flat_pct']:.1f}%")
        print(f"    空仓错过涨幅是核心原因" if r['total_flat_pct'] > 30 else "")


if __name__ == "__main__":
    main()
