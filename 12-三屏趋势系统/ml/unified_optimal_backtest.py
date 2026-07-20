#!/usr/bin/env python3
"""统一最优配置回测 — 将所有有益探索组合在一起验证

历史最优数据对比：
- 纯V4基线:          年化53.93%, 夏普1.3585, 回撤-44.37%
- 智能融合E(默认参数): 年化58.42%, 夏普1.4066, 回撤-43.18%
- 最优参数(ZZ=0.03):  年化57.23%, 夏普1.4034, 回撤-42.80%
- 宽追踪+动能止盈:    年化56.61%, 夏普1.3914, 回撤-44.15%
- 动能力度仓位:       年化56.76%, 夏普1.3939, 回撤-44.13%

目标：将所有最优配置组合，验证是否达到或超过历史最优
"""
import os, sys, json, time
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
    from ml.physics_enhancer import PhysicsEnhancer, PhysicsEnhancerConfig
    enhancer = PhysicsEnhancer(PhysicsEnhancerConfig())
    return enhancer.compute_features(prices)


def compute_wave_position_all_optimal(
    prices, wave_signals, wave_confs, physics_feats,
    base_position=0.3,
    wave_conf_threshold=0.7,
    phys_conf_threshold=0.5,
    sizing_mode="kinetic",
    trailing_mode="combo",
    take_profit_mode="kinetic",
    base_trailing_pct=0.08,
    base_take_profit_pct=0.25,
    trail_min=0.06, trail_max=0.15,
    tp_min=0.13, tp_max=0.50,
):
    """全部最优配置组合的波浪仓位计算

    集成所有有益探索：
    1. ZigZag=0.03 (在调用方生成信号时已使用)
    2. 波浪置信度过滤 >= 0.7
    3. 物理置信度过滤 >= 0.5
    4. 动能力度仓位: base × (0.5 + 1.5 × kinetic_score)
    5. 仓位调节: × (0.6 + 1.0 × phys_conf)
    6. 宽追踪止损: combo模式, 范围[6%, 15%]
    7. 动能止盈: kinetic模式, 范围[13%, 50%]
    """
    from ml.physics_enhancer import PhysicsState

    n = len(prices)
    closes = prices["close"].values
    highs = prices["high"].values
    lows = prices["low"].values

    eta_series = physics_feats["eta"]
    phys_conf = physics_feats["phys_conf"]
    trend_score = physics_feats["trend_score"]
    reversal_score = physics_feats["reversal_score"]
    kinetic_score = physics_feats["kinetic_score"]

    position = np.zeros(n)
    direction = np.zeros(n)

    state = PhysicsState()
    wave_long = ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
    wave_short = ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")

    stats = {
        "total_enter": 0, "total_exit_by_trailing": 0,
        "total_exit_by_tp": 0, "total_exit_by_signal": 0,
        "filtered_by_wave_conf": 0, "filtered_by_phys_conf": 0,
    }

    for i in range(n):
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        # === Layer 1: 双重信号过滤 ===
        if sig in wave_long or sig in wave_short:
            if wave_conf < wave_conf_threshold:
                sig = "WAIT"
                stats["filtered_by_wave_conf"] += 1
        if sig in wave_long or sig in wave_short:
            pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
            if pc < phys_conf_threshold:
                sig = "WAIT"
                stats["filtered_by_phys_conf"] += 1

        # === 计算动态追踪止损和止盈 ===
        if state.direction != 0:
            # 宽追踪止损（combo模式）
            ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
            rs = float(reversal_score[i]) if not np.isnan(reversal_score[i]) else 0.5
            ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
            combined = ts * 0.5 + rs * 0.3 + ks * 0.2
            trail_factor = 0.5 + 1.5 * combined
            trail_pct = np.clip(base_trailing_pct * trail_factor, trail_min, trail_max)

            # 动能止盈
            tp_factor = 0.5 + 1.5 * ks
            tp_pct = np.clip(base_take_profit_pct * tp_factor, tp_min, tp_max)

            state.current_trail_pct = trail_pct
            state.current_tp_pct = tp_pct

        # === 入场逻辑 ===
        def compute_size():
            """动能力度仓位 + 物理置信度调节"""
            ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
            pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
            # 动能力度仓位
            size = base_position * (0.5 + 1.5 * ks) * max(wave_conf, 0.5)
            # 物理置信度仓位调节
            multiplier = 0.6 + 1.0 * pc
            size = size * multiplier
            return float(np.clip(size, 0.1, 1.0))

        if sig in wave_long:
            if state.direction != 1:
                if state.direction != 0:
                    stats["total_exit_by_signal"] += 1
                state.direction = 1
                state.entry_price = closes[i]
                state.peak_price = highs[i]
                state.base_size = compute_size()
                state.trailing_stop_price = state.entry_price * (1 - base_trailing_pct)
                stats["total_enter"] += 1
        elif sig in wave_short:
            if state.direction != -1:
                if state.direction != 0:
                    stats["total_exit_by_signal"] += 1
                state.direction = -1
                state.entry_price = closes[i]
                state.trough_price = lows[i]
                state.base_size = compute_size()
                state.trailing_stop_price = state.entry_price * (1 + base_trailing_pct)
                stats["total_enter"] += 1
        elif sig in ("EXIT_LONG", "EXIT_SHORT", "WAIT") and state.direction != 0:
            stats["total_exit_by_signal"] += 1
            state = PhysicsState()

        # === 持仓中：更新追踪止损并检查触发 ===
        if state.direction == 1 and state.entry_price > 0:
            state.peak_price = max(state.peak_price, highs[i])
            new_trail = state.peak_price * (1 - state.current_trail_pct)
            if new_trail > state.trailing_stop_price:
                state.trailing_stop_price = new_trail

            if lows[i] <= state.trailing_stop_price:
                stats["total_exit_by_trailing"] += 1
                state = PhysicsState()
                continue

            tp_price = state.entry_price * (1 + state.current_tp_pct)
            if highs[i] >= tp_price:
                stats["total_exit_by_tp"] += 1
                state = PhysicsState()
                continue

            position[i] = state.base_size
            direction[i] = 1

        elif state.direction == -1 and state.entry_price > 0:
            state.trough_price = min(state.trough_price, lows[i])
            new_trail = state.trough_price * (1 + state.current_trail_pct)
            if new_trail < state.trailing_stop_price or state.trailing_stop_price == 0:
                state.trailing_stop_price = new_trail

            if highs[i] >= state.trailing_stop_price:
                stats["total_exit_by_trailing"] += 1
                state = PhysicsState()
                continue

            tp_price = state.entry_price * (1 - state.current_tp_pct)
            if lows[i] <= tp_price:
                stats["total_exit_by_tp"] += 1
                state = PhysicsState()
                continue

            position[i] = state.base_size
            direction[i] = -1

    return np.abs(position), np.sign(position), stats


def compute_smart_fusion(v4_pos, v4_dir, wave_pos, wave_dir,
                         add_ratio=0.5, bottom_ratio=0.25, max_position=1.0):
    """智能融合E参数（50%/25%）"""
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
    return {
        "ann_return": float(ann_ret),
        "total_return": float(cum_ret[-1]),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "avg_position": float(np.mean(position)),
    }


def run_unified_optimal(symbol="BTC"):
    print(f"\n{'='*120}")
    print(f"  统一最优配置回测 — 所有有益探索组合验证 ({symbol})")
    print(f"{'='*120}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    print("\n[1/5] 生成波浪信号 (ZigZag=0.03)...")
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

    print("[4/5] 计算全部最优配置的波浪仓位...")
    wave_pos, wave_dir, wave_stats = compute_wave_position_all_optimal(
        prices, wave_signals, wave_confs, physics_feats,
        base_position=0.3,
        wave_conf_threshold=0.7,
        phys_conf_threshold=0.5,
        sizing_mode="kinetic",
        trailing_mode="combo",
        take_profit_mode="kinetic",
        base_trailing_pct=0.08,
        base_take_profit_pct=0.25,
        trail_min=0.06, trail_max=0.15,
        tp_min=0.13, tp_max=0.50,
    )

    print(f"  波浪统计: 入场={wave_stats['total_enter']}, 追踪止损={wave_stats['total_exit_by_trailing']}, "
          f"止盈={wave_stats['total_exit_by_tp']}, 信号退出={wave_stats['total_exit_by_signal']}")
    print(f"  过滤统计: 波浪置信度={wave_stats['filtered_by_wave_conf']}, 物理置信度={wave_stats['filtered_by_phys_conf']}")

    print("[5/5] 智能融合E (50%/25%) + 回测...")
    fusion_pos, fusion_dir = compute_smart_fusion(v4_pos, v4_dir, wave_pos, wave_dir,
                                                   add_ratio=0.5, bottom_ratio=0.25)

    valid_start = 365
    m_v4 = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:], prices.iloc[valid_start:])
    m_wave = backtest_position(wave_pos[valid_start:], wave_dir[valid_start:], prices.iloc[valid_start:])
    m_fusion = backtest_position(fusion_pos[valid_start:], fusion_dir[valid_start:], prices.iloc[valid_start:])

    # 对比表格
    print(f"\n{'='*120}")
    print(f"  统一最优配置回测结果")
    print(f"{'='*120}")
    print(f"{'策略':<45} {'年化':>8} {'总收益':>9} {'夏普':>8} {'回撤':>8} {'Calmar':>8} {'均仓':>6}")
    print(f"{'-'*100}")

    # 历史最优数据对比
    print(f"{'[历史] 纯V4基线':<45} {53.93:>7.2f}% {2757:>8.0f}% {1.3585:>8.4f} {-44.37:>7.2f}% {1.2155:>8.4f} {0.606:>6.3f}")
    print(f"{'[历史] 智能融合E(默认参数ZZ=0.05)':<45} {58.42:>7.2f}% {3474:>8.0f}% {1.4066:>8.4f} {-43.18:>7.2f}% {1.3529:>8.4f} {0.611:>6.3f}")
    print(f"{'[历史] 最优参数(ZZ=0.03,融合40/20)':<45} {57.23:>7.2f}% {3269:>8.0f}% {1.4034:>8.4f} {-42.80:>7.2f}% {1.3370:>8.4f} {0.602:>6.3f}")
    print(f"{'[历史] 宽追踪+动能止盈(融合50/25)':<45} {56.61:>7.2f}% {3167:>8.0f}% {1.3914:>8.4f} {-44.15:>7.2f}% {1.2823:>8.4f} {0.602:>6.3f}")
    print(f"{'[历史] 动能力度仓位(融合50/25)':<45} {56.76:>7.2f}% {3192:>8.0f}% {1.3939:>8.4f} {-44.13:>7.2f}% {1.2862:>8.4f} {0.602:>6.3f}")
    print(f"{'-'*100}")

    print(f"{'[本次] 纯V4':<45} {m_v4['ann_return']*100:>7.2f}% {m_v4['total_return']*100:>8.0f}% {m_v4['sharpe']:>8.4f} {m_v4['max_drawdown']*100:>7.2f}% {m_v4['calmar']:>8.4f} {m_v4['avg_position']:>6.3f}")
    print(f"{'[本次] 纯波浪(全部最优)':<45} {m_wave['ann_return']*100:>7.2f}% {m_wave['total_return']*100:>8.0f}% {m_wave['sharpe']:>8.4f} {m_wave['max_drawdown']*100:>7.2f}% {m_wave['calmar']:>8.4f} {m_wave['avg_position']:>6.3f}")
    print(f"{'[本次] 智能融合E(全部最优组合)':<45} {m_fusion['ann_return']*100:>7.2f}% {m_fusion['total_return']*100:>8.0f}% {m_fusion['sharpe']:>8.4f} {m_fusion['max_drawdown']*100:>7.2f}% {m_fusion['calmar']:>8.4f} {m_fusion['avg_position']:>6.3f}")

    # 增量分析
    print(f"\n{'='*120}")
    print(f"  增量分析（相对纯V4基线）")
    print(f"{'='*120}")
    ann_delta = (m_fusion['ann_return'] - m_v4['ann_return']) * 100
    sharpe_delta = m_fusion['sharpe'] - m_v4['sharpe']
    mdd_delta = (m_fusion['max_drawdown'] - m_v4['max_drawdown']) * 100
    calmar_delta = m_fusion['calmar'] - m_v4['calmar']
    print(f"  年化增量:   {ann_delta:>+7.2f}pp  (目标: >+2.83pp 即超越历史最优58.42%)")
    print(f"  夏普增量:   {sharpe_delta:>+7.4f}")
    print(f"  回撤改善:   {mdd_delta:>+7.2f}pp")
    print(f"  Calmar增量: {calmar_delta:>+7.4f}")

    # 是否超越历史最优
    print(f"\n{'='*120}")
    print(f"  历史最优对比")
    print(f"{'='*120}")
    best_ann = 58.42
    best_sharpe = 1.4066
    curr_ann = m_fusion['ann_return'] * 100
    curr_sharpe = m_fusion['sharpe']
    print(f"  年化收益:  当前={curr_ann:.2f}%  历史最优={best_ann:.2f}%  {'✅ 超越' if curr_ann >= best_ann else '❌ 未超越'} (差值={curr_ann-best_ann:+.2f}pp)")
    print(f"  夏普比:    当前={curr_sharpe:.4f}  历史最优={best_sharpe:.4f}  {'✅ 超越' if curr_sharpe >= best_sharpe else '❌ 未超越'} (差值={curr_sharpe-best_sharpe:+.4f})")

    # 保存
    os.makedirs("ml/backtest_results", exist_ok=True)
    save_data = {
        "symbol": symbol,
        "config": {
            "zigzag_threshold": 0.03,
            "wave_conf_threshold": 0.7,
            "phys_conf_threshold": 0.5,
            "sizing_mode": "kinetic",
            "trailing_mode": "combo",
            "take_profit_mode": "kinetic",
            "base_trailing_pct": 0.08,
            "base_take_profit_pct": 0.25,
            "trail_range": [0.06, 0.15],
            "tp_range": [0.13, 0.50],
            "fusion_add_ratio": 0.5,
            "fusion_bottom_ratio": 0.25,
        },
        "wave_stats": wave_stats,
        "v4_baseline": m_v4,
        "wave_optimal": m_wave,
        "fusion_optimal": m_fusion,
        "history_best": {"ann_return": 0.5842, "sharpe": 1.4066},
    }
    with open(f"ml/backtest_results/unified_optimal_{symbol.lower()}.json", "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到 ml/backtest_results/unified_optimal_{symbol.lower()}.json")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="统一最优配置回测")
    parser.add_argument("--symbol", type=str, default="BTC")
    args = parser.parse_args()
    run_unified_optimal(symbol=args.symbol)


if __name__ == "__main__":
    main()
