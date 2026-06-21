#!/usr/bin/env python3
"""
资金流回测验证模块

功能：
1. 加载历史 Regime 记录
2. 加载历史价格数据
3. 计算预测准确率
4. 生成回测评估报告

核心方法：
- 使用历史 Regime 记录中的 bias 字段作为预测信号
- 对比预测信号与实际次日收益方向
- 计算总体准确率、多头准确率、空头准确率、中性准确率
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# =============================================================================
# 配置
# =============================================================================

FLOW_DIR = Path("/workspace/ops/nanoclaw/core_task1/flow")
OUTPUT_DIR = FLOW_DIR / "outputs"
HISTORY_DIR = FLOW_DIR / "history"
DATA_DIR = Path("/workspace/ops/nanoclaw/core_task1/raw")

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 回测配置
BACKTEST_CONFIG = {
    "lookback_days": 30,  # 回测窗口（天）
    "min_samples": 10,    # 最小样本数
    "target_accuracy": 0.55,  # 目标准确率
    "target_bullish_accuracy": 0.60,  # 目标多头准确率
    "target_bearish_accuracy": 0.60,  # 目标空头准确率
}

# =============================================================================
# 数据加载
# =============================================================================

def load_historical_regime(lookback_days: int = 30) -> List[dict]:
    """
    加载历史 Regime 记录

    Args:
        lookback_days: 回测天数

    Returns:
        Regime 记录列表
    """
    # 优先从 history 目录加载 JSONL 记录
    history_files = sorted(HISTORY_DIR.glob("regime_history_*.jsonl"))

    if not history_files:
        print("[INFO] No regime history files found, checking output directory...")
        # 回退到 output 目录的 flow_regime 文件
        regime_files = sorted(OUTPUT_DIR.glob("flow_regime_*.json"))
        if regime_files:
            records = []
            for file in regime_files[-lookback_days:]:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 转换为记录格式
                    record = {
                        "timestamp": data.get("timestamp", ""),
                        "composite": data.get("composite", 0),
                        "bias": data.get("regime_output", {}).get("bias", "neutral"),
                        "filter": data.get("regime_output", {}).get("filter", "enable"),
                        "confidence": data.get("confidence", 0.5),
                        "layer_signals": data.get("layer_signals", {})
                    }
                    records.append(record)
            return records
        return []

    # 从 JSONL 加载
    records = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    for history_file in history_files:
        with open(history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    record = json.loads(line)
                    try:
                        record_time = datetime.fromisoformat(
                            record.get("timestamp", "").replace("Z", "+00:00")
                        )
                        if record_time >= cutoff:
                            records.append(record)
                    except:
                        pass

    # 按时间排序
    records.sort(key=lambda x: x.get("timestamp", ""))

    print(f"[INFO] Loaded {len(records)} historical regime records")
    return records


def load_historical_prices(lookback_days: int = 30) -> Dict[str, dict]:
    """
    加载历史价格数据（用于计算实际收益）

    优先级：
    1. CoinGecko API（实时获取）
    2. 本地缓存文件
    3. 模拟数据（用于测试）

    Returns:
        {date_str: {"open": float, "close": float, "high": float, "low": float}}
    """
    price_cache = {}

    # 尝试从本地缓存加载
    cache_file = DATA_DIR / "btc_price_history.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                price_cache = json.load(f)
            print(f"[INFO] Loaded {len(price_cache)} days of price history from cache")
            return price_cache
        except:
            pass

    # 尝试从 CoinGecko 获取
    print("[INFO] Fetching price data from CoinGecko...")
    try:
        import urllib.request

        # 获取 BTC 历史数据（最多 30 天）
        url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days={lookback_days}&interval=daily"

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())

        prices = data.get("prices", [])
        for price_point in prices:
            timestamp = price_point[0] / 1000  # ms -> s
            price = price_point[1]
            date_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
            price_cache[date_str] = {
                "close": price,
                "open": price,  # 简化：使用收盘价作为开盘价
                "high": price * 1.02,  # 估计值
                "low": price * 0.98    # 估计值
            }

        print(f"[INFO] Fetched {len(price_cache)} days of price data from CoinGecko")

        # 保存缓存
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(price_cache, f, indent=2)

        return price_cache
    except Exception as e:
        print(f"[WARN] Failed to fetch price data: {e}")

    # 回退到模拟数据
    print("[INFO] Using mock price data for testing")
    base_price = 85000
    for i in range(lookback_days):
        date = datetime.now(timezone.utc) - timedelta(days=lookback_days - i)
        date_str = date.strftime("%Y-%m-%d")
        # 模拟随机波动
        import random
        random.seed(hash(date_str) % 10000)
        daily_change = random.uniform(-0.05, 0.05)
        base_price = base_price * (1 + daily_change)
        price_cache[date_str] = {
            "close": round(base_price, 2),
            "open": round(base_price * (1 - daily_change), 2),
            "high": round(base_price * 1.02, 2),
            "low": round(base_price * 0.98, 2)
        }

    return price_cache


# =============================================================================
# 回测分析
# =============================================================================

def calculate_next_day_return(regime_timestamp: str, price_data: Dict[str, dict]) -> Tuple[float, str]:
    """
    计算 Regime 时间点次日的收益率

    Args:
        regime_timestamp: Regime 时间戳
        price_data: 价格数据

    Returns:
        (next_day_return, price_direction)
        next_day_return: 次日收益率（小数）
        price_direction: "up" | "down" | "unknown"
    """
    try:
        # 解析 Regime 时间
        regime_dt = datetime.fromisoformat(regime_timestamp.replace("Z", "+00:00"))
        regime_date = regime_dt.strftime("%Y-%m-%d")
        next_day = (regime_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        # 获取当日和次日价格
        today_price = price_data.get(regime_date, {}).get("close")
        next_price = price_data.get(next_day, {}).get("close")

        if not today_price or not next_price:
            # 尝试使用前后最近的数据
            print(f"  [DEBUG] Missing price data for {regime_date} or {next_day}")
            return 0.0, "unknown"

        # 计算收益率
        return_pct = (next_price - today_price) / today_price

        # 确定方向
        if return_pct > 0.01:  # >1% 视为上涨
            direction = "up"
        elif return_pct < -0.01:  # <-1% 视为下跌
            direction = "down"
        else:
            direction = "flat"

        return return_pct, direction
    except Exception as e:
        print(f"  [WARN] Error calculating return: {e}")
        return 0.0, "unknown"


def calculate_prediction_accuracy(
    regime_records: List[dict],
    price_data: Dict[str, dict]
) -> dict:
    """
    计算预测准确率

    Args:
        regime_records: Regime 记录列表
        price_data: 价格数据

    Returns:
        准确率统计字典
    """
    stats = {
        "total": 0,
        "correct": 0,
        "bullish": {"total": 0, "correct": 0},
        "bearish": {"total": 0, "correct": 0},
        "neutral": {"total": 0, "correct": 0},
        "predictions": []
    }

    for record in regime_records:
        bias = record.get("bias", "neutral")
        filter_status = record.get("filter", "enable")
        timestamp = record.get("timestamp", "")
        confidence = record.get("confidence", 0.5)

        # 跳过 filter=disable 的记录
        if filter_status == "disable":
            continue

        # 计算次日实际收益
        next_return, direction = calculate_next_day_return(timestamp, price_data)

        if direction == "unknown":
            continue

        stats["total"] += 1

        # 判断预测是否正确
        correct = False
        if bias == "bullish" and direction == "up":
            correct = True
            stats["bullish"]["total"] += 1
            stats["bullish"]["correct"] += 1
        elif bias == "bearish" and direction == "down":
            correct = True
            stats["bearish"]["total"] += 1
            stats["bearish"]["correct"] += 1
        elif bias == "neutral":
            stats["neutral"]["total"] += 1
            # 中性预测：只要不是大幅波动（|return| < 2%）就视为正确
            if abs(next_return) < 0.02:
                correct = True
                stats["neutral"]["correct"] += 1

        if correct:
            stats["correct"] += 1

        # 记录单次预测
        stats["predictions"].append({
            "timestamp": timestamp,
            "bias": bias,
            "confidence": confidence,
            "next_return": round(next_return, 4),
            "direction": direction,
            "correct": correct
        })

    # 计算准确率
    overall_accuracy = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
    bullish_accuracy = (stats["bullish"]["correct"] / stats["bullish"]["total"]
                       if stats["bullish"]["total"] > 0 else 0)
    bearish_accuracy = (stats["bearish"]["correct"] / stats["bearish"]["total"]
                       if stats["bearish"]["total"] > 0 else 0)
    neutral_accuracy = (stats["neutral"]["correct"] / stats["neutral"]["total"]
                       if stats["neutral"]["total"] > 0 else 0)

    stats["accuracy"] = {
        "overall": round(overall_accuracy, 4),
        "bullish": round(bullish_accuracy, 4),
        "bearish": round(bearish_accuracy, 4),
        "neutral": round(neutral_accuracy, 4)
    }

    print(f"[INFO] Calculation complete: {stats['total']} samples")
    return stats


# =============================================================================
# 回测报告
# =============================================================================

def generate_backtest_report(accuracy_stats: dict) -> str:
    """
    生成回测评估报告

    Args:
        accuracy_stats: 准确率统计

    Returns:
        Markdown 格式报告
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    accuracy = accuracy_stats.get("accuracy", {})
    overall = accuracy.get("overall", 0)
    bullish = accuracy.get("bullish", 0)
    bearish = accuracy.get("bearish", 0)
    neutral = accuracy.get("neutral", 0)

    # 评估结果
    target = BACKTEST_CONFIG["target_accuracy"]
    target_bullish = BACKTEST_CONFIG["target_bullish_accuracy"]
    target_bearish = BACKTEST_CONFIG["target_bearish_accuracy"]

    overall_status = "✅ 通过" if overall >= target else "❌ 未达标"
    bullish_status = "✅ 通过" if bullish >= target_bullish else "❌ 未达标"
    bearish_status = "✅ 通过" if bearish >= target_bearish else "❌ 未达标"

    # 综合评估
    passed_count = sum([overall >= target, bullish >= target_bullish, bearish >= target_bearish])
    if passed_count >= 2:
        overall_evaluation = "✅ 回测通过 - 模型有效"
    elif passed_count >= 1:
        overall_evaluation = "⚠️ 部分通过 - 需要优化"
    else:
        overall_evaluation = "❌ 回测失败 - 模型需要重大调整"

    report = f"""# 资金流回测评估报告

**生成时间**: {ts}
**回测窗口**: {BACKTEST_CONFIG["lookback_days"]} 天
**有效样本**: {accuracy_stats.get("total", 0)}

---

## 📊 预测准确率

| 指标 | 准确率 | 目标 | 状态 |
|------|--------|------|------|
| **总体准确率** | {overall:.2%} | ≥{target:.0%} | {overall_status} |
| **多头准确率** | {bullish:.2%} | ≥{target_bullish:.0%} | {bullish_status} |
| **空头准确率** | {bearish:.2%} | ≥{target_bearish:.0%} | {bearish_status} |
| **中性准确率** | {neutral:.2%} | ≥40% | - |

---

## 📈 样本分布

| Bias 类型 | 样本数 | 正确数 | 准确率 |
|-----------|--------|--------|--------|
| Bullish | {accuracy_stats.get("bullish", {}).get("total", 0)} | {accuracy_stats.get("bullish", {}).get("correct", 0)} | {bullish:.2%} |
| Bearish | {accuracy_stats.get("bearish", {}).get("total", 0)} | {accuracy_stats.get("bearish", {}).get("correct", 0)} | {bearish:.2%} |
| Neutral | {accuracy_stats.get("neutral", {}).get("total", 0)} | {accuracy_stats.get("neutral", {}).get("correct", 0)} | {neutral:.2%} |

---

## 🎯 综合评估

**{overall_evaluation}**

### 评估标准
- ✅ 通过：准确率 ≥ 目标值
- ⚠️ 部分通过：至少 1 项指标达标
- ❌ 失败：所有指标均未达标

### 性能基准对比
| 策略 | 收益率 | 最大回撤 | 夏普比率 |
|------|--------|----------|----------|
| 基准（Buy & Hold）| -25.26% | 28.56% | - |
| V9.3/V9.8 事件账本 | +5.22% | 15.96% | 0.85 |
| **资金流三层状态机** | TBD | TBD | TBD |

---

## 📝 预测详情
"""

    # 添加预测详情（最近 10 条）
    predictions = accuracy_stats.get("predictions", [])[-10:]
    if predictions:
        report += """
| 时间 | Bias | 置信度 | 次日收益 | 实际方向 | 预测结果 |
|------|------|--------|----------|----------|----------|
"""
        for pred in reversed(predictions[-10:]):
            result_icon = "✅" if pred.get("correct") else "❌"
            direction_icon = {"up": "📈", "down": "📉", "flat": "➡️"}.get(pred.get("direction", ""), "?")
            report += f"| {pred.get('timestamp', '')[:16]} | {pred.get('bias', '')} | {pred.get('confidence', 0):.2f} | {pred.get('next_return', 0):+.2%} | {direction_icon} | {result_icon} |\n"

    # 置信度校准分析
    report += f"""
---

## 🔍 置信度校准分析

### 置信度分布
"""

    # 按置信度分组统计
    high_conf_preds = [p for p in predictions if p.get("confidence", 0) >= 0.7]
    low_conf_preds = [p for p in predictions if p.get("confidence", 0) < 0.5]

    high_conf_acc = sum(1 for p in high_conf_preds if p.get("correct")) / len(high_conf_preds) if high_conf_preds else 0
    low_conf_acc = sum(1 for p in low_conf_preds if p.get("correct")) / len(low_conf_preds) if low_conf_preds else 0

    report += f"""
| 置信度区间 | 样本数 | 准确率 |
|------------|--------|--------|
| 高 (≥0.7) | {len(high_conf_preds)} | {high_conf_acc:.2%} |
| 中 (0.5-0.7) | {len(predictions) - len(high_conf_preds) - len(low_conf_preds)} | - |
| 低 (<0.5) | {len(low_conf_preds)} | {low_conf_acc:.2%} |

---

*本报告由 backtest_flow.py 生成 | 回测结果仅供参考，不构成投资建议*
"""

    return report


# =============================================================================
# 主流程
# =============================================================================

def run_backtest(lookback_days: int = 30) -> dict:
    """
    执行完整回测流程

    Args:
        lookback_days: 回测天数

    Returns:
        回测结果字典
    """
    print("=" * 60)
    print("资金流回测验证引擎")
    print("=" * 60)

    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookback_days": lookback_days,
        "accuracy_stats": None,
        "report_path": None
    }

    # ==========================================================================
    # Step 1: 加载历史 Regime 记录
    # ==========================================================================
    print("\n[STEP 1] 加载历史 Regime 记录...")
    regime_records = load_historical_regime(lookback_days)

    if not regime_records:
        print("[WARN] No historical regime records found")
        result["accuracy_stats"] = {
            "total": 0,
            "accuracy": {"overall": 0, "bullish": 0, "bearish": 0, "neutral": 0}
        }
        return result

    print(f"  记录数量：{len(regime_records)}")

    # 统计 bias 分布
    bias_counts = {}
    for record in regime_records:
        bias = record.get("bias", "neutral")
        bias_counts[bias] = bias_counts.get(bias, 0) + 1
    print(f"  Bias 分布：{bias_counts}")

    # ==========================================================================
    # Step 2: 加载历史价格数据
    # ==========================================================================
    print("\n[STEP 2] 加载历史价格数据...")
    price_data = load_historical_prices(lookback_days + 1)  # +1 for next day calculation
    print(f"  价格数据天数：{len(price_data)}")

    # ==========================================================================
    # Step 3: 计算预测准确率
    # ==========================================================================
    print("\n[STEP 3] 计算预测准确率...")
    accuracy_stats = calculate_prediction_accuracy(regime_records, price_data)
    result["accuracy_stats"] = accuracy_stats

    accuracy = accuracy_stats.get("accuracy", {})
    print(f"""
  总体准确率：{accuracy.get('overall', 0):.2%}
  多头准确率：{accuracy.get('bullish', 0):.2%}
  空头准确率：{accuracy.get('bearish', 0):.2%}
  中性准确率：{accuracy.get('neutral', 0):.2%}
""")

    # ==========================================================================
    # Step 4: 生成回测报告
    # ==========================================================================
    print("\n[STEP 4] 生成回测报告...")

    report = generate_backtest_report(accuracy_stats)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    report_path = OUTPUT_DIR / f"backtest_report_{ts}.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    result["report_path"] = str(report_path)
    print(f"  报告已保存：{report_path}")

    # 保存 JSON 结果
    json_path = OUTPUT_DIR / f"backtest_result_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"  JSON 已保存：{json_path}")

    # ==========================================================================
    # 输出摘要
    # ==========================================================================
    print("\n" + "=" * 60)
    print("回测完成!")
    print("=" * 60)

    overall = accuracy.get("overall", 0)
    target = BACKTEST_CONFIG["target_accuracy"]

    if overall >= target:
        print(f"✅ 回测通过！总体准确率 {overall:.2%} ≥ 目标 {target:.0%}")
    else:
        print(f"⚠️ 回测未达标：总体准确率 {overall:.2%} < 目标 {target:.0%}")

    return result


# =============================================================================
# 命令行入口
# =============================================================================

if __name__ == "__main__":
    import sys

    lookback = int(sys.argv[1]) if len(sys.argv) > 1 else BACKTEST_CONFIG["lookback_days"]
    result = run_backtest(lookback)
