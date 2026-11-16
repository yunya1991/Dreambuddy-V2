#!/usr/bin/env python3
"""stats_capability.py — 前端统计能力出口 CLI（TASKS-20261116 T2-1 / T2-3）。

供 `/api/visual/capabilities` 调用：`list / explain / validate / run` 四操作，
每次只输出**一行** JSON（FAIL-OPEN：异常也输出 `{ok:false,degraded:true}` 并退出 0）。

约定：
  - 只读，不写库、不落盘；
  - 前端零重算：数值一律来自 `l1agg` 能力信封；
  - `validate` 只做签名与样本量校验，**不取数**。

用法：
  python3 scripts/stats_capability.py --op list [--domain E] [--q corr] [--limit 50]
  python3 scripts/stats_capability.py --op explain --capability D-E17
  python3 scripts/stats_capability.py --op validate --capability D-A06 --payload '{"values":[...]}'
  python3 scripts/stats_capability.py --op run --capability D-A06 --payload-file /tmp/p.json
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
_L1_DIR = os.path.join(_REPO_ROOT, "54-L1架构能力聚合层")
if _L1_DIR not in sys.path:
    sys.path.insert(0, _L1_DIR)

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def _domain_of(capability_id: str) -> str:
    parts = str(capability_id).split("-")
    return parts[1][:1] if len(parts) > 1 and parts[1] else "OTHER"


def _manifest():
    from l1agg.capabilities.manifest import load

    return load()


def _run_capability():
    from l1agg.capabilities.stats import run_capability

    return run_capability


def _executor(cap: Any):
    module_name, _, attr = str(cap.executor).rpartition(".")
    return getattr(importlib.import_module(f"l1agg.{module_name}"), attr)


def _find(manifest: Any, capability_id: str):
    return next((item for item in manifest.capabilities if item.id == capability_id), None)


def _format(cap: Any) -> Dict[str, Any]:
    return {
        "capability_id": cap.id,
        "domain": _domain_of(cap.id),
        "intent": cap.intent,
        "mode": cap.mode,
        "min_n": cap.min_n,
        "min_span_days": cap.min_span_days,
        "methods": list(cap.methods),
        "data_scope": list(cap.data_scope),
        "visibility": cap.visibility,
        "executor": cap.executor,
        "notes": cap.notes,
    }


def op_list(args: argparse.Namespace) -> Dict[str, Any]:
    manifest = _manifest()
    domain = (args.domain or "").strip().upper()
    query = (args.q or "").strip().lower()
    min_n_max = args.min_n_max
    limit = max(1, min(int(args.limit or DEFAULT_LIMIT), MAX_LIMIT))

    matched: List[Dict[str, Any]] = []
    for cap in sorted(manifest.capabilities, key=lambda c: c.id):
        if domain and _domain_of(cap.id) != domain:
            continue
        if min_n_max is not None and int(cap.min_n or 0) > int(min_n_max):
            continue
        if query:
            haystack = " ".join(
                [cap.id, cap.intent, " ".join(cap.methods), " ".join(cap.data_scope)]
            ).lower()
            if query not in haystack:
                continue
        matched.append(_format(cap))

    counts: Dict[str, int] = {}
    for cap in manifest.capabilities:
        key = _domain_of(cap.id)
        counts[key] = counts.get(key, 0) + 1

    return {
        "ok": True,
        "manifest_version": manifest.version,
        "manifest_updated": manifest.updated,
        "total": len(matched),
        "returned": len(matched[:limit]),
        "domains": [{"domain": k, "count": counts[k]} for k in sorted(counts)],
        "items": matched[:limit],
    }


def op_explain(args: argparse.Namespace) -> Dict[str, Any]:
    capability_id = str(args.capability or "").strip()
    if not capability_id:
        return {"ok": False, "degraded": True, "reason": "capability_id_required"}
    cap = _find(_manifest(), capability_id)
    if cap is None:
        return {"ok": False, "degraded": True, "reason": f"unknown_capability: {capability_id}"}

    payload = _format(cap)
    try:
        signature = inspect.signature(_executor(cap))
        payload["accepted_params"] = [
            name
            for name, item in signature.parameters.items()
            if item.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        ]
        payload["accepts_extra"] = any(
            item.kind == inspect.Parameter.VAR_KEYWORD for item in signature.parameters.values()
        )
        payload["executable"] = True
        # SPEC-54 R1：参数 schema（唯一事实源，含 derived/unsupported 标注）
        from l1agg.capabilities import param_schema

        payload["schema"] = param_schema.for_capability(capability_id)
    except Exception as exc:  # noqa: BLE001
        payload["executable"] = False
        payload["degraded"] = True
        payload["degraded_reason"] = f"executor_unresolved: {type(exc).__name__}"
    return payload


def op_validate(args: argparse.Namespace) -> Dict[str, Any]:
    capability_id = str(args.capability or "").strip()
    if not capability_id:
        return {"ok": False, "degraded": True, "reason": "capability_id_required"}
    cap = _find(_manifest(), capability_id)
    if cap is None:
        return {"ok": False, "degraded": True, "reason": f"unknown_capability: {capability_id}"}

    payload = _load_payload(args)
    if payload is None:
        return {"ok": False, "degraded": True, "reason": "payload_must_be_object"}

    try:
        signature = inspect.signature(_executor(cap))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "degraded": True,
            "reason": f"executor_unresolved: {type(exc).__name__}: {exc}",
        }

    parameters = signature.parameters
    accepts_extra = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values())
    missing = [
        name
        for name, item in parameters.items()
        if item.default is inspect.Parameter.empty
        and item.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and name not in payload
    ]
    unknown = [] if accepts_extra else [key for key in payload if key not in parameters]
    warnings: List[str] = []
    min_n = int(cap.min_n or 0)
    for key in ("values", "series", "returns", "prices", "dates"):
        value = payload.get(key)
        if isinstance(value, (list, tuple)) and len(value) < min_n:
            warnings.append(f"{key} length {len(value)} < min_n {min_n}")

    return {
        "ok": not missing and not unknown and not warnings,
        "capability_id": capability_id,
        "missing_params": missing,
        "unknown_params": unknown,
        "warnings": warnings,
        "min_n": min_n,
        "accepts_extra": accepts_extra,
    }


def op_run(args: argparse.Namespace) -> Dict[str, Any]:
    capability_id = str(args.capability or "").strip()
    if not capability_id:
        return {"ok": False, "degraded": True, "reason": "capability_id_required"}
    payload = _load_payload(args)
    if payload is None:
        return {"ok": False, "degraded": True, "reason": "payload_must_be_object"}
    try:
        envelope = _run_capability()(capability_id, **payload)
    except KeyError:
        return {"ok": False, "degraded": True, "reason": f"unknown_capability: {capability_id}"}
    except TypeError as exc:
        return {"ok": False, "degraded": True, "reason": f"invalid_params: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "degraded": True,
            "reason": f"capability_failed: {type(exc).__name__}: {exc}",
        }
    return {"ok": True, "capability_id": capability_id, "result": envelope}


def _load_payload(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    raw: Optional[str] = None
    if args.payload_file:
        with open(args.payload_file, "r", encoding="utf-8") as fh:
            raw = fh.read()
    elif args.payload:
        raw = args.payload
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


_OPS = {
    "list": op_list,
    "explain": op_explain,
    "validate": op_validate,
    "run": op_run,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="统计能力出口 CLI")
    parser.add_argument("--op", required=True, choices=sorted(_OPS))
    parser.add_argument("--capability", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--q", default="")
    parser.add_argument("--min-n-max", dest="min_n_max", type=int, default=None)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--payload", default="")
    parser.add_argument("--payload-file", dest="payload_file", default="")
    args = parser.parse_args(argv)

    try:
        result = _OPS[args.op](args)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        result = {
            "ok": False,
            "degraded": True,
            "reason": f"cli_failed: {type(exc).__name__}: {exc}",
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
