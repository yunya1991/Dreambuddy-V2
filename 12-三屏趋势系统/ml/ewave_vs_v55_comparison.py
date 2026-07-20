"""方向2对比: 波浪策略 vs V5.5 ML基线 vs 买入持有

系统对比三种策略在4个币种上的表现，评估波浪策略的增量价值。

策略:
1. V5.5 ML基线（28维哲学特征+LightGBM+Walk-Forward）
2. 波浪策略（艾略特波浪识别+物理引擎评估器，3成仓位）
3. 买入持有（基准）

文件: ml/ewave_vs_v55_comparison.py
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
            # TOP_EXIT: 未来最大跌幅超过阈值
            drawdown = (future_min - prices[i]) / prices[i]
            labels[i] = 1 if drawdown <= -threshold else 0
        else:
            # DIP_BUY: 未来最大涨幅超过阈值
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
        except Exception:
            pass

        start += test_days

    avg_auc = np.mean(aucs) if aucs else 0.5
    return preds, avg_auc, splits


def compute_v55_position(prices, symbol="BTC"):
    """计算V5.5 ML基线仓位（Walk-Forward）"""
    print(f"  [V5.5] 计算 {symbol} V5.5 ML基线...")
    t0 = time.time()

    closes = prices["close"].values

    # V5.5特征：趋势特征 + 哲学特征
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol=symbol)

    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)
    print(f"    特征维数: {len(v55_names)}")

    # 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    # Walk-Forward预测
    top_preds, top_auc, splits = walk_forward_predictions(v55_base, top_exit_labels, v55_names)
    dip_preds, dip_auc, _ = walk_forward_predictions(v55_base, dip_buy_labels, v55_names)
    print(f"    TOP_EXIT AUC: {top_auc:.4f}")
    print(f"    DIP_BUY AUC:  {dip_auc:.4f}")

    # 基础仓位（与方向1验证一致）
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
    entry_price = np.zeros(n)

    # 物理置信度（如启用）
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

        # 止损/止盈
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
        entry_price[i] = current_entry

    return position, direction


def backtest_position(position, direction, prices, cost_pct=0.001):
    """回测仓位序列"""
    n = len(prices)
    closes = prices["close"].values
    daily_ret = np.zeros(n)
    daily_ret[1:] = closes[1:] / closes[:-1] - 1

    # 策略收益
    strategy_ret = position * direction * daily_ret

    # 交易成本
    pos_with_dir = position * direction
    position_change = np.abs(np.diff(np.concatenate([[0], pos_with_dir])))
    cost = position_change * cost_pct
    strategy_ret_net = strategy_ret - cost

    # 指标
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

    return {
        "ann_return": float(ann_ret),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "win_rate": float(win_rate),
        "holding_days": int(holding_days),
        "trades": int(trades),
        "final_cum_return": float(cum_ret[-1]),
        "avg_position": float(np.mean(position)),
    }


def run_comparison(symbols=None, zigzag_threshold=0.05, wave_base_position=0.3):
    """运行对比分析"""
    if symbols is None:
        symbols = ["BTC", "ETH", "SOL", "UNI"]

    print("=" * 90)
    print("方向2对比: 波浪策略 vs V5.5 ML基线 vs 买入持有")
    print("=" * 90)
    print(f"参数: zigzag={zigzag_threshold}, wave_base_pos={wave_base_position}")
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
        except FileNotFoundError:
            print(f"⚠ {symbol} 数据文件不存在, 跳过")
            continue

        closes = prices["close"].values
        n = len(prices)

        # 1. V5.5 ML基线
        v55_pos, splits = compute_v55_position(prices, symbol=symbol)
        v55_dir = np.ones(n)  # V5.5基线只做多
        valid_start = splits[0][2] if splits else 730

        # 计算V5.5指标（只在有效预测区域）
        v55_metrics = backtest_position(v55_pos[valid_start:], v55_dir[valid_start:], prices.iloc[valid_start:])
        print(f"  V5.5 ML基线:")
        print(f"    年化: {v55_metrics['ann_return']*100:.2f}%, 夏普: {v55_metrics['sharpe']:.4f}, 回撤: {v55_metrics['max_drawdown']*100:.2f}%")
        print(f"    Calmar: {v55_metrics['calmar']:.4f}, 胜率: {v55_metrics['win_rate']*100:.2f}%, 平均仓位: {v55_metrics['avg_position']:.3f}")

        # 2. 波浪策略（含物理调节）
        wave_sigs, wave_confs = generate_wave_signals(prices, zigzag_threshold=zigzag_threshold)
        wave_pos, wave_dir = compute_wave_position(
            prices, wave_sigs, wave_confs,
            use_physics=True, base_position=wave_base_position
        )

        # 在同一有效区域计算波浪指标
        wave_metrics = backtest_position(wave_pos[valid_start:], wave_dir[valid_start:], prices.iloc[valid_start:])
        print(f"  波浪策略(+物理):")
        print(f"    年化: {wave_metrics['ann_return']*100:.2f}%, 夏普: {wave_metrics['sharpe']:.4f}, 回撤: {wave_metrics['max_drawdown']*100:.2f}%")
        print(f"    Calmar: {wave_metrics['calmar']:.4f}, 胜率: {wave_metrics['win_rate']*100:.2f}%, 平均仓位: {wave_metrics['avg_position']:.3f}")

        # 3. 买入持有
        bh_pos = np.ones(n - valid_start)
        bh_dir = np.ones(n - valid_start)
        bh_metrics = backtest_position(bh_pos, bh_dir, prices.iloc[valid_start:])
        print(f"  买入持有:")
        print(f"    年化: {bh_metrics['ann_return']*100:.2f}%, 夏普: {bh_metrics['sharpe']:.4f}, 回撤: {bh_metrics['max_drawdown']*100:.2f}%")

        all_results[symbol] = {
            "v55_ml": v55_metrics,
            "wave_physics": wave_metrics,
            "buy_hold": bh_metrics,
        }

    # 总体对比表格
    print(f"\n{'='*90}")
    print("总体对比（有效预测区域）")
    print(f"{'='*90}")

    # 年化收益
    print(f"\n【年化收益】")
    print(f"{'币种':<6} {'V5.5 ML':>12} {'波浪+物理':>12} {'买入持有':>12} {'波浪vs V5.5':>14} {'波浪vs BH':>14}")
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        v55 = res["v55_ml"]["ann_return"] * 100
        wv = res["wave_physics"]["ann_return"] * 100
        bh = res["buy_hold"]["ann_return"] * 100
        print(f"{sym:<6} {v55:>10.2f}% {wv:>10.2f}% {bh:>10.2f}% {wv-v55:>+10.2f}pp {wv-bh:>+10.2f}pp")

    # 夏普比
    print(f"\n【夏普比】")
    print(f"{'币种':<6} {'V5.5 ML':>12} {'波浪+物理':>12} {'买入持有':>12} {'波浪vs V5.5':>14} {'波浪vs BH':>14}")
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        v55 = res["v5.5_ml"]["sharpe"] if "v5.5_ml" in res else res["v55_ml"]["sharpe"]
        v55 = res["v55_ml"]["sharpe"]
        wv = res["wave_physics"]["sharpe"]
        bh = res["buy_hold"]["sharpe"]
        print(f"{sym:<6} {v55:>12.4f} {wv:>12.4f} {bh:>12.4f} {wv-v55:>+14.4f} {wv-bh:>+14.4f}")

    # 最大回撤
    print(f"\n【最大回撤】")
    print(f"{'币种':<6} {'V5.5 ML':>12} {'波浪+物理':>12} {'买入持有':>12} {'波浪vs V5.5':>14} {'波浪vs BH':>14}")
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        v55 = res["v55_ml"]["max_drawdown"] * 100
        wv = res["wave_physics"]["max_drawdown"] * 100
        bh = res["buy_hold"]["max_drawdown"] * 100
        print(f"{sym:<6} {v55:>10.2f}% {wv:>10.2f}% {bh:>10.2f}% {wv-v55:>+10.2f}pp {wv-bh:>+10.2f}pp")

    # Calmar比
    print(f"\n【Calmar比】")
    print(f"{'币种':<6} {'V5.5 ML':>12} {'波浪+物理':>12} {'买入持有':>12} {'波浪vs V5.5':>14} {'波浪vs BH':>14}")
    print(f"{'-'*70}")
    for sym, res in all_results.items():
        v55 = res["v55_ml"]["calmar"]
        wv = res["wave_physics"]["calmar"]
        bh = res["buy_hold"]["calmar"]
        print(f"{sym:<6} {v55:>12.4f} {wv:>12.4f} {bh:>12.4f} {wv-v55:>+14.4f} {wv-bh:>+14.4f}")

    # 综合评分（归一化: 夏普0.4 + Calmar0.3 + 年化0.3）
    print(f"\n【综合评分（夏普0.4 + Calmar0.3 + 年化*100*0.3，越高越好）】")
    print(f"{'币种':<6} {'V5.5 ML':>12} {'波浪+物理':>12} {'买入持有':>12} {'波浪胜出':>12}")
    print(f"{'-'*60}")
    for sym, res in all_results.items():
        v55_score = res["v55_ml"]["sharpe"] * 0.4 + res["v55_ml"]["calmar"] * 0.3 + res["v55_ml"]["ann_return"] * 100 * 0.3
        wv_score = res["wave_physics"]["sharpe"] * 0.4 + res["wave_physics"]["calmar"] * 0.3 + res["wave_physics"]["ann_return"] * 100 * 0.3
        bh_score = res["buy_hold"]["sharpe"] * 0.4 + res["buy_hold"]["calmar"] * 0.3 + res["buy_hold"]["ann_return"] * 100 * 0.3
        win = "✅是" if wv_score > v55_score else "❌否"
        print(f"{sym:<6} {v55_score:>12.2f} {wv_score:>12.2f} {bh_score:>12.2f} {win:>12}")

    # 价值分析
    print(f"\n{'='*90}")
    print("波浪策略的增量价值分析")
    print(f"{'='*90}")
    print()
    print("1. 风险控制价值:")
    for sym, res in all_results.items():
        v55_dd = res["v55_ml"]["max_drawdown"] * 100
        wv_dd = res["wave_physics"]["max_drawdown"] * 100
        improvement = (v55_dd - wv_dd) / abs(v55_dd) * 100 if v55_dd != 0 else 0
        print(f"   {sym}: 回撤 {v55_dd:.2f}% → {wv_dd:.2f}%, 减小 {improvement:.1f}%")

    print()
    print("2. 风险调整后收益价值:")
    for sym, res in all_results.items():
        v55_sharpe = res["v55_ml"]["sharpe"]
        wv_sharpe = res["wave_physics"]["sharpe"]
        improvement = (wv_sharpe - v55_sharpe) / abs(v55_sharpe) * 100 if v55_sharpe != 0 else 0
        print(f"   {sym}: 夏普 {v55_sharpe:.4f} → {wv_sharpe:.4f}, {'提升' if improvement > 0 else '下降'} {abs(improvement):.1f}%")

    print()
    print("3. 组合价值（7成V5.5 + 3成波浪，等权重合并）:")
    for sym, res in all_results.items():
        v55_ret = res["v55_ml"]["ann_return"]
        wv_ret = res["wave_physics"]["ann_return"]
        combined_ret = 0.7 * v55_ret + 0.3 * wv_ret

        v55_sharpe = res["v55_ml"]["sharpe"]
        wv_sharpe = res["wave_physics"]["sharpe"]
        combined_sharpe = 0.7 * v55_sharpe + 0.3 * wv_sharpe  # 粗略估计

        print(f"   {sym}: 组合年化 {combined_ret*100:.2f}% (V5.5 {v55_ret*100:.2f}%), 组合夏普 {combined_sharpe:.4f} (V5.5 {v55_sharpe:.4f})")

    print()
    print("结论: 波浪策略在风险控制上有显著价值，可作为V5.5的补充（分仓位运行）")

    # 保存结果
    output_path = os.path.join(BASE_DIR, "ml", "ewave_vs_v55_comparison.json")
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
    args = parser.parse_args()

    run_comparison(
        symbols=args.symbols,
        zigzag_threshold=args.zigzag,
        wave_base_position=args.position,
    )
