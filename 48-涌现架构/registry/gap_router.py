"""gap_router.py — E6 需求单路由器（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E6）。

职责：
  1. gap_type → 能力域映射（查表路由，非人工指派；未知类型落 proposals + 人工评审）
  2. 超时扫描防静默黑洞（v0.3 评审 P0 封口）：open 超 48h 未认领 → alert；超 7 天 → expired

FAIL-OPEN：路由/扫描失败仅记日志，不抛出；能力域无响应时主链降级不崩溃。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import capability_gaps as cg

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROPOSALS_PATH = _REPO_ROOT / "48-涌现架构" / "registry" / "gap_type_proposals.jsonl"

# gap_type → 能力域 映射表（SPEC §4 E6：19 数据采集 / 因子工程 / evolution-case-ingest / wind 数据）
ROUTE_TABLE = {
    "missing_market_data": "19-数据访问层",
    "missing_fundamental_data": "19-数据访问层",
    "factor_insufficient_samples": "因子工程",
    "case_sparse": "evolution-case-ingest",
    "coupling_unsupported": "19-数据访问层",
    "backtest_evaluator_missing": "45-评测系统",
    "trading_recall_log_missing": "11-易经推理系统",
    "reflection_log_missing": "35-广义认知",
    "domain_state_series_missing": "4-MEMORY",
}

CLAIM_ALERT_HOURS = 48
EXPIRE_DAYS = 7


def route_gap(
    gap: Dict[str, Any],
    gaps_path: Optional[Path] = None,
    proposals_path: Optional[Path] = None,
) -> Optional[str]:
    """查表路由。已知 gap_type 返回能力域；未知类型落 proposals（人工评审）并返回 None。"""
    gap_type = gap.get("gap_type", "")
    domain = ROUTE_TABLE.get(gap_type)
    if domain is not None:
        return domain
    # 未知类型：落 gap_type_proposals.jsonl，等人工评审注册新映射。FAIL-OPEN。
    proposals_path = Path(proposals_path) if proposals_path else DEFAULT_PROPOSALS_PATH
    proposal = {
        "gap_type": gap_type,
        "sample_gap_id": gap.get("gap_id"),
        "evidence": gap.get("evidence"),
        "status": "pending_human_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        proposals_path.parent.mkdir(parents=True, exist_ok=True)
        with proposals_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(proposal, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("proposal 落盘失败（降级）: %s", exc)
    logger.warning("未知 gap_type %s 已落 proposals 待人工评审", gap_type)
    return None


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def scan_timeouts(
    gaps_path: Optional[Path] = None,
    now: Optional[datetime] = None,
    claim_alert_hours: int = CLAIM_ALERT_HOURS,
    expire_days: int = EXPIRE_DAYS,
) -> Dict[str, List[str]]:
    """超时扫描。返回 {"alerted": [gap_id...], "expired": [gap_id...]}。FAIL-OPEN 返回双空。"""
    try:
        gaps = cg.load_gaps(gaps_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("scan_timeouts 读取失败: %s", exc)
        return {"alerted": [], "expired": []}
    now = now or datetime.now(timezone.utc)
    alert_cutoff = now - timedelta(hours=claim_alert_hours)
    expire_cutoff = now - timedelta(days=expire_days)
    alerted: List[str] = []
    expired: List[str] = []
    for gap in gaps:
        status = gap.get("status", "open")
        if status in cg.TERMINAL_STATUSES:
            continue
        created = _parse_ts(gap.get("created_at"))
        claimed = _parse_ts(gap.get("claimed_at"))
        gid = gap.get("gap_id", "")
        if status == "open" and created is not None:
            if created < expire_cutoff:
                if cg.update_status(
                    gid, "expired", note="超 7 天未认领自动过期", path=gaps_path, now=now
                ):
                    expired.append(gid)
            elif created < alert_cutoff and not gap.get("alert"):
                # alert 是纯标记，不走状态机——直接重写该行
                gap["alert"] = True
                _rewrite_gap(gaps_path, gap)
                alerted.append(gid)
        elif status == "claimed" and claimed is not None and claimed < expire_cutoff:
            if cg.update_status(
                gid, "expired", note="认领超 7 天未解决自动过期", path=gaps_path, now=now
            ):
                expired.append(gid)
    return {"alerted": alerted, "expired": expired}


def _rewrite_gap(gaps_path: Optional[Path], updated: Dict[str, Any]) -> bool:
    """按 gap_id 原位更新一行（alert 标记等非状态字段）。FAIL-OPEN。"""
    path = Path(gaps_path) if gaps_path else cg.DEFAULT_GAPS_PATH
    gaps = cg.load_gaps(path)
    for i, gap in enumerate(gaps):
        if gap.get("gap_id") == updated.get("gap_id"):
            gaps[i] = updated
            break
    else:
        return False
    try:
        with path.open("w", encoding="utf-8") as fh:
            for gap in gaps:
                fh.write(json.dumps(gap, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("_rewrite_gap 写盘失败: %s", exc)
        return False
