"""Event Ledger — T-G17 测量、数据与审计契约

SPEC-33-G §2.11.9：
  1. 单一事实源 `ledger/events.jsonl`；只存引用 + 摘要
  2. outcome 幂等键 (change_id, run_id, outcome_seq)，重复覆盖不追加
  3. change_id 贯穿 proposal→branch→merge→deploy→metric→outcome
  4. 事件带 schema_version
  5. prev_hash 哈希链；断链即冻结 auto
  6. evaluator_version 冻结，切换需历史回归一致率达标
  9. 同观察窗 >1 变更需 BH-FDR(q≤0.1)
  10. 同 section 禁止并行 L2，无法隔离走 switchback

工程约束：纯标准库；JSONL + 原子写（tmp + os.replace）；哈希链覆盖 payload。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_VERSION}
GENESIS_HASH = "0" * 64
KINDS = frozenset(
    {"proposal", "branch", "merge", "deploy", "metric", "outcome", "case", "evidence", "policy"}
)
REQUIRED_CHAIN = ("proposal", "branch", "merge", "deploy", "metric", "outcome")
MAX_PAYLOAD_BYTES = 2048
EVALUATOR_MIN_AGREEMENT = 0.8
OUTCOME_BOOL_FIELDS = ("accepted", "tests_pass", "reverted")


class EventLedgerError(ValueError):
    """审计 / 测量契约违约（硬拒绝）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EventLedgerError(message)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_entry(entry: Dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k not in ("prev_hash", "receipt_hash")}
    return _sha256(_canonical(body) + str(entry.get("prev_hash") or ""))


class EventLedger:
    """演化事件唯一事实源：写入即上链，读取可校验。"""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.root = Path(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---------------------------------------------------------------- 路径

    @property
    def path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def evaluator_path(self) -> Path:
        return self.root / "evaluator.json"

    def _section_path(self, section: str) -> Path:
        return self.root / "section_locks" / f"{section}.json"

    # ---------------------------------------------------------------- 写

    def append(
        self,
        *,
        kind: str,
        change_id: str,
        payload: Optional[Dict[str, Any]] = None,
        run_id: str = "",
        outcome_seq: Optional[int] = None,
    ) -> Dict[str, Any]:
        kind = str(kind or "").strip()
        change_id = str(change_id or "").strip()
        _require(kind in KINDS, f"未知事件类型：{kind}")
        _require(kind != "outcome", "outcome 必须通过 record_outcome 写入（幂等键约束）")
        _require(bool(change_id), "change_id is required")
        payload = self._validate_payload(payload)

        events = self._read_all()
        entry = self._build_entry(
            seq=len(events) + 1,
            kind=kind,
            change_id=change_id,
            payload=payload,
            run_id=run_id,
            outcome_seq=outcome_seq,
        )
        self._append_entry(events, entry)
        self._write_all(events)
        return dict(entry)

    def record_outcome(
        self,
        *,
        change_id: str,
        run_id: str,
        outcome_seq: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        change_id = str(change_id or "").strip()
        run_id = str(run_id or "").strip()
        _require(bool(change_id) and bool(run_id), "change_id / run_id is required")
        _require(
            isinstance(outcome_seq, int) and not isinstance(outcome_seq, bool) and outcome_seq >= 0,
            "outcome_seq must be a non-negative integer",
        )
        payload = self._validate_payload(payload)
        for field in OUTCOME_BOOL_FIELDS:
            _require(isinstance(payload.get(field), bool), f"outcome.{field} must be boolean")

        events = self._read_all()
        index = self._find_outcome(events, change_id, run_id, outcome_seq)
        if index is None:
            entry = self._build_entry(
                seq=len(events) + 1,
                kind="outcome",
                change_id=change_id,
                payload=payload,
                run_id=run_id,
                outcome_seq=outcome_seq,
            )
            self._append_entry(events, entry)
        else:
            entry = dict(events[index])
            entry["payload"] = payload
            entry["created_at"] = self._now_iso()
            entry["receipt_hash"] = _hash_entry(entry)
            events[index] = entry
            _rechain(events, index + 1)

        self._write_all(events)
        return dict(entry)

    # ---------------------------------------------------------------- 读

    def events(self) -> List[Dict[str, Any]]:
        return self._read_all()

    def outcomes(self, *, change_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = [e for e in self._read_all() if e.get("kind") == "outcome"]
        if change_id is not None:
            rows = [e for e in rows if e.get("change_id") == change_id]
        return rows

    def trace(self, change_id: str) -> Dict[str, Any]:
        """change_id 贯穿检查：缺任一环节即不计入证据。"""
        rows = [e for e in self._read_all() if e.get("change_id") == change_id]
        stages: Dict[str, Any] = {}
        for entry in rows:
            kind = entry.get("kind")
            if kind in REQUIRED_CHAIN and kind not in stages:
                stages[kind] = {
                    "event_id": entry.get("event_id"),
                    "receipt_hash": entry.get("receipt_hash"),
                }
        missing = [kind for kind in REQUIRED_CHAIN if kind not in stages]
        return {
            "change_id": change_id,
            "stages": stages,
            "missing": missing,
            "complete": not missing and bool(rows),
        }

    def counts_as_evidence(self, change_id: str) -> bool:
        return bool(self.trace(change_id)["complete"])

    def verify_chain(self) -> Dict[str, Any]:
        events = self._read_all()
        prev = GENESIS_HASH
        for index, entry in enumerate(events):
            if entry.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
                return self._broken(
                    index, f"schema_version 不受支持：{entry.get('schema_version')}"
                )
            if entry.get("prev_hash") != prev:
                return self._broken(index, "prev_hash 与上一条 receipt_hash 不匹配")
            if entry.get("receipt_hash") != _hash_entry(entry):
                return self._broken(index, "receipt_hash 与内容不匹配")
            prev = entry["receipt_hash"]
        return {"ok": True, "events": len(events), "head": prev, "broken_at": None, "reason": ""}

    def enforce_chain(self, controller: Any = None) -> Dict[str, Any]:
        """断链即冻结 auto（可通过注入 controller.open_breaker 落地）。"""
        report = self.verify_chain()
        report["auto_frozen"] = False
        if report["ok"] or controller is None:
            return report
        controller.open_breaker(reason=f"审计链断裂：seq {report['broken_at']} {report['reason']}")
        report["auto_frozen"] = True
        return report

    # ---------------------------------------------------------------- 评估器冻结

    def evaluator_version(self) -> Optional[str]:
        document = self._read_evaluator()
        return document.get("frozen_version") or None

    def freeze_evaluator(self, version: str) -> Dict[str, Any]:
        version = str(version or "").strip()
        _require(bool(version), "evaluator_version is required")
        document = self._read_evaluator()
        frozen = document.get("frozen_version")
        if frozen:
            _require(
                frozen == version,
                f"评估器版本已冻结为 {frozen}；切换必须走 request_evaluator_switch 并回归达标",
            )
            return dict(document)
        document["frozen_version"] = version
        document.setdefault("history", []).append(
            {"version": version, "action": "freeze", "at": self._now_iso()}
        )
        self._write_evaluator(document)
        return dict(document)

    def request_evaluator_switch(
        self,
        version: str,
        *,
        agreement: float,
        min_agreement: float = EVALUATOR_MIN_AGREEMENT,
    ) -> Dict[str, Any]:
        version = str(version or "").strip()
        _require(bool(version), "evaluator_version is required")
        document = self._read_evaluator()
        frozen = document.get("frozen_version")
        if not frozen:
            self.freeze_evaluator(version)
            return {
                "allowed": True,
                "from": None,
                "to": version,
                "agreement": float(agreement),
                "threshold": min_agreement,
            }
        allowed = float(agreement) >= float(min_agreement)
        result = {
            "allowed": allowed,
            "from": frozen,
            "to": version,
            "agreement": float(agreement),
            "threshold": min_agreement,
        }
        if allowed:
            document["frozen_version"] = version
            document.setdefault("history", []).append(
                {
                    "version": version,
                    "action": "switch",
                    "from": frozen,
                    "agreement": float(agreement),
                    "at": self._now_iso(),
                }
            )
            self._write_evaluator(document)
        return result

    # ---------------------------------------------------------------- 多重比较

    @staticmethod
    def requires_bh_fdr(change_count: int) -> bool:
        return int(change_count) > 1

    @staticmethod
    def bh_fdr(pvalues: Dict[str, float], *, q: float = 0.1) -> Dict[str, Any]:
        """Benjamini-Hochberg：返回 rejected（可晋级）与 hold（未校正只能 hold）。"""
        items = sorted((float(p), str(key)) for key, p in (pvalues or {}).items())
        total = len(items)
        cutoff = 0
        for rank, (pvalue, _key) in enumerate(items, start=1):
            if pvalue <= (rank / total) * float(q):
                cutoff = rank
        rejected = sorted(key for _p, key in items[:cutoff])
        hold = sorted(key for _p, key in items[cutoff:])
        return {"method": "bh", "q": float(q), "rejected": rejected, "hold": hold}

    # ---------------------------------------------------------------- 归因隔离

    def acquire_section(
        self, section: str, *, change_id: str, mode: str = "exclusive"
    ) -> Dict[str, Any]:
        section = str(section or "").strip()
        change_id = str(change_id or "").strip()
        _require(bool(section) and bool(change_id), "section / change_id is required")
        path = self._section_path(section)
        existing = self._read_json(path)
        if existing is None:
            lock = {
                "section": section,
                "holder": change_id,
                "switchback": [],
                "acquired_at": self._now_iso(),
            }
            self._write_json(path, lock)
            return {"section": section, "holder": change_id, "mode": "exclusive"}
        if existing.get("holder") == change_id:
            return {"section": section, "holder": change_id, "mode": "exclusive"}
        if str(mode) == "switchback":
            members = list(existing.get("switchback") or [])
            if change_id not in members:
                members.append(change_id)
            existing["switchback"] = members
            self._write_json(path, existing)
            return {"section": section, "holder": existing.get("holder"), "mode": "switchback"}
        raise EventLedgerError(
            f"同 section 禁止并行 L2：{section} 已由 {existing.get('holder')} 占用；"
            "无法隔离请改用 switchback（时间交替）"
        )

    def release_section(self, section: str, *, change_id: str) -> Dict[str, Any]:
        section = str(section or "").strip()
        path = self._section_path(section)
        existing = self._read_json(path)
        _require(existing is not None, f"{section} 发布锁不存在，拒绝释放")
        if existing.get("holder") == change_id:
            path.unlink()
            return {"section": section, "released": True, "holder": change_id}
        members = list(existing.get("switchback") or [])
        _require(
            change_id in members,
            f"{section} 归因锁不属于 {change_id}，拒绝释放",
        )
        existing["switchback"] = [item for item in members if item != change_id]
        self._write_json(path, existing)
        return {"section": section, "released": True, "holder": change_id}

    # ---------------------------------------------------------------- 内部

    def _validate_payload(self, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        payload = payload or {}
        _require(isinstance(payload, dict), "payload must be an object")
        size = len(_canonical(payload).encode("utf-8"))
        _require(
            size <= MAX_PAYLOAD_BYTES,
            f"payload 超过摘要上限 {MAX_PAYLOAD_BYTES} 字节（只存引用 + 摘要，禁止复制完整正文）",
        )
        return payload

    def _build_entry(
        self,
        *,
        seq: int,
        kind: str,
        change_id: str,
        payload: Dict[str, Any],
        run_id: str,
        outcome_seq: Optional[int],
    ) -> Dict[str, Any]:
        return {
            "event_id": f"EV-{seq:06d}",
            "seq": seq,
            "kind": kind,
            "change_id": change_id,
            "run_id": str(run_id or ""),
            "outcome_seq": outcome_seq,
            "payload": payload,
            "schema_version": SCHEMA_VERSION,
            "created_at": self._now_iso(),
            "prev_hash": GENESIS_HASH,
            "receipt_hash": "",
        }

    @staticmethod
    def _append_entry(events: List[Dict[str, Any]], entry: Dict[str, Any]) -> None:
        entry["prev_hash"] = events[-1]["receipt_hash"] if events else GENESIS_HASH
        entry["receipt_hash"] = _hash_entry(entry)
        events.append(entry)

    @staticmethod
    def _find_outcome(
        events: Sequence[Dict[str, Any]], change_id: str, run_id: str, outcome_seq: int
    ) -> Optional[int]:
        for index, entry in enumerate(events):
            if entry.get("kind") != "outcome":
                continue
            if (
                entry.get("change_id"),
                entry.get("run_id"),
                entry.get("outcome_seq"),
            ) == (change_id, run_id, outcome_seq):
                return index
        return None

    @staticmethod
    def _broken(index: int, reason: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "events": None,
            "head": None,
            "broken_at": index,
            "reason": reason,
        }

    def _read_all(self) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _write_all(self, events: Sequence[Dict[str, Any]]) -> None:
        body = "\n".join(_canonical(entry) for entry in events)
        self._write_text(self.path, body + ("\n" if events else ""))

    def _read_evaluator(self) -> Dict[str, Any]:
        return self._read_json(self.evaluator_path) or {}

    def _write_evaluator(self, document: Dict[str, Any]) -> None:
        self._write_json(self.evaluator_path, document)

    def _read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.is_file():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return loaded if isinstance(loaded, dict) else None

    def _write_json(self, path: Path, document: Dict[str, Any]) -> None:
        self._write_text(
            path, json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )

    @staticmethod
    def _write_text(path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)

    def _now_iso(self) -> str:
        return self.clock().isoformat()


def _rechain(events: List[Dict[str, Any]], start: int) -> None:
    for index in range(max(1, start), len(events)):
        events[index]["prev_hash"] = events[index - 1]["receipt_hash"]
        events[index]["receipt_hash"] = _hash_entry(events[index])
