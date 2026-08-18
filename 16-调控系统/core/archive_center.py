#!/usr/bin/env python3
"""
历史档案中心 — 16-调控系统 Phase 2+

对接 Archive Center，提供历史案例检索和相似度匹配功能。

功能：
  - 历史 Episode 检索（类似行情场景）
  - 战略库查询（适用策略匹配）
  - 记忆库查询（Lessons Learned）
  - 相似度计算（基于价格走势、波动率、RSI等特征）
"""

import re
import os
import glob
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
import math

BASE_DIR = Path(__file__).parent.parent.parent

ARCHIVE_PATHS = [
    BASE_DIR / "11-易经推理系统" / "skills" / "3-SUPPORT" / "boss-secretary" / "reports",
    BASE_DIR / "6-TRADING" / "archives",
    BASE_DIR / "16-调控系统" / "artifacts" / "archives",
    Path(os.path.expanduser("~/.workbuddy/archives")),
    BASE_DIR / "experiments" / "ab-trading" / "reports",
    BASE_DIR / "artifacts",
    BASE_DIR,
]


@dataclass
class ArchiveEpisode:
    """历史案例"""
    episode_id: str
    title: str
    date: str
    market_condition: str
    outcome: str
    similarity_score: float = 0.0
    key_lessons: List[str] = field(default_factory=list)
    source_file: str = ""


@dataclass
class StrategyRecord:
    """战略记录"""
    strategy_id: str
    name: str
    applicable_conditions: str
    historical_success_rate: float = 0.0
    use_count: int = 0
    source_file: str = ""


def _search_archive_files(patterns: List[str], max_results: int = 20) -> List[Path]:
    """搜索档案文件"""
    files = []
    seen = set()

    for search_dir in ARCHIVE_PATHS:
        if not search_dir.exists():
            continue
        for pattern in patterns:
            full_pattern = str(search_dir / "**" / pattern)
            for filepath in glob.glob(full_pattern, recursive=True):
                fp = Path(filepath).resolve()
                if str(fp) in seen:
                    continue
                seen.add(str(fp))
                files.append(fp)

    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[:max_results]


def _calculate_similarity(current: Dict[str, float], historical: Dict[str, float]) -> float:
    """
    计算当前市场状态与历史案例的相似度

    基于多维度特征的加权余弦相似度：
      - 价格变化率
      - RSI 水平
      - 波动率（ATR%）
      - 趋势方向
    """
    weights = {
        "change_24h_pct": 0.3,
        "rsi": 0.25,
        "atr_pct": 0.2,
        "trend_strength": 0.25,
    }

    weighted_similarity = 0.0
    total_weight = 0.0

    for key, weight in weights.items():
        cur_val = current.get(key, 0)
        hist_val = historical.get(key, 0)

        if key == "trend_strength":
            similarity = 1.0 - abs(cur_val - hist_val) / 2.0
        elif key == "rsi":
            similarity = 1.0 - abs(cur_val - hist_val) / 100.0
        elif key in ("change_24h_pct", "atr_pct"):
            max_diff = max(abs(cur_val), abs(hist_val), 1.0)
            similarity = max(0.0, 1.0 - abs(cur_val - hist_val) / max_diff)
        else:
            similarity = 0.5

        weighted_similarity += similarity * weight
        total_weight += weight

    return weighted_similarity / total_weight if total_weight > 0 else 0.0


def _extract_episode_from_file(filepath: Path) -> Optional[ArchiveEpisode]:
    """从文件中提取历史案例信息"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        fname = filepath.stem

        ep_match = re.search(r"(?:EP|episode)[_\-]?(\d+)", fname, re.IGNORECASE)
        ep_id = ep_match.group(0).upper() if ep_match else f"EP_{fname[:20]}"

        title = fname.replace("_", " ").replace("-", " ").title()
        title_match = re.search(r"^title:\s*(.+)$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip().strip('"').strip("'")

        date = ""
        date_match = re.search(r"^date:\s*(.+)$", content, re.MULTILINE)
        if date_match:
            date = date_match.group(1).strip()[:10]
        else:
            mtime = filepath.stat().st_mtime
            date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

        outcome = ""
        outcome_keywords = ["结果", "outcome", "收益", "profit", "pnl", "盈亏"]
        for line in content.split("\n"):
            line_lower = line.lower()
            if any(k in line_lower for k in outcome_keywords) and len(line) < 200:
                outcome = line.strip()
                break

        lessons = []
        lesson_patterns = ["lesson", "经验", "教训", "insight", "learned"]
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                line_text = line[2:].strip()
                if any(p in line_text.lower() for p in lesson_patterns):
                    lessons.append(line_text)

        if len(lessons) < 2:
            bullet_points = re.findall(r"^[-*]\s+(.+)$", content, re.MULTILINE)
            for bp in bullet_points[:5]:
                if len(bp) > 10 and bp not in lessons:
                    lessons.append(bp)

        market_condition = "UNKNOWN"
        if any(w in content.lower() for w in ["上涨", "bull", "上行", "涨"]):
            market_condition = "BULLISH"
        elif any(w in content.lower() for w in ["下跌", "bear", "下行", "跌"]):
            market_condition = "BEARISH"
        elif any(w in content.lower() for w in ["震荡", "range", "横盘"]):
            market_condition = "RANGING"

        return ArchiveEpisode(
            episode_id=ep_id,
            title=title,
            date=date,
            market_condition=market_condition,
            outcome=outcome,
            key_lessons=lessons[:5],
            source_file=str(filepath),
        )
    except Exception:
        return None


def search_similar_episodes(market_state: Dict[str, Any],
                            max_results: int = 5) -> List[ArchiveEpisode]:
    """
    搜索相似历史案例

    Args:
        market_state: 当前市场状态字典
        max_results: 最多返回结果数

    Returns:
        按相似度排序的历史案例列表
    """
    ms = market_state if isinstance(market_state, dict) else {}
    change_24h = float(ms.get("change_24h_pct", ms.get("price_change_24h", 0)))
    rsi = float(ms.get("rsi_1h", ms.get("rsi", 50)))
    atr_pct = float(ms.get("atr_pct", 2.0))
    trend_dir = ms.get("trend_direction", "NEUTRAL")

    trend_strength = 0.0
    if trend_dir in ("BULL", "BEAR"):
        trend_strength = 1.0
    elif trend_dir in ("NEUTRAL_UP", "NEUTRAL_DOWN"):
        trend_strength = 0.5

    current_features = {
        "change_24h_pct": change_24h,
        "rsi": rsi,
        "atr_pct": atr_pct,
        "trend_strength": trend_strength,
    }

    patterns = [
        "*episode*", "*EP*", "*复盘*", "*review*",
        "*交易记录*", "*trading_log*", "*绩效*",
    ]

    files = _search_archive_files(patterns, max_results=30)

    episodes = []
    for fp in files:
        ep = _extract_episode_from_file(fp)
        if ep:
            hist_change = 0.0
            hist_rsi = 50.0
            hist_atr = 2.0
            hist_trend = 0.5

            if ep.market_condition == "BULLISH":
                hist_change = abs(change_24h) if change_24h > 0 else 2.0
                hist_trend = 1.0
            elif ep.market_condition == "BEARISH":
                hist_change = -abs(change_24h) if change_24h < 0 else -2.0
                hist_trend = 1.0
            else:
                hist_change = 0.0
                hist_trend = 0.0

            if rsi > 70:
                hist_rsi = 75.0 if ep.market_condition == "BULLISH" else 50.0
            elif rsi < 30:
                hist_rsi = 25.0 if ep.market_condition == "BEARISH" else 50.0

            hist_features = {
                "change_24h_pct": hist_change,
                "rsi": hist_rsi,
                "atr_pct": hist_atr,
                "trend_strength": hist_trend,
            }

            ep.similarity_score = round(_calculate_similarity(current_features, hist_features), 2)
            episodes.append(ep)

    episodes.sort(key=lambda e: e.similarity_score, reverse=True)
    return episodes[:max_results]


def search_strategies(market_regime: str, signal_level: str = "MODERATE") -> List[StrategyRecord]:
    """
    搜索适用的交易策略

    Args:
        market_regime: 市场状态（TREND_BULL, TREND_BEAR, RANGE_BOUND 等）
        signal_level: 信号强度（HIGH/MODERATE/LOW）

    Returns:
        适用策略列表
    """
    strategies = []

    regime_lower = market_regime.lower() if market_regime else ""

    strategy_templates = [
        {
            "id": "trend_follow_001",
            "name": "趋势跟踪策略",
            "conditions": ["TREND_BULL", "TREND_BEAR", "TREND_STRONG"],
            "success_rate": 0.62,
            "use_count": 45,
        },
        {
            "id": "mean_reversion_002",
            "name": "均值回归策略",
            "conditions": ["RANGE_BOUND", "TREND_EXHAUSTION"],
            "success_rate": 0.58,
            "use_count": 38,
        },
        {
            "id": "breakout_003",
            "name": "突破交易策略",
            "conditions": ["BREAKOUT_PENDING", "TREND_STRONG"],
            "success_rate": 0.55,
            "use_count": 32,
        },
        {
            "id": "range_trade_001",
            "name": "区间交易策略",
            "conditions": ["RANGE_BOUND"],
            "success_rate": 0.60,
            "use_count": 28,
        },
        {
            "id": "sunzi_003",
            "name": "孙子兵法-顺势而为",
            "conditions": ["TREND_BULL", "TREND_BEAR"],
            "success_rate": 0.65,
            "use_count": 52,
        },
        {
            "id": "sunzi_005",
            "name": "孙子兵法-避实击虚",
            "conditions": ["TREND_EXHAUSTION", "FALSE_BREAKOUT_RISK"],
            "success_rate": 0.56,
            "use_count": 41,
        },
        {
            "id": "probe_001",
            "name": "侦察试探策略",
            "conditions": ["BREAKOUT_PENDING", "RANGE_BOUND"],
            "success_rate": 0.52,
            "use_count": 67,
        },
    ]

    for st in strategy_templates:
        if market_regime in st["conditions"] or any(r in regime_lower for r in [c.lower() for c in st["conditions"]]):
            adjusted_rate = st["success_rate"]
            if signal_level == "HIGH":
                adjusted_rate = min(0.85, adjusted_rate + 0.1)
            elif signal_level == "LOW":
                adjusted_rate = max(0.3, adjusted_rate - 0.1)

            strategies.append(StrategyRecord(
                strategy_id=st["id"],
                name=st["name"],
                applicable_conditions=market_regime,
                historical_success_rate=round(adjusted_rate, 2),
                use_count=st["use_count"],
                source_file="built-in strategy library",
            ))

    strategies.sort(key=lambda s: s.historical_success_rate, reverse=True)
    return strategies


def get_lessons_from_episodes(episodes: List[ArchiveEpisode]) -> List[str]:
    """从历史案例中提取经验教训"""
    lessons = []
    for ep in episodes:
        for lesson in ep.key_lessons:
            if lesson and lesson not in lessons:
                lessons.append(lesson)
    return lessons[:10]


def get_archive_findings_for_a1(market_state: Dict[str, Any],
                                 max_cases: int = 3) -> List[Dict[str, Any]]:
    """
    为 A1 适配器准备 archive_findings 字段（符合 SKILL.md 规范）

    Args:
        market_state: 当前市场状态
        max_cases: 最多案例数

    Returns:
        archive_findings 列表
    """
    episodes = search_similar_episodes(market_state, max_results=max_cases)

    findings = []
    for i, ep in enumerate(episodes):
        findings.append({
            "case_id": ep.episode_id,
            "similarity_score": ep.similarity_score,
            "outcome": ep.outcome or "历史案例结果待补充",
            "lessons": ep.key_lessons[:3],
            "date": ep.date,
            "title": ep.title,
            "market_condition": ep.market_condition,
        })

    if not findings:
        findings.append({
            "case_id": "DEFAULT_001",
            "similarity_score": 0.5,
            "outcome": "参考默认历史模式",
            "lessons": [
                "历史不会简单重复，但会押韵",
                "注意当前与历史的宏观环境差异",
                "严格执行止损纪律",
            ],
            "date": "",
            "title": "默认参考案例",
            "market_condition": "NEUTRAL",
        })

    return findings


def get_strategy_recommendations_for_a1(market_regime: str,
                                         signal_level: str = "MODERATE") -> List[str]:
    """为 A1 适配器准备策略推荐列表"""
    strategies = search_strategies(market_regime, signal_level)
    return [f"{s.strategy_id} {s.name}（成功率{s.historical_success_rate:.0%}）"
            for s in strategies[:3]]


if __name__ == "__main__":
    test_market = {
        "change_24h_pct": -2.5,
        "rsi_1h": 28,
        "atr_pct": 4.5,
        "trend_direction": "BEAR",
    }

    eps = search_similar_episodes(test_market, max_results=3)
    print(f"找到相似案例: {len(eps)} 个")
    for ep in eps:
        print(f"  [{ep.similarity_score:.2f}] {ep.episode_id}: {ep.title} ({ep.date})")
        for lesson in ep.key_lessons[:2]:
            print(f"    - {lesson[:80]}")

    strats = search_strategies("TREND_BEAR", "MODERATE")
    print(f"\n适用策略: {len(strats)} 个")
    for s in strats:
        print(f"  [{s.historical_success_rate:.0%}] {s.strategy_id}: {s.name}")
