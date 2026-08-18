#!/usr/bin/env python3
"""
通过 ml_trade_service 内部函数批量测试策略信号质量
模拟回测：统计策略信号的方向正确性和一致性
"""
import sys
sys.path.insert(0, '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统')

import ml_trade_service
from datetime import datetime, timedelta
import json

# 核心策略列表
CORE_STRATEGIES = [
    ("user_data.strategies.MultiGroupStrategy", "MultiGroupStrategy"),
    ("user_data.strategies.RegimeHybridStrategy", "RegimeHybridStrategy"),
    ("user_data.strategies.Bot2StrategyTrend", "Bot2StrategyTrend"),
    ("user_data.strategies.Bot2StrategyRange", "Bot2Strategy"),
    ("user_data.strategies.Strategy005", "Strategy005"),
    ("user_data.strategies.Strategy006", "Strategy006"),
    ("user_data.strategies.OTTStrategy", "OttStrategy"),
    ("user_data.strategies.AdaptiveVolatilityStrategy_forced", "AdaptiveVolatilityStrategy_forced"),
    ("user_data.strategies.MarketBreadthFlowStrategy", "BreadthFlow1HStrategy"),
    ("user_data.strategies.LongShortTripleScreenStrategy", "ShortTGEStrategy"),
    ("user_data.strategies.TrendConfirmationStrategy", "TrendConfirmationStrategy"),
    ("user_data.strategies.breakoutStrategy", "BreakoutStrategy"),
]

COINS = ["BTC", "ETH", "SOL", "AVAX", "ARB"]


def test_strategy_signals(strategy_module: str, class_name: str) -> dict:
    """测试策略在多个币种上的信号生成能力"""
    results = {
        "strategy": class_name,
        "module": strategy_module,
        "total_tests": 0,
        "signal_count": 0,
        "long_signals": 0,
        "short_signals": 0,
        "no_signal": 0,
        "errors": 0,
        "coins": {},
    }

    for coin in COINS:
        try:
            result = ml_trade_service._run_freqtrade_strategy_signal_hyperliquid(
                strategy_module, class_name, coin
            )
            results["total_tests"] += 1

            if result.get("ok"):
                side = result.get("side")
                tf = result.get("timeframe", "unknown")
                results["coins"][coin] = {
                    "side": side,
                    "timeframe": tf,
                    "tag": result.get("tag"),
                }

                if side == "long":
                    results["signal_count"] += 1
                    results["long_signals"] += 1
                elif side == "short":
                    results["signal_count"] += 1
                    results["short_signals"] += 1
                else:
                    results["no_signal"] += 1
            else:
                results["errors"] += 1
                results["coins"][coin] = {"error": result.get("error")}
        except Exception as e:
            results["errors"] += 1
            results["coins"][coin] = {"error": str(e)}

    # 计算信号活跃度
    if results["total_tests"] > 0:
        results["signal_rate"] = round(results["signal_count"] / results["total_tests"] * 100, 1)
        results["long_rate"] = round(results["long_signals"] / results["total_tests"] * 100, 1)
        results["short_rate"] = round(results["short_signals"] / results["total_tests"] * 100, 1)
    else:
        results["signal_rate"] = 0
        results["long_rate"] = 0
        results["short_rate"] = 0

    return results


def classify_timeframe(results: dict) -> str:
    """根据策略信号的时间周期进行分类"""
    timeframes = set()
    for coin_data in results["coins"].values():
        if "timeframe" in coin_data:
            timeframes.add(coin_data["timeframe"])

    if "4h" in timeframes or "1h" in timeframes:
        return "swing"  # 波段策略
    elif "5m" in timeframes or "15m" in timeframes:
        return "scalping"  #  scalp 策略
    else:
        return "unknown"


def calculate_score(r: dict) -> float:
    """计算策略综合评分"""
    if r["total_tests"] == 0 or r["errors"] > 2:
        return -999

    # 信号活跃度评分（30%）
    activity_score = r["signal_rate"] * 0.3

    # 信号一致性评分（40%）
    # 如果所有信号方向一致，给高分
    sides = [c.get("side") for c in r["coins"].values() if c.get("side")]
    if len(sides) >= 3 and len(set(sides)) == 1:
        consistency_score = 40
    elif len(sides) >= 2:
        consistency_score = 20
    else:
        consistency_score = 5

    # 稳定性评分（30%）
    stability_score = max(0, 30 - r["errors"] * 10)

    return round(activity_score + consistency_score + stability_score, 1)


def main():
    print("=" * 80)
    print("Freqtrade 策略信号质量测试")
    print(f"测试币种: {', '.join(COINS)}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    all_results = []

    for module, class_name in CORE_STRATEGIES:
        print(f"\n[测试] {class_name} ...")
        result = test_strategy_signals(module, class_name)
        result["category"] = classify_timeframe(result)
        result["score"] = calculate_score(result)
        all_results.append(result)

        print(f"  信号率: {result['signal_rate']}% ({result['signal_count']}/{result['total_tests']})")
        print(f"  做多: {result['long_signals']}, 做空: {result['short_signals']}, 无信号: {result['no_signal']}")
        print(f"  错误: {result['errors']}, 分类: {result['category']}, 评分: {result['score']}")

    # 保存结果
    output_file = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统/strategy_test_results.json"
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print("结果汇总")
    print("=" * 80)

    # 按评分排序
    all_results.sort(key=lambda x: x["score"], reverse=True)

    print("\n--- 按评分排序 ---")
    for i, r in enumerate(all_results, 1):
        status = "✅" if r["score"] > 30 else ("⚠️" if r["score"] > 0 else "❌")
        print(f"  {i}. {status} {r['strategy']}: 评分={r['score']}, 信号率={r['signal_rate']}%, 分类={r['category']}")

    # 按周期分类推荐
    print("\n--- 1h/4h 波段策略推荐 ---")
    swing_strategies = [r for r in all_results if r["category"] == "swing" and r["score"] > 0]
    for r in swing_strategies[:5]:
        print(f"  • {r['strategy']}: 评分={r['score']}, 信号率={r['signal_rate']}%")

    print("\n--- 5m/15m 短线策略推荐 ---")
    scalp_strategies = [r for r in all_results if r["category"] == "scalping" and r["score"] > 0]
    for r in scalp_strategies[:5]:
        print(f"  • {r['strategy']}: 评分={r['score']}, 信号率={r['signal_rate']}%")

    print(f"\n详细结果已保存至: {output_file}")

    # 输出推荐配置
    print("\n" + "=" * 80)
    print("推荐策略配置 (screen_engine.py)")
    print("=" * 80)

    # 选择 top 3 策略
    top_strategies = [r for r in all_results if r["score"] > 20][:3]

    print("\nFREQTRADE_STRATEGIES = {")
    for r in top_strategies:
        tf = "4h" if r["category"] == "swing" else "5m"
        print(f'    "{r["strategy"]}": {{')
        print(f'        "module": "{r["module"]}",')
        print(f'        "class": "{r["strategy"]}",')
        print(f'        "timeframe": "{tf}",')
        print(f'        "score": {r["score"]},')
        print("    },")
    print("}")


if __name__ == "__main__":
    main()
