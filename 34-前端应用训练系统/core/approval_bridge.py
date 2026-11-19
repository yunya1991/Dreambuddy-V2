# -*- coding: utf-8 -*-
"""P0-D3D: ApprovalBridge —— GateFlow 的唯一写入者。

Hermes/飞书只能提交签名的 ApprovalGrant；Bridge 负责验签、幂等与写事件。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional

from core.feishu_authorization_bridge import ApprovalGrant, verify_grant


class JsonlGateFlowSink:
    """ApprovalBridge → GateFlow 事件 outbox（append-only JSONL）。"""

    def __init__(self, path: str) -> None:
        self.path = str(path)

    def append(self, event: Dict[str, Any]) -> bool:
        try:
            if not isinstance(event, dict):
                return False
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False


class ApprovalBridge:
    _CONTEXT_KEYS = ("task_id", "gate_id", "gate_kind", "gate_run_id", "node_id")

    def __init__(self, secret: str, gateflow_sink: Any = None) -> None:
        self.secret = secret
        self.sink = gateflow_sink if hasattr(gateflow_sink, "append") else []
        self._seen_requests = set()
        self._used_nonces = set()
        self._lock = threading.Lock()

    def write_grant(
        self,
        grant: Any,
        now: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """验签通过后写入；同 request_id 幂等，同 nonce 拒绝。

        context 用于把 task/gate 定位一并写入 outbox，供 GateFlow 消费者推进；
        不参与签名（签名只覆盖 Grant 本身）。
        """
        if not isinstance(grant, ApprovalGrant):
            return False
        # 先验签/哈希/过期，不检查 nonce，保证重复请求可幂等返回
        if not verify_grant(grant, self.secret, used_nonces=set(), now=now):
            return False
        with self._lock:
            if grant.request_id in self._seen_requests:
                return True
            if grant.nonce in self._used_nonces:
                return False
            self._seen_requests.add(grant.request_id)
            self._used_nonces.add(grant.nonce)
            event: Dict[str, Any] = {
                "type": "approval.granted",
                "request_id": grant.request_id,
                "grant_id": grant.grant_id,
                "grant_hash": grant.grant_hash,
                "scope": list(grant.scope),
                "subject": grant.subject,
                "grant": grant.to_dict(),
            }
            if isinstance(context, dict):
                for key in self._CONTEXT_KEYS:
                    if context.get(key):
                        event[key] = context[key]
            self.sink.append(event)
            return True

    @staticmethod
    def reject_direct_write(source: str) -> bool:
        """返回 True 表示允许直写；Hermes 直写一律拒绝。"""
        return str(source or "").lower() != "hermes"
