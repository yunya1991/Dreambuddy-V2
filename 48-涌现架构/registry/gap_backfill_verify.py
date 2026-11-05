"""gap_backfill_verify.py — E6 回填验证（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E6 P1 M7 口径）。

能力补齐后对比主链指标前后变化：gap resolved 后以 resolved_at 为界，
前后各取 14 个自然日（无交易日 pnl 计 0，保证 Wilcoxon 配对等长），
按日聚合 pnl_pct，跑 Wilcoxon signed-rank 检验。

数据源口径（2026-11-05 落地实证修正）：SPEC 原文 all_trades.jsonl 更新止于 2026-10-13，
改用 E0b 同源 bcrm_trades.db（trades 表 exit_time + pnl_pct，实盘真实成交，与 E0b 基线一致）。

FAIL-OPEN：任何异常返回 {"status": "error", ...}，不抛出。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import capability_gaps as cg

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "11-易经推理系统" / "scripts" / "data" / "bcrm_trades.db"

WINDOW_DAYS = 14
MIN_ACTIVE_DAYS = 5
P_SIGNIFICANT = 0.05


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _daily_pnl(db_path: Path, start: datetime, end: datetime) -> Tuple[List[float], int]:
    """[start, end) 内按自然日聚合 pnl_pct（求和），无交易日计 0。返回 (序列, 活跃天数)。"""
    days = (end.date() - start.date()).days
    series = [0.0] * days
    active = set()
    conn = sqlite3.connect(str(db_path))
    try:
        for exit_time, pnl in conn.execute("SELECT exit_time, pnl_pct FROM trades"):
            dt = _parse_ts(exit_time)
            if dt is None or pnl is None or not (start <= dt < end):
                continue
            idx = (dt.date() - start.date()).days
            if 0 <= idx < days:
                series[idx] += float(pnl)
                active.add(idx)
    finally:
        conn.close()
    return series, len(active)


def verify_gap_resolution(
    gap_id: str,
    gaps_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
    window_days: int = WINDOW_DAYS,
    min_days: int = MIN_ACTIVE_DAYS,
) -> Dict[str, Any]:
    """回填验证主入口。对比 gap resolved 前后 window_days 天日 PnL，Wilcoxon 检验。"""
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    gaps = cg.load_gaps(gaps_path)
    gap = next((g for g in gaps if g.get("gap_id") == gap_id), None)
    if gap is None:
        return {"gap_id": gap_id, "status": "error", "reason": "gap_not_found"}
    if gap.get("status") != "resolved":
        return {"gap_id": gap_id, "status": "skip_not_resolved"}
    t0 = _parse_ts(gap.get("resolved_at"))
    if t0 is None:
        return {"gap_id": gap_id, "status": "error", "reason": "resolved_at_unparseable"}

    before_start = t0 - timedelta(days=window_days)
    after_end = t0 + timedelta(days=window_days)
    try:
        before, before_active = _daily_pnl(db_path, before_start, t0)
        after, after_active = _daily_pnl(db_path, t0, after_end)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("回填验证读取失败: %s", exc)
        return {"gap_id": gap_id, "status": "error", "reason": str(exc)}

    if before_active < min_days or after_active < min_days:
        return {
            "gap_id": gap_id,
            "status": "insufficient_data",
            "before_active_days": before_active,
            "after_active_days": after_active,
            "min_required": min_days,
        }

    from scipy.stats import wilcoxon

    before_mean = sum(before) / len(before)
    after_mean = sum(after) / len(after)
    improved = after_mean > before_mean
    try:
        p_value = float(wilcoxon(before, after).pvalue)
    except ValueError:
        # 全零差值（两侧序列完全一致）→ 无差异
        p_value = 1.0
    return {
        "gap_id": gap_id,
        "status": "ok",
        "window_days": window_days,
        "before_active_days": before_active,
        "after_active_days": after_active,
        "before_mean": before_mean,
        "after_mean": after_mean,
        "improved": improved,
        "p_value": p_value,
        "significant": bool(improved and p_value < P_SIGNIFICANT),
    }
