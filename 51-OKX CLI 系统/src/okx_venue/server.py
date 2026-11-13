"""Local HTTP bridge: expose the OKX venue ports to the Next.js frontend.

前端 / 产品专用通道。后端自链路（11 旁路 / trade-exec MCP）不经过本进程，
二者仅共享 `okx` CLI 凭证体系，profile 与审计文件均独立，天然隔离。

安全要点：
- 只监听 127.0.0.1，且必须携带本地 token（``runtime/bridge_token`` 或环境变量）。
- 读走 demo/live 只读；写默认 demo，live 写必须一次性人工解锁（LiveGate）。
- 所有下单先落 order_intent 草稿，只有 confirm 才真正调用 OrderPort。
- 每次调用由 CliRunner 追加 JSONL 审计（脱敏）。
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .adapter import OkxCliVenue
from .config import USER_AUDIT_PATH, VenueConfig
from .credentials import (
    UserCredentialStore,
    assert_no_withdraw,
    build_env_credentials,
    env_credential_paths,
    probe_permissions,
)
from .errors import (
    LiveTradingForbidden,
    VenueError,
)
from .live_gate import DEFAULT_TTL_S, LiveGate
from .runner import AuditLogger

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8097
DEFAULT_MAX_ORDER_SIZE = 1000.0
INTENT_TTL_S = 300
MAX_AUDIT_LINES = 200

_INST_RE = re.compile(r"^[A-Z0-9]{2,15}-[A-Z0-9]{2,10}(-SWAP)?$")
_QUOTES = {"USDT", "USDC"}

_STATUS_BY_CODE = {
    "live_trading_forbidden": 403,
    "live_read_forbidden": 403,
    "live_unlock_denied": 403,
    "command_not_allowed": 403,
    "invalid_argument": 400,
    "intent_not_found": 404,
    "intent_expired": 409,
    "intent_already_confirmed": 409,
    "venue_credentials_missing": 409,
    "venue_credentials_invalid": 400,
    "unauthorized": 401,
    "cli_not_installed": 503,
    "cli_timeout": 504,
    "cli_auth_error": 502,
    "cli_rate_limit": 429,
    "cli_nonzero_exit": 502,
    "cli_invalid_json": 502,
    "venue_config_error": 500,
}


class BridgeError(VenueError):
    """Adapter-level validation error raised inside the bridge."""


def load_or_create_token(path: Path) -> str:
    env_token = os.getenv("OKX_VENUE_BRIDGE_TOKEN", "").strip()
    if env_token:
        return env_token
    path = Path(path)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def default_config(mode: str) -> VenueConfig:
    """用户 venue 配置：demo 默认；live 仅由解锁闸门临时打开。"""
    base = VenueConfig.for_user()
    if mode == "live":
        return replace(base, mode="live", allow_live_read=True, allow_live_write=True)
    return replace(base, mode="demo", allow_live_read=False, allow_live_write=False)


def _float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BridgeError(f"{name} must be numeric", code="invalid_argument") from exc


class VenueApp:
    """Transport-free request dispatcher (unit-testable without sockets)."""

    def __init__(
        self,
        *,
        config_factory: Optional[Callable[[str], VenueConfig]] = None,
        adapter_factory: Optional[Callable[[VenueConfig], OkxCliVenue]] = None,
        live_gate: Optional[LiveGate] = None,
        token: Optional[str] = None,
        audit_path: Optional[Path] = None,
        credential_store: Optional[UserCredentialStore] = None,
        probe_permission: Optional[Callable[[Dict[str, str], bool], str]] = None,
        intent_ttl_s: int = INTENT_TTL_S,
        max_order_size: Optional[float] = None,
        clock=time.time,
    ) -> None:
        self.config_factory = config_factory
        self.adapter_factory = adapter_factory or (lambda cfg: OkxCliVenue(config=cfg))
        self.live_gate = live_gate or LiveGate()
        self.token = token
        self.audit_path = Path(audit_path or USER_AUDIT_PATH)
        self.credentials = credential_store or UserCredentialStore()
        self._probe_permission = probe_permission or (
            lambda env, demo: probe_permissions(env, demo=demo, audit_path=self.audit_path)
        )
        self.intent_ttl_s = intent_ttl_s
        self.max_order_size = float(
            max_order_size
            if max_order_size is not None
            else os.getenv("OKX_VENUE_MAX_ORDER_SIZE", str(DEFAULT_MAX_ORDER_SIZE))
        )
        self._clock = clock
        self._intents: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ── routing ─────────────────────────────────────────────────
    def handle(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Dict[str, str]] = None,
        body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        query = query or {}
        body = body or {}
        try:
            self._authenticate(headers or {})
            data = self._dispatch(method.upper(), path, query, body)
            return 200, {"ok": True, "data": data}
        except VenueError as exc:
            status = _STATUS_BY_CODE.get(exc.code, 400)
            return status, {
                "ok": False,
                "error": {"code": exc.code, "message": str(exc)},
            }

    def _authenticate(self, headers: Dict[str, str]) -> None:
        if not self.token:
            return
        provided = headers.get("x-venue-token") or headers.get("X-Venue-Token") or ""
        if not secrets.compare_digest(str(provided), str(self.token)):
            raise BridgeError("missing or invalid venue token", code="unauthorized")

    def _dispatch(
        self,
        method: str,
        path: str,
        query: Dict[str, str],
        body: Dict[str, Any],
    ) -> Any:
        if path in {"/health", "/health/"} and method == "GET":
            return self._health()
        if path == "/credentials" and method == "GET":
            return self._credentials_public()
        if path == "/credentials" and method == "POST":
            return self._save_credentials(body)
        if path == "/credentials" and method == "DELETE":
            return self._delete_credentials()
        if path == "/credentials/test" and method == "POST":
            return self._test_credentials()
        if path == "/account/balance" and method == "GET":
            return self._adapter(self._read_mode()).get_balance(query.get("ccy") or None)
        if path == "/account/positions" and method == "GET":
            return self._adapter(self._read_mode()).get_positions(query.get("inst_id") or None)
        if path == "/market/ticker" and method == "GET":
            inst_id = query.get("inst_id") or ""
            if not inst_id:
                raise BridgeError("inst_id is required", code="invalid_argument")
            return self._adapter("demo").get_ticker(inst_id)
        if path == "/order-intents" and method == "POST":
            return self._create_intent(body)
        if path.startswith("/order-intents/"):
            parts = [p for p in path.split("/") if p]
            intent_id = parts[1] if len(parts) > 1 else ""
            if len(parts) == 2 and method == "GET":
                return self._get_intent(intent_id)
            if len(parts) == 3 and parts[2] == "confirm" and method == "POST":
                return self._confirm_intent(intent_id)
        if path == "/live/status" and method == "GET":
            return self.live_gate.status()
        if path == "/live/unlock" and method == "POST":
            return self.live_gate.unlock(
                body.get("phrase"), int(body.get("ttl_s") or DEFAULT_TTL_S)
            )
        if path == "/live/lock" and method == "POST":
            return self.live_gate.lock()
        if path == "/audit" and method == "GET":
            return self._read_audit(int(query.get("limit") or 50))
        raise BridgeError(f"unknown route: {method} {path}", code="invalid_argument")

    # ── handlers ────────────────────────────────────────────────
    def _health(self) -> Dict[str, Any]:
        mode = self._mode()
        try:
            config = self._config(mode)
        except VenueError:
            config = default_config(mode)
        credentials = self.credentials.public()
        return {
            "bridge": "okx-venue",
            "config": config.describe(),
            "effective_mode": mode,
            "live": self.live_gate.status(),
            "credentials": credentials,
            "paths": env_credential_paths(),
            "audit_path": str(self.audit_path),
            "max_order_size": self.max_order_size,
            "quote_currencies": sorted(_QUOTES),
        }

    # ── user credentials ────────────────────────────────────────
    def _credentials_public(self) -> Dict[str, Any]:
        return self.credentials.public()

    def _save_credentials(self, body: Dict[str, Any]) -> Dict[str, Any]:
        api_key = str(body.get("api_key") or "")
        secret_key = str(body.get("secret_key") or "")
        passphrase = str(body.get("passphrase") or "")
        demo = bool(body.get("demo", True))
        label = str(body.get("label") or "user")

        env = {
            "OKX_API_KEY": api_key.strip(),
            "OKX_SECRET_KEY": secret_key.strip(),
            "OKX_PASSPHRASE": passphrase.strip(),
        }
        perms = self._probe_permission(env, demo)
        assert_no_withdraw(perms)
        public = self.credentials.save(
            api_key=api_key,
            secret_key=secret_key,
            passphrase=passphrase,
            demo=demo,
            label=label,
            permissions=perms,
        )
        self._audit_credentials("credentials_save", ok=True)
        return public

    def _delete_credentials(self) -> Dict[str, Any]:
        self.credentials.delete()
        self._audit_credentials("credentials_delete", ok=True)
        return {"configured": False}

    def _test_credentials(self) -> Dict[str, Any]:
        record = self.credentials.load()
        if not record:
            raise VenueError(
                "user venue credentials are not configured", code="venue_credentials_missing"
            )
        adapter = self._adapter(self._mode())
        balance = adapter.get_balance("USDT")
        self._audit_credentials("credentials_test", ok=True)
        return {
            "ok": True,
            "mode": self._mode(),
            "permissions": record.get("permissions", ""),
            "balance": balance.get("balance"),
            "total_eq": balance.get("total_eq"),
        }

    def _create_intent(self, body: Dict[str, Any]) -> Dict[str, Any]:
        inst_id = str(body.get("inst_id") or "").strip().upper()
        if not _INST_RE.match(inst_id):
            raise BridgeError(
                "inst_id must look like BTC-USDT or BTC-USDT-SWAP", code="invalid_argument"
            )
        quote = inst_id.split("-")[1]
        if quote not in _QUOTES:
            raise BridgeError(f"quote currency {quote} is not allowed", code="invalid_argument")

        side = str(body.get("side") or "").strip().lower()
        if side not in {"buy", "sell"}:
            raise BridgeError("side must be buy|sell", code="invalid_argument")

        order_type = str(body.get("order_type") or "market").strip().lower()
        if order_type not in {"market", "limit"}:
            raise BridgeError("order_type must be market|limit", code="invalid_argument")

        size = _float(body.get("size"), "size")
        if size <= 0:
            raise BridgeError("size must be > 0", code="invalid_argument")
        if size > self.max_order_size:
            raise BridgeError(
                f"size {size} exceeds local cap {self.max_order_size}",
                code="invalid_argument",
            )

        price: Optional[float] = None
        if order_type == "limit":
            price = _float(body.get("price"), "price")
            if price <= 0:
                raise BridgeError("price must be > 0", code="invalid_argument")

        mode = self._mode()
        intent_id = uuid.uuid4().hex[:12]
        now = self._clock()
        intent = {
            "id": intent_id,
            "inst_id": inst_id,
            "side": side,
            "size": size,
            "order_type": order_type,
            "price": price,
            "td_mode": (str(body.get("td_mode") or "").strip().lower() or None),
            "pos_side": (str(body.get("pos_side") or "").strip().lower() or None),
            "mode": mode,
            "status": "pending",
            "created_at": now,
            "expires_at": now + self.intent_ttl_s,
            "risk": {
                "max_order_size": self.max_order_size,
                "quote": quote,
                "notional_hint": (
                    round(price * size, 6) if (price and not inst_id.endswith("-SWAP")) else None
                ),
                "source": str(body.get("source") or "manual"),
            },
        }
        with self._lock:
            self._purge_expired_locked()
            self._intents[intent_id] = intent
        return self._public_intent(intent)

    def _get_intent(self, intent_id: str) -> Dict[str, Any]:
        with self._lock:
            intent = self._intents.get(intent_id)
        if not intent:
            raise BridgeError(f"intent {intent_id} not found", code="intent_not_found")
        return self._public_intent(intent)

    def _confirm_intent(self, intent_id: str) -> Dict[str, Any]:
        with self._lock:
            intent = self._intents.get(intent_id)
        if not intent:
            raise BridgeError(f"intent {intent_id} not found", code="intent_not_found")
        if intent["status"] != "pending":
            raise BridgeError(
                f"intent {intent_id} already {intent['status']}",
                code="intent_already_confirmed",
            )
        if self._clock() > intent["expires_at"]:
            with self._lock:
                intent["status"] = "expired"
            raise BridgeError(f"intent {intent_id} expired", code="intent_expired")
        if intent["mode"] == "live" and not self.live_gate.is_unlocked():
            raise LiveTradingForbidden(
                "live unlock window closed; re-unlock before confirming",
                details={"intent_id": intent_id},
            )

        adapter = self._adapter(intent["mode"])
        try:
            result = adapter.place_order(
                intent["inst_id"],
                intent["side"],
                intent["size"],
                order_type=intent["order_type"],
                price=intent["price"],
                td_mode=intent["td_mode"],
                pos_side=intent["pos_side"],
            )
        except VenueError as exc:
            with self._lock:
                intent["status"] = "failed"
                intent["error"] = {"code": exc.code, "message": str(exc)}
            self._audit_intent(intent, ok=False, error_code=exc.code)
            raise

        with self._lock:
            intent["status"] = "executed" if result.get("ok") else "rejected"
            intent["result"] = {
                "order_id": result.get("order_id"),
                "cl_ord_id": result.get("cl_ord_id"),
                "s_code": result.get("s_code"),
                "s_msg": result.get("s_msg"),
            }
        self._audit_intent(
            intent,
            ok=bool(result.get("ok")),
            error_code="" if result.get("ok") else "venue_rejected",
        )
        return {
            "intent": self._public_intent(intent),
            "order": intent["result"],
        }

    # ── helpers ─────────────────────────────────────────────────
    def _config(self, mode: str) -> VenueConfig:
        record = self.credentials.load()
        if record:
            return VenueConfig(
                profile="user",
                mode=mode,
                credential_source="env",
                env_credentials=build_env_credentials(record),
                allow_live_read=mode == "live",
                allow_live_write=mode == "live" and self.live_gate.is_unlocked(),
                audit_path=self.audit_path,
            )
        if self.config_factory:
            return self.config_factory(mode)
        # 未配置用户凭证时 fail-closed：不隐式回落到任何 profile。
        raise VenueError(
            "用户交易 API 未配置：请先在「通用设置 → 用户交易 API」中填写并验证",
            code="venue_credentials_missing",
        )

    def _mode(self) -> str:
        """用户凭证决定读环境；写环境另外受 LiveGate 约束。"""
        record = self.credentials.load()
        if record and not record.get("demo", True):
            return "live"
        return "demo"

    def _read_mode(self) -> str:
        return self._mode()

    def _audit_credentials(self, operation: str, *, ok: bool, error_code: str = "") -> None:
        AuditLogger(self.audit_path).write(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "trace_id": uuid.uuid4().hex[:12],
                "operation": operation,
                "argv": [],
                "profile": "user",
                "mode": self._mode(),
                "ok": ok,
                "error_code": error_code,
            }
        )

    def _adapter(self, mode: str) -> OkxCliVenue:
        return self.adapter_factory(self._config(mode))

    def _purge_expired_locked(self) -> None:
        now = self._clock()
        for key in [k for k, v in self._intents.items() if now > v["expires_at"] + 3600]:
            self._intents.pop(key, None)

    def _public_intent(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        public = {k: v for k, v in intent.items() if k not in {"result", "error"}}
        if "result" in intent:
            public["result"] = intent["result"]
        if "error" in intent:
            public["error"] = intent["error"]
        return public

    def _audit_intent(self, intent: Dict[str, Any], *, ok: bool, error_code: str) -> None:
        logger = AuditLogger(self.audit_path)
        logger.write(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "trace_id": intent["id"],
                "operation": "order_intent_confirm",
                "argv": [],
                "profile": self._config(intent["mode"]).profile,
                "mode": intent["mode"],
                "ok": ok,
                "error_code": error_code,
                "intent": {
                    "inst_id": intent["inst_id"],
                    "side": intent["side"],
                    "size": intent["size"],
                    "order_type": intent["order_type"],
                    "price": intent["price"],
                },
            }
        )

    def _read_audit(self, limit: int) -> Dict[str, Any]:
        limit = max(1, min(MAX_AUDIT_LINES, int(limit)))
        if not self.audit_path.exists():
            return {"records": [], "path": str(self.audit_path)}
        with self.audit_path.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()[-limit:]
        records: List[Any] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({"raw": line[:200]})
        records.reverse()
        return {"records": records, "path": str(self.audit_path)}


class _BridgeHandler(BaseHTTPRequestHandler):
    app: VenueApp  # injected by make_server
    server_version = "OkxVenueBridge/0.2"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        status, payload = self.app.handle(
            "GET", parsed.path, query=query, headers=dict(self.headers.items())
        )
        self._send(status, payload)

    def do_POST(self) -> None:  # noqa: N802
        from urllib.parse import urlparse

        parsed = urlparse(self.path)
        status, payload = self.app.handle(
            "POST",
            parsed.path,
            body=self._read_body(),
            headers=dict(self.headers.items()),
        )
        self._send(status, payload)


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    app: Optional[VenueApp] = None,
    token: Optional[str] = None,
) -> ThreadingHTTPServer:
    router = app or VenueApp(
        token=token or load_or_create_token(USER_AUDIT_PATH.parent / "bridge_token")
    )

    class Handler(_BridgeHandler):
        pass

    Handler.app = router
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.getenv("OKX_VENUE_BRIDGE_HOST", DEFAULT_HOST)
    port = int(os.getenv("OKX_VENUE_BRIDGE_PORT", str(DEFAULT_PORT)))
    token = load_or_create_token(USER_AUDIT_PATH.parent / "bridge_token")
    server = make_server(host, port, token=token)
    print(
        f"[okx-venue-bridge] listening on http://{host}:{port} (token file: runtime/bridge_token)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
