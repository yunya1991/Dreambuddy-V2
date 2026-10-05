"""
基因准入统计检验模块（P0 改进）

P0-1: 所有 promote 决策附 p 值（二项检验 H0: 胜率≤0.5）+ 效应量(Cohen's d) + 95% 置信区间
P0-2: 准入门槛 N≥30（替代 shadow_backtest.py 中的 SHADOW_MIN_SAMPLES=10）

提供 4 个统计原语 + 1 个综合决策函数：
  1. binomial_test_pvalue(wins, n, p_h0=0.5) — 单边二项检验 p 值
  2. cohens_d(pnl_values) — Cohen's d 效应量（单样本 vs 0）
  3. win_rate_ci(wins, n, conf=0.95) — Wilson score 置信区间
  4. check_promotion_with_stats(samples) — 综合统计准入决策

FAIL-OPEN: scipy/binomtest 不可用时降级为正态近似 + numpy，不 crash。
参考: dream-science-hypothesis-verification / dream-science-statistics-check SKILL。
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 scipy.stats.binomtest（可选，FAIL-OPEN）
try:
    from scipy.stats import binomtest  # type: ignore
    _SCIPY_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SCIPY_AVAILABLE = False
    logger.debug("[P0] scipy.stats.binomtest 不可用，降级为正态近似")

# P0-2 硬约束: 准入门槛从 10 提升至 30
MIN_PROMOTION_SAMPLES = 30

# 统计显著性阈值
P_VALUE_SIG = 0.05
MIN_WIN_RATE = 0.50
MIN_COHENS_D = 0.50  # 中等效应量门槛（Cohen 1988）


def _safe_int(value: Any, default: int = 0) -> int:
    """安全转 int，失败返回 default."""
    try:
        v = int(value)
        if math.isfinite(v):
            return v
    except (TypeError, ValueError):
        pass
    return default


def binomial_test_pvalue(wins: int, n: int, p_h0: float = 0.5) -> float:
    """单边二项检验 p 值（H0: 胜率 ≤ p_h0, H1: 胜率 > p_h0）.

    Args:
        wins: 成功次数
        n: 总样本数
        p_h0: 原假设胜率（默认 0.5 = 随机）

    Returns:
        p 值 [0, 1]。无效输入返回 1.0（FAIL-OPEN, 保守不拒绝）。
    """
    wins = _safe_int(wins)
    n = _safe_int(n)
    # FAIL-OPEN: 无效输入返回 1.0（保守，不 promote）
    if wins < 0 or n <= 0 or wins > n or not (0.0 < p_h0 < 1.0):
        return 1.0

    try:
        if _SCIPY_AVAILABLE:
            # scipy binomtest 默认双侧，这里取单边 (greater)
            result = binomtest(wins, n, p_h0, alternative="greater")
            return float(result.pvalue)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[P0] binomtest 失败, 降级正态近似: {exc}")

    # 正态近似 fallback: z = (p_hat - p_0) / sqrt(p_0*(1-p_0)/n)
    p_hat = wins / n
    se = math.sqrt(p_h0 * (1.0 - p_h0) / n)
    if se <= 0:
        return 1.0
    z = (p_hat - p_h0) / se
    # 单边 p = 1 - Φ(z)
    try:
        from math import erf, sqrt
        p_norm = 0.5 * (1.0 + erf(z / sqrt(2.0)))
        return float(max(0.0, min(1.0, 1.0 - p_norm)))
    except Exception:  # noqa: BLE001
        return 1.0


def cohens_d(pnl_values: list[float]) -> float:
    """单样本 Cohen's d 效应量（vs 0）.

    d = mean(pnl) / std(pnl)
    解释: |d|<0.2 小, 0.5 中, 0.8 大（Cohen 1988）

    Returns:
        Cohen's d。空/无效返回 0.0。
    """
    if not pnl_values:
        return 0.0
    try:
        arr = np.asarray(pnl_values, dtype=np.float64)
        # 过滤 NaN
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return 0.0
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1))  # 样本标准差
        if std <= 0 or not math.isfinite(std):
            return 0.0
        return mean / std
    except Exception:  # noqa: BLE001
        return 0.0


def win_rate_ci(wins: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Wilson score 置信区间（比正态近似更稳定，小样本也适用）.

    Returns:
        (lower, upper) 胜率 95% CI。无效输入返回 (0.0, 1.0)。
    """
    wins = _safe_int(wins)
    n = _safe_int(n)
    if wins < 0 or n <= 0 or wins > n or not (0.0 < conf < 1.0):
        return (0.0, 1.0)

    try:
        p_hat = wins / n
        # z_{1-α/2}: 95% → 1.96, 99% → 2.576
        z_map = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
        z = z_map.get(round(conf, 2), 1.96)
        denom = 1.0 + z * z / n
        center = (p_hat + z * z / (2 * n)) / denom
        margin = (z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))) / denom
        low = max(0.0, center - margin)
        high = min(1.0, center + margin)
        return (float(low), float(high))
    except Exception:  # noqa: BLE001
        return (0.0, 1.0)


def check_promotion_with_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """综合统计准入决策（P0 核心）.

    准入条件（全部满足）:
      - N ≥ MIN_PROMOTION_SAMPLES (30)
      - win_rate ≥ MIN_WIN_RATE (0.50)
      - p_value < P_VALUE_SIG (0.05) — 二项检验显著
      - avg_pnl > 0
      - Cohen's d > MIN_COHENS_D (0.50) — 中等效应量

    淘汰条件（任一）:
      - 全负 PnL（retire）
      - 胜率 < 0.30（retire）

    Args:
        samples: [{"pnl_pct": float, ...}, ...]

    Returns:
        {
          "promote": bool,
          "retire": bool (optional),
          "reason": str,
          "n": int,
          "win_rate": float,
          "avg_pnl": float,
          "p_value": float,        # P0-1
          "effect_size": float,    # P0-1 Cohen's d
          "ci_lower": float,       # P0-1 95% CI 下界
          "ci_upper": float,       # P0-1 95% CI 上界
        }
    """
    # FAIL-OPEN: 空样本返回保守决策
    if not samples:
        return {
            "promote": False,
            "reason": "N=0 < 30",
            "n": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "p_value": 1.0,
            "effect_size": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 1.0,
        }

    n = len(samples)
    pnl_values = [float(s.get("pnl_pct", 0.0)) for s in samples]
    wins = sum(1 for p in pnl_values if p > 0)
    win_rate = wins / n
    avg_pnl = sum(pnl_values) / n
    p_value = binomial_test_pvalue(wins, n, p_h0=0.5)
    d = cohens_d(pnl_values)
    ci_low, ci_high = win_rate_ci(wins, n, conf=0.95)

    base = {
        "n": n,
        "win_rate": round(win_rate, 4),
        "avg_pnl": round(avg_pnl, 6),
        "p_value": round(p_value, 6),
        "effect_size": round(d, 4),
        "ci_lower": round(ci_low, 4),
        "ci_upper": round(ci_high, 4),
    }

    # 门槛 1: N ≥ 30
    if n < MIN_PROMOTION_SAMPLES:
        return {**base, "promote": False, "reason": f"N={n} < {MIN_PROMOTION_SAMPLES}"}

    # 门槛 2: 淘汰 — 全负或胜率<30%
    if win_rate < 0.30:
        return {**base, "promote": False, "retire": True,
                "reason": f"win_rate={win_rate:.0%} < 30% (retire)"}

    # 门槛 3: 统计显著性 p<0.05
    if p_value >= P_VALUE_SIG:
        return {**base, "promote": False,
                "reason": f"p_value={p_value:.4f} >= {P_VALUE_SIG} (not significant)"}

    # 门槛 4: avg_pnl > 0
    if avg_pnl <= 0:
        return {**base, "promote": False,
                "reason": f"avg_pnl={avg_pnl:.6f} <= 0"}

    # 门槛 5: 胜率 ≥ 50%
    if win_rate < MIN_WIN_RATE:
        return {**base, "promote": False,
                "reason": f"win_rate={win_rate:.0%} < {MIN_WIN_RATE:.0%}"}

    # 门槛 6: Cohen's d ≥ 0.5（中等效应量）
    if d < MIN_COHENS_D:
        return {**base, "promote": False,
                "reason": f"effect_size={d:.3f} < {MIN_COHENS_D} (small effect)"}

    # 全部通过 → promote
    return {**base, "promote": True,
            "reason": f"pass all gates (N={n}, p={p_value:.4f}, d={d:.3f}, CI=[{ci_low:.2f},{ci_high:.2f}])"}
