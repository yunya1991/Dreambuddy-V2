#!/usr/bin/env python3
"""
经典牛熊指标回测验证框架
- 基线：日线 MA200（价格>MA200做多，<MA200做空）
- 22个指标各自独立回测，跑赢基线的保留为检测器
- 支持合成数据 / OKX 真实历史数据
- 筛选标准：夏普比率、最大回撤、胜率中至少两项优于基线
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统")
from talib import abstract as ta


@dataclass
class BacktestResult:
    name: str
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    num_trades: int
    avg_trade_return: float


OKX_API_URL = "https://www.okx.com/api/v5/market/candles"


def fetch_okx_klines(inst_id: str = "BTC-USDT-SWAP", bar: str = "1D", limit: int = 300) -> pd.DataFrame:
    """从 OKX 获取真实历史 K 线数据"""
    params = {"instId": inst_id, "bar": bar, "limit": limit}
    resp = requests.get(OKX_API_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        raise RuntimeError(f"OKX API error: {data.get('msg')}")
    raw = data["data"]
    df = pd.DataFrame(raw, columns=["ts", "o", "h", "l", "c", "vol", "volCcy", "volCcyQuote", "confirm"])
    df = df.iloc[::-1].reset_index(drop=True)  # 按时间正序排列
    df["ts"] = pd.to_numeric(df["ts"])
    for col in ["o", "h", "l", "c", "vol"]:
        df[col] = pd.to_numeric(df[col])
    df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}, inplace=True)
    return df


def fetch_okx_history(inst_id: str = "BTC-USDT-SWAP", bar: str = "1D", total_bars: int = 500) -> pd.DataFrame:
    """分页获取 OKX 历史 K 线数据"""
    all_dfs = []
    before_ts = None
    remaining = total_bars
    while remaining > 0:
        limit = min(300, remaining)
        params = {"instId": inst_id, "bar": bar, "limit": limit}
        if before_ts:
            params["before"] = before_ts
        resp = requests.get(OKX_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0" or not data.get("data"):
            break
        raw = data["data"]
        df = pd.DataFrame(raw, columns=["ts", "o", "h", "l", "c", "vol", "volCcy", "volCcyQuote", "confirm"])
        df = df.iloc[::-1].reset_index(drop=True)
        for col in ["o", "h", "l", "c", "vol"]:
            df[col] = pd.to_numeric(df[col])
        df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}, inplace=True)
        all_dfs.append(df)
        before_ts = str(int(raw[-1][0]))  # 最早一根K线的时间戳
        remaining -= len(raw)
        if len(raw) < limit:
            break
        time.sleep(0.1)  # 避免限流
    if not all_dfs:
        raise RuntimeError("未能获取任何数据")
    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return combined


def _generate_synthetic_data(n: int = 500, seed: int = 42, freq: str = "daily") -> pd.DataFrame:
    """生成合成K线数据：包含牛市、熊市、震荡三种市场环境
    freq: "daily" 或 "weekly"，weekly 数据点数自动调整为 n/5
    """
    np.random.seed(seed)
    actual_n = n if freq == "daily" else max(1, n // 5)

    # 分段趋势：牛 → 熊 → 震荡 → 牛
    stage_n = actual_n // 4
    trends = []
    for i in range(stage_n):
        trends.append(0.15 + np.random.randn() * 0.8)
    for i in range(stage_n):
        trends.append(-0.15 + np.random.randn() * 0.8)
    for i in range(stage_n):
        trends.append(np.random.randn() * 0.5)
    for i in range(stage_n):
        trends.append(0.12 + np.random.randn() * 0.7)
    # 补齐
    while len(trends) < actual_n:
        trends.append(np.random.randn() * 0.3)

    close = 100 + np.cumsum(trends[:actual_n])
    high = close + np.abs(np.random.randn(actual_n) * 0.4)
    low = close - np.abs(np.random.randn(actual_n) * 0.4)
    open_p = close + np.random.randn(actual_n) * 0.2
    volume = np.ones(actual_n) * 1000 + np.random.randn(actual_n) * 200

    df = pd.DataFrame({
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    return df


def _calc_returns(df: pd.DataFrame, signals: pd.Series) -> Tuple[float, float, float, float, int]:
    """
    根据信号序列计算回测结果
    signals: -1=做空, 0=空仓, 1=做多
    返回: (总收益率%, 夏普比率, 最大回撤%, 胜率, 交易次数)
    """
    returns = df["close"].pct_change().fillna(0)
    strategy_returns = signals.shift(1).fillna(0) * returns
    cumulative = (1 + strategy_returns).cumprod()
    total_return = (cumulative.iloc[-1] - 1) * 100

    # 夏普比率（年化，假设252个交易日）
    if strategy_returns.std() > 0:
        sharpe = (strategy_returns.mean() / strategy_returns.std()) * np.sqrt(252)
    else:
        sharpe = 0.0

    # 最大回撤
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    max_dd = drawdown.min() * 100

    # 交易次数和胜率（按信号变化计算）
    signal_changes = signals.diff().fillna(0).abs()
    trades = signal_changes[signal_changes > 0]
    num_trades = len(trades)

    # 每次交易收益
    trade_returns = []
    in_pos = 0
    entry_price = 0
    for i in range(len(df)):
        if signals.iloc[i] != in_pos:
            if in_pos != 0:
                trade_ret = (df["close"].iloc[i] / entry_price - 1) * in_pos
                trade_returns.append(trade_ret)
            in_pos = signals.iloc[i]
            entry_price = df["close"].iloc[i]
    if in_pos != 0 and len(df) > 0:
        trade_ret = (df["close"].iloc[-1] / entry_price - 1) * in_pos
        trade_returns.append(trade_ret)

    win_rate = (sum(1 for r in trade_returns if r > 0) / len(trade_returns) * 100) if trade_returns else 0
    avg_return = (sum(trade_returns) / len(trade_returns) * 100) if trade_returns else 0

    return total_return, sharpe, max_dd, win_rate, num_trades, avg_return


def _signal_ma200(df: pd.DataFrame) -> pd.Series:
    sma200 = df["close"].rolling(200, min_periods=1).mean()
    return pd.Series(np.where(df["close"] > sma200, 1, -1), index=df.index)


def _signal_ema200(df: pd.DataFrame) -> pd.Series:
    ema200 = ta.EMA(df, timeperiod=200)
    return pd.Series(np.where(df["close"] > ema200, 1, -1), index=df.index)


def _signal_golden_cross(df: pd.DataFrame) -> pd.Series:
    sma50 = df["close"].rolling(50, min_periods=1).mean()
    sma200 = df["close"].rolling(200, min_periods=1).mean()
    return pd.Series(np.where(sma50 > sma200, 1, -1), index=df.index)


def _signal_ema_alignment(df: pd.DataFrame) -> pd.Series:
    ema20 = ta.EMA(df, timeperiod=20)
    ema50 = ta.EMA(df, timeperiod=50)
    ema200 = ta.EMA(df, timeperiod=200)
    bull = (ema20 > ema50) & (ema50 > ema200)
    bear = (ema20 < ema50) & (ema50 < ema200)
    return pd.Series(np.where(bull, 1, np.where(bear, -1, 0)), index=df.index)


def _signal_macd(df: pd.DataFrame) -> pd.Series:
    macd_dict = ta.MACD(df, fastperiod=12, slowperiod=26, signalperiod=9)
    macd_line = macd_dict["macd"]
    signal_line = macd_dict["macdsignal"]
    return pd.Series(np.where(macd_line > signal_line, 1, -1), index=df.index)


def _signal_adx(df: pd.DataFrame) -> pd.Series:
    adx = ta.ADX(df, timeperiod=14)
    pdi = ta.PLUS_DI(df, timeperiod=14)
    mdi = ta.MINUS_DI(df, timeperiod=14)
    strong_trend = adx > 25
    bull = strong_trend & (pdi > mdi)
    bear = strong_trend & (pdi < mdi)
    return pd.Series(np.where(bull, 1, np.where(bear, -1, 0)), index=df.index)


def _signal_rsi(df: pd.DataFrame) -> pd.Series:
    rsi = ta.RSI(df, timeperiod=14)
    return pd.Series(np.where(rsi > 50, 1, -1), index=df.index)


def _signal_bbands(df: pd.DataFrame) -> pd.Series:
    bb = ta.BBANDS(df, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
    mid = bb["middleband"]
    return pd.Series(np.where(df["close"] > mid, 1, -1), index=df.index)


def _signal_sar(df: pd.DataFrame) -> pd.Series:
    sar = ta.SAR(df, acceleration=0.02, maximum=0.2)
    return pd.Series(np.where(df["close"] > sar, 1, -1), index=df.index)


def _signal_willr(df: pd.DataFrame) -> pd.Series:
    willr = ta.WILLR(df, timeperiod=14)
    return pd.Series(np.where(willr > -50, 1, -1), index=df.index)


def _signal_stochrsi(df: pd.DataFrame) -> pd.Series:
    sr = ta.STOCHRSI(df, timeperiod=14, fastk_period=5, fastd_period=3)
    return pd.Series(np.where(sr["fastk"] > sr["fastd"], 1, -1), index=df.index)


def _signal_obv(df: pd.DataFrame) -> pd.Series:
    obv = ta.OBV(df)
    obv_ma = obv.rolling(10, min_periods=1).mean()
    return pd.Series(np.where(obv > obv_ma, 1, -1), index=df.index)


def _signal_supertrend(df: pd.DataFrame) -> pd.Series:
    st = ta.SUPERTREND(df, period=10, multiplier=3.0)
    return pd.Series(st["direction"], index=df.index)


def _signal_ichimoku(df: pd.DataFrame) -> pd.Series:
    ichi = ta.ICHIMOKU(df, tenkan=9, kijun=26, senkou_b=52)
    above = df["close"] > ichi["cloud_top"]
    below = df["close"] < ichi["cloud_bottom"]
    return pd.Series(np.where(above, 1, np.where(below, -1, 0)), index=df.index)


def _signal_keltner(df: pd.DataFrame) -> pd.Series:
    kc = ta.KELTNER(df, ema_period=20, atr_period=10, mult=2.0)
    above = df["close"] > kc["upper"]
    below = df["close"] < kc["lower"]
    return pd.Series(np.where(above, 1, np.where(below, -1, 0)), index=df.index)


def _signal_donchian(df: pd.DataFrame) -> pd.Series:
    dc = ta.DONCHIAN(df, period=20)
    above = df["close"] > dc["upper"]
    below = df["close"] < dc["lower"]
    return pd.Series(np.where(above, 1, np.where(below, -1, 0)), index=df.index)


def _signal_tema(df: pd.DataFrame) -> pd.Series:
    tema = ta.TEMA(df, timeperiod=30)
    return pd.Series(np.where(df["close"] > tema, 1, -1), index=df.index)


def _signal_dmi(df: pd.DataFrame) -> pd.Series:
    pdi = ta.PLUS_DI(df, timeperiod=14)
    mdi = ta.MINUS_DI(df, timeperiod=14)
    return pd.Series(np.where(pdi > mdi, 1, -1), index=df.index)


def _signal_roc(df: pd.DataFrame) -> pd.Series:
    """ROC 变化率"""
    roc = ta.ROC(df, period=10)
    return pd.Series(np.where(roc > 0, 1, -1), index=df.index)


def _signal_aroon(df: pd.DataFrame) -> pd.Series:
    """Aroon 趋势强度"""
    aroon = ta.AROON(df, period=25)
    up = aroon["aroonup"]
    down = aroon["aroondown"]
    return pd.Series(np.where(up > down, 1, -1), index=df.index)


def _signal_vortex(df: pd.DataFrame) -> pd.Series:
    """Vortex 趋势方向"""
    vx = ta.VORTEX(df, period=14)
    return pd.Series(np.where(vx["plus_vi"] > vx["minus_vi"], 1, -1), index=df.index)


def _signal_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP 成交量加权平均价"""
    vwap = ta.VWAP(df)
    return pd.Series(np.where(df["close"] > vwap, 1, -1), index=df.index)


ALL_INDICATORS: List[Tuple[str, Callable]] = [
    ("MA200_EMA", _signal_ma200),
    ("EMA200", _signal_ema200),
    ("GoldenCross_50_200", _signal_golden_cross),
    ("EMA_Align_20_50_200", _signal_ema_alignment),
    ("MACD_Cross", _signal_macd),
    ("ADX_DMI", _signal_adx),
    ("RSI_50", _signal_rsi),
    ("BBands_Mid", _signal_bbands),
    ("Parabolic_SAR", _signal_sar),
    ("Williams_R", _signal_willr),
    ("StochRSI_Cross", _signal_stochrsi),
    ("OBV_Trend", _signal_obv),
    ("SuperTrend", _signal_supertrend),
    ("Ichimoku_Cloud", _signal_ichimoku),
    ("Keltner_Channel", _signal_keltner),
    ("Donchian_Channel", _signal_donchian),
    ("TEMA", _signal_tema),
    ("DMI_Cross", _signal_dmi),
    ("ROC", _signal_roc),
    ("Aroon", _signal_aroon),
    ("Vortex", _signal_vortex),
    ("VWAP", _signal_vwap),
]


def run_backtest(df: pd.DataFrame | None = None, freq: str = "daily") -> Dict[str, BacktestResult]:
    """运行全部指标回测，返回结果字典
    freq: "daily" 或 "weekly"，用于区分回测类型
    """
    if df is None:
        df = _generate_synthetic_data(n=500, freq=freq)

    results: Dict[str, BacktestResult] = {}
    for name, signal_fn in ALL_INDICATORS:
        try:
            signals = signal_fn(df)
            total_ret, sharpe, max_dd, win_rate, num_trades, avg_ret = _calc_returns(df, signals)
            results[name] = BacktestResult(
                name=name,
                total_return_pct=round(total_ret, 2),
                sharpe_ratio=round(sharpe, 3),
                max_drawdown_pct=round(max_dd, 2),
                win_rate=round(win_rate, 1),
                num_trades=num_trades,
                avg_trade_return=round(avg_ret, 3),
            )
        except Exception as e:
            print(f"  ⚠️ {name} ({freq}) 回测失败: {e}")

    return results


def run_daily_vs_weekly_backtest(seed: int = 42) -> Tuple[Dict[str, BacktestResult], Dict[str, BacktestResult]]:
    """同时运行日线和周线回测，返回对比结果"""
    df_daily = _generate_synthetic_data(n=500, seed=seed, freq="daily")
    df_weekly = _generate_synthetic_data(n=500, seed=seed, freq="weekly")
    daily_results = run_backtest(df_daily, freq="daily")
    weekly_results = run_backtest(df_weekly, freq="weekly")
    return daily_results, weekly_results


def evaluate_survivors(results: Dict[str, BacktestResult], baseline_name: str = "MA200_EMA", strict_count: int = 2) -> Tuple[List[str], List[str]]:
    """
    筛选存活指标：夏普比率、最大回撤(绝对值)、胜率中至少 strict_count 项优于基线
    strict_count: 严格度，2=至少2项优于，1=至少1项优于
    返回: (存活指标列表, 淘汰指标列表)
    """
    baseline = results.get(baseline_name)
    if not baseline:
        return list(results.keys()), []

    survivors = []
    eliminated = []

    for name, res in results.items():
        if name == baseline_name:
            continue
        better_count = 0
        if res.sharpe_ratio > baseline.sharpe_ratio:
            better_count += 1
        if abs(res.max_drawdown_pct) < abs(baseline.max_drawdown_pct):
            better_count += 1
        if res.win_rate > baseline.win_rate:
            better_count += 1

        if better_count >= strict_count:
            survivors.append(name)
        else:
            eliminated.append(name)

    return survivors, eliminated


def print_report(results: Dict[str, BacktestResult], baseline_name: str = "MA200_EMA") -> None:
    """打印回测报告"""
    baseline = results.get(baseline_name)
    survivors, eliminated = evaluate_survivors(results, baseline_name)

    print("=" * 100)
    print(f"{'指标名称':<25} {'总收益%':>10} {'夏普':>8} {'最大回撤%':>12} {'胜率%':>8} {'交易次数':>10} {'均收益%':>10} {'状态':>6}")
    print("=" * 100)

    for name, res in sorted(results.items(), key=lambda x: x[1].sharpe_ratio, reverse=True):
        status = "✅基线" if name == baseline_name else ("✅存活" if name in survivors else "❌淘汰")
        print(f"{res.name:<25} {res.total_return_pct:>10.2f} {res.sharpe_ratio:>8.3f} {res.max_drawdown_pct:>12.2f} {res.win_rate:>8.1f} {res.num_trades:>10} {res.avg_trade_return:>10.3f} {status:>6}")

    print("=" * 100)
    print(f"\n基线: {baseline_name}")
    print(f"存活指标 ({len(survivors)}个): {', '.join(survivors)}")
    print(f"淘汰指标 ({len(eliminated)}个): {', '.join(eliminated)}")
    print(f"\n筛选标准: 夏普比率、最大回撤(绝对值)、胜率 中至少两项优于基线")


def print_daily_vs_weekly_report(daily_results: Dict[str, BacktestResult], weekly_results: Dict[str, BacktestResult], baseline_name: str = "MA200_EMA", top_n: int = 5) -> Tuple[List[str], List[str]]:
    """
    打印日线 vs 周线对比报告，筛选周线组(Screen1)和日线组(Screen2)
    每组按夏普比率取前 top_n 个
    返回: (周线组指标列表, 日线组指标列表)
    """
    # Screen1 用严格筛选（2项优于基线）
    weekly_survivors, _ = evaluate_survivors(weekly_results, baseline_name, strict_count=2)
    # Screen2 放宽到1项优于基线（因为日线指标整体偏弱）
    daily_survivors, _ = evaluate_survivors(daily_results, baseline_name, strict_count=1)

    # 合并存活指标（去重）
    all_survivors = sorted(set(daily_survivors + weekly_survivors))

    print("=" * 120)
    print(f"{'指标名称':<25} {'日线夏普':>10} {'周线夏普':>10} {'日线回撤%':>12} {'周线回撤%':>12} {'日线胜率':>10} {'周线胜率':>10} {'推荐':>12}")
    print("=" * 120)

    # 分离日线/周线更优的指标
    weekly_better_list = []
    daily_better_list = []
    for name in all_survivors:
        d = daily_results.get(name)
        w = weekly_results.get(name)
        if not d or not w:
            continue
        weekly_better = (w.sharpe_ratio > d.sharpe_ratio) or (abs(w.max_drawdown_pct) < abs(d.max_drawdown_pct))
        if weekly_better:
            weekly_better_list.append((name, w, d))
        else:
            daily_better_list.append((name, w, d))
        print(f"{name:<25} {d.sharpe_ratio:>10.3f} {w.sharpe_ratio:>10.3f} {d.max_drawdown_pct:>12.2f} {w.max_drawdown_pct:>12.2f} {d.win_rate:>10.1f} {w.win_rate:>10.1f} {'Screen1(周线)' if weekly_better else 'Screen2(日线)':>12}")

    # 按夏普排序取前5
    weekly_better_list.sort(key=lambda x: x[1].sharpe_ratio, reverse=True)
    daily_better_list.sort(key=lambda x: x[2].sharpe_ratio, reverse=True)
    screen1_indicators = [x[0] for x in weekly_better_list[:top_n]]
    screen2_indicators = [x[0] for x in daily_better_list[:top_n]]

    print("=" * 120)
    print(f"\n【Screen1 周线组 TOP{top_n}】: {screen1_indicators}")
    print(f"【Screen2 日线组 TOP{top_n}】: {screen2_indicators}")
    print(f"\n筛选标准:")
    print(f"  - Screen1 周线组: 2项优于SMA200（夏普/回撤/胜率）")
    print(f"  - Screen2 日线组: 1项优于SMA200（夏普/回撤/胜率）")
    print(f"\n权重分配: 周线 60% / 日线 40%")
    print(f"\n置信度计算公式:")
    print(f"  - 单一指标命中可信度: 50%")
    print(f"  - 多个指标共振: 50% + N×10% (N=同向指标数)")
    print(f"  - Screen1(周线)置信度 = 50 + bull_count_weekly * 10")
    print(f"  - Screen2(日线)置信度 = 50 + bull_count_daily * 10")
    print(f"  - 综合置信度 = Screen1×0.6 + Screen2×0.4")

    return screen1_indicators, screen2_indicators


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="经典牛熊指标回测验证")
    parser.add_argument("--mode", choices=["daily", "weekly", "compare"], default="compare", help="回测模式")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--real", action="store_true", help="使用 OKX 真实历史数据")
    parser.add_argument("--inst", type=str, default="BTC-USDT-SWAP", help="交易对（仅--real时有效）")
    parser.add_argument("--bars", type=int, default=500, help="获取的K线数量（仅--real时有效）")
    args = parser.parse_args()

    if args.mode == "compare":
        if args.real:
            print(f"🔄 从 OKX 获取真实历史数据 ({args.inst})...")
            df_daily = fetch_okx_history(args.inst, "1D", args.bars)
            df_weekly = fetch_okx_history(args.inst, "1W", args.bars // 5)
            print(f"   日线: {len(df_daily)} 根, 周线: {len(df_weekly)} 根")
            print(f"   日线区间: {df_daily['ts'].iloc[0]} → {df_daily['ts'].iloc[-1]}")
            print(f"   周线区间: {df_weekly['ts'].iloc[0]} → {df_weekly['ts'].iloc[-1]}")
            daily_results = run_backtest(df_daily, freq="daily")
            weekly_results = run_backtest(df_weekly, freq="weekly")
        else:
            print("🔄 生成日线 + 周线合成数据（牛→熊→震荡→牛）...")
            daily_results, weekly_results = run_daily_vs_weekly_backtest(seed=args.seed)
        print()
        print("【日线回测结果】")
        print_report(daily_results)
        print()
        print("【周线回测结果】")
        print_report(weekly_results, baseline_name="MA200_EMA")
        print()
        print("【日线 vs 周线对比 - Screen1/Screen2 分组】")
        screen1, screen2 = print_daily_vs_weekly_report(daily_results, weekly_results)
    elif args.mode == "daily":
        if args.real:
            print(f"🔄 从 OKX 获取日线数据 ({args.inst})...")
            df = fetch_okx_history(args.inst, "1D", args.bars)
        else:
            print("🔄 运行日线回测（合成数据）...")
            df = _generate_synthetic_data(n=500, seed=args.seed, freq="daily")
        results = run_backtest(df, freq="daily")
        print_report(results)
    elif args.mode == "weekly":
        if args.real:
            print(f"🔄 从 OKX 获取周线数据 ({args.inst})...")
            df = fetch_okx_history(args.inst, "1W", args.bars // 5)
        else:
            print("🔄 运行周线回测（合成数据）...")
            df = _generate_synthetic_data(n=500, seed=args.seed, freq="weekly")
        results = run_backtest(df, freq="weekly")
        print_report(results)
