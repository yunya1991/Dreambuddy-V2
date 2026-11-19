#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_output_gate.py — L2 出口宪法门禁的运行时封装（SPEC-57 §4.3 / §7 P6）

`constitution_gate.evaluate()` 只接受完整 L2 输出文档；本模块负责把各 lane 的
实际返回值组装成该文档，并统一处理 FAIL-OPEN：

  - 门禁自身异常（模块缺失/注册表不可读）→ verdict=unknown，不阻断业务；
  - 判定结果原样返回，由 lane 决定 deny 阻断 / needs_review / degraded 标记。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

_RUNTIME = Path(__file__).resolve().parent
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))


def _normalize_output(output: Any, evidence: Optional[str]) -> Any:
    """C-04 要求 evidence 显式分级；字符串输出包装为对象后注入。"""
    if isinstance(output, dict):
        payload = dict(output)
        if evidence and "evidence" not in payload:
            quality = payload.get("quality")
            if not isinstance(quality, dict) or "evidence" not in quality:
                payload["quality"] = {**(quality or {}), "evidence": evidence}
        return payload
    return {
        "text": "" if output is None else str(output),
        "quality": {"evidence": evidence or "none"},
    }


def gate_output(
    prompt_id: str,
    output: Any,
    *,
    context: Optional[Dict[str, Any]] = None,
    tools: Iterable[str] = (),
    budget: Optional[Dict[str, int]] = None,
    evidence: Optional[str] = None,
    output_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """对一次 L2 出口做宪法校验；异常一律 FAIL-OPEN（verdict=unknown）。"""
    tool_list = [str(t) for t in tools]
    try:
        import constitution_gate as gate
        import prompt_context_57 as pc

        doc = {
            "prompt_id": prompt_id,
            "meta": pc.build_meta(prompt_id, tools=tool_list),
            "output": _normalize_output(output, evidence),
            "tool_set": {"declared": tool_list, "snapshot": tool_list},
            "context": context or {},
            "budget": budget or {},
            "output_contract": output_contract or {},
        }
        result = gate.evaluate(doc)
        return {
            "ok": bool(result.get("ok")),
            "verdict": str(result.get("verdict", "unknown")),
            "violations": result.get("violations", []),
            "gates": result.get("gates", {}),
        }
    except Exception as exc:  # noqa: BLE001 — 门禁自身故障不阻断业务
        return {
            "ok": False,
            "verdict": "unknown",
            "violations": [],
            "gates": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


def should_block(result: Dict[str, Any]) -> bool:
    return result.get("verdict") == "deny"


def is_degraded(result: Dict[str, Any]) -> bool:
    return result.get("verdict") in ("needs_review", "degraded", "unknown")
