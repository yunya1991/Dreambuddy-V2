"""统一信封（SPEC-C §3.1）：fetch(scope, params) -> {ok, data, source, timestamp, degraded, meta}

评审 P0-3 新增 4 字段：version / trace_id / idempotency_key / error_code。
error_code 为枚举，禁止自由文本 reason 直出（reason 保留在 meta 内）。
"""
from datetime import datetime
from typing import Any, Dict, Optional

EnvelopeVersion = "l0-v1"

# 错误码枚举（SPEC-C §3.1 四类语义之④）
ERROR_CODES = frozenset({
    "not_found", "unavailable", "conflict", "invalid", "timeout", "degraded",
    "unknown_scope", "fetch_error", "all_sources_unavailable",
})


def envelope(data: Any, source: str, *, degraded: bool = False,
             meta: Optional[Dict] = None, trace_id: str = "",
             idempotency_key: str = "") -> Dict[str, Any]:
    """成功/降级信封。degraded=True 时 meta.reason 必填。"""
    return {
        "ok": not degraded,
        "data": data,
        "source": source,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "degraded": degraded,
        "meta": meta or {},
        "version": EnvelopeVersion,
        "trace_id": trace_id,
        "idempotency_key": idempotency_key,
        "error_code": (meta or {}).get("error_code", "") if degraded else "",
    }


def degraded(source: str, error_code: str, error: str = "",
             data: Any = None, trace_id: str = "") -> Dict[str, Any]:
    """降级信封：error_code 必须取自 ERROR_CODES 枚举。"""
    if error_code not in ERROR_CODES:
        error_code = "degraded"
    meta: Dict[str, Any] = {"reason": error_code}
    if error:
        meta["error"] = str(error)
    meta["error_code"] = error_code
    return envelope(data, source, degraded=True, meta=meta, trace_id=trace_id)
