#!/usr/bin/env python3
"""基线对比回测：纯V4 vs 智能融合最优配置

使用实际回测引擎（backtest/engine.py）进行对比，确保结果准确。
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


def generate_v4_position(prices, symbol="BTC"):
    """生成V4减半周期策略仓位"""
    from ml.halving_top_exit_strategy import HalvingTopExitStrategy
    is_btc = (symbol == "BTC")
    strategy = HalvingTopExitStrategy(symbol=symbol, is_btc=is_btc, btc_prices=prices if is_btc else None)
    v4_series = strategy.generate_signals(prices)
    return v4_series


def generate_wave_signals(prices, zigzag_threshold=0.05):
    """生成波浪信号和置信度"""
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
    """计算物理特征"""
    from ml.physics_enhancer import PhysicsEnhancer, PhysicsEnhancerConfig
    enhancer = PhysicsEnhancer(PhysicsEnhancerConfig())
    return enhancer.compute_features(prices)


def compute_wave_position_optimal(prices, wave_signals, wave_confs, physics_feats,
                                  wave_conf_threshold=0.0, phys_conf_threshold=0.0):
    """计算波浪仓位（融合最优配置：4项物理增强 + 信号过滤可选）

    集成的物理增强：
    1. 动能力度仓位: base × (0.5 + 1.5 × kinetic_score)
    2. 仓位调节: × (0.6 + 1.0 × phys_conf)
    3. 宽追踪止损: combo模式, 范围[6%, 15%]
    4. 动能止盈: kinetic模式, 范围[13%, 50%]
    """
    from ml.physics_enhancer import PhysicsState

    n = len(prices)
    closes = prices["close"].values
    highs = prices["high"].values
    lows = prices["low"].values

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
        "avg_size_on_enter": [],
    }

    base_trailing = 0.08
    base_tp = 0.25
    trail_min, trail_max = 0.06, 0.15
    tp_min, tp_max = 0.13, 0.50
    base_position = 0.3

    for i in range(n):
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        # 信号过滤
        if sig in wave_long or sig in wave_short:
            if wave_conf < wave_conf_threshold:
                sig = "WAIT"
                stats["filtered_by_wave_conf"] += 1
        if sig in wave_long or sig in wave_short:
            pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
            if pc < phys_conf_threshold:
                sig = "WAIT"
                stats["filtered_by_phys_conf"] += 1

        # 计算动态追踪止损和止盈
        if state.direction != 0:
            ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
            rs = float(reversal_score[i]) if not np.isnan(reversal_score[i]) else 0.5
            ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
            combined = ts * 0.5 + rs * 0.3 + ks * 0.2
            trail_factor = 0.5 + 1.5 * combined
            trail_pct = np.clip(base_trailing * trail_factor, trail_min, trail_max)

            tp_factor = 0.5 + 1.5 * ks
            tp_pct = np.clip(base_tp * tp_factor, tp_min, tp_max)

            state.current_trail_pct = trail_pct
            state.current_tp_pct = tp_pct

        def compute_size():
            ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
            pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
            size = base_position * (0.5 + 1.5 * ks) * max(wave_conf, 0.5)
            multiplier = 0.6 + 1.0 * pc
            size = size * multiplier
            return float(np.clip(size, 0.0, 1.0))

        # 入场/出场信号
        if sig in wave_long:
            if state.direction != 1:
                if state.direction != 0:
                    stats["total_exit_by_signal"] += 1
                state.direction = 1
                state.entry_price = closes[i]
                state.peak_price = highs[i]
                size = compute_size()
                state.base_size = size
                state.trailing_stop_price = state.entry_price * (1 - base_trailing)
                stats["total_enter"] += 1
                stats["avg_size_on_enter"].append(size)
        elif sig in wave_short:
            if state.direction != -1:
                if state.direction != 0:
                    stats["total_exit_by_signal"] += 1
                state.direction = -1
                state.entry_price = closes[i]
                state.trough_price = lows[i]
                size = compute_size()
                state.base_size = size
                state.trailing_stop_price = state.entry_price * (1 + base_trailing)
                stats["total_enter"] += 1
                stats["avg_size_on_enter"].append(size)
        elif sig in ("EXIT_LONG", "EXIT_SHORT", "WAIT") and state.direction != 0:
            stats["total_exit_by_signal"] += 1
            state = PhysicsState()

        # 持仓中检查追踪止损和止盈
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

    stats["avg_position_size"] = np.mean(stats["avg_size_on_enter"]) if stats["avg_size_on_enter"] else 0
    return np.abs(position), np.sign(direction), stats


def compute_smart_fusion_e(v4_pos, v4_dir, wave_pos, wave_dir):
    """智能融合E(50%/25%)"""
    n = len(v4_pos)
    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)
    for i in range(n):
        v4_d = v4_dir[i]
        w_d = wave_dir[i]
        v4_p = v4_pos[i]
        w_p = wave_pos[i]

        if v4_d > 0:
            if w_d > 0:
                total = min(v4_p + w_p * 0.5, 1.0)
                fusion_pos[i] = total
                fusion_dir[i] = 1
            elif w_d < 0:
                fusion_pos[i] = v4_p * 0.8
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = v4_p
                fusion_dir[i] = 1
        elif v4_d == 0:
            if w_d > 0:
                bottom = min(w_p * 0.25, 0.3)
                fusion_pos[i] = bottom
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = 0
                fusion_dir[i] = 0
        else:
            if w_d < 0:
                fusion_pos[i] = v4_p
                fusion_dir[i] = -1
            elif w_d > 0:
                fusion_pos[i] = v4_p * 0.5
                fusion_dir[i] = -1
            else:
                fusion_pos[i] = v4_p
                fusion_dir[i] = -1
    return fusion_pos, fusion_dir


def compute_mutex_fusion(v4_pos, v4_dir, wave_pos, wave_dir, v4_threshold=0.3):
    """严格互斥融合：V4 定顶底大趋势，波浪+物理负责区间交易

    策略分工（V4 phase 直接判定 + 严格互斥）：
    - V4 position >= v4_threshold（V4 满仓/预警阶段，处于趋势/顶底时机）→ V4 主导，波浪不交易
    - V4 position < v4_threshold（V4 减仓/退出，市场进入区间震荡）→ 波浪接管，做方向性交易

    V4 仓位本身就是 phase 的最终体现：
      normal → 满仓(base_long) | warn → 0.7×base | danger → 0.3×base | peak/MA128破位 → 0
    当 v4_threshold=0.3 时：
    - normal/warn → V4 主导（仓位>=0.3）
    - danger/peak → 波浪接管（仓位<0.3 或=0）
    这样波浪能覆盖 V4 减仓的 danger phase + 完全退出的 peak phase，窗口更大。
    """
    n = len(v4_pos)
    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)

    v4_active_days = 0
    wave_active_days = 0
    idle_days = 0

    for i in range(n):
        if v4_pos[i] >= v4_threshold:
            # V4 主导（满仓/预警阶段，趋势/顶底时机）
            fusion_pos[i] = v4_pos[i]
            fusion_dir[i] = v4_dir[i]
            v4_active_days += 1
        else:
            # V4 减仓/退出 → 波浪接管区间交易
            fusion_pos[i] = wave_pos[i]
            fusion_dir[i] = wave_dir[i]
            if wave_pos[i] > 0.001:
                wave_active_days += 1
            else:
                idle_days += 1

    stats = {
        "v4_active_days": v4_active_days,
        "wave_active_days": wave_active_days,
        "idle_days": idle_days,
        "total_days": n,
        "v4_active_ratio": v4_active_days / n if n > 0 else 0,
        "wave_active_ratio": wave_active_days / n if n > 0 else 0,
        "v4_threshold": v4_threshold,
    }
    return fusion_pos, fusion_dir, stats


def run_comparison(symbol="BTC"):
    print(f"\n{'='*120}")
    print(f"  基线对比回测 — 纯V4 vs 智能融合最优配置 ({symbol})")
    print(f"{'='*120}")

    prices = load_coin_data(symbol)
    n = len(prices)
    valid_start = 365
    print(f"数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")
    print(f"有效回测期: {n-valid_start}天, {prices.index[valid_start].date()} ~ {prices.index[-1].date()}")

    print("\n[1/5] 生成V4仓位...")
    v4_series = generate_v4_position(prices, symbol)
    v4_pos = np.abs(v4_series.values)
    v4_dir = np.sign(v4_series.values)

    print("[2/5] 生成波浪信号 (ZigZag=0.05, 融合最优)...")
    t0 = time.time()
    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=0.05)
    print(f"  耗时: {time.time()-t0:.1f}s")

    print("[3/5] 计算物理特征...")
    t0 = time.time()
    physics_feats = compute_physics_features(prices)
    print(f"  耗时: {time.time()-t0:.1f}s")

    print("[4/5] 计算波浪仓位（4项物理增强，信号过滤关闭）...")
    wave_pos, wave_dir, wave_stats = compute_wave_position_optimal(
        prices, wave_signals, wave_confs, physics_feats,
        wave_conf_threshold=0.0, phys_conf_threshold=0.0,
    )
    print(f"  入场: {wave_stats['total_enter']}次, 平均仓位: {wave_stats['avg_position_size']:.3f}")
    print(f"  出场: 信号={wave_stats['total_exit_by_signal']}, 追踪止损={wave_stats['total_exit_by_trailing']}, 止盈={wave_stats['total_exit_by_tp']}")

    print("[5/6] 旧方案：智能融合E(50%/25%) 同向加仓...")
    fusion_e_pos, fusion_e_dir = compute_smart_fusion_e(v4_pos, v4_dir, wave_pos, wave_dir)

    print("[6/6] 新方案：严格互斥融合（V4仓位>=0.3时V4主导，<0.3时波浪接管）...")
    mutex_pos, mutex_dir, mutex_stats = compute_mutex_fusion(v4_pos, v4_dir, wave_pos, wave_dir, v4_threshold=0.3)
    print(f"  V4主导: {mutex_stats['v4_active_days']}天 ({mutex_stats['v4_active_ratio']*100:.1f}%)")
    print(f"  波浪接管: {mutex_stats['wave_active_days']}天 ({mutex_stats['wave_active_ratio']*100:.1f}%)")
    print(f"  空仓: {mutex_stats['idle_days']}天")

    # 使用实际回测引擎（无未来函数）
    from backtest.engine import BacktestEngine
    engine = BacktestEngine(initial_capital=10000, commission=0.0005, slippage=0.0005)

    close_prices = prices["close"]
    v4_pos_series = pd.Series(v4_pos * v4_dir, index=prices.index)
    fusion_e_pos_series = pd.Series(fusion_e_pos * fusion_e_dir, index=prices.index)
    mutex_pos_series = pd.Series(mutex_pos * mutex_dir, index=prices.index)
    wave_pos_series = pd.Series(wave_pos * wave_dir, index=prices.index)

    r_v4 = engine.run(close_prices[valid_start:], v4_pos_series[valid_start:], symbol=symbol)
    r_wave = engine.run(close_prices[valid_start:], wave_pos_series[valid_start:], symbol=symbol)
    r_fusion_e = engine.run(close_prices[valid_start:], fusion_e_pos_series[valid_start:], symbol=symbol)
    r_mutex = engine.run(close_prices[valid_start:], mutex_pos_series[valid_start:], symbol=symbol)

    def fmt(r, key, is_pct=True):
        v = r.get("metrics", {}).get(key, 0)
        if is_pct:
            return f"{v*100:>7.2f}%"
        return f"{v:>8.4f}"

    # 对比表格
    print(f"\n{'='*120}")
    print(f"  基线对比结果（使用实际回测引擎）")
    print(f"{'='*120}")
    print(f"{'策略':<40} {'年化':>8} {'总收益':>9} {'夏普':>8} {'回撤':>8} {'Calmar':>8} {'交易':>6} {'均仓':>6}")
    print(f"{'-'*95}")

    def get_metrics(r):
        m = r.get("metrics", {})
        return {
            "ann": m.get("annualized_return_pct", 0),
            "tot": m.get("total_return_pct", 0),
            "sharpe": m.get("sharpe_ratio", 0),
            "mdd": m.get("max_drawdown_pct", 0),
            "calmar": m.get("calmar_ratio", 0),
            "trades": len(r.get("trades", [])),
            "avg_pos": np.mean(np.abs(r.get("position", pd.Series([0])).values)),
        }

    m_v4 = get_metrics(r_v4)
    m_wave = get_metrics(r_wave)
    m_fusion_e = get_metrics(r_fusion_e)
    m_mutex = get_metrics(r_mutex)

    print(f"{'【基线】纯V4减半周期':<40} {m_v4['ann']:>7.2f}% {m_v4['tot']:>8.1f}% {m_v4['sharpe']:>8.4f} {m_v4['mdd']:>7.2f}% {m_v4['calmar']:>8.4f} {m_v4['trades']:>6} {m_v4['avg_pos']:>6.3f}")
    print(f"{'纯波浪策略（4项物理增强）':<40} {m_wave['ann']:>7.2f}% {m_wave['tot']:>8.1f}% {m_wave['sharpe']:>8.4f} {m_wave['mdd']:>7.2f}% {m_wave['calmar']:>8.4f} {m_wave['trades']:>6} {m_wave['avg_pos']:>6.3f}")
    print(f"{'【旧】智能融合E(50%/25%)同向加仓':<40} {m_fusion_e['ann']:>7.2f}% {m_fusion_e['tot']:>8.1f}% {m_fusion_e['sharpe']:>8.4f} {m_fusion_e['mdd']:>7.2f}% {m_fusion_e['calmar']:>8.4f} {m_fusion_e['trades']:>6} {m_fusion_e['avg_pos']:>6.3f}")
    print(f"{'【新】严格互斥融合(V4定顶底+波浪区间)':<40} {m_mutex['ann']:>7.2f}% {m_mutex['tot']:>8.1f}% {m_mutex['sharpe']:>8.4f} {m_mutex['mdd']:>7.2f}% {m_mutex['calmar']:>8.4f} {m_mutex['trades']:>6} {m_mutex['avg_pos']:>6.3f}")

    # 增量分析（新方案 vs V4 基线）
    print(f"\n{'='*120}")
    print(f"  增量分析（新互斥融合 vs 纯V4基线）")
    print(f"{'='*120}")
    ann_delta = m_mutex['ann'] - m_v4['ann']
    sharpe_delta = m_mutex['sharpe'] - m_v4['sharpe']
    mdd_delta = m_mutex['mdd'] - m_v4['mdd']
    calmar_delta = m_mutex['calmar'] - m_v4['calmar']
    print(f"  年化收益增量:   {ann_delta:>+7.2f}pp")
    print(f"  夏普比增量:     {sharpe_delta:>+7.4f}")
    print(f"  回撤变化:       {mdd_delta:>+7.2f}pp")
    print(f"  Calmar比增量:   {calmar_delta:>+7.4f}")

    # 新旧融合对比
    print(f"\n{'='*120}")
    print(f"  新旧融合方案对比")
    print(f"{'='*120}")
    ann_diff = m_mutex['ann'] - m_fusion_e['ann']
    sharpe_diff = m_mutex['sharpe'] - m_fusion_e['sharpe']
    mdd_diff = m_mutex['mdd'] - m_fusion_e['mdd']
    print(f"  年化收益差:     {ann_diff:>+7.2f}pp  (新互斥 vs 旧融合E)")
    print(f"  夏普比差:       {sharpe_diff:>+7.4f}")
    print(f"  回撤差:         {mdd_diff:>+7.2f}pp")

    # 与历史最优对比
    print(f"\n{'='*120}")
    print(f"  与历史最优（简化脚本58.42%，含未来函数偏差）对比")
    print(f"{'='*120}")
    best_ann = 58.42
    curr_ann = m_mutex['ann']
    diff = curr_ann - best_ann
    print(f"  新互斥融合年化: {curr_ann:.2f}%")
    print(f"  历史最优年化:   {best_ann:.2f}% (含未来函数偏差，不可信)")
    print(f"  差值:           {diff:+.2f}pp")
    print(f"  注: 历史最优来自简化脚本(当期仓位×当期收益)，实际引擎已证伪")

    # 保存结果
    os.makedirs("ml/backtest_results", exist_ok=True)
    save_data = {
        "symbol": symbol,
        "valid_days": n - valid_start,
        "date_range": [str(prices.index[valid_start].date()), str(prices.index[-1].date())],
        "v4_baseline": m_v4,
        "wave_only": m_wave,
        "fusion_e_old": m_fusion_e,
        "fusion_mutex_new": m_mutex,
        "mutex_stats": mutex_stats,
        "wave_stats": {k: float(v) if isinstance(v, (int, float, np.floating)) else v for k, v in wave_stats.items()},
        "delta_mutex_vs_v4": {
            "annualized_return_pct": ann_delta,
            "sharpe_ratio": sharpe_delta,
            "max_drawdown_pct": mdd_delta,
            "calmar_ratio": calmar_delta,
        },
        "delta_mutex_vs_fusion_e": {
            "annualized_return_pct": ann_diff,
            "sharpe_ratio": sharpe_diff,
            "max_drawdown_pct": mdd_diff,
        },
    }
    out_path = f"ml/backtest_results/baseline_comparison_{symbol.lower()}.json"
    with open(out_path, "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到 {out_path}")
    return save_data


def main():
    import argparse
    parser = argparse.ArgumentParser(description="基线对比回测")
    parser.add_argument("--symbol", type=str, default="BTC")
    args = parser.parse_args()
    run_comparison(symbol=args.symbol)


if __name__ == "__main__":
    main()
