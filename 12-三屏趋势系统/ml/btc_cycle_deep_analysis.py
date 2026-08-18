"""BTC 4年周期深度分析：累计跌幅 + 市值变化 + 周期相似性

扩展分析：
1. 顶到底的分段累计跌幅（每月跌幅曲线）
2. 顶到底的市值（成交量代理）变化曲线
3. 4年周期相似性：当前周期 vs 历史周期同阶段对比
4. 构建"周期相似度"特征，用于趋势预测

数据源：BTC_1D_730d.json（2017-10 ~ 2026-07）
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

# 历史周期关键点（基于公开数据 + 数据库验证）
HISTORICAL_CYCLES = [
    {
        "cycle": 1,
        "halving_date": "2012-11-28",
        "peak_date": "2013-12-04",
        "peak_price": 1151.0,
        "bottom_date": "2015-01-14",
        "bottom_price": 171.0,
    },
    {
        "cycle": 2,
        "halving_date": "2016-07-09",
        "peak_date": "2017-12-17",
        "peak_price": 19666.0,
        "bottom_date": "2018-12-15",
        "bottom_price": 3122.0,
    },
    {
        "cycle": 3,
        "halving_date": "2020-05-11",
        "peak_date": "2021-11-10",
        "peak_price": 69000.0,
        "bottom_date": "2022-11-21",
        "bottom_price": 15500.0,
    },
    {
        "cycle": 4,
        "halving_date": "2024-04-20",
        "peak_date": None,
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
    """在指定时间段内寻找极值点"""
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


def compute_peak_to_bottom_path(prices: pd.DataFrame, peak_date, bottom_date) -> pd.DataFrame:
    """计算顶到底的价格路径（每月采样）"""
    start = pd.Timestamp(peak_date)
    end = pd.Timestamp(bottom_date)
    mask = (prices.index >= start) & (prices.index <= end)
    segment = prices.loc[mask]
    if len(segment) == 0:
        return pd.DataFrame()

    peak_price = segment["high"].iloc[0] if "high" in segment.columns else segment["close"].iloc[0]
    # 使用峰值当天的最高价
    peak_price = segment["high"].max()
    peak_idx = segment["high"].idxmax()

    # 重新切片从峰值开始
    mask2 = (prices.index >= peak_idx) & (prices.index <= end)
    segment = prices.loc[mask2]
    if len(segment) == 0:
        return pd.DataFrame()

    # 按月重采样，取月末收盘价
    monthly = segment["close"].resample("ME").last()
    if len(monthly) == 0:
        return pd.DataFrame()

    # 计算累计跌幅%
    path = pd.DataFrame({
        "close": monthly.values,
        "months_after_peak": range(len(monthly)),
    })
    path["drawdown_pct"] = (path["close"] - peak_price) / peak_price * 100
    return path


def compute_volume_path(prices: pd.DataFrame, peak_date, bottom_date) -> pd.DataFrame:
    """计算顶到底的成交量路径（30日均量，按月采样）"""
    start = pd.Timestamp(peak_date)
    end = pd.Timestamp(bottom_date)
    mask = (prices.index >= start) & (prices.index <= end)
    segment = prices.loc[mask]
    if len(segment) == 0:
        return pd.DataFrame()

    # 30日均量
    vol_ma30 = segment["volume"].rolling(30, min_periods=1).mean()

    # 峰值量
    peak_vol = vol_ma30.max()
    peak_idx = vol_ma30.idxmax()

    # 从量能峰值开始的路径（使用segment的索引，避免长度不匹配）
    mask2 = (vol_ma30.index >= peak_idx) & (vol_ma30.index <= end)
    vol_segment = vol_ma30.loc[mask2]

    # 按月重采样
    monthly_vol = vol_segment.resample("ME").last()
    if len(monthly_vol) == 0:
        return pd.DataFrame()

    path = pd.DataFrame({
        "vol_ma30": monthly_vol.values,
        "months_after_peak": range(len(monthly_vol)),
    })
    if peak_vol > 0:
        path["vol_change_pct"] = (path["vol_ma30"] - peak_vol) / peak_vol * 100
    else:
        path["vol_change_pct"] = 0.0
    return path


def analyze_cycle_similarity(prices: pd.DataFrame):
    """4年周期相似性分析"""
    print("=" * 80)
    print("  BTC 4年周期深度分析：累计跌幅 + 市值变化 + 周期相似性")
    print("=" * 80)

    # 1. 顶到底的分段累计跌幅
    print("\n【1. 历次周期顶到底的分段累计跌幅】")
    print("  (按月采样，相对峰值价格的累计跌幅%)")
    print()
    print("  {:>6} | {:>30}".format("月份", "周期1 / 周期2 / 周期3"))
    print("  {} | {}".format("-"*6, "-"*30))

    paths_drawdown = {}
    for cyc in HISTORICAL_CYCLES[:3]:  # 前3个完整周期
        if cyc["peak_date"] is None:
            continue
        path = compute_peak_to_bottom_path(prices, cyc["peak_date"], cyc["bottom_date"])
        if len(path) > 0:
            paths_drawdown[cyc["cycle"]] = path

    max_months = max(len(p) for p in paths_drawdown.values()) if paths_drawdown else 0
    for m in range(min(max_months, 15)):  # 显示前15个月
        vals = []
        for cyc_id in [1, 2, 3]:
            if cyc_id in paths_drawdown and m < len(paths_drawdown[cyc_id]):
                v = paths_drawdown[cyc_id]["drawdown_pct"].iloc[m]
                vals.append("{:+.1f}%".format(v))
            else:
                vals.append("N/A")
        print("  {:>6} | {:>30}".format(m, " / ".join(vals)))

    # 统计每月平均跌幅
    print()
    print("  月度平均跌幅曲线（3轮周期均值）:")
    avg_drawdowns = []
    for m in range(min(max_months, 15)):
        vals = []
        for cyc_id in [1, 2, 3]:
            if cyc_id in paths_drawdown and m < len(paths_drawdown[cyc_id]):
                vals.append(paths_drawdown[cyc_id]["drawdown_pct"].iloc[m])
        if vals:
            avg = np.mean(vals)
            avg_drawdowns.append(avg)
            print("    月{:>2}: 平均 {:+.1f}% (范围 {:+.1f}% ~ {:+.1f}%)".format(
                m, avg, min(vals), max(vals)))

    # 2. 成交量（市值代理）变化
    print("\n【2. 历次周期顶到底的成交量变化】")
    print("  (30日均量，相对量能峰值的变化%)")
    print()
    print("  {:>6} | {:>30}".format("月份", "周期1 / 周期2 / 周期3"))
    print("  {} | {}".format("-"*6, "-"*30))

    paths_vol = {}
    for cyc in HISTORICAL_CYCLES[:3]:
        if cyc["peak_date"] is None:
            continue
        path = compute_volume_path(prices, cyc["peak_date"], cyc["bottom_date"])
        if len(path) > 0:
            paths_vol[cyc["cycle"]] = path

    max_months_vol = max(len(p) for p in paths_vol.values()) if paths_vol else 0
    avg_vol_changes = []
    for m in range(min(max_months_vol, 15)):
        vals = []
        for cyc_id in [1, 2, 3]:
            if cyc_id in paths_vol and m < len(paths_vol[cyc_id]):
                vals.append(paths_vol[cyc_id]["vol_change_pct"].iloc[m])
        if vals:
            avg = np.mean(vals)
            avg_vol_changes.append(avg)
            print("  {:>6} | {:>30}".format(
                m,
                " / ".join(["{:+.1f}%".format(v) if not np.isnan(v) else "N/A" for v in vals])))

    # 3. 周期相似性：当前周期 vs 历史周期
    print("\n【3. 当前周期（第4周期）与历史周期相似性】")
    print("  (从各自周期峰值开始的累计跌幅路径对比)")

    # 找当前周期峰值（减半后0-24个月内）
    current_halving = pd.Timestamp("2024-04-20")
    search_end = current_halving + pd.DateOffset(months=24)
    if search_end > prices.index[-1]:
        search_end = prices.index[-1]
    current_peak_date, current_peak_price = find_local_extremum(
        prices, str(current_halving.date()), str(search_end.date()), "max"
    )

    if current_peak_date is not None:
        current_date = prices.index[-1]
        months_since_peak = (current_date - current_peak_date).days / 30.44
        current_price = prices["close"].iloc[-1]
        current_drawdown = (current_price - current_peak_price) / current_peak_price * 100

        print("  当前周期峰值: ${:,.0f} ({})".format(current_peak_price, str(current_peak_date.date())))
        print("  当前价格: ${:,.0f}".format(current_price))
        print("  距峰值月数: {:.1f}".format(months_since_peak))
        print("  当前累计跌幅: {:+.1f}%".format(current_drawdown))

        # 与历史周期同月数对比
        print()
        print("  与历史周期同月数对比:")
        print("  {:>6} | {:>20} | {:>20} | {:>15}".format(
            "月数", "当前跌幅", "历史平均跌幅", "相似度"))
        print("  {} | {} | {} | {}".format("-"*6, "-"*20, "-"*20, "-"*15))

        m_int = int(months_since_peak)
        similarities = []
        for m in range(min(m_int + 1, 15)):
            current_dd = None
            # 当前周期在月数m时的跌幅
            if m == m_int:
                current_dd = current_drawdown
            else:
                # 查找当前周期月数m时的价格
                target_date = current_peak_date + pd.DateOffset(months=m)
                mask = prices.index <= target_date
                if mask.any():
                    px = prices.loc[mask, "close"].iloc[-1]
                    if current_peak_price > 0:
                        current_dd = (px - current_peak_price) / current_peak_price * 100

            hist_vals = []
            for cyc_id in [1, 2, 3]:
                if cyc_id in paths_drawdown and m < len(paths_drawdown[cyc_id]):
                    hist_vals.append(paths_drawdown[cyc_id]["drawdown_pct"].iloc[m])

            if hist_vals and current_dd is not None and not np.isnan(current_dd):
                hist_avg = np.mean(hist_vals)
                # 相似度 = 1 - |当前 - 历史| / 100 (跌幅差异越小越相似)
                diff = abs(current_dd - hist_avg)
                sim = max(0.0, 1.0 - diff / 100.0)
                similarities.append((m, current_dd, hist_avg, sim))
                print("  {:>6} | {:+.1f}%            | {:+.1f}%             | {:.2f}".format(
                    m, current_dd, hist_avg, sim))

        # 整体相似度评分（最近3个月的平均）
        if len(similarities) >= 1:
            recent_sims = [s[3] for s in similarities[-3:]]
            overall_sim = np.mean(recent_sims)
            print()
            print("  整体相似度评分（近3月平均）: {:.2f}".format(overall_sim))
            if overall_sim > 0.7:
                print("  → 当前周期路径与历史高度相似，可能延续历史趋势")
            elif overall_sim > 0.4:
                print("  → 当前周期路径与历史部分相似")
            else:
                print("  → 当前周期路径偏离历史，需警惕结构性变化")

    # 4. 市值/成交量与周期的关系
    print("\n【4. 成交量与周期阶段的关系】")
    print("  (各阶段30日均量中位数，相对牛熊转换点)")

    for cyc in HISTORICAL_CYCLES[:3]:
        if cyc["peak_date"] is None:
            continue
        halving = pd.Timestamp(cyc["halving_date"])
        peak = pd.Timestamp(cyc["peak_date"])
        bottom = pd.Timestamp(cyc["bottom_date"])

        # 牛市阶段：减半到峰值
        bull_mask = (prices.index >= halving) & (prices.index < peak)
        bull_vol = prices.loc[bull_mask, "volume"].rolling(30, min_periods=1).mean().median()

        # 熊市阶段：峰值到底部
        bear_mask = (prices.index >= peak) & (prices.index <= bottom)
        bear_vol = prices.loc[bear_mask, "volume"].rolling(30, min_periods=1).mean().median()

        # 累积阶段：底部到下次减半
        cyc_idx = cyc["cycle"] - 1
        if cyc_idx + 1 < len(BTC_HALVING_DATES):
            next_halving = BTC_HALVING_DATES[cyc_idx + 1]
            acc_mask = (prices.index > bottom) & (prices.index < next_halving)
            if acc_mask.any():
                acc_vol = prices.loc[acc_mask, "volume"].rolling(30, min_periods=1).mean().median()
            else:
                acc_vol = 0
        else:
            acc_vol = 0

        print("  周期{}: 牛市量能中位数 {:,.0f} | 熊市 {:,.0f} | 累积 {:,.0f}".format(
            cyc["cycle"], bull_vol, bear_vol, acc_vol))
        if bull_vol > 0:
            print("         熊市/牛市 = {:.2f}x | 累积/牛市 = {:.2f}x".format(
                bear_vol / bull_vol, acc_vol / bull_vol if bull_vol > 0 else 0))

    # 5. 特征设计建议
    print("\n【5. 增强型周期特征设计建议】")
    print("  ┌──────────────────────────────────────────────────────────────────────┐")
    print("  │ 基于跌幅统计+市值变化+周期相似性的增强特征                          │")
    print("  ├──────────────────────────────────────────────────────────────────────┤")
    print("  │ 1. drawdown_vs_hist_avg: 当前跌幅 - 历史同月数平均跌幅              │")
    print("  │    正值=当前跌幅小于历史（强势），负值=当前跌幅大于历史（弱势）     │")
    print("  │                                                                      │")
    print("  │ 2. cycle_path_similarity: 当前周期路径与历史平均路径的相似度[0,1]    │")
    print("  │    高相似度→延续历史，低相似度→结构性变化                           │")
    print("  │                                                                      │")
    print("  │ 3. vol_regime_ratio: 当前30日均量 / 周期内峰值量                     │")
    print("  │    <0.5=量能萎缩(熊市特征)，>1.0=放量(牛市特征)                     │")
    print("  │                                                                      │")
    print("  │ 4. vol_phase_position: 成交量周期位置 [0,1]                          │")
    print("  │    当前量能 / (周期内最大量 - 最小量)，判断量能趋势                 │")
    print("  │                                                                      │")
    print("  │ 5. bear_severity_score: 熊市严重度评分 [0,1]                         │")
    print("  │    结合时间进度(bear_phase_progress) × 跌幅进度(当前跌幅/82%)        │")
    print("  │    综合判断熊市深度，避免单一维度误判                               │")
    print("  └──────────────────────────────────────────────────────────────────────┘")

    # 保存结果
    result = {
        "analysis_date": str(prices.index[-1].date()),
        "drawdown_paths": {
            str(cyc_id): path["drawdown_pct"].tolist() for cyc_id, path in paths_drawdown.items()
        },
        "avg_drawdown_curve": avg_drawdowns,
        "volume_paths": {
            str(cyc_id): path["vol_change_pct"].tolist() for cyc_id, path in paths_vol.items()
        },
        "avg_volume_curve": avg_vol_changes,
        "current_peak_date": str(current_peak_date.date()) if current_peak_date else None,
        "current_peak_price": float(current_peak_price) if current_peak_price else None,
        "current_drawdown_pct": float(current_drawdown) if current_peak_date else None,
        "months_since_peak": float(months_since_peak) if current_peak_date else None,
    }

    if 'similarities' in dir() and similarities:
        result["similarities"] = [
            {"month": m, "current_dd": cdd, "hist_avg_dd": hdd, "similarity": s}
            for m, cdd, hdd, s in similarities
        ]

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/btc_cycle_deep_analysis.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\n结果已保存: {}".format(output_path))

    return result


if __name__ == "__main__":
    prices = load_btc_data()
    print("数据: {}天, {} ~ {}\n".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))
    analyze_cycle_similarity(prices)
