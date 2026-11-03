# -*- coding: utf-8 -*-
"""T-DSH-P2 P2-3 RED: Evidence Bundle 引用调用链。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P2·验收(Evidence Bundle 引用调用链)
+ ADR-7(trace_id 唯一观测主轴) + §六 验收层(Evidence Bundle WORM 哈希链)
+ ADR-9(Verifier/45 仅记录裁决结果,凭证随沉淀走)。

契约:
  build_evidence_bundle(trace_id, ticket_id=?, gate_verdict=?) -> bundle
  bundle = {schema_version, trace_id, ticket_id, eval_id, verdict,
            evidence_uri, created_ts, content_hash}
  - content_hash: 内容 sha256(WORM 防篡改,内容变则哈希变)
  attach_evidence_gate(gate, ticket_id=?) -> wrapped gate
  - 内层 gate 放行时: 构建 bundle 写入 context["evidence_bundle"](随沉淀走)
  - 内层 gate 拦截时: 不写证据(未过门禁无凭证沉淀,V6)
  FAIL-OPEN: 坏输入 → bundle None / wrapped gate 仍透传内层结果
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.evidence_bundle import (  # noqa: E402  ModuleNotFoundError → RED
    attach_evidence_gate,
    build_evidence_bundle,
    verify_bundle_hash,
)


def _verdict(v="PASS", eval_id="EV-1", uri="pg://ev/1", trace_id="tr-1"):
    return {"verdict": v, "eval_id": eval_id, "evidence_uri": uri, "trace_id": trace_id}


# ---------- build ----------


def test_build_bundle_fields():
    b = build_evidence_bundle("tr-1", ticket_id="TK-1", gate_verdict=_verdict())
    assert b["schema_version"] == "1.0"
    assert b["trace_id"] == "tr-1"
    assert b["ticket_id"] == "TK-1"
    assert b["eval_id"] == "EV-1"
    assert b["verdict"] == "PASS"
    assert b["evidence_uri"] == "pg://ev/1"
    assert isinstance(b["content_hash"], str) and len(b["content_hash"]) == 64
    assert b["created_ts"]


def test_build_requires_trace_id():
    assert build_evidence_bundle(None) is None
    assert build_evidence_bundle("") is None


def test_content_hash_tamper_evident():
    b1 = build_evidence_bundle("tr-1", gate_verdict=_verdict())
    b2 = build_evidence_bundle("tr-1", gate_verdict=_verdict(eval_id="EV-2"))
    assert b1["content_hash"] != b2["content_hash"]  # 内容变 → 哈希变
    assert verify_bundle_hash(b1) is True
    b1["verdict"] = "BLOCK"  # 篡改
    assert verify_bundle_hash(b1) is False


def test_build_without_verdict_still_chains_trace():
    b = build_evidence_bundle("tr-9")
    assert b["trace_id"] == "tr-9"
    assert b["eval_id"] is None
    assert verify_bundle_hash(b) is True


# ---------- attach gate 包装 ----------


def test_attach_on_allow_writes_bundle_to_context():
    def pass_gate(ctx):
        return True, _verdict()

    wrapped = attach_evidence_gate(pass_gate, ticket_id="TK-7")
    ctx = {"trace_id": "tr-1", "intent": "i"}
    allowed, verdict = wrapped(ctx)
    assert allowed is True
    assert ctx["evidence_bundle"]["eval_id"] == "EV-1"
    assert ctx["evidence_bundle"]["trace_id"] == "tr-1"
    assert ctx["evidence_bundle"]["ticket_id"] == "TK-7"
    assert verdict["verdict"] == "PASS"


def test_attach_on_deny_writes_nothing():
    def block_gate(ctx):
        return False, _verdict(v="BLOCK")

    wrapped = attach_evidence_gate(block_gate)
    ctx = {"trace_id": "tr-1"}
    allowed, _ = wrapped(ctx)
    assert allowed is False
    assert "evidence_bundle" not in ctx  # V6: 未过门禁无凭证


def test_attach_fail_open_passthrough():
    def boom_gate(ctx):
        raise RuntimeError("inner exploded")

    wrapped = attach_evidence_gate(boom_gate)
    allowed, verdict = wrapped({"trace_id": "tr-1"})
    assert allowed is False  # 内层异常 → 拦截透传(fail-closed 同 settle 语义)
    assert verdict["verdict"] == "ERROR"
    assert attach_evidence_gate(None) is None
