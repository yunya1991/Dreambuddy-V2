"""
审计标准模块（P0-3 改进）

P0-3 硬约束: Sharpe 为负时不应标记 HEALTHY

修正 model_validation_20260915_0011.md 中的错误标准:
  原标准（错误）: Sharpe=-0.02 → HEALTHY ✅
  新标准（正确）: Sharpe<0 → WARNING ⚠️（不是 HEALTHY）
                Sharpe<-0.5 → CRITICAL 🔴

提供 1 个枚举 + 1 个分类函数，供后续审计脚本/报告统一引用。
"""
from __future__ import annotations

import logging
import math
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HealthLevel(str, Enum):
    """审计健康度等级（从优到劣）."""
    HEALTHY = "HEALTHY"
    INITIAL = "INITIAL"        # 初始态（样本不足/未触发）
    WARNING = "WARNING"        # 警告（含 Sharpe≤0）
    CRITICAL = "CRITICAL"      # 严重（Sharpe<-0.5 或样本严重不足）
    UNKNOWN = "UNKNOWN"        # 未知（字段缺失）


# 审计阈值（P0-3 硬约束）
MIN_HEALTHY_SHARPE = 0.5          # Sharpe≥0.5 才能 HEALTHY
MIN_HEALTHY_SAMPLE_COUNT = 2000  # 样本≥2000 才能 HEALTHY
MIN_INITIAL_SAMPLE_COUNT = 200   # 样本≥200 才脱离 UNKNOWN
CRITICAL_SHARPE = -0.5           # Sharpe<-0.5 → CRITICAL
CRITICAL_SAMPLE_COUNT = 100     # 样本<100 → CRITICAL


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        if math.isfinite(v):
            return v
    except (TypeError, ValueError):
        pass
    return default


def classify_shadow_health(stats: dict[str, Any]) -> HealthLevel:
    """分类 ShadowRL 健康度（P0-3 硬约束）.

    规则（优先级从高到低）:
      1. 字段缺失 → UNKNOWN
      2. sample_count < 100 → CRITICAL
      3. sample_count < 200 → INITIAL
      4. sharpe < -0.5 → CRITICAL
      5. sharpe < 0 → WARNING          ← P0-3 核心：负 Sharpe 不 HEALTHY
      6. sharpe ≥ 0.5 and mean_reward > 0 and sample_count ≥ 2000 → HEALTHY
      7. 其他 → WARNING

    Args:
        stats: {"sharpe": float, "mean_reward": float, "sample_count": int}

    Returns:
        HealthLevel 枚举
    """
    # 1. 字段缺失 → UNKNOWN (FAIL-OPEN)
    if not stats or "sharpe" not in stats or "sample_count" not in stats:
        return HealthLevel.UNKNOWN

    sharpe = _safe_float(stats.get("sharpe"))
    sample_count = int(stats.get("sample_count", 0))
    mean_reward = _safe_float(stats.get("mean_reward"))

    # 2. 样本严重不足 → CRITICAL
    if sample_count < CRITICAL_SAMPLE_COUNT:
        return HealthLevel.CRITICAL

    # 3. 样本不足 → INITIAL
    if sample_count < MIN_INITIAL_SAMPLE_COUNT:
        return HealthLevel.INITIAL

    # 4. Sharpe 严重负 → CRITICAL
    if sharpe < CRITICAL_SHARPE:
        return HealthLevel.CRITICAL

    # 5. P0-3 核心: Sharpe 负值 → WARNING（不 HEALTHY）
    if sharpe < 0:
        return HealthLevel.WARNING

    # 6. 全部满足 → HEALTHY
    if (sharpe >= MIN_HEALTHY_SHARPE
            and mean_reward > 0
            and sample_count >= MIN_HEALTHY_SAMPLE_COUNT):
        return HealthLevel.HEALTHY

    # 7. 边界态 → WARNING
    return HealthLevel.WARNING
