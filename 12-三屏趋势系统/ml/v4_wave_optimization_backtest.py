#!/usr/bin/env python3
"""V4+波浪融合策略优化回测验证

验证4个优化方向，只有回测表现更好才允许接入：
1. 抄底分级优化：提高初始仓位，调整梯度
2. 波浪置信度阈值降低：0.6 -> 0.4
3. V4+波浪融合规则修复：保留V4 dip_buy仓位
4. 支撑区域上方保护增强：提高上方5%内仓位

回测周期：
- 8年期：3202天（2017-10 ~ 2026-07）
- 4年期：约1460天（2022-07 ~ 2026-07）

评估指标：年化收益、夏普比率、最大回撤、Calmar比率
评估标准：优化后 Calmar 比率 >= 基准，且年化收益 >= 基准
"""
import os, sys, json, time
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, '.')


def load_coin_data(symbol: str) -> pd.DataFrame:
    path = f"{BASE_DIR}/data/historical/{symbol}_1D_730d.json"
    with open(path) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )
    return prices


def calc_metrics(prices, position_arr, valid_start=0):
    """计算回测指标"""
    n = len(prices)
    closes = prices["close"].values
    daily_returns = np.zeros(n)
    for i in range(1, n):
        daily_returns[i] = position_arr[i-1] * (closes[i] / closes[i-1] - 1)

    valid_returns = daily_returns[valid_start:]
    valid_days = len(valid_returns)
    if valid_days == 0:
        return {}

    total_return = np.prod(1 + valid_returns) - 1
    annualized = (1 + total_return) ** (365 / valid_days) - 1

    daily_vol = np.std(valid_returns) * np.sqrt(365)
    sharpe = annualized / daily_vol if daily_vol > 0 else 0

    cumulative = np.cumprod(1 + valid_returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    max_dd = np.min(drawdowns)

    calmar = annualized / abs(max_dd) if max_dd < 0 else 0

    win_days = np.sum(valid_returns > 0)
    total_trading_days = np.sum(np.abs(position_arr[valid_start:]) > 0.01)
    win_rate = win_days / total_trading_days if total_trading_days > 0 else 0

    avg_pos = np.mean(np.abs(position_arr[valid_start:]))

    return {
        "total_return": total_return,
        "annualized": annualized,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "win_rate": win_rate,
        "avg_position": avg_pos,
        "valid_days": valid_days,
    }


def compute_v4_position(prices, symbol="BTC", config_override=None):
    """计算V4策略仓位，支持参数覆盖"""
    from ml.halving_top_exit_strategy import HalvingTopExitStrategy

    is_btc = (symbol == "BTC")
    strategy = HalvingTopExitStrategy(
        symbol=symbol,
        is_btc=is_btc,
        btc_prices=prices if is_btc else None,
    )

    if config_override:
        for k, v in config_override.items():
            if hasattr(strategy, k):
                setattr(strategy, k, v)

    position_series = strategy.generate_signals(prices)
    return position_series.values if hasattr(position_series, 'values') else np.array(position_series)


def generate_wave_signals(prices, zigzag_threshold=0.05):
    """预计算波浪信号（滚动识别）"""
    from ml.ewave_recognizer import ElliottWaveRecognizer

    print(f"  [波浪识别] threshold={zigzag_threshold}, 数据量={len(prices)}天...")
    t0 = time.time()
    recognizer = ElliottWaveRecognizer(zigzag_threshold=zigzag_threshold)
    n = len(prices)
    signals = []
    confs = []
    min_window = 90
    for i in range(n):
        if i < min_window:
            signals.append("WAIT")
            confs.append(0.0)
            continue
        slice_df = prices.iloc[: i + 1]
        try:
            ws = recognizer.identify_waves(slice_df)
            signals.append(ws.signal)
            confs.append(ws.confidence)
        except Exception:
            signals.append("WAIT")
            confs.append(0.0)
    print(f"    完成，耗时 {time.time()-t0:.1f}s")
    return np.array(signals), np.array(confs, dtype=float)


def parse_wave_direction(signal: str) -> str:
    if signal.startswith("ENTER_LONG") or signal.startswith("HOLD_LONG"):
        return "LONG"
    elif signal.startswith("ENTER_SHORT") or signal.startswith("HOLD_SHORT"):
        return "SHORT"
    return "NEUTRAL"


def compute_v4_wave_fusion(
    prices,
    v4_positions,
    wave_signals,
    wave_confs,
    config_override=None,
    fix_rule2b=False,
):
    """计算V4+波浪互斥融合后的仓位

    融合规则：
    1. V4多头 + 波浪看多(≥阈值) → V4仓位 + wave_weight * wave_conf
    2. V4多头 + 波浪中性/看空 → 保持V4仓位
    3. V4空仓 + 波浪看多(≥阈值) → min(wave_weight*wave_conf, bottom_position_cap)
       - fix_rule2b=True: V4有dip_buy仓位时保留V4仓位
    4. V4空仓 + 波浪中性/看空 → 空仓观望
       - fix_rule2b=True: V4有dip_buy仓位时保留V4仓位
    5. V4空头 + 波浪看多(≥阈值) → V4空头仓位减半
    6. V4空头 + 波浪中性/看空 → 保持V4空头
    """
    wave_weight = 0.6
    confirm_threshold = 0.6
    bottom_position_cap = 0.5
    total_position_cap = 1.0

    if config_override:
        wave_weight = config_override.get("wave_weight", wave_weight)
        confirm_threshold = config_override.get("confirm_threshold", confirm_threshold)
        bottom_position_cap = config_override.get("bottom_position_cap", bottom_position_cap)
        total_position_cap = config_override.get("total_position_cap", total_position_cap)

    n = len(prices)
    fused_positions = np.zeros(n)

    for i in range(n):
        v4_pos = v4_positions[i]
        wave_sig = wave_signals[i]
        wave_conf = wave_confs[i]
        wave_dir = parse_wave_direction(wave_sig)

        v4_abs = abs(v4_pos)
        v4_sign = 1 if v4_pos > 0.01 else (-1 if v4_pos < -0.01 else 0)

        if v4_sign == 1:
            if wave_dir == "LONG" and wave_conf >= confirm_threshold:
                add_pos = wave_weight * wave_conf
                fused = min(v4_pos + add_pos, total_position_cap)
            else:
                fused = v4_pos

        elif v4_sign == -1:
            if wave_dir == "LONG" and wave_conf >= confirm_threshold:
                fused = v4_pos * 0.5
            else:
                fused = v4_pos

        else:
            if wave_dir == "LONG" and wave_conf >= confirm_threshold:
                wave_pos = min(wave_weight * wave_conf, bottom_position_cap)
                fused = wave_pos
            elif fix_rule2b and v4_abs > 0.001:
                fused = v4_pos
            else:
                fused = 0.0

        fused_positions[i] = fused

    return fused_positions


def run_v4_only_backtest(prices, symbol, period_name, valid_start=0):
    """纯V4策略基准回测"""
    print(f"\n  [{symbol}] {period_name} - 纯V4基准...")
    v4_pos = compute_v4_position(prices, symbol)
    metrics = calc_metrics(prices, v4_pos, valid_start)
    return {
        "name": "纯V4基准",
        "positions": v4_pos,
        "metrics": metrics,
    }


def run_optimization_backtests(
    prices,
    symbol,
    period_name,
    wave_signals,
    wave_confs,
    valid_start=0,
):
    """运行所有优化方案的回测"""
    results = {}

    # 基准1：纯V4
    v4_pos = compute_v4_position(prices, symbol)
    results["baseline_v4"] = {
        "name": "纯V4基准",
        "metrics": calc_metrics(prices, v4_pos, valid_start),
    }

    # 基准2：V4+波浪默认融合
    base_fused = compute_v4_wave_fusion(prices, v4_pos, wave_signals, wave_confs)
    results["baseline_v4_wave"] = {
        "name": "V4+波浪融合(默认)",
        "metrics": calc_metrics(prices, base_fused, valid_start),
    }

    # 优化1：抄底分级调整
    # 初始仓位从0.1*0.9=9% 提升到 0.15*0.9=13.5%
    # step_pct从3%降到2%（更密集加仓）
    # max_position从0.9降到0.8（避免过高）
    print(f"  [{symbol}] {period_name} - 优化1：抄底分级调整...")
    v4_opt1 = compute_v4_position(prices, symbol, config_override={
        "dip_buy_initial_pct": 0.15,
        "dip_buy_step_pct": 2.0,
        "dip_buy_levels": 8,
        "dip_buy_max_position": 0.8,
    })
    fused_opt1 = compute_v4_wave_fusion(prices, v4_opt1, wave_signals, wave_confs)
    results["opt1_dip_buy"] = {
        "name": "优化1：抄底分级(15%起步/2%步长/8级/80%上限)",
        "v4_positions": v4_opt1,
        "positions": fused_opt1,
        "metrics": calc_metrics(prices, fused_opt1, valid_start),
    }

    # 优化2：波浪置信度阈值降低
    print(f"  [{symbol}] {period_name} - 优化2：波浪阈值降低...")
    fused_opt2 = compute_v4_wave_fusion(
        prices, v4_pos, wave_signals, wave_confs,
        config_override={"confirm_threshold": 0.4}
    )
    results["opt2_wave_threshold"] = {
        "name": "优化2：波浪阈值0.4",
        "positions": fused_opt2,
        "metrics": calc_metrics(prices, fused_opt2, valid_start),
    }

    # 优化3：融合规则修复（保留V4 dip_buy仓位）
    print(f"  [{symbol}] {period_name} - 优化3：融合规则修复...")
    fused_opt3 = compute_v4_wave_fusion(
        prices, v4_pos, wave_signals, wave_confs,
        fix_rule2b=True
    )
    results["opt3_fix_rule2b"] = {
        "name": "优化3：保留V4抄底仓位",
        "positions": fused_opt3,
        "metrics": calc_metrics(prices, fused_opt3, valid_start),
    }

    # 优化4：支撑区域上方保护增强
    # 保护范围从5%扩大到8%
    # 上方保护仓位系数从线性衰减改为更平缓（sqrt）
    print(f"  [{symbol}] {period_name} - 优化4：支撑区域增强...")
    v4_opt4 = compute_v4_position(prices, symbol, config_override={
        "weekly_ma200_support_zone_pct": 8.0,
    })
    fused_opt4 = compute_v4_wave_fusion(prices, v4_opt4, wave_signals, wave_confs)
    results["opt4_support_zone"] = {
        "name": "优化4：支撑区域增强(8%)",
        "v4_positions": v4_opt4,
        "positions": fused_opt4,
        "metrics": calc_metrics(prices, fused_opt4, valid_start),
    }

    # 组合优化：1+2+3+4全部
    print(f"  [{symbol}] {period_name} - 组合优化：全部4项...")
    v4_combo = compute_v4_position(prices, symbol, config_override={
        "dip_buy_initial_pct": 0.15,
        "dip_buy_step_pct": 2.0,
        "dip_buy_levels": 8,
        "dip_buy_max_position": 0.8,
        "weekly_ma200_support_zone_pct": 8.0,
    })
    fused_combo = compute_v4_wave_fusion(
        prices, v4_combo, wave_signals, wave_confs,
        config_override={"confirm_threshold": 0.4},
        fix_rule2b=True
    )
    results["combo_all"] = {
        "name": "组合优化：全部4项",
        "positions": fused_combo,
        "metrics": calc_metrics(prices, fused_combo, valid_start),
    }

    return results


def print_comparison_table(results, title):
    """打印对比表格"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")
    print(f"{'方案':<35} {'年化%':>8} {'夏普':>7} {'最大回撤%':>10} {'Calmar':>7} {'胜率%':>7} {'平均仓位%':>9}")
    print(f"{'-'*80}")

    baseline_key = "baseline_v4_wave"
    baseline = results[baseline_key]["metrics"]
    base_calmar = baseline.get("calmar", 0)
    base_ann = baseline.get("annualized", 0)

    for key, result in results.items():
        m = result["metrics"]
        name = result["name"]
        ann = m.get("annualized", 0) * 100
        sharpe = m.get("sharpe", 0)
        mdd = m.get("max_drawdown", 0) * 100
        calmar = m.get("calmar", 0)
        wr = m.get("win_rate", 0) * 100
        avg_pos = m.get("avg_position", 0) * 100

        better = ""
        if key != baseline_key:
            calmar_better = calmar >= base_calmar * 0.99
            ann_better = ann >= base_ann * 100 * 0.99
            if calmar_better and ann_better:
                better = " ✓ 通过"
            else:
                reasons = []
                if not calmar_better:
                    reasons.append(f"Calmar{calmar:.2f}<{base_calmar:.2f}")
                if not ann_better:
                    reasons.append(f"年化{ann:.1f}%<{base_ann*100:.1f}%")
                better = " ✗ " + ",".join(reasons)

        print(f"{name:<35} {ann:>8.2f} {sharpe:>7.3f} {mdd:>10.2f} {calmar:>7.3f} {wr:>7.1f} {avg_pos:>9.1f}{better}")


def main():
    print("=" * 80)
    print("V4+波浪融合策略优化回测验证")
    print("=" * 80)

    symbol = "BTC"
    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n数据: {symbol}, {n} 天 ({prices.index[0].strftime('%Y-%m-%d')} ~ {prices.index[-1].strftime('%Y-%m-%d')})")

    # 8年期和4年期的切片索引
    four_year_days = 1460
    four_year_start = n - four_year_days

    print(f"8年期: 全量 {n} 天, valid_start=730 (前2年预热)")
    print(f"4年期: 最近 {four_year_days} 天, valid_start=365 (前1年预热)")

    # 预计算波浪信号（全量数据）
    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=0.05)

    # 8年期回测
    results_8y = run_optimization_backtests(
        prices, symbol, "8年期",
        wave_signals, wave_confs,
        valid_start=730
    )
    print_comparison_table(results_8y, "8年期回测对比 (valid_start=730)")

    # 4年期回测
    prices_4y = prices.iloc[four_year_start:]
    wave_signals_4y = wave_signals[four_year_start:]
    wave_confs_4y = wave_confs[four_year_start:]

    results_4y = run_optimization_backtests(
        prices_4y, symbol, "4年期",
        wave_signals_4y, wave_confs_4y,
        valid_start=365
    )
    print_comparison_table(results_4y, "4年期回测对比 (valid_start=365)")

    # 综合评估
    print(f"\n{'='*80}")
    print("  综合评估（8年+4年均需通过：Calmar≥基准 AND 年化≥基准）")
    print(f"{'='*80}")

    base_8y = results_8y["baseline_v4_wave"]["metrics"]
    base_4y = results_4y["baseline_v4_wave"]["metrics"]

    passed = []
    failed = []

    for key in ["opt1_dip_buy", "opt2_wave_threshold", "opt3_fix_rule2b", "opt4_support_zone", "combo_all"]:
        r8 = results_8y[key]["metrics"]
        r4 = results_4y[key]["metrics"]
        name = results_8y[key]["name"]

        pass_8y = r8["calmar"] >= base_8y["calmar"] * 0.99 and r8["annualized"] >= base_8y["annualized"] * 0.99
        pass_4y = r4["calmar"] >= base_4y["calmar"] * 0.99 and r4["annualized"] >= base_4y["annualized"] * 0.99
        both_pass = pass_8y and pass_4y

        status = "✓ 通过" if both_pass else "✗ 未通过"
        detail = f"8年:{'✓' if pass_8y else '✗'} 4年:{'✓' if pass_4y else '✗'}"
        print(f"  {status}  {name:<35} [{detail}]")

        if both_pass:
            passed.append((key, name))
        else:
            failed.append((key, name))

    print(f"\n通过: {len(passed)} 项, 未通过: {len(failed)} 项")
    if passed:
        print("通过的优化方案:")
        for key, name in passed:
            print(f"  - {name}")
    if failed:
        print("未通过(需回退):")
        for key, name in failed:
            print(f"  - {name}")

    # 保存结果
    output = {
        "symbol": symbol,
        "periods": {
            "8y": {k: {"name": v["name"], "metrics": v["metrics"]} for k, v in results_8y.items()},
            "4y": {k: {"name": v["name"], "metrics": v["metrics"]} for k, v in results_4y.items()},
        },
        "passed": [k for k, _ in passed],
        "failed": [k for k, _ in failed],
    }

    out_path = f"{BASE_DIR}/ml/backtest_results/v4_wave_optimization_{symbol}.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
