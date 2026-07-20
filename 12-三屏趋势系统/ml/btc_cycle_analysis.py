"""BTC 4年周期历史统计分析

目标：
    统计比特币历次周期的关键数据，为构建周期性趋势预测特征提供依据

统计内容：
    1. 历次减半时间点
    2. 历次周期高点（价格、时间、距减半年数）
    3. 历次周期低点（价格、时间、距高点月数、距减半年数）
    4. 高点→低点的跌幅、时间、市值变化
    5. 低点→下次减半的时间
    6. 周期规律总结

数据源：BTC_1D_730d.json（2017-10 ~ 2026-07，3202天）
"""

import json
import os
import sys
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


# 比特币减半历史时间点
BTC_HALVING_DATES = [
    pd.Timestamp("2012-11-28"),
    pd.Timestamp("2016-07-09"),
    pd.Timestamp("2020-05-11"),
    pd.Timestamp("2024-04-20"),
]

# 已知历史周期关键点（补充数据，因数据从2017-10开始，2012年周期缺失）
# 来源：公开历史数据
HISTORICAL_CYCLES = [
    {
        "cycle": 1,  # 第1周期
        "halving_date": "2012-11-28",
        "peak_date": "2013-12-04",
        "peak_price": 1151.0,
        "bottom_date": "2015-01-14",
        "bottom_price": 171.0,
    },
    {
        "cycle": 2,  # 第2周期
        "halving_date": "2016-07-09",
        "peak_date": "2017-12-17",
        "peak_price": 19666.0,
        "bottom_date": "2018-12-15",
        "bottom_price": 3122.0,
    },
    {
        "cycle": 3,  # 第3周期
        "halving_date": "2020-05-11",
        "peak_date": "2021-11-10",
        "peak_price": 69000.0,
        "bottom_date": "2022-11-21",
        "bottom_price": 15500.0,
    },
    {
        "cycle": 4,  # 第4周期（进行中）
        "halving_date": "2024-04-20",
        "peak_date": None,  # 尚未确定
        "peak_price": None,
        "bottom_date": None,
        "bottom_price": None,
    },
]


def load_btc_data() -> pd.DataFrame:
    """加载 BTC 日线数据"""
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )
    return prices


def find_local_extremum(prices: pd.DataFrame, start_date: str, end_date: str, mode: str = "max"):
    """在指定时间段内寻找极值点

    Args:
        prices: 日线数据
        start_date: 开始日期
        end_date: 结束日期
        mode: 'max' 找最高点，'min' 找最低点

    Returns:
        (date, price) 极值日期和价格
    """
    mask = (prices.index >= pd.Timestamp(start_date)) & (prices.index <= pd.Timestamp(end_date))
    segment = prices.loc[mask]
    if len(segment) == 0:
        return None, None
    if mode == "max":
        idx = segment["high"].idxmax()
        price = segment.loc[idx, "high"]
    else:
        idx = segment["low"].idxmin()
        price = segment.loc[idx, "low"]
    return idx, price


def analyze_cycles(prices: pd.DataFrame):
    """分析历次BTC周期"""
    print("=" * 80)
    print("  BTC 4年周期历史统计分析")
    print("=" * 80)

    print("\n【1. 历次周期关键数据】")
    print("  {:>6} | {:>12} | {:>12} | {:>10} | {:>12} | {:>10} | {:>10} | {:>10}".format(
        "周期", "减半日期", "顶部日期", "顶价($)", "底部日期", "底价($)", "顶→底月", "跌幅%"))
    print("  {} | {} | {} | {} | {} | {} | {} | {}".format(
        "-"*6, "-"*12, "-"*12, "-"*10, "-"*12, "-"*10, "-"*10, "-"*10))

    cycle_stats = []
    for cyc in HISTORICAL_CYCLES:
        halving = pd.Timestamp(cyc["halving_date"])

        if cyc["peak_date"] is None:
            # 第4周期，从数据中找当前高点
            # 限定在减半后0-24个月内
            search_end = halving + pd.DateOffset(months=24)
            if search_end > prices.index[-1]:
                search_end = prices.index[-1]
            peak_date, peak_price = find_local_extremum(
                prices, cyc["halving_date"], str(search_end.date()), "max"
            )
            bottom_date, bottom_price = None, None
            peak_to_bottom_months = None
            drawdown_pct = None
            status = "进行中"
        else:
            peak_date = pd.Timestamp(cyc["peak_date"])
            peak_price = cyc["peak_price"]
            bottom_date = pd.Timestamp(cyc["bottom_date"])
            bottom_price = cyc["bottom_price"]
            peak_to_bottom_months = (bottom_date - peak_date).days / 30.44
            drawdown_pct = (peak_price - bottom_price) / peak_price * 100
            status = "已完成"

        # 距减半年数
        if peak_date is not None:
            peak_after_halving_months = (peak_date - halving).days / 30.44
        else:
            peak_after_halving_months = None

        if bottom_date is not None:
            bottom_after_halving_months = (bottom_date - halving).days / 30.44
            bottom_after_peak_months = peak_to_bottom_months
        else:
            bottom_after_halving_months = None
            bottom_after_peak_months = None

        cycle_stats.append({
            "cycle": cyc["cycle"],
            "halving_date": halving,
            "peak_date": peak_date,
            "peak_price": peak_price,
            "bottom_date": bottom_date,
            "bottom_price": bottom_price,
            "peak_after_halving_months": peak_after_halving_months,
            "bottom_after_halving_months": bottom_after_halving_months,
            "peak_to_bottom_months": peak_to_bottom_months,
            "drawdown_pct": drawdown_pct,
            "status": status,
        })

        if peak_date is not None:
            peak_str = str(peak_date.date())
            peak_price_str = "${:,.0f}".format(peak_price)
        else:
            peak_str = "N/A"
            peak_price_str = "N/A"

        if bottom_date is not None:
            bottom_str = str(bottom_date.date())
            bottom_price_str = "${:,.0f}".format(bottom_price)
            ptb_str = "{:.1f}".format(peak_to_bottom_months)
            dd_str = "-{:.1f}%".format(drawdown_pct)
        else:
            bottom_str = "N/A"
            bottom_price_str = "N/A"
            ptb_str = "N/A"
            dd_str = "N/A"

        print("  {:>6} | {:>12} | {:>12} | {:>10} | {:>12} | {:>10} | {:>10} | {:>10}".format(
            cyc["cycle"], str(halving.date()), peak_str, peak_price_str,
            bottom_str, bottom_price_str, ptb_str, dd_str))

    # 2. 周期规律统计
    print("\n【2. 周期规律统计】")

    completed = [c for c in cycle_stats if c["status"] == "已完成"]
    if len(completed) >= 2:
        peak_months = [c["peak_after_halving_months"] for c in completed]
        bottom_months = [c["bottom_after_halving_months"] for c in completed]
        ptb_months = [c["peak_to_bottom_months"] for c in completed]
        drawdowns = [c["drawdown_pct"] for c in completed]

        print("  减半→顶部 月数: {} | 平均 {:.1f} | 范围 {:.1f}-{:.1f}".format(
            ["{:.1f}".format(m) for m in peak_months], np.mean(peak_months),
            min(peak_months), max(peak_months)))
        print("  减半→底部 月数: {} | 平均 {:.1f} | 范围 {:.1f}-{:.1f}".format(
            ["{:.1f}".format(m) for m in bottom_months], np.mean(bottom_months),
            min(bottom_months), max(bottom_months)))
        print("  顶部→底部 月数: {} | 平均 {:.1f} | 范围 {:.1f}-{:.1f}".format(
            ["{:.1f}".format(m) for m in ptb_months], np.mean(ptb_months),
            min(ptb_months), max(ptb_months)))
        print("  顶部→底部 跌幅: {} | 平均 {:.1f}% | 范围 {:.1f}%-{:.1f}%".format(
            ["-{:.1f}%".format(d) for d in drawdowns], np.mean(drawdowns),
            min(drawdowns), max(drawdowns)))

        # 底部→下次减半
        print("\n  底部→下次减半 月数:")
        for i, c in enumerate(completed):
            if i + 1 < len(BTC_HALVING_DATES):
                next_halving = BTC_HALVING_DATES[c["cycle"]]  # cycle是1-based，下一个是cycle索引
                months = (next_halving - c["bottom_date"]).days / 30.44
                print("    周期{}: 底部{} → 下次减半{} = {:.1f}月".format(
                    c["cycle"], str(c["bottom_date"].date()),
                    str(next_halving.date()), months))

    # 3. 第4周期当前状态
    print("\n【3. 第4周期当前状态（截至 {}）】".format(str(prices.index[-1].date())))
    current = cycle_stats[-1]
    current_date = prices.index[-1]
    months_after_halving = (current_date - current["halving_date"]).days / 30.44
    print("  减半日期: {}".format(str(current["halving_date"].date())))
    print("  当前日期: {}".format(str(current_date.date())))
    print("  减半后月数: {:.1f}".format(months_after_halving))
    if current["peak_date"] is not None:
        print("  当前周期高点: ${:,.0f} ({})".format(
            current["peak_price"], str(current["peak_date"].date())))
        print("  距高点月数: {:.1f}".format((current_date - current["peak_date"]).days / 30.44))

        # 从高点回撤
        current_price = prices["close"].iloc[-1]
        drawdown_from_peak = (current["peak_price"] - current_price) / current["peak_price"] * 100
        print("  当前价格: ${:,.0f}".format(current_price))
        print("  从高点回撤: -{:.1f}%".format(drawdown_from_peak))

        # 历史规律推断
        if len(completed) >= 2:
            avg_ptb = np.mean([c["peak_to_bottom_months"] for c in completed])
            avg_dd = np.mean([c["drawdown_pct"] for c in completed])
            predicted_bottom_date = current["peak_date"] + pd.DateOffset(months=int(avg_ptb))
            predicted_bottom_price = current["peak_price"] * (1 - avg_dd / 100)
            print("\n  基于历史规律推断:")
            print("    预测底部日期: ~{} (顶后{:.1f}月)".format(
                str(predicted_bottom_date.date()), avg_ptb))
            print("    预测底部价格: ~${:,.0f} (跌幅{:.1f}%)".format(
                predicted_bottom_price, avg_dd))

    # 4. 市值变化分析（用成交量作为市值代理）
    print("\n【4. 成交量变化与周期关系】")
    print("  (使用30日平均成交量作为活跃度代理)")

    # 按周期分段统计成交量
    for i, cyc in enumerate(cycle_stats):
        halving = cyc["halving_date"]
        if i + 1 < len(BTC_HALVING_DATES):
            next_halving = BTC_HALVING_DATES[i + 1]
        else:
            next_halving = prices.index[-1]

        mask = (prices.index >= halving) & (prices.index < next_halving)
        segment = prices.loc[mask]
        if len(segment) > 0:
            vol_ma30 = segment["volume"].rolling(30).mean()
            peak_vol = vol_ma30.max()
            peak_vol_date = vol_ma30.idxmax()
            trough_vol = vol_ma30.min()
            trough_vol_date = vol_ma30.idxmin()
            print("  周期{} ({}~{}):".format(
                cyc["cycle"], str(halving.date()), str(next_halving.date())[:10]))
            print("    成交量峰值: {:,.0f} ({})".format(peak_vol, str(peak_vol_date.date())))
            print("    成交量谷值: {:,.0f} ({})".format(trough_vol, str(trough_vol_date.date())))
            print("    量能比: {:.1f}x".format(peak_vol / trough_vol if trough_vol > 0 else 0))

    # 5. 特征设计建议
    print("\n【5. 基于历史统计的特征设计建议】")
    print("  ┌─────────────────────────────────────────────────────────────┐")
    print("  │ 周期性趋势预测特征设计                                       │")
    print("  ├─────────────────────────────────────────────────────────────┤")
    print("  │ 1. cycle_phase: 周期阶段 (4维 one-hot)                      │")
    print("  │    - accumulation: 减半前12个月                              │")
    print("  │    - bull_run: 减半后0-12个月                                │")
    print("  │    - peak_warning: 减半后12-18个月                           │")
    print("  │    - bear_market: 减半后18-36个月（预计顶到底）              │")
    print("  │                                                              │")
    print("  │ 2. months_to_predicted_bottom: 距预测底部月数                │")
    print("  │    基于历史平均顶到底时间推断                                │")
    print("  │                                                              │")
    print("  │ 3. drawdown_from_cycle_peak: 距周期高点回撤%                 │")
    print("  │    用于判断是否进入熊市阶段                                  │")
    print("  │                                                              │")
    print("  │ 4. bear_progress_pct: 熊市进度%                              │")
    print("  │    (当前价-顶部)/(底部-顶部)，0=顶部 100=底部               │")
    print("  │                                                              │")
    print("  │ 5. volume_cycle_position: 成交量周期位置                     │")
    print("  │    当前30日均量 / 周期内峰值量                              │")
    print("  └─────────────────────────────────────────────────────────────┘")

    # 保存统计结果
    result = {
        "analysis_date": str(prices.index[-1].date()),
        "cycles": [],
    }
    for c in cycle_stats:
        result["cycles"].append({
            "cycle": c["cycle"],
            "halving_date": str(c["halving_date"].date()),
            "peak_date": str(c["peak_date"].date()) if c["peak_date"] is not None else None,
            "peak_price": c["peak_price"],
            "bottom_date": str(c["bottom_date"].date()) if c["bottom_date"] is not None else None,
            "bottom_price": c["bottom_price"],
            "peak_after_halving_months": c["peak_after_halving_months"],
            "bottom_after_halving_months": c["bottom_after_halving_months"],
            "peak_to_bottom_months": c["peak_to_bottom_months"],
            "drawdown_pct": c["drawdown_pct"],
            "status": c["status"],
        })

    if len(completed) >= 2:
        result["cycle_patterns"] = {
            "peak_after_halving_months": {
                "values": [c["peak_after_halving_months"] for c in completed],
                "mean": float(np.mean([c["peak_after_halving_months"] for c in completed])),
                "min": float(min([c["peak_after_halving_months"] for c in completed])),
                "max": float(max([c["peak_after_halving_months"] for c in completed])),
            },
            "bottom_after_halving_months": {
                "values": [c["bottom_after_halving_months"] for c in completed],
                "mean": float(np.mean([c["bottom_after_halving_months"] for c in completed])),
                "min": float(min([c["bottom_after_halving_months"] for c in completed])),
                "max": float(max([c["bottom_after_halving_months"] for c in completed])),
            },
            "peak_to_bottom_months": {
                "values": [c["peak_to_bottom_months"] for c in completed],
                "mean": float(np.mean([c["peak_to_bottom_months"] for c in completed])),
                "min": float(min([c["peak_to_bottom_months"] for c in completed])),
                "max": float(max([c["peak_to_bottom_months"] for c in completed])),
            },
            "drawdown_pct": {
                "values": [c["drawdown_pct"] for c in completed],
                "mean": float(np.mean([c["drawdown_pct"] for c in completed])),
                "min": float(min([c["drawdown_pct"] for c in completed])),
                "max": float(max([c["drawdown_pct"] for c in completed])),
            },
        }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/btc_cycle_analysis.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\n结果已保存: {}".format(output_path))

    return cycle_stats


if __name__ == "__main__":
    prices = load_btc_data()
    print("数据: {}天, {} ~ {}\n".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))
    analyze_cycles(prices)
