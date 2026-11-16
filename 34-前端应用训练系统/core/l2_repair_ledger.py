"""L1 发现 → `repair_ledger.trigger` 入队（SPEC-56 §4.5 / GAP-29 / G-L2-7）。

职责边界
--------
- **只做生成与入队**：L1 发现（`54.discovery_path`）→ 合法台账条目 → 追加 `l2_repair_ledger.jsonl`。
- **不做业务判定**：发现是否成立由 L1/54 负责；本模块只校验「来源可追溯 + 结构可判定」。
- **fail-closed**：任何字段不合契约（含 ref 与 resolver 不匹配、symptom 过短、缺少复现证据）直接拒绝写入，
  不生成「先写进去再说」的脏数据。

契约版本：`repair_ledger.schema.json` v1.1（初始入队自迁移 `reported→reported`）。

finding 入参（dict）
--------------------
    ref            必填  `reports/discovery/YYYYMMDD-NNNN`（54 发现路径）
    symptom        必填  ≥10 字，描述可观察异常（禁止「代码有问题」）
    repro_cmd      必填  复现命令（在 base 上必然失败）
    artifact_path  二选一  复现产物文件（计算 sha256）
    artifact_hash  二选一  已计算的 `sha256:<64hex>`
    kind           必填  `bugfix` | `optimization`
    base_commit    必填  7-40 位十六进制
    repo           可选  默认 `dreambuddy-v2`
    env            可选  默认 `py3.12/local`
    discovered_at  可选  发现时间（缺省取当前时间）
    optimization_evidence  优化类必填  `{gate45}` 或 `{stats}`（G-L2-8）
    metrics        优化类必填  `[{name,unit,before,after,...}]`（同一测试集前后对照）
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "1.1"

LEDGER_FILENAME = "l2_repair_ledger.jsonl"

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parents[1] / LEDGER_FILENAME

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "56-L2架构能力聚合层"
    / "contracts"
    / "repair_ledger.schema.json"
)

KINDS = ("bugfix", "optimization")

_TASK_ID_RE = re.compile(r"^(fix|opt)-(\d{8})-(\d{3})$")
_DISCOVERY_REF_RE = re.compile(r"^reports/discovery/\d{8}-\d{4}/?$")
_BASE_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
_ARTIFACT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_KIND_PREFIX = {"bugfix": "fix", "optimization": "opt"}


class LedgerError(ValueError):
    """发现不满足台账契约（拒绝入队）"""


# ============================================================
# 基础工具
# ============================================================


def _iso(value: Optional[datetime] = None) -> str:
    stamp = value or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.isoformat()


def _artifact_hash(finding: Dict[str, Any]) -> str:
    explicit = finding.get("artifact_hash")
    if explicit:
        if not _ARTIFACT_HASH_RE.match(str(explicit)):
            raise LedgerError(f"artifact_hash 非法（应为 sha256:<64hex>）: {explicit!r}")
        return str(explicit)

    path = finding.get("artifact_path")
    if not path:
        raise LedgerError("缺少复现产物：需提供 artifact_path 或 artifact_hash")
    file_path = Path(path)
    if not file_path.is_file():
        raise LedgerError(f"复现产物不存在: {file_path}")
    return "sha256:" + hashlib.sha256(file_path.read_bytes()).hexdigest()


def build_l1_trigger(ref: str, resolved_at: Optional[datetime] = None) -> Dict[str, Any]:
    """构造 L1 发现 trigger（G-L2-7：source/ref 必须可回溯到 54 发现路径）"""
    if not _DISCOVERY_REF_RE.match(str(ref or "")):
        raise LedgerError(
            f"trigger.ref 不匹配 54.discovery_path（应形如 reports/discovery/20261117-0001）: {ref!r}"
        )
    return {
        "source": "l1_finding",
        "resolver": "54.discovery_path",
        "ref": str(ref),
        "resolved_at": _iso(resolved_at),
    }


def _next_task_id(kind: str, day: str, existing: Iterable[Dict[str, Any]]) -> str:
    prefix = _KIND_PREFIX[kind]
    max_seq = 0
    for row in existing:
        match = _TASK_ID_RE.match(str(row.get("task_id") or ""))
        if not match:
            continue
        if match.group(1) == prefix and match.group(2) == day:
            max_seq = max(max_seq, int(match.group(3)))
    return f"{prefix}-{day}-{max_seq + 1:03d}"


# ============================================================
# 条目生成
# ============================================================


def build_entry(
    finding: Dict[str, Any],
    existing: Iterable[Dict[str, Any]] = (),
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """由 L1 发现生成台账条目（state=reported，初始自迁移）"""
    stamp = now or datetime.now(timezone.utc)

    kind = str(finding.get("kind") or "")
    if kind not in KINDS:
        raise LedgerError(f"kind 非法: {kind!r}（允许 {KINDS}）")

    symptom = str(finding.get("symptom") or "").strip()
    if len(symptom) < 10:
        raise LedgerError(f"symptom 至少 10 字（禁止「代码有问题」式描述）: {symptom!r}")

    repro_cmd = str(finding.get("repro_cmd") or "").strip()
    if len(repro_cmd) < 3:
        raise LedgerError("缺少复现命令 repro_cmd（fails_on_base 必须可执行验证）")

    base_commit = str(finding.get("base_commit") or "")
    if not _BASE_COMMIT_RE.match(base_commit):
        raise LedgerError(f"base_commit 非法（应为 7-40 位十六进制）: {base_commit!r}")

    trigger = build_l1_trigger(
        str(finding.get("ref") or ""),
        resolved_at=finding.get("discovered_at") or stamp,
    )

    day = stamp.strftime("%Y%m%d")
    iso_now = _iso(stamp)
    rows = list(existing)

    entry: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": _next_task_id(kind, day, rows),
        "kind": kind,
        "trigger": trigger,
        "state": "reported",
        "history": [{"from": "reported", "to": "reported", "at": iso_now, "by": "l1_finding"}],
        "attempts": 0,
        "symptom": symptom,
        "reported": {
            "repo": str(finding.get("repo") or "dreambuddy-v2"),
            "base_commit": base_commit,
            "env": str(finding.get("env") or "py3.12/local"),
        },
        "evidence": {
            "repro": {
                "cmd": repro_cmd,
                "fails_on_base": True,
                "artifact_hash": _artifact_hash(finding),
            }
        },
        "metrics": list(finding.get("metrics") or []),
        "created_at": iso_now,
        "updated_at": iso_now,
    }

    # 优化类必须带 45 或统计证据（G-L2-8）；发现期无证据则拒绝，不写空壳
    if kind == "optimization":
        optimization = finding.get("optimization_evidence")
        if not isinstance(optimization, dict) or not (
            "gate45" in optimization or "stats" in optimization
        ):
            raise LedgerError(
                "optimization 缺少证据：需 optimization_evidence={gate45:PASS|BLOCK|INCONCLUSIVE} "
                "或 {stats:{test_set,n≥30,effect,p_adj≤0.05,report_uri}}"
            )
        if not entry["metrics"]:
            raise LedgerError("optimization 缺少 metrics（同一测试集前后对照）")
        entry["evidence"]["optimization"] = optimization

    return entry


# ============================================================
# 校验与入队
# ============================================================


def validate_entry(entry: Dict[str, Any]) -> None:
    """按 v1.1 契约校验（结构 + trigger 可追溯），失败抛 LedgerError"""
    if entry.get("trigger", {}).get("source") != "l1_finding":
        raise LedgerError("本模块只接受 source=l1_finding 的条目")

    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - 环境缺依赖
        raise LedgerError("缺少 jsonschema，无法校验台账条目") from exc

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(entry), key=lambda e: e.path
    )
    if errors:
        raise LedgerError("台账条目不合契约: " + "; ".join(e.message for e in errors))


def load_ledger(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """读取 jsonl 台账（缺文件返回空；坏行直接报错，不静默跳过）"""
    file_path = Path(path) if path else DEFAULT_LEDGER_PATH
    if not file_path.exists():
        return []

    rows: List[Dict[str, Any]] = []
    for lineno, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise LedgerError(f"台账第 {lineno} 行不是合法 JSON: {exc}") from exc
    return rows


def enqueue_l1_finding(
    finding: Dict[str, Any],
    ledger_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """L1 发现入队：生成条目 → 校验 → 追加台账；重复发现返回既有条目（幂等）"""
    path = Path(ledger_path) if ledger_path else DEFAULT_LEDGER_PATH
    existing = load_ledger(path)

    ref = str(finding.get("ref") or "")
    symptom = str(finding.get("symptom") or "").strip()
    for row in existing:
        trigger = row.get("trigger") or {}
        if (
            trigger.get("source") == "l1_finding"
            and trigger.get("ref") == ref
            and row.get("symptom") == symptom
            and row.get("state") not in ("settled", "abandoned")
        ):
            return row

    entry = build_entry(finding, existing=existing, now=now)
    validate_entry(entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry
