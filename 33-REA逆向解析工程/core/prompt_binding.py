#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_binding.py — 33-REA 侧 l2.worker.rea 运行时绑定（SPEC-57 §8 P6）

定位：
  REA 内核**不调用大模型**（见 core/hypothesis.py 设计边界），investigation_prompt
  由宿主 agent 消费。本模块负责把该资产接进 REA 的可审计链路：
    1. render    —— 资产正文 + 宪法/人格注入，供宿主直接使用；
    2. ai_context —— 给 S33_rea_audit 的 provenance 补 prompt_id/version/fingerprint；
    3. gate      —— 对调查结论做 C-01..C-12 出口校验。

硬约束：全部 FAIL-OPEN；57 运行时不可用时返回原 ai_context（或空注入）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

PROMPT_ID = "l2.worker.rea"
_RUNTIME = Path(__file__).resolve().parents[2] / "57-Agent提示词工程" / "runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

_IMPORT_ERROR = ""


def _bridge():
    try:
        import l2_prompt_bridge

        return l2_prompt_bridge
    except Exception as exc:  # noqa: BLE001 — 57 不可用不得阻断 REA
        global _IMPORT_ERROR
        _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def render_investigation(
    variables: Optional[Dict[str, Any]] = None,
    *,
    tools: Iterable[str] = (),
) -> Dict[str, Any]:
    bridge = _bridge()
    if bridge is None:
        return {"prompt_id": PROMPT_ID, "injected": False, "meta": None, "error": _IMPORT_ERROR}
    return bridge.render(PROMPT_ID, variables=variables, tools=tools)


def enrich_ai_context(
    ai_context: Optional[Dict[str, Any]],
    *,
    model: str = "",
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """给审计 provenance 补 L2 prompt 绑定；已有 prompt_hash 时保留调用方口径。"""
    ctx: Dict[str, Any] = dict(ai_context or {})
    bridge = _bridge()
    if bridge is None:
        return ctx
    try:
        rendered = bridge.render(PROMPT_ID, variables=variables, include_asset=False)
        meta = rendered.get("meta") or {}
        if not meta.get("prompt_fingerprint"):
            return ctx
        ctx.setdefault("prompt_id", meta.get("prompt_id"))
        ctx.setdefault("prompt_version", meta.get("prompt_version"))
        ctx.setdefault("prompt_hash", meta.get("prompt_fingerprint"))
        ctx.setdefault("constitution_version", meta.get("constitution_version"))
        if model:
            ctx.setdefault("model", model)
        ctx.setdefault("bound_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return ctx
    return ctx


def gate(payload: Any, *, evidence: Optional[str] = "partial") -> Dict[str, Any]:
    bridge = _bridge()
    if bridge is None:
        return {"verdict": "unknown", "ok": False, "error": _IMPORT_ERROR}
    return bridge.gate(PROMPT_ID, payload, evidence=evidence)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="l2.worker.rea 运行时绑定 CLI")
    ap.add_argument("cmd", choices=["verify", "render", "ai-context", "gate"])
    ap.add_argument("--vars", default="")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    variables = json.loads(args.vars) if args.vars else None
    if args.cmd == "verify":
        bridge = _bridge()
        if bridge is None:
            print(json.dumps({"error": _IMPORT_ERROR}, ensure_ascii=False))
            return 1
        print(json.dumps(bridge.verify(PROMPT_ID), ensure_ascii=False, indent=2))
        return 0
    if args.cmd in ("render", "ai-context"):
        payload = (
            render_investigation(variables)
            if args.cmd == "render"
            else enrich_ai_context({}, variables=variables)
        )
        if args.cmd == "render":
            payload.pop("asset_text", None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    raw = Path(args.output).read_text(encoding="utf-8") if args.output else "{}"
    print(json.dumps(gate(json.loads(raw)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
