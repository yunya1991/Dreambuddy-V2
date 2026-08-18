#!/usr/bin/env python3
"""
宏观特征优化 v3 — 统一评估口径的直接性能对比

修正 v2 的根本问题：
  v2 用 3000 bars / 3 折选特征，用 6000 bars / 5 折验证 → 样本不一致，选择不可靠
  v3 用 9 币种 / 5 折 / 6000 bars 统一评估所有配置，选择和验证同一口径

修正 v2 的方法论问题：
  v2 用 LightGBM importance 选特征 → importance ≠ 回测效用
  v3 直接用回测得分对比多种配置（特征级 + 维度级），不依赖 importance

测试配置：
  A. K=0     — 无宏观特征（真基线）
  B. K=3     — Top-3 非冗余（stablecoin_growth + tvl_change_7d + fgi_trend_7d）
  C. K=5     — Top-5 by importance（v2 的选择，含 3 个 FGI 冗余特征）
  D. K=8     — Top-8 by importance
  E. K=24    — 全特征
  F. Bayesian — 贝叶斯最优维度（funding + liquidity + onchain）

评分函数（多指标均衡）：
  score = sharpe*1.0 + win_rate*2.0 + return*0.01 - dd*0.05 + pf*0.3

落地标准：
  1. 平均得分 > K=0 基线
  2. 9 币种中 ≥6 个币种得分优于 K=0
  3. 无严重退化（任一币种得分降幅 < 30%）
"""
import sys
import os
import json
import time
import logging
import importlib
from pathlib import Path
from datetime import datetime

import numpy as np

# 设置路径
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]  # 11-易经推理系统/
sys.path.insert(0, str(PROJECT_ROOT))

# 避免 inspect.py 冲突
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# 配置 — 与 baseline-v1 完全对齐
# ============================================================
COINS = ["UNI", "PUMP", "HYPE", "ETH", "BTC", "SOL", "XAUT", "OKB", "BNB"]
TIMEFRAME = "1H"
MAX_BARS = 6000
N_FOLDS = 5
CONF_THRESHOLD = 0.40
TP_ATR = 3.0
SL_ATR = 2.0
MAX_HOLD_BARS = 60
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.001
FEATURE_SELECTION = True

# ============================================================
# 测试配置定义
# ============================================================

# v2 importance 排名（跨 5 币种平均）
IMPORTANCE_RANKING = [
    "stablecoin_growth",    # liquidity, imp=74.0
    "tvl_change_7d",        # liquidity, imp=72.6
    "fgi_trend_7d",         # sentiment, imp=72.4
    "fgi_divergence",       # sentiment, imp=71.6
    "fgi_zscore",           # sentiment, imp=55.8
    "market_cap_rank",      # valuation, imp=51.7 (3 coins)
    "ath_drop_pct",         # valuation, imp=25.7 (3 coins)
    "fgi_extreme_fear",     # sentiment, imp=2.6
]

CONFIGS = {
    "K=0": {
        "label": "无宏观特征（真基线）",
        "features": [],
        "dimensions": {},
    },
    "K=3": {
        "label": "Top-3 非冗余（liquidity×2 + sentiment×1）",
        "features": IMPORTANCE_RANKING[:3],  # stablecoin_growth, tvl_change_7d, fgi_trend_7d
        "dimensions": {},
    },
    "K=5": {
        "label": "Top-5 by importance（v2 选择，含3个FGI冗余）",
        "features": IMPORTANCE_RANKING[:5],
        "dimensions": {},
    },
    "K=8": {
        "label": "Top-8 by importance",
        "features": IMPORTANCE_RANKING[:8],
        "dimensions": {},
    },
    "K=24": {
        "label": "全特征（24个）",
        "features": "all",  # 特殊标记，全开
        "dimensions": {},
    },
    "Bayesian": {
        "label": "贝叶斯最优维度（funding+liquidity+onchain）",
        "features": [],
        "dimensions": {
            "macro_enable_sentiment": False,
            "macro_enable_funding": True,
            "macro_enable_liquidity": True,
            "macro_enable_onchain": True,
            "macro_enable_smart_money": False,
            "macro_enable_valuation": False,
        },
    },
}


def build_macro_config(config_def):
    """构建宏观特征开关配置

    两级开关优先级：特征级 > 维度级 > 默认 True
    - 特征级配置（K=3/5/8）：设置 macro_feat_* 开关
    - 维度级配置（Bayesian）：只设置 macro_enable_* 开关，不设 macro_feat_*
    - 全开（K=24）：不设任何开关
    - 全关（K=0）：设置所有 macro_feat_* 为 False
    """
    from scripts.memory_l4.bcrm2.macro_features import MacroFeatures
    cfg = {}

    if config_def["features"] == "all":
        # 全开：不设任何开关（默认 True）
        return {}

    # 特征级开关（仅当有指定特征时才设）
    # 注意：Bayesian 配置 features=[]，不设特征级开关，让维度级开关生效
    if config_def["features"]:
        enabled_features = set(config_def["features"])
        for feat in MacroFeatures.ALL_FEATURES:
            cfg[f"macro_feat_{feat}"] = feat in enabled_features
    elif not config_def.get("dimensions"):
        # K=0: 无特征且无维度开关 → 全部特征级关闭
        for feat in MacroFeatures.ALL_FEATURES:
            cfg[f"macro_feat_{feat}"] = False

    # 维度级开关（贝叶斯配置用）
    cfg.update(config_def.get("dimensions", {}))

    return cfg


def compute_score(metrics):
    """多指标均衡评分

    各指标典型范围（6000 bars / 5 折）：
      sharpe: 1-20
      win_rate: 0.4-0.85
      total_return: -10% ~ +300%
      max_drawdown: 2-15%
      profit_factor: 1-8

    权重设计：
      sharpe: 1.0（主指标）
      win_rate: 2.0（0.75 → 1.5 贡献）
      return: 0.01（100% → 1.0 贡献）
      drawdown: -0.05（10% → -0.5 惩罚）
      profit_factor: 0.3（3.0 → 0.9 贡献）
    """
    if metrics is None or metrics["total_trades"] == 0:
        return -10.0

    sharpe = metrics["sharpe_ratio"]
    win_rate = metrics["win_rate"]
    total_ret = metrics["total_return_pct"]
    max_dd = metrics["max_drawdown_pct"]
    pf = min(metrics["profit_factor"], 5.0)

    score = (
        1.0 * sharpe
        + 2.0 * win_rate
        + 0.01 * total_ret
        - 0.05 * max_dd
        + 0.3 * pf
    )
    return score


def get_git_commit():
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
        ).decode().strip()
    except Exception:
        return "unknown"


# ============================================================
# 数据缓存
# ============================================================
_KLINE_CACHE = {}
_REF_DF_CACHE = None


def load_klines(symbol):
    if symbol not in _KLINE_CACHE:
        from scripts.memory_l4.bcrm2.data_fetcher import get_klines
        _KLINE_CACHE[symbol] = get_klines(symbol, TIMEFRAME, max_bars=MAX_BARS)
    return _KLINE_CACHE[symbol]


def get_ref_df():
    global _REF_DF_CACHE
    if _REF_DF_CACHE is None:
        from scripts.memory_l4.bcrm2.data_fetcher import get_klines
        _REF_DF_CACHE = get_klines("BTC", TIMEFRAME, max_bars=MAX_BARS + 200)
    return _REF_DF_CACHE


# ============================================================
# 回测
# ============================================================

def run_single_backtest(symbol, df, macro_config):
    """运行单币种回测，返回 metrics dict"""
    from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester

    ref_df = get_ref_df()

    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=N_FOLDS,
        conf_threshold=CONF_THRESHOLD,
        tp_atr=TP_ATR,
        sl_atr=SL_ATR,
        max_hold_bars=MAX_HOLD_BARS,
        fee_rate=FEE_RATE,
        slippage_rate=SLIPPAGE_RATE,
        feature_selection=FEATURE_SELECTION,
        macro_config=macro_config if macro_config else None,
    )

    result = bt.run(df, ref_df=ref_df, verbose=False)

    return {
        "total_trades": result.total_trades,
        "win_rate": round(result.overall_win_rate, 4),
        "total_return_pct": round(result.total_return, 4),
        "max_drawdown_pct": round(result.max_drawdown, 4),
        "profit_factor": round(result.profit_factor, 4),
        "sharpe_ratio": round(result.sharpe_ratio, 4),
        "avg_hold_bars": round(result.avg_hold_bars, 2),
    }


def run_all_configs():
    """对 9 币种 × 6 配置运行回测"""
    print(f"\n  开始回测：{len(COINS)} 币种 × {len(CONFIGS)} 配置 = {len(COINS)*len(CONFIGS)} 次回测")
    print(f"  参数：{N_FOLDS} 折, {MAX_BARS} bars, conf={CONF_THRESHOLD}")
    print(f"  预计耗时：~{len(COINS)*len(CONFIGS)*1.5:.0f} 分钟\n")

    # 预构建所有配置的 macro_config
    config_macros = {}
    for config_name, config_def in CONFIGS.items():
        config_macros[config_name] = build_macro_config(config_def)

    # 结果存储：{config_name: {coin: metrics}}
    all_results = {config_name: {} for config_name in CONFIGS}

    t_start = time.time()

    for i, coin in enumerate(COINS, 1):
        print(f"\n{'='*60}")
        print(f"  [{i}/{len(COINS)}] {coin}")
        print(f"{'='*60}")

        df = load_klines(coin)
        if df is None or len(df) < 500:
            print(f"  [SKIP] 数据不足: {len(df) if df is not None else 0} bars")
            continue
        print(f"  K线: {len(df)} bars, {df.index[0]} ~ {df.index[-1]}")

        for config_name in CONFIGS:
            macro_config = config_macros[config_name]
            t0 = time.time()

            try:
                metrics = run_single_backtest(coin, df, macro_config)
                score = compute_score(metrics)
                metrics["score"] = round(score, 4)
                all_results[config_name][coin] = metrics

                elapsed = time.time() - t0
                print(f"    {config_name:<10} 交易={metrics['total_trades']:>3} "
                      f"胜率={metrics['win_rate']:.1%} "
                      f"收益={metrics['total_return_pct']:+.1f}% "
                      f"夏普={metrics['sharpe_ratio']:.2f} "
                      f"回撤={metrics['max_drawdown_pct']:.1f}% "
                      f"得分={score:.3f} ({elapsed:.0f}s)")
            except Exception as e:
                print(f"    {config_name:<10} 回测失败: {e}")
                all_results[config_name][coin] = None

    total_elapsed = time.time() - t_start
    print(f"\n  总耗时: {total_elapsed/60:.1f} 分钟")

    return all_results


# ============================================================
# 分析与对比
# ============================================================

def aggregate_config(config_results):
    """聚合单配置的多币种结果"""
    valid = {k: v for k, v in config_results.items() if v is not None}
    if not valid:
        return None
    n = len(valid)
    return {
        "coin_count": n,
        "total_trades": sum(v["total_trades"] for v in valid.values()),
        "avg_win_rate": round(sum(v["win_rate"] for v in valid.values()) / n, 4),
        "avg_return_pct": round(sum(v["total_return_pct"] for v in valid.values()) / n, 4),
        "avg_max_drawdown_pct": round(sum(v["max_drawdown_pct"] for v in valid.values()) / n, 4),
        "avg_profit_factor": round(sum(v["profit_factor"] for v in valid.values()) / n, 4),
        "avg_sharpe_ratio": round(sum(v["sharpe_ratio"] for v in valid.values()) / n, 4),
        "avg_score": round(sum(v["score"] for v in valid.values()) / n, 4),
    }


def compare_configs(all_results):
    """对比所有配置"""
    print(f"\n{'='*90}")
    print(f"  配置对比汇总（{len(COINS)} 币种 × {N_FOLDS} 折 × {MAX_BARS} bars）")
    print(f"{'='*90}")

    summaries = {}
    for config_name in CONFIGS:
        summaries[config_name] = aggregate_config(all_results[config_name])

    # 表格输出
    print(f"\n  {'配置':<12} {'特征数':>5} {'平均得分':>8} {'夏普':>7} {'胜率':>7} {'收益%':>8} {'回撤%':>7} {'盈亏比':>7} {'交易数':>6}")
    print(f"  {'-'*80}")
    for config_name in CONFIGS:
        s = summaries[config_name]
        if s is None:
            print(f"  {config_name:<12} {'N/A':>5}")
            continue
        n_feats = len(CONFIGS[config_name]["features"]) if CONFIGS[config_name]["features"] != "all" else 24
        if CONFIGS[config_name]["dimensions"]:
            n_feats = "dim"
        print(f"  {config_name:<12} {n_feats:>5} {s['avg_score']:>8.3f} "
              f"{s['avg_sharpe_ratio']:>7.2f} {s['avg_win_rate']:>7.1%} "
              f"{s['avg_return_pct']:>+8.1f} {s['avg_max_drawdown_pct']:>7.1f} "
              f"{s['avg_profit_factor']:>7.2f} {s['total_trades']:>6}")

    # 找最优配置
    baseline_score = summaries.get("K=0", {}).get("avg_score", 0)
    best_config = max(
        [c for c in CONFIGS if summaries[c] is not None],
        key=lambda c: summaries[c]["avg_score"],
    )
    best_score = summaries[best_config]["avg_score"]

    print(f"\n  最优配置: {best_config} (得分={best_score:.3f})")
    print(f"  K=0 基线: 得分={baseline_score:.3f}")
    print(f"  提升: {best_score - baseline_score:+.3f}")

    # 逐币种对比最优 vs K=0
    if best_config != "K=0":
        print(f"\n  逐币种对比 ({best_config} vs K=0):")
        print(f"  {'币种':<8} {'K=0得分':>8} {f'{best_config}得分':>10} {'变化':>8} {'判定':>6}")
        print(f"  {'-'*50}")
        improved = 0
        for coin in COINS:
            k0 = all_results["K=0"].get(coin)
            best = all_results[best_config].get(coin)
            if k0 is None or best is None:
                continue
            k0_score = k0["score"]
            best_s = best["score"]
            change = best_s - k0_score
            verdict = "✓" if change > 0 else "✗"
            if change > 0:
                improved += 1
            print(f"  {coin:<8} {k0_score:>8.3f} {best_s:>10.3f} {change:>+8.3f} {verdict:>6}")
        print(f"\n  改善币种: {improved}/{len(COINS)}")

    return summaries, best_config


def check_landing_criteria(all_results, best_config, summaries):
    """检查落地标准"""
    print(f"\n{'='*70}")
    print(f"  落地标准检查")
    print(f"{'='*70}")

    if best_config == "K=0":
        print(f"\n  ✗ 最优配置是 K=0（无宏观特征）")
        print(f"    结论：宏观特征在当前数据质量下不带来稳定收益")
        print(f"    建议：维持 baseline-v1（无宏观特征），待宏观数据源补齐后再优化")
        return False

    baseline = summaries["K=0"]
    best = summaries[best_config]

    # 标准1：平均得分 > K=0
    crit1 = best["avg_score"] > baseline["avg_score"]
    print(f"\n  标准1: 平均得分 > K=0 基线")
    print(f"    {best['avg_score']:.3f} > {baseline['avg_score']:.3f} → {'✓ 通过' if crit1 else '✗ 未通过'}")

    # 标准2：≥6/9 币种得分优于 K=0
    improved = 0
    for coin in COINS:
        k0 = all_results["K=0"].get(coin)
        best_r = all_results[best_config].get(coin)
        if k0 and best_r and best_r["score"] > k0["score"]:
            improved += 1
    crit2 = improved >= 6
    print(f"\n  标准2: ≥6/9 币种得分优于 K=0")
    print(f"    {improved}/9 改善 → {'✓ 通过' if crit2 else '✗ 未通过'}")

    # 标准3：无严重退化（任一币种得分降幅 < 30%）
    severe_degrade = []
    for coin in COINS:
        k0 = all_results["K=0"].get(coin)
        best_r = all_results[best_config].get(coin)
        if k0 and best_r and k0["score"] > 0:
            degrade = (k0["score"] - best_r["score"]) / k0["score"]
            if degrade > 0.30:
                severe_degrade.append((coin, degrade))
    crit3 = len(severe_degrade) == 0
    print(f"\n  标准3: 无严重退化（降幅 < 30%）")
    if severe_degrade:
        for coin, deg in severe_degrade:
            print(f"    {coin}: 退化 {deg:.1%}")
        print(f"    → ✗ 未通过")
    else:
        print(f"    → ✓ 通过")

    all_pass = crit1 and crit2 and crit3
    print(f"\n  总结: {'✓ 全部通过，可落地' if all_pass else '✗ 未全部通过，不可落地'}")

    if all_pass:
        config_def = CONFIGS[best_config]
        print(f"\n  落地配置:")
        if config_def["features"]:
            print(f"    启用特征 ({len(config_def['features'])}个): {config_def['features']}")
        if config_def["dimensions"]:
            print(f"    启用维度: {[k for k, v in config_def['dimensions'].items() if v]}")
        print(f"\n  下一步:")
        print(f"    1. 将配置写入实盘 config")
        print(f"    2. 更新 baseline_v1.json 为新基线")

    return all_pass


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 90)
    print("  宏观特征优化 v3 — 统一评估口径的直接性能对比")
    print("  修正 v2: 选择和验证同一口径（9币种/5折/6000bars）")
    print("=" * 90)
    print(f"  币种: {', '.join(COINS)}")
    print(f"  配置: {', '.join(CONFIGS.keys())}")
    print(f"  参数: {N_FOLDS} 折, {MAX_BARS} bars, conf={CONF_THRESHOLD}")

    # 预加载 K 线数据
    print(f"\n  [准备] 预加载 K 线数据...")
    for coin in COINS:
        df = load_klines(coin)
        if df is not None:
            print(f"    {coin}: {len(df)} bars")
    get_ref_df()

    # 打印配置详情
    print(f"\n  [配置详情]")
    for config_name, config_def in CONFIGS.items():
        if config_def["features"] == "all":
            print(f"    {config_name}: 全部 24 个特征")
        elif config_def["features"]:
            print(f"    {config_name}: {len(config_def['features'])} 个 → {config_def['features']}")
        elif config_def["dimensions"]:
            enabled_dims = [k.replace("macro_enable_", "") for k, v in config_def["dimensions"].items() if v]
            print(f"    {config_name}: 维度级 → {enabled_dims}")
        else:
            print(f"    {config_name}: 无宏观特征")

    # 运行回测
    all_results = run_all_configs()

    # 对比分析
    summaries, best_config = compare_configs(all_results)

    # 落地检查
    can_land = check_landing_criteria(all_results, best_config, summaries)

    # 保存结果
    output = {
        "version": "v3-macro-optimize",
        "created_at": datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "config": {
            "coins": COINS,
            "timeframe": TIMEFRAME,
            "max_bars": MAX_BARS,
            "n_folds": N_FOLDS,
            "conf_threshold": CONF_THRESHOLD,
            "tp_atr": TP_ATR,
            "sl_atr": SL_ATR,
            "max_hold_bars": MAX_HOLD_BARS,
            "fee_rate": FEE_RATE,
            "slippage_rate": SLIPPAGE_RATE,
            "feature_selection": FEATURE_SELECTION,
        },
        "configs_tested": {
            name: {
                "label": cfg["label"],
                "features": cfg["features"] if cfg["features"] != "all" else "all",
                "dimensions": cfg.get("dimensions", {}),
            }
            for name, cfg in CONFIGS.items()
        },
        "summaries": summaries,
        "best_config": best_config,
        "can_land": can_land,
        "per_config_per_coin": {
            config_name: {
                coin: result for coin, result in results.items()
            }
            for config_name, results in all_results.items()
        },
    }

    output_path = PROJECT_ROOT / "data" / "baseline" / "macro_optimize_v3.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\n  结果已保存: {output_path}")

    print(f"\n{'='*90}")


if __name__ == "__main__":
    main()
