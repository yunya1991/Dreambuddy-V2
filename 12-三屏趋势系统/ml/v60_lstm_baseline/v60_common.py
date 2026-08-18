"""V6.0 混合回测公共模块

注意：本模块不import任何ML模型库（lightgbm/torch），
避免OpenMP冲突。各预测脚本各自import所需库。
"""

import os
import sys
import json
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '12-三屏趋势系统'))


def load_coin_data(symbol: str) -> pd.DataFrame:
    path = os.path.join(BASE_DIR, f"data/historical/{symbol}_1D_730d.json")
    with open(path) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def generate_labels(closes, lookahead=20, threshold=0.20, mode="drop"):
    """mode='drop': 未来下跌超threshold→1（逃顶）; mode='rise': 未来上涨超threshold→1（抄底）"""
    n = len(closes)
    labels = np.zeros(n)
    for i in range(n - lookahead):
        future = closes[i + lookahead]
        if mode == "drop":
            if (closes[i] - future) / closes[i] > threshold:
                labels[i] = 1
        else:
            if (future - closes[i]) / closes[i] > threshold:
                labels[i] = 1
    return labels


def build_features(prices):
    """构建特征（不import模型库）"""
    from ml.feature_engineer import TrendFeatureEngineer
    from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer

    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns
                  if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    redundant = ["dip_buy_level", "dip_buy_position_ratio", "left_side_buy_signal"]
    phil_cols = [c for c in phil_features.columns if c not in redundant]

    features = pd.concat([trend_features, phil_features[phil_cols]], axis=1)
    features = features.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    return features


def walk_forward_splits(n, train_days=730, test_days=180, step_days=180, lookahead=20):
    """返回 [(train_start, train_end, test_start, test_end), ...]"""
    splits = []
    test_end = n
    while True:
        test_start = test_end - test_days
        train_end = test_start
        train_start = train_end - train_days
        if train_start < lookahead or test_start < 0:
            break
        splits.append((train_start, train_end, test_start, test_end))
        test_end -= step_days
    return list(reversed(splits))


def compute_v4_position(prices, symbol="BTC"):
    """计算V4减半周期策略仓位"""
    from ml.halving_top_exit_strategy import HalvingTopExitStrategy

    is_btc = (symbol == "BTC")
    strategy = HalvingTopExitStrategy(
        symbol=symbol, is_btc=is_btc,
        btc_prices=prices if is_btc else None,
    )
    pos_series = strategy.generate_signals(prices)
    pos_arr = pos_series.values if hasattr(pos_series, 'values') else np.array(pos_series)
    direction = np.sign(pos_arr)
    abs_pos = np.abs(pos_arr)
    return abs_pos, direction


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

    years = n / 365
    cum_ret = np.cumprod(1 + strategy_ret_net) - 1
    ann_ret = (1 + cum_ret[-1]) ** (1 / years) - 1 if years > 0 else 0

    daily_nonzero = strategy_ret_net[strategy_ret_net != 0]
    sharpe = (np.mean(daily_nonzero) / (np.std(daily_nonzero) + 1e-10) * np.sqrt(365)
              if len(daily_nonzero) > 10 else 0.0)

    cum_value = np.cumprod(1 + strategy_ret_net)
    running_max = np.maximum.accumulate(cum_value)
    drawdown = (cum_value - running_max) / running_max
    max_dd = np.min(drawdown) if len(drawdown) > 0 else 0.0
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    holding_days = int(np.sum(position > 0))
    win_days = int(np.sum((position > 0) & (strategy_ret_net > 0)))
    win_rate = win_days / holding_days if holding_days > 0 else 0.0

    entries = int(np.sum((direction != 0) & (np.concatenate([[0], direction[:-1]]) == 0)))
    exits = int(np.sum((direction == 0) & (np.concatenate([[0], direction[:-1]]) != 0)))
    trades = min(entries, exits)

    return {
        "ann_return": float(ann_ret),
        "total_return": float(cum_ret[-1]),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "win_rate": float(win_rate),
        "holding_days": holding_days,
        "trades": trades,
        "avg_position": float(np.mean(position)),
    }


def print_result_row(name, m):
    ann = m['ann_return'] * 100
    tot = m['total_return'] * 100
    sharpe = m['sharpe']
    mdd = m['max_drawdown'] * 100
    calmar = m['calmar']
    win = m['win_rate'] * 100
    avgpos = m['avg_position']
    print(f"{name:<30s} {ann:>7.2f}% {tot:>9.2f}% {sharpe:>8.4f} {mdd:>9.2f}% {calmar:>8.4f} {win:>7.2f}% {avgpos:>7.3f}")
