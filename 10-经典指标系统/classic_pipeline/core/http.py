"""HTTP 横切 hooks（从 ml_trade_service.py 抽取）

包含：
- _cors_after_request：CORS 响应头处理
- _cors_preflight：OPTIONS 预检请求处理
- _characterization_exclusive_guard：characterization 运行期间排他守卫
- _fundamental_non_news_retired_guard：fundamental 非 news 路由退役守卫
- _fundamental_non_news_retired_response：退役路由统一响应

通过 register_hooks(app) 注册到 Flask app，避免模块加载时绑定 app。
"""

import os
from typing import Optional, Tuple

from flask import Response, jsonify, request

from .runtime import (
    _CHARACTERIZATION_EXCLUSIVE_STATE,
    _characterization_exclusive_is_running,
    _now_ms,
)


def _cors_after_request(resp: Response) -> Response:
    try:
        origin = str(request.headers.get("Origin") or "").strip()
    except Exception:
        origin = ""
    allowlist = None
    try:
        raw = str(os.environ.get("CORS_ALLOW_ORIGINS", "") or "").strip()
        if raw:
            allowlist = {x.strip() for x in raw.split(",") if x.strip()}
    except Exception:
        allowlist = None
    allow_any = allowlist is None

    if origin and (allow_any or (origin in (allowlist or set()))):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    else:
        resp.headers["Access-Control-Allow-Origin"] = "*"

    resp.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-CSRF-Token, X-Webhook-Token, "
        "X-Execute-Token, X-Config-Token, X-Maintenance-Token, "
        "X-Config-Signature, X-HMAC-Signature"
    )
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return resp


def _cors_preflight() -> Optional[Response]:
    try:
        m = str(request.method or "").strip().upper()
    except Exception:
        m = ""
    if m == "OPTIONS":
        return jsonify({"ok": True}), 200
    return None


def _characterization_exclusive_guard() -> Optional[Response]:
    try:
        if not _characterization_exclusive_is_running():
            return None
    except Exception:
        return None
    try:
        m = str(request.method or "").strip().upper()
    except Exception:
        m = ""
    if m == "OPTIONS":
        return None
    try:
        p = str(request.path or "")
    except Exception:
        p = ""
    if p.startswith("/governance/characterization/"):
        return None
    if p in ("/health", "/ping"):
        return None
    try:
        st = dict(_CHARACTERIZATION_EXCLUSIVE_STATE)
    except Exception:
        st = {"running": 1}
    return jsonify({"ok": False, "error": "characterization_running", "state": st}), 503


def _fundamental_non_news_retired_guard() -> Optional[Response]:
    try:
        p = str(request.path or "").strip()
    except Exception:
        p = ""
    if not p.startswith("/fundamental/"):
        return None
    if p.startswith("/fundamental/news/"):
        return None
    return jsonify({"ok": False, "error": "module_retired", "module": "fundamental_non_news", "path": p, "ts": int(_now_ms())}), 410


def _fundamental_non_news_retired_response(path: str) -> Tuple[Response, int]:
    return jsonify({"ok": False, "error": "module_retired", "module": "fundamental_non_news", "path": str(path or ""), "ts": int(_now_ms())}), 410


def register_hooks(app) -> None:
    """将所有横切 hooks 注册到给定 Flask app"""
    app.after_request(_cors_after_request)
    app.before_request(_cors_preflight)
    app.before_request(_characterization_exclusive_guard)
    app.before_request(_fundamental_non_news_retired_guard)


__all__ = [
    "register_hooks",
    "_cors_after_request",
    "_cors_preflight",
    "_characterization_exclusive_guard",
    "_fundamental_non_news_retired_guard",
    "_fundamental_non_news_retired_response",
]
