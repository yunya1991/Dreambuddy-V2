# -*- coding: utf-8 -*-
"""T7-2a 期级实验预注册（SPEC-20261116 §5.8 v0.12）。

边界：
  - 54 拥有**预注册**，48 拥有 **verdict**；本模块只写预注册与回填，不裁决；
  - `hypothesis_key` 必须由结构化字段派生，禁止用自然语言去重（评审 M4）；
  - 预注册后参数冻结（`frozen_params_hash` 由 params 派生），改参数 = 新 experiment_id；
  - 同一 `hypothesis_key` 30 天唯一；同一 `suggestion_id` 冷却 7 天。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

SCHEMA_VERSION = "1.0"
ARM_SCHEME = "aba_v1"
UNIT = "period"
ENDPOINT = "excess_hit"
VERDICT_SCHEME = "stat_relation_v1"
STATUSES = ("preregistered", "running", "closed", "abandoned")
VERDICTS = ("candidate", "verified", "rejected", "falsified", "insufficient_data")
DEDUP_DAYS = 30
COOLDOWN_DAYS = 7
DEFAULT_GUARDRAIL = {"min_periods": 3, "effect_bps_gt_cost_bps": True, "max_drawdown": 0.2}
MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DB_FILE = os.path.join(MODULE_ROOT, "data", "experiment_prereg.db")

_REQUIRED_KEY_FIELDS = ("relation_type", "target", "horizon", "param_name", "delta_sign")
_TRANSITIONS = {
    "preregistered": {"running", "abandoned"},
    "running": {"closed", "abandoned"},
    "closed": set(),
    "abandoned": set(),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment_prereg (
  experiment_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  hypothesis_key TEXT NOT NULL,
  hypothesis TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  arm_scheme TEXT NOT NULL,
  unit TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  guardrail_json TEXT NOT NULL,
  cooldown_days INTEGER NOT NULL,
  frozen_params_hash TEXT NOT NULL,
  params_json TEXT NOT NULL,
  suggestion_id TEXT,
  status TEXT NOT NULL,
  verdict TEXT,
  verdict_scheme TEXT,
  effect REAL,
  reason_code TEXT,
  created_at TEXT NOT NULL,
  evaluated_at TEXT
)
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def hypothesis_key(
    *,
    relation_type: str,
    target: str,
    horizon: Any,
    param_name: str,
    delta_sign: str,
) -> str:
    """结构化去重键：换一种自然语言说法也绕不过去。"""
    raw = "|".join(
        str(part).strip().lower()
        for part in (relation_type, target, horizon, param_name, delta_sign)
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def frozen_params_hash(params: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(params), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _validate(proposal: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    for key in _REQUIRED_KEY_FIELDS:
        if not str(proposal.get(key) or "").strip():
            errors.append(f"缺字段 {key}")
    if not isinstance(proposal.get("evidence_ids"), list) or not proposal.get("evidence_ids"):
        errors.append("evidence_ids 必须是非空列表")
    if not isinstance(proposal.get("params"), Mapping) or not proposal.get("params"):
        errors.append("params 必须是非空对象（预注册即冻结）")
    if not str(proposal.get("hypothesis") or "").strip():
        errors.append("缺字段 hypothesis（仅作展示）")
    if proposal.get("arm_scheme", ARM_SCHEME) != ARM_SCHEME:
        errors.append(f"arm_scheme 必须为 {ARM_SCHEME}")
    if proposal.get("unit", UNIT) != UNIT:
        errors.append(f"unit 必须为 {UNIT}")
    if proposal.get("endpoint", ENDPOINT) != ENDPOINT:
        errors.append(f"endpoint 必须为 {ENDPOINT}")
    guardrail = proposal.get("guardrail") or DEFAULT_GUARDRAIL
    if not isinstance(guardrail, Mapping):
        errors.append("guardrail 必须是对象")
    elif int(guardrail.get("min_periods") or 0) <= 0:
        errors.append("guardrail.min_periods 必须为正整数")
    return errors


def preregister(
    proposal: Mapping[str, Any],
    *,
    db_path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """写一条期级预注册；重复 hypothesis 或冷却期内同 suggestion 直接拒绝。"""
    errors = _validate(proposal)
    if errors:
        return {"ok": False, "reason": "invalid_proposal", "errors": errors}
    path = db_path or DB_FILE
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    moment = now or _now()
    stamp = _iso(moment)
    key = hypothesis_key(
        relation_type=proposal["relation_type"],
        target=proposal["target"],
        horizon=proposal["horizon"],
        param_name=proposal["param_name"],
        delta_sign=proposal["delta_sign"],
    )
    params_hash = frozen_params_hash(proposal["params"])
    guardrail = dict(proposal.get("guardrail") or DEFAULT_GUARDRAIL)
    cooldown = int(proposal.get("cooldown_days") or COOLDOWN_DAYS)
    suggestion_id = str(proposal.get("suggestion_id") or "") or None

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(_SCHEMA)
        open_rows = conn.execute(
            "SELECT created_at FROM experiment_prereg "
            "WHERE hypothesis_key = ? AND status IN ('preregistered','running') "
            "ORDER BY created_at DESC LIMIT 1",
            (key,),
        ).fetchone()
        if open_rows is not None:
            created = datetime.fromisoformat(open_rows["created_at"])
            if moment - created < timedelta(days=DEDUP_DAYS):
                return {
                    "ok": False,
                    "reason": "duplicate_hypothesis",
                    "hypothesis_key": key,
                    "existing_created_at": open_rows["created_at"],
                }
        if suggestion_id:
            recent = conn.execute(
                "SELECT created_at FROM experiment_prereg WHERE suggestion_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (suggestion_id,),
            ).fetchone()
            if recent is not None:
                created = datetime.fromisoformat(recent["created_at"])
                if moment - created < timedelta(days=cooldown):
                    return {
                        "ok": False,
                        "reason": "cooldown_active",
                        "suggestion_id": suggestion_id,
                        "existing_created_at": recent["created_at"],
                    }
        day = moment.strftime("%Y%m%d")
        prefix = f"EXP-{key[:8]}-{day}-"
        used = conn.execute(
            "SELECT COUNT(*) AS n FROM experiment_prereg WHERE experiment_id LIKE ?",
            (f"{prefix}%",),
        ).fetchone()["n"]
        experiment_id = f"{prefix}{int(used) + 1:02d}"
        conn.execute(
            "INSERT INTO experiment_prereg (experiment_id, schema_version, hypothesis_key, hypothesis, "
            "evidence_ids_json, arm_scheme, unit, endpoint, guardrail_json, cooldown_days, "
            "frozen_params_hash, params_json, suggestion_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'preregistered', ?)",
            (
                experiment_id,
                SCHEMA_VERSION,
                key,
                str(proposal["hypothesis"]),
                json.dumps(list(proposal["evidence_ids"]), ensure_ascii=False),
                ARM_SCHEME,
                UNIT,
                ENDPOINT,
                json.dumps(guardrail, ensure_ascii=False, sort_keys=True),
                cooldown,
                params_hash,
                json.dumps(dict(proposal["params"]), ensure_ascii=False, sort_keys=True),
                suggestion_id,
                stamp,
            ),
        )
        conn.commit()
    return {
        "ok": True,
        "experiment_id": experiment_id,
        "hypothesis_key": key,
        "frozen_params_hash": params_hash,
        "created_at": stamp,
    }


def advance_status(
    experiment_id: str, status: str, *, db_path: Optional[str] = None
) -> Dict[str, Any]:
    path = db_path or DB_FILE
    if not os.path.isfile(path):
        return {"ok": False, "reason": "registry_missing"}
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(_SCHEMA)
        row = conn.execute(
            "SELECT status FROM experiment_prereg WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
        if row is None:
            return {"ok": False, "reason": "not_found"}
        current = str(row["status"])
        if status not in _TRANSITIONS.get(current, set()):
            return {"ok": False, "reason": "illegal_transition", "from": current, "to": status}
        conn.execute(
            "UPDATE experiment_prereg SET status = ? WHERE experiment_id = ?",
            (status, experiment_id),
        )
        conn.commit()
    return {"ok": True, "from": current, "to": status}


def apply_outcome(record: Mapping[str, Any], *, db_path: Optional[str] = None) -> Dict[str, Any]:
    """48 → 54 裁决回填；54 只存储，不判定。"""
    if record.get("verdict_scheme") != VERDICT_SCHEME:
        return {"ok": False, "reason": "verdict_scheme_mismatch"}
    if record.get("verdict") not in VERDICTS:
        return {"ok": False, "reason": "invalid_verdict"}
    path = db_path or DB_FILE
    if not os.path.isfile(path):
        return {"ok": False, "reason": "registry_missing"}
    experiment_id = str(record.get("experiment_id") or "")
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(_SCHEMA)
        row = conn.execute(
            "SELECT experiment_id FROM experiment_prereg WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
        if row is None:
            return {"ok": False, "reason": "not_found", "experiment_id": experiment_id}
        conn.execute(
            "UPDATE experiment_prereg SET verdict = ?, verdict_scheme = ?, effect = ?, "
            "reason_code = ?, evaluated_at = ? WHERE experiment_id = ?",
            (
                record["verdict"],
                VERDICT_SCHEME,
                float(record["effect"]) if record.get("effect") is not None else None,
                str(record.get("reason_code") or "") or None,
                _iso(_now()),
                experiment_id,
            ),
        )
        conn.commit()
    return {"ok": True, "experiment_id": experiment_id, "verdict": record["verdict"]}


def read_prereg(
    *,
    db_path: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    path = db_path or DB_FILE
    if not os.path.isfile(path):
        return []
    clause = " WHERE status = ?" if status else ""
    params: List[Any] = [status] if status else []
    params.append(max(1, int(limit)))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM experiment_prereg{clause} ORDER BY created_at DESC, experiment_id LIMIT ?",
            params,
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["evidence_ids"] = json.loads(item.pop("evidence_ids_json") or "[]")
        item["guardrail"] = json.loads(item.pop("guardrail_json") or "{}")
        item["params"] = json.loads(item.pop("params_json") or "{}")
        out.append(item)
    return out


def export_prereg_jsonl(path: str, *, db_path: Optional[str] = None) -> Dict[str, Any]:
    """跨端同步：54 导出 → 48 本地 ingest；不建跨库视图。"""
    rows = read_prereg(db_path=db_path, limit=100000)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"ok": True, "exported": len(rows), "path": path}
