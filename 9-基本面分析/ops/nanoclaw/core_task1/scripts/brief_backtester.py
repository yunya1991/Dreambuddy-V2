#!/usr/bin/env python3
"""
加密新闻简报技能回测工具
基于已生成的 brief_v2_*.json 数据进行回测分析
"""

import json
import os
import glob
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = "/workspace/ops/nanoclaw/core_task1/outputs"
HISTORICAL_DATA_DIR = "/workspace/ops/nanoclaw/core_task1/historical_data"

def load_brief_files():
    """加载所有 brief_v2_*.json 文件"""
    brief_files = glob.glob(os.path.join(OUTPUT_DIR, "brief_v2_*.json"))
    briefs = []

    for filepath in brief_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "timestamp" in data:
                    briefs.append({
                        "file": filepath,
                        "data": data
                    })
        except Exception as e:
            print(f"[WARN] Failed to load {filepath}: {e}")

    # 按时间排序
    briefs.sort(key=lambda x: x["data"].get("timestamp", ""))
    return briefs

def load_price_data():
    """加载 BTC 历史价格数据"""
    price_file = os.path.join(HISTORICAL_DATA_DIR, "btc_daily_prices.json")
    if os.path.exists(price_file):
        with open(price_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def calculate_signal_quality(briefs, prices):
    """
    计算信号质量

    检查简报中的信号与后续价格变动的相关性
    """
    results = []

    for i, brief in enumerate(briefs):
        data = brief["data"]
        timestamp = data.get("timestamp", "")
        signal_analysis = data.get("signal_analysis", {})
        composite_signal = signal_analysis.get("composite_signal", 0)
        recommendation = data.get("recommendation", "hold")

        # 提取日期
        try:
            date_str = timestamp[:10]  # YYYY-MM-DD
            current_price = None
            future_return_1d = None
            future_return_3d = None
            future_return_5d = None

            # 查找对应的价格数据
            if date_str in prices:
                current_price = prices[date_str].get("close")

            # 计算未来收益（1 天、3 天、5 天）
            date_idx = list(prices.keys()).index(date_str) if date_str in prices else -1
            if date_idx >= 0:
                if date_idx + 1 < len(prices):
                    future_date_1d = list(prices.keys())[date_idx + 1]
                    price_1d = prices[future_date_1d].get("close", current_price)
                    future_return_1d = (price_1d - current_price) / current_price if current_price else None

                if date_idx + 3 < len(prices):
                    future_date_3d = list(prices.keys())[date_idx + 3]
                    price_3d = prices[future_date_3d].get("close", current_price)
                    future_return_3d = (price_3d - current_price) / current_price if current_price else None

                if date_idx + 5 < len(prices):
                    future_date_5d = list(prices.keys())[date_idx + 5]
                    price_5d = prices[future_date_5d].get("close", current_price)
                    future_return_5d = (price_5d - current_price) / current_price if current_price else None

            results.append({
                "date": date_str,
                "composite_signal": composite_signal,
                "recommendation": recommendation,
                "current_price": current_price,
                "return_1d": future_return_1d,
                "return_3d": future_return_3d,
                "return_5d": future_return_5d,
                "signal_direction": "bullish" if composite_signal > 0.2 else "bearish" if composite_signal < -0.2 else "neutral"
            })
        except Exception as e:
            print(f"[WARN] Failed to process brief {timestamp}: {e}")

    return results

def evaluate_signal_accuracy(signal_data):
    """
    评估信号准确性
    """
    correct_1d = 0
    total_1d = 0
    correct_3d = 0
    total_3d = 0
    correct_5d = 0
    total_5d = 0

    profits_bullish = []
    profits_bearish = []
    profits_neutral = []

    for item in signal_data:
        signal = item["signal_direction"]

        # 1 天收益评估
        if item["return_1d"] is not None:
            total_1d += 1
            actual_direction = "bullish" if item["return_1d"] > 0.01 else "bearish" if item["return_1d"] < -0.01 else "neutral"
            if signal == actual_direction:
                correct_1d += 1

        # 3 天收益评估
        if item["return_3d"] is not None:
            total_3d += 1
            actual_direction = "bullish" if item["return_3d"] > 0.03 else "bearish" if item["return_3d"] < -0.03 else "neutral"
            if signal == actual_direction:
                correct_3d += 1

        # 5 天收益评估
        if item["return_5d"] is not None:
            total_5d += 1
            actual_direction = "bullish" if item["return_5d"] > 0.05 else "bearish" if item["return_5d"] < -0.05 else "neutral"
            if signal == actual_direction:
                correct_5d += 1

        # 收集不同信号的实际收益
        if item["return_1d"] is not None:
            if signal == "bullish":
                profits_bullish.append(item["return_1d"])
            elif signal == "bearish":
                profits_bearish.append(item["return_1d"])
            else:
                profits_neutral.append(item["return_1d"])

    def avg(lst):
        return sum(lst) / len(lst) if lst else 0

    return {
        "accuracy_1d": correct_1d / total_1d if total_1d > 0 else 0,
        "accuracy_3d": correct_3d / total_3d if total_3d > 0 else 0,
        "accuracy_5d": correct_5d / total_5d if total_5d > 0 else 0,
        "avg_profit_bullish": avg(profits_bullish),
        "avg_profit_bearish": avg(profits_bearish),
        "avg_profit_neutral": avg(profits_neutral),
        "sample_sizes": {
            "1d": total_1d,
            "3d": total_3d,
            "5d": total_5d,
            "bullish": len(profits_bullish),
            "bearish": len(profits_bearish),
            "neutral": len(profits_neutral)
        }
    }

def run_backtest():
    """运行回测"""
    print("=" * 70)
    print("加密新闻简报技能回测")
    print("=" * 70)

    # 加载数据
    print("\n[1/4] 加载简报数据...")
    briefs = load_brief_files()
    print(f"  已加载 {len(briefs)} 份简报")

    print("\n[2/4] 加载价格数据...")
    prices = load_price_data()
    print(f"  已加载 {len(prices)} 天价格数据")

    print("\n[3/4] 计算信号质量...")
    signal_data = calculate_signal_quality(briefs, prices)
    print(f"  已处理 {len(signal_data)} 个信号样本")

    print("\n[4/4] 评估信号准确性...")
    accuracy = evaluate_signal_accuracy(signal_data)

    # 输出结果
    print("\n" + "=" * 70)
    print("回测结果报告")
    print("=" * 70)

    print(f"""
【信号准确性】
  1 天预测准确率：  {accuracy['accuracy_1d']*100:.1f}%  (样本数：{accuracy['sample_sizes']['1d']})
  3 天预测准确率：  {accuracy['accuracy_3d']*100:.1f}%  (样本数：{accuracy['sample_sizes']['3d']})
  5 天预测准确率：  {accuracy['accuracy_5d']*100:.1f}%  (样本数：{accuracy['sample_sizes']['5d']})

【不同信号的平均收益 (1 天)】
  Bullish 信号：  {accuracy['avg_profit_bullish']*100:+.2f}%  (样本数：{accuracy['sample_sizes']['bullish']})
  Bearish 信号：  {accuracy['avg_profit_bearish']*100:+.2f}%  (样本数：{accuracy['sample_sizes']['bearish']})
  Neutral 信号：  {accuracy['avg_profit_neutral']*100:+.2f}%  (样本数：{accuracy['sample_sizes']['neutral']})

【评估结论】
""")

    # 评估
    if accuracy['accuracy_1d'] > 0.6:
        print("  ✅ 优秀：1 天预测准确率 > 60%")
    elif accuracy['accuracy_1d'] > 0.5:
        print("  ⚠️  一般：1 天预测准确率 50-60%")
    else:
        print("  ❌ 需改进：1 天预测准确率 < 50%")

    if accuracy['avg_profit_bullish'] > 0.01:
        print("  ✅ Bullish 信号有效：平均收益 > 1%")
    else:
        print("  ⚠️  Bullish 信号需改进：平均收益 <= 1%")

    if accuracy['avg_profit_bearish'] < -0.01:
        print("  ✅ Bearish 信号有效：平均收益 < -1%")
    else:
        print("  ⚠️  Bearish 信号需改进：平均收益 >= -1%")

    # 保存详细数据
    output_file = os.path.join(HISTORICAL_DATA_DIR, "brief_backtest_result.json")
    result_data = {
        "backtest_timestamp": datetime.now().isoformat(),
        "brief_count": len(briefs),
        "price_days": len(prices),
        "signal_samples": len(signal_data),
        "accuracy": accuracy,
        "detailed_results": signal_data
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    print(f"\n【详细结果已保存】")
    print(f"  {output_file}")
    print("=" * 70)

    return result_data

if __name__ == "__main__":
    run_backtest()
