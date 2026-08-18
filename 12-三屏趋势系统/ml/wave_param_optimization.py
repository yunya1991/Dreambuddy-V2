#!/usr/bin/env python3
"""
波浪信号参数寻优 + 物理评估器集成
寻优维度：
1. ZigZag阈值：0.03/0.05/0.07/0.10
2. 波浪置信度入场阈值：0.4/0.5/0.6/0.7
3. 物理置信度过滤阈值：0.0(关闭)/0.3/0.4/0.5
4. 物理置信度权重组合：4种

物理评估器作用：
- 入场过滤：物理置信度 < 阈值时，拒绝波浪入场信号
- 仓位调节：物理置信度高时加仓，低时减仓
"""
import os
import sys
import json
import time
import itertools
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


def compute_v4_position(prices, symbol="BTC"):
    from ml.halving_top_exit_strategy import HalvingTopExitStrategy
    is_btc = (symbol == "BTC")
    strategy = HalvingTopExitStrategy(
        symbol=symbol, is_btc=is_btc,
        btc_prices=prices if is_btc else None,
    )
    position_series = strategy.generate_signals(prices)
    position_arr = position_series.values if hasattr(position_series, 'values') else np.array(position_series)
    return np.abs(position_arr), np.sign(position_arr)


def generate_wave_signals_with_params(prices, zigzag_threshold=0.05):
    """生成波浪信号（带参数）"""
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
    """预计算物理特征（只计算一次）"""
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


def compute_wave_position_with_physics_filter(
    prices, wave_signals, wave_confs, physics_feats,
    base_position=0.3,
    wave_conf_threshold=0.5,
    phys_conf_threshold=0.0,
    use_physics_position_adjust=True,
):
    """计算波浪仓位（带物理过滤和调节）

    参数：
    - wave_conf_threshold: 波浪置信度入场阈值，低于此值不入场
    - phys_conf_threshold: 物理置信度过滤阈值，低于此值不入场（0=关闭）
    - use_physics_position_adjust: 是否用物理置信度调节仓位大小
    """
    n = len(prices)
    closes = prices["close"].values

    eta_series = physics_feats["eta"]
    phys_conf = physics_feats["phys_conf"]

    position = np.zeros(n)
    direction = np.zeros(n)

    current_pos = 0.0
    current_dir = 0
    current_entry = 0.0
    stop_loss_pct = 0.10
    take_profit_pct = 0.30

    wave_long_signals = ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
    wave_short_signals = ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")

    stats = {
        "total_enter": 0, "filtered_by_wave_conf": 0,
        "filtered_by_phys_conf": 0, "total_exit": 0,
    }

    for i in range(n):
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        # 波浪置信度过滤
        if sig in wave_long_signals or sig in wave_short_signals:
            if wave_conf < wave_conf_threshold:
                sig = "WAIT"
                stats["filtered_by_wave_conf"] += 1

        # 物理置信度过滤
        if sig in wave_long_signals or sig in wave_short_signals:
            pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
            if pc < phys_conf_threshold:
                sig = "WAIT"
                stats["filtered_by_phys_conf"] += 1

        if sig in wave_long_signals:
            if current_dir != 1:
                new_pos = base_position * max(wave_conf, 0.5)
                # 物理置信度调节仓位
                if use_physics_position_adjust:
                    pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
                    multiplier = 0.6 + 1.0 * pc
                    new_pos = new_pos * multiplier
                new_pos = min(new_pos, 1.0)

                if current_dir != 0:
                    current_pos = 0.0
                    current_dir = 0
                    stats["total_exit"] += 1

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
                    stats["total_exit"] += 1

                current_pos = new_pos
                current_dir = -1
                current_entry = closes[i]
                stats["total_enter"] += 1

        elif sig in ("EXIT_LONG", "EXIT_SHORT", "WAIT") and current_dir != 0:
            current_pos = 0.0
            current_dir = 0
            stats["total_exit"] += 1

        # 止损止盈
        if current_dir == 1 and current_entry > 0:
            pnl = (closes[i] - current_entry) / current_entry
            if pnl <= -stop_loss_pct or pnl >= take_profit_pct:
                current_pos = 0.0
                current_dir = 0
                stats["total_exit"] += 1
        elif current_dir == -1 and current_entry > 0:
            pnl = (current_entry - closes[i]) / current_entry
            if pnl <= -stop_loss_pct or pnl >= take_profit_pct:
                current_pos = 0.0
                current_dir = 0
                stats["total_exit"] += 1

        position[i] = current_pos * current_dir if current_dir != 0 else 0
        direction[i] = current_dir

    abs_position = np.abs(position)
    direction_arr = np.sign(position)

    return abs_position, direction_arr, stats


def compute_smart_fusion(v4_pos, v4_dir, wave_pos, wave_dir,
                         add_ratio=0.3, bottom_ratio=0.2, max_position=1.0):
    """智能融合：V4定方向 + 波浪择时加仓"""
    n = len(v4_pos)
    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)

    for i in range(n):
        v4_p = v4_pos[i] * v4_dir[i]
        v4_d = v4_dir[i]
        w_p = wave_pos[i] * wave_dir[i]
        w_d = wave_dir[i]

        if v4_d > 0:  # V4多头
            if w_d > 0:  # 波浪也看多 → 加仓
                total = v4_p + w_p * add_ratio
                total = min(total, max_position)
                fusion_pos[i] = abs(total)
                fusion_dir[i] = 1
            elif w_d < 0:  # 波浪看空 → 减仓
                fusion_pos[i] = abs(v4_p) * 0.8
                fusion_dir[i] = 1
            else:  # 波浪中性 → 保持
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = 1

        elif v4_d == 0:  # V4空仓
            if w_d > 0:  # 波浪看多 → 轻仓抄底
                bottom = w_p * bottom_ratio
                bottom = min(bottom, 0.3)
                fusion_pos[i] = bottom
                fusion_dir[i] = 1
            elif w_d < 0:  # 波浪看空 → 保持空仓
                pass
            else:
                pass

        else:  # V4空头
            if w_d < 0:  # 波浪也看空 → 保持空头
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = -1
            elif w_d > 0:  # 波浪看多 → 空头减半
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

    return {
        "ann_return": float(ann_ret),
        "total_return": float(cum_ret[-1]),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "avg_position": float(np.mean(position)),
    }


def run_optimization(symbol="BTC"):
    """运行参数寻优"""
    print(f"\n{'='*100}")
    print(f"  波浪参数寻优 + 物理评估器集成 - {symbol}")
    print(f"{'='*100}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # 1. 计算V4仓位
    print("\n[1/4] 计算V4仓位...")
    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)

    # 2. 预计算物理特征
    print("[2/4] 计算物理特征...")
    t0 = time.time()
    physics_feats = compute_physics_features(prices)
    print(f"  物理特征计算完成, 耗时: {time.time()-t0:.1f}s")
    print(f"  eta范围: [{np.nanmin(physics_feats['eta']):.4f}, {np.nanmax(physics_feats['eta']):.4f}], 均值: {np.nanmean(physics_feats['eta']):.4f}")
    print(f"  phys_conf范围: [{np.nanmin(physics_feats['phys_conf']):.4f}, {np.nanmax(physics_feats['phys_conf']):.4f}], 均值: {np.nanmean(physics_feats['phys_conf']):.4f}")

    # 3. 寻优参数网格
    zigzag_thresholds = [0.03, 0.05, 0.07, 0.10]
    wave_conf_thresholds = [0.4, 0.5, 0.6, 0.7]
    phys_conf_thresholds = [0.0, 0.3, 0.4, 0.5]

    valid_start = 365
    fusion_add_ratio = 0.4
    fusion_bottom_ratio = 0.2

    # 4. 先对每个ZigZag阈值生成波浪信号
    print(f"\n[3/4] 生成不同ZigZag阈值的波浪信号...")
    wave_signal_cache = {}
    for zz in zigzag_thresholds:
        t0 = time.time()
        print(f"  ZigZag={zz}...", end=" ")
        sigs, confs = generate_wave_signals_with_params(prices, zigzag_threshold=zz)
        wave_signal_cache[zz] = (sigs, confs)
        long_count = np.sum(np.isin(sigs, ["ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3"]))
        short_count = np.sum(np.isin(sigs, ["ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3"]))
        print(f"耗时: {time.time()-t0:.1f}s, 多头信号: {long_count}天, 空头信号: {short_count}天")

    # 5. 网格寻优
    print(f"\n[4/4] 参数网格寻优...")
    print(f"  参数组合数: {len(zigzag_thresholds)} × {len(wave_conf_thresholds)} × {len(phys_conf_thresholds)} = {len(zigzag_thresholds)*len(wave_conf_thresholds)*len(phys_conf_thresholds)}")
    print(f"  融合参数: add_ratio={fusion_add_ratio}, bottom_ratio={fusion_bottom_ratio}")

    results = []
    best_score = -999
    best_params = None

    print(f"\n{'='*120}")
    print(f"{'ZigZag':>7} {'波浪阈值':>8} {'物理阈值':>8} {'年化':>8} {'总收益':>10} {'夏普':>8} {'回撤':>8} {'Calmar':>8} {'均仓':>7} {'评分':>8}")
    print(f"{'-'*100}")

    for zz, wc_thresh, pc_thresh in itertools.product(zigzag_thresholds, wave_conf_thresholds, phys_conf_thresholds):
        wave_signals, wave_confs = wave_signal_cache[zz]

        wave_pos, wave_dir, stats = compute_wave_position_with_physics_filter(
            prices, wave_signals, wave_confs, physics_feats,
            base_position=0.3,
            wave_conf_threshold=wc_thresh,
            phys_conf_threshold=pc_thresh,
            use_physics_position_adjust=True,
        )

        smart_pos, smart_dir = compute_smart_fusion(
            v4_pos, v4_dir, wave_pos, wave_dir,
            add_ratio=fusion_add_ratio, bottom_ratio=fusion_bottom_ratio,
        )

        m = backtest_position(smart_pos[valid_start:], smart_dir[valid_start:], prices.iloc[valid_start:])

        # 综合评分：年化*0.3 + 夏普*0.4 + Calmar*0.3
        score = m['ann_return'] * 0.3 + m['sharpe'] * 0.4 + m['calmar'] * 0.3

        results.append({
            "zigzag": zz,
            "wave_conf_threshold": wc_thresh,
            "phys_conf_threshold": pc_thresh,
            "metrics": m,
            "stats": stats,
            "score": score,
        })

        mark = ""
        if score > best_score:
            best_score = score
            best_params = (zz, wc_thresh, pc_thresh)
            mark = " ★"

        print(f"{zz:>7.2f} {wc_thresh:>8.2f} {pc_thresh:>8.2f} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>9.1f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>7.2f}% {m['calmar']:>8.4f} {m['avg_position']:>7.3f} {score:>8.4f}{mark}")

    # 排序输出Top10
    results.sort(key=lambda x: -x["score"])
    print(f"\n{'='*120}")
    print(f"  Top 10 参数组合")
    print(f"{'='*120}")
    print(f"{'排名':>4} {'ZigZag':>7} {'波浪阈值':>8} {'物理阈值':>8} {'年化':>8} {'夏普':>8} {'回撤':>8} {'Calmar':>8} {'评分':>8}")
    print(f"{'-'*80}")
    for i, r in enumerate(results[:10], 1):
        m = r["metrics"]
        print(f"{i:>4} {r['zigzag']:>7.2f} {r['wave_conf_threshold']:>8.2f} {r['phys_conf_threshold']:>8.2f} {m['ann_return']*100:>7.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>7.2f}% {m['calmar']:>8.4f} {r['score']:>8.4f}")

    # 分析物理过滤器的效果
    print(f"\n{'='*120}")
    print(f"  物理过滤器效果分析（固定 ZigZag={best_params[0]}, 波浪阈值={best_params[1]}）")
    print(f"{'='*120}")
    print(f"{'物理阈值':>8} {'入场次数':>8} {'波浪过滤':>8} {'物理过滤':>8} {'年化':>8} {'夏普':>8} {'回撤':>8}")
    print(f"{'-'*70}")
    for r in results:
        if r["zigzag"] == best_params[0] and r["wave_conf_threshold"] == best_params[1]:
            m = r["metrics"]
            s = r["stats"]
            print(f"{r['phys_conf_threshold']:>8.2f} {s['total_enter']:>8} {s['filtered_by_wave_conf']:>8} {s['filtered_by_phys_conf']:>8} {m['ann_return']*100:>7.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>7.2f}%")

    # 保存结果
    print(f"\n最优参数: ZigZag={best_params[0]}, 波浪阈值={best_params[1]}, 物理阈值={best_params[2]}")
    print(f"最优评分: {best_score:.4f}")

    os.makedirs("ml/backtest_results", exist_ok=True)
    save_data = {
        "symbol": symbol,
        "best_params": {
            "zigzag_threshold": best_params[0],
            "wave_conf_threshold": best_params[1],
            "phys_conf_threshold": best_params[2],
        },
        "best_score": best_score,
        "fusion_params": {
            "add_ratio": fusion_add_ratio,
            "bottom_ratio": fusion_bottom_ratio,
        },
        "top10": [{
            "zigzag": r["zigzag"],
            "wave_conf_threshold": r["wave_conf_threshold"],
            "phys_conf_threshold": r["phys_conf_threshold"],
            "metrics": r["metrics"],
            "score": r["score"],
        } for r in results[:10]],
    }
    with open(f"ml/backtest_results/wave_param_optimization_{symbol.lower()}.json", "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"结果已保存到 ml/backtest_results/wave_param_optimization_{symbol.lower()}.json")

    return best_params, results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="波浪参数寻优+物理评估器集成")
    parser.add_argument("--symbol", type=str, default="BTC")
    args = parser.parse_args()
    run_optimization(symbol=args.symbol)


if __name__ == "__main__":
    main()
