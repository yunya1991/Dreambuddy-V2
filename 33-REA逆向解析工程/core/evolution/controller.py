"""Controller — T-G9 双模晋级控制器（状态机 + 三段式 + 飞书告警）

SPEC-33-G：
  - §2.5 状态机 proposed→evaluated→sandboxed→shadowed→qualified→promoted→observing→confirmed/rolled_back
  - §2.8 双模晋级：auto 仅 S3 + 八门禁全绿；无 AI 模式 qualified→notified + 飞书告警 + 人工批准
  - §2.8.1 三段式 S1/S2/S3：S1 manual 不启影子；降级立即生效，升级需 advance_stage
  - §2.8.2 断路器：连续 2 次 auto 观察期回滚 → open + 冻结 7 天 + 阶段回落 S2
  - §2.9 无 LLM 降级；§2.10 防退化五原则；§1 G-G9

工程约束：纯标准库；通知器可注入（离线测试）；状态/阶段/断路器全部本地 JSON 落盘。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .executor import evaluate_observation
from .policy_ledger import PolicyLedger

STAGES = ("S1", "S2", "S3")
STAGE_ORDER = {"S1": 1, "S2": 2, "S3": 3}
MIN_SECTION_OUTCOMES = 30
MIN_SECTION_HOURS = 24.0
MIN_CONSECUTIVE_AGREEMENTS = 5
AUTO_VETO_WINDOW = timedelta(hours=24)
AUTO_VETO_FIRST_N = 3
BREAKER_THRESHOLD = 2
BREAKER_FREEZE = timedelta(days=7)
GATE_COUNT = 8


class ControllerError(ValueError):
    """状态机 / 阶段机 / 断路器契约违约（硬门禁）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ControllerError(message)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class EvolutionController:
    """双模晋级控制器：唯一状态机入口，禁止绕过它直接调用 ledger.promote。"""

    def __init__(
        self,
        ledger: PolicyLedger,
        *,
        notifier: Optional[Callable[[Dict[str, Any]], Any]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.ledger = ledger
        self.root = ledger.root
        self.notifier = notifier
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---------------------------------------------------------------- 路径

    @property
    def stage_path(self) -> Path:
        return self.root / "stage.json"

    @property
    def breaker_path(self) -> Path:
        return self.root / "breaker.json"

    @property
    def states_dir(self) -> Path:
        return self.root / "states"

    @property
    def auto_promotions_path(self) -> Path:
        return self.root / "auto_promotions.json"

    @property
    def breaker_audit_path(self) -> Path:
        return self.root / "audit" / "breaker_audit.jsonl"

    def _state_path(self, policy_id: str) -> Path:
        return self.states_dir / f"{policy_id}.json"

    # ---------------------------------------------------------------- 读

    def stage(self) -> str:
        if not self.stage_path.exists():
            return "S1"
        stage = str(json.loads(self.stage_path.read_text(encoding="utf-8")).get("stage") or "S1")
        return stage if stage in STAGES else "S1"

    def state(self, policy_id: str) -> str:
        return str(self._read_state(policy_id).get("state") or "proposed")

    def history(self, policy_id: str) -> list:
        return list(self._read_state(policy_id).get("history") or [])

    def breaker(self) -> Dict[str, Any]:
        if not self.breaker_path.exists():
            return {"open": False, "consecutive_auto_rollbacks": 0}
        doc = json.loads(self.breaker_path.read_text(encoding="utf-8"))
        doc.setdefault("open", False)
        doc.setdefault("consecutive_auto_rollbacks", 0)
        return doc

    def is_auto_frozen(self) -> bool:
        """断路器打开即冻结 auto（恢复只能人工 reset_breaker）。"""
        return bool(self.breaker().get("open"))

    def breaker_audit(self) -> list:
        """断路器审计流水（open / reset 均留痕）。"""
        if not self.breaker_audit_path.exists():
            return []
        rows = []
        for line in self.breaker_audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    # ---------------------------------------------------------------- 阶段机

    def advance_stage(
        self,
        stage: str,
        *,
        reason: str,
        evidence: Optional[Dict[str, Any]] = None,
        actor: str = "operator",
    ) -> Dict[str, Any]:
        """升级只能逐级，且必须满足 SPEC §2.8.1 的退出条件。"""
        _require(stage in STAGES, f"stage must be one of {STAGES}")
        current = self.stage()
        _require(
            STAGE_ORDER[stage] == STAGE_ORDER[current] + 1,
            f"只能逐级升级：{current} → S{STAGE_ORDER[current] + 1}（当前 {current}，目标 {stage}）",
        )
        _require(bool(str(reason or "").strip()), "advance_stage 必须填写原因")
        evidence = evidence or {}

        if current == "S1":
            outcomes = int(evidence.get("section_outcomes") or 0)
            hours = float(evidence.get("hours") or 0.0)
            _require(
                outcomes >= MIN_SECTION_OUTCOMES,
                f"S1→S2 需某 section ≥{MIN_SECTION_OUTCOMES} 条有效 outcome（当前 {outcomes}）",
            )
            _require(
                hours >= MIN_SECTION_HOURS,
                f"S1→S2 需 ≥{MIN_SECTION_HOURS:.0f}h 观察（当前 {hours}h）",
            )
        else:
            agreements = int(evidence.get("consecutive_agreements") or 0)
            _require(
                agreements >= MIN_CONSECUTIVE_AGREEMENTS,
                f"S2→S3 需连续 {MIN_CONSECUTIVE_AGREEMENTS} 次门禁建议与人工决定一致（当前 {agreements}）",
            )
            _require(not self.breaker().get("open"), "断路器打开时不得升级到 S3")

        document = self._read_stage_doc()
        document["stage"] = stage
        document.setdefault("history", []).append(
            {
                "from": current,
                "to": stage,
                "reason": reason,
                "actor": actor or "operator",
                "evidence": evidence,
                "at": self._now(),
            }
        )
        document["updated_at"] = self._now()
        self._write_json(self.stage_path, document)
        return {"stage": stage, "from": current}

    def downgrade_stage(
        self, stage: str, *, reason: str, actor: str = "operator"
    ) -> Dict[str, Any]:
        """降级立即生效（断路器回落走此入口）。"""
        current = self.stage()
        _require(
            stage in STAGES and STAGE_ORDER[stage] < STAGE_ORDER[current],
            f"downgrade 只能降级（当前 {current}，目标 {stage}）",
        )
        _require(bool(str(reason or "").strip()), "downgrade_stage 必须填写原因")
        document = self._read_stage_doc()
        document["stage"] = stage
        document.setdefault("history", []).append(
            {
                "from": current,
                "to": stage,
                "reason": reason,
                "actor": actor or "operator",
                "at": self._now(),
            }
        )
        document["updated_at"] = self._now()
        self._write_json(self.stage_path, document)
        return {"stage": stage, "from": current}

    def open_breaker(
        self, *, reason: str, actor: str = "operator", trigger_policy: str = ""
    ) -> Dict[str, Any]:
        """打开断路器：冻结 auto 7 天 + 阶段立即回落 S2 + 审计 + 告警。"""
        _require(bool(str(reason or "").strip()), "open_breaker 必须填写原因")
        document = self.breaker()
        if document.get("open"):
            return document
        now = self.clock()
        document.update(
            {
                "open": True,
                "opened_at": now.isoformat(),
                "freeze_until": (now + BREAKER_FREEZE).isoformat(),
                "reason": reason,
            }
        )
        if trigger_policy:
            document["trigger_policy"] = trigger_policy
        self._write_json(self.breaker_path, document)
        self._audit(
            "breaker_open",
            {
                "reason": reason,
                "actor": actor or "operator",
                "trigger_policy": trigger_policy,
                "consecutive_auto_rollbacks": int(document.get("consecutive_auto_rollbacks") or 0),
                "freeze_until": document["freeze_until"],
            },
        )
        if STAGE_ORDER[self.stage()] > STAGE_ORDER["S2"]:
            self.downgrade_stage("S2", reason=f"断路器打开（{reason}）", actor="controller")
        self._notify(
            {
                "event": "breaker_open",
                "policy_id": trigger_policy,
                "mode": "auto",
                "stage": self.stage(),
                "reason": reason,
                "freeze_until": document["freeze_until"],
            }
        )
        return document

    def reset_breaker(self, *, reason: str, actor: str = "operator") -> Dict[str, Any]:
        """人工恢复：必须填原因，写审计留痕（§2.8.2）。"""
        _require(bool(str(reason or "").strip()), "reset_breaker 必须填写原因")
        document = self.breaker()
        previous = dict(document)
        document["open"] = False
        document["consecutive_auto_rollbacks"] = 0
        document.setdefault("reset_history", []).append(
            {
                "at": self._now(),
                "actor": actor or "operator",
                "reason": reason,
                "previous": previous,
            }
        )
        document["reset_at"] = self._now()
        self._write_json(self.breaker_path, document)
        self._audit(
            "breaker_reset",
            {"reason": reason, "actor": actor or "operator", "previous": previous},
        )
        return document

    # ---------------------------------------------------------------- 状态机

    def on_evaluated(self, policy_id: str, *, verdict: str) -> Dict[str, Any]:
        self._require_state(policy_id, ("proposed",), "on_evaluated")
        if verdict != "improve":
            return self._transition(policy_id, "hold", event="evaluated", note=f"verdict={verdict}")
        return self._transition(policy_id, "evaluated", event="evaluated")

    def on_sandboxed(self, policy_id: str, sandbox_report: Dict[str, Any]) -> Dict[str, Any]:
        self._require_state(policy_id, ("evaluated",), "on_sandboxed")
        overall = (sandbox_report or {}).get("overall")
        target = "sandboxed" if overall == "pass" else "sandbox_failed"
        return self._transition(policy_id, target, event="sandboxed", note=f"sandbox={overall!r}")

    def on_shadowed(self, policy_id: str, shadow_report: Dict[str, Any]) -> Dict[str, Any]:
        _require(self.stage() != "S1", "S1 数据积累阶段为 manual，不启影子")
        self._require_state(policy_id, ("sandboxed",), "on_shadowed")
        overall = (shadow_report or {}).get("overall")
        target = "shadowed" if overall == "pass" else "shadow_failed"
        return self._transition(policy_id, target, event="shadowed", note=f"shadow={overall!r}")

    def qualify(self, policy_id: str, gate_report: Dict[str, Any]) -> Dict[str, Any]:
        """门禁通过后决定 auto / manual / blocked；auto 仅限 S3 且断路器未开。"""
        self._require_policy(policy_id)
        current = self.state(policy_id)
        stage = self.stage()
        allowed = ("sandboxed",) if stage == "S1" else ("shadowed",)
        _require(
            current in allowed,
            f"qualify 需要 state=sandboxed|shadowed，即先完成 evaluated（当前 {current}）",
        )

        gate_report = gate_report or {}
        gates = gate_report.get("gates") or []
        failing = [item for item in gates if item.get("status") != "pass"]
        if gate_report.get("overall") != "pass" or len(gates) != GATE_COUNT or failing:
            reason = self._classify_gate_failure(gates)
            target = "hold"
            if "配额" in reason:
                target = "quota_exceeded"
            elif "breaker" in reason:
                target = "breaker_open"
            self._transition(
                policy_id,
                target,
                event="qualify",
                note=reason,
                extra={"gate_report": gate_report, "blocked_reason": reason},
            )
            return {
                "policy_id": policy_id,
                "state": target,
                "decision": "blocked",
                "mode": None,
                "reason": reason,
                "veto_until": None,
            }

        breaker = self.breaker()
        if stage != "S3" or breaker.get("open"):
            reason = "breaker_open" if breaker.get("open") else f"stage={stage}"
            self._transition(
                policy_id,
                "notified",
                event="qualify",
                mode="manual",
                note=reason,
                extra={"gate_report": gate_report, "notified_reason": reason},
            )
            # 无 AI 模式：manual 必发飞书告警（§2.9）
            self._notify(
                {
                    "event": "manual_required",
                    "policy_id": policy_id,
                    "mode": "manual",
                    "stage": stage,
                    "reason": reason,
                    "gate_report": gate_report,
                }
            )
            return {
                "policy_id": policy_id,
                "state": "notified",
                "decision": "manual",
                "mode": "manual",
                "reason": reason,
                "veto_until": None,
            }

        promotion = self.ledger.promote(policy_id, gate_report=gate_report, mode="auto", stage="S3")
        index = self._record_auto_promotion(policy_id)
        veto_until = (
            (self.clock() + AUTO_VETO_WINDOW).isoformat() if index <= AUTO_VETO_FIRST_N else None
        )
        self._transition(
            policy_id,
            "promoted",
            event="promoted",
            mode="auto",
            extra={"gate_report": gate_report, "veto_until": veto_until},
        )
        self._transition(policy_id, "observing", event="observing", mode="auto")
        # auto 仅通知，不阻塞（§2.9）
        self._notify(
            {
                "event": "auto_notice",
                "policy_id": policy_id,
                "mode": "auto",
                "stage": "S3",
                "veto_until": veto_until,
            }
        )
        return {
            "policy_id": policy_id,
            "state": "observing",
            "decision": "auto",
            "mode": "auto",
            "reason": "",
            "veto_until": veto_until,
            "promotion": promotion,
        }

    def approve(
        self, policy_id: str, *, actor: str = "operator", reason: str = ""
    ) -> Dict[str, Any]:
        """人工批准 notified → promoted(manual) → observing。"""
        self._require_state(policy_id, ("notified",), "approve")
        _require(bool(str(actor or "").strip()), "approve 需要 actor")
        record = self._read_state(policy_id)
        gate_report = record.get("gate_report")
        _require(isinstance(gate_report, dict), "缺少 gate_report，无法人工晋级")
        promotion = self.ledger.promote(
            policy_id, gate_report=gate_report, mode="manual", stage=self.stage()
        )
        note = f"{actor}: {reason}".strip().rstrip(":")
        self._transition(policy_id, "promoted", event="approved", mode="manual", note=note)
        self._transition(policy_id, "observing", event="observing", mode="manual")
        return {
            "policy_id": policy_id,
            "state": "observing",
            "mode": "manual",
            "promotion": promotion,
        }

    def observe(
        self,
        policy_id: str,
        *,
        before: Dict[str, Any],
        after: Dict[str, Any],
    ) -> Dict[str, Any]:
        """观察期判定：continue / confirm / rollback；auto 回滚累计触发断路器。"""
        self._require_state(policy_id, ("observing", "promoted"), "observe")
        decision = evaluate_observation(before or {}, after or {})
        verdict = decision.get("decision")
        if verdict == "continue":
            return {
                "policy_id": policy_id,
                "state": self.state(policy_id),
                "decision": "continue",
                "reason": decision.get("reason", ""),
            }
        if verdict == "confirm":
            self._transition(
                policy_id,
                "confirmed",
                event="confirmed",
                note=decision.get("reason") or "观察期达标",
            )
            return {
                "policy_id": policy_id,
                "state": "confirmed",
                "decision": "confirm",
                "reason": decision.get("reason", ""),
            }

        mode = self._read_state(policy_id).get("mode")
        reason = decision.get("reason") or "观察期指标下降"
        self.ledger.mark_rolled_back(policy_id, reason=reason)
        self._transition(policy_id, "rolled_back", event="rolled_back", note=reason)
        if mode == "auto":
            self._register_auto_rollback(policy_id, reason)
        return {
            "policy_id": policy_id,
            "state": "rolled_back",
            "decision": "rollback",
            "reason": reason,
        }

    def veto(self, policy_id: str, *, actor: str = "operator", reason: str = "") -> Dict[str, Any]:
        """S3 前 3 次 auto 晋级的 24h 否决窗口内，人工可回滚（不计入断路器）。"""
        self._require_state(policy_id, ("observing", "promoted"), "veto")
        record = self._read_state(policy_id)
        _require(record.get("mode") == "auto", "只有 auto 晋级存在 24h 否决窗口")
        veto_until = _parse_ts(record.get("veto_until"))
        _require(
            veto_until is not None and self.clock() <= veto_until,
            "已超出 24h 否决窗口",
        )
        note = f"{actor}: {reason}".strip().rstrip(":")
        self.ledger.mark_rolled_back(policy_id, reason=f"veto: {reason}".strip())
        self._transition(policy_id, "rolled_back", event="veto", note=note)
        return {"policy_id": policy_id, "state": "rolled_back"}

    # ---------------------------------------------------------------- 内部

    def _require_policy(self, policy_id: str) -> None:
        _require(self.ledger.get(policy_id) is not None, f"policy not found: {policy_id}")

    def _require_state(self, policy_id: str, expected: tuple, action: str) -> None:
        self._require_policy(policy_id)
        current = self.state(policy_id)
        _require(
            current in expected,
            f"{action} 需要 state={'|'.join(expected)}（当前 {current}）",
        )

    def _classify_gate_failure(self, gates: list) -> str:
        if len(gates) != GATE_COUNT:
            return f"gate_report.gates 必须为 {GATE_COUNT} 项（当前 {len(gates)}）"
        failing = [item for item in gates if item.get("status") != "pass"]
        if not failing:
            return "gate_report.overall 非 pass"
        for item in failing:
            if item.get("gate") == 8:
                reason = str(item.get("reason") or "")
                if "配额" in reason:
                    return reason
                if "breaker" in reason:
                    return "breaker_open"
        return "；".join(
            f"gate{item.get('gate')}: {item.get('status')} {item.get('reason') or ''}".strip()
            for item in failing
        )

    def _read_state(self, policy_id: str) -> Dict[str, Any]:
        path = self._state_path(policy_id)
        if not path.exists():
            return {"policy_id": policy_id, "state": "proposed", "mode": None, "history": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _transition(
        self,
        policy_id: str,
        target: str,
        *,
        event: str,
        mode: Optional[str] = None,
        note: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        record = self._read_state(policy_id)
        previous = record.get("state") or "proposed"
        record["state"] = target
        record["policy_id"] = policy_id
        record["stage"] = self.stage()
        record["mode"] = mode or record.get("mode")
        record["updated_at"] = self._now()
        if extra:
            record.update(extra)
        record.setdefault("history", []).append(
            {
                "event": event,
                "from": previous,
                "to": target,
                "mode": record.get("mode"),
                "stage": record.get("stage"),
                "note": note,
                "at": self._now(),
            }
        )
        self._write_json(self._state_path(policy_id), record)
        return record

    def _register_auto_rollback(self, policy_id: str, reason: str) -> None:
        document = self.breaker()
        count = int(document.get("consecutive_auto_rollbacks") or 0) + 1
        document["consecutive_auto_rollbacks"] = count
        self._write_json(self.breaker_path, document)
        if count >= BREAKER_THRESHOLD and not document.get("open"):
            self.open_breaker(
                reason=f"连续 {count} 次 auto 观察期回滚：{reason}",
                actor="controller",
                trigger_policy=policy_id,
            )

    def _record_auto_promotion(self, policy_id: str) -> int:
        document = {"count": 0, "records": []}
        if self.auto_promotions_path.exists():
            document = json.loads(self.auto_promotions_path.read_text(encoding="utf-8"))
        document["count"] = int(document.get("count") or 0) + 1
        document.setdefault("records", []).append(
            {"policy_id": policy_id, "at": self._now(), "stage": "S3"}
        )
        self._write_json(self.auto_promotions_path, document)
        return document["count"]

    def _read_stage_doc(self) -> Dict[str, Any]:
        if not self.stage_path.exists():
            return {"stage": "S1", "history": []}
        document = json.loads(self.stage_path.read_text(encoding="utf-8"))
        document.setdefault("stage", "S1")
        document.setdefault("history", [])
        return document

    def _notify(self, event: Dict[str, Any]) -> None:
        if self.notifier is not None:
            self.notifier(event)
            return
        path = self.root / "notifications.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def _audit(self, event_name: str, payload: Dict[str, Any]) -> None:
        self.breaker_audit_path.parent.mkdir(parents=True, exist_ok=True)
        row = {"event": event_name, "at": self._now()}
        row.update(payload)
        with self.breaker_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def _now(self) -> str:
        return self.clock().isoformat()

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
