#!/usr/bin/env python3
"""
综合策略对比回测
对比：V5.5 ML+波浪融合、V4+波浪互斥融合、纯策略、买入持有

互斥融合规则：
1. V5.5 ML + 波浪互斥融合：波浪信号与ML信号同向时增强，反向时以ML为主（波浪作为辅助确认）
2. V4主策略 + 波浪互斥融合：V4定方向，波浪信号冲突时以V4为准，同向时叠加仓位
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


def load_coin_data(symbol: str) -> pd.DataFrame:
    """加载币种K线数据"""
    path = os.path.join(BASE_DIR, f"data/historical/{symbol}_1D_730d.json")
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


def compute_v55_position(prices, symbol="BTC"):
    """计算V5.5 ML基线仓位（Walk-Forward）"""
    print(f"  [V5.5] 计算 {symbol} V5.5 ML基线...")
    t0 = time.time()

    from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer
    from ml.feature_engineer import TrendFeatureEngineer
    import lightgbm as lgb

    closes = prices["close"].values

    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol=symbol)

    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)

    def generate_labels(prices, lookahead, threshold, direction="drop"):
        n = len(prices)
        labels = np.zeros(n)
        for i in range(n - lookahead):
            future_max = np.max(prices[i + 1 : i + 1 + lookahead])
            future_min = np.min(prices[i + 1 : i + 1 + lookahead])
            if direction == "drop":
                drawdown = (future_min - prices[i]) / prices[i]
                labels[i] = 1 if drawdown <= -threshold else 0
            else:
                upside = (future_max - prices[i]) / prices[i]
                labels[i] = 1 if upside >= threshold else 0
        return labels

    def walk_forward_predictions(X, y, feature_names, train_days=730, test_days=180):
        n = len(X)
        preds = np.full(n, 0.5)
        start = train_days
        while start + test_days <= n:
            train_end, test_end = start, min(start + test_days, n)
            X_train, y_train = X.iloc[:train_end][feature_names].values, y[:train_end]
            X_test, y_test = X.iloc[train_end:test_end][feature_names].values, y[train_end:test_end]
            valid_mask = ~np.isnan(y_train) & (y_train >= 0)
            X_train_valid, y_train_valid = X_train[valid_mask], y_train[valid_mask].astype(int)
            if len(np.unique(y_train_valid)) < 2:
                start += test_days
                continue
            try:
                model = lgb.LGBMClassifier(
                    n_estimators=200, learning_rate=0.05, max_depth=5,
                    num_leaves=20, subsample=0.8, colsample_bytree=0.8,
                    random_state=42, verbose=-1,
                )
                model.fit(X_train_valid, y_train_valid)
                preds[train_end:test_end] = model.predict_proba(X_test)[:, 1]
            except Exception:
                pass
            start += test_days
        return preds

    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    top_preds = walk_forward_predictions(v55_base, top_exit_labels, v55_names)
    dip_preds = walk_forward_predictions(v55_base, dip_buy_labels, v55_names)

    bull_signal = np.maximum(dip_preds - 0.5, 0) * 2
    bear_signal = np.maximum(top_preds - 0.5, 0) * 2
    base_pos = 0.3 + bull_signal - bear_signal
    base_pos = np.clip(base_pos, 0.0, 1.0)

    print(f"    特征维数: {len(v55_names)}, 耗时: {time.time()-t0:.1f}s")
    return base_pos, np.ones(len(base_pos))


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

        elif sig in ("EXIT_LONG_W5", "EXIT_SHORT_W5"):
            current_pos = 0.0
            current_dir = 0
            current_entry = 0.0

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


def compute_v55_wave_mutex_fusion(v55_pos, v55_dir, wave_signals, wave_confs, phys_conf, eta_series,
                                   wave_weight=0.3, confirm_threshold=0.6):
    """V5.5 ML + 波浪互斥融合
    规则：
    1. ML看多 + 波浪看多 → ML仓位 + 波浪增强（同向确认）
    2. ML看多 + 波浪看空 → 保持ML仓位（互斥：以ML为主）
    3. ML看多 + 波浪中性 → 保持ML仓位
    4. ML空仓 + 波浪看多 → 波浪轻仓（低置信度时仅确认）
    5. ML空仓 + 波浪看空 → 空仓
    """
    n = len(v55_pos)
    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)

    wave_long = ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
    wave_short = ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")

    for i in range(n):
        v55_p = v55_pos[i] * v55_dir[i]
        v55_d = v55_dir[i]
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        is_wave_long = sig in wave_long
        is_wave_short = sig in wave_short

        if v55_d > 0:
            if is_wave_long and wave_conf >= confirm_threshold:
                add_amount = wave_weight * wave_conf
                total = v55_p + add_amount
                total = min(total, 1.0)
                fusion_pos[i] = abs(total)
                fusion_dir[i] = 1
            elif is_wave_short:
                fusion_pos[i] = v55_p * 0.7
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = v55_p
                fusion_dir[i] = 1

        elif v55_d == 0:
            if is_wave_long and wave_conf >= confirm_threshold:
                bottom_pos = wave_weight * wave_conf
                if not np.isnan(eta_series[i]) and eta_series[i] < 0.10:
                    bottom_pos = bottom_pos * (0.6 + 1.0 * phys_conf[i])
                bottom_pos = min(bottom_pos, 0.3)
                fusion_pos[i] = bottom_pos
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = 0.0
                fusion_dir[i] = 0

        else:
            fusion_pos[i] = abs(v55_p)
            fusion_dir[i] = v55_d

    print(f"    V5.5+波浪互斥融合 - 平均仓位: {np.mean(fusion_pos):.3f}")
    return fusion_pos, fusion_dir


def compute_v4_wave_mutex_fusion(v4_pos, v4_dir, wave_signals, wave_confs, phys_conf, eta_series,
                                  wave_weight=0.3, confirm_threshold=0.6):
    """V4主策略 + 波浪互斥融合
    规则：
    1. V4多头 + 波浪看多 → V4仓位 + 波浪加仓（同向叠加）
    2. V4多头 + 波浪看空 → 保持V4仓位（互斥：V4优先）
    3. V4空仓 + 波浪看多 → 波浪轻仓抄底（低仓位）
    4. V4空仓 + 波浪看空 → 空仓
    5. V4空头 + 波浪看空 → 保持V4空头
    6. V4空头 + 波浪看多 → V4空头减半（波浪提示反弹）
    """
    n = len(v4_pos)
    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)

    wave_long = ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
    wave_short = ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")

    for i in range(n):
        v4_p = v4_pos[i] * v4_dir[i]
        v4_d = v4_dir[i]
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        is_wave_long = sig in wave_long
        is_wave_short = sig in wave_short

        if v4_d > 0:
            if is_wave_long and wave_conf >= confirm_threshold:
                add_amount = wave_weight * wave_conf
                total = v4_p + add_amount
                total = min(total, 1.0)
                fusion_pos[i] = abs(total)
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = 1

        elif v4_d == 0:
            if is_wave_long and wave_conf >= confirm_threshold:
                bottom_pos = wave_weight * wave_conf
                if not np.isnan(eta_series[i]) and eta_series[i] < 0.10:
                    bottom_pos = bottom_pos * (0.6 + 1.0 * phys_conf[i])
                bottom_pos = min(bottom_pos, 0.3)
                fusion_pos[i] = bottom_pos
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = 0.0
                fusion_dir[i] = 0

        else:
            if is_wave_long and wave_conf >= confirm_threshold:
                fusion_pos[i] = abs(v4_p) * 0.5
                fusion_dir[i] = -1
            else:
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = -1

    print(f"    V4+波浪互斥融合 - 平均仓位: {np.mean(fusion_pos):.3f}")
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
    """运行综合策略对比回测"""
    print(f"\n{'='*90}")
    print(f"  综合策略对比回测 - {symbol}")
    print(f"  V5.5 ML+波浪互斥融合 vs V4+波浪互斥融合")
    print(f"{'='*90}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    v55_pos, v55_dir = compute_v55_position(prices, symbol=symbol)
    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=zigzag_threshold)
    wave_pos, wave_dir, phys_conf, eta_series = compute_wave_position(
        prices, wave_signals, wave_confs,
        use_physics=True, base_position=wave_base_position,
    )

    v55_valid_start = 730
    v4_valid_start = 365
    valid_start = max(v55_valid_start, v4_valid_start)

    print(f"\n{'='*90}")
    print(f"  回测结果对比（有效天数: {n-valid_start}天）")
    print(f"{'='*90}")
    print(f"{'策略':<35} {'年化':>8} {'总收益':>12} {'夏普':>8} {'回撤':>10} {'Calmar':>8} {'胜率':>8} {'均仓':>7}")
    print(f"{'-'*110}")

    results = {}

    m = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:], prices.iloc[valid_start:])
    results["纯V4"] = m
    print(f"{'纯V4':<35} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>11.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    m = backtest_position(v55_pos[valid_start:], v55_dir[valid_start:], prices.iloc[valid_start:])
    results["纯V5.5 ML"] = m
    print(f"{'纯V5.5 ML':<35} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>11.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    m = backtest_position(wave_pos[valid_start:], wave_dir[valid_start:], prices.iloc[valid_start:])
    results["纯波浪+物理"] = m
    print(f"{'纯波浪+物理':<35} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>11.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    v55_fusion_pos, v55_fusion_dir = compute_v55_wave_mutex_fusion(
        v55_pos, v55_dir, wave_signals, wave_confs, phys_conf, eta_series,
        wave_weight=0.3, confirm_threshold=0.6,
    )
    m = backtest_position(v55_fusion_pos[valid_start:], v55_fusion_dir[valid_start:], prices.iloc[valid_start:])
    results["V5.5 ML+波浪互斥融合"] = m
    print(f"{'V5.5 ML+波浪互斥融合':<35} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>11.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    v4_fusion_pos, v4_fusion_dir = compute_v4_wave_mutex_fusion(
        v4_pos, v4_dir, wave_signals, wave_confs, phys_conf, eta_series,
        wave_weight=0.3, confirm_threshold=0.6,
    )
    m = backtest_position(v4_fusion_pos[valid_start:], v4_fusion_dir[valid_start:], prices.iloc[valid_start:])
    results["V4+波浪互斥融合"] = m
    print(f"{'V4+波浪互斥融合':<35} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>11.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    bh_pos = np.ones(n)
    bh_dir = np.ones(n)
    m = backtest_position(bh_pos[valid_start:], bh_dir[valid_start:], prices.iloc[valid_start:])
    results["买入持有"] = m
    print(f"{'买入持有':<35} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>11.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>9.2f}% {m['calmar']:>8.4f} {m['win_rate']*100:>7.2f}% {m['avg_position']:>7.3f}")

    print(f"\n{'='*90}")
    print(f"  增量价值分析（相对纯V4）")
    print(f"{'='*90}")
    print(f"{'策略':<35} {'年化增量':>12} {'夏普增量':>10} {'回撤改善':>12} {'综合评分':>10}")
    print(f"{'-'*90}")

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

        print(f"{name:<35} {ann_delta:>+11.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+11.2f}pp {score:>10.4f}{mark}")

    print(f"\n最优策略: {best_name} (综合评分: {best_score:.4f})")

    print(f"\n{'='*90}")
    print(f"  核心结论")
    print(f"{'='*90}")

    v4_fusion = results["V4+波浪互斥融合"]
    v55_fusion = results["V5.5 ML+波浪互斥融合"]

    print(f"\n1. V4+波浪互斥融合 vs 纯V4:")
    print(f"   年化: {v4_fusion['ann_return']*100:.2f}% vs {v4_base['ann_return']*100:.2f}% ({'提升' if v4_fusion['ann_return'] > v4_base['ann_return'] else '下降'} {abs(v4_fusion['ann_return']-v4_base['ann_return'])*100:.2f}pp)")
    print(f"   夏普: {v4_fusion['sharpe']:.4f} vs {v4_base['sharpe']:.4f}")
    print(f"   回撤: {v4_fusion['max_drawdown']*100:.2f}% vs {v4_base['max_drawdown']*100:.2f}%")

    print(f"\n2. V5.5 ML+波浪互斥融合 vs 纯V5.5 ML:")
    v55_base = results["纯V5.5 ML"]
    print(f"   年化: {v55_fusion['ann_return']*100:.2f}% vs {v55_base['ann_return']*100:.2f}% ({'提升' if v55_fusion['ann_return'] > v55_base['ann_return'] else '下降'} {abs(v55_fusion['ann_return']-v55_base['ann_return'])*100:.2f}pp)")
    print(f"   夏普: {v55_fusion['sharpe']:.4f} vs {v55_base['sharpe']:.4f}")
    print(f"   回撤: {v55_fusion['max_drawdown']*100:.2f}% vs {v55_base['max_drawdown']*100:.2f}%")

    print(f"\n3. V4+波浪互斥融合 vs V5.5 ML+波浪互斥融合:")
    print(f"   年化: {v4_fusion['ann_return']*100:.2f}% vs {v55_fusion['ann_return']*100:.2f}%")
    print(f"   夏普: {v4_fusion['sharpe']:.4f} vs {v55_fusion['sharpe']:.4f}")
    print(f"   回撤: {v4_fusion['max_drawdown']*100:.2f}% vs {v55_fusion['max_drawdown']*100:.2f}%")

    os.makedirs("ml/backtest_results", exist_ok=True)
    save_results = {
        "symbol": symbol,
        "data_days": int(n),
        "valid_days": int(n - valid_start),
        "date_range": [str(prices.index[0].date()), str(prices.index[-1].date())],
        "results": results,
    }
    with open(f"ml/backtest_results/comprehensive_comparison_{symbol.lower()}.json", "w") as f:
        json.dump(save_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到 ml/backtest_results/comprehensive_comparison_{symbol.lower()}.json")

    return results


def main():
    parser = argparse.ArgumentParser(description="综合策略对比回测")
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