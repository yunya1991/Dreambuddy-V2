"""capability_gaps.py — E6 需求单存储层（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E6）。

stigmergy 信息素模型：主链缺口以需求单形式落 48-涌现架构/registry/capability_gaps.jsonl
即完成"广播"，能力域自主认领补齐，无需中心调度。append-only JSONL。

状态机：open → claimed → resolved / expired / rejected；open → expired / rejected。
resolved 必须先经 claimed（保证 time_to_capability 可度量）；终态不可再转移。

FAIL-OPEN：任何 IO/解析异常不向调用方抛出，记日志并返回降级值（空表/False）。
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAPS_PATH = _REPO_ROOT / "48-涌现架构" / "registry" / "capability_gaps.jsonl"

VALID_STATUSES = ("open", "claimed", "resolved", "expired", "rejected")
TERMINAL_STATUSES = ("resolved", "expired", "rejected")

# 合法状态转移表
VALID_TRANSITIONS = {
    "open": ("claimed", "expired", "rejected"),
    "claimed": ("resolved", "expired", "rejected"),
    "resolved": (),
    "expired": (),
    "rejected": (),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_gap(
    gap_type: str,
    evidence: Dict[str, Any],
    expected_value: str = "",
    target_domain_hint: str = "",
    created_by: str = "manual",
) -> Dict[str, Any]:
    """构造一张需求单（不落盘，落盘用 append_gap）。"""
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return {
        "gap_id": f"GAP-{day}-{secrets.token_hex(4)}",
        "gap_type": gap_type,
        "evidence": evidence,
        "expected_value": expected_value,
        "target_domain_hint": target_domain_hint,
        "created_by": created_by,
        "status": "open",
        "created_at": _now_iso(),
        "claimed_at": None,
        "claimed_by": None,
        "resolved_at": None,
        "resolution_note": None,
        "alert": False,
    }


def append_gap(gap: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """追加需求单到 JSONL。FAIL-OPEN：失败返回 False。"""
    path = Path(path) if path else DEFAULT_GAPS_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(gap, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("append_gap 失败（降级不抛出）: %s", exc)
        return False


def load_gaps(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """读取全部需求单。坏行跳过；文件不存在返回空表。FAIL-OPEN。"""
    path = Path(path) if path else DEFAULT_GAPS_PATH
    if not path.exists():
        return []
    gaps: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    gaps.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("跳过损坏行: %.80s", line)
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_gaps 失败（降级返回已读部分）: %s", exc)
    return gaps


def update_status(
    gap_id: str,
    status: str,
    note: Optional[str] = None,
    actor: Optional[str] = None,
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> bool:
    """状态转移（重写整个 JSONL）。非法转移/缺口不存在返回 False。FAIL-OPEN。"""
    if status not in VALID_STATUSES:
        logger.warning("非法状态 %s", status)
        return False
    path = Path(path) if path else DEFAULT_GAPS_PATH
    gaps = load_gaps(path)
    ts = (now or datetime.now(timezone.utc)).isoformat()
    hit = False
    for gap in gaps:
        if gap.get("gap_id") != gap_id:
            continue
        hit = True
        current = gap.get("status", "open")
        if status not in VALID_TRANSITIONS.get(current, ()):
            logger.warning("非法状态转移 %s → %s（gap %s）", current, status, gap_id)
            return False
        gap["status"] = status
        if status == "claimed":
            gap["claimed_at"] = ts
            gap["claimed_by"] = actor
        elif status == "resolved":
            gap["resolved_at"] = ts
            gap["resolution_note"] = note
        elif status in ("expired", "rejected") and note:
            gap["resolution_note"] = note
        break
    if not hit:
        return False
    try:
        with path.open("w", encoding="utf-8") as fh:
            for gap in gaps:
                fh.write(json.dumps(gap, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("update_status 写盘失败: %s", exc)
        return False
