#!/usr/bin/env python3
"""V4+波浪策略独立回测验证

验证从三屏系统分离后的 V4+波浪策略仍保持性能优势。

对比策略：
1. 纯V4减半周期策略（基准）
2. V4+波浪互斥融合（优化参数：wave_weight=0.6, confirm_threshold=0.6, bottom_position_cap=0.5）
3. V4+波浪互斥融合 + 物理增强（动能止盈/jerk止损/动能力度仓位）
4. 买入持有

回测周期：
- 8年期（valid_start=730，前2年预热）
- 4年期（valid_start=365，前1年预热）

评估指标：年化收益、夏普比率、最大回撤、Calmar比率、胜率、均仓
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
SANPING_DIR = os.path.join(PROJECT_ROOT, "12-三屏趋势系统")
sys.path.insert(0, MODULE_DIR)
sys.path.insert(1, SANPING_DIR)

from halving_top_exit_strategy import HalvingTopExitStrategy
from ewave_recognizer import ElliottWaveRecognizer
from ewave_strategy_adapter import EWaveStrategyAdapter, WaveConfig


def load_coin_data(symbol: str) -> pd.DataFrame:
    """加载币种历史K线数据（优先使用9年数据）"""
    # 优先使用新拉取的9年数据
    nine_year_path = os.path.join(MODULE_DIR, "data", f"{symbol}_1D_9year.json")
    original_path = os.path.join(SANPING_DIR, "data", "historical", f"{symbol}_1D_730d.json")

    path = nine_year_path if os.path.exists(nine_year_path) else original_path
    with open(path) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )
    return prices


def calc_metrics(prices, position_arr, valid_start=0, cost_pct=0.001):
    """计算回测指标（含交易成本）

    Args:
        prices: OHLCV DataFrame
        position_arr: 仓位序列（带方向，正=多头，负=空头，0=空仓）
        valid_start: 有效数据起始索引（预热期）
        cost_pct: 单边交易成本（默认0.1%）
    """
    n = len(prices)
    closes = prices["close"].values

    daily_returns = np.zeros(n)
    for i in range(1, n):
        daily_returns[i] = position_arr[i - 1] * (closes[i] / closes[i - 1] - 1)

    # 交易成本
    pos_change = np.abs(np.diff(np.concatenate([[0], position_arr])))
    cost = pos_change * cost_pct
    daily_returns_net = daily_returns - cost

    valid_returns = daily_returns_net[valid_start:]
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

    entries = np.sum((np.abs(position_arr[valid_start:]) > 0.01) &
                     (np.abs(np.concatenate([[0], position_arr[valid_start:-1]])) <= 0.01))

    return {
        "total_return": float(total_return),
        "annualized": float(annualized),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "win_rate": float(win_rate),
        "avg_position": float(avg_pos),
        "valid_days": int(valid_days),
        "trades": int(entries),
    }


def compute_v4_positions(prices, symbol="BTC"):
    """计算V4减半周期策略仓位"""
    print(f"  [V4] 计算 {symbol} V4减半周期策略...")
    t0 = time.time()

    is_btc = (symbol == "BTC")
    strategy = HalvingTopExitStrategy(
        symbol=symbol,
        is_btc=is_btc,
        btc_prices=prices if is_btc else None,
    )

    position_series = strategy.generate_signals(prices)
    position_arr = position_series.values if hasattr(position_series, 'values') else np.array(position_series)

    print(f"    耗时: {time.time()-t0:.1f}s, 平均仓位: {np.mean(np.abs(position_arr)):.3f}")
    return position_arr


def generate_wave_signals(prices, zigzag_threshold=0.05):
    """预计算波浪信号（滚动识别）"""
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

        if i % 500 == 0 and i > 0:
            print(f"    波浪识别进度 {i}/{n} ({i/n*100:.1f}%)")

        slice_df = prices.iloc[:i + 1]
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


def compute_v4_wave_fusion(prices, v4_positions, wave_signals, wave_confs,
                           wave_weight=0.6, confirm_threshold=0.6,
                           bottom_position_cap=0.5, total_position_cap=1.0,
                           keep_v4_dip_buy=True):
    """V4+波浪互斥融合（与 EWaveStrategyAdapter._fuse_positions 一致的规则）

    融合规则：
    1. V4多头 + 波浪看多(≥阈值) → V4仓位 + wave_weight × wave_conf
    2. V4多头 + 波浪中性/看空 → 保持V4仓位
    3. V4空仓 + 波浪看多(≥阈值) → min(wave_weight×wave_conf, bottom_position_cap)
       - keep_v4_dip_buy=True: V4有dip_buy仓位时保留V4仓位
    4. V4空仓 + 波浪中性/看空 → 空仓观望
       - keep_v4_dip_buy=True: V4有dip_buy仓位时保留V4仓位
    5. V4空头 + 波浪看多(≥阈值) → V4空头仓位减半
    6. V4空头 + 波浪中性/看空 → 保持V4空头
    """
    n = len(prices)
    fused_positions = np.zeros(n)

    stats = {"bull_add": 0, "bull_keep": 0, "empty_bottom": 0, "empty_keep_dip": 0,
             "empty_wait": 0, "bear_reduce": 0, "bear_keep": 0}

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
                stats["bull_add"] += 1
            else:
                fused = v4_pos
                stats["bull_keep"] += 1

        elif v4_sign == -1:
            if wave_dir == "LONG" and wave_conf >= confirm_threshold:
                fused = v4_pos * 0.5
                stats["bear_reduce"] += 1
            else:
                fused = v4_pos
                stats["bear_keep"] += 1

        else:
            if wave_dir == "LONG" and wave_conf >= confirm_threshold:
                wave_pos = min(wave_weight * wave_conf, bottom_position_cap)
                fused = wave_pos
                stats["empty_bottom"] += 1
            elif keep_v4_dip_buy and v4_abs > 0.001:
                fused = v4_pos
                stats["empty_keep_dip"] += 1
            else:
                fused = 0.0
                stats["empty_wait"] += 1

        fused_positions[i] = fused

    print(f"    [融合统计] 多头+加仓={stats['bull_add']} | 多头+保持={stats['bull_keep']} | "
          f"空仓+抄底={stats['empty_bottom']} | 空仓+保留dip={stats['empty_keep_dip']} | "
          f"空仓+观望={stats['empty_wait']} | 空头+减半={stats['bear_reduce']} | 空头+保持={stats['bear_keep']}")

    return fused_positions


def compute_v4_wave_fusion_with_physics(prices, v4_positions, wave_signals, wave_confs,
                                        wave_weight=0.6, confirm_threshold=0.6,
                                        bottom_position_cap=0.5, keep_v4_dip_buy=True):
    """V4+波浪互斥融合 + 物理引擎增强

    物理增强：
    - 动能力度仓位：η < eta_weak 时，仓位 × (lower + scale × phys_conf)
    - 宽追踪止损：jerk反转信号触发止盈保护
    - 动能止盈：动能峰值触发提前止盈
    """
    from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
    from ml.pitd_kinematics_engineer import KinematicsEngineer
    from ml.pitd_dynamics_engineer import DynamicsEngineer

    print(f"  [物理增强] 计算物理特征...")
    t0 = time.time()

    n = len(prices)
    closes = prices["close"].values

    # 物理特征（pandas兼容性处理）
    try:
        kin_fe = KinematicsEngineer()
        dyn_fe = DynamicsEngineer()
        kin_feats = kin_fe.extract_series(prices)
        dyn_feats = dyn_fe.extract_series(prices, kin_feats)

        eta_series = dyn_feats["dyn_coupling_eta"].values

        weights = ConfidenceWeights(
            w_eta=0.211, w_reversal=0.368,
            w_support=0.211, w_kinetic=0.211,
            position_lower=0.6, position_scale=1.0,
        )
        scorer = PhysicsConfidenceScorer(weights)
        ml_pred_neutral = np.full(n, 0.5)
        phys_conf, _ = scorer.score_signals(prices=prices, ml_predictions=ml_pred_neutral)

        # jerk 反转信号
        jerk_series = kin_feats.get("jerk", pd.Series(np.zeros(n))).values if hasattr(kin_feats.get("jerk"), 'values') else np.zeros(n)
        kinetic_series = kin_feats.get("kinetic_score", pd.Series(np.full(n, 0.5))).values if hasattr(kin_feats.get("kinetic_score"), 'values') else np.full(n, 0.5)

        print(f"    物理特征计算完成，耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        print(f"    ⚠️ 物理特征计算失败({e})，回退到无物理增强模式")
        eta_series = np.full(n, 1.0)
        phys_conf = np.full(n, 0.5)
        jerk_series = np.zeros(n)
        kinetic_series = np.full(n, 0.5)

    # 基础融合
    fused = compute_v4_wave_fusion(
        prices, v4_positions, wave_signals, wave_confs,
        wave_weight=wave_weight,
        confirm_threshold=confirm_threshold,
        bottom_position_cap=bottom_position_cap,
        keep_v4_dip_buy=keep_v4_dip_buy,
    )

    # 物理增强
    eta_weak = 0.10
    position_lower = 0.6
    position_scale = 1.0

    enhanced = fused.copy()

    for i in range(n):
        pos = enhanced[i]

        # 1. 动能力度仓位：弱趋势时调节
        if not np.isnan(eta_series[i]) and eta_series[i] < eta_weak:
            multiplier = position_lower + position_scale * phys_conf[i]
            enhanced[i] = pos * multiplier

        # 2. jerk反转止盈保护：jerk突然增大时减仓
        if i > 0 and not np.isnan(jerk_series[i]) and abs(jerk_series[i]) > np.nanpercentile(np.abs(jerk_series), 95):
            if pos > 0.3:
                enhanced[i] = pos * 0.7  # 减仓30%

        # 3. 动能止盈：动能极高时锁定利润
        if not np.isnan(kinetic_series[i]) and kinetic_series[i] > 0.85:
            if pos > 0.5:
                enhanced[i] = pos * 0.8  # 减仓20%

    return enhanced


def run_backtest(symbol="BTC"):
    """运行9年完整回测对比"""
    print(f"\n{'='*90}")
    print(f"  V4+波浪策略独立模块 9年回测验证 - {symbol}")
    print(f"  模块: 17-v4-wave-strategy (完全独立)")
    print(f"{'='*90}")

    prices = load_coin_data(symbol)
    n = len(prices)
    years = n / 365.25
    print(f"\n数据: {n}天 ({years:.2f}年), {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # 计算V4仓位
    v4_positions = compute_v4_positions(prices, symbol=symbol)

    # 计算波浪信号
    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=0.05)

    # ===== 9年期回测（valid_start=730, 2年预热）=====
    valid_start = 730
    valid_days = n - valid_start
    valid_years = valid_days / 365.25

    # ===== 含交易成本（0.1%/侧）=====
    print(f"\n{'='*90}")
    print(f"  9年期回测 — 含交易成本 (valid_start={valid_start}, 有效{valid_days}天/{valid_years:.1f}年)")
    print(f"{'='*90}")
    print(f"{'策略':<36} {'年化':>8} {'总收益':>10} {'夏普':>8} {'回撤':>10} {'Calmar':>8} {'胜率':>8} {'均仓':>7}")
    print(f"{'-'*100}")

    results_cost = {}

    m = calc_metrics(prices, v4_positions, valid_start, cost_pct=0.001)
    results_cost["纯V4"] = m
    print(f"{'纯V4减半周期':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    print(f"\n  --- V4+波浪互斥融合（默认参数 wave_weight=0.3, threshold=0.6, cap=0.3）---")
    fused_default = compute_v4_wave_fusion(
        prices, v4_positions, wave_signals, wave_confs,
        wave_weight=0.3, confirm_threshold=0.6, bottom_position_cap=0.3,
    )
    m = calc_metrics(prices, fused_default, valid_start, cost_pct=0.001)
    results_cost["V4+波浪(默认)"] = m
    print(f"{'V4+波浪(默认参数)':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    print(f"\n  --- V4+波浪互斥融合（优化参数 wave_weight=0.6, threshold=0.6, cap=0.5）---")
    fused_opt = compute_v4_wave_fusion(
        prices, v4_positions, wave_signals, wave_confs,
        wave_weight=0.6, confirm_threshold=0.6, bottom_position_cap=0.5,
    )
    m = calc_metrics(prices, fused_opt, valid_start, cost_pct=0.001)
    results_cost["V4+波浪(优化)"] = m
    print(f"{'V4+波浪(优化参数)':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    bh_pos = np.ones(n)
    m = calc_metrics(prices, bh_pos, valid_start, cost_pct=0.001)
    results_cost["买入持有"] = m
    print(f"{'买入持有':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    # ===== 无交易成本 =====
    print(f"\n{'='*90}")
    print(f"  9年期回测 — 无交易成本 (理论参考)")
    print(f"{'='*90}")
    print(f"{'策略':<36} {'年化':>8} {'总收益':>10} {'夏普':>8} {'回撤':>10} {'Calmar':>8} {'胜率':>8} {'均仓':>7}")
    print(f"{'-'*100}")

    results_nocost = {}

    m = calc_metrics(prices, v4_positions, valid_start, cost_pct=0.0)
    results_nocost["纯V4"] = m
    print(f"{'纯V4减半周期':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    m = calc_metrics(prices, fused_default, valid_start, cost_pct=0.0)
    results_nocost["V4+波浪(默认)"] = m
    print(f"{'V4+波浪(默认参数)':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    m = calc_metrics(prices, fused_opt, valid_start, cost_pct=0.0)
    results_nocost["V4+波浪(优化)"] = m
    print(f"{'V4+波浪(优化参数)':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    m = calc_metrics(prices, bh_pos, valid_start, cost_pct=0.0)
    results_nocost["买入持有"] = m
    print(f"{'买入持有':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    # ===== 增量分析 =====
    print(f"\n{'='*90}")
    print(f"  相对纯V4的增量价值（9年期，含成本）")
    print(f"{'='*90}")
    print(f"{'策略':<36} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'Calmar增量':>10}")
    print(f"{'-'*80}")
    v4_base = results_cost["纯V4"]
    for name, metrics in results_cost.items():
        if name == "纯V4":
            continue
        ann_delta = (metrics['annualized'] - v4_base['annualized']) * 100
        sharpe_delta = metrics['sharpe'] - v4_base['sharpe']
        mdd_delta = (metrics['max_drawdown'] - v4_base['max_drawdown']) * 100
        calmar_delta = metrics['calmar'] - v4_base['calmar']
        mark = " ✅" if ann_delta > 0 and calmar_delta > 0 else ""
        print(f"{name:<36} {ann_delta:>+9.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+9.2f}pp {calmar_delta:>+10.4f}{mark}")

    print(f"\n{'='*90}")
    print(f"  相对纯V4的增量价值（9年期，无成本）")
    print(f"{'='*90}")
    print(f"{'策略':<36} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'Calmar增量':>10}")
    print(f"{'-'*80}")
    v4_base_nc = results_nocost["纯V4"]
    for name, metrics in results_nocost.items():
        if name == "纯V4":
            continue
        ann_delta = (metrics['annualized'] - v4_base_nc['annualized']) * 100
        sharpe_delta = metrics['sharpe'] - v4_base_nc['sharpe']
        mdd_delta = (metrics['max_drawdown'] - v4_base_nc['max_drawdown']) * 100
        calmar_delta = metrics['calmar'] - v4_base_nc['calmar']
        mark = " ✅" if ann_delta > 0 and calmar_delta > 0 else ""
        print(f"{name:<36} {ann_delta:>+9.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+9.2f}pp {calmar_delta:>+10.4f}{mark}")

    # ===== 4年期样本外 =====
    valid_start_4y = max(365, n - 1460)
    print(f"\n{'='*90}")
    print(f"  4年期样本外回测 — 含交易成本 (valid_start={valid_start_4y})")
    print(f"{'='*90}")
    print(f"{'策略':<36} {'年化':>8} {'总收益':>10} {'夏普':>8} {'回撤':>10} {'Calmar':>8} {'胜率':>8} {'均仓':>7}")
    print(f"{'-'*100}")

    results_4y = {}

    m = calc_metrics(prices, v4_positions, valid_start_4y, cost_pct=0.001)
    results_4y["纯V4"] = m
    print(f"{'纯V4减半周期':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    m = calc_metrics(prices, fused_default, valid_start_4y, cost_pct=0.001)
    results_4y["V4+波浪(默认)"] = m
    print(f"{'V4+波浪(默认参数)':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    m = calc_metrics(prices, fused_opt, valid_start_4y, cost_pct=0.001)
    results_4y["V4+波浪(优化)"] = m
    print(f"{'V4+波浪(优化参数)':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    m = calc_metrics(prices, bh_pos, valid_start_4y, cost_pct=0.001)
    results_4y["买入持有"] = m
    print(f"{'买入持有':<36} {m['annualized']*100:>7.2f}% {m['total_return']*100:>9.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    print(f"\n  --- 相对纯V4的增量价值（4年期/样本外）---")
    v4_base_4y = results_4y["纯V4"]
    print(f"{'策略':<36} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'Calmar增量':>10}")
    print(f"{'-'*80}")
    for name, metrics in results_4y.items():
        if name == "纯V4":
            continue
        ann_delta = (metrics['annualized'] - v4_base_4y['annualized']) * 100
        sharpe_delta = metrics['sharpe'] - v4_base_4y['sharpe']
        mdd_delta = (metrics['max_drawdown'] - v4_base_4y['max_drawdown']) * 100
        calmar_delta = metrics['calmar'] - v4_base_4y['calmar']
        mark = " ✅" if ann_delta > 0 and calmar_delta > 0 else ""
        print(f"{name:<36} {ann_delta:>+9.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+9.2f}pp {calmar_delta:>+10.4f}{mark}")

    # ===== 总结 =====
    print(f"\n{'='*90}")
    print(f"  9年回测总结")
    print(f"{'='*90}")
    print(f"  数据: {n}天 ({years:.2f}年), {prices.index[0].date()} ~ {prices.index[-1].date()}")
    print(f"  有效: {valid_days}天 ({valid_years:.1f}年), valid_start={valid_start}")
    print()
    print(f"  含成本(0.1%/侧):")
    print(f"    纯V4:        年化={results_cost['纯V4']['annualized']*100:.2f}%, 夏普={results_cost['纯V4']['sharpe']:.4f}, Calmar={results_cost['纯V4']['calmar']:.4f}")
    print(f"    V4+波浪(优化): 年化={results_cost['V4+波浪(优化)']['annualized']*100:.2f}%, 夏普={results_cost['V4+波浪(优化)']['sharpe']:.4f}, Calmar={results_cost['V4+波浪(优化)']['calmar']:.4f}")
    print(f"    买入持有:     年化={results_cost['买入持有']['annualized']*100:.2f}%, 夏普={results_cost['买入持有']['sharpe']:.4f}, Calmar={results_cost['买入持有']['calmar']:.4f}")
    print()
    print(f"  无成本(理论):")
    print(f"    纯V4:        年化={results_nocost['纯V4']['annualized']*100:.2f}%, 夏普={results_nocost['纯V4']['sharpe']:.4f}, Calmar={results_nocost['纯V4']['calmar']:.4f}")
    print(f"    V4+波浪(优化): 年化={results_nocost['V4+波浪(优化)']['annualized']*100:.2f}%, 夏普={results_nocost['V4+波浪(优化)']['sharpe']:.4f}, Calmar={results_nocost['V4+波浪(优化)']['calmar']:.4f}")

    # 原始贝叶斯优化结果对比
    print()
    print(f"  原始贝叶斯优化结果（无成本，含计算差异）:")
    print(f"    纯V4:        年化=62.89%, 夏普=1.374, Calmar=1.418")
    print(f"    V4+波浪(优化): 年化=70.31%, 夏普=1.455, Calmar=1.654")
    print(f"    注: 原始计算用 cum_ret[-1]-cum_ret[vs] 代替 prod(1+ret[vs:])-1, 导致数值偏高")

    v4_9y = results_cost["纯V4"]["annualized"]
    fused_9y = results_cost["V4+波浪(优化)"]["annualized"]
    v4_4y_val = results_4y["纯V4"]["annualized"]
    fused_4y_val = results_4y["V4+波浪(优化)"]["annualized"]

    print(f"\n  优势验证:")
    print(f"    9年期: V4+波浪 {fused_9y*100:.2f}% vs 纯V4 {v4_9y*100:.2f}% → {'✅ 优势保持' if fused_9y > v4_9y else '⚠ 波浪未增强（V4本身已强）'}")
    print(f"    4年期: V4+波浪 {fused_4y_val*100:.2f}% vs 纯V4 {v4_4y_val*100:.2f}% → {'✅ 优势保持' if fused_4y_val > v4_4y_val else '⚠ 波浪未增强'}")

    # 保存结果
    os.makedirs(os.path.join(MODULE_DIR, "backtest_results"), exist_ok=True)
    save_data = {
        "symbol": symbol,
        "module": "17-v4-wave-strategy (独立模块)",
        "data_days": int(n),
        "years": round(years, 2),
        "date_range": [str(prices.index[0].date()), str(prices.index[-1].date())],
        "valid_start": valid_start,
        "valid_days": valid_days,
        "valid_years": round(valid_years, 2),
        "results_9y_with_cost": results_cost,
        "results_9y_no_cost": results_nocost,
        "results_4y_with_cost": results_4y,
    }
    save_path = os.path.join(MODULE_DIR, "backtest_results", f"v4_wave_9year_{symbol.lower()}.json")
    with open(save_path, "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到 {save_path}")

    return results_cost, results_nocost, results_4y


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="V4+波浪策略独立模块回测验证")
    parser.add_argument("--symbol", type=str, default="BTC", help="交易对")
    args = parser.parse_args()

    run_backtest(symbol=args.symbol)
