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
TOP_K_CANDIDATES = [0, 3, 5, 8, 12, 24, 37]

# 第一轮 13 个新特征（宏金融扩展 7 + 残差 1 + BTC 链上扩展 5），用于 NEW13_ONLY 独立评估
FIRST_ROUND_13_NEW_FEATURES = [
    "vix_zone", "us_macro_regime", "sp500_7d_break", "dxy_strength",
    "btc_etf_flow_3d", "rwa_liquidity_pulse", "treasury_balance_delta",
    "stablecoin_minus_rwa",
    "whale_netflow_pulse", "exchange_btc_30d", "defi_breadth",
    "oi_liq_pressure", "btc_dom_delta",
]

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

        # === [REG] 三层判据日志：开关真命中证据（经验 1433933）===
        _log_registry_evidence(enabled=enabled, extra_cfg=None)

        features, _ = FeatureRegistry.compute_all(
            df=df, ref_df=ref_df, macro_df=macro_df,
            symbol=symbol, enabled=enabled, verbose=False,
        )

        # === [DF] 三层判据日志：新特征真注入证据（经验 1433933）===
        _log_dataframe_evidence(features_df=features, macro_df=macro_df, symbol=symbol)

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

            # === [LGBM] 三层判据日志：模型真消费新特征证据（经验 1433933）===
            _log_lgbm_evidence(importances=importances, symbol=symbol)
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

    # ──────────────────────────────────────────────────────────────────────
    # NEW13_ONLY 附加模式：只启用第一轮 13 新特征（完全不用旧 24 宏观特征的重要性排名）
    # 目的：评估「独立注入新13特征」本身是否具备增量价值（即便尾段只有3bars有值的严苛情形）
    # ──────────────────────────────────────────────────────────────────────
    _NEW13_KEY = "NEW13"
    print(f"\n  [测试] NEW13_ONLY: 启用第一轮13新特征独立 (subset = FIRST_ROUND_13_NEW_FEATURES)")
    subset_new13 = list(FIRST_ROUND_13_NEW_FEATURES)
    macro_cfg_new13 = build_macro_feat_config(subset_new13)
    coin_res_new13 = {}
    scores_new13 = []
    for symbol in TEST_COINS:
        df = load_klines(symbol)
        if df is None or len(df) < 800:
            continue
        try:
            result = run_backtest_with_features(symbol, df, macro_cfg_new13, n_folds=N_FOLDS_FAST)
            s = compute_score(result)
            coin_res_new13[symbol] = {
                "trades": result.total_trades,
                "win_rate": round(result.overall_win_rate, 4),
                "return_pct": round(result.total_return, 2),
                "max_drawdown": round(result.max_drawdown, 2),
                "sharpe": round(result.sharpe_ratio, 4),
                "profit_factor": round(result.profit_factor, 4),
                "score": round(s, 4),
            }
            scores_new13.append(s)
            print(f"    {symbol}: 交易={result.total_trades:>3} "
                  f"胜率={result.overall_win_rate:.1%} "
                  f"收益={result.total_return:+.1f}% "
                  f"夏普={result.sharpe_ratio:.2f} "
                  f"回撤={result.max_drawdown:.2f}% "
                  f"得分={s:.3f}")
        except Exception as e:
            print(f"    {symbol}: NEW13 回测失败: {e}")
            coin_res_new13[symbol] = None
    if scores_new13:
        avg_s = float(np.mean(scores_new13))
        avg_sh = float(np.mean([c["sharpe"] for c in coin_res_new13.values() if c]))
        avg_w = float(np.mean([c["win_rate"] for c in coin_res_new13.values() if c]))
        avg_r = float(np.mean([c["return_pct"] for c in coin_res_new13.values() if c]))
        avg_d = float(np.mean([c["max_drawdown"] for c in coin_res_new13.values() if c]))
        results_by_k[_NEW13_KEY] = {
            "label": "NEW13_ONLY（第一轮13新特征独立）",
            "features": subset_new13,
            "n_features": len(subset_new13),
            "avg_score": round(avg_s, 4),
            "avg_sharpe": round(avg_sh, 4),
            "avg_win_rate": round(avg_w, 4),
            "avg_return_pct": round(avg_r, 2),
            "avg_drawdown": round(avg_d, 2),
            "coin_results": coin_res_new13,
        }
        print(f"    → NEW13 平均: 得分={avg_s:.3f}, 夏普={avg_sh:.2f}, "
              f"胜率={avg_w:.1%}, 收益={avg_r:+.1f}%, 回撤={avg_d:.2f}%")
    else:
        print("    → NEW13_ONLY: 全部回测无有效结果")

    # 汇总对比
    print(f"\n  {'='*80}")
    print(f"  Top-K 子集 + NEW13_ONLY 汇总")
    print(f"  {'='*80}")
    print(f"  {'Config':<7} {'特征数':>5} {'得分':>8} {'夏普':>8} {'胜率':>8} {'收益%':>8} {'回撤%':>8}")
    print(f"  {'-'*60}")
    # 先按 TOP_K 顺序输出
    for k in TOP_K_CANDIDATES:
        if k in results_by_k:
            r = results_by_k[k]
            print(f"  K={k:<5} {r['n_features']:>5} {r['avg_score']:>8.3f} "
                  f"{r['avg_sharpe']:>8.2f} {r['avg_win_rate']:>8.1%} "
                  f"{r['avg_return_pct']:>+8.1f} {r['avg_drawdown']:>8.2f}")
    # 再单独输出 NEW13
    if _NEW13_KEY in results_by_k:
        r = results_by_k[_NEW13_KEY]
        print(f"  NEW13   {r['n_features']:>5} {r['avg_score']:>8.3f} "
              f"{r['avg_sharpe']:>8.2f} {r['avg_win_rate']:>8.1%} "
              f"{r['avg_return_pct']:>+8.1f} {r['avg_drawdown']:>8.2f}")

    # 找最优配置（含 NEW13）
    all_keys = list(TOP_K_CANDIDATES) + ([_NEW13_KEY] if _NEW13_KEY in results_by_k else [])
    valid_keys = [k for k in all_keys if k in results_by_k]
    if not valid_keys:
        return results_by_k, None
    best_key = max(valid_keys, key=lambda k: results_by_k[k]["avg_score"])
    baseline_key = 0
    best_score = results_by_k[best_key]["avg_score"]
    baseline_score = results_by_k.get(baseline_key, {}).get("avg_score", 0)

    print(f"\n  最优配置={'K='+str(best_key) if isinstance(best_key,int) else best_key}, 得分={best_score:.3f}")
    print(f"  基线 K=0, 得分={baseline_score:.3f}")
    print(f"  提升: {best_score - baseline_score:+.3f}")

    if best_key != 0 and best_score > baseline_score:
        print(f"\n  ✓ 最优配置优于无宏观基线")
        print(f"  启用特征 ({len(results_by_k[best_key]['features'])}个): "
              f"{results_by_k[best_key]['features']}")
    else:
        print(f"\n  ✗ 最优配置未超过无宏观基线，宏观特征不建议启用")

    return results_by_k, best_key


# ============================================================
# Phase 2-3: 严格型一损全弃判定 + 基线打印 + 子集剪枝 + t 检验
# 严格型（A）验收门槛：
#   任一指标劣于下限 → FAIL（一损全弃）；显著提升项 < 2 → FAIL。
#   下限 = 容差保护的 min(B0,B1)；显著 = 比 max(B0,B1) 再上一个台阶。
#   回撤指标为反向：上限 = max(B0,B1)+容差；显著 = 低于 min(B0,B1) - 阈值。
# ============================================================

# 严格型门槛（可全局配置，默认按 A 标准）
_STRICT_THRESHOLDS = {
    # (劣于下限的容差减法, 显著高于 max 的加法门槛)
    # 对反向指标（drawdown）, 含义为: (上限加法, 显著低于 min 的减法门槛)
    "sharpe":        {"worse_tol": 0.05, "sig_delta": 0.20},
    "win_pct":       {"worse_tol": 0.005, "sig_delta": 0.02},
    "return_pct":    {"worse_tol": 0.02,  "sig_delta": 0.05},
    "max_dd_pct":    {"worse_tol": 0.02,  "sig_delta": 0.03},  # 反向指标
    "profit_factor": {"worse_tol": 0.05,  "sig_delta": 0.10},
}


def evaluate_strict_criteria(cand: dict, B0: dict, B1: dict) -> tuple:
    """严格型一损全弃判定。

    Args:
        cand: 候选方案 5 指标 dict {sharpe,win_pct,return_pct,max_dd_pct,profit_factor}
        B0: 基线 K=0（无宏观）5 指标
        B1: 基线 Top-K（现有宏观）5 指标

    Returns:
        (ok: bool, reasons: list[str])
        任一指标「劣」→ ok=False；或显著项 <2 → ok=False。
    """
    reasons = []
    sig_count = 0

    # 指标分两类：正向（越大越好）/ 反向（越小越好，max_dd_pct）
    forward_metrics = ["sharpe", "win_pct", "return_pct", "profit_factor"]
    reverse_metrics = ["max_dd_pct"]

    for m in forward_metrics:
        th = _STRICT_THRESHOLDS[m]
        b0v, b1v, cv = B0[m], B1[m], cand[m]
        baseline_min = min(b0v, b1v)
        baseline_max = max(b0v, b1v)
        lower_floor = baseline_min - th["worse_tol"]
        sig_line = baseline_max + th["sig_delta"]
        if cv < lower_floor:
            reasons.append(
                f"{m} 劣于下限: cand={cv:.4f} < min(B0={b0v:.4f},B1={b1v:.4f})-{th['worse_tol']:.4f}={lower_floor:.4f}"
            )
        elif cv >= sig_line:
            sig_count += 1

    for m in reverse_metrics:
        th = _STRICT_THRESHOLDS[m]
        b0v, b1v, cv = B0[m], B1[m], cand[m]
        baseline_min = min(b0v, b1v)
        baseline_max = max(b0v, b1v)
        upper_cap = baseline_max + th["worse_tol"]  # 回撤不能超过上限
        sig_line = baseline_min - th["sig_delta"]  # 显著=比最好基线还低一截（回撤越小越好）
        if cv > upper_cap:
            reasons.append(
                f"{m}(回撤) 劣于上限: cand={cv:.4f} > max(B0={b0v:.4f},B1={b1v:.4f})+{th['worse_tol']:.4f}={upper_cap:.4f}"
            )
        elif cv <= sig_line:
            sig_count += 1

    if reasons:
        return False, reasons  # 一损全弃

    if sig_count < 2:
        reasons.append(
            f"显著提升项不足: 仅 {sig_count} 项达到显著门槛（要求≥2）。5项均不劣但未形成共振优势。"
        )
        return False, reasons

    return True, [f"通过：5指标均不劣 + {sig_count} 项显著提升（≥2项要求）"]


def print_baseline_with_evidence(B0: dict, B1: dict, coin: str, fold: int) -> str:
    """Phase0 基线打印：返回一条包含 [BASELINE] 前缀、币种、折数、两基线 5 指标的可读字符串。

    （经验 1433933：不新建脚本，直接在现有入口处打印可操作判据行）
    """
    def _row(d: dict) -> str:
        return (f"S={d['sharpe']:.3f} WR={d['win_pct']*100:.2f}% "
                f"R={d['return_pct']*100:+.2f}% DD={d['max_dd_pct']*100:.2f}% PF={d['profit_factor']:.3f}")
    line = (f"[BASELINE] coin={coin} fold={fold} | B0(无宏观): {_row(B0)} | "
            f"B1(现有TopK): {_row(B1)}")
    print(line)
    return line


def best_subset_search(scores: dict, threshold: float = 0.0) -> tuple:
    """Phase3 最佳子集剪枝搜索。

    Args:
        scores: {subset_key: score}，subset_key 可为 str（单特征）或 tuple/list（组合）
        threshold: 仅 score >= threshold 的候选参与竞争（剪枝）

    Returns:
        (best_names: tuple, best_score: float)
    """
    eligible = [(k, v) for k, v in scores.items() if v >= threshold]
    if not eligible:
        return (tuple(), 0.0)
    best_key, best_score = max(eligible, key=lambda kv: kv[1])
    if isinstance(best_key, (tuple, list)):
        best_names = tuple(best_key)
    else:
        best_names = (str(best_key),)
    return best_names, best_score


def paired_improvement_significant(baseline_metrics: list, cand_metrics: list,
                                   alpha: float = 0.05) -> bool:
    """配对 t 检验（单侧，cand 是否显著优于 baseline）。

    n_fold * n_coin = 3*5 = 15 样本。scipy 优先；缺失时用正态近似。
    """
    b = np.asarray(baseline_metrics, dtype=float)
    c = np.asarray(cand_metrics, dtype=float)
    if len(b) != len(c) or len(b) < 3:
        return False
    diff = c - b
    try:
        from scipy import stats as _stats  # 延迟导入，避免 import 成本
        # 单侧 t 检验：cand 是否 > baseline → H1: diff_mean > 0
        t_stat, p_two = _stats.ttest_rel(c, b)  # two-sided by default
        # 单侧 p = 如果 t>0（cand 更优）→ p_two/2；否则 1 - p_two/2
        if t_stat > 0:
            p_one = p_two / 2.0
        else:
            p_one = 1.0 - (p_two / 2.0) if p_two is not None else 1.0
        return bool(p_one < alpha)
    except Exception:
        # 无 scipy fallback：z-score 近似（正态）
        dmean = diff.mean()
        dstd = diff.std(ddof=1) + 1e-12
        z = dmean / (dstd / np.sqrt(len(diff)))
        # Φ(z) >= 1-α → z >= norminv(1-α) ≈ 1.645 for α=0.05
        from math import erf, sqrt
        phi = 0.5 * (1.0 + erf(z / sqrt(2.0)))
        return bool(phi > (1.0 - alpha))


# ============================================================
# Phase 0-3 三层判据日志点（经验 1433933：不新建脚本，直接在现有文件打可操作证据行）
#   [REG] 启动时：FeatureRegistry 启用的特征列表 → 证明两级开关真命中
#   [DF]  特征合并后：features.shape + 宏观列 null_counts → 证明新特征真注入进 DataFrame
#   [LGBM] LightGBM 训练后：importance top10 + 新特征 gain>0 列表 → 证明模型真消费了新特征
# ============================================================

# 12/13 个第一轮新特征名（用于 [LGBM] 日志筛选）
_NEW_EXT_FEATURES = [
    "vix_zone", "us_macro_regime", "sp500_7d_break", "dxy_strength",
    "btc_etf_flow_3d", "rwa_liquidity_pulse", "treasury_balance_delta",
    "stablecoin_minus_rwa",  # 宏金融扩展 + 残差 8 个
    "whale_netflow_pulse", "exchange_btc_30d", "defi_breadth",
    "oi_liq_pressure", "btc_dom_delta",  # BTC 链上扩展 5 个
]


def _log_registry_evidence(enabled: list, extra_cfg: dict | None = None) -> None:
    """[REG] 层日志：打印 FeatureRegistry.compute_all 实际启用的卦名/特征开关覆盖。"""
    cfg_snippet = ""
    if extra_cfg:
        # 只展示 macro 相关开关（前 8 个，避免日志泛滥）
        macro_keys = [k for k in extra_cfg.keys() if k.startswith("macro_")][:8]
        if macro_keys:
            cfg_snippet = f" | macro_cfg_sample={[(k, extra_cfg[k]) for k in macro_keys]}"
    line = f"[REG] FeatureRegistry enabled_gua={enabled} count={len(enabled)}{cfg_snippet}"
    print(line)
    logger.info(line)


def _log_dataframe_evidence(features_df: pd.DataFrame, macro_df: pd.DataFrame | None,
                            symbol: str) -> None:
    """[DF] 层日志：特征合并后的形状 + 新特征空值计数（证明数据底座真注入）。"""
    shape = tuple(features_df.shape)
    # 统计第一轮 13 个新特征的 null 率
    new_col_stats = {}
    for col in _NEW_EXT_FEATURES:
        if col in features_df.columns:
            total = len(features_df[col])
            nulls = int(features_df[col].isna().sum())
            new_col_stats[col] = f"{total - nulls}/{total}"
    macro_shape = tuple(macro_df.shape) if macro_df is not None else None
    line = (f"[DF] merge_klines_with_macro sym={symbol} feat_shape={shape} "
            f"macro_shape={macro_shape} | new_ext_nonnull={new_col_stats}")
    print(line)
    logger.info(line)


def _log_lgbm_evidence(importances: dict, symbol: str) -> None:
    """[LGBM] 层日志：importance Top10 + 第一轮 13 新特征中 gain>0 的名单。"""
    top10 = sorted(importances.items(), key=lambda x: -x[1])[:10]
    new_ext_used = [
        (f, float(importances[f])) for f in _NEW_EXT_FEATURES
        if f in importances and importances[f] > 0
    ]
    line = (f"[LGBM] sym={symbol} top10_gain={[(k, round(v, 2)) for k, v in top10]} "
            f"| new_ext_with_gain>0={new_ext_used}")
    print(line)
    logger.info(line)


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
