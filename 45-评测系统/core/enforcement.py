# -*- coding: utf-8 -*-
"""
enforcement.py — 门禁执行器：凭证卡点 + 双凭证（P3-2 / P3-3 / P3-4）
======================================================================
职责（PLAN P3-2/P3-3/P3-4 验收 / SPEC §4 / §13.3 / §7 边界表）：
- 部署（`deploy`）与 L0 沉淀（`l0_settle`）共用同一裁决入口：无有效凭证 → 拒绝
- 双凭证（P3-4）：`require_approval=True` 时还必须持有有效的 27 审批凭证，
  缺失、过期或未通过一律拒绝（互不豁免）
- 影子模式（`gate.shadow=true`，用户硬约束）：只记录 `SHADOW_WOULD_BLOCK`，
  不阻断现有流程；转实盘（shadow=false）后同代码路径直接拦截
- 每次裁决写审计（`storage/audit.py`），供 P3-5「全链路审计可查」

退出码语义（复用 §13.4）：0 = 放行 / 影子观测；2 = 拦截。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from storage.audit import AuditLog
from storage.repo import zulu

from core.gate import Credential, Gate, GateError

KINDS = ("deploy", "l0_settle")

EXIT_ALLOW = 0
EXIT_BLOCK = 2


class EnforcementError(Exception):
    """门禁执行参数非法（未知 kind）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class EnforcementDecision:
    """一次门禁裁决（含影子观测结论与依据）。"""

    kind: str
    eval_id: str
    mode: str  # shadow / live
    decision: str  # PASS / BLOCK / SHADOW_WOULD_BLOCK
    reasons: tuple[str, ...] = ()
    approval_id: str | None = None
    credential: Credential | None = None
    at: str = ""

    @property
    def allowed(self) -> bool:
        """影子模式下不阻断（fail-open 观测）；实盘 BLOCK 才拒绝。"""
        return self.decision != "BLOCK"

    @property
    def exit_code(self) -> int:
        return EXIT_ALLOW if self.allowed else EXIT_BLOCK

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "eval_id": self.eval_id,
            "mode": self.mode,
            "decision": self.decision,
            "allowed": self.allowed,
            "exit_code": self.exit_code,
            "reasons": list(self.reasons),
            "approval_id": self.approval_id,
            "credential": self.credential.to_dict() if self.credential else None,
            "at": self.at,
        }


class Enforcer:
    """部署 / L0 沉淀门禁执行器。"""

    def __init__(
        self,
        gate: Gate,
        audit: AuditLog | None = None,
        shadow: bool = True,
        approvals: Callable[[str], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._gate = gate
        self._audit = audit
        self._shadow = shadow
        self._approvals = approvals
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def shadow(self) -> bool:
        return self._shadow

    def enforce(
        self,
        kind: str,
        eval_id: str,
        *,
        credential: Credential | None = None,
        approval_id: str | None = None,
        require_approval: bool = False,
    ) -> EnforcementDecision:
        if kind not in KINDS:
            raise EnforcementError("unknown_kind", f"kind 须为 {KINDS}，收到 {kind!r}")

        reasons: list[str] = []
        resolved: Credential | None = None

        if credential is None:
            try:
                resolved = self._gate.issue(eval_id, purpose=kind)
            except GateError as exc:
                reasons.append(str(exc))
        else:
            try:
                resolved = self._gate.verify(credential, purpose=kind)
            except GateError as exc:
                reasons.append(str(exc))

        approval_ok = True
        if require_approval:
            approval_ok = False
            if not approval_id:
                reasons.append("approval_missing: 策略上线需 27 审批凭证（P3-4）")
            elif self._approvals is None:
                reasons.append("approval_missing: 未装配 27 审批查询器（fail-closed）")
            else:
                try:
                    approval_ok = bool(self._approvals(approval_id))
                except Exception as exc:  # noqa: BLE001 — 审批查询异常按未通过
                    reasons.append(f"approval_error: {exc}")
                    approval_ok = False
                if not approval_ok:
                    reasons.append(f"approval_invalid: 审批 {approval_id} 缺失/过期/未通过（P3-4）")

        passed = resolved is not None and approval_ok
        if passed:
            decision = "PASS"
        elif self._shadow:
            decision = "SHADOW_WOULD_BLOCK"
        else:
            decision = "BLOCK"

        record = EnforcementDecision(
            kind=kind,
            eval_id=eval_id,
            mode="shadow" if self._shadow else "live",
            decision=decision,
            reasons=tuple(reasons),
            approval_id=approval_id,
            credential=resolved,
            at=zulu(self._clock()),
        )
        if self._audit is not None:
            self._audit.append(record.to_dict())
        return record
