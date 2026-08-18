#!/usr/bin/env python3
"""
物理引擎驱动的动态仓位管理与风险预算实验
探索物理引擎在仓位管理上的6种应用策略

对比策略：
1. 基线：固定基础仓位3成
2. η趋势仓位：强趋势加仓，弱趋势减仓
3. 风险预算仓位：波动率（摩擦力）反比调整仓位
4. 动能力度仓位：动能充沛时加仓，衰竭时减仓
5. 综合物理仓位：η趋势 + 动能 + 风险预算三维调节
6. 凯利式物理仓位：基于物理胜率和赔率的凯利公式

风险预算核心思想：
- 摩擦力占比高（高波动）→ 减仓（风险预算约束）
- 动量传递效率高（强趋势）→ 加仓
- 动能充沛 → 加仓
- 三者综合 → 最优仓位
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

    # 额外提取物理量用于仓位管理
    momentum = dyn_feats["dyn_momentum"].values
    kinetic_energy = dyn_feats["dyn_kinetic_energy"].values
    force_net = dyn_feats["dyn_force_net"].values
    friction_ratio = dyn_feats["dyn_friction_ratio"].values
    force_ratio_wd = dyn_feats["dyn_force_ratio_WD"].values

    # 波动率（温度）作为风险预算的核心
    closes = prices["close"].values
    highs = prices["high"].values
    lows = prices["low"].values
    prev_closes = np.concatenate([[closes[0]], closes[:-1]])
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)))
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    volatility = atr / closes  # 归一化波动率

    # 波动率排名（百分位）
    vol_rank = pd.Series(volatility).rank(pct=True).values

    return {
        "eta": eta_series,
        "phys_conf": phys_conf,
        "trend_score": phys_components.get("trend_score", np.full(n, 0.5)),
        "reversal_score": phys_components.get("reversal_score", np.full(n, 0.5)),
        "support_score": phys_components.get("support_score", np.full(n, 0.5)),
        "kinetic_score": phys_components.get("kinetic_score", np.full(n, 0.5)),
        "momentum": momentum,
        "kinetic_energy": kinetic_energy,
        "force_net": force_net,
        "friction_ratio": friction_ratio,
        "force_ratio_wd": force_ratio_wd,
        "volatility": volatility,
        "vol_rank": vol_rank,
    }


def compute_wave_position_with_sizing(
    prices, wave_signals, wave_confs, physics_feats,
    base_position=0.3,
    wave_conf_threshold=0.7,
    phys_conf_threshold=0.5,
    sizing_mode="fixed",
    trailing_mode="combo",
    base_trailing_pct=0.08,
    take_profit_mode="kinetic",
    base_take_profit_pct=0.25,
):
    """波浪策略仓位计算（带多种仓位管理模式）

    sizing_mode:
    - "fixed": 固定基础仓位
    - "eta": η趋势仓位（强趋势加仓）
    - "risk_budget": 风险预算仓位（波动率反比）
    - "kinetic": 动能力度仓位（动能充沛加仓）
    - "combo": 综合物理仓位（η + 动能 + 风险预算）
    - "kelly": 凯利式物理仓位
    """
    n = len(prices)
    closes = prices["close"].values
    highs = prices["high"].values
    lows = prices["low"].values

    eta_series = physics_feats["eta"]
    phys_conf = physics_feats["phys_conf"]
    trend_score = physics_feats["trend_score"]
    reversal_score = physics_feats["reversal_score"]
    kinetic_score = physics_feats["kinetic_score"]
    momentum = physics_feats["momentum"]
    kinetic_energy = physics_feats["kinetic_energy"]
    friction_ratio = physics_feats["friction_ratio"]
    vol_rank = physics_feats["vol_rank"]

    position = np.zeros(n)
    direction = np.zeros(n)

    current_pos = 0.0
    current_dir = 0
    current_entry = 0.0
    trailing_stop_price = 0.0
    peak_price = 0.0
    trough_price = 0.0
    trail_pct = base_trailing_pct
    tp_pct = base_take_profit_pct

    wave_long_signals = ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
    wave_short_signals = ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")

    stats = {
        "total_enter": 0, "total_exit_by_trailing": 0,
        "total_exit_by_tp": 0, "total_exit_by_signal": 0,
        "position_sizes": [],
        "pos_min": 1.0, "pos_max": 0.0,
    }

    # 凯利公式的滚动胜率估计
    trade_results = []  # 记录每笔交易盈亏

    for i in range(n):
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])

        # 信号过滤
        if sig in wave_long_signals or sig in wave_short_signals:
            if wave_conf < wave_conf_threshold:
                sig = "WAIT"
        if sig in wave_long_signals or sig in wave_short_signals:
            pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
            if pc < phys_conf_threshold:
                sig = "WAIT"

        # 计算当日动态追踪止损距离和止盈目标
        if current_dir != 0:
            if trailing_mode == "fixed":
                trail_pct = base_trailing_pct
            elif trailing_mode == "combo":
                ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
                rs = float(reversal_score[i]) if not np.isnan(reversal_score[i]) else 0.5
                ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
                combined = ts * 0.5 + rs * 0.3 + ks * 0.2
                trail_factor = 0.5 + 1.5 * combined
                trail_pct = np.clip(base_trailing_pct * trail_factor, 0.02, 0.15)

            if take_profit_mode == "fixed":
                tp_pct = base_take_profit_pct
            elif take_profit_mode == "kinetic":
                ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
                tp_factor = 0.5 + 1.5 * ks
                tp_pct = np.clip(base_take_profit_pct * tp_factor, 0.08, 0.50)

        # 计算动态仓位大小
        def compute_position_size():
            if sizing_mode == "fixed":
                return base_position

            elif sizing_mode == "eta":
                # η趋势仓位：趋势越强，仓位越大
                ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
                # 映射到 [0.5×base, 2.0×base]
                size = base_position * (0.5 + 1.5 * ts)
                return np.clip(size, 0.1, 1.0)

            elif sizing_mode == "risk_budget":
                # 风险预算：波动率越高，仓位越小（反比）
                # vol_rank 0~1，1=最高波动率
                vr = float(vol_rank[i]) if not np.isnan(vol_rank[i]) else 0.5
                # 波动率排名映射到仓位因子 [0.3, 1.5]
                # 低波动(rank=0) → 1.5×base，高波动(rank=1) → 0.3×base
                risk_factor = 1.5 - 1.2 * vr
                size = base_position * risk_factor
                return np.clip(size, 0.1, 1.0)

            elif sizing_mode == "kinetic":
                # 动能力度仓位：动能充沛时加仓
                ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
                size = base_position * (0.5 + 1.5 * ks)
                return np.clip(size, 0.1, 1.0)

            elif sizing_mode == "combo":
                # 综合物理仓位：η趋势(0.3) + 动能(0.3) + 风险预算(0.4)
                ts = float(trend_score[i]) if not np.isnan(trend_score[i]) else 0.5
                ks = float(kinetic_score[i]) if not np.isnan(kinetic_score[i]) else 0.5
                vr = float(vol_rank[i]) if not np.isnan(vol_rank[i]) else 0.5
                # 趋势+动能加成
                momentum_boost = 0.5 + 1.0 * (ts * 0.5 + ks * 0.5)
                # 风险预算约束
                risk_factor = 1.5 - 1.2 * vr
                # 综合
                size = base_position * momentum_boost * risk_factor / 1.0
                return np.clip(size, 0.1, 1.0)

            elif sizing_mode == "kelly":
                # 凯利式物理仓位
                # 胜率估计：基于物理置信度
                pc = float(phys_conf[i]) if not np.isnan(phys_conf[i]) else 0.5
                # 物理置信度映射到胜率 [0.35, 0.65]
                win_prob = 0.35 + 0.30 * pc
                # 赔率估计：基于止盈/止损比
                odds = tp_pct / trail_pct if trail_pct > 0 else 2.0
                # 凯利公式：f = (p * b - (1-p)) / b
                kelly_f = (win_prob * odds - (1 - win_prob)) / odds
                # 半凯利（更保守）
                kelly_f = max(0, kelly_f * 0.5)
                # 映射到仓位 [0.1, 1.0]
                size = kelly_f
                return np.clip(size, 0.1, 1.0)

            return base_position

        # 入场逻辑
        if sig in wave_long_signals:
            if current_dir != 1:
                new_pos = compute_position_size() * max(wave_conf, 0.5)
                new_pos = min(new_pos, 1.0)

                if current_dir != 0:
                    # 记录上一笔交易结果
                    pnl = (closes[i] - current_entry) / current_entry if current_dir == 1 else (current_entry - closes[i]) / current_entry
                    trade_results.append(pnl)
                    current_pos = 0.0
                    current_dir = 0
                    stats["total_exit_by_signal"] += 1

                current_pos = new_pos
                current_dir = 1
                current_entry = closes[i]
                peak_price = highs[i]
                trailing_stop_price = current_entry * (1 - base_trailing_pct)
                stats["total_enter"] += 1
                stats["position_sizes"].append(new_pos)
                stats["pos_min"] = min(stats["pos_min"], new_pos)
                stats["pos_max"] = max(stats["pos_max"], new_pos)

        elif sig in wave_short_signals:
            if current_dir != -1:
                new_pos = compute_position_size() * max(wave_conf, 0.5)
                new_pos = min(new_pos, 1.0)

                if current_dir != 0:
                    pnl = (closes[i] - current_entry) / current_entry if current_dir == 1 else (current_entry - closes[i]) / current_entry
                    trade_results.append(pnl)
                    current_pos = 0.0
                    current_dir = 0
                    stats["total_exit_by_signal"] += 1

                current_pos = new_pos
                current_dir = -1
                current_entry = closes[i]
                trough_price = lows[i]
                trailing_stop_price = current_entry * (1 + base_trailing_pct)
                stats["total_enter"] += 1
                stats["position_sizes"].append(new_pos)
                stats["pos_min"] = min(stats["pos_min"], new_pos)
                stats["pos_max"] = max(stats["pos_max"], new_pos)

        elif sig in ("EXIT_LONG", "EXIT_SHORT", "WAIT") and current_dir != 0:
            pnl = (closes[i] - current_entry) / current_entry if current_dir == 1 else (current_entry - closes[i]) / current_entry
            trade_results.append(pnl)
            current_pos = 0.0
            current_dir = 0
            stats["total_exit_by_signal"] += 1

        # 持仓中：更新追踪止损并检查
        if current_dir == 1 and current_entry > 0:
            peak_price = max(peak_price, highs[i])
            new_trail = peak_price * (1 - trail_pct)
            if new_trail > trailing_stop_price:
                trailing_stop_price = new_trail

            if lows[i] <= trailing_stop_price:
                pnl = (trailing_stop_price - current_entry) / current_entry
                trade_results.append(pnl)
                current_pos = 0.0
                current_dir = 0
                stats["total_exit_by_trailing"] += 1
                continue

            current_tp = current_entry * (1 + tp_pct)
            if highs[i] >= current_tp:
                pnl = (current_tp - current_entry) / current_entry
                trade_results.append(pnl)
                current_pos = 0.0
                current_dir = 0
                stats["total_exit_by_tp"] += 1
                continue

        elif current_dir == -1 and current_entry > 0:
            trough_price = min(trough_price, lows[i])
            new_trail = trough_price * (1 + trail_pct)
            if new_trail < trailing_stop_price:
                trailing_stop_price = new_trail

            if highs[i] >= trailing_stop_price:
                pnl = (current_entry - trailing_stop_price) / current_entry
                trade_results.append(pnl)
                current_pos = 0.0
                current_dir = 0
                stats["total_exit_by_trailing"] += 1
                continue

            current_tp = current_entry * (1 - tp_pct)
            if lows[i] <= current_tp:
                pnl = (current_entry - current_tp) / current_entry
                trade_results.append(pnl)
                current_pos = 0.0
                current_dir = 0
                stats["total_exit_by_tp"] += 1
                continue

        position[i] = current_pos * current_dir if current_dir != 0 else 0
        direction[i] = current_dir

    # 统计
    stats["avg_position_size"] = np.mean(stats["position_sizes"]) if stats["position_sizes"] else 0
    stats["trade_count"] = len(trade_results)
    stats["win_trades"] = sum(1 for r in trade_results if r > 0)
    stats["lose_trades"] = sum(1 for r in trade_results if r <= 0)
    stats["win_rate"] = stats["win_trades"] / stats["trade_count"] if stats["trade_count"] > 0 else 0
    stats["avg_win"] = np.mean([r for r in trade_results if r > 0]) if stats["win_trades"] > 0 else 0
    stats["avg_lose"] = np.mean([r for r in trade_results if r <= 0]) if stats["lose_trades"] > 0 else 0

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


def run_sizing_experiment(symbol="BTC"):
    print(f"\n{'='*120}")
    print(f"  物理驱动动态仓位管理与风险预算实验 - {symbol}")
    print(f"{'='*120}")

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

    # 物理量分布统计
    print(f"\n[4/5] 物理量分布统计:")
    print(f"  η (耦合效率):  均值={np.nanmean(physics_feats['eta']):.4f}, 范围=[{np.nanmin(physics_feats['eta']):.4f}, {np.nanmax(physics_feats['eta']):.4f}]")
    print(f"  波动率排名:    均值={np.nanmean(physics_feats['vol_rank']):.4f}")
    print(f"  动能评分:      均值={np.nanmean(physics_feats['kinetic_score']):.4f}")
    print(f"  物理置信度:    均值={np.nanmean(physics_feats['phys_conf']):.4f}")
    print(f"  摩擦力占比:    均值={np.nanmean(physics_feats['friction_ratio']):.4f}")

    # 实验配置
    configs = [
        ("基线（固定仓位3成）", "fixed"),
        ("η趋势仓位", "eta"),
        ("风险预算仓位", "risk_budget"),
        ("动能力度仓位", "kinetic"),
        ("综合物理仓位", "combo"),
        ("凯利式物理仓位", "kelly"),
    ]

    print(f"\n[5/5] 测试 {len(configs)} 种仓位管理配置...")
    print(f"\n{'='*120}")
    print(f"  纯波浪策略 - 不同仓位管理对比")
    print(f"{'='*120}")
    print(f"{'配置':<22} {'年化':>8} {'总收益':>9} {'夏普':>8} {'回撤':>8} {'Calmar':>8} {'胜率':>7} {'均仓':>6} {'仓位范围':>12} {'交易':>5} {'盈亏比':>7}")
    print(f"{'-'*115}")

    wave_results = {}
    for name, sizing_mode in configs:
        wave_pos, wave_dir, stats = compute_wave_position_with_sizing(
            prices, wave_signals, wave_confs, physics_feats,
            base_position=0.3,
            wave_conf_threshold=0.7,
            phys_conf_threshold=0.5,
            sizing_mode=sizing_mode,
            trailing_mode="combo",
            base_trailing_pct=0.08,
            take_profit_mode="kinetic",
            base_take_profit_pct=0.25,
        )
        m = backtest_position(wave_pos[valid_start:], wave_dir[valid_start:], prices.iloc[valid_start:])
        wave_results[name] = {"metrics": m, "stats": stats}

        pos_range = f"{stats['pos_min']:.2f}~{stats['pos_max']:.2f}"
        trade_count = stats["trade_count"]
        win_rate = stats["win_rate"] * 100
        avg_win = stats["avg_win"] * 100
        avg_lose = abs(stats["avg_lose"]) * 100
        profit_factor = avg_win / avg_lose if avg_lose > 0 else 0

        print(f"{name:<22} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>8.1f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>7.2f}% {m['calmar']:>8.4f} {win_rate:>6.1f}% {m['avg_position']:>6.3f} {pos_range:>12} {trade_count:>5} {profit_factor:>7.2f}")

    # 融合策略对比
    print(f"\n{'='*120}")
    print(f"  智能融合策略 - 不同仓位管理对比（加仓50%/抄底25%）")
    print(f"{'='*120}")
    print(f"{'配置':<22} {'年化':>8} {'总收益':>9} {'夏普':>8} {'回撤':>8} {'Calmar':>8} {'均仓':>6}")
    print(f"{'-'*80}")

    fusion_results = {}
    for name, sizing_mode in configs:
        wave_pos, wave_dir, stats = compute_wave_position_with_sizing(
            prices, wave_signals, wave_confs, physics_feats,
            base_position=0.3,
            wave_conf_threshold=0.7,
            phys_conf_threshold=0.5,
            sizing_mode=sizing_mode,
            trailing_mode="combo",
            base_trailing_pct=0.08,
            take_profit_mode="kinetic",
            base_take_profit_pct=0.25,
        )
        smart_pos, smart_dir = compute_smart_fusion(v4_pos, v4_dir, wave_pos, wave_dir)
        m = backtest_position(smart_pos[valid_start:], smart_dir[valid_start:], prices.iloc[valid_start:])
        fusion_results[name] = m
        print(f"{name:<22} {m['ann_return']*100:>7.2f}% {m['total_return']*100:>8.1f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>7.2f}% {m['calmar']:>8.4f} {m['avg_position']:>6.3f}")

    m_v4 = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:], prices.iloc[valid_start:])
    print(f"{'纯V4 (参考)':<22} {m_v4['ann_return']*100:>7.2f}% {m_v4['total_return']*100:>8.1f}% {m_v4['sharpe']:>8.4f} {m_v4['max_drawdown']*100:>7.2f}% {m_v4['calmar']:>8.4f} {m_v4['avg_position']:>6.3f}")

    # 增量分析
    print(f"\n{'='*120}")
    print(f"  相对基线的增量（融合策略）")
    print(f"{'='*120}")
    print(f"{'配置':<22} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'综合评分':>10}")
    print(f"{'-'*75}")

    base_m = fusion_results["基线（固定仓位3成）"]
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
        print(f"{name:<22} {ann_delta:>+9.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+9.2f}pp {score:>10.4f}{mark}")

    print(f"\n最优配置: {best_name} (综合评分: {best_score:.4f})")

    # 保存
    os.makedirs("ml/backtest_results", exist_ok=True)
    save_data = {
        "symbol": symbol,
        "wave_results": {k: {"metrics": v["metrics"], "stats": {kk: vv for kk, vv in v["stats"].items() if isinstance(vv, (int, float))}} for k, v in wave_results.items()},
        "fusion_results": fusion_results,
        "v4_baseline": m_v4,
        "best_config": best_name,
    }
    with open(f"ml/backtest_results/physics_sizing_{symbol.lower()}.json", "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存到 ml/backtest_results/physics_sizing_{symbol.lower()}.json")

    return wave_results, fusion_results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="物理驱动动态仓位管理实验")
    parser.add_argument("--symbol", type=str, default="BTC")
    args = parser.parse_args()
    run_sizing_experiment(symbol=args.symbol)


if __name__ == "__main__":
    main()
