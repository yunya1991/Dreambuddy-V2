"""方向2: 波浪理论 + 物理引擎五浪趋势捕捉回测

策略设计:
- 信号源: 艾略特波浪识别器（技术指标的波浪理论）
- 信号评估器: 物理置信度评估器（与方向1相同的PhysicsConfidenceScorer）
- 仓位: 3成基础仓位 × 物理调节系数
- 入场: 浪2结束/浪4结束的入场信号
- 离场: 浪5结束信号 或 止损/止盈

回测对比:
- 基线1: V5.5 ML策略 (用户已确认基线)
- 基线2: 买入持有
- 测试策略: 波浪策略 + 物理调节 vs 波浪策略（无物理调节）

关键指标:
- 年化收益、夏普比、最大回撤、Calmar比、胜率

文件: ml/ewave_backtest.py
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from typing import Dict, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.ewave_recognizer import ElliottWaveRecognizer, WAVE_SIGNALS
from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
from ml.pitd_kinematics_engineer import KinematicsEngineer
from ml.pitd_dynamics_engineer import DynamicsEngineer


def load_coin_data(symbol: str = "BTC") -> pd.DataFrame:
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


def generate_wave_signals(prices: pd.DataFrame, zigzag_threshold: float = 0.05) -> pd.DataFrame:
    """生成波浪信号时间序列（滚动识别）"""
    recognizer = ElliottWaveRecognizer(zigzag_threshold=zigzag_threshold)
    print(f"[Wave] 滚动识别波浪结构 (threshold={zigzag_threshold})...")

    n = len(prices)
    signals = []
    labels = []
    waves = []
    confs = []

    t0 = time.time()
    min_window = 90  # 最小识别窗口
    for i in range(n):
        if i < min_window:
            signals.append("WAIT")
            labels.append("INCOMPLETE")
            waves.append(0)
            confs.append(0.0)
            continue

        if i % 200 == 0:
            elapsed = time.time() - t0
            eta = elapsed / max(i, 1) * (n - i) if i > 0 else 0
            print(f"  进度 {i}/{n} ({i/n*100:.1f}%), 已用 {elapsed:.1f}s, 剩余 ~{eta:.1f}s")

        slice_df = prices.iloc[: i + 1]
        try:
            ws = recognizer.identify_waves(slice_df)
            signals.append(ws.signal)
            labels.append(ws.wave_label)
            waves.append(ws.current_wave)
            confs.append(ws.confidence)
        except Exception:
            signals.append("WAIT")
            labels.append("INCOMPLETE")
            waves.append(0)
            confs.append(0.0)

    print(f"  完成, 用时 {time.time()-t0:.1f}s")
    return pd.DataFrame(
        {
            "wave_signal": signals,
            "wave_label": labels,
            "current_wave": waves,
            "wave_confidence": confs,
        },
        index=prices.index,
    )


def compute_physics_confidence(prices: pd.DataFrame) -> pd.DataFrame:
    """计算物理置信度时间序列（一次性向量化计算）"""
    print("[Physics] 计算物理置信度时间序列...")
    t0 = time.time()

    # 最优参数（与方向1集成相同）
    weights = ConfidenceWeights(
        w_eta=0.211, w_reversal=0.368,
        w_support=0.211, w_kinetic=0.211,
        position_lower=0.6, position_scale=1.0,
    )
    scorer = PhysicsConfidenceScorer(weights)

    # 物理特征计算（KinematicsEngineer + DynamicsEngineer）
    kin_fe = KinematicsEngineer()
    dyn_fe = DynamicsEngineer()
    kin_feats = kin_fe.extract_series(prices)
    dyn_feats = dyn_fe.extract_series(prices, kin_feats)
    eta_series = dyn_feats["dyn_coupling_eta"].values

    # 用零信号计算各分量评分（信号方向由波浪方向决定，单独处理）
    # 这里先计算"基础物理置信度"（不考虑ml_signal方向），后续按方向叠加
    # 由于score_signals需要ml_predictions，我们传入0.5（中性）得到基础分量
    n = len(prices)
    ml_pred_neutral = np.full(n, 0.5)
    conf_arr, components = scorer.score_signals(prices=prices, ml_predictions=ml_pred_neutral)

    physics_df = pd.DataFrame(
        {
            "physics_confidence": conf_arr,
            "eta": eta_series,
            "trend_score": components["trend_score"],
            "reversal_score": components["reversal_score"],
            "support_score": components["support_score"],
            "kinetic_score": components["kinetic_score"],
        },
        index=prices.index,
    )
    print(f"  完成, 用时 {time.time()-t0:.1f}s")
    return physics_df


def backtest_wave_strategy(
    prices: pd.DataFrame,
    wave_signals: pd.DataFrame,
    physics_df: pd.DataFrame,
    base_position: float = 0.3,
    use_physics: bool = True,
    stop_loss_pct: float = 0.10,
    take_profit_pct: float = 0.30,
    cost_pct: float = 0.001,
) -> Dict:
    """回测波浪策略

    策略逻辑:
    1. 入场: 波浪识别器给出ENTER_LONG/ENTER_SHORT信号
    2. 离场: EXIT信号 或 止损/止盈
    3. 仓位: 基础仓位 × 物理调节系数（如启用）
    4. 持仓期间: 保持仓位不变（HOLD信号不增减）

    参数:
        base_position: 基础仓位 (3成=0.3)
        use_physics: 是否启用物理置信度调节
        stop_loss_pct: 止损比例
        take_profit_pct: 止盈比例
        cost_pct: 单边交易成本
    """
    print(f"[Backtest] base_pos={base_position}, use_physics={use_physics}")
    t0 = time.time()

    n = len(prices)
    closes = prices["close"].values
    highs = prices["high"].values
    lows = prices["low"].values

    # 合并信号
    df = prices.copy()
    df["wave_signal"] = wave_signals["wave_signal"]
    df["wave_confidence"] = wave_signals["wave_confidence"]
    df["physics_confidence"] = physics_df["physics_confidence"]
    df["eta"] = physics_df["eta"]

    # 仓位和持仓方向
    position = np.zeros(n)  # 仓位 [0, 1]
    direction = np.zeros(n)  # +1=多, -1=空, 0=空仓
    entry_price = np.zeros(n)

    # 状态变量
    current_pos = 0.0
    current_dir = 0
    current_entry = 0.0

    for i in range(n):
        sig = df["wave_signal"].iloc[i]
        wave_conf = float(df["wave_confidence"].iloc[i])

        # 信号处理
        # 入场信号：ENTER_*_W3/W5 + HOLD_*_W3（浪3进行中=事后确认的入场点）
        # 离场信号：EXIT_*_W5（浪5结束）
        if sig in ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3"):
            # 入场或持有做多
            if current_dir != 1:
                # 计算仓位
                new_pos = base_position * max(wave_conf, 0.5)  # 波浪置信度调节，下限0.5
                if use_physics:
                    # 物理置信度调节（弱趋势时启用）
                    eta_i = float(df["eta"].iloc[i])
                    phys_conf_i = float(df["physics_confidence"].iloc[i])
                    if eta_i < 0.10:
                        # 弱趋势时物理调节
                        multiplier = 0.6 + 1.0 * phys_conf_i
                        new_pos = new_pos * multiplier
                new_pos = min(new_pos, 1.0)

                # 离场旧仓位（如有）
                if current_dir != 0:
                    current_pos = 0.0
                    current_dir = 0

                current_pos = new_pos
                current_dir = 1
                current_entry = closes[i]

        elif sig in ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3"):
            # 入场或持有做空
            if current_dir != -1:
                new_pos = base_position * max(wave_conf, 0.5)
                if use_physics:
                    eta_i = float(df["eta"].iloc[i])
                    phys_conf_i = float(df["physics_confidence"].iloc[i])
                    if eta_i < 0.10:
                        multiplier = 0.6 + 1.0 * phys_conf_i
                        new_pos = new_pos * multiplier
                new_pos = min(new_pos, 1.0)

                if current_dir != 0:
                    current_pos = 0.0
                    current_dir = 0

                current_pos = new_pos
                current_dir = -1
                current_entry = closes[i]

        elif sig in ("EXIT_LONG_W5", "EXIT_SHORT_W5"):
            # 离场
            current_pos = 0.0
            current_dir = 0
            current_entry = 0.0

        # 止损/止盈检查（基于当日高低点）
        if current_dir == 1:  # 多头
            if lows[i] <= current_entry * (1 - stop_loss_pct):
                current_pos = 0.0
                current_dir = 0
            elif highs[i] >= current_entry * (1 + take_profit_pct):
                current_pos = 0.0
                current_dir = 0
        elif current_dir == -1:  # 空头
            if highs[i] >= current_entry * (1 + stop_loss_pct):
                current_pos = 0.0
                current_dir = 0
            elif lows[i] <= current_entry * (1 - take_profit_pct):
                current_pos = 0.0
                current_dir = 0

        position[i] = current_pos
        direction[i] = current_dir
        entry_price[i] = current_entry

    # 计算收益
    df["position"] = position
    df["direction"] = direction
    df["entry_price"] = entry_price

    # 日收益率
    daily_ret = closes[1:] / closes[:-1] - 1
    daily_ret = np.concatenate([[0], daily_ret])

    # 策略收益 = 仓位 × 方向 × 日收益
    strategy_ret = position * direction * daily_ret

    # 交易成本（仓位变化时）
    position_change = np.abs(np.diff(np.concatenate([[0], position])))
    cost = position_change * cost_pct
    strategy_ret_net = strategy_ret - cost

    # 累计收益
    cum_ret = np.cumprod(1 + strategy_ret_net) - 1

    # 计算指标
    days = n
    years = days / 365
    ann_ret = (1 + cum_ret[-1]) ** (1 / years) - 1 if years > 0 else 0

    # 夏普比（年化）
    daily_ret_nonzero = strategy_ret_net[strategy_ret_net != 0]
    if len(daily_ret_nonzero) > 10:
        sharpe = np.mean(daily_ret_nonzero) / (np.std(daily_ret_nonzero) + 1e-10) * np.sqrt(365)
    else:
        sharpe = 0.0

    # 最大回撤
    cum_value = np.cumprod(1 + strategy_ret_net)
    running_max = np.maximum.accumulate(cum_value)
    drawdown = (cum_value - running_max) / running_max
    max_dd = np.min(drawdown) if len(drawdown) > 0 else 0.0

    # Calmar比
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    # 胜率（持仓期间正收益占比）
    holding_days = np.sum(position > 0)
    win_days = np.sum((position > 0) & (strategy_ret_net > 0))
    win_rate = win_days / holding_days if holding_days > 0 else 0.0

    # 交易次数
    entries = np.sum((direction != 0) & (np.concatenate([[0], direction[:-1]]) == 0))
    exits = np.sum((direction == 0) & (np.concatenate([[0], direction[:-1]]) != 0))
    trades = min(entries, exits)

    # 信号分布
    sig_counts = df["wave_signal"].value_counts().to_dict()

    result = {
        "total_days": days,
        "years": round(years, 2),
        "ann_return": float(ann_ret),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "win_rate": float(win_rate),
        "holding_days": int(holding_days),
        "trades": int(trades),
        "final_cum_return": float(cum_ret[-1]),
        "signal_distribution": sig_counts,
        "use_physics": use_physics,
        "base_position": base_position,
    }

    print(f"  完成, 用时 {time.time()-t0:.1f}s")
    return result, df


def backtest_baseline_buy_hold(prices: pd.DataFrame) -> Dict:
    """基线: 买入持有"""
    closes = prices["close"].values
    n = len(closes)
    cum_ret = closes[-1] / closes[0] - 1
    years = n / 365
    ann_ret = (1 + cum_ret) ** (1 / years) - 1

    daily_ret = closes[1:] / closes[:-1] - 1
    sharpe = np.mean(daily_ret) / (np.std(daily_ret) + 1e-10) * np.sqrt(365)

    cum_value = np.cumprod(1 + np.concatenate([[0], daily_ret]))
    running_max = np.maximum.accumulate(cum_value)
    drawdown = (cum_value - running_max) / running_max
    max_dd = np.min(drawdown) if len(drawdown) > 0 else 0.0

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    return {
        "total_days": n,
        "years": round(years, 2),
        "ann_return": float(ann_ret),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "final_cum_return": float(cum_ret),
        "strategy": "buy_hold",
    }


def run_ewave_backtest(symbols=None, zigzag_threshold=0.05, base_position=0.3):
    """运行波浪策略回测"""
    if symbols is None:
        symbols = ["BTC", "ETH", "SOL", "UNI"]

    print("=" * 70)
    print("方向2: 波浪理论 + 物理引擎 五浪趋势捕捉 回测验证")
    print("=" * 70)
    print(f"参数: zigzag_threshold={zigzag_threshold}, base_position={base_position}")
    print(f"币种: {symbols}")
    print()

    all_results = {}

    for symbol in symbols:
        print(f"\n{'='*50}")
        print(f"币种: {symbol}")
        print(f"{'='*50}")

        try:
            prices = load_coin_data(symbol)
            print(f"数据: {len(prices)} 行, 时间范围: {prices.index[0]} ~ {prices.index[-1]}")
        except FileNotFoundError:
            print(f"⚠ {symbol} 数据文件不存在, 跳过")
            continue

        # 1. 生成波浪信号
        wave_signals = generate_wave_signals(prices, zigzag_threshold=zigzag_threshold)

        # 2. 计算物理置信度
        physics_df = compute_physics_confidence(prices)

        # 3. 信号分布
        print(f"\n[Signal] 信号分布:")
        for sig, cnt in wave_signals["wave_signal"].value_counts().items():
            print(f"  {sig}: {cnt} ({cnt/len(wave_signals)*100:.1f}%)")

        # 4. 回测: 波浪策略（无物理调节）
        result_no_phys, _ = backtest_wave_strategy(
            prices, wave_signals, physics_df,
            base_position=base_position, use_physics=False,
        )

        # 5. 回测: 波浪策略 + 物理调节
        result_with_phys, _ = backtest_wave_strategy(
            prices, wave_signals, physics_df,
            base_position=base_position, use_physics=True,
        )

        # 6. 基线: 买入持有
        result_bh = backtest_baseline_buy_hold(prices)

        all_results[symbol] = {
            "wave_only": result_no_phys,
            "wave_with_physics": result_with_phys,
            "buy_hold": result_bh,
        }

        # 打印对比
        print(f"\n[Result] {symbol} 回测结果对比:")
        print(f"{'指标':<15} {'波浪(无物理)':<18} {'波浪+物理':<18} {'买入持有':<18}")
        print(f"{'-'*70}")
        print(f"{'年化收益':<15} {result_no_phys['ann_return']*100:>10.2f}%    {result_with_phys['ann_return']*100:>10.2f}%    {result_bh['ann_return']*100:>10.2f}%")
        print(f"{'夏普比':<15} {result_no_phys['sharpe']:>14.4f}    {result_with_phys['sharpe']:>14.4f}    {result_bh['sharpe']:>14.4f}")
        print(f"{'最大回撤':<15} {result_no_phys['max_drawdown']*100:>10.2f}%    {result_with_phys['max_drawdown']*100:>10.2f}%    {result_bh['max_drawdown']*100:>10.2f}%")
        print(f"{'Calmar比':<15} {result_no_phys['calmar']:>14.4f}    {result_with_phys['calmar']:>14.4f}    {result_bh['calmar']:>14.4f}")
        print(f"{'交易次数':<15} {result_no_phys['trades']:>14d}    {result_with_phys['trades']:>14d}    {'N/A':>14}")
        print(f"{'持仓天数':<15} {result_no_phys['holding_days']:>14d}    {result_with_phys['holding_days']:>14d}    {'N/A':>14}")

    # 总体总结
    print(f"\n{'='*70}")
    print("总体总结")
    print(f"{'='*70}")
    print(f"\n币种 | 波浪年化 | 波浪+物理年化 | 买入持有年化 | 波浪夏普 | 波浪+物理夏普")
    for sym, res in all_results.items():
        wp = res["wave_only"]
        wpp = res["wave_with_physics"]
        bh = res["buy_hold"]
        print(f"{sym:<5} | {wp['ann_return']*100:>8.2f}% | {wpp['ann_return']*100:>10.2f}% | {bh['ann_return']*100:>10.2f}% | {wp['sharpe']:>8.4f} | {wpp['sharpe']:>10.4f}")

    # 保存结果
    output_path = os.path.join(BASE_DIR, "ml", "ewave_backtest_results.json")
    serializable_results = {}
    for sym, res in all_results.items():
        serializable_results[sym] = {}
        for k, v in res.items():
            serializable_results[sym][k] = {
                key: (val if not isinstance(val, dict) else {kk: int(vv) if isinstance(vv, (np.integer,)) else vv for kk, vv in val.items()})
                for key, val in v.items()
            }
    with open(output_path, "w") as f:
        json.dump(serializable_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到: {output_path}")

    return all_results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "UNI"])
    parser.add_argument("--zigzag", type=float, default=0.05)
    parser.add_argument("--position", type=float, default=0.3)
    args = parser.parse_args()

    run_ewave_backtest(
        symbols=args.symbols,
        zigzag_threshold=args.zigzag,
        base_position=args.position,
    )
