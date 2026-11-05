# -*- coding: utf-8 -*-
"""Worker 工具调用链接线(DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-4/9/10 落线, T-DSH-P4)。

链路: mandate_gate(ADR-4 能力集 + H7 写工具纵深,默认拒绝) → tool→shell 解析
(47 registry 唯一载体,B4) → ShellHandleManager(ADR-10 进程级单壳,Worker 持句柄)
→ 壳调用。本模块只做编排,不含门禁规则/壳生命周期/stdio 细节(各自模块单一职责)。

错误语义(47 SPEC §3.2 B1:Worker 工具调用=主功能,禁止 FAIL-OPEN 伪装无结果):
  disabled / forbidden / not_found / invalid / unavailable(+meta.degraded=true)
  —— 编排层错误码 ⊇ 44 六值枚举(disabled/forbidden 为编排层扩充)。

硬约束: H2 开关 enable_worker_tool_call 默认关;审计留痕 recorder 异常吞掉(V4)。
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Optional

import yaml

_SWITCH = "enable_worker_tool_call"

_DEFAULT_REGISTRY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "47-MCP管理系统",
    "registry",
    "mcp_capabilities.yaml",
)


# registry 磁盘读取缓存(D4 延迟治理): {path: (mtime, payload)};mtime 变即重读,
# 文件消失回退空载体(deny-by-default 语义不变——空 map/空 roles 一律拒)。
_registry_cache: Dict[str, Any] = {}


def _load_registry_doc_cached(path: str) -> Dict[str, Any]:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _registry_cache.get(path)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except Exception:
        doc = {}
    _registry_cache[path] = (mtime, doc)
    return doc


def load_tool_shell_map(registry_path: Optional[str] = None) -> Dict[str, str]:
    """47 registry → {tool_name: shell_id}(只读引用,B4 唯一载体);坏文件 → {}。"""
    try:
        doc = _load_registry_doc_cached(registry_path or _DEFAULT_REGISTRY)
        out: Dict[str, str] = {}
        for spec in doc.get("shells") or []:
            if not isinstance(spec, dict):
                continue
            sid = spec.get("shell_id")
            if not isinstance(sid, str) or not sid:
                continue
            for t in spec.get("tools") or []:
                if isinstance(t, dict) and isinstance(t.get("name"), str):
                    out[t["name"]] = sid
        return out
    except Exception:
        return {}


def _default_checker(role: Any, tool: Any) -> bool:
    """默认门禁: mandate_gate 三件套(roles/write_tools/check);异常 → 拒绝。"""
    try:
        from core.mandate_gate import check_tool_call

        doc = _load_registry_doc_cached(_DEFAULT_REGISTRY)
        roles_raw = doc.get("worker_roles") or {}
        roles = {
            str(r): [str(t) for t in (cfg or {}).get("tools") or []]
            for r, cfg in roles_raw.items()
            if isinstance(r, str)
        }
        write_tools = {
            str(t["name"])
            for spec in doc.get("shells") or []
            if isinstance(spec, dict)
            for t in spec.get("tools") or []
            if isinstance(t, dict)
            and t.get("requires_mandate") is True
            and isinstance(t.get("name"), str)
        }
        decision = check_tool_call(role, tool, roles=roles, write_tools=write_tools)
        return bool(decision.get("allowed"))
    except Exception:
        return False  # deny-by-default


def _fail(code: str, trace_id: Optional[str], degraded: bool = False) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"trace_id": trace_id}
    if degraded:
        meta["degraded"] = True
    return {"ok": False, "data": None, "error_code": code, "meta": meta}


def _fail_degraded(
    code: str,
    trace_id: Optional[str],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """HC-7: shell_degraded 信封 — degraded=True + 自定义 meta(含 reason)。"""
    m: Dict[str, Any] = {"trace_id": trace_id, "degraded": True}
    if meta:
        m.update(meta)
    return {"ok": False, "data": None, "error_code": code, "meta": m}


def _audit(recorder: Optional[Callable[[Dict[str, Any]], None]], entry: Dict[str, Any]) -> None:
    try:
        if recorder is not None:
            recorder(entry)
    except Exception:
        pass  # V4: 审计异常不击穿调用


def call_worker_tool(
    role: Any,
    tool: Any,
    args: Optional[Dict[str, Any]] = None,
    *,
    checker: Optional[Callable[[Any, Any], bool]] = None,
    manager: Any = None,
    flags: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    recorder: Optional[Callable[[Dict[str, Any]], None]] = None,
    registry_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Worker 经门禁 → 句柄 → 壳 调用一个工具,返回统一信封。"""
    entry = {"role": role, "tool": tool, "ok": False, "trace_id": trace_id, "ts": time.time()}
    try:
        enabled = isinstance(flags, dict) and bool(flags.get(_SWITCH, False))
        if not enabled:
            return _audit_and(recorder, entry, _fail("disabled", trace_id))
        if not isinstance(role, str) or not role or not isinstance(tool, str) or not tool:
            return _audit_and(recorder, entry, _fail("invalid", trace_id))

        check = checker if callable(checker) else _default_checker
        try:
            allowed = bool(check(role, tool))
        except Exception:
            allowed = False  # deny-by-default
        if not allowed:
            return _audit_and(recorder, entry, _fail("forbidden", trace_id))

        shell_id = load_tool_shell_map(registry_path).get(tool)
        if shell_id is None:
            return _audit_and(recorder, entry, _fail("not_found", trace_id))

        handle = None
        try:
            if manager is not None:
                handle = manager.get_handle(shell_id)
        except Exception:
            handle = None
        if handle is None:
            return _audit_and(recorder, entry, _fail("unavailable", trace_id, degraded=True))

        # SPEC-DSH-P5 HC-6/HC-7: try-retry-degrade 三态
        # HC-6: 传输层失败(壳 crash/SSH 断连/超时) → 重拉壳 → 重试 1 次
        # HC-7: 重试仍败 → degrade 信封(ok=false,error_code=shell_degraded)
        try:
            result = handle.call(tool, args)
        except Exception as exc:
            # HC-6: 自动重拉壳 + 重试
            if manager is not None:
                retry_handle = None
                try:
                    retry_handle = manager.get_handle(shell_id, force_new=True)
                except Exception:
                    retry_handle = None
                if retry_handle is not None:
                    try:
                        result = retry_handle.call(tool, args)
                    except Exception as retry_exc:
                        # HC-7: 重试仍败 → degrade 信封, 不抛
                        return _audit_and(
                            recorder,
                            entry,
                            _fail_degraded(
                                "shell_degraded",
                                trace_id,
                                meta={"reason": str(retry_exc), "original": str(exc)},
                            ),
                        )
                else:
                    # manager 重拉也拿不到(开关关/超上限) → degrade
                    return _audit_and(
                        recorder,
                        entry,
                        _fail_degraded("shell_degraded", trace_id, meta={"reason": str(exc)}),
                    )
            else:
                # 无 manager → 直接 degrade
                return _audit_and(
                    recorder,
                    entry,
                    _fail_degraded("shell_degraded", trace_id, meta={"reason": str(exc)}),
                )

        if isinstance(result, dict) and "ok" in result:
            envelope = result
            envelope.setdefault("meta", {})
            if isinstance(envelope["meta"], dict):
                envelope["meta"].setdefault("trace_id", trace_id)
        else:
            envelope = {
                "ok": True,
                "data": result,
                "error_code": None,
                "meta": {"trace_id": trace_id},
            }
        return _audit_and(recorder, entry, envelope)
    except Exception:
        return _audit_and(recorder, entry, _fail("unavailable", trace_id, degraded=True))


def _audit_and(recorder, entry, envelope):
    entry["ok"] = bool(envelope.get("ok"))
    _audit(recorder, entry)
    return envelope


__all__ = ["call_worker_tool", "load_tool_shell_map"]
