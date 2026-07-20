#!/usr/bin/env python3
"""
物理引擎驱动的动态止损止盈探索
对比5种止损止盈策略在波浪+物理融合策略上的效果：
1. 基线：固定止损10% + 固定止盈30%
2. η自适应止损：强趋势放宽，弱趋势收紧
3. jerk反转保护：反转风险高时收紧止损
4. 动能止盈：动能充沛时扩大止盈，衰竭时提前止盈
5. 综合物理止损止盈：η + jerk + 动能三维调节
"""
import os
import sys
import json
import time
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, '.')


def load_coin_data(symbol: str) -> pd.DataFrame:
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


def generate_wave_signals(prices, zigzag_threshold=0.03):
    from ml.ewave_recognizer import ElliottWaveRecognizer
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
    return np.array(signals), np.array(confs, dtype=float)


def compute_physics_features(prices):
    from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
    from ml.pitd_kinematics_engineer import KinematicsEngineer
    from ml.pitd_dynamics_engineer import DynamicsEngineer

    n = len(prices)
    weights = ConfidenceWeights(
        w_eta=0.211, w_reversal=0.368,
        w_support=0.211, w_kinetic=0.211,
        position_lower=0.6, position_scale=1.0,
    )
    scorer = PhysicsConfidenceScorer(weights)
    kin_fe = KinematicsEngineer()
    dyn_fe = DynamicsEngineer()
    kin_feats = kin_fe.extract_series(prices)
    dyn_feats = dyn_fe.extract_series(prices, kin_feats)
    eta_series = dyn_feats["dyn_coupling_eta"].values
    ml_pred_neutral = np.full(n, 0.5)
    phys_conf, phys_components = scorer.score_signals(prices=prices, ml_predictions=ml_pred_neutral)

    return {
        "eta": eta_series,
        "phys_conf": phys_conf,
        "trend_score": phys_components.get("trend_score", np.full(n, 0.5)),
        "reversal_score": phys_components.get("reversal_score", np.full(n, 0.5)),
        "support_score": phys_components.get("support_score", np.full(n, 0.5)),
        "kinetic_score": phys_components.get("kinetic_score", np.full(n, 0.5)),
    }


def compute_wave_position_custom_tp_sl(
    prices, wave_signals, wave_confs, physics_feats,
    base_position=0.3,
    wave_conf_threshold=0.7,
    phys_conf_threshold=0.5,
    use_physics_position_adjust=True,
    sl_mode="fixed",
    tp_mode="fixed",
    base_sl=0.10,
    base_tp=0.30,
):
    """波浪策略仓位计算（支持多种止损止盈模式）

    sl_mode / tp_mode 可选:
    - "fixed": 固定止损止盈
    - "eta": η自适应（强趋势放宽止损/止盈，弱趋势收紧）
    - "jerk": jerk反转保护（反转风险高时收紧止损）
    - "kinetic": 动能止盈（动能充沛时扩大止盈）
    - "combo": 综合物理止损止盈
    """
    n = len(prices)
    closes = prices["close"].values

    eta_series = physics_feats["eta"]
    phys_conf = physics_feats["phys_conf"]
    trend_score = physics_feats["trend_score"]
    reversal_score = physics_feats["reversal_score"]
    kinetic_score = physics_feats["kinetic_score"]

    position = np.zeros(n)
    direction = np.zeros(n)

    current_pos = 0.0
    current_dir = 0
    current_entry = 0.0
    dynamic_sl = base_sl
    dynamic_tp = base_tp

    wave_long_signals = ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
    wave_short_signals = ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")

    stats = {
        "total_enter": 0, "total_exit_by_sl": 0, "total_exit_by_tp": 0,
        "total_exit_by_signal": 0, "avg_sl_pct": [], "avg_tp_pct": [],
        "sl_min": 1.0, "sl_max": 0.0, "tp_min": 1.0, "tp_max": 0.0,
    }

    for i in range(n):
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        if sig in wave_long_signals or sig in wave_short_signals:
            if wave_conf < wave_conf_threshold:
                sig = "WAIT"

        if sig in wave_long_signals or sig in wave_short_signals:
            pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
            if pc < phys_conf_threshold:
                sig = "WAIT"

        # 动态止损止盈计算
        if current_dir != 0:
            # --- 止损模式 ---
            if sl_mode == "fixed":
                dynamic_sl = base_sl

            elif sl_mode == "eta":
                # η自适应止损：趋势越强，止损越宽
                ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
                # trend_score ∈ [0,1]，0.5为中性
                # 止损范围：base_sl * [0.5, 1.5]
                sl_factor = 0.5 + 1.0 * ts
                dynamic_sl = base_sl * sl_factor
                dynamic_sl = np.clip(dynamic_sl, 0.03, 0.25)

            elif sl_mode == "jerk":
                # jerk反转保护：反转风险高时收紧止损
                rs = float(reversal_score[i]) if not np.isnan(reversal_score[i]) else 0.5
                # reversal_score高 = 反转风险低 = 可以放宽
                # 止损范围：base_sl * [0.6, 1.3]
                sl_factor = 0.6 + 0.7 * rs
                dynamic_sl = base_sl * sl_factor
                dynamic_sl = np.clip(dynamic_sl, 0.03, 0.25)

            elif sl_mode == "combo":
                # 综合止损：η趋势 + jerk反转
                ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
                rs = float(reversal_score[i]) if not np.isnan(reversal_score[i]) else 0.5
                # 趋势权重0.6，反转权重0.4
                sl_factor = 0.5 + 1.0 * (ts * 0.6 + rs * 0.4)
                dynamic_sl = base_sl * sl_factor
                dynamic_sl = np.clip(dynamic_sl, 0.03, 0.25)

            # --- 止盈模式 ---
            if tp_mode == "fixed":
                dynamic_tp = base_tp

            elif tp_mode == "eta":
                # η自适应止盈：趋势越强，止盈越高
                ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
                # 止盈范围：base_tp * [0.6, 1.8]
                tp_factor = 0.6 + 1.2 * ts
                dynamic_tp = base_tp * tp_factor
                dynamic_tp = np.clip(dynamic_tp, 0.10, 1.00)

            elif tp_mode == "kinetic":
                # 动能止盈：动能充沛时扩大止盈，衰竭时提前止盈
                ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
                # 止盈范围：base_tp * [0.5, 2.0]
                tp_factor = 0.5 + 1.5 * ks
                dynamic_tp = base_tp * tp_factor
                dynamic_tp = np.clip(dynamic_tp, 0.10, 1.00)

            elif tp_mode == "combo":
                # 综合止盈：η趋势 + 动能
                ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
                ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
                # 趋势权重0.5，动能权重0.5
                tp_factor = 0.5 + 1.5 * (ts * 0.5 + ks * 0.5)
                dynamic_tp = base_tp * tp_factor
                dynamic_tp = np.clip(dynamic_tp, 0.10, 1.00)

            # 记录统计
            stats["sl_min"] = min(stats["sl_min"], dynamic_sl)
            stats["sl_max"] = max(stats["sl_max"], dynamic_sl)
            stats["tp_min"] = min(stats["tp_min"], dynamic_tp)
            stats["tp_max"] = max(stats["tp_max"], dynamic_tp)

        # 入场逻辑
        if sig in wave_long_signals:
            if current_dir != 1:
                new_pos = base_position * max(wave_conf, 0.5)
                if use_physics_position_adjust:
                    pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
                    multiplier = 0.6 + 1.0 * pc
                    new_pos = new_pos * multiplier
                new_pos = min(new_pos, 1.0)
                if current_dir != 0:
                    current_pos = 0.0
                    current_dir = 0
                    stats["total_exit_by_signal"] += 1
                current_pos = new_pos
                current_dir = 1
                current_entry = closes[i]
                stats["total_enter"] += 1

        elif sig in wave_short_signals:
            if current_dir != -1:
                new_pos = base_position * max(wave_conf, 0.5)
                if use_physics_position_adjust:
                    pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
                    multiplier = 0.6 + 1.0 * pc
                    new_pos = new_pos * multiplier
                new_pos = min(new_pos, 1.0)
                if current_dir != 0:
                    current_pos = 0.0
                    current_dir = 0
                    stats["total_exit_by_signal"] += 1
                current_pos = new_pos
                current_dir = -1
                current_entry = closes[i]
                stats["total_enter"] += 1

        elif sig in ("EXIT_LONG", "EXIT_SHORT", "WAIT") and current_dir != 0:
            current_pos = 0.0
            current_dir = 0
            stats["total_exit_by_signal"] += 1

        # 止损止盈检查
        if current_dir == 1 and current_entry > 0:
            pnl = (closes[i] - current_entry) / current_entry
            if pnl <= -dynamic_sl:
                current_pos = 0.0
                current_dir = 0
                stats["total_exit_by_sl"] += 1
                stats["avg_sl_pct"].append(dynamic_sl)
            elif pnl >= dynamic_tp:
                current_pos = 0.0
                current_dir = 0
                stats["total_exit_by_tp"] += 1
                stats["avg_tp_pct"].append(dynamic_tp)

        elif current_dir == -1 and current_entry > 0:
            pnl = (current_entry - closes[i]) / current_entry
            if pnl <= -dynamic_sl:
                current_pos = 0.0
                current_dir = 0
                stats["total_exit_by_sl"] += 1
                stats["avg_sl_pct"].append(dynamic_sl)
            elif pnl >= dynamic_tp:
                current_pos = 0.0
                current_dir = 0
                stats["total_exit_by_tp"] += 1
                stats["avg_tp_pct"].append(dynamic_tp)

        position[i] = current_pos * current_dir if current_dir != 0 else 0
        direction[i] = current_dir

    # 统计汇总
    stats["avg_sl"] = np.mean(stats["avg_sl_pct"]) if stats["avg_sl_pct"] else 0
    stats["avg_tp"] = np.mean(stats["avg_tp_pct"]) if stats["avg_tp_pct"] else 0

    abs_position = np.abs(position)
    direction_arr = np.sign(position)
    return abs_position, direction_arr, stats


def compute_smart_fusion(v4_pos, v4_dir, wave_pos, wave_dir,
                         add_ratio=0.5, bottom_ratio=0.25, max_position=1.0):
    n = len(v4_pos)
    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)

    for i in range(n):
        v4_p = v4_pos[i] * v4_dir[i]
        v4_d = v4_dir[i]
        w_p = wave_pos[i] * wave_dir[i]
        w_d = wave_dir[i]

        if v4_d > 0:
            if w_d > 0:
                total = v4_p + w_p * add_ratio
                total = min(total, max_position)
                fusion_pos[i] = abs(total)
                fusion_dir[i] = 1
            elif w_d < 0:
                fusion_pos[i] = abs(v4_p) * 0.8
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = 1
        elif v4_d == 0:
            if w_d > 0:
                bottom = w_p * bottom_ratio
                bottom = min(bottom, 0.3)
                fusion_pos[i] = bottom
                fusion_dir[i] = 1
        else:
            if w_d < 0:
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = -1
            elif w_d > 0:
                fusion_pos[i] = abs(v4_p) * 0.5
                fusion_dir[i] = -1
            else:
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = -1

    return fusion_pos, fusion_dir


def backtest_position(position, direction, prices, cost_pct=0.001):
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

    return {
        "ann_return": float(ann_ret),
        "total_return": float(cum_ret[-1]),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "win_rate": float(win_rate),
        "avg_position": float(np.mean(position)),
    }


def run_tp_sl_experiment(symbol="BTC"):
    print(f"\n{'='*100}")
    print(f"  物理驱动动态止损止盈实验 - {symbol}")
    print(f"{'='*100}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    print("\n[1/5] 生成波浪信号...")
    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=0.03)

    print("[2/5] 计算物理特征...")
    t0 = time.time()
    physics_feats = compute_physics_features(prices)
    print(f"  耗时: {time.time()-t0:.1f}s")

    print("[3/5] 计算V4仓位...")
    from ml.halving_top_exit_strategy import HalvingTopExitStrategy
    is_btc = (symbol == "BTC")
    strategy = HalvingTopExitStrategy(symbol=symbol, is_btc=is_btc, btc_prices=prices if is_btc else None)
    v4_series = strategy.generate_signals(prices)
    v4_pos = np.abs(v4_series.values)
    v4_dir = np.sign(v4_series.values)

    valid_start = 365

    # 实验配置
    configs = [
        ("基线（固定10%/30%）", "fixed", "fixed", 0.10, 0.30),
        ("η自适应止损", "eta", "fixed", 0.10, 0.30),
        ("jerk反转保护止损", "jerk", "fixed", 0.10, 0.30),
        ("动能止盈", "fixed", "kinetic", 0.10, 0.30),
        ("η止损+动能止盈", "eta", "kinetic", 0.10, 0.30),
        ("综合物理止损止盈", "combo", "combo", 0.10, 0.30),
        ("宽止损+动能止盈", "eta", "kinetic", 0.15, 0.30),
    ]

    print(f"\n[4/5] 测试 {len(configs)} 种止损止盈配置...")
    print(f"\n{'='*100}")
    print(f"  纯波浪策略 - 不同止损止盈对比")
    print(f"{'='*100}")
    print(f"{'配置':<25} {'年化':>8} {'总收益':>9} {'夏普':>8} {'回撤':>8} {'Calmar':>8} {'胜率':>7} {'均仓':>6} {'SL次数':>6} {'TP次数':>6}")
    print(f"{'-'*100}")

    wave_results = {}
    for name, sl_mode, tp_mode, base_sl, base_tp in configs:
        wave_pos, wave_dir, stats = compute_wave_position_custom_tp_sl(
            prices, wave_signals, wave_confs, physics_feats,
            base_position=0.3,
            wave_conf_threshold=0.7,
            phys_conf_threshold=0.5,
            sl_mode=sl_mode,
            tp_mode=tp_mode,
            base_sl=base_sl,
            base_tp=base_tp,
        )
        m = backtest_position(wave_pos[valid_start:], wave_dir[valid_start:], prices.iloc[valid_start:])
        wave_results[name] = {"metrics": m, "stats": stats}
        print(f"{name:<25} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>8.1f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>7.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>6.2f}% {m['avg_position']:>6.3f} {stats['total_exit_by_sl']:>6} {stats['total_exit_by_tp']:>6}")

    # 止损止盈范围统计
    print(f"\n  动态止损止盈范围（最优配置）:")
    best_wave = max(wave_results.items(), key=lambda x: x[1]["metrics"]["sharpe"])[0]
    bs = wave_results[best_wave]["stats"]
    print(f"    止损范围: {bs['sl_min']*100:.1f}% ~ {bs['sl_max']*100:.1f}%, 平均: {bs['avg_sl']*100:.1f}%")
    print(f"    止盈范围: {bs['tp_min']*100:.1f}% ~ {bs['tp_max']*100:.1f}%, 平均: {bs['avg_tp']*100:.1f}%")

    # 融合策略对比
    print(f"\n{'='*100}")
    print(f"  智能融合策略 - 不同止损止盈对比（加仓50%/抄底25%）")
    print(f"{'='*100}")
    print(f"{'配置':<25} {'年化':>8} {'总收益':>9} {'夏普':>8} {'回撤':>8} {'Calmar':>8} {'均仓':>6}")
    print(f"{'-'*85}")

    fusion_results = {}
    for name, sl_mode, tp_mode, base_sl, base_tp in configs:
        wave_pos, wave_dir, stats = compute_wave_position_custom_tp_sl(
            prices, wave_signals, wave_confs, physics_feats,
            base_position=0.3,
            wave_conf_threshold=0.7,
            phys_conf_threshold=0.5,
            sl_mode=sl_mode,
            tp_mode=tp_mode,
            base_sl=base_sl,
            base_tp=base_tp,
        )
        smart_pos, smart_dir = compute_smart_fusion(v4_pos, v4_dir, wave_pos, wave_dir)
        m = backtest_position(smart_pos[valid_start:], smart_dir[valid_start:], prices.iloc[valid_start:])
        fusion_results[name] = m
        print(f"{name:<25} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>8.1f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>7.2f}% {m['calmar']:>8.4f} {m['avg_position']:>6.3f}")

    # 纯V4参考
    m_v4 = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:], prices.iloc[valid_start:])
    print(f"{'纯V4 (参考)':<25} {m_v4['ann_return']*100:>7.2f}% {m_v4['total_return']*100:>8.1f}% {m_v4['sharpe']:>8.4f} {m_v4['max_drawdown']*100:>7.2f}% {m_v4['calmar']:>8.4f} {m_v4['avg_position']:>6.3f}")

    # 增量分析
    print(f"\n{'='*100}")
    print(f"  相对基线的增量（融合策略）")
    print(f"{'='*100}")
    print(f"{'配置':<25} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'综合评分':>10}")
    print(f"{'-'*75}")

    base_m = fusion_results["基线（固定10%/30%）"]
    best_score = -999
    best_name = ""
    for name, m in fusion_results.items():
        ann_delta = (m['ann_return'] - base_m['ann_return']) * 100
        sharpe_delta = m['sharpe'] - base_m['sharpe']
        mdd_delta = (m['max_drawdown'] - base_m['max_drawdown']) * 100
        score = sharpe_delta * 0.4 + ann_delta * 0.01 * 0.3 + (-mdd_delta) * 0.01 * 0.3
        mark = " ✅" if score > 0 else ""
        if score > best_score:
            best_score = score
            best_name = name
        print(f"{name:<25} {ann_delta:>+9.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+9.2f}pp {score:>10.4f}{mark}")

    print(f"\n最优配置: {best_name} (综合评分: {best_score:.4f})")

    # 保存结果
    os.makedirs("ml/backtest_results", exist_ok=True)
    save_data = {
        "symbol": symbol,
        "wave_results": {k: {"metrics": v["metrics"], "stats": {kk: vv for kk, vv in v["stats"].items() if isinstance(vv, (int, float))}} for k, v in wave_results.items()},
        "fusion_results": fusion_results,
        "v4_baseline": m_v4,
        "best_config": best_name,
    }
    with open(f"ml/backtest_results/physics_tp_sl_{symbol.lower()}.json", "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到 ml/backtest_results/physics_tp_sl_{symbol.lower()}.json")

    return wave_results, fusion_results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="物理驱动动态止损止盈实验")
    parser.add_argument("--symbol", type=str, default="BTC")
    args = parser.parse_args()
    run_tp_sl_experiment(symbol=args.symbol)


if __name__ == "__main__":
    main()
