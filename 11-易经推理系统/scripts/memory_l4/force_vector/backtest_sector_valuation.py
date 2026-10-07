"""TDD-SVC-004: waterline >= 80 离场信号回测验证。

> 版本: v1.0 (TDD-SVC-004 GREEN)
> SPEC: docs/superpowers/specs/2026-10-07-sector-valuation-comparison-spec.md §8.2 §10

假设（SPEC §10 TDD-SVC-004）：
  waterline >= 80 时赛道未来 30d 收益率显著为负，可作为离场信号

test_assertion: assert backtest_waterline_exit(80)['avg_return_30d'] < 0

设计：
  1. 纯函数 compute_backtest_stats(triggered_returns) — 从收益率列表计算统计
  2. 数据获取 _fetch_historical_waterlines_with_returns(db_path) — 历史水位 + 30d 收益率
     （占位实现，真实回测需从 db 查历史 chart 数据计算每个日期的 waterline）
  3. 主函数 backtest_waterline_exit(threshold, db_path) — 遍历历史，过滤触发点

铁律（SPEC §0.2）：
  R4 FAIL-OPEN：数据不足不触发信号
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from force_vector.coin_fundamental_crypto import DEFAULT_DB_PATH  # noqa: E402


# ---------------------------------------------------------------------------
# 纯函数：从触发的收益率列表计算统计
# ---------------------------------------------------------------------------

def compute_backtest_stats(triggered_returns: List[float]) -> Dict[str, object]:
    """从触发的收益率列表计算回测统计。

    Args:
        triggered_returns: 触发点后 30d 的收益率列表（如 [-0.10, -0.15]）

    Returns:
        Dict 包含：
          - avg_return_30d: 平均 30d 收益率
          - win_rate: 正收益率占比 [0, 1]
          - sample_count: 样本数
          - max_drawdown: 最大单点回撤（最小收益率）
    """
    if not triggered_returns:
        return {
            "avg_return_30d": 0.0,
            "win_rate": 0.0,
            "sample_count": 0,
            "max_drawdown": 0.0,
        }

    returns = [float(r) for r in triggered_returns]
    n = len(returns)
    avg = sum(returns) / n
    wins = sum(1 for r in returns if r > 0)
    max_dd = min(returns) if returns else 0.0

    return {
        "avg_return_30d": avg,
        "win_rate": wins / n,
        "sample_count": n,
        "max_drawdown": max_dd,
    }


# ---------------------------------------------------------------------------
# 数据获取：历史 waterline + 30d 收益率（占位，真实实现需查 db 历史数据）
# ---------------------------------------------------------------------------

def _fetch_historical_waterlines_with_returns(db_path: str) -> List[Dict[str, object]]:
    """获取历史 waterline 序列 + 对应 30d 后收益率。

    占位实现：真实实现需要：
      1. 遍历历史日期（如过去 365 天，按周采样）
      2. 对每个日期，计算赛道 waterline（需历史 MC/Fees 百分位）
      3. 计算该日期后 30d 的赛道平均收益率
      4. 返回 [{"date": ..., "waterline": ..., "return_30d": ...}, ...]

    当前返回空列表（FAIL-OPEN），单元测试用 mock 验证逻辑。
    真实回测留给后续阶段接入历史数据采集器。

    Returns:
        List of {"date": str, "waterline": float, "return_30d": float}
    """
    if not db_path or not os.path.exists(db_path):
        return []

    # TODO: 真实实现 — 从 data_center.db 查历史 chart 数据，计算每个采样点的 waterline
    # 需要历史 MC/Fees 序列，按周/月采样，计算纵向百分位 → waterline
    # 当前返回空列表，FAIL-OPEN
    return []


# ---------------------------------------------------------------------------
# 主函数：backtest_waterline_exit
# ---------------------------------------------------------------------------

def backtest_waterline_exit(
    threshold: float = 80.0,
    db_path: Optional[str] = None,
) -> Dict[str, object]:
    """回测 waterline >= threshold 后的 30d 收益率（SPEC §8.2 §10 TDD-SVC-004）。

    流程：
      1. 获取历史 waterline + 30d 收益率序列
      2. 过滤 waterline >= threshold 的触发点
      3. 提取触发点的 return_30d 列表
      4. 调用 compute_backtest_stats 计算统计

    Args:
        threshold: waterline 触发阈值（默认 80，SPEC §5.2 G2 离场信号）
        db_path: data_center.db 路径；None 用 DEFAULT_DB_PATH

    Returns:
        Dict 包含：
          - avg_return_30d: 触发点平均 30d 收益率
          - win_rate: 正收益率占比
          - sample_count: 触发样本数
          - max_drawdown: 最大单点回撤
          - threshold: 触发阈值
    """
    if not db_path:
        db_path = DEFAULT_DB_PATH

    try:
        history = _fetch_historical_waterlines_with_returns(db_path)

        # 过滤触发点
        triggered_returns = [
            float(entry["return_30d"])
            for entry in history
            if float(entry.get("waterline", 0)) >= threshold
        ]

        stats = compute_backtest_stats(triggered_returns)
        stats["threshold"] = threshold
        return stats
    except Exception:
        # FAIL-OPEN：任何异常 → 中性结果
        return {
            "avg_return_30d": 0.0,
            "win_rate": 0.0,
            "sample_count": 0,
            "max_drawdown": 0.0,
            "threshold": threshold,
        }


# ---------------------------------------------------------------------------
# TDD-SVC-005: waterline>=85 + 龙头转弱 + 普遍高估 → 14d 跌幅 > 5%
# SPEC §10 TDD-SVC-005 / §5.3 三重确认 AND
# ---------------------------------------------------------------------------

# 阈值（与 sector_valuation_orchestrator 一致，SPEC §5.3）
_OVERHEAT_WATERLINE_THRESHOLD = 85.0
_OVERHEAT_LEADER_MOMENTUM_THRESHOLD = -0.1   # 严格小于
_OVERHEAT_OVERVALUED_RATIO_THRESHOLD = 0.6


def compute_overheat_backtest_stats(triggered_returns: List[float]) -> Dict[str, object]:
    """从触发的 14d 收益率列表计算统计（TDD-SVC-005）。

    Args:
        triggered_returns: 触发点后 14d 的收益率列表（如 [-0.10, -0.08]）

    Returns:
        Dict 包含：
          - avg_return_14d: 平均 14d 收益率
          - win_rate: 正收益率占比 [0, 1]
          - sample_count: 样本数
          - max_drawdown: 最大单点回撤（最小收益率）
    """
    if not triggered_returns:
        return {
            "avg_return_14d": 0.0,
            "win_rate": 0.0,
            "sample_count": 0,
            "max_drawdown": 0.0,
        }
    returns = [float(r) for r in triggered_returns]
    n = len(returns)
    avg = sum(returns) / n
    wins = sum(1 for r in returns if r > 0)
    max_dd = min(returns)
    return {
        "avg_return_14d": avg,
        "win_rate": wins / n,
        "sample_count": n,
        "max_drawdown": max_dd,
    }


def _fetch_historical_overheat_with_returns(db_path: str) -> List[Dict[str, object]]:
    """获取历史三重确认序列 + 14d 收益率（TDD-SVC-005）。

    占位实现：真实实现需要：
      1. 遍历历史日期（如过去 365 天，按周采样）
      2. 对每个日期，计算赛道 waterline / leader_momentum / overvalued_ratio
         （需历史 MC/Fees 序列 + 龙头价格 + 多维估值）
      3. 计算该日期后 14d 的赛道平均收益率
      4. 返回 [{"date", "waterline", "leader_momentum",
               "overvalued_ratio", "return_14d"}, ...]

    当前返回空列表（FAIL-OPEN），单元测试用 mock 验证逻辑。
    真实回测留给后续阶段接入历史数据采集器。

    Returns:
        List of {date, waterline, leader_momentum, overvalued_ratio, return_14d}
    """
    if not db_path or not os.path.exists(db_path):
        return []
    # TODO: 真实实现 — 从 data_center.db 查历史 chart 数据，
    # 计算每个采样点的三重确认 + 14d 收益率
    return []


def backtest_overheat_short(
    db_path: Optional[str] = None,
    waterline_threshold: float = _OVERHEAT_WATERLINE_THRESHOLD,
    leader_momentum_threshold: float = _OVERHEAT_LEADER_MOMENTUM_THRESHOLD,
    overvalued_ratio_threshold: float = _OVERHEAT_OVERVALUED_RATIO_THRESHOLD,
) -> Dict[str, object]:
    """回测三重确认触发后的 14d 收益率（SPEC §5.3 §10 TDD-SVC-005）。

    三重确认 AND（SPEC §5.3）：
      1. waterline >= waterline_threshold（默认 85）
      2. leader_momentum < leader_momentum_threshold（默认 -0.1，严格小于）
      3. overvalued_ratio >= overvalued_ratio_threshold（默认 0.6）

    流程：
      1. 获取历史三重确认序列 + 14d 收益率
      2. 过滤三重确认同时满足的触发点
      3. 提取触发点的 return_14d 列表
      4. 调用 compute_overheat_backtest_stats 计算统计

    Args:
        db_path: data_center.db 路径；None 用 DEFAULT_DB_PATH
        waterline_threshold: waterline 触发阈值（默认 85）
        leader_momentum_threshold: 龙头动量阈值（默认 -0.1，严格小于）
        overvalued_ratio_threshold: 高估币占比阈值（默认 0.6）

    Returns:
        Dict 包含：
          - avg_return_14d: 触发点平均 14d 收益率
          - win_rate: 正收益率占比
          - sample_count: 触发样本数
          - max_drawdown: 最大单点回撤
          - threshold: waterline 触发阈值（向后兼容键名）
    """
    if not db_path:
        db_path = DEFAULT_DB_PATH

    try:
        history = _fetch_historical_overheat_with_returns(db_path)

        triggered_returns: List[float] = []
        for entry in history:
            try:
                wl = float(entry.get("waterline", 0))
                lm = float(entry.get("leader_momentum", 0))
                ratio = float(entry.get("overvalued_ratio", 0))
            except (TypeError, ValueError):
                continue
            # 三重确认 AND（SPEC §5.3）
            if wl < waterline_threshold:
                continue
            if lm >= leader_momentum_threshold:  # 严格小于
                continue
            if ratio < overvalued_ratio_threshold:
                continue
            triggered_returns.append(float(entry.get("return_14d", 0.0)))

        stats = compute_overheat_backtest_stats(triggered_returns)
        stats["threshold"] = waterline_threshold
        return stats
    except Exception:
        # FAIL-OPEN：任何异常 → 中性结果
        return {
            "avg_return_14d": 0.0,
            "win_rate": 0.0,
            "sample_count": 0,
            "max_drawdown": 0.0,
            "threshold": waterline_threshold,
        }
