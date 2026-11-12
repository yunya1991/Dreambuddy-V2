"""Policy Ledger — T-G2 Policy 版本账本 + 八门禁校验器

SPEC-33-G：
  - §1 G-G2：每次 Policy 变更都有 policy_id / 前后 sha256 / 八门禁逐项结论 / 回滚点
  - §2.1 Policy 账本：policy/registry.json + policy/versions/<policy_id>.json
  - §2.6 备份：versions/<policy_id>/backup/<path> + manifest.json + rollback.sh
  - §2.8 八门禁；§4 硬约束 15（promotion.json 记录门禁逐项、模式、阶段、污染条数）
  - §2.11.9 第 2/3/9 条：outcome 幂等键、change_id 贯穿、BH-FDR(q≤0.1)

工程约束：纯标准库；八门禁为纯函数（无 IO）；账本写入原子替换；门禁不通过一律抛错。
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

LEVEL_QUOTAS = {"L1": 1, "L2": 2}
VALID_LEVELS = ("L1", "L2", "L3")
MIN_OUTCOMES = 30
MIN_OBSERVE_HOURS = 24.0
MIN_HELDOUT_BUCKET = 20
BH_FDR_Q = 0.1
L2_MAX_FILES = 3
L2_MAX_LOC = 200
WEEK = timedelta(days=7)

GATE_NAMES = {
    1: "备份完整",
    2: "沙箱三组全绿",
    3: "回滚演练通过",
    4: "影子期达标",
    5: "提案/评估分离且可证伪",
    6: "变更幅度合规",
    7: "证据充分",
    8: "配额与断路器",
}


class PolicyLedgerError(ValueError):
    """Policy 账本契约或门禁违约（硬门禁）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PolicyLedgerError(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _gate(number: int, status: str, reason: str = "") -> Dict[str, Any]:
    return {"gate": number, "name": GATE_NAMES[number], "status": status, "reason": reason}


def _is_valid_outcome(entry: Any) -> bool:
    """有效 outcome：change_id/run_id/outcome_seq 齐全且时间可解析（§2.11.9 第 2/3 条）。"""
    if not isinstance(entry, dict):
        return False
    if not str(entry.get("change_id") or "").strip():
        return False
    if not str(entry.get("run_id") or "").strip():
        return False
    seq = entry.get("outcome_seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        return False
    return _parse_ts(entry.get("created_at")) is not None


def evaluate_gates(
    *,
    level: str,
    change: Dict[str, Any],
    backup: Dict[str, Any],
    sandbox_report: Optional[Dict[str, Any]],
    rollback_drill: Any,
    shadow_report: Optional[Dict[str, Any]],
    proposal: Optional[Dict[str, Any]],
    evaluation: Optional[Dict[str, Any]],
    outcomes: Iterable[Dict[str, Any]],
    section: str = "",
    heldout_bucket: int = 0,
    concurrent_changes: int = 1,
    bh_fdr_q: Optional[float] = None,
    quota: Optional[Dict[str, int]] = None,
    breaker: Optional[Dict[str, Any]] = None,
    stateful: bool = False,
) -> Dict[str, Any]:
    """八门禁校验（纯函数）。返回逐项结论 + overall(pass|fail|hold)。"""
    change = change or {}
    gates: List[Dict[str, Any]] = []

    # 1 备份完整
    if backup.get("verified") is True:
        gates.append(_gate(1, "pass"))
    else:
        gates.append(
            _gate(1, "fail", str(backup.get("reason") or "manifest 缺失或 sha256 不可复算"))
        )

    # 2 沙箱三组全绿
    sandbox = sandbox_report or {}
    groups = sandbox.get("groups") or {}
    if sandbox.get("overall") != "pass":
        gates.append(_gate(2, "fail", f"sandbox_report.overall={sandbox.get('overall')!r}"))
    elif not groups:
        gates.append(_gate(2, "hold", "缺少 A/B/C 三组明细"))
    else:
        failed = [name for name in ("A", "B", "C") if groups.get(name) != "pass"]
        if failed:
            gates.append(_gate(2, "fail", f"沙箱组未通过: {', '.join(failed)}"))
        else:
            gates.append(_gate(2, "pass"))

    # 3 回滚演练
    if isinstance(rollback_drill, str):
        drill_overall, state_restore = rollback_drill, None
    else:
        drill = rollback_drill or {}
        drill_overall, state_restore = drill.get("overall"), drill.get("state_restore")
    if drill_overall != "pass":
        gates.append(_gate(3, "fail", f"rollback_drill={drill_overall!r}"))
    elif stateful and state_restore != "pass":
        gates.append(_gate(3, "fail", "stateful 变更须含数据/状态恢复演练"))
    else:
        gates.append(_gate(3, "pass"))

    # 4 影子期达标（按 section）
    shadow = shadow_report or {}
    sections = shadow.get("sections") or {}
    if shadow.get("overall") != "pass":
        gates.append(_gate(4, "fail", f"shadow_report.overall={shadow.get('overall')!r}"))
    elif not sections:
        gates.append(_gate(4, "hold", "缺少按 section 的影子结论"))
    else:
        failed = [name for name, status in sections.items() if status != "pass"]
        if failed:
            gates.append(_gate(4, "fail", f"section 影子未达标: {', '.join(failed)}"))
        else:
            gates.append(_gate(4, "pass"))

    # 5 提案/评估分离且可证伪（confidence 只记录，不入任何门禁）
    proposal = proposal or {}
    evaluation = evaluation or {}
    proposer = str(proposal.get("proposer_model") or "").strip()
    evaluator = str(evaluation.get("evaluator_model") or "").strip()
    falsifier = str(proposal.get("falsifier") or "").strip()
    verdict = evaluation.get("verdict")
    if not proposer or not evaluator or not falsifier:
        gates.append(_gate(5, "hold", "缺少 proposer_model / evaluator_model / falsifier"))
    elif proposer == evaluator:
        gates.append(_gate(5, "fail", "提案模型与评估模型相同"))
    elif verdict != "improve":
        gates.append(_gate(5, "fail", f"evaluation.verdict={verdict!r}"))
    else:
        gates.append(_gate(5, "pass"))

    # 6 变更幅度合规
    if level == "L1":
        targets = change.get("targets") or []
        units = change.get("units", len(targets))
        if change.get("kind") not in ("rule", "param", "skill"):
            gates.append(_gate(6, "fail", "L1 只允许 rule / param / skill"))
        elif units != 1 or len(targets) != 1:
            gates.append(
                _gate(
                    6,
                    "fail",
                    f"L1 每次仅 1 规则/1 参数/1 SKILL（units={units}, targets={len(targets)}）",
                )
            )
        else:
            gates.append(_gate(6, "pass"))
    elif level == "L2":
        files = int(change.get("files") or 0)
        loc = int(change.get("loc") or 0)
        modules = change.get("modules") or []
        if files > L2_MAX_FILES or loc > L2_MAX_LOC or len(modules) != 1:
            gates.append(
                _gate(
                    6,
                    "fail",
                    f"L2 限制 ≤3 文件/≤200 行/单模块（files={files}, loc={loc}, modules={len(modules)}）",
                )
            )
        else:
            gates.append(_gate(6, "pass"))
    else:
        gates.append(_gate(6, "fail", "L3 只出 ADR/SPEC，不得进入自动门禁"))

    # 7 证据充分
    valid = [
        entry
        for entry in outcomes
        if _is_valid_outcome(entry) and (not section or entry.get("section") == section)
    ]
    if len(valid) < MIN_OUTCOMES:
        gates.append(_gate(7, "fail", f"有效 outcome {len(valid)} < {MIN_OUTCOMES}"))
    else:
        stamps = sorted(_parse_ts(entry["created_at"]) for entry in valid)
        span_hours = (stamps[-1] - stamps[0]).total_seconds() / 3600.0
        if span_hours < MIN_OBSERVE_HOURS:
            gates.append(_gate(7, "fail", f"观察期 {span_hours:.1f}h < {MIN_OBSERVE_HOURS}h"))
        elif heldout_bucket < MIN_HELDOUT_BUCKET:
            gates.append(
                _gate(7, "fail", f"held-out 对应桶 {heldout_bucket} < {MIN_HELDOUT_BUCKET}")
            )
        elif concurrent_changes > 1 and bh_fdr_q is None:
            gates.append(_gate(7, "hold", "同期多变更须 BH-FDR 校正"))
        elif concurrent_changes > 1 and bh_fdr_q > BH_FDR_Q:
            gates.append(_gate(7, "fail", f"BH-FDR q={bh_fdr_q} > {BH_FDR_Q}"))
        else:
            gates.append(_gate(7, "pass"))

    # 8 配额与断路器
    quota = quota or {}
    used = int(quota.get("used") or 0)
    limit = int(quota.get("limit") or 0)
    if limit <= 0:
        gates.append(_gate(8, "fail", "周配额未配置"))
    elif used >= limit:
        gates.append(_gate(8, "fail", f"周配额已用尽（{used}/{limit}）"))
    elif (breaker or {}).get("open"):
        gates.append(_gate(8, "fail", "breaker.json 已打开，auto 冻结"))
    else:
        gates.append(_gate(8, "pass"))

    statuses = {item["status"] for item in gates}
    overall = "fail" if "fail" in statuses else ("hold" if "hold" in statuses else "pass")
    return {"overall": overall, "gates": gates}


class PolicyLedger:
    """Policy 版本账本：registry + versions/<policy_id>.json + backup + promotion 留痕。"""

    def __init__(self, root: str | Path, *, quotas: Optional[Dict[str, int]] = None):
        self.root = Path(root)
        self.quotas = dict(quotas or LEVEL_QUOTAS)

    # ---------- 路径 ----------

    @property
    def registry_path(self) -> Path:
        return self.root / "registry.json"

    def version_path(self, policy_id: str) -> Path:
        return self.root / "versions" / f"{policy_id}.json"

    def bundle_dir(self, policy_id: str) -> Path:
        return self.root / "versions" / policy_id

    # ---------- 写 ----------

    def record_change(
        self,
        policy_id: str,
        *,
        level: str,
        changes: List[Dict[str, Any]],
        rollback_point: str,
        workspace_root: Optional[str | Path] = None,
        change: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        _require(bool(str(policy_id or "").strip()), "policy_id is required")
        _require(level in VALID_LEVELS, f"level must be one of {VALID_LEVELS}")
        _require(isinstance(changes, list) and bool(changes), "changes must be a non-empty list")
        _require(bool(str(rollback_point or "").strip()), "rollback_point is required")

        existing = self.get(policy_id)
        if existing is not None:
            _require(existing.get("status") != "promoted", f"policy already promoted: {policy_id}")

        bundle = self.bundle_dir(policy_id)
        backup_root = bundle / "backup"
        entries: List[Dict[str, Any]] = []
        for index, item in enumerate(changes):
            _require(isinstance(item, dict), "change entry must be an object")
            relative = self._safe_relative(item.get("path"), index)
            source = item.get("source")
            if source is None and workspace_root is not None:
                source = Path(workspace_root) / relative
            _require(source is not None, f"changes[{index}] requires source or workspace_root")
            source_path = Path(source)
            _require(source_path.exists(), f"source file not found: {source_path}")

            sha_before = str(item.get("sha256_before") or "").strip() or sha256_file(source_path)
            _require(
                sha256_file(source_path) == sha_before,
                f"changes[{index}] sha256_before mismatch: {relative}",
            )
            sha_after = item.get("sha256_after")
            if sha_after is not None:
                _require(
                    isinstance(sha_after, str) and len(sha_after) == 64,
                    f"changes[{index}] sha256_after must be a 64-char hex string",
                )

            target = backup_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            entries.append(
                {
                    "path": relative.as_posix(),
                    "sha256_before": sha_before,
                    "sha256_after": sha_after,
                    "backup_path": (Path("backup") / relative).as_posix(),
                }
            )

        manifest = {
            "policy_id": policy_id,
            "level": level,
            "rollback_point": rollback_point,
            "created_at": _now(),
            "entries": entries,
            "aggregate": {
                "sha256_before": self._aggregate(entries, "sha256_before"),
                "sha256_after": self._aggregate(entries, "sha256_after"),
            },
        }
        self._write_json(bundle / "manifest.json", manifest)
        self._write_rollback_script(bundle / "rollback.sh", policy_id, rollback_point, entries)

        record: Dict[str, Any] = {
            "policy_id": policy_id,
            "level": level,
            "status": "proposed",
            "created_at": manifest["created_at"],
            "rollback_point": rollback_point,
            "manifest": "manifest.json",
            "rollback_script": "rollback.sh",
            "before_sha256": manifest["aggregate"]["sha256_before"],
            "after_sha256": manifest["aggregate"]["sha256_after"],
            "change": self._normalize_change(change, entries),
            "metadata": dict(metadata or {}),
        }
        self._write_json(self.version_path(policy_id), record)
        self._update_registry(record)
        return dict(record)

    def promote(
        self,
        policy_id: str,
        *,
        gate_report: Dict[str, Any],
        mode: str,
        stage: str,
        pollution_count: int = 0,
    ) -> Dict[str, Any]:
        record = self.get(policy_id)
        _require(record is not None, f"policy not found: {policy_id}")
        _require(isinstance(gate_report, dict), "gate_report must be an object")
        declared = gate_report.get("policy_id")
        _require(
            declared in (None, policy_id),
            f"gate_report.policy_id mismatch: {declared!r} != {policy_id!r}",
        )
        _require(
            gate_report.get("overall") == "pass",
            f"八门禁未全绿，禁止晋级（overall={gate_report.get('overall')!r}）",
        )
        gates = gate_report.get("gates")
        _require(isinstance(gates, list) and len(gates) == 8, "gate_report.gates 必须为 8 项")
        _require(
            all(item.get("status") == "pass" for item in gates),
            "门禁逐项结论必须全部 pass",
        )
        _require(mode in ("auto", "manual"), f"mode must be auto|manual, got {mode!r}")
        _require(stage in ("S1", "S2", "S3"), f"stage must be S1|S2|S3, got {stage!r}")
        _require(
            not (mode == "auto" and stage != "S3"),
            f"自动晋级仅限 S3（当前 {stage}）",
        )

        promotion = {
            "policy_id": policy_id,
            "mode": mode,
            "stage": stage,
            "pollution_count": int(pollution_count),
            "overall": "pass",
            "gates": gates,
            "promoted_at": _now(),
        }
        self._write_json(self.bundle_dir(policy_id) / "promotion.json", promotion)

        record["status"] = "promoted"
        record["promoted_at"] = promotion["promoted_at"]
        self._write_json(self.version_path(policy_id), record)
        self._update_registry(record)
        return promotion

    # ---------- 读 ----------

    def get(self, policy_id: str) -> Optional[Dict[str, Any]]:
        path = self.version_path(policy_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def mark_rolled_back(
        self,
        policy_id: str,
        *,
        reason: str = "",
        duration_s: Optional[float] = None,
        pollution_count: int = 0,
    ) -> Dict[str, Any]:
        record = self.get(policy_id)
        _require(record is not None, f"policy not found: {policy_id}")
        record["status"] = "rolled_back"
        record["rolled_back_at"] = _now()
        record["rollback_reason"] = reason
        if duration_s is not None:
            record["rollback_duration_s"] = duration_s
        record["pollution_count"] = int(pollution_count)
        self._write_json(self.version_path(policy_id), record)
        self._update_registry(record)
        return record

    def registry(self) -> Dict[str, Any]:
        if not self.registry_path.exists():
            return {"version": 1, "policies": {}}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def verify_backup(
        self, policy_id: str, *, current_root: Optional[str | Path] = None
    ) -> Dict[str, Any]:
        record = self.get(policy_id)
        if record is None:
            return {"verified": False, "reason": f"policy not found: {policy_id}"}
        bundle = self.bundle_dir(policy_id)
        manifest_path = bundle / "manifest.json"
        if not manifest_path.exists():
            return {"verified": False, "reason": "manifest 缺失"}

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("entries") or []
        if not entries:
            return {"verified": False, "reason": "manifest.entries 为空"}

        for entry in entries:
            backup_file = bundle / entry["backup_path"]
            if not backup_file.exists():
                return {"verified": False, "reason": f"备份文件缺失: {entry['backup_path']}"}
            if sha256_file(backup_file) != entry["sha256_before"]:
                return {"verified": False, "reason": f"backup sha256 不匹配: {entry['path']}"}
            if entry.get("sha256_after") and current_root is not None:
                current = Path(current_root) / entry["path"]
                if not current.exists():
                    return {"verified": False, "reason": f"变更后文件缺失: {entry['path']}"}
                if sha256_file(current) != entry["sha256_after"]:
                    return {"verified": False, "reason": f"变更后 sha256 不匹配: {entry['path']}"}

        aggregate = manifest.get("aggregate") or {}
        if aggregate.get("sha256_before") != self._aggregate(entries, "sha256_before"):
            return {"verified": False, "reason": "聚合 sha256_before 不可复算"}
        if aggregate.get("sha256_after") != self._aggregate(entries, "sha256_after"):
            return {"verified": False, "reason": "聚合 sha256_after 不可复算"}
        return {"verified": True, "reason": ""}

    def weekly_usage(self, level: str, *, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        threshold = now - WEEK
        count = 0
        for summary in self.registry().get("policies", {}).values():
            if summary.get("level") != level:
                continue
            if summary.get("status") not in ("promoted", "observing", "confirmed"):
                continue
            promoted_at = _parse_ts(summary.get("promoted_at"))
            if promoted_at is not None and promoted_at >= threshold:
                count += 1
        return count

    def weekly_limit(self, level: str) -> int:
        return int(self.quotas.get(level, 0))

    def breaker_state(self) -> Dict[str, Any]:
        path = self.root / "breaker.json"
        if not path.exists():
            return {"open": False}
        return json.loads(path.read_text(encoding="utf-8"))

    # ---------- 门禁便捷入口 ----------

    def evaluate(
        self,
        policy_id: str,
        *,
        stateful: bool = False,
        sandbox_report: Optional[Dict[str, Any]] = None,
        rollback_drill: Any = None,
        shadow_report: Optional[Dict[str, Any]] = None,
        proposal: Optional[Dict[str, Any]] = None,
        evaluation: Optional[Dict[str, Any]] = None,
        outcomes: Iterable[Dict[str, Any]] = (),
        section: str = "",
        heldout_bucket: int = 0,
        concurrent_changes: int = 1,
        bh_fdr_q: Optional[float] = None,
        quota: Optional[Dict[str, int]] = None,
        breaker: Optional[Dict[str, Any]] = None,
        current_root: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        record = self.get(policy_id)
        _require(record is not None, f"policy not found: {policy_id}")
        level = record["level"]
        report = evaluate_gates(
            level=level,
            change=record.get("change") or {},
            backup=self.verify_backup(policy_id, current_root=current_root),
            sandbox_report=sandbox_report,
            rollback_drill=rollback_drill,
            shadow_report=shadow_report,
            proposal=proposal,
            evaluation=evaluation,
            outcomes=outcomes,
            section=section,
            heldout_bucket=heldout_bucket,
            concurrent_changes=concurrent_changes,
            bh_fdr_q=bh_fdr_q,
            quota=(
                quota
                if quota is not None
                else {"used": self.weekly_usage(level), "limit": self.weekly_limit(level)}
            ),
            breaker=breaker if breaker is not None else self.breaker_state(),
            stateful=stateful,
        )
        report["policy_id"] = policy_id
        return report

    # ---------- 内部 ----------

    @staticmethod
    def _safe_relative(path: Any, index: int) -> Path:
        _require(isinstance(path, str) and bool(path.strip()), f"changes[{index}].path is required")
        relative = Path(path)
        _require(not relative.is_absolute(), f"changes[{index}].path must be relative")
        _require(".." not in relative.parts, f"changes[{index}].path escapes workspace")
        return relative

    @staticmethod
    def _normalize_change(
        change: Optional[Dict[str, Any]], entries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        normalized = dict(change or {})
        targets = list(normalized.get("targets") or [entry["path"] for entry in entries])
        normalized["targets"] = targets
        normalized.setdefault("units", len(targets))
        normalized.setdefault("files", len(entries))
        return normalized

    @staticmethod
    def _aggregate(entries: List[Dict[str, Any]], field: str) -> str:
        payload = [{"path": entry["path"], field: entry.get(field)} for entry in entries]
        return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))

    @staticmethod
    def _write_rollback_script(
        path: Path, policy_id: str, rollback_point: str, entries: List[Dict[str, Any]]
    ) -> None:
        lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"# rollback {policy_id} -> {rollback_point}",
            'ROOT="${WORKSPACE_ROOT:?set WORKSPACE_ROOT to the project root}"',
        ]
        bundle = path.parent
        for entry in entries:
            source = bundle / entry["backup_path"]
            target = f"$ROOT/{entry['path']}"
            lines.append(f"cp -f {shlex.quote(str(source))} {shlex.quote(target)}")
        lines.append(f'echo "rolled back {policy_id} to {rollback_point}"')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o755)

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def _update_registry(self, record: Dict[str, Any]) -> None:
        registry = self.registry()
        summary = {
            key: record.get(key)
            for key in (
                "policy_id",
                "level",
                "status",
                "before_sha256",
                "after_sha256",
                "rollback_point",
                "created_at",
                "promoted_at",
            )
            if record.get(key) is not None
        }
        registry.setdefault("policies", {})[record["policy_id"]] = summary
        registry.setdefault("version", 1)
        self._write_json(self.registry_path, registry)
