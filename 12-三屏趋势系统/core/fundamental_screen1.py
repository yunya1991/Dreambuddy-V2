"""三屏趋势系统 — 第一屏基本面分析模块（Path B 核心算法）

双路径基本面架构：
    Path A (AI驱动)：通过研报系统获取基本面方向（engine.py 的 fetch_fundamental_data）
    Path B (算法驱动)：本模块实现，纯代码 + Tavily API，不依赖 AI

Path B 的 7 维分析框架：
    A. 技术维度 (40%)    → 已由 SCREEN1_INDICATORS 实现，此模块不重复
    B. 减半周期 (15%)    → 纯代码可计算，基于 BTC 减半时间表
    C. 矿工经济 (15%)    → Tavily 搜索 + 算法评分（Puell Multiple, Hashrate 等）
    D. 链上估值 (15%)    → Tavily 搜索 + 算法评分（MVRV, SOPR, NUPL）
    E. 宏观金融 (10%)    → Tavily 搜索 + 算法评分（DXY, 10Y, Fed Rate）
    F. 跨市场周期 (5%)   → Tavily 搜索 + 算法评分（Risk-On/Off, Gold, S&P）

数据源优先级：
    1. Tavily API 实时搜索（主数据源，freshness_days=1）
    2. 6-TRADING annotation JSON（回退，freshness_days=7）
    3. 纯代码计算（维度 B，无外部依赖）

回退策略：
    - 每个维度都有 available 标志
    - 不可用的维度不参与加权，权重重新归一化到可用维度
    - 如果所有基本面维度都不可用 → 返回 None，调用方回退到纯技术分析
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List


# ── BTC 减半时间表 ──
BTC_HALVING_DATES = [
    {"date": "2012-11-28", "block": 210000, "reward_before": 50, "reward_after": 25},
    {"date": "2016-07-09", "block": 420000, "reward_before": 25, "reward_after": 12.5},
    {"date": "2020-05-11", "block": 630000, "reward_before": 12.5, "reward_after": 6.25},
    {"date": "2024-04-20", "block": 840000, "reward_before": 6.25, "reward_after": 3.125},
    {"date": "2028-04-19", "block": 1050000, "reward_before": 3.125, "reward_after": 1.5625},  # 预估
]

# 7 阶段周期评分体系（来自 6-TRADING/skills/screen1/screen1-halving-cycle.md）
HALVING_STAGES = [
    # (天数范围起始, 天数范围结束, 基线评分, 信号, 阶段名)
    (-360, 0,      +5,  "NEUTRAL", "减半前积累"),
    (0,    180,    +15, "BULL",    "供给冲击初期"),
    (180,  360,    +10, "BULL",    "价格发现期"),
    (360,  540,    +5,  "NEUTRAL", "顶部窗口"),
    (540,  720,    -10, "BEAR",    "熊市确认"),
    (720,  1080,   -15, "BEAR",    "去库存期"),
    (1080, 999999, +5,  "NEUTRAL", "下一轮积累"),
]

# 7 维权重配置（来自 6-TRADING strategy-type.json）
DIMENSION_WEIGHTS = {
    "A_tech":        0.40,  # 技术维度（外部已计算，此模块不重复）
    "B_halving":     0.15,  # 减半周期
    "C_miner":       0.15,  # 矿工经济
    "D_onchain":     0.15,  # 链上估值
    "E_macro":       0.10,  # 宏观金融
    "F_cross_market": 0.05, # 跨市场周期
}

# annotation 文件搜索路径
ANNOTATION_PATHS = [
    os.path.join(os.path.dirname(__file__), "..", "..", "6-TRADING"),
    os.path.expanduser("~/WorkBuddy/dreambuddy-v2/6-TRADING"),
    "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING",
]


def calc_halving_cycle(current_date: Optional[datetime] = None) -> dict:
    """
    维度 B：减半周期分析（纯代码可计算）

    基于 BTC 4 年减半周期的 7 阶段评分体系。
    来源：6-TRADING/skills/screen1/screen1-halving-cycle.md

    参数:
        current_date: 当前日期，默认 today()

    返回:
        {
            "available": True,
            "dimension": "B_halving_cycle",
            "weight": 0.15,
            "score": int,           # 基线评分
            "signal": "BULL"/"BEAR"/"NEUTRAL",
            "stage": str,            # 阶段名
            "days_since_halving": int,
            "halving_date": str,
            "reasoning": str,
        }
    """
    if current_date is None:
        current_date = datetime.now()

    # 找到最近一次已发生的减半
    latest_halving = None
    next_halving = None
    for i, h in enumerate(BTC_HALVING_DATES):
        h_date = datetime.strptime(h["date"], "%Y-%m-%d")
        if h_date <= current_date:
            latest_halving = h
        else:
            next_halving = h
            break

    if latest_halving is None:
        return {
            "available": False,
            "dimension": "B_halving_cycle",
            "weight": 0.15,
            "score": 0,
            "signal": "NEUTRAL",
            "reasoning": "减半周期数据不可用",
        }

    halving_date = datetime.strptime(latest_halving["date"], "%Y-%m-%d")
    days_since = (current_date - halving_date).days

    # 确定当前阶段
    stage_info = None
    for start, end, score, signal, name in HALVING_STAGES:
        if start <= days_since < end:
            stage_info = (score, signal, name)
            break

    if stage_info is None:
        stage_info = (+5, "NEUTRAL", "下一轮积累")

    score, signal, stage_name = stage_info

    reasoning = (
        f"距{latest_halving['date']}减半{days_since}天，"
        f"处于「{stage_name}」阶段，基线评分{score}，信号{signal}"
    )

    return {
        "available": True,
        "dimension": "B_halving_cycle",
        "weight": 0.15,
        "score": score,
        "signal": signal,
        "stage": stage_name,
        "days_since_halving": days_since,
        "halving_date": latest_halving["date"],
        "next_halving_date": next_halving["date"] if next_halving else None,
        "reasoning": reasoning,
    }


def load_annotation_dimension(dim_name: str, annotation_file: str) -> dict:
    """
    从 6-TRADING 的 annotation JSON 文件加载维度数据

    参数:
        dim_name: 维度名（如 "C_miner"）
        annotation_file: annotation 文件名（如 "screen1_miner_annotation.json"）

    返回:
        维度字典，包含 available/score/signal 等字段
    """
    for base_path in ANNOTATION_PATHS:
        filepath = os.path.join(base_path, annotation_file)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 检查数据新鲜度
                generated_at = data.get("generated_at", "")
                freshness_days = data.get("freshness_days", 7)
                if generated_at:
                    try:
                        gen_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                        age_days = (datetime.now(gen_dt.tzinfo) - gen_dt).days
                        if age_days > freshness_days:
                            return {
                                "available": False,
                                "dimension": dim_name,
                                "weight": DIMENSION_WEIGHTS.get(dim_name, 0),
                                "reasoning": f"数据已过期({age_days}天前)",
                            }
                    except (ValueError, TypeError):
                        pass  # 日期解析失败，继续使用数据

                score = data.get("score", 0)
                signal = data.get("signal", "NEUTRAL")
                reasoning = data.get("reasoning", data.get("summary", ""))

                return {
                    "available": True,
                    "dimension": dim_name,
                    "weight": DIMENSION_WEIGHTS.get(dim_name, 0),
                    "score": score,
                    "signal": signal,
                    "reasoning": reasoning,
                    "source": filepath,
                    "generated_at": generated_at,
                }
            except (json.JSONDecodeError, IOError):
                continue

    return {
        "available": False,
        "dimension": dim_name,
        "weight": DIMENSION_WEIGHTS.get(dim_name, 0),
        "reasoning": "annotation 文件不存在",
    }


def _try_tavily_dimensions() -> Dict[str, dict]:
    """
    尝试通过 Tavily API 获取 4 个基本面维度数据

    返回:
        {"C_miner": {...}, "D_onchain": {...}, "E_macro": {...}, "F_cross_market": {...}}
        Tavily 不可用时返回空 dict，调用方回退到 annotation
    """
    try:
        # 优先相对导入（包内），回退到绝对导入
        try:
            from ..data.tavily_data import fetch_all_tavily_dimensions
        except (ImportError, ValueError):
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from data.tavily_data import fetch_all_tavily_dimensions

        return fetch_all_tavily_dimensions()
    except Exception:
        return {}


def calc_fundamental_screen1(current_date: Optional[datetime] = None) -> Optional[dict]:
    """
    第一屏基本面 7 维分析（不含技术维度 A，A 由外部 SCREEN1_INDICATORS 计算）

    Path B 核心入口：纯算法驱动，通过 Tavily API 获取实时基本面数据。

    流程：
    1. 维度 B（减半周期）— 纯代码计算
    2. 维度 C/D/E/F — 优先 Tavily API 实时搜索，回退到 annotation 文件
    3. 加权融合可用维度（权重归一化）
    4. 若无可用基本面维度 → 返回 None（调用方回退到纯技术分析）

    参数:
        current_date: 当前日期

    返回:
        {
            "available": bool,             # 是否有可用的基本面维度
            "direction": "BULL"/"BEAR"/"NEUTRAL",
            "score": float,                # 加权总分
            "confidence": 0-100,
            "dimensions": {dim_name: {...}},
            "data_source": str,            # "tavily" / "annotation" / "mixed"
            "fallback_reason": str,        # 如果 available=False，说明原因
        }
    """
    # 维度 B：减半周期（纯代码）
    dim_b = calc_halving_cycle(current_date)

    # 维度 C/D/E/F：优先 Tavily API，回退到 annotation
    tavily_dims = _try_tavily_dimensions()

    dim_c = tavily_dims.get("C_miner") or load_annotation_dimension("C_miner", "screen1_miner_annotation.json")
    dim_d = tavily_dims.get("D_onchain") or load_annotation_dimension("D_onchain", "screen1_onchain_annotation.json")
    dim_e = tavily_dims.get("E_macro") or load_annotation_dimension("E_macro", "screen1_macro_annotation.json")
    dim_f = tavily_dims.get("F_cross_market") or load_annotation_dimension("F_cross_market", "screen1_cross_market_annotation.json")

    all_dims = {"B_halving": dim_b, "C_miner": dim_c, "D_onchain": dim_d, "E_macro": dim_e, "F_cross_market": dim_f}

    # 统计数据源
    tavily_count = sum(1 for v in all_dims.values() if v.get("source") == "tavily_api")
    data_source = "tavily" if tavily_count >= 2 else ("mixed" if tavily_count >= 1 else "annotation")

    # 筛选可用维度
    available_dims = {k: v for k, v in all_dims.items() if v.get("available", False)}

    if not available_dims:
        return {
            "available": False,
            "direction": "NEUTRAL",
            "score": 0.0,
            "confidence": 0.0,
            "dimensions": all_dims,
            "fallback_reason": "所有基本面维度均不可用，回退到纯技术分析",
        }

    # 权重归一化（仅可用维度）
    total_weight = sum(v["weight"] for v in available_dims.values())

    # 加权评分
    weighted_score = 0.0
    bull_weight = 0.0
    bear_weight = 0.0

    for dim_name, dim_data in available_dims.items():
        weight = dim_data["weight"] / total_weight  # 归一化
        score = dim_data.get("score", 0)
        signal = dim_data.get("signal", "NEUTRAL")

        weighted_score += score * weight

        if signal == "BULL":
            bull_weight += weight
        elif signal == "BEAR":
            bear_weight += weight

    # 方向判定
    if bull_weight > bear_weight and bull_weight > 0.4:
        direction = "BULL"
    elif bear_weight > bull_weight and bear_weight > 0.4:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"

    # 置信度：基于可用维度数量和一致性
    n_available = len(available_dims)
    n_total = len(all_dims)
    availability_ratio = n_available / n_total

    # 方向一致性
    consistent_weight = max(bull_weight, bear_weight)
    consistency = consistent_weight / total_weight if total_weight > 0 else 0

    confidence = min(100.0, abs(weighted_score) * 2 + consistency * 50 + availability_ratio * 20)

    return {
        "available": True,
        "direction": direction,
        "score": round(weighted_score, 2),
        "confidence": round(confidence, 1),
        "dimensions": all_dims,
        "available_count": n_available,
        "total_count": n_total,
        "bull_weight": round(bull_weight / total_weight, 3),
        "bear_weight": round(bear_weight / total_weight, 3),
        "data_source": data_source,
    }


def fuse_tech_fundamental(
    tech_direction: str,
    tech_confidence: float,
    fundamental: Optional[dict],
    tech_weight: float = 0.6,
    fundamental_weight: float = 0.4,
) -> dict:
    """
    融合技术分析和基本面分析的周线方向

    策略：
    1. 基本面不可用 → 直接返回技术分析结果
    2. 两者同向 → 增强 confidence
    3. 两者反向 → 降低 confidence，技术优先但标注冲突
    4. 基本面中性 → 技术为主，轻微降权

    参数:
        tech_direction: 技术分析方向 "BULL"/"BEAR"/"NEUTRAL"
        tech_confidence: 技术分析置信度 0-100
        fundamental: calc_fundamental_screen1() 的返回值
        tech_weight: 技术权重（默认0.6）
        fundamental_weight: 基本面权重（默认0.4）

    返回:
        {
            "direction": str,          # 融合后方向
            "confidence": float,        # 融合后置信度
            "tech_direction": str,      # 原技术方向
            "tech_confidence": float,   # 原技术置信度
            "fundamental_direction": str,
            "fundamental_confidence": float,
            "fundamental_available": bool,
            "conflict": bool,           # 技术与基本面是否冲突
            "fused": bool,              # 是否进行了融合
        }
    """
    if fundamental is None or not fundamental.get("available", False):
        return {
            "direction": tech_direction,
            "confidence": tech_confidence,
            "tech_direction": tech_direction,
            "tech_confidence": tech_confidence,
            "fundamental_direction": "NEUTRAL",
            "fundamental_confidence": 0.0,
            "fundamental_available": False,
            "conflict": False,
            "fused": False,
            "fallback_reason": fundamental.get("fallback_reason", "基本面不可用") if fundamental else "基本面未提供",
        }

    fund_direction = fundamental["direction"]
    fund_confidence = fundamental["confidence"]

    # 两者同向 → 增强
    if tech_direction == fund_direction and tech_direction != "NEUTRAL":
        fused_confidence = min(100, tech_confidence * (1 + fundamental_weight * 0.3))
        return {
            "direction": tech_direction,
            "confidence": round(fused_confidence, 1),
            "tech_direction": tech_direction,
            "tech_confidence": tech_confidence,
            "fundamental_direction": fund_direction,
            "fundamental_confidence": fund_confidence,
            "fundamental_available": True,
            "conflict": False,
            "fused": True,
        }

    # 两者反向 → 降低 confidence，技术优先
    if tech_direction != "NEUTRAL" and fund_direction != "NEUTRAL" and tech_direction != fund_direction:
        penalty = fundamental_weight * 0.4
        fused_confidence = max(0, tech_confidence * (1 - penalty))
        return {
            "direction": tech_direction,  # 技术优先
            "confidence": round(fused_confidence, 1),
            "tech_direction": tech_direction,
            "tech_confidence": tech_confidence,
            "fundamental_direction": fund_direction,
            "fundamental_confidence": fund_confidence,
            "fundamental_available": True,
            "conflict": True,
            "fused": True,
        }

    # 基本面中性 → 技术为主，轻微降权
    if fund_direction == "NEUTRAL" and tech_direction != "NEUTRAL":
        fused_confidence = tech_confidence * (1 - fundamental_weight * 0.1)
        return {
            "direction": tech_direction,
            "confidence": round(fused_confidence, 1),
            "tech_direction": tech_direction,
            "tech_confidence": tech_confidence,
            "fundamental_direction": fund_direction,
            "fundamental_confidence": fund_confidence,
            "fundamental_available": True,
            "conflict": False,
            "fused": True,
        }

    # 技术中性，基本面有方向 → 基本面提供方向参考但不覆盖
    if tech_direction == "NEUTRAL" and fund_direction != "NEUTRAL":
        return {
            "direction": tech_direction,  # 仍保持中性，但标注基本面方向
            "confidence": tech_confidence,
            "tech_direction": tech_direction,
            "tech_confidence": tech_confidence,
            "fundamental_direction": fund_direction,
            "fundamental_confidence": fund_confidence,
            "fundamental_available": True,
            "conflict": False,
            "fused": True,
        }

    # 都中性
    return {
        "direction": "NEUTRAL",
        "confidence": tech_confidence,
        "tech_direction": tech_direction,
        "tech_confidence": tech_confidence,
        "fundamental_direction": fund_direction,
        "fundamental_confidence": fund_confidence,
        "fundamental_available": True,
        "conflict": False,
        "fused": True,
    }
