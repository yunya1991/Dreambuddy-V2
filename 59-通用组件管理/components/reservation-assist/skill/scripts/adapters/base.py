"""适配器基座：Transport、快照、命中、错误类型、注册表与 fixture 回放。

约定：
- 平台协议差异只允许出现在 `adapters/<平台>.py`；
- 内核（scheduler / store / notify / security）通过本文件的类型工作，不认识任何平台名。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

CN_TZ = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) reservation-assist/0.1"


class AdapterError(Exception):
    """适配器错误基类；code 用于事件与 missing[] 原因码。"""

    code = "E_ADAPTER"


class GateDenied(AdapterError):
    code = "E_GATE"


class AuthExpired(AdapterError):
    code = "E_AUTH"


class RateLimited(AdapterError):
    code = "E_RATE"


class PlatformChanged(AdapterError):
    code = "E_PLATFORM"


class TransportError(AdapterError):
    code = "E_NET"


class SubmitUnknown(AdapterError):
    code = "E_SUBMIT_UNKNOWN"


@dataclass
class Response:
    status: int
    body: str
    headers: dict = field(default_factory=dict)


@runtime_checkable
class Transport(Protocol):
    def fetch(self, req: dict) -> Response: ...


class HttpTransport:
    """真实通道：仅运行期使用；测试一律注入 FakeTransport。"""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def fetch(self, req: dict) -> Response:
        import urllib.request

        request = urllib.request.Request(
            req["url"], method=req.get("method", "GET"), headers=req.get("headers") or {}
        )
        data = req.get("body")
        if data is not None:
            request.data = data.encode("utf-8") if isinstance(data, str) else data
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return Response(status=resp.status, body=raw, headers=dict(resp.headers))
        except Exception as exc:  # noqa: BLE001 - 网络异常统一为 TransportError
            raise TransportError(str(exc)) from None


@dataclass
class Snapshot:
    adapter: str
    target_id: str
    fetched_at: int
    digest: str
    items: list[dict] = field(default_factory=list)


@dataclass
class Hit:
    task_id: str
    fingerprint: str
    adapter: str
    target_id: str
    session: str
    price_tier: str
    price: float | None = None
    price_max: float | None = None
    remaining: int = 0
    url: str = ""

    def summary(self) -> dict:
        return {
            "adapter": self.adapter,
            "target_id": self.target_id,
            "session": self.session,
            "price_tier": self.price_tier,
            "price": self.price,
            "remaining": self.remaining,
            "url": self.url,
        }


@dataclass
class SubmitResult:
    state: str  # ok | unknown | rejected
    official_order_ref: str = ""
    detail: str = ""


@dataclass
class Grant:
    id: str
    task_id: str
    fingerprint: str
    issued_at: int
    expires_at: int
    hmac: str = ""


@runtime_checkable
class Adapter(Protocol):
    NAME: str
    MIN_INTERVAL_MS: int
    DEFAULT_INTERVAL_MS: int
    PERFORMANCE: bool
    SUBMIT_READY: bool

    def login_state(self, ctx: dict | None = None) -> str: ...

    def probe(self, target: dict, transport: Transport) -> Snapshot: ...

    def match(self, snap: Snapshot, rule: dict, task_id: str = "") -> list[Hit]: ...

    def handoff(self, hit: Hit) -> str: ...

    def submit(self, hit: Hit, grant: Grant, transport: Transport) -> SubmitResult: ...


def now_ms() -> int:
    return int(time.time() * 1000)


def date_key(ts_ms: int | None = None) -> str:
    """亚洲/上海自然日，用于指纹归一。"""
    ts = now_ms() if ts_ms is None else int(ts_ms)
    return datetime.fromtimestamp(ts / 1000, CN_TZ).strftime("%Y-%m-%d")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(adapter: str, target_id: str, date: str, session: str, price_tier: str) -> str:
    raw = "|".join([adapter, str(target_id), str(date), str(session), str(price_tier)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def target_fingerprint(task: dict, at_ms: int | None = None) -> str:
    """任务目标指纹：date 取开窗日，没有窗口时取当天。"""
    target = task.get("target") or {}
    if isinstance(target, str):
        target = json.loads(target)
    stamp = task.get("window_start") or at_ms
    return fingerprint(
        task.get("adapter", ""),
        target.get("target_id", ""),
        date_key(stamp),
        target.get("session", ""),
        target.get("price_tier", ""),
    )


class BaseHttpAdapter:
    """HTTP 类适配器的公共实现：请求构造、状态码映射、match 与只读跳转。"""

    NAME = ""
    MIN_INTERVAL_MS = 1500
    DEFAULT_INTERVAL_MS = 1500
    PERFORMANCE = False
    SUBMIT_READY = False
    REQUIRES_LOGIN = True

    def __init__(self) -> None:
        self.cookie = ""

    # --- 子类实现 ---------------------------------------------------------
    def build_request(self, target: dict) -> dict:
        headers = {"User-Agent": UA, "Accept": "application/json,text/html;q=0.9"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        return {
            "method": "GET",
            "url": target.get("url") or target.get("endpoint") or "",
            "headers": headers,
        }

    def parse_items(self, body: str, target: dict) -> list[dict]:
        raise NotImplementedError

    # --- 公共实现 ---------------------------------------------------------
    def login_state(self, ctx: dict | None = None) -> str:
        if not self.REQUIRES_LOGIN:
            return "ok"
        if ctx is not None:
            return "ok" if ctx.get("logged_in") else "unknown"
        return "ok" if self.cookie else "unknown"

    def fetch(self, target: dict, transport: Transport) -> Response:
        resp = transport.fetch(self.build_request(target))
        if resp.status in (401, 403):
            raise AuthExpired("登录态失效或被拦截")
        if resp.status == 429:
            raise RateLimited("平台限流")
        if resp.status >= 500:
            raise TransportError("平台 5xx：{}".format(resp.status))
        if resp.status >= 400:
            raise PlatformChanged("页面结构或接口变化：HTTP {}".format(resp.status))
        return resp

    def probe(self, target: dict, transport: Transport) -> Snapshot:
        resp = self.fetch(target, transport)
        items = self.parse_items(resp.body, target)
        return Snapshot(
            adapter=self.NAME,
            target_id=str(target.get("target_id", "")),
            fetched_at=now_ms(),
            digest=digest(resp.body),
            items=items,
        )

    def match(self, snap: Snapshot, rule: dict, task_id: str = "") -> list[Hit]:
        max_price = rule.get("max_price")
        tiers = set(rule.get("price_tiers") or [])
        date = date_key(snap.fetched_at)
        hits: list[Hit] = []
        for item in snap.items or []:
            if int(item.get("remaining") or 0) <= 0:
                continue
            price = item.get("price")
            if max_price is not None and price is not None and float(price) > float(max_price):
                continue
            tier = str(item.get("tier") or "")
            if tiers and tier not in tiers:
                continue
            hit = Hit(
                task_id=task_id,
                fingerprint=fingerprint(
                    self.NAME,
                    item.get("target_id") or snap.target_id,
                    date,
                    item.get("session") or "",
                    tier,
                ),
                adapter=self.NAME,
                target_id=str(item.get("target_id") or snap.target_id),
                session=str(item.get("session") or ""),
                price_tier=tier,
                price=price,
                price_max=max_price,
                remaining=int(item.get("remaining") or 0),
                url=str(item.get("url") or snap.target_id),
            )
            hits.append(hit)
        return hits

    def handoff(self, hit: Hit) -> str:
        return hit.url

    def submit(self, hit: Hit, grant: Grant, transport: Transport) -> SubmitResult:
        # P3 之前只保留协议：未通过就绪实验的适配器不做任何落单动作。
        if not self.SUBMIT_READY:
            raise GateDenied("adapter_not_ready")
        raise GateDenied("submit_not_implemented")


# ---------------------------------------------------------------------------
# fixture 回放契约：fixtures/<adapter>/<case>/{request.json,response.txt,expected.json}
# ---------------------------------------------------------------------------


def load_fixture(case_dir: Path) -> tuple[dict, Response, dict]:
    request = json.loads((case_dir / "request.json").read_text(encoding="utf-8"))
    body = (case_dir / "response.txt").read_text(encoding="utf-8")
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    return request, Response(status=int(request.get("status", 200)), body=body), expected


def iter_fixture_cases(fixtures_root: Path):
    if not fixtures_root.is_dir():
        return
    for adapter_dir in sorted(p for p in fixtures_root.iterdir() if p.is_dir()):
        for case_dir in sorted(p for p in adapter_dir.iterdir() if p.is_dir()):
            if (case_dir / "response.txt").is_file():
                yield adapter_dir.name, case_dir


def json_items(body: str, key: str) -> list[dict]:
    payload: Any = json.loads(body)
    if isinstance(payload, dict):
        node: Any = payload
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return list(node or [])
    return list(payload or [])
