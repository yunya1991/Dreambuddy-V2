#!/usr/bin/env python3
"""
宏观特征级选择 v2 — 基于特征重要性的精确选择

修正 v1 的核心问题:
  1. 维度级开关太粗 → 改为 24 个特征级独立开关
  2. sharpe 占 97% 权重 → 改为多指标均衡评分
  3. 只用 3 币种 → 改为 5 币种代表性子集
  4. hold-out 0-3 笔交易 → 改为 walk-forward 多折验证
  5. Bayesian 搜索 64 种组合浪费 → 改为按重要性排名选 top-K

流程:
  Phase 1: 用 5 币种全特征回测，获取 24 个宏观特征的 LightGBM 重要性排名
  Phase 2: 测试 top-K 子集 (K=0,3,5,8,12,24)，用 5 币种 3 折快速回测
  Phase 3: 最优 K 的特征列表保存，供 9 币种 5 折完整验证
"""
import sys
import os
import json
import time
import logging
import importlib

import numpy as np
import pandas as pd

# 设置路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, PROJECT_ROOT)

# 避免 inspect.py 冲突
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================

# Phase 1: 重要性分析用的币种（代表性子集：大盘+中小盘）
IMPORTANCE_COINS = ["BTC", "ETH", "SOL", "UNI", "BNB"]

# Phase 2: 子集测试用的币种（与 Phase 1 一致，保证一致性）
TEST_COINS = IMPORTANCE_COINS

# 回测参数（与 run_baseline_comparison.py 对齐）
TIMEFRAME = "1H"
MAX_BARS = 3000  # 快速评估用 3000 bars
N_FOLDS_FAST = 3  # Phase 2 快速验证用 3 折
CONF_THRESHOLD = 0.40
TP_ATR = 3.0
SL_ATR = 2.0
MAX_HOLD_BARS = 60
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.001

# 待测试的 top-K 值
TOP_K_CANDIDATES = [0, 3, 5, 8, 12, 24]

# 数据缓存
_KLINE_CACHE = {}
_REF_DF_CACHE = None


def load_klines(symbol, timeframe="1H", max_bars=3000):
    if symbol not in _KLINE_CACHE:
        from scripts.memory_l4.bcrm2.data_fetcher import get_klines
        df = get_klines(symbol, timeframe, max_bars=max_bars)
        _KLINE_CACHE[symbol] = df
    return _KLINE_CACHE[symbol]


def get_ref_df():
    global _REF_DF_CACHE
    if _REF_DF_CACHE is None:
        from scripts.memory_l4.bcrm2.data_fetcher import get_klines
        _REF_DF_CACHE = get_klines("BTC", "1H", max_bars=3200)
    return _REF_DF_CACHE


# ============================================================
# Phase 1: 特征重要性分析
# ============================================================

def analyze_feature_importance():
    """用 5 币种全特征构建，训练 LightGBM，获取宏观特征重要性排名"""
    print("\n" + "=" * 70)
    print("  Phase 1: 宏观特征重要性分析")
    print("=" * 70)

    from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
    # 触发所有模块注册
    import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
    import scripts.memory_l4.bcrm2.classic_experience_features  # noqa: F401
    import scripts.memory_l4.bcrm2.fibonacci_features  # noqa: F401
    import scripts.memory_l4.bcrm2.pivot_point_features  # noqa: F401
    import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa: F401
    import scripts.memory_l4.bcrm2.wdh_features  # noqa: F401
    import scripts.memory_l4.bcrm2.cycle_features  # noqa: F401
    import scripts.memory_l4.bcrm2.market_cap  # noqa: F401
    import scripts.memory_l4.bcrm2.cross_asset_features  # noqa: F401
    import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa: F401
    import scripts.memory_l4.bcrm2.macro_features  # noqa: F401

    from scripts.memory_l4.bcrm2.macro_features import MacroFeatures
    from scripts.memory_l4.bcrm2.triple_barrier_labeler import DialecticalLabeler

    all_macro_imps = {}  # {feature_name: [importance across coins]}
    ref_df = get_ref_df()

    for symbol in IMPORTANCE_COINS:
        print(f"\n  [{symbol}] 构建特征 + 训练 LightGBM...")
        df = load_klines(symbol)
        if df is None or len(df) < 800:
            print(f"    跳过: 数据不足 ({len(df) if df is not None else 0} bars)")
            continue

        # 获取宏观数据
        try:
            from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher
            fetcher = MacroDataFetcher()
            macro_df = fetcher.fetch_all(symbol, df.index, live=False, verbose=False)
        except Exception as e:
            print(f"    宏观数据获取失败: {e}")
            macro_df = None

        # 构建全部特征
        enabled = ["bagua", "classic_exp", "fibonacci", "pivot_point",
                   "rsi_sentiment", "wdh"]
        if ref_df is not None:
            enabled.append("cross_asset")
        if macro_df is not None and not macro_df.empty:
            enabled.append("macro")

        features, _ = FeatureRegistry.compute_all(
            df=df, ref_df=ref_df, macro_df=macro_df,
            symbol=symbol, enabled=enabled, verbose=False,
        )

        # 生成标签
        labeler = DialecticalLabeler(
            tp_atr=TP_ATR, sl_atr=SL_ATR,
            max_bars=MAX_HOLD_BARS, atr_period=14,
        )
        labels_df = labeler.label(df)
        y_series = labels_df["label"] if isinstance(labels_df, pd.DataFrame) else labels_df

        # 对齐：替换 inf → NaN，用 LightGBM 原生 NaN 支持
        valid_mask = y_series.notna()
        X = features.loc[valid_mask].replace([np.inf, -np.inf], np.nan)
        y = y_series[valid_mask].values

        # 删除全 NaN 的列（无任何有效值的特征）
        col_valid = X.notna().any()
        X = X.loc[:, col_valid]

        if len(X) < 200 or len(np.unique(y)) < 2:
            print(f"    跳过: 有效样本不足 ({len(X)})")
            continue

        # 训练 LightGBM（用 Dataset API 原生支持 NaN）
        try:
            import lightgbm as lgb
            y_mapped = y + 1  # -1,0,1 → 0,1,2
            train_data = lgb.Dataset(X, label=y_mapped, feature_name=list(X.columns))
            params = {
                "objective": "multiclass",
                "num_class": 3,
                "max_depth": 5,
                "learning_rate": 0.05,
                "subsample": 0.8,
                "colsample_bytree": 0.7,
                "verbose": -1,
            }
            model = lgb.train(params, train_data, num_boost_round=100)
            importances = dict(zip(X.columns, model.feature_importance(importance_type="split")))
        except Exception as e:
            print(f"    LightGBM 训练失败: {e}")
            continue

        # 提取宏观特征重要性
        macro_feat_names = set(MacroFeatures.ALL_FEATURES)
        macro_imps = {k: v for k, v in importances.items() if k in macro_feat_names}

        print(f"    总特征: {len(X.columns)}, 宏观特征: {len(macro_imps)}")
        for feat, imp in sorted(macro_imps.items(), key=lambda x: -x[1]):
            print(f"      {feat:<35} imp={imp:.1f}")
            all_macro_imps.setdefault(feat, []).append(imp)

    if not all_macro_imps:
        print("\n  ✗ 未获取到任何宏观特征重要性")
        return []

    # 平均跨币种的重要性
    avg_imps = {}
    for feat, imps in all_macro_imps.items():
        avg_imps[feat] = float(np.mean(imps))

    # 按重要性降序排名
    ranked = sorted(avg_imps.items(), key=lambda x: -x[1])

    print(f"\n  {'='*60}")
    print(f"  宏观特征重要性排名 (跨 {len(IMPORTANCE_COINS)} 币种平均)")
    print(f"  {'='*60}")
    print(f"  {'排名':<5} {'特征名':<35} {'平均重要性':>10} {'出现币种数':>10}")
    print(f"  {'-'*65}")
    for i, (feat, imp) in enumerate(ranked, 1):
        n_coins = len(all_macro_imps[feat])
        print(f"  {i:<5} {feat:<35} {imp:>10.1f} {n_coins:>10}")

    return ranked


# ============================================================
# Phase 2: 子集测试
# ============================================================

def build_macro_feat_config(top_k_features):
    """构建特征级开关配置

    Args:
        top_k_features: 要启用的特征名列表，空列表 = 全部关闭

    Returns:
        dict: {macro_feat_{name}: True/False}
    """
    from scripts.memory_l4.bcrm2.macro_features import MacroFeatures
    config = {}
    for feat in MacroFeatures.ALL_FEATURES:
        config[f"macro_feat_{feat}"] = feat in top_k_features
    return config


def run_backtest_with_features(symbol, df, macro_feat_config, n_folds=3):
    """用指定宏观特征开关运行回测"""
    from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester

    ref_df = get_ref_df()

    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=n_folds,
        conf_threshold=CONF_THRESHOLD,
        tp_atr=TP_ATR,
        sl_atr=SL_ATR,
        max_hold_bars=MAX_HOLD_BARS,
        fee_rate=FEE_RATE,
        slippage_rate=SLIPPAGE_RATE,
        feature_selection=True,
        macro_config=macro_feat_config,
    )

    result = bt.run(df, ref_df=ref_df, verbose=False)
    return result


def compute_score(result):
    """多指标均衡评分

    修正 v1 问题: v1 中 sharpe 占 97% 权重
    v2 改为: sharpe + win_rate + return - drawdown 均衡加权

    各指标典型范围:
      sharpe: 0-3 (backtester 计算的，相对保守)
      win_rate: 0.3-0.9
      total_return: -50% ~ +100%
      max_drawdown: 0-30%
      profit_factor: 0-5

    权重设计:
      sharpe: 1.0 (主指标，但不会主导)
      win_rate: 2.0 (0.75 → 1.5 贡献，与 sharpe 相当)
      return: 0.01 (50% → 0.5 贡献)
      drawdown: -0.05 (5% → -0.25 惩罚)
      profit_factor: 0.3 (2.0 → 0.6 贡献)
    """
    if result.total_trades == 0:
        return -10.0

    sharpe = result.sharpe_ratio
    win_rate = result.overall_win_rate
    total_ret = result.total_return
    max_dd = result.max_drawdown
    pf = min(result.profit_factor, 5.0)  # cap at 5

    score = (
        1.0 * sharpe
        + 2.0 * win_rate
        + 0.01 * total_ret
        - 0.05 * max_dd
        + 0.3 * pf
    )
    return score


def test_top_k_subsets(ranked_features):
    """测试不同 top-K 子集的性能"""
    print("\n" + "=" * 70)
    print("  Phase 2: Top-K 子集测试")
    print("=" * 70)

    results_by_k = {}

    for k in TOP_K_CANDIDATES:
        if k == 0:
            subset = []
            label = "K=0 (无宏观特征, baseline-v1 等效)"
        elif k >= len(ranked_features):
            subset = [f for f, _ in ranked_features]
            label = f"K={k} (全特征, {len(subset)}个)"
        else:
            subset = [f for f, _ in ranked_features[:k]]
            label = f"K={k} ({','.join(subset[:3])}{'...' if k > 3 else ''})"

        print(f"\n  [测试] {label}")
        macro_config = build_macro_feat_config(subset)

        coin_results = {}
        all_scores = []

        for symbol in TEST_COINS:
            df = load_klines(symbol)
            if df is None or len(df) < 800:
                continue

            try:
                result = run_backtest_with_features(symbol, df, macro_config, n_folds=N_FOLDS_FAST)
                score = compute_score(result)

                coin_results[symbol] = {
                    "trades": result.total_trades,
                    "win_rate": round(result.overall_win_rate, 4),
                    "return_pct": round(result.total_return, 2),
                    "max_drawdown": round(result.max_drawdown, 2),
                    "sharpe": round(result.sharpe_ratio, 4),
                    "profit_factor": round(result.profit_factor, 4),
                    "score": round(score, 4),
                }
                all_scores.append(score)

                print(f"    {symbol}: 交易={result.total_trades:>3} "
                      f"胜率={result.overall_win_rate:.1%} "
                      f"收益={result.total_return:+.1f}% "
                      f"夏普={result.sharpe_ratio:.2f} "
                      f"回撤={result.max_drawdown:.2f}% "
                      f"得分={score:.3f}")
            except Exception as e:
                print(f"    {symbol}: 回测失败: {e}")
                coin_results[symbol] = None

        if all_scores:
            avg_score = float(np.mean(all_scores))
            avg_sharpe = float(np.mean([c["sharpe"] for c in coin_results.values() if c]))
            avg_wr = float(np.mean([c["win_rate"] for c in coin_results.values() if c]))
            avg_ret = float(np.mean([c["return_pct"] for c in coin_results.values() if c]))
            avg_dd = float(np.mean([c["max_drawdown"] for c in coin_results.values() if c]))

            results_by_k[k] = {
                "label": label,
                "features": subset,
                "n_features": len(subset),
                "avg_score": round(avg_score, 4),
                "avg_sharpe": round(avg_sharpe, 4),
                "avg_win_rate": round(avg_wr, 4),
                "avg_return_pct": round(avg_ret, 2),
                "avg_drawdown": round(avg_dd, 2),
                "coin_results": coin_results,
            }

            print(f"    → 平均: 得分={avg_score:.3f}, 夏普={avg_sharpe:.2f}, "
                  f"胜率={avg_wr:.1%}, 收益={avg_ret:+.1f}%, 回撤={avg_dd:.2f}%")

    # 汇总对比
    print(f"\n  {'='*80}")
    print(f"  Top-K 子集对比汇总")
    print(f"  {'='*80}")
    print(f"  {'K':<5} {'特征数':>5} {'得分':>8} {'夏普':>8} {'胜率':>8} {'收益%':>8} {'回撤%':>8}")
    print(f"  {'-'*55}")
    for k in TOP_K_CANDIDATES:
        if k in results_by_k:
            r = results_by_k[k]
            print(f"  K={k:<3} {r['n_features']:>5} {r['avg_score']:>8.3f} "
                  f"{r['avg_sharpe']:>8.2f} {r['avg_win_rate']:>8.1%} "
                  f"{r['avg_return_pct']:>+8.1f} {r['avg_drawdown']:>8.2f}")

    # 找最优 K
    best_k = max(results_by_k.keys(), key=lambda k: results_by_k[k]["avg_score"])
    baseline_k = 0
    best_score = results_by_k[best_k]["avg_score"]
    baseline_score = results_by_k.get(baseline_k, {}).get("avg_score", 0)

    print(f"\n  最优 K={best_k}, 得分={best_score:.3f}")
    print(f"  基线 K=0, 得分={baseline_score:.3f}")
    print(f"  提升: {best_score - baseline_score:+.3f}")

    if best_k > 0 and best_score > baseline_score:
        print(f"\n  ✓ 最优子集优于无宏观基线")
        print(f"  启用特征 ({len(results_by_k[best_k]['features'])}个): "
              f"{results_by_k[best_k]['features']}")
    else:
        print(f"\n  ✗ 最优子集未超过无宏观基线，宏观特征不建议启用")

    return results_by_k, best_k


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 70)
    print("  宏观特征级选择 v2 — 基于重要性的精确选择")
    print("  修正 v1: 特征级开关 + 均衡评分 + 5币种验证")
    print("=" * 70)
    print(f"  重要性分析币种: {', '.join(IMPORTANCE_COINS)}")
    print(f"  测试币种: {', '.join(TEST_COINS)}")
    print(f"  快速回测: {N_FOLDS_FAST} 折, {MAX_BARS} bars")
    print(f"  Top-K 候选: {TOP_K_CANDIDATES}")

    # 预加载数据
    print("\n  [准备] 预加载 K 线数据...")
    for sym in IMPORTANCE_COINS:
        df = load_klines(sym)
        if df is not None:
            print(f"    {sym}: {len(df)} bars")
    get_ref_df()

    # Phase 1: 特征重要性分析
    ranked = analyze_feature_importance()
    if not ranked:
        print("\n  ✗ 无法获取特征重要性，退出")
        return

    # Phase 2: 子集测试
    results_by_k, best_k = test_top_k_subsets(ranked)

    # 保存结果
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": "feature_level_importance_v2",
        "config": {
            "importance_coins": IMPORTANCE_COINS,
            "test_coins": TEST_COINS,
            "n_folds": N_FOLDS_FAST,
            "max_bars": MAX_BARS,
            "scoring": "sharpe*1.0 + win_rate*2.0 + return*0.01 - dd*0.05 + pf*0.3",
        },
        "feature_ranking": [
            {"rank": i + 1, "feature": f, "importance": imp}
            for i, (f, imp) in enumerate(ranked)
        ],
        "results_by_k": {
            str(k): v for k, v in results_by_k.items()
        },
        "best_k": best_k,
        "best_features": results_by_k.get(best_k, {}).get("features", []),
    }

    output_path = os.path.join(
        SCRIPT_DIR, "..", "..", "..", "data", "baseline",
        "macro_feature_select_v2.json"
    )
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {output_path}")

    if best_k > 0:
        print(f"\n  下一步: 用 K={best_k} 的 {len(results_by_k[best_k]['features'])} 个特征")
        print(f"  跑 9 币种 5 折完整回测，与 baseline-v1 对比")

    print("=" * 70)


if __name__ == "__main__":
    main()
