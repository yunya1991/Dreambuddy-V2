"""mcp_shells/_shared/envelope_wrap.py — L0 统一信封的 MCP 壳外层包装层

SPEC-L0 §3.1 信封：{ok, data, source, timestamp, degraded, meta,
  version, trace_id, idempotency_key, error_code}
MCP 壳的 6 个工具（recall/record/verify/stats/health/unified_search）
当前返回纯业务 JSON。本模块提供 _wrap() 工厂，**只外层包信封、不侵入业务体**。

硬约束：
  - 业务体原样透传到 envelope.data，零删零改
  - 对 unified_search / health 已半信封（自带 ok/source/degraded）做 merge
  - envelope.version = "0.1"（本层版本，与壳 envelope_version 一致）
  - trace_id 默认从 env MCP_TRACE_ID 取（宿主 MCP 传入），否则空串
  - idempotency_key 默认空（壳层幂等由宿主 Mandate 或调用方保证）
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

ENVELOPE_VERSION = "0.1"

# 注册表自描述能力（v1.1-mcp）：壳运行时注入 meta.{shadow_capable, oracle_verifiable, config_version}
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"
_CAPS_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _registry_caps(source: str) -> Dict[str, Any]:
    """按壳 source 查注册表 capabilities。FAIL-OPEN：任何异常返回空 dict。"""
    global _CAPS_CACHE
    if os.environ.get("MCP_CAPS_INJECT", "1") == "0":
        return {}
    try:
        if _CAPS_CACHE is None:
            import yaml  # 惰性导入，壳进程默认不依赖

            with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
                reg = yaml.safe_load(f) or {}
            caps: Dict[str, Dict[str, Any]] = {}
            for shell in reg.get("shells", []) or []:
                sid = shell.get("shell_id")
                if not sid:
                    continue
                item = dict(shell.get("capabilities") or {})
                item["config_version"] = str(reg.get("registry_version", ""))
                caps[sid] = item
            _CAPS_CACHE = caps
        return _CAPS_CACHE.get(source, {})
    except Exception:  # noqa: BLE001 — FAIL-OPEN，不阻断信封
        return {}


def _inject_caps(meta: Dict[str, Any], source: str) -> Dict[str, Any]:
    """把注册表能力字段补进 meta（只补缺失键，不覆盖调用方显式值）。"""
    caps = _registry_caps(source)
    for key in ("shadow_capable", "oracle_verifiable", "config_version"):
        if key in caps and key not in meta:
            meta[key] = caps[key]
    return meta


# SPEC-L0 §3.1 ERROR_CODES 枚举
ERROR_CODES = {
    "not_found",
    "unavailable",
    "conflict",
    "invalid",
    "timeout",
    "degraded",
    "all_sources_unavailable",
}


def wrap(
    data: Any,
    source: str,
    *,
    degraded: bool = False,
    error_code: str = "",
    meta: Optional[Dict[str, Any]] = None,
    trace_id: str = "",
    idempotency_key: str = "",
) -> Dict[str, Any]:
    """通用信封包装。业务体 data 透传到 envelope.data，零删零改。"""
    return {
        "ok": not degraded,
        "data": data,
        "source": source,
        "timestamp": time.time(),
        "degraded": degraded,
        "meta": _inject_caps(dict(meta or {}), source),
        "version": ENVELOPE_VERSION,
        "trace_id": trace_id or os.environ.get("MCP_TRACE_ID", ""),
        "idempotency_key": idempotency_key,
        "error_code": error_code if degraded and error_code else "",
    }


def wrap_merge_partial(
    partial: Dict[str, Any],
    source: str,
    *,
    data_key: str = "result",
    partial_ok_key: str = "ok",
    partial_degraded_key: str = "degraded",
) -> Dict[str, Any]:
    """对 unified_search / health 等已半信封的返回体做 merge。

    保留其内部结构（如 health.l0 聚合、unified_search.sources 明细），
    外层补全缺失的信封字段。
    """
    degraded = bool(partial.get(partial_degraded_key, False))
    ok = bool(partial.get(partial_ok_key, not degraded))

    # 业务体 = 去掉信封关键字段后的剩余部分
    inner = {
        k: v
        for k, v in partial.items()
        if k
        not in {
            "ok",
            "source",
            "degraded",
            "version",
            "trace_id",
            "idempotency_key",
            "error_code",
            "timestamp",
            "meta",
            "data",
        }
    }

    error_code = partial.get("error_code", "")
    # source 参数为权威（调用方声明的壳级 source），partial 自带的旧 source 字段忽略
    return {
        "ok": ok and not degraded,
        "data": inner,
        "source": source,
        "timestamp": partial.get("timestamp", time.time()),
        "degraded": degraded,
        "meta": _inject_caps(dict(partial.get("meta") or {}), source),
        "version": ENVELOPE_VERSION,
        "trace_id": partial.get("trace_id") or os.environ.get("MCP_TRACE_ID", ""),
        "idempotency_key": partial.get("idempotency_key", ""),
        "error_code": error_code if degraded and error_code else "",
    }
