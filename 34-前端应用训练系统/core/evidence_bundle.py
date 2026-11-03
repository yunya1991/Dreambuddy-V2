# -*- coding: utf-8 -*-
"""Evidence Bundle 引用调用链(T-DSH-P2 P2-3)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P2·验收(Evidence Bundle 引用调用链)
+ ADR-7(trace_id 唯一观测主轴) + §六 验收层(Evidence Bundle WORM 哈希链)
+ V6(未过门禁的产出 0 条进入沉淀——拦截时不写证据,无凭证不沉淀)。

定位: 把 45 裁决凭证(eval_id/evidence_uri/verdict)与 trace_id 绑定为
防篡改证据包(content_hash = sha256),随 context 流入 settle 沉淀,
使每条沉淀可回溯到「哪次评测、哪份证据、哪条调用链」。

硬约束:
  WORM: content_hash 内容寻址,内容变则哈希变(篡改可检测)
  FAIL-OPEN: 坏输入 → None;attach 包装不吞内层结果
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Dict, Optional, Tuple

SCHEMA_VERSION = "1.0"

_BUNDLE_KEYS = (
    "schema_version",
    "trace_id",
    "ticket_id",
    "eval_id",
    "verdict",
    "evidence_uri",
    "created_ts",
)


def _canonical(bundle: Dict[str, Any]) -> str:
    """内容寻址规范化: 固定键序、排除 content_hash 本身。"""
    body = {k: bundle.get(k) for k in _BUNDLE_KEYS}
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def build_evidence_bundle(
    trace_id: Any,
    ticket_id: Optional[str] = None,
    gate_verdict: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """构建证据包。trace_id 缺失 → None(调用链主轴不可缺,ADR-7)。"""
    try:
        if not trace_id:
            return None
        verdict = gate_verdict if isinstance(gate_verdict, dict) else {}
        bundle = {
            "schema_version": SCHEMA_VERSION,
            "trace_id": str(trace_id),
            "ticket_id": ticket_id,
            "eval_id": verdict.get("eval_id"),
            "verdict": verdict.get("verdict"),
            "evidence_uri": verdict.get("evidence_uri"),
            "created_ts": time.time(),
        }
        bundle["content_hash"] = hashlib.sha256(_canonical(bundle).encode("utf-8")).hexdigest()
        return bundle
    except Exception:
        return None


def verify_bundle_hash(bundle: Any) -> bool:
    """WORM 校验: 重算 content_hash 比对,篡改 → False。坏输入 → False。"""
    try:
        if not isinstance(bundle, dict):
            return False
        expect = bundle.get("content_hash")
        if not expect:
            return False
        actual = hashlib.sha256(_canonical(bundle).encode("utf-8")).hexdigest()
        return bool(actual == expect)
    except Exception:
        return False


def attach_evidence_gate(
    gate: Any,
    ticket_id: Optional[str] = None,
) -> Optional[Callable[[Dict[str, Any]], Tuple[bool, Dict[str, Any]]]]:
    """包装 settle gate: 放行时把证据包写入 context["evidence_bundle"] 随沉淀走。

    拦截时不写证据(V6: 未过门禁无凭证);内层异常 → (False, ERROR) 透传拦截
    (与 settle「门禁异常 fail-closed」语义一致)。gate 非 callable → None。
    """
    if not callable(gate):
        return None

    def wrapped(context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        ctx = context if isinstance(context, dict) else {}
        try:
            allowed, verdict = gate(ctx)
        except Exception:
            return False, {"verdict": "ERROR", "trace_id": ctx.get("trace_id")}
        if not isinstance(verdict, dict):
            verdict = {"verdict": None}
        if allowed:
            bundle = build_evidence_bundle(
                ctx.get("trace_id") or verdict.get("trace_id"),
                ticket_id=ticket_id,
                gate_verdict=verdict,
            )
            if bundle is not None:
                ctx["evidence_bundle"] = bundle
        return bool(allowed), verdict

    return wrapped
