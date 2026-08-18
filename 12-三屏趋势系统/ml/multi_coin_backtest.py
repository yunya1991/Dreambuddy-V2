"""多币种策略回测对比

对比两种模式：
1. 独立趋势模式：各币种独立运行AI V2策略
2. BTC趋势跟随模式（基线）：BTC信号决定小币交易方向

BTC趋势跟随逻辑（基线）：
- BTC看多或震荡 → 小币只允许看多（过滤掉空头信号）
- BTC看空 → 小币必须看空（过滤掉多头信号）

基线配置：ml/multi_coin_baseline_config.json
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from datetime import datetime

from data.market_data import fetch_candles
from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2
from backtest.engine import BacktestEngine


# 币种配置
COINS = {
    "BTC": {"inst_id": "BTC-USDT", "is_btc": True},
    "ETH": {"inst_id": "ETH-USDT", "is_btc": False},
    "SOL": {"inst_id": "SOL-USDT", "is_btc": False},
    "UNI": {"inst_id": "UNI-USDT", "is_btc": False},
}


def fetch_coin_data(inst_id: str, bar: str = "1D", limit: int = 600) -> pd.DataFrame:
    """获取币种K线数据"""
    try:
        candles = fetch_candles(inst_id, bar=bar, limit=limit)
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("timestamp")
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        print(f"  [ERROR] 获取 {inst_id} 数据失败: {e}")
        return pd.DataFrame()


def get_fundamental_data() -> Dict:
    """模拟基本面数据"""
    return {
        "screen1": {
            "composite_score": 65.0, "momentum_score": 70.0,
            "value_score": 60.0, "growth_score": 65.0,
            "quality_score": 68.0, "sentiment_score": 55.0,
        },
        "fundamental_9": {
            "pe_ttm": 15.0, "pb": 2.0, "roe": 12.0,
            "revenue_growth": 20.0, "profit_growth": 18.0,
            "debt_ratio": 45.0, "cash_ratio": 30.0,
            "gross_margin": 35.0, "net_margin": 15.0,
        }
    }


def load_baseline_config() -> Dict:
    """加载多币种基线配置"""
    config_path = os.path.join(os.path.dirname(__file__), "multi_coin_baseline_config.json")
    if not os.path.exists(config_path):
        print(f"  [WARN] 基线配置不存在: {config_path}，使用内置默认参数")
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [WARN] 加载基线配置失败: {e}")
        return None


def create_strategy(baseline_config: Dict = None) -> LeastResistanceAIStrategyV2:
    """创建AI V2策略（从基线配置加载参数）"""
    if baseline_config is None:
        baseline_config = load_baseline_config()

    # 优先使用基线配置，否则使用内置默认
    if baseline_config:
        sp = baseline_config.get("strategy_params", {})
        dws = baseline_config.get("dynamic_weight_fusion", {})
        print(f"  [基线] 加载版本: {baseline_config.get('version', 'unknown')}")
    else:
        sp = {}
        dws = {}

    # 默认参数（基线配置缺失字段时使用）
    defaults = {
        "label_lookahead": 7,
        "train_window": 200,
        "retrain_interval": 30,
        "min_ml_confidence": 0.1,
        "enable_fundamental": True,
        "enable_multitask": True,
        "enable_dynamic_weight": True,
        "enable_feature_selection": False,
        "base_rule_weight": 0.3,
    }
    params = {**defaults, **sp}

    strategy = LeastResistanceAIStrategyV2(
        label_lookahead=params["label_lookahead"],
        train_window=params["train_window"],
        retrain_interval=params["retrain_interval"],
        min_ml_confidence=params["min_ml_confidence"],
        enable_fundamental=params["enable_fundamental"],
        enable_multitask=params["enable_multitask"],
        enable_dynamic_weight=params["enable_dynamic_weight"],
        enable_feature_selection=params["enable_feature_selection"],
        base_rule_weight=params["base_rule_weight"],
        fundamental_data=get_fundamental_data(),
    )
    # 应用优化的动态权重参数（基线配置优先）
    if strategy.dynamic_fusion:
        strategy.dynamic_fusion.base_rule_weight = dws.get("base_rule_weight", 0.3)
        strategy.dynamic_fusion.trend_sensitivity = dws.get("trend_sensitivity", 0.25)
        strategy.dynamic_fusion.vol_sensitivity = dws.get("vol_sensitivity", 0.25)
        strategy.dynamic_fusion.volume_sensitivity = dws.get("volume_sensitivity", 0.2)
        strategy.dynamic_fusion.duration_sensitivity = dws.get("duration_sensitivity", 0.25)
    return strategy


def run_independent_mode(prices_dict: Dict[str, pd.DataFrame], baseline_config: Dict = None) -> Dict[str, Dict]:
    """独立趋势模式：各币种独立运行"""
    print("\n" + "=" * 60)
    print("  模式A: 独立趋势模式")
    print("=" * 60)

    results = {}
    strategy = create_strategy(baseline_config)

    for coin, prices in prices_dict.items():
        if prices.empty or len(prices) < 300:
            print(f"  [{coin}] 数据不足，跳过")
            continue

        print(f"\n  [{coin}] 运行策略...", end=" ", flush=True)
        try:
            signals = strategy.generate_signals(prices)
            engine = BacktestEngine(initial_capital=10000)
            result = engine.run(prices["close"], signals)
            m = result["metrics"]
            results[coin] = m
            print(f"收益: {m['total_return_pct']:.2f}% 夏普: {m['sharpe_ratio']:.3f} 交易: {m['total_trades']}")
        except Exception as e:
            print(f"失败: {e}")
            results[coin] = None

    return results


def run_btc_ma_filter_mode(prices_dict: Dict[str, pd.DataFrame], baseline_config: Dict = None) -> Dict[str, Dict]:
    """模式C: BTC均线过滤模式

    规则：
    1. BTC 3天有效跌破日线MA200 → 小币只允许做空
    2. BTC跌至周线MA200后（价格回升/触底）→ 小币只允许做多
    3. 其他情况 → 小币独立运行

    注意：周线MA200需要~200周数据，当前OKX仅返回300天日线，
    此模式在数据约束下不可行，仅保留作为未来扩展。
    """
    print("\n" + "=" * 60)
    print("  模式C: BTC均线过滤模式 [数据约束下不可行]")
    print("=" * 60)

    results = {}
    strategy = create_strategy(baseline_config)

    btc_prices = prices_dict.get("BTC")
    if btc_prices is None or btc_prices.empty or len(btc_prices) < 300:
        print("  [ERROR] BTC数据不足")
        return results

    print("\n  [BTC] 计算均线状态...", end=" ", flush=True)

    # 日线MA200
    btc_daily_ma200 = btc_prices["close"].rolling(200).mean().fillna(method="bfill")

    # 周线MA200（重采样到周线）
    btc_weekly = btc_prices["close"].resample("W").last()
    btc_weekly_ma200 = btc_weekly.rolling(200).mean().fillna(method="bfill")
    # 对齐回日线
    btc_weekly_ma200_daily = btc_weekly_ma200.reindex(btc_prices.index, method="ffill")

    # 条件1: 3天有效跌破日线MA200
    below_daily_ma200 = btc_prices["close"] < btc_daily_ma200
    break_daily_ma200 = below_daily_ma200.rolling(3).sum() >= 3

    # 条件2: BTC跌至周线MA200附近（±15%区间）且近期从下方回升到MA200附近
    # 判定"跌至周线MA200后"：过去30天曾触及周线MA200下方（价格<MA200*1.05），且当前价格回升至±15%内
    weekly_ma_dist = (btc_prices["close"] - btc_weekly_ma200_daily) / btc_weekly_ma200_daily
    # 过去30天曾下探到周线MA200附近（±5%下方）
    touched_weekly_ma200 = (btc_prices["close"] < btc_weekly_ma200_daily * 1.05).rolling(30).sum() >= 1
    # 当前价格在周线MA200 ±15% 区间
    near_weekly_ma200 = (weekly_ma_dist > -0.15) & (weekly_ma_dist < 0.15)
    # 组合：触底后回升
    near_weekly_ma200 = near_weekly_ma200 & touched_weekly_ma200

    # 定义BTC状态
    def classify_btc_ma_state(idx):
        if break_daily_ma200.loc[idx]:
            return "BELOW_MA200"  # 跌破日线MA200
        elif near_weekly_ma200.loc[idx]:
            return "NEAR_WEEKLY_MA200"  # 接近周线MA200
        else:
            return "NORMAL"  # 正常状态

    btc_ma_states = pd.Series([classify_btc_ma_state(i) for i in btc_prices.index], index=btc_prices.index)

    # BTC自身结果
    btc_signals = strategy.generate_signals(btc_prices)
    btc_engine = BacktestEngine(initial_capital=10000)
    btc_result = btc_engine.run(btc_prices["close"], btc_signals)
    m = btc_result["metrics"]
    print(f"收益: {m['total_return_pct']:.2f}% 夏普: {m['sharpe_ratio']:.3f}")

    # 统计BTC状态分布
    state_counts = btc_ma_states.value_counts()
    print(f"\n  [BTC状态分布] BELOW_MA200:{state_counts.get('BELOW_MA200', 0)} "
          f"NEAR_WEEKLY_MA200:{state_counts.get('NEAR_WEEKLY_MA200', 0)} "
          f"NORMAL:{state_counts.get('NORMAL', 0)}")

    # 小币根据BTC均线状态过滤信号
    for coin, prices in prices_dict.items():
        if coin == "BTC" or prices.empty or len(prices) < 300:
            continue

        print(f"\n  [{coin}] 生成并过滤信号...", end=" ", flush=True)
        try:
            raw_signals = strategy.generate_signals(prices)

            aligned_btc = btc_ma_states.reindex(raw_signals.index, method="ffill")

            filtered_signals = raw_signals.copy()
            for idx in filtered_signals.index:
                btc_state = aligned_btc.get(idx, "NORMAL")
                raw_sig = filtered_signals.loc[idx]

                if btc_state == "BELOW_MA200":
                    # BTC跌破日线MA200 → 小币只允许做空
                    if raw_sig > 0:
                        filtered_signals.loc[idx] = 0
                elif btc_state == "NEAR_WEEKLY_MA200":
                    # BTC接近周线MA200 → 小币只允许做多
                    if raw_sig < 0:
                        filtered_signals.loc[idx] = 0
                # NORMAL状态：小币独立运行，不做过滤

            n_filtered = (filtered_signals != raw_signals).sum()
            n_long_kept = ((raw_signals > 0) & (filtered_signals > 0)).sum()
            n_short_kept = ((raw_signals < 0) & (filtered_signals < 0)).sum()

            engine = BacktestEngine(initial_capital=10000)
            result = engine.run(prices["close"], filtered_signals)
            m = result["metrics"]
            results[coin] = m
            print(f"收益: {m['total_return_pct']:.2f}% 夏普: {m['sharpe_ratio']:.3f} "
                  f"交易: {m['total_trades']} (过滤{n_filtered}个, 保留多{n_long_kept}/空{n_short_kept})")

        except Exception as e:
            print(f"失败: {e}")
            results[coin] = None

    results["BTC"] = btc_result["metrics"]
    return results


def run_btc_follow_mode(prices_dict: Dict[str, pd.DataFrame], baseline_config: Dict = None) -> Dict[str, Dict]:
    """模式B: BTC趋势跟随模式（基线）：BTC信号决定小币方向

    规则：
    - BTC看多/震荡 → 小币只允许看多（过滤空头信号）
    - BTC看空 → 小币必须看空（过滤多头信号）

    配置参数来自 multi_coin_baseline_config.json
    """
    print("\n" + "=" * 60)
    print("  模式B: BTC趋势跟随模式 [基线]")
    print("=" * 60)

    results = {}
    strategy = create_strategy(baseline_config)

    # 先获取BTC信号
    btc_prices = prices_dict.get("BTC")
    if btc_prices is None or btc_prices.empty or len(btc_prices) < 300:
        print("  [ERROR] BTC数据不足")
        return results

    print("\n  [BTC] 生成趋势信号...", end=" ", flush=True)
    btc_signals = strategy.generate_signals(btc_prices)

    # 判断BTC趋势方向
    # 规则：取最近N天信号的平均值作为BTC趋势判断
    btc_trend_window = 7
    btc_trend = btc_signals.rolling(btc_trend_window).mean().fillna(0)

    # 分类BTC状态
    def classify_btc_state(trend_val: float) -> str:
        if trend_val > 0.1:
            return "LONG"  # 看多
        elif trend_val < -0.1:
            return "SHORT"  # 看空
        else:
            return "NEUTRAL"  # 震荡

    btc_states = btc_trend.apply(classify_btc_state)

    btc_engine = BacktestEngine(initial_capital=10000)
    btc_result = btc_engine.run(btc_prices["close"], btc_signals)
    m = btc_result["metrics"]
    print(f"收益: {m['total_return_pct']:.2f}% 夏普: {m['sharpe_ratio']:.3f}")

    # 小币根据BTC状态过滤信号
    for coin, prices in prices_dict.items():
        if coin == "BTC" or prices.empty or len(prices) < 300:
            continue

        print(f"\n  [{coin}] 生成并过滤信号...", end=" ", flush=True)
        try:
            raw_signals = strategy.generate_signals(prices)

            # 对齐时间索引
            aligned_btc = btc_states.reindex(raw_signals.index, method="ffill")

            # 过滤逻辑
            filtered_signals = raw_signals.copy()
            for idx in filtered_signals.index:
                btc_state = aligned_btc.get(idx, "NEUTRAL")
                raw_sig = filtered_signals.loc[idx]

                if btc_state == "LONG" or btc_state == "NEUTRAL":
                    # BTC看多或震荡 → 小币只允许看多
                    if raw_sig < 0:
                        filtered_signals.loc[idx] = 0  # 过滤空头
                elif btc_state == "SHORT":
                    # BTC看空 → 小币必须看空
                    if raw_sig > 0:
                        filtered_signals.loc[idx] = 0  # 过滤多头

            # 统计过滤效果
            n_filtered = (filtered_signals != raw_signals).sum()
            n_long_kept = ((raw_signals > 0) & (filtered_signals > 0)).sum()
            n_short_kept = ((raw_signals < 0) & (filtered_signals < 0)).sum()

            engine = BacktestEngine(initial_capital=10000)
            result = engine.run(prices["close"], filtered_signals)
            m = result["metrics"]
            results[coin] = m
            print(f"收益: {m['total_return_pct']:.2f}% 夏普: {m['sharpe_ratio']:.3f} "
                  f"交易: {m['total_trades']} (过滤{n_filtered}个, 保留多{n_long_kept}/空{n_short_kept})")

        except Exception as e:
            print(f"失败: {e}")
            results[coin] = None

    # 也保存BTC自身结果
    results["BTC"] = btc_result["metrics"]

    return results


def print_comparison_table(mode_a_results: Dict, mode_b_results: Dict, mode_c_results: Dict = None) -> None:
    """打印对比表格（支持2-3种模式）"""
    print("\n" + "=" * 80)
    print("  多币种策略对比报告")
    print("=" * 80)

    all_coins = set(mode_a_results.keys()) | set(mode_b_results.keys())
    if mode_c_results:
        all_coins |= set(mode_c_results.keys())
    all_coins = sorted(all_coins)

    if mode_c_results:
        header = f"{'币种':>8} {'模式A收益':>11} {'模式A夏普':>9} {'模式B收益':>11} {'模式B夏普':>9} {'模式C收益':>11} {'模式C夏普':>9}"
        print(f"\n{header}")
        print("-" * 80)

        total_a = total_b = total_c = 0
        valid_coins = 0
        best_mode = {}

        for coin in all_coins:
            a = mode_a_results.get(coin)
            b = mode_b_results.get(coin)
            c = mode_c_results.get(coin) if mode_c_results else None

            a_ret = a["total_return_pct"] if a else 0
            a_sharpe = a["sharpe_ratio"] if a else 0
            b_ret = b["total_return_pct"] if b else 0
            b_sharpe = b["sharpe_ratio"] if b else 0
            c_ret = c["total_return_pct"] if c else 0
            c_sharpe = c["sharpe_ratio"] if c else 0

            print(f"{coin:>8} {a_ret:>10.2f}% {a_sharpe:>9.3f} {b_ret:>10.2f}% {b_sharpe:>9.3f} {c_ret:>10.2f}% {c_sharpe:>9.3f}")

            if a and b and c:
                total_a += a_ret
                total_b += b_ret
                total_c += c_ret
                valid_coins += 1
                # 记录最佳模式
                best = max([(a_ret, "A"), (b_ret, "B"), (c_ret, "C")], key=lambda x: x[0])
                best_mode[coin] = best[1]

        if valid_coins > 0:
            avg_a = total_a / valid_coins
            avg_b = total_b / valid_coins
            avg_c = total_c / valid_coins
            print("-" * 80)
            print(f"{'平均':>8} {avg_a:>10.2f}% {'':>9} {avg_b:>10.2f}% {'':>9} {avg_c:>10.2f}% {'':>9}")

            best_avg = max([(avg_a, "A"), (avg_b, "B"), (avg_c, "C")], key=lambda x: x[0])
            print(f"\n结论: 模式{best_avg[1]}最优 (平均收益: {best_avg[0]:.2f}%)")
            print(f"各币种最佳模式: {best_mode}")
    else:
        header = f"{'币种':>8} {'模式A收益':>12} {'模式A夏普':>10} {'模式B收益':>12} {'模式B夏普':>10} {'差值':>8}"
        print(f"\n{header}")
        print("-" * 70)

        total_a = 0
        total_b = 0
        valid_coins = 0

        for coin in all_coins:
            a = mode_a_results.get(coin)
            b = mode_b_results.get(coin)

            a_ret = a["total_return_pct"] if a else 0
            a_sharpe = a["sharpe_ratio"] if a else 0
            b_ret = b["total_return_pct"] if b else 0
            b_sharpe = b["sharpe_ratio"] if b else 0
            diff = b_ret - a_ret

            print(f"{coin:>8} {a_ret:>11.2f}% {a_sharpe:>10.3f} {b_ret:>11.2f}% {b_sharpe:>10.3f} {diff:>+7.2f}%")

            if a and b:
                total_a += a_ret
                total_b += b_ret
                valid_coins += 1

        if valid_coins > 0:
            avg_a = total_a / valid_coins
            avg_b = total_b / valid_coins
            print("-" * 70)
            print(f"{'平均':>8} {avg_a:>11.2f}% {'':>10} {avg_b:>11.2f}% {'':>10} {avg_b - avg_a:>+7.2f}%")

        print(f"\n结论: {'模式B更优' if avg_b > avg_a else '模式A更优'} (平均收益差: {avg_b - avg_a:+.2f}%)")


def main():
    print("=" * 70)
    print("  多币种策略回测对比")
    print("=" * 70)

    # 加载基线配置
    print("\n0. 加载基线配置...")
    baseline_config = load_baseline_config()
    if baseline_config:
        print(f"   ✓ 版本: {baseline_config.get('version', 'unknown')}")
        print(f"   ✓ 模式: {baseline_config.get('mode', 'unknown')}")
        print(f"   ✓ 说明: {baseline_config.get('description', '')[:60]}...")
    else:
        print("   ✗ 使用内置默认参数")

    print(f"\n币种: {list(COINS.keys())}")
    print("模式A: 独立趋势（各币种独立运行AI V2）")
    print("模式B: BTC趋势跟随（基线）← 当前推荐")
    print("模式C: BTC均线过滤（数据约束下不可行）")

    # 获取数据
    print("\n1. 获取数据...")
    prices_dict = {}
    for coin, config in COINS.items():
        print(f"   [{coin}] {config['inst_id']}...", end=" ", flush=True)
        df = fetch_coin_data(config["inst_id"], bar="1D", limit=600)
        if not df.empty:
            prices_dict[coin] = df
            print(f"✓ {len(df)} 天")
        else:
            print("✗ 失败")

    if len(prices_dict) < 2:
        print("\n[ERROR] 数据不足，无法运行回测")
        return

    # 运行基线模式（模式B）和对比模式（模式A）
    print("\n[基线模式] BTC趋势跟随（推荐）")
    mode_b_results = run_btc_follow_mode(prices_dict, baseline_config)
    mode_a_results = run_independent_mode(prices_dict, baseline_config)

    # 打印对比
    print_comparison_table(mode_a_results, mode_b_results)

    # 保存结果
    os.makedirs("ml/optimization_results", exist_ok=True)
    result_file = f"ml/optimization_results/multi_coin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    def clean_result(r):
        if r is None:
            return None
        cleaned = {}
        for k, v in r.items():
            if isinstance(v, pd.Timestamp):
                cleaned[k] = str(v)
            elif isinstance(v, np.floating):
                cleaned[k] = float(v)
            elif isinstance(v, np.integer):
                cleaned[k] = int(v)
            else:
                cleaned[k] = v
        return cleaned

    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "baseline_version": baseline_config.get("version", "unknown") if baseline_config else "default",
            "baseline_mode": "btc_trend_follow",
            "coins": list(COINS.keys()),
            "mode_a_independent": {k: clean_result(v) for k, v in mode_a_results.items()},
            "mode_b_btc_follow_baseline": {k: clean_result(v) for k, v in mode_b_results.items()},
        }, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {result_file}")


if __name__ == "__main__":
    main()
