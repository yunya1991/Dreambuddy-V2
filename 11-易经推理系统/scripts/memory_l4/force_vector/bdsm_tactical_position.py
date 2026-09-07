"""BDSM 战术小仓策略（Tactical Micro-Position Framework）。

融合三大传统流派：
  - 彼得·林奇 tenbagger：底部盘整 + 基本面改善 → 小仓观察仓
  - 威廉·欧奈尔 CANSLIM：跌破 MA50 或亏 15% → 硬止损
  - 斯坦利·德鲁肯米勒：高确信度走标准仓，低确信度走小仓

定位：BDSM 价值框架的补充策略。适用于「基本面强但纵向估值偏高/技术超买」的标的，
     不替代 BDSM 标准仓路径。独立开关、独立配额、独立止损。

开关：ENABLE_TACTICAL_MICRO_POSITION（默认 False）
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

# ── 开关与参数（环境变量覆盖，FAIL-OPEN 用默认值）──────────────────────────
ENABLE_TACTICAL_MICRO_POSITION = os.environ.get(
    "ENABLE_TACTICAL_MICRO_POSITION", ""
).lower() in ("1", "true")

TACTICAL_MICRO_BUDGET_USDT = float(
    os.environ.get("TACTICAL_MICRO_BUDGET_USDT", "60")
)
TACTICAL_STOP_LOSS_PCT = float(
    os.environ.get("TACTICAL_STOP_LOSS_PCT", "0.15")
)
TACTICAL_E8_EXIT_THRESHOLD = float(
    os.environ.get("TACTICAL_E8_EXIT_THRESHOLD", "-0.3")
)
TACTICAL_MAX_POSITIONS = int(
    os.environ.get("TACTICAL_MAX_POSITIONS", "2")
)

# 入场门槛
TACTICAL_BDS_THRESHOLD = 0.3
TACTICAL_VALUATION_HIGH = 80.0
TACTICAL_RSI_OVERBOUGHT = 70.0


def tactical_entry_check(coin_entry: Dict[str, Any]) -> bool:
    """战术小仓入场条件（全部满足才 eligible）。

    条件：
      ① bds_score ≥ 0.3（基本面过关）
      ② phase ∈ {P1_UNDERVALUED_RECOVERY, P2_REVENUE_EXPANSION}
      ③ trend_stop.action == "none"（趋势未破）
      ④ value_exit.action != "full_exit"（未触发完整出场）
      ⑤ 非 BDSM 标准仓已覆盖场景：cvs < 0.3 OR valuation_percentile > 80 OR rsi_14 > 70

    FAIL-OPEN：coin_entry 缺失关键字段 → False（不入场，安全）
    """
    try:
        bds_score = float(coin_entry.get("bds_score", 0.0) or 0.0)
        phase = str(coin_entry.get("phase", "") or "")
        cvs = float(coin_entry.get("cvs", 0.0) or 0.0)
        val_pct = float(coin_entry.get("valuation_percentile", 50.0) or 50.0)

        # ① 基本面过关
        if bds_score < TACTICAL_BDS_THRESHOLD:
            return False

        # ② 阶段正确
        if phase not in ("P1_UNDERVALUED_RECOVERY", "P2_REVENUE_EXPANSION"):
            return False

        # ③ 趋势未破
        trend_stop = coin_entry.get("trend_stop") or {}
        if str(trend_stop.get("action", "none") or "none").lower() != "none":
            return False

        # ④ 未触发完整出场
        value_exit = coin_entry.get("value_exit") or {}
        if str(value_exit.get("action", "none") or "none").lower() == "full_exit":
            return False

        # ⑤ 非 BDSM 标准仓已覆盖（标准仓条件：cvs ≥ 0.3 且估值不高且不超买）
        ta = coin_entry.get("technical_assessment") or {}
        rsi_14 = float(ta.get("rsi_14", 50.0) or 50.0)
        is_standard_covered = (
            cvs >= 0.3
            and val_pct <= TACTICAL_VALUATION_HIGH
            and rsi_14 <= TACTICAL_RSI_OVERBOUGHT
        )
        if is_standard_covered:
            return False  # 标准仓已覆盖，不走战术小仓

        return True
    except Exception:
        return False  # FAIL-OPEN


def tactical_exit_check(
    position: Dict[str, Any],
    coin_entry: Dict[str, Any],
    bds_history: Optional[List[float]] = None,
) -> Tuple[bool, str]:
    """战术小仓退出条件（任一触发即全平）。

    Args:
        position: 持仓信息，需含 current_price / avg_entry_price（或 unrealized_pnl_pct）
                  可选 ma50
        coin_entry: 今日快照 entry
        bds_history: 最近 N 个快照的 bds_score 列表（用于检测基本面恶化）

    Returns:
        (should_exit, reason)
    """
    try:
        # ① BDSM full_exit
        value_exit = coin_entry.get("value_exit") or {}
        if str(value_exit.get("action", "none") or "none").lower() == "full_exit":
            return True, "bdsm_full_exit"

        # ② E8 板块高估
        e8 = float(coin_entry.get("e8_cross_sector_valuation", 0.0) or 0.0)
        if e8 < TACTICAL_E8_EXIT_THRESHOLD:
            return True, f"sector_overvalued_e8_{e8:.3f}"

        # ③ 跌破 MA50（欧奈尔硬止损）
        ma50 = float(position.get("ma50", 0.0) or 0.0)
        current_price = float(position.get("current_price", 0.0) or 0.0)
        if ma50 > 0 and current_price > 0 and current_price < ma50:
            return True, f"ma50_break_{current_price:.2f}<{ma50:.2f}"

        # ④ 亏损 ≥ 止损百分比
        pnl_pct = position.get("unrealized_pnl_pct")
        if pnl_pct is None:
            avg_entry = float(position.get("avg_entry_price", 0.0) or 0.0)
            if avg_entry > 0 and current_price > 0:
                pnl_pct = (current_price - avg_entry) / avg_entry
        if pnl_pct is not None and float(pnl_pct) <= -TACTICAL_STOP_LOSS_PCT:
            return True, f"stop_loss_{float(pnl_pct):.3f}"

        # ⑤ BDS 基本面恶化（连续 2 个快照环比下滑 > 0.1）
        if bds_history and len(bds_history) >= 2:
            recent = bds_history[-1]
            prev = bds_history[-2]
            if prev - recent > 0.1:
                return True, f"bds_deterioration_{prev:.3f}->{recent:.3f}"

        return False, "none"
    except Exception:
        return False, "none"  # FAIL-OPEN：不退出
