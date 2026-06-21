#!/usr/bin/env python3
"""
信号融合模块 - 与 crypto-news-digest 联动

功能：
1. 读取 news-digest 的事件账本数据
2. 计算新闻情感信号 (news_sentiment)
3. 融合新闻信号与资金流信号
4. 输出综合交易信号

核心公式：
    fused_signal = news_weight × news_sentiment + flow_weight × flow_composite
"""

import json
import os
import math
from datetime import datetime, timezone
from pathlib import Path

# =============================================================================
# 配置
# =============================================================================

NEWS_DIGEST_DIR = Path("/workspace/ops/nanoclaw/core_task1/raw")
FLOW_DIR = Path("/workspace/ops/nanoclaw/core_task1/flow")
OUTPUT_DIR = FLOW_DIR / "outputs"

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# 信号融合配置
# =============================================================================

FUSION_CONFIG = {
    # 默认权重
    "default": {
        "news_weight": 0.50,
        "flow_weight": 0.50
    },
    # 高波动市场：新闻反应更快
    "high_volatility": {
        "news_weight": 0.60,
        "flow_weight": 0.40
    },
    # 低波动市场：资金流更可靠
    "low_volatility": {
        "news_weight": 0.40,
        "flow_weight": 0.60
    },
    # 信号冲突：倾向资金流（更客观）
    "conflict": {
        "news_weight": 0.30,
        "flow_weight": 0.70
    }
}

# 冲突检测阈值（两信号差值超过此值视为冲突）
CONFLICT_THRESHOLD = 0.3

# =============================================================================
# 新闻情感计算
# =============================================================================

def load_event_ledger() -> list:
    """
    加载 news-digest 的事件账本数据

    Returns:
        事件列表
    """
    # 查找最新的事件账本文件
    ledger_files = sorted(NEWS_DIGEST_DIR.glob("event_ledger_*.jsonl"))

    if not ledger_files:
        print("[WARN] No event ledger file found")
        return []

    latest_file = ledger_files[-1]
    events = []

    with open(latest_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    print(f"[INFO] Loaded {len(events)} events from {latest_file.name}")
    return events

def calculate_type_weight(event_type: str) -> float:
    """
    计算事件类型权重

    事件类型优先级：
    - P0: 监管/政策 > 交易所事故 > 宏观政策
    - P1: ETF > 稳定币 > 链上升级
    - P2: 一般新闻 > KOL 观点
    """
    type_weights = {
        # P0 - 重大事件
        "regulatory_ban": 1.0,
        "regulatory_approval": 1.0,
        "exchange_hack": 0.95,
        "exchange_bankruptcy": 0.95,
        "fed_rate_decision": 0.90,

        # P1 - 重要事件
        "etf_approval": 0.85,
        "etf_rejection": 0.85,
        "stablecoin_depeg": 0.80,
        "major_protocol_upgrade": 0.75,

        # P2 - 一般事件
        "whale_movement": 0.60,
        "exchange_listing": 0.55,
        "protocol_launch": 0.50,

        # P3 - 观点/ rumor
        "analyst_view": 0.40,
        "rumor": 0.35,
        "social_media": 0.30
    }

    return type_weights.get(event_type, 0.50)

def calculate_window_weight(event_timestamp: str) -> float:
    """
    计算时间窗口权重（指数衰减）

    T0 (0-2h): 1.0
    T1 (2-6h): 0.7
    T2 (6-12h): 0.4
    T3 (12-24h): 0.2
    """
    try:
        event_dt = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - event_dt).total_seconds() / 3600

        if age_hours <= 2:
            return 1.0
        elif age_hours <= 6:
            return 0.7
        elif age_hours <= 12:
            return 0.4
        elif age_hours <= 24:
            return 0.2
        else:
            return 0.1
    except:
        return 0.5

def calculate_surprise_weight(surprise_bucket: str) -> float:
    """
    计算意外程度权重

    surprise_bucket: "major_positive" | "positive" | "neutral" | "negative" | "major_negative"
    """
    surprise_weights = {
        "major_positive": 1.0,
        "major_negative": 1.0,
        "positive": 0.8,
        "negative": 0.8,
        "neutral": 0.5
    }

    return surprise_weights.get(surprise_bucket, 0.5)

def calculate_news_sentiment(events: list) -> dict:
    """
    计算新闻情感信号（V9.3 事件账本方法）

    核心公式：
    news_sentiment = Σ(base_sentiment × type_weight × window_weight × surprise_weight × confidence)
                     / Σ(type_weight × window_weight × surprise_weight × confidence)

    Returns:
        {
            "sentiment": float,  # [-1, 1]
            "weighted_sum": float,
            "weight_total": float,
            "event_count": int,
            "breakdown": {...}
        }
    """
    if not events:
        return {
            "sentiment": 0.0,
            "weighted_sum": 0.0,
            "weight_total": 0.0,
            "event_count": 0,
            "breakdown": {}
        }

    weighted_sum = 0.0
    weight_total = 0.0
    breakdown = {
        "positive_events": 0,
        "negative_events": 0,
        "neutral_events": 0,
        "by_type": {}
    }

    for event in events:
        # 支持两种字段名：sentiment_score 或 sentiment
        base_sentiment = event.get("sentiment_score", event.get("sentiment", 0.0))

        # 限制 sentiment 在 [-1, 1]
        base_sentiment = max(-1, min(1, base_sentiment))

        type_weight = calculate_type_weight(event.get("event_type", ""))
        window_weight = calculate_window_weight(event.get("timestamp", event.get("published_at", "")))

        # 支持 surprise_bucket 或 surprise_score
        surprise_bucket = event.get("surprise_bucket", "neutral")
        surprise_weight = calculate_surprise_weight(surprise_bucket)

        # 支持 confidence_level 或 confidence
        confidence = event.get("confidence_level", event.get("confidence", 0.8))

        # 综合权重
        total_weight = type_weight * window_weight * surprise_weight * confidence
        weighted_sum += base_sentiment * total_weight
        weight_total += total_weight

        # 统计
        if base_sentiment > 0.1:
            breakdown["positive_events"] += 1
        elif base_sentiment < -0.1:
            breakdown["negative_events"] += 1
        else:
            breakdown["neutral_events"] += 1

        # 按类型统计
        event_type = event.get("event_type", "unknown")
        if event_type not in breakdown["by_type"]:
            breakdown["by_type"][event_type] = {"count": 0, "sentiment_sum": 0}
        breakdown["by_type"][event_type]["count"] += 1
        breakdown["by_type"][event_type]["sentiment_sum"] += base_sentiment

    # 计算归一化 sentiment
    if weight_total > 0:
        news_sentiment = weighted_sum / weight_total
    else:
        news_sentiment = 0.0

    return {
        "sentiment": round(news_sentiment, 4),
        "weighted_sum": round(weighted_sum, 4),
        "weight_total": round(weight_total, 4),
        "event_count": len(events),
        "breakdown": breakdown
    }

# =============================================================================
# 信号融合逻辑
# =============================================================================

def detect_market_state(volatility_24h: float = None) -> str:
    """
    检测市场状态

    Args:
        volatility_24h: 24 小时波动率（可选）

    Returns:
        "high_volatility" | "low_volatility" | "default"
    """
    if volatility_24h is None:
        # 无数据时返回默认
        return "default"

    # 波动率阈值
    if volatility_24h > 0.05:  # >5% 波动
        return "high_volatility"
    elif volatility_24h < 0.02:  # <2% 波动
        return "low_volatility"
    else:
        return "default"

def detect_signal_conflict(news_sentiment: float, flow_composite: float) -> bool:
    """
    检测信号冲突

    冲突定义：两信号差值超过阈值 (0.3)，且方向相反
    """
    return (
        (news_sentiment > CONFLICT_THRESHOLD and flow_composite < -CONFLICT_THRESHOLD) or
        (news_sentiment < -CONFLICT_THRESHOLD and flow_composite > CONFLICT_THRESHOLD)
    )

def fuse_signals(
    news_sentiment: float,
    flow_composite: float,
    market_state: str = "default"
) -> dict:
    """
    融合新闻信号与资金流信号

    Args:
        news_sentiment: 新闻情感信号 [-1, 1]
        flow_composite: 资金流综合信号 [-1, 1]
        market_state: 市场状态

    Returns:
        {
            "fused_signal": float,
            "news_weight": float,
            "flow_weight": float,
            "conflict_flag": bool,
            "market_state": str,
            "recommendation": str
        }
    """
    # 检测冲突
    conflict_flag = detect_signal_conflict(news_sentiment, flow_composite)

    # 确定权重配置
    if conflict_flag:
        weights = FUSION_CONFIG["conflict"]
        print(f"[FUSION] Signal conflict detected! Using conflict weights.")
    elif market_state in FUSION_CONFIG:
        weights = FUSION_CONFIG[market_state]
    else:
        weights = FUSION_CONFIG["default"]

    news_weight = weights["news_weight"]
    flow_weight = weights["flow_weight"]

    # 融合信号
    fused_signal = news_weight * news_sentiment + flow_weight * flow_composite

    # 生成建议
    if fused_signal > 0.5:
        recommendation = "strong_buy"
    elif fused_signal > 0.2:
        recommendation = "buy"
    elif fused_signal > -0.2:
        recommendation = "hold"
    elif fused_signal > -0.5:
        recommendation = "sell"
    else:
        recommendation = "strong_sell"

    return {
        "fused_signal": round(fused_signal, 4),
        "news_weight": news_weight,
        "flow_weight": flow_weight,
        "conflict_flag": conflict_flag,
        "market_state": market_state,
        "recommendation": recommendation
    }

# =============================================================================
# 主流程
# =============================================================================

def run_signal_fusion(flow_regime_file: str = None) -> dict:
    """
    执行信号融合

    Args:
        flow_regime_file: 资金流 Regime JSON 文件路径（可选，默认使用最新文件）

    Returns:
        融合结果字典
    """
    print("=" * 60)
    print("信号融合引擎")
    print("=" * 60)

    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "news_signal": None,
        "flow_signal": None,
        "fused_signal": None,
        "diagnostics": {}
    }

    # ==========================================================================
    # Step 1: 加载新闻事件账本
    # ==========================================================================
    print("\n[STEP 1] 加载新闻事件账本...")
    events = load_event_ledger()
    news_result = calculate_news_sentiment(events)
    result["news_signal"] = news_result

    print(f"  事件数量：{news_result['event_count']}")
    print(f"  新闻情感：{news_result['sentiment']:+.4f}")
    print(f"  正面/负面/中性：{news_result['breakdown']['positive_events']}/{news_result['breakdown']['negative_events']}/{news_result['breakdown']['neutral_events']}")

    # ==========================================================================
    # Step 2: 加载资金流 Regime
    # ==========================================================================
    print("\n[STEP 2] 加载资金流 Regime...")

    if flow_regime_file:
        flow_path = Path(flow_regime_file)
    else:
        # 查找最新的 flow_regime 文件
        regime_files = sorted(OUTPUT_DIR.glob("flow_regime_*.json"))
        if regime_files:
            flow_path = regime_files[-1]
        else:
            print("  [WARN] No flow regime file found, using mock data")
            flow_path = None

    if flow_path and flow_path.exists():
        with open(flow_path, "r", encoding="utf-8") as f:
            flow_data = json.load(f)
        print(f"  加载文件：{flow_path.name}")
    else:
        # 模拟数据
        flow_data = {
            "composite": 0.0,
            "layer_signals": {
                "exogenous": 0.0,
                "leverage": 0.0,
                "onchain": 0.0
            },
            "confidence": 0.7
        }

    flow_composite = flow_data.get("composite", 0.0)
    result["flow_signal"] = {
        "composite": flow_composite,
        "layer_signals": flow_data.get("layer_signals", {}),
        "confidence": flow_data.get("confidence", 0.5)
    }

    print(f"  资金流信号：{flow_composite:+.4f}")
    print(f"  置信度：{flow_data.get('confidence', 0.5):.2f}")

    # ==========================================================================
    # Step 3: 信号融合
    # ==========================================================================
    print("\n[STEP 3] 执行信号融合...")

    fused_result = fuse_signals(
        news_result["sentiment"],
        flow_composite,
        market_state="default"  # 简化：使用默认状态
    )

    result["fused_signal"] = fused_result

    print(f"  融合信号：{fused_result['fused_signal']:+.4f}")
    print(f"  权重配置：news={fused_result['news_weight']:.2f}, flow={fused_result['flow_weight']:.2f}")
    print(f"  冲突标记：{fused_result['conflict_flag']}")
    print(f"  建议操作：{fused_result['recommendation']}")

    # ==========================================================================
    # Step 4: 保存结果
    # ==========================================================================
    print("\n[STEP 4] 保存融合结果...")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    output_file = OUTPUT_DIR / f"signal_fusion_{ts}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  已保存：{output_file}")

    # ==========================================================================
    # 输出摘要
    # ==========================================================================
    print("\n" + "=" * 60)
    print("信号融合完成!")
    print("=" * 60)

    print(f"""
┌─────────────────────────────────────────────────────┐
│              信号融合结果摘要                         │
├─────────────────────────────────────────────────────┤
│  新闻情感 (News):     {news_result['sentiment']:+.4f}                    │
│  资金流 (Flow):       {flow_composite:+.4f}                    │
├─────────────────────────────────────────────────────┤
│  融合信号 (Fused):    {fused_result['fused_signal']:+.4f}                    │
│  建议操作:            {fused_result['recommendation']:<15}          │
├─────────────────────────────────────────────────────┤
│  新闻权重:            {fused_result['news_weight']:.2f}                      │
│  资金流权重：{fused_result['flow_weight']:.2f}                      │
│  信号冲突：{str(fused_result['conflict_flag']):<10}                        │
└─────────────────────────────────────────────────────┘
""")

    return result

# =============================================================================
# 命令行入口
# =============================================================================

if __name__ == "__main__":
    import sys

    flow_file = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_signal_fusion(flow_file)
