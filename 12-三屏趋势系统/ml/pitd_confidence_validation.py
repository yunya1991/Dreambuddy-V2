"""PITD 物理置信度评估器 — 参数寻优与回测验证

流程:
1. 用V5.5 ML生成基础仓位（ML预测概率 → 仓位）
2. 计算物理置信度各分量
3. 参数寻优：网格搜索权重 + Walk-Forward验证
   - 目标：最大化风险调整后收益（夏普比）
   - 参数：w_eta, w_reversal, w_support, w_kinetic, position_lower, position_scale
4. 对比：原始仓位 vs 物理调节仓位
   - 指标：年化收益、夏普比、最大回撤、Calmar比、胜率
5. 不同市场状态下的表现分析

回测逻辑:
- V5.5 ML输出TOP_EXIT和DIP_BUY两个概率
- 基础仓位 = max(DIP_BUY概率 - TOP_EXIT概率, 0)  # 多头仓位
- 物理调节仓位 = 基础仓位 × (lower + scale × confidence)
- 日收益 = 仓位 × 次日收益率
- 考虑交易成本（每次调仓0.1%）
"""

import os
import sys
import json
import time
import itertools
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer
from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights


def load_btc_data() -> pd.DataFrame:
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def generate_labels(closes, lookahead, threshold, mode="drop"):
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


def walk_forward_ml_predictions(features, labels, feature_names,
                                 n_splits=12, train_days=730, test_days=180, step_days=180):
    """Walk-Forward ML预测，返回每个时点的预测概率"""
    n = len(features)
    all_preds = np.full(n, 0.5)
    pred_count = np.zeros(n)

    test_end = n
    splits = []
    for _ in range(n_splits):
        test_start = test_end - test_days
        train_end = test_start
        train_start = train_end - train_days
        if train_start < 0 or test_start < 0:
            break
        splits.append((train_start, train_end, test_start, test_end))
        test_end -= step_days
    splits = list(reversed(splits))

    aucs = []
    for tr_s, tr_e, te_s, te_e in splits:
        X_train = features.iloc[tr_s:tr_e][feature_names].values
        y_train = labels[tr_s:tr_e]
        X_test = features.iloc[te_s:te_e][feature_names].values
        y_test = labels[te_s:te_e]
        if y_train.sum() < 5 or y_test.sum() < 2:
            continue
        model = lgb.LGBMClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            num_leaves=31, min_child_samples=20,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbose=-1,
        )
        model.fit(X_train, y_train)
        preds = model.predict_proba(X_test)[:, 1]
        all_preds[te_s:te_e] += preds
        pred_count[te_s:te_e] += 1
        if len(set(y_test)) > 1:
            aucs.append(roc_auc_score(y_test, preds))

    valid = pred_count > 0
    all_preds[valid] /= pred_count[valid]
    return all_preds, float(np.mean(aucs)) if aucs else 0.0, splits


def compute_base_position(top_exit_pred, dip_buy_pred):
    """根据ML预测生成基础仓位

    改进逻辑：
    - DIP_BUY概率 > 0.5 → 看多，仓位随概率增加
    - TOP_EXIT概率 > 0.5 → 看空，仓位随概率减小
    - 两者都不明确 → 中性仓位
    - 仓位范围: [0, 1]

    具体公式:
      多头信号 = max(DIP_BUY - 0.5, 0) × 2  # [0, 1]
      空头信号 = max(TOP_EXIT - 0.5, 0) × 2  # [0, 1]
      基础仓位 = clip(多头信号 - 空头信号 + 0.3, 0, 1)  # 0.3=中性底仓
    """
    # 多头/空头信号
    bull_signal = np.maximum(dip_buy_pred - 0.5, 0) * 2  # [0, 1]
    bear_signal = np.maximum(top_exit_pred - 0.5, 0) * 2  # [0, 1]

    # 基础仓位 = 中性底仓 + 多头信号 - 空头信号
    base_pos = 0.3 + bull_signal - bear_signal
    base_pos = np.clip(base_pos, 0.0, 1.0)
    return base_pos


def backtest_position(positions, daily_returns, cost_per_trade=0.001):
    """回测仓位策略

    参数:
        positions: 每日仓位 [0, 1]
        daily_returns: 每日收益率
        cost_per_trade: 每次调仓成本（比例）

    返回:
        metrics dict
    """
    n = len(positions)
    # 仓位变化产生的交易成本
    position_changes = np.abs(np.diff(positions, prepend=positions[0]))
    costs = position_changes * cost_per_trade

    # 策略日收益 = 仓位 × 资产收益 - 交易成本
    strategy_returns = positions * daily_returns - costs

    # 累计收益
    cumulative = np.cumprod(1 + strategy_returns)
    total_return = cumulative[-1] - 1

    # 年化收益（假设365天）
    n_days = len(strategy_returns)
    annual_return = (1 + total_return) ** (365 / n_days) - 1

    # 夏普比（年化）
    if np.std(strategy_returns) > 0:
        sharpe = np.mean(strategy_returns) / np.std(strategy_returns) * np.sqrt(365)
    else:
        sharpe = 0

    # 最大回撤
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = np.min(drawdown)

    # Calmar比
    calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

    # 胜率
    win_rate = (strategy_returns > 0).mean()

    # 平均仓位
    avg_position = positions.mean()

    # 交易频率
    trade_frequency = (position_changes > 0.01).mean()

    return {
        "total_return": float(total_return),
        "annual_return": float(annual_return),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "calmar": float(calmar),
        "win_rate": float(win_rate),
        "avg_position": float(avg_position),
        "trade_frequency": float(trade_frequency),
    }


def objective_function(weights_arr, base_position, confidence_components, daily_returns, splits):
    """优化目标函数：最大化Walk-Forward夏普比

    参数:
        weights_arr: [w_eta, w_reversal, w_support, w_kinetic, position_lower, position_scale]
        base_position: 基础仓位
        confidence_components: 物理置信度各分量
        daily_returns: 日收益率
        splits: Walk-Forward分折

    返回:
        平均测试集夏普比（负值，用于最小化）
    """
    weights = ConfidenceWeights.from_array(weights_arr)
    weights.normalize_weights()

    # 仓位约束
    if weights.position_lower < 0.2 or weights.position_lower > 0.8:
        return 1e6
    if weights.position_scale < 0.3 or weights.position_scale > 1.5:
        return 1e6
    if weights.position_lower + weights.position_scale > 2.0:
        return 1e6

    # 计算物理置信度
    confidence = (
        weights.w_eta * confidence_components["trend_score"]
        + weights.w_reversal * confidence_components["reversal_score"]
        + weights.w_support * confidence_components["support_score"]
        + weights.w_kinetic * confidence_components["kinetic_score"]
    )
    confidence = np.clip(confidence, 0, 1)

    # 调整仓位
    multiplier = weights.position_lower + weights.position_scale * confidence
    adjusted_position = np.clip(base_position * multiplier, 0, 1)

    # Walk-Forward验证
    test_sharpes = []
    for tr_s, tr_e, te_s, te_e in splits:
        pos_test = adjusted_position[te_s:te_e]
        ret_test = daily_returns[te_s:te_e]
        if len(pos_test) < 30:
            continue
        # 策略收益
        pos_changes = np.abs(np.diff(pos_test, prepend=pos_test[0]))
        strat_ret = pos_test * ret_test - pos_changes * 0.001
        if np.std(strat_ret) > 0:
            sharpe = np.mean(strat_ret) / np.std(strat_ret) * np.sqrt(365)
            test_sharpes.append(sharpe)

    if not test_sharpes:
        return 1e6

    # 返回负的夏普比（最小化目标）
    return -np.mean(test_sharpes)


def grid_search_optimize(base_position, confidence_components, daily_returns, splits):
    """网格搜索参数寻优"""
    print("\n【参数寻优 - 网格搜索】")

    # 参数网格（精简版：每个维度2-3个值，共~100-200组合）
    w_eta_grid = [0.20, 0.35]
    w_reversal_grid = [0.20, 0.35]
    w_support_grid = [0.20, 0.35]
    w_kinetic_grid = [0.10, 0.20]
    pos_lower_grid = [0.4, 0.5, 0.6]
    pos_scale_grid = [0.6, 0.8, 1.0]

    total_combos = (len(w_eta_grid) * len(w_reversal_grid) * len(w_support_grid)
                    * len(w_kinetic_grid) * len(pos_lower_grid) * len(pos_scale_grid))
    print("  网格组合数: {}".format(total_combos))

    best_score = 1e6
    best_weights = None
    results = []

    t0 = time.time()
    count = 0
    for w_eta in w_eta_grid:
        for w_rev in w_reversal_grid:
            for w_sup in w_support_grid:
                for w_kin in w_kinetic_grid:
                    for p_low in pos_lower_grid:
                        for p_scale in pos_scale_grid:
                            arr = np.array([w_eta, w_rev, w_sup, w_kin, p_low, p_scale])
                            score = objective_function(
                                arr, base_position, confidence_components, daily_returns, splits
                            )
                            results.append({
                                "w_eta": w_eta, "w_reversal": w_rev,
                                "w_support": w_sup, "w_kinetic": w_kin,
                                "pos_lower": p_low, "pos_scale": p_scale,
                                "neg_sharpe": score,
                                "sharpe": -score if score < 1e5 else 0,
                            })
                            if score < best_score:
                                best_score = score
                                best_weights = arr
                            count += 1
                            if count % 200 == 0:
                                print("  进度: {}/{} ({:.1f}%) 当前最优夏普: {:.3f}  {:.0f}s".format(
                                    count, total_combos, count / total_combos * 100,
                                    -best_score if best_score < 1e5 else 0,
                                    time.time() - t0))

    print("  网格搜索完成: {:.1f}s".format(time.time() - t0))
    print("  最优夏普比: {:.4f}".format(-best_score if best_score < 1e5 else 0))

    # 排序结果
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    print("\n  Top 10 参数组合:")
    print("  {:>6s} {:>6s} {:>6s} {:>6s} {:>8s} {:>8s} {:>8s}".format(
        "w_eta", "w_rev", "w_sup", "w_kin", "p_low", "p_scale", "sharpe"))
    for r in results[:10]:
        print("  {:>6.2f} {:>6.2f} {:>6.2f} {:>6.2f} {:>8.2f} {:>8.2f} {:>8.4f}".format(
            r["w_eta"], r["w_reversal"], r["w_support"], r["w_kinetic"],
            r["pos_lower"], r["pos_scale"], r["sharpe"]))

    return best_weights, results


def main():
    print("=" * 80)
    print("  PITD 物理置信度评估器 — 参数寻优与回测验证")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    n = len(prices)
    daily_returns = np.zeros(n)
    daily_returns[1:] = (closes[1:] - closes[:-1]) / closes[:-1]
    print("\n  BTC日线: {}天, {} ~ {}".format(
        n, prices.index[0].date(), prices.index[-1].date()))

    # 1. 构建V5.5基线
    print("\n【1. 构建V5.5 ML基线】")
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)
    print("  V5.5基线: {}维".format(len(v55_names)))

    # 2. Walk-Forward ML预测
    print("\n【2. Walk-Forward ML预测】")
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    t0 = time.time()
    top_preds, top_auc, splits = walk_forward_ml_predictions(v55_base, top_exit_labels, v55_names)
    dip_preds, dip_auc, _ = walk_forward_ml_predictions(v55_base, dip_buy_labels, v55_names)
    print("  TOP_EXIT AUC: {:.4f}".format(top_auc))
    print("  DIP_BUY AUC:  {:.4f}".format(dip_auc))
    print("  Walk-Forward分折数: {}".format(len(splits)))
    print("  预测耗时: {:.1f}s".format(time.time() - t0))

    # 3. 计算基础仓位
    print("\n【3. 基础仓位计算】")
    base_position = compute_base_position(top_preds, dip_preds)
    print("  基础仓位: mean={:.3f} std={:.3f} min={:.3f} max={:.3f}".format(
        base_position.mean(), base_position.std(), base_position.min(), base_position.max()))
    print("  仓位分布:")
    for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
        print("    {}%分位: {:.3f}".format(int(q * 100), np.percentile(base_position, q * 100)))

    # 4. 计算物理置信度分量
    print("\n【4. 物理置信度分量计算】")
    t0 = time.time()
    scorer = PhysicsConfidenceScorer()
    # 预计算物理特征
    physics_feats = scorer._compute_physics_features(prices)
    # ML信号用于阻力一致性
    ml_signal = (dip_preds - top_preds)
    confidence, components = scorer.score_signals(prices, ml_signal, precomputed_features=physics_feats)
    print("  计算耗时: {:.1f}s".format(time.time() - t0))
    print("  物理置信度: mean={:.3f} std={:.3f}".format(confidence.mean(), confidence.std()))
    print("  分量评分:")
    for comp in ["trend_score", "reversal_score", "support_score", "kinetic_score"]:
        v = components[comp]
        print("    {:<20s}: mean={:.3f} std={:.3f}".format(comp, v.mean(), v.std()))

    # 5. 基线回测（原始仓位）
    print("\n【5. 基线回测（原始仓位）】")
    # 只在Walk-Forward有效预测区域回测
    valid_start = splits[0][2] if splits else 730
    base_metrics = backtest_position(base_position[valid_start:], daily_returns[valid_start:])
    print("  原始仓位:")
    print("    年化收益: {:.2%}".format(base_metrics["annual_return"]))
    print("    夏普比:   {:.4f}".format(base_metrics["sharpe"]))
    print("    最大回撤: {:.2%}".format(base_metrics["max_drawdown"]))
    print("    Calmar比: {:.4f}".format(base_metrics["calmar"]))
    print("    胜率:     {:.2%}".format(base_metrics["win_rate"]))
    print("    平均仓位: {:.3f}".format(base_metrics["avg_position"]))

    # 6. 默认权重对比
    print("\n【6. 默认权重对比】")
    default_weights = ConfidenceWeights()
    default_scorer = PhysicsConfidenceScorer(default_weights)
    default_conf, _ = default_scorer.score_signals(prices, ml_signal, precomputed_features=physics_feats)
    default_pos = default_scorer.adjust_position(base_position, default_conf)
    default_metrics = backtest_position(default_pos[valid_start:], daily_returns[valid_start:])
    print("  默认权重物理调节仓位:")
    print("    年化收益: {:.2%} (Δ{:+.2%})".format(
        default_metrics["annual_return"], default_metrics["annual_return"] - base_metrics["annual_return"]))
    print("    夏普比:   {:.4f} (Δ{:+.4f})".format(
        default_metrics["sharpe"], default_metrics["sharpe"] - base_metrics["sharpe"]))
    print("    最大回撤: {:.2%} (Δ{:+.2%})".format(
        default_metrics["max_drawdown"], default_metrics["max_drawdown"] - base_metrics["max_drawdown"]))
    print("    Calmar比: {:.4f} (Δ{:+.4f})".format(
        default_metrics["calmar"], default_metrics["calmar"] - base_metrics["calmar"]))
    print("    平均仓位: {:.3f}".format(default_metrics["avg_position"]))

    # 7. 参数寻优
    print("\n【7. 参数寻优】")
    best_arr, grid_results = grid_search_optimize(
        base_position, components, daily_returns, splits
    )

    if best_arr is not None:
        best_weights = ConfidenceWeights.from_array(best_arr)
        best_weights.normalize_weights()
        print("\n  最优参数:")
        print("    w_eta={}, w_reversal={}, w_support={}, w_kinetic={}".format(
            best_weights.w_eta, best_weights.w_reversal,
            best_weights.w_support, best_weights.w_kinetic))
        print("    position_lower={}, position_scale={}".format(
            best_weights.position_lower, best_weights.position_scale))

        # 8. 最优参数回测
        print("\n【8. 最优参数回测】")
        best_scorer = PhysicsConfidenceScorer(best_weights)
        best_conf, _ = best_scorer.score_signals(prices, ml_signal, precomputed_features=physics_feats)
        best_pos = best_scorer.adjust_position(base_position, best_conf)
        best_metrics = backtest_position(best_pos[valid_start:], daily_returns[valid_start:])

        print("\n  {:<20s}  {:>12s}  {:>12s}  {:>12s}".format(
            "指标", "原始仓位", "默认权重", "最优权重"))
        print("  " + "-" * 65)
        for metric, label in [
            ("annual_return", "年化收益"),
            ("sharpe", "夏普比"),
            ("max_drawdown", "最大回撤"),
            ("calmar", "Calmar比"),
            ("win_rate", "胜率"),
            ("avg_position", "平均仓位"),
        ]:
            base_v = base_metrics[metric]
            default_v = default_metrics[metric]
            best_v = best_metrics[metric]
            if metric in ["annual_return", "max_drawdown", "win_rate"]:
                print("  {:<20s}  {:>12.2%}  {:>12.2%}  {:>12.2%} (Δ{:+.2%})".format(
                    label, base_v, default_v, best_v, best_v - base_v))
            else:
                print("  {:<20s}  {:>12.4f}  {:>12.4f}  {:>12.4f} (Δ{:+.4f})".format(
                    label, base_v, default_v, best_v, best_v - base_v))

        # 9. 不同市场状态下的表现
        print("\n【9. 不同趋势状态下的表现】")
        eta = components["eta"]
        for regime, (lo, hi) in [("弱趋势", (0, 0.10)), ("正常", (0.10, 0.20)), ("强趋势", (0.20, 1.0))]:
            mask = (eta[valid_start:] >= lo) & (eta[valid_start:] < hi)
            if mask.sum() < 10:
                continue
            base_ret = base_position[valid_start:][mask] * daily_returns[valid_start:][mask]
            best_ret = best_pos[valid_start:][mask] * daily_returns[valid_start:][mask]
            print("  {:<10s} (样本={:>4d}): 原始平均收益={:+.3%} 最优平均收益={:+.3%} 差值={:+.3%}".format(
                regime, mask.sum(), base_ret.mean(), best_ret.mean(),
                best_ret.mean() - base_ret.mean()))

        # 9.5 条件策略测试：仅弱趋势状态启用物理调节
        print("\n【9.5 条件策略测试：仅弱趋势状态启用物理调节】")

        # 条件策略：弱趋势时用物理调节，其他状态保持原始仓位
        conditional_pos = base_position.copy()
        weak_mask = eta < 0.10
        conditional_pos[weak_mask] = best_pos[weak_mask]

        conditional_metrics = backtest_position(conditional_pos[valid_start:], daily_returns[valid_start:])
        print("  条件策略（弱趋势启用物理调节）:")
        print("    年化收益: {:.2%} (Δ{:+.2%})".format(
            conditional_metrics["annual_return"],
            conditional_metrics["annual_return"] - base_metrics["annual_return"]))
        print("    夏普比:   {:.4f} (Δ{:+.4f})".format(
            conditional_metrics["sharpe"],
            conditional_metrics["sharpe"] - base_metrics["sharpe"]))
        print("    最大回撤: {:.2%} (Δ{:+.2%})".format(
            conditional_metrics["max_drawdown"],
            conditional_metrics["max_drawdown"] - base_metrics["max_drawdown"]))
        print("    Calmar比: {:.4f} (Δ{:+.4f})".format(
            conditional_metrics["calmar"],
            conditional_metrics["calmar"] - base_metrics["calmar"]))

        # 条件策略2：仅强趋势状态启用物理调节
        strong_pos = base_position.copy()
        strong_mask = eta >= 0.20
        strong_pos[strong_mask] = best_pos[strong_mask]
        strong_metrics = backtest_position(strong_pos[valid_start:], daily_returns[valid_start:])
        print("\n  条件策略2（强趋势启用物理调节）:")
        print("    年化收益: {:.2%} (Δ{:+.2%})".format(
            strong_metrics["annual_return"],
            strong_metrics["annual_return"] - base_metrics["annual_return"]))
        print("    夏普比:   {:.4f} (Δ{:+.4f})".format(
            strong_metrics["sharpe"],
            strong_metrics["sharpe"] - base_metrics["sharpe"]))

        # 条件策略3：反转预警时降低仓位
        reversal_warning = (components["reversal_score"] < 0.5)
        reversal_pos = base_position.copy()
        reversal_pos[reversal_warning] *= 0.5  # 反转预警时仓位减半
        reversal_metrics = backtest_position(reversal_pos[valid_start:], daily_returns[valid_start:])
        print("\n  条件策略3（反转预警时仓位减半）:")
        print("    年化收益: {:.2%} (Δ{:+.2%})".format(
            reversal_metrics["annual_return"],
            reversal_metrics["annual_return"] - base_metrics["annual_return"]))
        print("    夏普比:   {:.4f} (Δ{:+.4f})".format(
            reversal_metrics["sharpe"],
            reversal_metrics["sharpe"] - base_metrics["sharpe"]))
        print("    最大回撤: {:.2%} (Δ{:+.2%})".format(
            reversal_metrics["max_drawdown"],
            reversal_metrics["max_drawdown"] - base_metrics["max_drawdown"]))

        # 10. 总结
        print("\n" + "=" * 80)
        print("  【物理置信度评估器验证总结】")
        print("=" * 80)

        d_sharpe = best_metrics["sharpe"] - base_metrics["sharpe"]
        d_return = best_metrics["annual_return"] - base_metrics["annual_return"]
        d_drawdown = best_metrics["max_drawdown"] - base_metrics["max_drawdown"]
        d_calmar = best_metrics["calmar"] - base_metrics["calmar"]

        print("\n  最优权重 vs 原始仓位:")
        print("    夏普比:   {:+.4f} {}".format(d_sharpe, "✅" if d_sharpe > 0 else "❌"))
        print("    年化收益: {:+.2%} {}".format(d_return, "✅" if d_return > 0 else "❌"))
        print("    最大回撤: {:+.2%} {} (负值=回撤减小=改善)".format(
            d_drawdown, "✅" if d_drawdown > 0 else "❌"))
        print("    Calmar比: {:+.4f} {}".format(d_calmar, "✅" if d_calmar > 0 else "❌"))

        if d_sharpe > 0.05 and d_calmar > 0:
            decision = "✅ 采纳：物理置信度显著提升风险调整后收益"
        elif d_sharpe > 0 or d_calmar > 0:
            decision = "🟡 部分采纳：有改善但幅度有限"
        else:
            decision = "❌ 回退：物理置信度未改善"

        print("\n  决策: {}".format(decision))

        # 保存结果
        output = {
            "analysis_date": str(pd.Timestamp.now()),
            "phase": "Physics Confidence Scorer",
            "v55_baseline": {"top_auc": top_auc, "dip_auc": dip_auc},
            "base_metrics": base_metrics,
            "default_metrics": default_metrics,
            "best_weights": {
                "w_eta": best_weights.w_eta,
                "w_reversal": best_weights.w_reversal,
                "w_support": best_weights.w_support,
                "w_kinetic": best_weights.w_kinetic,
                "position_lower": best_weights.position_lower,
                "position_scale": best_weights.position_scale,
            },
            "best_metrics": best_metrics,
            "grid_top10": grid_results[:10],
            "decision": decision,
        }
        output_path = os.path.join(BASE_DIR, "ml/backtest_results/pitd_confidence_scorer_result.json")
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)
        print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
