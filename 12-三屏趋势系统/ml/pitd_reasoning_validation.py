"""PITD 物理推理引擎验证

验证物理推理引擎作为独立交易信号的有效性：
1. 信号统计特征（分布、状态转换）
2. 信号与未来收益相关性（预测力）
3. 信号准确率（方向预测）
4. 与V5.5 ML预测对比（独立价值与互补性）
5. 信号分层收益分析（分位数组合）
6. 反转预警准确率
7. 不同市场状态下的表现

输出: 物理推理引擎评估报告
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, roc_curve
from scipy import stats

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer
from ml.pitd_reasoning_engine import PhysicsReasoningEngine


def load_btc_data() -> pd.DataFrame:
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def walk_forward_validation(features, labels, feature_names,
                             n_splits=12, train_days=730, test_days=180, step_days=180):
    n = len(features)
    train_aucs, test_aucs = [], []
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

    all_preds = np.zeros(n)
    pred_count = np.zeros(n)

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
        if len(set(y_test)) > 1:
            test_aucs.append(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))
        if len(set(y_train)) > 1:
            train_aucs.append(roc_auc_score(y_train, model.predict_proba(X_train)[:, 1]))
        preds = model.predict_proba(X_test)[:, 1]
        all_preds[te_s:te_e] += preds
        pred_count[te_s:te_e] += 1

    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    # 合并预测
    valid = pred_count > 0
    all_preds[~valid] = 0.5
    all_preds[valid] /= pred_count[valid]
    return avg_test, avg_train, float(decay), all_preds


def main():
    print("=" * 80)
    print("  PITD 物理推理引擎验证")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    n = len(prices)
    print("\n  BTC日线: {}天, {} ~ {}".format(
        n, prices.index[0].date(), prices.index[-1].date()))

    # 1. 计算物理信号
    print("\n【1. 物理信号计算】")
    t0 = time.time()
    engine = PhysicsReasoningEngine()
    signals = engine.compute_signals(prices)
    print("  计算耗时: {:.2f}s".format(time.time() - t0))
    print("  信号样本:")
    print(signals[["physics_signal", "physics_confidence", "physics_regime",
                    "trend_signal", "reversal_signal", "support_signal", "momentum_signal"]].tail(10))

    # 2. 信号统计特征
    print("\n【2. 信号统计特征】")
    sig = signals["physics_signal"]
    conf = signals["physics_confidence"]
    print("  综合信号: mean={:+.4f} std={:.4f} min={:+.4f} max={:+.4f}".format(
        sig.mean(), sig.std(), sig.min(), sig.max()))
    print("  置信度:   mean={:.4f} std={:.4f} min={:.4f} max={:.4f}".format(
        conf.mean(), conf.std(), conf.min(), conf.max()))
    print("\n  趋势状态分布:")
    regime_counts = signals["physics_regime"].value_counts()
    for regime, count in regime_counts.items():
        print("    {:<15s}  {:>5d} ({:.1%})".format(regime, count, count / n))
    print("\n  反转预警: {}次 ({:.1%})".format(signals["reversal_warning"].sum(),
                                              signals["reversal_warning"].mean()))
    print("  强趋势:   {}次 ({:.1%})".format(signals["strong_trend"].sum(),
                                             signals["strong_trend"].mean()))

    # 3. 信号与未来收益相关性
    print("\n【3. 信号与未来收益相关性】")
    future_returns = {}
    for days in [1, 3, 5, 10, 20, 40, 60]:
        fr = np.zeros(n)
        for i in range(n - days):
            fr[i] = (closes[i + days] - closes[i]) / closes[i]
        future_returns[days] = fr

    print("  {:<20s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}".format(
        "信号", "1日", "3日", "5日", "10日", "20日", "40日", "60日"))
    print("  " + "-" * 85)
    for col in ["physics_signal", "trend_signal", "reversal_signal",
                "support_signal", "momentum_signal"]:
        cors = []
        for days in [1, 3, 5, 10, 20, 40, 60]:
            r, p = stats.spearmanr(signals[col].values, future_returns[days])
            cors.append("{:+.3f}".format(r))
        print("  {:<20s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}".format(
            col, *cors))

    # 4. 信号方向准确率
    print("\n【4. 信号方向预测准确率】")
    print("  {:<20s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}".format(
        "信号", "5日", "10日", "20日", "40日", "60日", "样本"))
    print("  " + "-" * 70)

    for col in ["physics_signal", "trend_signal", "reversal_signal",
                "support_signal", "momentum_signal"]:
        sig_vals = signals[col].values
        results = []
        for days in [5, 10, 20, 40, 60]:
            future_dir = np.sign(future_returns[days])
            valid = (sig_vals != 0) & (future_dir != 0)
            if valid.sum() > 0:
                acc = (np.sign(sig_vals[valid]) == future_dir[valid]).mean()
                results.append("{:.1%}".format(acc))
            else:
                results.append("  N/A")
        sample = ((sig_vals != 0).sum())
        print("  {:<20s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8s}  {:>8d}".format(
            col, *results, sample))

    # 5. 分层收益分析（分位数组合）
    print("\n【5. 分层收益分析（20日持有）】")
    sig_vals = signals["physics_signal"].values
    fr_20 = future_returns[20]

    # 按信号分5档
    valid = (sig_vals != 0) & (np.abs(fr_20) < 0.5)  # 排除极端值
    if valid.sum() > 100:
        sig_valid = sig_vals[valid]
        fr_valid = fr_20[valid]
        quantiles = np.percentile(sig_valid, [0, 20, 40, 60, 80, 100])
        print("  {:<15s}  {:>10s}  {:>10s}  {:>10s}  {:>10s}".format(
            "分档", "信号范围", "平均收益", "胜率", "样本数"))
        for i in range(5):
            lo = quantiles[i]
            hi = quantiles[i + 1]
            mask = (sig_valid >= lo) & (sig_valid <= hi if i == 4 else sig_valid < hi)
            if mask.sum() > 0:
                mean_ret = fr_valid[mask].mean()
                win_rate = (fr_valid[mask] > 0).mean()
                print("  档{}({:.0%})      [{:+.3f}, {:+.3f}]  {:+.2%}   {:>5.1%}   {:>5d}".format(
                    i + 1, (i + 1) / 5, lo, hi, mean_ret, win_rate, mask.sum()))

    # 6. 反转预警准确率
    print("\n【6. 反转预警准确率】")
    warnings = signals["reversal_warning"].values
    if warnings.sum() > 0:
        print("  反转预警触发: {}次 ({:.1%})".format(warnings.sum(), warnings.mean()))
        print("  预警后未来收益:")
        for days in [3, 5, 10, 20]:
            future_dir = np.sign(future_returns[days])
            valid = (warnings) & (future_dir != 0)
            if valid.sum() > 0:
                # 预警时的速度方向
                v_D_at_warning = signals["velocity_D"].values
                # 反转预警应预测价格反转（与当前速度反方向）
                predicted_dir = -np.sign(v_D_at_warning)
                actual_dir = future_dir
                reversal_acc = (predicted_dir[valid] == actual_dir[valid]).mean()
                # 预警后平均收益
                mean_ret = future_returns[days][valid].mean()
                print("    {}日: 反转准确率={:.1%}, 平均收益={:+.2%}, 样本={}".format(
                    days, reversal_acc, mean_ret, valid.sum()))

    # 7. 不同市场状态下的表现
    print("\n【7. 不同趋势状态下的信号表现】")
    for regime in ["strong_trend", "normal", "weak_trend"]:
        mask = (signals["physics_regime"] == regime).values
        if mask.sum() < 10:
            continue
        sig_r = sig_vals[mask]
        fr_r = fr_20[mask]
        valid = np.abs(fr_r) < 0.5
        if valid.sum() > 0:
            corr, _ = stats.spearmanr(sig_r[valid], fr_r[valid])
            acc = (np.sign(sig_r[valid]) == np.sign(fr_r[valid])).mean() if (sig_r[valid] != 0).any() else 0
            mean_ret = fr_r[valid].mean()
            print("  {:<15s}: 样本={:>5d}, 相关性={:+.3f}, 方向准确率={:.1%}, 平均收益={:+.2%}".format(
                regime, mask.sum(), corr, acc, mean_ret))

    # 8. 与V5.5 ML预测对比
    print("\n【8. 与V5.5 ML预测对比】")

    # 构建V5.5基线
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)

    # 标签
    top_exit_labels = np.zeros(n)
    for i in range(n - 20):
        if (closes[i] - closes[i + 20]) / closes[i] > 0.20:
            top_exit_labels[i] = 1
    dip_buy_labels = np.zeros(n)
    for i in range(n - 20):
        if (closes[i + 20] - closes[i]) / closes[i] > 0.15:
            dip_buy_labels[i] = 1

    # V5.5 ML预测
    print("\n  8.1 V5.5 ML预测")
    ml_top, ml_top_tr, ml_top_dec, ml_top_preds = walk_forward_validation(
        v55_base, top_exit_labels, v55_names)
    ml_dip, ml_dip_tr, ml_dip_dec, ml_dip_preds = walk_forward_validation(
        v55_base, dip_buy_labels, v55_names)
    print("    TOP_EXIT: AUC={:.4f} (decay={:.1%})".format(ml_top, ml_top_dec))
    print("    DIP_BUY:  AUC={:.4f} (decay={:.1%})".format(ml_dip, ml_dip_dec))

    # 物理信号作为分类器的AUC
    print("\n  8.2 物理信号作为分类器的AUC")
    # 物理信号预测TOP_EXIT: 信号负(看空) → 预测顶部
    # 物理信号预测DIP_BUY: 信号正(看多) → 预测抄底
    phys_sig_vals = signals["physics_signal"].values
    # TOP_EXIT: 信号越负，下跌概率越高
    phys_top_pred = 1 - (phys_sig_vals + 1) / 2  # 反转+归一化
    # DIP_BUY: 信号越正，上涨概率越高
    phys_dip_pred = (phys_sig_vals + 1) / 2

    # 计算AUC（在V5.5相同的测试集上）
    valid_mask = (top_exit_labels >= 0)  # 全部数据
    # 使用与V5.5相同的分折计算AUC
    def compute_signal_auc(pred_vals, labels, n_splits=12, test_days=180, step_days=180):
        n = len(labels)
        aucs = []
        test_end = n
        splits = []
        for _ in range(n_splits):
            test_start = test_end - test_days
            train_end = test_start
            train_start = train_end - 730
            if train_start < 0 or test_start < 0:
                break
            splits.append((train_start, train_end, test_start, test_end))
            test_end -= step_days
        splits = list(reversed(splits))
        for _, _, te_s, te_e in splits:
            y_test = labels[te_s:te_e]
            p_test = pred_vals[te_s:te_e]
            if len(set(y_test)) > 1:
                aucs.append(roc_auc_score(y_test, p_test))
        return float(np.mean(aucs)) if aucs else 0.0

    phys_top_auc = compute_signal_auc(phys_top_pred, top_exit_labels)
    phys_dip_auc = compute_signal_auc(phys_dip_pred, dip_buy_labels)
    print("    TOP_EXIT: AUC={:.4f} (物理信号)".format(phys_top_auc))
    print("    DIP_BUY:  AUC={:.4f} (物理信号)".format(phys_dip_auc))
    print("    对比: V5.5 TOP={:.4f}, DIP={:.4f}".format(ml_top, ml_dip))

    # 9. 互补性分析
    print("\n  8.3 互补性分析（ML+物理融合）")
    # 简单加权融合
    for alpha in [0.3, 0.5, 0.7]:
        fused_top = alpha * ml_top_preds + (1 - alpha) * phys_top_pred
        fused_dip = alpha * ml_dip_preds + (1 - alpha) * phys_dip_pred
        fused_top_auc = compute_signal_auc(fused_top, top_exit_labels)
        fused_dip_auc = compute_signal_auc(fused_dip, dip_buy_labels)
        d_top = fused_top_auc - ml_top
        d_dip = fused_dip_auc - ml_dip
        print("    α={:.1f} (ML权重): TOP={:.4f} (Δ{:+.4f}), DIP={:.4f} (Δ{:+.4f})".format(
            alpha, fused_top_auc, d_top, fused_dip_auc, d_dip))

    # 10. 物理信号作为后置过滤器
    print("\n  8.4 物理信号作为ML后置过滤器")
    # 策略：当物理信号与ML预测冲突时，降低置信度
    # 简化评估：在ML预测的基础上，用物理信号过滤
    for conf_thresh in [0.3, 0.5, 0.7]:
        # 物理置信度高时增强ML预测，低时减弱
        phys_conf = signals["physics_confidence"].values
        filtered_top = ml_top_preds * (0.5 + phys_conf)  # 置信度0.5~1.5倍调节
        filtered_dip = ml_dip_preds * (0.5 + phys_conf)
        filtered_top_auc = compute_signal_auc(filtered_top, top_exit_labels)
        filtered_dip_auc = compute_signal_auc(filtered_dip, dip_buy_labels)
        d_top = filtered_top_auc - ml_top
        d_dip = filtered_dip_auc - ml_dip
        print("    conf调节(0.5+c): TOP={:.4f} (Δ{:+.4f}), DIP={:.4f} (Δ{:+.4f})".format(
            filtered_top_auc, d_top, filtered_dip_auc, d_dip))

    # 11. 总结
    print("\n" + "=" * 80)
    print("  【物理推理引擎验证总结】")
    print("=" * 80)

    # 综合评估
    best_corr_days = None
    best_corr = 0
    for days in [5, 10, 20, 40, 60]:
        r, _ = stats.spearmanr(sig_vals, future_returns[days])
        if abs(r) > abs(best_corr):
            best_corr = r
            best_corr_days = days

    direction_acc_20 = 0
    valid = (sig_vals != 0) & (np.sign(future_returns[20]) != 0)
    if valid.sum() > 0:
        direction_acc_20 = (np.sign(sig_vals[valid]) == np.sign(future_returns[20])[valid]).mean()

    print("\n  1. 信号预测力:")
    print("     最佳相关性: {}日 ρ={:+.3f}".format(best_corr_days, best_corr))
    print("     20日方向准确率: {:.1%}".format(direction_acc_20))
    print("\n  2. ML对比:")
    print("     V5.5 ML:  TOP={:.4f}, DIP={:.4f}".format(ml_top, ml_dip))
    print("     物理信号:  TOP={:.4f}, DIP={:.4f}".format(phys_top_auc, phys_dip_auc))
    print("\n  3. 反转预警:")
    if warnings.sum() > 0:
        valid = (warnings) & (np.sign(future_returns[5]) != 0)
        if valid.sum() > 0:
            v_D_warn = signals["velocity_D"].values
            reversal_acc_5 = (-np.sign(v_D_warn[valid]) == np.sign(future_returns[5])[valid]).mean()
            print("     5日反转准确率: {:.1%} (样本={})".format(reversal_acc_5, valid.sum()))

    print("\n  4. 评估:")
    if best_corr > 0.1 or direction_acc_20 > 0.52:
        print("     ✅ 物理信号有预测力，可作为独立信号或ML补充")
    elif best_corr > 0.05 or direction_acc_20 > 0.50:
        print("     🟡 物理信号有微弱预测力，建议作为辅助过滤器")
    else:
        print("     ❌ 物理信号预测力不足")

    # 保存结果
    output = {
        "analysis_date": str(pd.Timestamp.now()),
        "signal_stats": {
            "signal_mean": float(sig.mean()),
            "signal_std": float(sig.std()),
            "confidence_mean": float(conf.mean()),
            "reversal_warning_rate": float(signals["reversal_warning"].mean()),
            "strong_trend_rate": float(signals["strong_trend"].mean()),
        },
        "correlations": {
            "{}d".format(d): float(stats.spearmanr(sig_vals, future_returns[d])[0])
            for d in [1, 3, 5, 10, 20, 40, 60]
        },
        "direction_accuracy_20d": float(direction_acc_20),
        "best_correlation": {"days": best_corr_days, "value": float(best_corr)},
        "ml_comparison": {
            "v55_top": ml_top, "v55_dip": ml_dip,
            "physics_top": phys_top_auc, "physics_dip": phys_dip_auc,
        },
        "regime_distribution": {k: int(v) for k, v in regime_counts.items()},
    }
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/pitd_reasoning_engine_result.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
