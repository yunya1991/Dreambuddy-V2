# -*- coding: utf-8 -*-
"""L1-D/L2 对照表与事后收益打分（SPEC-54 §3 ADR-V17 / L1D-09）。

口径：
  - 同 `(as_of, symbol)` 只允许一条对照记录；**L2 结论不得覆盖 L1-D 记录**
    （`l1_direction`/`l1_strength` 一旦写入即不可改，`l2_verdict` 首写优先）；
  - 打分用**三重障碍**（±`barrier_atr_mult`×ATR 或 `barrier_days` 根，先到者），
    与「到期才看收益」相比消除了时间偏差；
  - 收益扣双边成本 `cost_bps_per_side` 与滑点 `slippage_atr_mult`×ATR；
  - 只写 `comparison` 表，不触碰 `signal`（append-only）。
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Sequence

from . import store

BARRIER_ATR_MULT = 2.0
BARRIER_DAYS = 10
COST_BPS_PER_SIDE = 5.0
SLIPPAGE_ATR_MULT = 0.5
LABEL_UPPER = "upper"
LABEL_LOWER = "lower"
LABEL_TIME = "time"


class ComparisonError(ValueError):
    """对照记录冲突（L2 试图覆盖 L1-D / 重复写入不同结论）。"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _row(db_path: Optional[str], as_of: str, symbol: str) -> Optional[Dict[str, Any]]:
    conn = store.connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM comparison WHERE as_of = ? AND symbol = ?", (str(as_of), symbol)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else dict(row)


def record_comparison(
    as_of: str,
    symbol: str,
    *,
    l1_direction: int,
    l1_strength: float,
    l2_verdict: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """写入/补齐对照记录；同键同方向幂等，方向不一致直接拒绝。"""
    direction = int(l1_direction)
    if direction not in (-1, 0, 1):
        raise ComparisonError("l1_direction 必须 ∈ {-1,0,1}")
    strength = float(l1_strength)
    if not 0.0 <= strength <= 1.0:
        raise ComparisonError("l1_strength 必须 ∈ [0,1]")

    existing = _row(db_path, as_of, symbol)
    if existing is None:
        conn = store.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO comparison (as_of, symbol, l1_direction, l1_strength, l2_verdict)"
                " VALUES (?, ?, ?, ?, ?)",
                (str(as_of), symbol, direction, strength, l2_verdict),
            )
            conn.commit()
        finally:
            conn.close()
        existing = _row(db_path, as_of, symbol)
    else:
        if existing["l1_direction"] != direction:
            raise ComparisonError(
                f"L2 不得覆盖 L1-D 记录：已有 {existing['l1_direction']}，收到 {direction}"
            )
        if existing["l1_strength"] != strength:
            raise ComparisonError("L2 不得覆盖 L1-D 记录：l1_strength 不一致")
        if l2_verdict is not None:
            set_l2_verdict(as_of, symbol, l2_verdict, db_path=db_path)
    return _row(db_path, as_of, symbol) or {}


def set_l2_verdict(as_of: str, symbol: str, verdict: str, *, db_path: Optional[str] = None) -> bool:
    """首写优先：已有不同结论时拒绝，避免 L2 反复改写影响事后归因。"""
    row = _row(db_path, as_of, symbol)
    if row is None:
        raise ComparisonError("对照记录不存在，先调用 record_comparison")
    current = row.get("l2_verdict")
    if current is not None:
        if current == verdict:
            return False
        raise ComparisonError(f"L2 结论已存在（{current}），不得覆盖为 {verdict}")
    conn = store.connect(db_path)
    try:
        conn.execute(
            "UPDATE comparison SET l2_verdict = ? WHERE as_of = ? AND symbol = ?",
            (verdict, str(as_of), symbol),
        )
        conn.commit()
    finally:
        conn.close()
    return True


def triple_barrier(
    entry_px: float,
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    atr: float,
    direction: int = 1,
    closes: Optional[Sequence[float]] = None,
    barrier_atr_mult: float = BARRIER_ATR_MULT,
    barrier_days: int = BARRIER_DAYS,
    cost_bps_per_side: float = COST_BPS_PER_SIDE,
    slippage_atr_mult: float = SLIPPAGE_ATR_MULT,
) -> Dict[str, Any]:
    """三重障碍打分：上/下障碍先到者成交，否则第 `barrier_days` 根按收盘价退出。"""
    side = int(direction)
    if side not in (-1, 1):
        raise ComparisonError("direction 必须 ∈ {-1,1}")
    entry = float(entry_px)
    if entry <= 0:
        raise ComparisonError("entry_px 必须 > 0")
    band = float(barrier_atr_mult) * float(atr)
    if band <= 0:
        raise ComparisonError("atr 必须 > 0（障碍带宽依赖 ATR）")
    upper, lower = entry + band, entry - band
    horizon = min(int(barrier_days), len(highs), len(lows))
    if horizon <= 0:
        raise ComparisonError("价格序列为空，无法打分")

    label, exit_px, bars = LABEL_TIME, None, horizon
    flags: List[str] = []
    for i in range(horizon):
        hit_low = float(lows[i]) <= lower
        hit_high = float(highs[i]) >= upper
        if hit_low and hit_high:
            flags.append("both_barriers_same_bar")
            # 同根双侧触发时取「对持仓不利」的一侧（保守）
            hit_low, hit_high = (True, False) if side > 0 else (False, True)
        if hit_low:
            label, exit_px, bars = LABEL_LOWER, lower, i + 1
            break
        if hit_high:
            label, exit_px, bars = LABEL_UPPER, upper, i + 1
            break
    if exit_px is None:
        if closes is not None and len(closes) >= bars:
            exit_px = float(closes[bars - 1])
        else:
            exit_px = (float(highs[bars - 1]) + float(lows[bars - 1])) / 2.0

    gross = side * (exit_px / entry - 1.0)
    cost = 2.0 * float(cost_bps_per_side) / 10000.0 + float(slippage_atr_mult) * float(atr) / entry
    return {
        "label": label,
        "bars": bars,
        "exit_px": round(exit_px, 8),
        "entry_px": entry,
        "direction": side,
        "gross_ret": round(gross, 8),
        "cost": round(cost, 8),
        "realized_ret": round(gross - cost, 6),
        "flags": flags,
    }


def score_comparison(
    as_of: str,
    symbol: str,
    *,
    entry_px: float,
    highs: Sequence[float],
    lows: Sequence[float],
    atr: float,
    closes: Optional[Sequence[float]] = None,
    direction: Optional[int] = None,
    db_path: Optional[str] = None,
    **barrier: Any,
) -> Dict[str, Any]:
    """按对照记录里的 L1 方向打分，并把 `realized_ret`/`scored_at` 写回。"""
    row = _row(db_path, as_of, symbol)
    if row is None:
        raise ComparisonError("对照记录不存在，先调用 record_comparison")
    side = int(row["l1_direction"] if direction is None else direction)
    if side == 0:
        result = {
            "label": LABEL_TIME,
            "bars": 0,
            "exit_px": None,
            "entry_px": float(entry_px),
            "direction": 0,
            "gross_ret": 0.0,
            "cost": 0.0,
            "realized_ret": 0.0,
            "flags": ["flat_position"],
        }
    else:
        result = triple_barrier(
            entry_px, highs, lows, atr=atr, direction=side, closes=closes, **barrier
        )

    conn = store.connect(db_path)
    try:
        conn.execute(
            "UPDATE comparison SET realized_ret = ?, scored_at = ? WHERE as_of = ? AND symbol = ?",
            (result["realized_ret"], _now(), str(as_of), symbol),
        )
        conn.commit()
    finally:
        conn.close()
    return {**result, "as_of": str(as_of), "symbol": symbol, "l1_direction": row["l1_direction"]}


def list_comparisons(
    db_path: Optional[str] = None, *, symbol: Optional[str] = None, limit: int = 100
) -> List[Dict[str, Any]]:
    conn = store.connect(db_path)
    try:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM comparison WHERE symbol = ? ORDER BY as_of LIMIT ?",
                (symbol, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM comparison ORDER BY as_of LIMIT ?", (int(limit),)
            ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


__all__ = [
    "BARRIER_ATR_MULT",
    "BARRIER_DAYS",
    "COST_BPS_PER_SIDE",
    "ComparisonError",
    "LABEL_LOWER",
    "LABEL_TIME",
    "LABEL_UPPER",
    "SLIPPAGE_ATR_MULT",
    "list_comparisons",
    "record_comparison",
    "score_comparison",
    "set_l2_verdict",
    "triple_barrier",
]
