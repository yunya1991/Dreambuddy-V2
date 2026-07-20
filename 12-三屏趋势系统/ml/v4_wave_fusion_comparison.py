#!/usr/bin/env python3
"""
V4减半周期 + 波浪策略融合对比回测
对比：V4基线、波浪+物理、V4+波浪融合（多种分仓比例）、买入持有
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

    n = len(position_arr)
    direction_arr = np.sign(position_arr)
    abs_position = np.abs(position_arr)

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


def compute_wave_position(prices, wave_signals, wave_confs, use_physics=True, base_position=0.3):
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
    return abs_position, direction_arr


def compute_fusion_position(v4_pos, v4_dir, wave_pos, wave_dir, v4_weight=0.7, wave_weight=0.3):
    """计算V4+波浪融合仓位（分仓模式）

    总仓位 = V4仓位 * v4_weight + 波浪仓位 * wave_weight
    方向：同向时叠加，异向时以V4为主
    """
    n = len(v4_pos)

    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)

    for i in range(n):
        v4 = v4_pos[i] * v4_dir[i]
        wave = wave_pos[i] * wave_dir[i]

        if v4_dir[i] == wave_dir[i] and v4_dir[i] != 0:
            total = v4 * v4_weight + wave * wave_weight
        elif v4_dir[i] != 0 and wave_dir[i] == 0:
            total = v4 * v4_weight
        elif v4_dir[i] == 0 and wave_dir[i] != 0:
            total = wave * wave_weight
        elif v4_dir[i] != 0 and wave_dir[i] != 0 and v4_dir[i] != wave_dir[i]:
            total = v4 * v4_weight
        else:
            total = 0.0

        total = np.clip(total, -1.0, 1.0)
        fusion_pos[i] = abs(total)
        fusion_dir[i] = np.sign(total)

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
        "cumulative_returns": cum_ret.tolist(),
    }


def run_comparison(symbol="BTC", zigzag_threshold=0.05, wave_base_position=0.3):
    """运行V4+波浪融合对比回测"""
    print(f"\n{'='*80}")
    print(f"  V4 + 波浪融合策略对比回测 - {symbol}")
    print(f"{'='*80}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=zigzag_threshold)
    wave_pos, wave_dir = compute_wave_position(
        prices, wave_signals, wave_confs,
        use_physics=True,
        base_position=wave_base_position,
    )

    valid_start = 365

    fusion_ratios = [
        (1.0, 0.0, "纯V4 (100%)"),
        (0.9, 0.1, "V4 90% + 波浪 10%"),
        (0.8, 0.2, "V4 80% + 波浪 20%"),
        (0.7, 0.3, "V4 70% + 波浪 30%"),
        (0.6, 0.4, "V4 60% + 波浪 40%"),
        (0.5, 0.5, "V4 50% + 波浪 50%"),
        (0.0, 1.0, "纯波浪 (100%)"),
    ]

    print(f"\n{'='*80}")
    print(f"  回测结果对比（有效天数: {n-valid_start}天）")
    print(f"{'='*80}")
    print(f"{'策略组合':<22} {'年化':>8} {'总收益':>10} {'夏普':>8} {'回撤':>10} {'Calmar':>8} {'胜率':>8} {'均仓':>7}")
    print(f"{'-'*90}")

    results = {}

    for v4_w, wave_w, name in fusion_ratios:
        if v4_w == 1.0:
            pos, direction = v4_pos, v4_dir
        elif wave_w == 1.0:
            pos, direction = wave_pos, wave_dir
        else:
            pos, direction = compute_fusion_position(v4_pos, v4_dir, wave_pos, wave_dir, v4_w, wave_w)

        metrics = backtest_position(pos[valid_start:], direction[valid_start:], prices.iloc[valid_start:])
        results[name] = metrics

        ann = metrics.get('ann_return', 0) * 100
        tot = metrics.get('total_return', 0) * 100
        sharpe = metrics.get('sharpe', 0)
        mdd = metrics.get('max_drawdown', 0) * 100
        calmar = metrics.get('calmar', 0)
        win = metrics.get('win_rate', 0) * 100
        avgpos = metrics.get('avg_position', 0)

        print(f"{name:<22} {ann:>7.2f}% {tot:>9.2f}% {sharpe:>8.4f} {mdd:>9.2f}% {calmar:>8.4f} {win:>7.2f}% {avgpos:>7.3f}")

    bh_pos = np.ones(n)
    bh_dir = np.ones(n)
    bh_metrics = backtest_position(bh_pos[valid_start:], bh_dir[valid_start:], prices.iloc[valid_start:])
    results["买入持有"] = bh_metrics
    ann = bh_metrics.get('ann_return', 0) * 100
    tot = bh_metrics.get('total_return', 0) * 100
    sharpe = bh_metrics.get('sharpe', 0)
    mdd = bh_metrics.get('max_drawdown', 0) * 100
    calmar = bh_metrics.get('calmar', 0)
    win = bh_metrics.get('win_rate', 0) * 100
    avgpos = bh_metrics.get('avg_position', 0)
    print(f"{'买入持有':<22} {ann:>7.2f}% {tot:>9.2f}% {sharpe:>8.4f} {mdd:>9.2f}% {calmar:>8.4f} {win:>7.2f}% {avgpos:>7.3f}")

    print(f"\n{'='*80}")
    print(f"  相对纯V4的增量价值")
    print(f"{'='*80}")
    print(f"{'策略组合':<22} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'综合评分':>10}")
    print(f"{'-'*75}")

    v4_base = results.get("纯V4 (100%)", {})
    v4_ann = v4_base.get('ann_return', 0)
    v4_sharpe = v4_base.get('sharpe', 0)
    v4_mdd = v4_base.get('max_drawdown', 0)

    best_score = -999
    best_name = ""

    for name, metrics in results.items():
        if name == "买入持有":
            continue
        ann_delta = (metrics.get('ann_return', 0) - v4_ann) * 100
        sharpe_delta = metrics.get('sharpe', 0) - v4_sharpe
        mdd_delta = (metrics.get('max_drawdown', 0) - v4_mdd) * 100

        score = sharpe_delta * 0.4 + ann_delta * 0.01 * 0.3 + (-mdd_delta) * 0.01 * 0.3

        mark = " ★" if score > best_score else ""
        if score > best_score:
            best_score = score
            best_name = name

        print(f"{name:<22} {ann_delta:>+9.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+9.2f}pp {score:>10.4f}{mark}")

    print(f"\n最优组合: {best_name} (综合评分: {best_score:.4f})")

    os.makedirs("ml/backtest_results", exist_ok=True)
    save_results = {
        "symbol": symbol,
        "data_days": int(n),
        "valid_days": int(n - valid_start),
        "date_range": [str(prices.index[0].date()), str(prices.index[-1].date())],
        "results": {
            k: {
                kk: float(vv) if isinstance(vv, (int, float, np.floating, np.integer))
                else vv
                for kk, vv in v.items()
                if kk != "cumulative_returns"
            }
            for k, v in results.items()
        },
    }
    with open(f"ml/backtest_results/v4_wave_fusion_{symbol.lower()}.json", "w") as f:
        json.dump(save_results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到 ml/backtest_results/v4_wave_fusion_{symbol.lower()}.json")

    return results


def main():
    parser = argparse.ArgumentParser(description="V4+波浪融合策略对比回测")
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
