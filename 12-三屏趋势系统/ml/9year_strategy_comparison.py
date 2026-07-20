"""9年完整回测对比：V4减半周期 vs V5.5 ML vs 波浪策略 vs 买入持有 vs 融合策略

使用全量历史数据（BTC/ETH约9年，SOL/UNI约6年）进行多策略横向对比，
验证波浪策略对V5.5的补充价值。

策略:
1. V4减半周期策略 - 经典技术指标 + 减半周期逃顶
2. V5.5 ML策略 - 28维哲学特征 + LightGBM + Walk-Forward
3. 波浪策略 - 艾略特波浪识别 + 物理引擎评估器（3成仓位）
4. 融合策略 - V5.5（7成）+ 波浪（3成）分仓位运行
5. 买入持有 - 基准

文件: ml/9year_strategy_comparison.py
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from typing import Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer
from ml.feature_engineer import TrendFeatureEngineer
from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
from ml.ewave_recognizer import ElliottWaveRecognizer
from ml.halving_top_exit_strategy import HalvingTopExitStrategy

import lightgbm as lgb


def load_coin_data(symbol: str) -> pd.DataFrame:
    """加载币种历史数据"""
    path = os.path.join(BASE_DIR, f"data/historical/{symbol}_1D_730d.json")
    with open(path) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def generate_labels(prices, lookahead: int, threshold: float, direction: str = "drop"):
    """生成标签（用于ML训练）"""
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
    """Walk-Forward预测"""
    n = len(X)
    preds = np.full(n, 0.5)
    aucs = []
    splits = []

    start = train_days
    fold = 0
    while start + test_days <= n:
        train_end = start
        test_end = min(start + test_days, n)

        X_train = X.iloc[:train_end][feature_names].values
        y_train = y[:train_end]
        X_test = X.iloc[train_end:test_end][feature_names].values
        y_test = y[train_end:test_end]

        valid_mask = ~np.isnan(y_train) & (y_train >= 0)
        X_train_valid = X_train[valid_mask]
        y_train_valid = y_train[valid_mask].astype(int)

        if len(np.unique(y_train_valid)) < 2:
            start += test_days
            continue

        try:
            model = lgb.LGBMClassifier(
                n_estimators=200,
                learning_rate=0.05,
                max_depth=5,
                num_leaves=20,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbose=-1,
            )
            model.fit(X_train_valid, y_train_valid)
            pred = model.predict_proba(X_test)[:, 1]
            preds[train_end:test_end] = pred

            test_valid_mask = ~np.isnan(y_test) & (y_test >= 0)
            if test_valid_mask.sum() > 10 and len(np.unique(y_test[test_valid_mask])) >= 2:
                from sklearn.metrics import roc_auc_score
                auc = roc_auc_score(y_test[test_valid_mask], pred[test_valid_mask])
                aucs.append(auc)

            splits.append((0, train_end, test_end))
            fold += 1
        except Exception:
            pass

        start += test_days

    avg_auc = np.mean(aucs) if aucs else 0.5
    return preds, avg_auc, splits


def compute_v55_position(prices, symbol="BTC", train_days=730, test_days=180):
    """计算V5.5 ML基线仓位（Walk-Forward）"""
    print(f"  [V5.5] 计算 {symbol} V5.5 ML基线 (train={train_days}d, test={test_days}d)...")
    t0 = time.time()

    closes = prices["close"].values

    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol=symbol)

    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)
    print(f"    特征维数: {len(v55_names)}")

    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    top_preds, top_auc, splits = walk_forward_predictions(v55_base, top_exit_labels, v55_names, train_days, test_days)
    dip_preds, dip_auc, _ = walk_forward_predictions(v55_base, dip_buy_labels, v55_names, train_days, test_days)
    print(f"    TOP_EXIT AUC: {top_auc:.4f}, DIP_BUY AUC: {dip_auc:.4f}")
    print(f"    Walk-Forward折数: {len(splits)}")

    bull_signal = np.maximum(dip_preds - 0.5, 0) * 2
    bear_signal = np.maximum(top_preds - 0.5, 0) * 2
    base_pos = 0.3 + bull_signal - bear_signal
    base_pos = np.clip(base_pos, 0.0, 1.0)

    print(f"    耗时: {time.time()-t0:.1f}s")
    return base_pos, splits


def generate_wave_signals(prices, zigzag_threshold=0.05):
    """生成波浪信号（滚动识别）"""
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
    n = len(prices)
    closes = prices["close"].values
    highs = prices["high"].values
    lows = prices["low"].values

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

        if current_dir == 1:
            if lows[i] <= current_entry * (1 - stop_loss_pct):
                current_pos = 0.0
                current_dir = 0
            elif highs[i] >= current_entry * (1 + take_profit_pct):
                current_pos = 0.0
                current_dir = 0
        elif current_dir == -1:
            if highs[i] >= current_entry * (1 + stop_loss_pct):
                current_pos = 0.0
                current_dir = 0
            elif lows[i] <= current_entry * (1 - take_profit_pct):
                current_pos = 0.0
                current_dir = 0

        position[i] = current_pos
        direction[i] = current_dir

    return position, direction


def compute_v4_position(prices, symbol="BTC"):
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

    n = len(position_arr)
    direction_arr = np.sign(position_arr)
    abs_position = np.abs(position_arr)

    print(f"    耗时: {time.time()-t0:.1f}s")
    return abs_position, direction_arr


def compute_fusion_position(v55_pos, v55_dir, wave_pos, wave_dir, v55_weight=0.7, wave_weight=0.3):
    """计算融合策略仓位（V5.5主 + 波浪补充）"""
    n = len(v55_pos)
    total_pos = np.zeros(n)
    total_dir = np.zeros(n)

    for i in range(n):
        v55_val = v55_pos[i] * v55_dir[i]
        wave_val = wave_pos[i] * wave_dir[i]

        combined = v55_weight * v55_val + wave_weight * wave_val
        total_pos[i] = abs(combined)
        total_dir[i] = np.sign(combined) if combined != 0 else v55_dir[i]

    total_pos = np.clip(total_pos, 0.0, 1.0)
    return total_pos, total_dir


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


def run_comparison(symbols=None, zigzag_threshold=0.05, wave_base_position=0.3,
                  train_days=730, test_days=180):
    """运行9年完整对比分析"""
    if symbols is None:
        symbols = ["BTC", "ETH", "SOL", "UNI"]

    print("=" * 90)
    print("9年完整回测对比: V4减半周期 vs V5.5 ML vs 波浪策略 vs 融合策略 vs 买入持有")
    print("=" * 90)
    print(f"参数: zigzag={zigzag_threshold}, wave_base_pos={wave_base_position}")
    print(f"      V5.5 Walk-Forward: train={train_days}d, test={test_days}d")
    print(f"币种: {symbols}")
    print()

    all_results = {}

    for symbol in symbols:
        print(f"\n{'='*80}")
        print(f"币种: {symbol}")
        print(f"{'='*80}")

        try:
            prices = load_coin_data(symbol)
            print(f"数据: {len(prices)} 天, {prices.index[0].date()} ~ {prices.index[-1].date()}")
            print(f"      约 {len(prices)/365:.1f} 年")
        except FileNotFoundError:
            print(f"⚠ {symbol} 数据文件不存在, 跳过")
            continue

        closes = prices["close"].values
        n = len(prices)

        # 1. V4减半周期策略
        try:
            v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
            v4_metrics = backtest_position(v4_pos, v4_dir, prices)
            print(f"  V4减半周期:")
            print(f"    年化: {v4_metrics['ann_return']*100:.2f}%, 总收益: {v4_metrics['total_return']*100:.2f}%")
            print(f"    夏普: {v4_metrics['sharpe']:.4f}, 回撤: {v4_metrics['max_drawdown']*100:.2f}%")
            print(f"    Calmar: {v4_metrics['calmar']:.4f}, 胜率: {v4_metrics['win_rate']*100:.2f}%")
        except Exception as e:
            print(f"  V4策略计算失败: {e}")
            v4_metrics = None

        # 2. V5.5 ML基线
        v55_pos, splits = compute_v55_position(prices, symbol=symbol, train_days=train_days, test_days=test_days)
        v55_dir = np.ones(n)
        valid_start = splits[0][1] if splits else train_days  # 第一个测试期开始

        v55_metrics = backtest_position(v55_pos[valid_start:], v55_dir[valid_start:], prices.iloc[valid_start:])
        print(f"  V5.5 ML基线 (有效区域 {len(prices)-valid_start}天):")
        print(f"    年化: {v55_metrics['ann_return']*100:.2f}%, 总收益: {v55_metrics['total_return']*100:.2f}%")
        print(f"    夏普: {v55_metrics['sharpe']:.4f}, 回撤: {v55_metrics['max_drawdown']*100:.2f}%")
        print(f"    Calmar: {v55_metrics['calmar']:.4f}, 胜率: {v55_metrics['win_rate']*100:.2f}%, 平均仓位: {v55_metrics['avg_position']:.3f}")

        # 3. 波浪策略（含物理调节）
        wave_sigs, wave_confs = generate_wave_signals(prices, zigzag_threshold=zigzag_threshold)
        wave_pos, wave_dir = compute_wave_position(
            prices, wave_sigs, wave_confs,
            use_physics=True, base_position=wave_base_position
        )

        wave_metrics = backtest_position(wave_pos[valid_start:], wave_dir[valid_start:], prices.iloc[valid_start:])
        print(f"  波浪策略(+物理):")
        print(f"    年化: {wave_metrics['ann_return']*100:.2f}%, 总收益: {wave_metrics['total_return']*100:.2f}%")
        print(f"    夏普: {wave_metrics['sharpe']:.4f}, 回撤: {wave_metrics['max_drawdown']*100:.2f}%")
        print(f"    Calmar: {wave_metrics['calmar']:.4f}, 胜率: {wave_metrics['win_rate']*100:.2f}%, 平均仓位: {wave_metrics['avg_position']:.3f}")

        # 4. 融合策略（V5.5 7成 + 波浪 3成）
        fusion_pos, fusion_dir = compute_fusion_position(
            v55_pos, v55_dir, wave_pos, wave_dir,
            v55_weight=0.7, wave_weight=0.3
        )
        fusion_metrics = backtest_position(fusion_pos[valid_start:], fusion_dir[valid_start:], prices.iloc[valid_start:])
        print(f"  融合策略(V5.5 70% + 波浪 30%):")
        print(f"    年化: {fusion_metrics['ann_return']*100:.2f}%, 总收益: {fusion_metrics['total_return']*100:.2f}%")
        print(f"    夏普: {fusion_metrics['sharpe']:.4f}, 回撤: {fusion_metrics['max_drawdown']*100:.2f}%")
        print(f"    Calmar: {fusion_metrics['calmar']:.4f}, 胜率: {fusion_metrics['win_rate']*100:.2f}%")

        # 5. 买入持有
        bh_pos = np.ones(n - valid_start)
        bh_dir = np.ones(n - valid_start)
        bh_metrics = backtest_position(bh_pos, bh_dir, prices.iloc[valid_start:])
        print(f"  买入持有:")
        print(f"    年化: {bh_metrics['ann_return']*100:.2f}%, 总收益: {bh_metrics['total_return']*100:.2f}%")
        print(f"    夏普: {bh_metrics['sharpe']:.4f}, 回撤: {bh_metrics['max_drawdown']*100:.2f}%")

        all_results[symbol] = {
            "v4_halving": v4_metrics,
            "v55_ml": v55_metrics,
            "wave_physics": wave_metrics,
            "fusion": fusion_metrics,
            "buy_hold": bh_metrics,
            "data_days": n,
            "valid_days": n - valid_start,
            "date_range": [str(prices.index[0].date()), str(prices.index[-1].date())],
        }

    # 总体对比表格
    print(f"\n{'='*90}")
    print("总体对比表（V5.5有效预测区域）")
    print(f"{'='*90}")

    strategies = [
        ("v4_halving", "V4减半"),
        ("v55_ml", "V5.5 ML"),
        ("wave_physics", "波浪+物理"),
        ("fusion", "融合策略"),
        ("buy_hold", "买入持有"),
    ]

    # 年化收益
    print(f"\n【年化收益 (%)】")
    header = f"{'币种':<6}"
    for _, name in strategies:
        header += f" {name:>10}"
    print(header)
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        line = f"{sym:<6}"
        for key, _ in strategies:
            val = res.get(key)
            if val and val.get('ann_return') is not None:
                line += f" {val['ann_return']*100:>9.2f}%"
            else:
                line += f" {'N/A':>10}"
        print(line)

    # 总收益
    print(f"\n【总收益 (%)】")
    header = f"{'币种':<6}"
    for _, name in strategies:
        header += f" {name:>10}"
    print(header)
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        line = f"{sym:<6}"
        for key, _ in strategies:
            val = res.get(key)
            if val and val.get('total_return') is not None:
                line += f" {val['total_return']*100:>9.2f}%"
            else:
                line += f" {'N/A':>10}"
        print(line)

    # 夏普比
    print(f"\n【夏普比】")
    header = f"{'币种':<6}"
    for _, name in strategies:
        header += f" {name:>10}"
    print(header)
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        line = f"{sym:<6}"
        for key, _ in strategies:
            val = res.get(key)
            if val and val.get('sharpe') is not None:
                line += f" {val['sharpe']:>10.4f}"
            else:
                line += f" {'N/A':>10}"
        print(line)

    # 最大回撤
    print(f"\n【最大回撤 (%)】")
    header = f"{'币种':<6}"
    for _, name in strategies:
        header += f" {name:>10}"
    print(header)
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        line = f"{sym:<6}"
        for key, _ in strategies:
            val = res.get(key)
            if val and val.get('max_drawdown') is not None:
                line += f" {val['max_drawdown']*100:>9.2f}%"
            else:
                line += f" {'N/A':>10}"
        print(line)

    # Calmar比
    print(f"\n【Calmar比】")
    header = f"{'币种':<6}"
    for _, name in strategies:
        header += f" {name:>10}"
    print(header)
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        line = f"{sym:<6}"
        for key, _ in strategies:
            val = res.get(key)
            if val and val.get('calmar') is not None:
                line += f" {val['calmar']:>10.4f}"
            else:
                line += f" {'N/A':>10}"
        print(line)

    # 综合评分
    print(f"\n【综合评分（夏普0.4 + Calmar0.3 + 年化*100*0.3，越高越好）】")
    header = f"{'币种':<6}"
    for _, name in strategies:
        header += f" {name:>10}"
    header += f" {'最优':>8}"
    print(header)
    print(f"{'-'*80}")
    for sym, res in all_results.items():
        line = f"{sym:<6}"
        scores = {}
        for key, name in strategies:
            val = res.get(key)
            if val and val.get('sharpe') is not None:
                score = val['sharpe'] * 0.4 + val['calmar'] * 0.3 + val['ann_return'] * 100 * 0.3
                scores[key] = score
                line += f" {score:>10.2f}"
            else:
                line += f" {'N/A':>10}"
        if scores:
            best = max(scores, key=scores.get)
            best_name = dict(strategies)[best]
            line += f" {best_name:>8}"
        print(line)

    # 价值分析
    print(f"\n{'='*90}")
    print("波浪策略增量价值分析")
    print(f"{'='*90}")
    print()

    print("1. 波浪 vs V5.5 ML:")
    for sym, res in all_results.items():
        v55 = res.get("v55_ml")
        wave = res.get("wave_physics")
        if v55 and wave:
            ret_diff = (wave['ann_return'] - v55['ann_return']) * 100
            sharpe_diff = wave['sharpe'] - v55['sharpe']
            dd_diff = (wave['max_drawdown'] - v55['max_drawdown']) * 100
            print(f"   {sym}: 年化 {v55['ann_return']*100:.2f}% → {wave['ann_return']*100:.2f}% ({ret_diff:+.2f}pp), "
                  f"夏普 {v55['sharpe']:.4f} → {wave['sharpe']:.4f} ({sharpe_diff:+.4f}), "
                  f"回撤 {v55['max_drawdown']*100:.2f}% → {wave['max_drawdown']*100:.2f}% ({dd_diff:+.2f}pp)")

    print()
    print("2. 融合策略 vs V5.5 ML:")
    for sym, res in all_results.items():
        v55 = res.get("v55_ml")
        fusion = res.get("fusion")
        if v55 and fusion:
            ret_diff = (fusion['ann_return'] - v55['ann_return']) * 100
            sharpe_diff = fusion['sharpe'] - v55['sharpe']
            dd_diff = (fusion['max_drawdown'] - v55['max_drawdown']) * 100
            print(f"   {sym}: 年化 {v55['ann_return']*100:.2f}% → {fusion['ann_return']*100:.2f}% ({ret_diff:+.2f}pp), "
                  f"夏普 {v55['sharpe']:.4f} → {fusion['sharpe']:.4f} ({sharpe_diff:+.4f}), "
                  f"回撤 {v55['max_drawdown']*100:.2f}% → {fusion['max_drawdown']*100:.2f}% ({dd_diff:+.2f}pp)")

    print()
    print("结论:")
    print("  - 波浪策略在风险控制方面的价值（回撤减小）")
    print("  - 融合策略是否实现了收益增强或风险分散")
    print("  - 各策略在牛熊周期中的表现差异")

    output_path = os.path.join(BASE_DIR, "ml", "backtest_results", "9year_strategy_comparison.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到: {output_path}")

    return all_results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "UNI"])
    parser.add_argument("--zigzag", type=float, default=0.05)
    parser.add_argument("--position", type=float, default=0.3)
    parser.add_argument("--train-days", type=int, default=730)
    parser.add_argument("--test-days", type=int, default=180)
    args = parser.parse_args()

    run_comparison(
        symbols=args.symbols,
        zigzag_threshold=args.zigzag,
        wave_base_position=args.position,
        train_days=args.train_days,
        test_days=args.test_days,
    )
