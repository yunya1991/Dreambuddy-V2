#!/usr/bin/env python3
"""
V4 + 波浪智能融合策略
核心思路：V4定方向，波浪择时加仓

四种市场状态下的融合规则：
1. V4多头 + 波浪看多 → V4仓位 + 波浪加仓（上限100%）
2. V4多头 + 波浪中性/看空 → 保持V4仓位（波浪不加仓）
3. V4空仓 + 波浪看多 → 波浪轻仓抄底（20%仓位上限）
4. V4空仓 + 波浪中性/看空 → 空仓观望

对比：纯V4、纯波浪、简单分仓融合、智能融合、买入持有
"""
import os
import sys
import json
import time
import argparse
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, '.')


def load_coin_data(symbol: str) -> pd.DataFrame:
    """加载币种K线数据"""
    path = f"data/historical/{symbol}_1D_730d.json"
    with open(path) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )
    return prices


def compute_v4_position(prices, symbol="BTC"):
    """计算V4减半周期策略仓位"""
    print(f"  [V4] 计算 {symbol} V4减半周期策略...")
    t0 = time.time()

    from ml.halving_top_exit_strategy import HalvingTopExitStrategy

    is_btc = (symbol == "BTC")
    strategy = HalvingTopExitStrategy(
        symbol=symbol,
        is_btc=is_btc,
        btc_prices=prices if is_btc else None,
    )

    position_series = strategy.generate_signals(prices)
    position_arr = position_series.values if hasattr(position_series, 'values') else np.array(position_series)

    abs_position = np.abs(position_arr)
    direction_arr = np.sign(position_arr)

    print(f"    耗时: {time.time()-t0:.1f}s, 平均仓位: {np.mean(abs_position):.3f}")
    return abs_position, direction_arr


def generate_wave_signals(prices, zigzag_threshold=0.05):
    """生成波浪信号（滚动识别）"""
    from ml.ewave_recognizer import ElliottWaveRecognizer

    print(f"  [Wave] 计算波浪信号 (threshold={zigzag_threshold})...")
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

        if i % 500 == 0:
            print(f"    波浪识别进度 {i}/{n} ({i/n*100:.1f}%)")

        slice_df = prices.iloc[: i + 1]
        try:
            ws = recognizer.identify_waves(slice_df)
            signals.append(ws.signal)
            confs.append(ws.confidence)
        except Exception:
            signals.append("WAIT")
            confs.append(0.0)

    print(f"    耗时: {time.time()-t0:.1f}s")
    return np.array(signals), np.array(confs)


def compute_wave_position_from_signals(prices, wave_signals, wave_confs, use_physics=True, base_position=0.3):
    """根据波浪信号计算仓位"""
    from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights

    print(f"  [Wave] 计算波浪仓位 (base_pos={base_position}, physics={use_physics})...")
    t0 = time.time()

    n = len(prices)
    closes = prices["close"].values

    position = np.zeros(n)
    direction = np.zeros(n)

    if use_physics:
        weights = ConfidenceWeights(
            w_eta=0.211, w_reversal=0.368,
            w_support=0.211, w_kinetic=0.211,
            position_lower=0.6, position_scale=1.0,
        )
        scorer = PhysicsConfidenceScorer(weights)
        from ml.pitd_kinematics_engineer import KinematicsEngineer
        from ml.pitd_dynamics_engineer import DynamicsEngineer
        kin_fe = KinematicsEngineer()
        dyn_fe = DynamicsEngineer()
        kin_feats = kin_fe.extract_series(prices)
        dyn_feats = dyn_fe.extract_series(prices, kin_feats)
        eta_series = dyn_feats["dyn_coupling_eta"].values
        ml_pred_neutral = np.full(n, 0.5)
        phys_conf, _ = scorer.score_signals(prices=prices, ml_predictions=ml_pred_neutral)
    else:
        eta_series = np.full(n, 1.0)
        phys_conf = np.full(n, 0.5)

    current_pos = 0.0
    current_dir = 0
    current_entry = 0.0
    stop_loss_pct = 0.10
    take_profit_pct = 0.30

    for i in range(n):
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        if sig in ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3"):
            if current_dir != 1:
                new_pos = base_position * max(wave_conf, 0.5)
                if use_physics and eta_series[i] < 0.10 and not np.isnan(eta_series[i]):
                    multiplier = 0.6 + 1.0 * phys_conf[i]
                    new_pos = new_pos * multiplier
                new_pos = min(new_pos, 1.0)

                if current_dir != 0:
                    current_pos = 0.0
                    current_dir = 0

                current_pos = new_pos
                current_dir = 1
                current_entry = closes[i]

        elif sig in ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3"):
            if current_dir != -1:
                new_pos = base_position * max(wave_conf, 0.5)
                if use_physics and eta_series[i] < 0.10 and not np.isnan(eta_series[i]):
                    multiplier = 0.6 + 1.0 * phys_conf[i]
                    new_pos = new_pos * multiplier
                new_pos = min(new_pos, 1.0)

                if current_dir != 0:
                    current_pos = 0.0
                    current_dir = 0

                current_pos = new_pos
                current_dir = -1
                current_entry = closes[i]

        elif sig in ("EXIT_LONG", "EXIT_SHORT", "WAIT") and current_dir != 0:
            current_pos = 0.0
            current_dir = 0

        if current_dir == 1 and current_entry > 0:
            pnl = (closes[i] - current_entry) / current_entry
            if pnl <= -stop_loss_pct or pnl >= take_profit_pct:
                current_pos = 0.0
                current_dir = 0

        position[i] = current_pos * current_dir if current_dir != 0 else 0
        direction[i] = current_dir

    abs_position = np.abs(position)
    direction_arr = np.sign(position)

    print(f"    耗时: {time.time()-t0:.1f}s, 平均仓位: {np.mean(abs_position):.3f}")
    return abs_position, direction_arr, phys_conf, eta_series


def compute_smart_fusion(v4_pos, v4_dir, wave_signals, wave_confs, phys_conf, eta_series,
                         add_ratio=0.3, bottom_ratio=0.2, max_position=1.0):
    """智能融合：V4定方向 + 波浪择时加仓

    规则：
    1. V4多头 + 波浪看多 → V4仓位 + 波浪加仓（add_ratio × 波浪置信度）
    2. V4多头 + 波浪中性/看空 → 保持V4仓位
    3. V4空仓 + 波浪看多 → 波浪轻仓抄底（bottom_ratio × 波浪置信度）
    4. V4空仓 + 波浪中性/看空 → 空仓观望
    5. V4空头 + 波浪看空 → V4空头仓位（不加仓）
    6. V4空头 + 波浪看多 → V4空头减半（波浪提示反弹）
    """
    n = len(v4_pos)
    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)

    wave_long_signals = ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
    wave_short_signals = ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")

    stats = {"bull_add": 0, "bull_keep": 0, "empty_bottom": 0, "empty_wait": 0,
             "bear_keep": 0, "bear_reduce": 0}

    for i in range(n):
        v4_p = v4_pos[i] * v4_dir[i]  # 带方向V4仓位
        v4_d = v4_dir[i]
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        wave_is_long = sig in wave_long_signals
        wave_is_short = sig in wave_short_signals

        if v4_d > 0:  # V4多头
            if wave_is_long:
                # 规则1：V4多头 + 波浪看多 → 加仓
                add_amount = add_ratio * max(wave_conf, 0.5)
                total = v4_p + add_amount
                total = min(total, max_position)
                fusion_pos[i] = abs(total)
                fusion_dir[i] = 1
                stats["bull_add"] += 1
            else:
                # 规则2：V4多头 + 波浪中性/看空 → 保持V4仓位
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = 1
                stats["bull_keep"] += 1

        elif v4_d == 0:  # V4空仓
            if wave_is_long:
                # 规则3：V4空仓 + 波浪看多 → 轻仓抄底
                bottom_pos = bottom_ratio * max(wave_conf, 0.5)
                # 物理置信度调节
                if not np.isnan(eta_series[i]) and eta_series[i] < 0.10:
                    multiplier = 0.6 + 1.0 * phys_conf[i]
                    bottom_pos = bottom_pos * multiplier
                bottom_pos = min(bottom_pos, 0.3)  # 抄底仓位上限30%
                fusion_pos[i] = bottom_pos
                fusion_dir[i] = 1
                stats["empty_bottom"] += 1
            else:
                # 规则4：V4空仓 + 波浪中性/看空 → 空仓
                stats["empty_wait"] += 1

        else:  # V4空头
            if wave_is_short:
                # 规则5：V4空头 + 波浪看空 → 保持V4空头
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = -1
                stats["bear_keep"] += 1
            elif wave_is_long:
                # 规则6：V4空头 + 波浪看多 → 空头减半
                fusion_pos[i] = abs(v4_p) * 0.5
                fusion_dir[i] = -1
                stats["bear_reduce"] += 1
            else:
                # V4空头 + 波浪中性 → 保持V4空头
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = -1
                stats["bear_keep"] += 1

    print(f"\n  [SmartFusion] 智能融合状态统计:")
    print(f"    V4多头+波浪加仓: {stats['bull_add']}天 ({stats['bull_add']/n*100:.1f}%)")
    print(f"    V4多头+保持: {stats['bull_keep']}天 ({stats['bull_keep']/n*100:.1f}%)")
    print(f"    V4空仓+波浪抄底: {stats['empty_bottom']}天 ({stats['empty_bottom']/n*100:.1f}%)")
    print(f"    V4空仓+空仓观望: {stats['empty_wait']}天 ({stats['empty_wait']/n*100:.1f}%)")
    print(f"    V4空头+保持: {stats['bear_keep']}天 ({stats['bear_keep']/n*100:.1f}%)")
    print(f"    V4空头+减半: {stats['bear_reduce']}天 ({stats['bear_reduce']/n*100:.1f}%)")
    print(f"    平均仓位: {np.mean(fusion_pos):.3f}")

    return fusion_pos, fusion_dir


def backtest_position(position, direction, prices, cost_pct=0.001):
    """回测仓位序列"""
    n = len(prices)
    closes = prices["close"].values
    daily_ret = np.zeros(n)
    daily_ret[1:] = closes[1:] / closes[:-1] - 1

    strategy_ret = position * direction * daily_ret

    pos_with_dir = position * direction
    position_change = np.abs(np.diff(np.concatenate([[0], pos_with_dir])))
    cost = position_change * cost_pct
    strategy_ret_net = strategy_ret - cost

    days = n
    years = days / 365
    cum_ret = np.cumprod(1 + strategy_ret_net) - 1
    ann_ret = (1 + cum_ret[-1]) ** (1 / years) - 1 if years > 0 else 0

    daily_nonzero = strategy_ret_net[strategy_ret_net != 0]
    if len(daily_nonzero) > 10:
        sharpe = np.mean(daily_nonzero) / (np.std(daily_nonzero) + 1e-10) * np.sqrt(365)
    else:
        sharpe = 0.0

    cum_value = np.cumprod(1 + strategy_ret_net)
    running_max = np.maximum.accumulate(cum_value)
    drawdown = (cum_value - running_max) / running_max
    max_dd = np.min(drawdown) if len(drawdown) > 0 else 0.0

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    holding_days = np.sum(position > 0)
    win_days = np.sum((position > 0) & (strategy_ret_net > 0))
    win_rate = win_days / holding_days if holding_days > 0 else 0.0

    entries = np.sum((direction != 0) & (np.concatenate([[0], direction[:-1]]) == 0))
    exits = np.sum((direction == 0) & (np.concatenate([[0], direction[:-1]]) != 0))
    trades = min(int(entries), int(exits))

    total_return = cum_ret[-1]

    return {
        "ann_return": float(ann_ret),
        "total_return": float(total_return),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "win_rate": float(win_rate),
        "holding_days": int(holding_days),
        "trades": int(trades),
        "final_cum_return": float(cum_ret[-1]),
        "avg_position": float(np.mean(position)),
    }


def run_comparison(symbol="BTC", zigzag_threshold=0.05, wave_base_position=0.3):
    """运行智能融合对比回测"""
    print(f"\n{'='*90}")
    print(f"  V4 + 波浪智能融合策略对比回测 - {symbol}")
    print(f"{'='*90}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # 计算各策略仓位
    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=zigzag_threshold)
    wave_pos, wave_dir, phys_conf, eta_series = compute_wave_position_from_signals(
        prices, wave_signals, wave_confs,
        use_physics=True, base_position=wave_base_position,
    )

    valid_start = 365

    # 智能融合参数组合
    smart_configs = [
        (0.2, 0.1, "智能融合A (加仓20%/抄底10%)"),
        (0.3, 0.15, "智能融合B (加仓30%/抄底15%)"),
        (0.3, 0.2, "智能融合C (加仓30%/抄底20%)"),
        (0.4, 0.2, "智能融合D (加仓40%/抄底20%)"),
        (0.5, 0.25, "智能融合E (加仓50%/抄底25%)"),
    ]

    print(f"\n{'='*90}")
    print(f"  回测结果对比（有效天数: {n-valid_start}天）")
    print(f"{'='*90}")
    print(f"{'策略':<32} {'年化':>8} {'总收益':>10} {'夏普':>8} {'回撤':>10} {'Calmar':>8} {'胜率':>8} {'均仓':>7}")
    print(f"{'-'*100}")

    results = {}

    # 纯V4
    m = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:], prices.iloc[valid_start:])
    results["纯V4"] = m
    print(f"{'纯V4':<32} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    # 纯波浪
    m = backtest_position(wave_pos[valid_start:], wave_dir[valid_start:], prices.iloc[valid_start:])
    results["纯波浪"] = m
    print(f"{'纯波浪':<32} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    # 简单分仓融合 (V4 70% + 波浪 30%)
    simple_fusion_pos = v4_pos[valid_start:] * 0.7
    simple_fusion_dir = v4_dir[valid_start:]
    m = backtest_position(simple_fusion_pos, simple_fusion_dir, prices.iloc[valid_start:])
    results["简单分仓(70/30)"] = m
    print(f"{'简单分仓(70/30)':<32} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    # 智能融合
    for add_r, bot_r, name in smart_configs:
        print(f"\n  --- {name} ---")
        smart_pos, smart_dir = compute_smart_fusion(
            v4_pos, v4_dir, wave_signals, wave_confs, phys_conf, eta_series,
            add_ratio=add_r, bottom_ratio=bot_r, max_position=1.0,
        )
        m = backtest_position(smart_pos[valid_start:], smart_dir[valid_start:], prices.iloc[valid_start:])
        results[name] = m
        print(f"  {name:<30} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    # 买入持有
    bh_pos = np.ones(n)
    bh_dir = np.ones(n)
    m = backtest_position(bh_pos[valid_start:], bh_dir[valid_start:], prices.iloc[valid_start:])
    results["买入持有"] = m
    print(f"{'买入持有':<32} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    # 增量分析
    print(f"\n{'='*90}")
    print(f"  相对纯V4的增量价值")
    print(f"{'='*90}")
    print(f"{'策略':<32} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'综合评分':>10}")
    print(f"{'-'*80}")

    v4_base = results["纯V4"]
    v4_ann = v4_base['ann_return']
    v4_sharpe = v4_base['sharpe']
    v4_mdd = v4_base['max_drawdown']

    best_score = -999
    best_name = ""

    for name, metrics in results.items():
        if name == "买入持有":
            continue
        ann_delta = (metrics['ann_return'] - v4_ann) * 100
        sharpe_delta = metrics['sharpe'] - v4_sharpe
        mdd_delta = (metrics['max_drawdown'] - v4_mdd) * 100

        score = sharpe_delta * 0.4 + ann_delta * 0.01 * 0.3 + (-mdd_delta) * 0.01 * 0.3

        mark = ""
        if score > 0:
            mark = " ✅"
        if score > best_score:
            best_score = score
            best_name = name
            mark = " ★" if score > 0 else mark

        print(f"{name:<32} {ann_delta:>+9.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+9.2f}pp {score:>10.4f}{mark}")

    print(f"\n最优组合: {best_name} (综合评分: {best_score:.4f})")

    # 保存结果
    os.makedirs("ml/backtest_results", exist_ok=True)
    save_results = {
        "symbol": symbol,
        "data_days": int(n),
        "valid_days": int(n - valid_start),
        "date_range": [str(prices.index[0].date()), str(prices.index[-1].date())],
        "results": results,
    }
    with open(f"ml/backtest_results/v4_wave_smart_fusion_{symbol.lower()}.json", "w") as f:
        json.dump(save_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到 ml/backtest_results/v4_wave_smart_fusion_{symbol.lower()}.json")

    return results


def main():
    parser = argparse.ArgumentParser(description="V4+波浪智能融合策略对比回测")
    parser.add_argument("--symbol", type=str, default="BTC", help="交易对")
    parser.add_argument("--zigzag-threshold", type=float, default=0.05, help="ZigZag阈值")
    parser.add_argument("--wave-base-position", type=float, default=0.3, help="波浪基础仓位")
    args = parser.parse_args()

    run_comparison(
        symbol=args.symbol,
        zigzag_threshold=args.zigzag_threshold,
        wave_base_position=args.wave_base_position,
    )


if __name__ == "__main__":
    main()
