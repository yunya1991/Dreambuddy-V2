# -*- coding: utf-8 -*-
"""P0-D3D: 飞书授权桥的请求/授权契约。

飞书只做授权通道；ApprovalBridge 才是 GateFlow 唯一写入者。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return ()


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sign(secret: str, payload: Any) -> str:
    return hmac.new(
        str(secret or "").encode("utf-8"),
        _canonical(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    gate_run_id: str
    node_id: str
    action: str
    scope: Tuple[str, ...] = ()
    ttl_s: float = 3600.0
    requested_by: str = ""
    reason: str = ""
    high_risk: bool = False
    # 回写 GateFlow 的目标定位（可选；由发起方传入）
    task_id: str = ""
    gate_id: str = ""
    gate_kind: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", _as_tuple(self.scope))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "gate_run_id": self.gate_run_id,
            "node_id": self.node_id,
            "action": self.action,
            "scope": list(self.scope),
            "ttl_s": self.ttl_s,
            "requested_by": self.requested_by,
            "reason": self.reason,
            "high_risk": self.high_risk,
            "task_id": self.task_id,
            "gate_id": self.gate_id,
            "gate_kind": self.gate_kind,
        }


@dataclass(frozen=True)
class ApprovalGrant:
    grant_id: str
    request_id: str
    subject: str
    scope: Tuple[str, ...]
    ttl_s: float
    signature: str
    signature_alg: str
    key_id: str
    nonce: str
    grant_hash: str
    issued_at: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", _as_tuple(self.scope))

    def payload(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "subject": self.subject,
            "scope": list(self.scope),
            "ttl_s": self.ttl_s,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
        }

    def to_dict(self) -> Dict[str, Any]:
        data = self.payload()
        data.update(
            {
                "grant_id": self.grant_id,
                "signature": self.signature,
                "signature_alg": self.signature_alg,
                "key_id": self.key_id,
                "grant_hash": self.grant_hash,
            }
        )
        return data


def build_grant(
    request: Any,
    subject: str,
    secret: str,
    issued_at: Optional[float] = None,
    nonce: str = "",
    key_id: str = "approval-key-2026-11",
) -> Optional[ApprovalGrant]:
    if not isinstance(request, ApprovalRequest) or not secret:
        return None
    now = float(issued_at if issued_at is not None else time.time())
    nonce = str(nonce or f"{request.request_id}-{now}")
    payload = {
        "request_id": request.request_id,
        "subject": str(subject),
        "scope": sorted(request.scope),
        "ttl_s": float(request.ttl_s),
        "nonce": nonce,
        "issued_at": now,
    }
    signature = _sign(secret, payload)
    grant_hash = "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return ApprovalGrant(
        grant_id="AG-" + grant_hash[7:19],
        request_id=request.request_id,
        subject=str(subject),
        scope=request.scope,
        ttl_s=float(request.ttl_s),
        signature=signature,
        signature_alg="hmac-sha256",
        key_id=key_id,
        nonce=nonce,
        grant_hash=grant_hash,
        issued_at=now,
    )


def verify_grant(
    grant: Any,
    secret: str,
    used_nonces: Optional[Set[str]] = None,
    now: Optional[float] = None,
) -> bool:
    if not isinstance(grant, ApprovalGrant) or not secret:
        return False
    if grant.signature_alg != "hmac-sha256":
        return False
    if used_nonces and grant.nonce in used_nonces:
        return False
    if now is not None and float(now) > float(grant.issued_at) + float(grant.ttl_s):
        return False
    expected_signature = _sign(secret, grant.payload())
    if not hmac.compare_digest(expected_signature, grant.signature):
        return False
    expected_hash = (
        "sha256:" + hashlib.sha256(_canonical(grant.payload()).encode("utf-8")).hexdigest()
    )
    return hmac.compare_digest(expected_hash, grant.grant_hash)
