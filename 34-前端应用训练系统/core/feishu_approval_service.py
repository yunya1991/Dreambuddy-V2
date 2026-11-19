# -*- coding: utf-8 -*-
"""P0-D3D Phase 2: 真实飞书审批服务（授权通道 → 签名 Grant → ApprovalBridge）。

硬约束：
  - GateFlow 唯一写入者仍是 ApprovalBridge；飞书只提供“人是否批准”的事实；
  - 高风险 / live / 不可逆 / 安全 / 策略上线 / 生产写：永不自动审批；
  - 紧急运维（可逆、低/中风险）仅限 UrgentPolicy 白名单可预授权；
  - 所有失败 FAIL-OPEN：返回 pending/blocked，不把异常抛进主链路；
  - 审批记录 append-only JSONL，重启后可继续轮询。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.approval_bridge import ApprovalBridge, JsonlGateFlowSink
from core.feishu_approval_client import FeishuApprovalClient, FeishuConfig, FeishuResult
from core.feishu_authorization_bridge import ApprovalRequest, build_grant
from core.urgent_policy import HARD_EXCLUSIONS, UrgentPolicyRegistry

PENDING = "pending"
GRANTED = "granted"
REJECTED = "rejected"
BLOCKED = "blocked"
UNKNOWN = "unknown"

_DEAD_STATUSES = frozenset({"CANCELED", "CANCELLED", "DELETED"})


@dataclass(frozen=True)
class ApprovalTicket:
    request_id: str
    instance_code: str
    status: str
    gate_run_id: str = ""
    node_id: str = ""
    action: str = ""
    scope: Tuple[str, ...] = ()
    ttl_s: float = 3600.0
    requested_by: str = ""
    reason: str = ""
    high_risk: bool = False
    submitted_at: float = 0.0
    updated_at: float = 0.0
    grant_id: str = ""
    error: str = ""
    auto_approved: bool = False


@dataclass(frozen=True)
class SubmitOutcome:
    request_id: str
    status: str
    ok: bool = True
    instance_code: str = ""
    grant_id: str = ""
    auto_approved: bool = False
    error: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class PollOutcome:
    request_id: str
    status: str
    ok: bool = True
    instance_code: str = ""
    grant_id: str = ""
    error: str = ""
    retryable: bool = False


def build_default_form(request: ApprovalRequest) -> List[Dict[str, Any]]:
    """飞书审批表单（widget 列表，与现有交易审批单结构一致）。"""
    return [
        {"id": "request_id", "type": "input", "value": request.request_id},
        {"id": "task_id", "type": "input", "value": request.task_id},
        {"id": "gate_id", "type": "input", "value": request.gate_id},
        {"id": "gate_run_id", "type": "input", "value": request.gate_run_id},
        {"id": "node_id", "type": "input", "value": request.node_id},
        {"id": "action", "type": "input", "value": request.action},
        {"id": "scope", "type": "input", "value": ", ".join(request.scope)},
        {"id": "risk", "type": "input", "value": "high" if request.high_risk else "normal"},
        {"id": "requested_by", "type": "input", "value": request.requested_by},
        {"id": "reason", "type": "textarea", "value": request.reason},
    ]


def _has_hard_exclusion(request: ApprovalRequest) -> bool:
    tokens = [str(request.action or "").lower()]
    tokens.extend(str(item).lower() for item in request.scope)
    for token in tokens:
        if not token:
            continue
        for excluded in HARD_EXCLUSIONS:
            if excluded in token:
                return True
    return False


def _request_from_record(record: Dict[str, Any]) -> Optional[ApprovalRequest]:
    try:
        request_id = str(record.get("request_id") or "")
        if not request_id:
            return None
        raw_scope = record.get("scope")
        if isinstance(raw_scope, str):
            scope: Tuple[str, ...] = (raw_scope,)
        elif isinstance(raw_scope, (list, tuple)):
            scope = tuple(str(item) for item in raw_scope)
        else:
            scope = ()
        return ApprovalRequest(
            request_id=request_id,
            gate_run_id=str(record.get("gate_run_id") or ""),
            node_id=str(record.get("node_id") or ""),
            action=str(record.get("action") or ""),
            scope=scope,
            ttl_s=float(record.get("ttl_s") or 3600.0),
            requested_by=str(record.get("requested_by") or ""),
            reason=str(record.get("reason") or ""),
            high_risk=bool(record.get("high_risk")),
            task_id=str(record.get("task_id") or ""),
            gate_id=str(record.get("gate_id") or ""),
            gate_kind=str(record.get("gate_kind") or ""),
        )
    except Exception:
        return None


class FeishuApprovalService:
    """审批编排：提交真实飞书实例 / 轮询 / 签名回写 / 预授权自动审批。"""

    def __init__(
        self,
        client: FeishuApprovalClient,
        bridge: ApprovalBridge,
        secret: str,
        *,
        approval_code: str,
        requester_user_id: str,
        approver_user_id: str = "",
        registry_path: str = "",
        urgent: Optional[UrgentPolicyRegistry] = None,
        key_id: str = "approval-key-2026-11",
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.client = client
        self.bridge = bridge
        self.secret = str(secret or "")
        self.approval_code = str(approval_code or "")
        self.requester_user_id = str(requester_user_id or "")
        self.approver_user_id = str(approver_user_id or "")
        self.registry_path = str(registry_path or "")
        self.urgent = urgent
        self.key_id = key_id
        self._clock = clock or time.time
        self._records: Dict[str, Dict[str, Any]] = {}
        self._by_instance: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._load_registry()

    # ── 构造 ──────────────────────────────────────────────────────────────
    @classmethod
    def from_env(
        cls,
        client: Optional[FeishuApprovalClient] = None,
        bridge: Optional[ApprovalBridge] = None,
        *,
        environ: Optional[Dict[str, str]] = None,
        registry_path: str = "",
        **kwargs: Any,
    ) -> Optional["FeishuApprovalService"]:
        env = os.environ if environ is None else environ
        secret = str(env.get("FEISHU_APPROVAL_SECRET") or "").strip()
        approval_code = str(env.get("FEISHU_APPROVAL_CODE") or "").strip()
        requester = str(env.get("FEISHU_REQUESTER_USER_ID") or "").strip()
        if not secret or not approval_code or not requester:
            return None
        client = client or FeishuApprovalClient(FeishuConfig.from_env(env))
        bridge = bridge or ApprovalBridge(secret=secret)
        return cls(
            client,
            bridge,
            secret,
            approval_code=approval_code,
            requester_user_id=requester,
            approver_user_id=str(env.get("FEISHU_APPROVER_USER_ID") or ""),
            registry_path=str(env.get("FEISHU_APPROVAL_REGISTRY") or registry_path),
            key_id=str(env.get("FEISHU_APPROVAL_KEY_ID") or "approval-key-2026-11"),
            **kwargs,
        )

    # ── 记录 ──────────────────────────────────────────────────────────────
    def _load_registry(self) -> None:
        if not self.registry_path or not os.path.exists(self.registry_path):
            return
        try:
            with open(self.registry_path, encoding="utf-8") as fh:
                for line in fh:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        record = json.loads(text)
                    except Exception:
                        continue
                    if not isinstance(record, dict):
                        continue
                    request_id = str(record.get("request_id") or "")
                    if not request_id:
                        continue
                    self._records[request_id] = record
                    instance_code = str(record.get("instance_code") or "")
                    if instance_code:
                        self._by_instance[instance_code] = request_id
        except Exception:
            return

    def _apply(self, record: Dict[str, Any]) -> None:
        with self._lock:
            self._records[str(record["request_id"])] = record
            instance_code = str(record.get("instance_code") or "")
            if instance_code:
                self._by_instance[instance_code] = str(record["request_id"])
        if not self.registry_path:
            return
        try:
            os.makedirs(os.path.dirname(self.registry_path) or ".", exist_ok=True)
            with open(self.registry_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass  # FAIL-OPEN：内存态仍可用，下轮重试

    def _record(
        self,
        request: ApprovalRequest,
        *,
        status: str,
        instance_code: str = "",
        grant_id: str = "",
        error: str = "",
        auto_approved: bool = False,
    ) -> Dict[str, Any]:
        now = float(self._clock())
        record = {
            "request_id": request.request_id,
            "instance_code": instance_code,
            "status": status,
            "gate_run_id": request.gate_run_id,
            "node_id": request.node_id,
            "action": request.action,
            "scope": list(request.scope),
            "ttl_s": float(request.ttl_s),
            "requested_by": request.requested_by,
            "reason": request.reason,
            "high_risk": bool(request.high_risk),
            "task_id": request.task_id,
            "gate_id": request.gate_id,
            "gate_kind": request.gate_kind,
            "grant_id": grant_id,
            "error": error,
            "auto_approved": bool(auto_approved),
            "updated_at": now,
        }
        previous = self._records.get(request.request_id) or {}
        if (
            previous.get("status") == status
            and previous.get("instance_code") == instance_code
            and previous.get("grant_id") == grant_id
            and previous.get("error") == error
            and bool(previous.get("auto_approved")) == bool(auto_approved)
        ):
            return previous  # 状态未变化：不重复落盘，避免轮询把 registry 撑爆
        record["submitted_at"] = float(previous.get("submitted_at") or now)
        self._apply(record)
        return record

    def tickets(self) -> List[ApprovalTicket]:
        with self._lock:
            records = list(self._records.values())
        tickets: List[ApprovalTicket] = []
        for record in records:
            try:
                tickets.append(
                    ApprovalTicket(
                        request_id=str(record.get("request_id") or ""),
                        instance_code=str(record.get("instance_code") or ""),
                        status=str(record.get("status") or UNKNOWN),
                        gate_run_id=str(record.get("gate_run_id") or ""),
                        node_id=str(record.get("node_id") or ""),
                        action=str(record.get("action") or ""),
                        scope=tuple(record.get("scope") or ()),
                        ttl_s=float(record.get("ttl_s") or 0.0),
                        requested_by=str(record.get("requested_by") or ""),
                        reason=str(record.get("reason") or ""),
                        high_risk=bool(record.get("high_risk")),
                        submitted_at=float(record.get("submitted_at") or 0.0),
                        updated_at=float(record.get("updated_at") or 0.0),
                        grant_id=str(record.get("grant_id") or ""),
                        error=str(record.get("error") or ""),
                        auto_approved=bool(record.get("auto_approved")),
                    )
                )
            except Exception:
                continue
        return tickets

    def pending_requests(self) -> List[ApprovalRequest]:
        requests: List[ApprovalRequest] = []
        for ticket in self.tickets():
            if ticket.status != PENDING or not ticket.instance_code:
                continue
            record = self._records.get(ticket.request_id) or {}
            request = _request_from_record(record)
            if request is not None:
                requests.append(request)
        return requests

    def _context(self, request: ApprovalRequest) -> Dict[str, Any]:
        """写入 outbox 的目标定位，供 GateFlow 消费者推进。"""
        return {
            "task_id": request.task_id,
            "gate_id": request.gate_id,
            "gate_kind": request.gate_kind,
            "gate_run_id": request.gate_run_id,
            "node_id": request.node_id,
        }

    # ── 预授权判定 ────────────────────────────────────────────────────────
    def _can_auto_approve(self, request: ApprovalRequest, policy_id: str, task_class: str) -> bool:
        if request.high_risk:
            return False
        if _has_hard_exclusion(request):
            return False
        if not policy_id or not task_class or self.urgent is None:
            return False
        return bool(self.urgent.can_auto_approve(policy_id, task_class))

    # ── 提交 ──────────────────────────────────────────────────────────────
    def submit(
        self,
        request: ApprovalRequest,
        form_values: Optional[List[Dict[str, Any]]] = None,
        *,
        policy_id: str = "",
        task_class: str = "",
        notify_chat_id: str = "",
    ) -> SubmitOutcome:
        if not isinstance(request, ApprovalRequest):
            return SubmitOutcome(request_id="", status=BLOCKED, ok=False, error="invalid_request")

        # 1) 仅白名单紧急运维可预授权自动审批。
        if self._can_auto_approve(request, policy_id, task_class):
            now = float(self._clock())
            grant = build_grant(
                request,
                subject="policy:%s" % policy_id,
                secret=self.secret,
                issued_at=now,
                nonce="%s-auto-%s" % (request.request_id, now),
                key_id=self.key_id,
            )
            if grant is not None and self.bridge.write_grant(
                grant, now=now, context=self._context(request)
            ):
                self._record(
                    request,
                    status=GRANTED,
                    grant_id=grant.grant_id,
                    auto_approved=True,
                )
                return SubmitOutcome(
                    request_id=request.request_id,
                    status=GRANTED,
                    instance_code="",
                    grant_id=grant.grant_id,
                    auto_approved=True,
                )
            self._record(request, status=BLOCKED, error="grant_write_failed")
            return SubmitOutcome(
                request_id=request.request_id,
                status=BLOCKED,
                ok=False,
                error="grant_write_failed",
            )

        # 2) 真实飞书审批实例。
        if not self.client.configured:
            self._record(request, status=BLOCKED, error="feishu_not_configured")
            return SubmitOutcome(
                request_id=request.request_id,
                status=BLOCKED,
                ok=False,
                error="feishu_not_configured",
            )

        form = form_values if form_values is not None else build_default_form(request)
        result = self.client.create_approval_instance(
            self.approval_code,
            form,
            self.requester_user_id,
            uuid=request.request_id,
        )
        if not result.ok:
            self._record(request, status=BLOCKED, error=result.error)
            return SubmitOutcome(
                request_id=request.request_id,
                status=BLOCKED,
                ok=False,
                error=result.error,
                retryable=result.retryable,
            )

        instance_code = str(result.data.get("instance_code") or "")
        self._record(request, status=PENDING, instance_code=instance_code)
        if notify_chat_id:
            self.client.send_message(
                notify_chat_id,
                "【待审批】%s | %s | %s" % (request.request_id, request.action, request.reason),
            )
        return SubmitOutcome(
            request_id=request.request_id,
            status=PENDING,
            instance_code=instance_code,
        )

    # ── 轮询 ──────────────────────────────────────────────────────────────
    def poll(
        self,
        instance_code: str = "",
        request: Optional[ApprovalRequest] = None,
    ) -> PollOutcome:
        record: Dict[str, Any] = {}
        if request is None:
            request_id = self._by_instance.get(str(instance_code or ""))
            record = self._records.get(request_id or "") or {}
            request = _request_from_record(record)
        if not isinstance(request, ApprovalRequest):
            return PollOutcome(
                request_id=str((record or {}).get("request_id") or ""),
                status=UNKNOWN,
                ok=False,
                error="request_not_found",
            )
        instance_code = str(instance_code or (record or {}).get("instance_code") or "")
        if not instance_code:
            return PollOutcome(
                request_id=request.request_id,
                status=BLOCKED,
                ok=False,
                error="instance_code_required",
            )

        result: FeishuResult = self.client.get_approval_status(instance_code)
        if not result.ok:
            # FAIL-OPEN：通道失败不改变审批真相，保持 pending 等下轮。
            self._record(
                request,
                status=PENDING,
                instance_code=instance_code,
                error=result.error,
            )
            return PollOutcome(
                request_id=request.request_id,
                status=PENDING,
                instance_code=instance_code,
                error=result.error,
                retryable=result.retryable,
            )

        status = str(result.data.get("status") or "UNKNOWN").upper()
        if status == "APPROVED":
            now = float(self._clock())
            subject_id = str(result.data.get("approver") or self.approver_user_id or "unknown")
            grant = build_grant(
                request,
                subject="feishu:%s" % subject_id,
                secret=self.secret,
                issued_at=now,
                nonce="%s-%s" % (request.request_id, now),
                key_id=self.key_id,
            )
            if grant is None or not self.bridge.write_grant(
                grant, now=now, context=self._context(request)
            ):
                self._record(
                    request,
                    status=BLOCKED,
                    instance_code=instance_code,
                    error="grant_write_failed",
                )
                return PollOutcome(
                    request_id=request.request_id,
                    status=BLOCKED,
                    ok=False,
                    instance_code=instance_code,
                    error="grant_write_failed",
                )
            self._record(
                request,
                status=GRANTED,
                instance_code=instance_code,
                grant_id=grant.grant_id,
            )
            return PollOutcome(
                request_id=request.request_id,
                status=GRANTED,
                instance_code=instance_code,
                grant_id=grant.grant_id,
            )

        if status == "REJECTED":
            self._record(request, status=REJECTED, instance_code=instance_code)
            return PollOutcome(
                request_id=request.request_id,
                status=REJECTED,
                instance_code=instance_code,
            )

        if status in _DEAD_STATUSES:
            error = "instance_%s" % status.lower()
            self._record(
                request,
                status=BLOCKED,
                instance_code=instance_code,
                error=error,
            )
            return PollOutcome(
                request_id=request.request_id,
                status=BLOCKED,
                ok=False,
                instance_code=instance_code,
                error=error,
            )

        if status == "PENDING":
            self._record(request, status=PENDING, instance_code=instance_code)
            return PollOutcome(
                request_id=request.request_id,
                status=PENDING,
                instance_code=instance_code,
            )

        self._record(
            request,
            status=BLOCKED,
            instance_code=instance_code,
            error="unknown_status:%s" % status,
        )
        return PollOutcome(
            request_id=request.request_id,
            status=BLOCKED,
            ok=False,
            instance_code=instance_code,
            error="unknown_status:%s" % status,
        )

    def poll_all(self) -> List[PollOutcome]:
        outcomes: List[PollOutcome] = []
        for request in self.pending_requests():
            record = self._records.get(request.request_id) or {}
            outcomes.append(self.poll(str(record.get("instance_code") or ""), request=request))
        return outcomes


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEFAULT_OUTBOX = os.environ.get("GATEFLOW_APPROVAL_OUTBOX") or os.path.join(
    _PROJECT_ROOT, "3.1-FRONTEND", ".data", "gateflow", "approval_outbox.jsonl"
)
_DEFAULT_REGISTRY = os.environ.get("FEISHU_APPROVAL_REGISTRY") or os.path.join(
    _PROJECT_ROOT, "3.1-FRONTEND", ".data", "gateflow", "approval_registry.jsonl"
)


def _apply_gateflow(url: str) -> Dict[str, Any]:
    """通知前端消费 outbox；FAIL-OPEN，失败不影响审批结果。"""
    headers = {"Content-Type": "application/json"}
    token = str(os.environ.get("APPROVAL_OUTBOX_TOKEN") or "")
    if token:
        headers["x-approval-token"] = token
    request = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            raw = resp.read().decode("utf-8", "replace")
            data = json.loads(raw) if raw else {}
            return data if isinstance(data, dict) else {"raw": data}
    except Exception as exc:  # noqa: BLE001 - FAIL-OPEN
        return {"success": False, "error": str(exc)}


def main(argv: Optional[List[str]] = None) -> int:
    """真实飞书审批轮询入口：pending → 人工结果 → 签名 Grant → outbox → GateFlow。"""
    parser = argparse.ArgumentParser(description="飞书审批轮询（ApprovalBridge 唯一写 outbox）")
    parser.add_argument("--once", action="store_true", help="只跑一轮（launchd/cron 用）")
    parser.add_argument("--interval", type=float, default=30.0, help="常驻轮询间隔秒")
    parser.add_argument("--outbox", default=_DEFAULT_OUTBOX)
    args = parser.parse_args(argv)

    secret = str(os.environ.get("FEISHU_APPROVAL_SECRET") or "")
    if not secret:
        print(
            json.dumps({"ok": False, "error": "FEISHU_APPROVAL_SECRET 未配置"}, ensure_ascii=False)
        )
        return 1
    bridge = ApprovalBridge(secret=secret, gateflow_sink=JsonlGateFlowSink(args.outbox))
    service = FeishuApprovalService.from_env(bridge=bridge, registry_path=_DEFAULT_REGISTRY)
    if service is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "缺少 FEISHU_APP_ID/FEISHU_APP_SECRET、FEISHU_APPROVAL_CODE 或 FEISHU_REQUESTER_USER_ID",
                },
                ensure_ascii=False,
            )
        )
        return 1

    while True:
        outcomes = service.poll_all()
        print(
            json.dumps(
                {
                    "ok": True,
                    "polled": len(outcomes),
                    "outcomes": [outcome.__dict__ for outcome in outcomes],
                },
                ensure_ascii=False,
            )
        )

        # 有新授权时立即触发前端消费（配置 GATEFLOW_APPLY_URL 才启用）
        apply_url = str(os.environ.get("GATEFLOW_APPLY_URL") or "")
        if apply_url and any(outcome.status == GRANTED for outcome in outcomes):
            print(json.dumps({"outbox_apply": _apply_gateflow(apply_url)}, ensure_ascii=False))

        if args.once:
            return 0
        time.sleep(max(1.0, float(args.interval)))


if __name__ == "__main__":
    sys.exit(main())
