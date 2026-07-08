from __future__ import annotations

import json
import os
import socket
import ssl
from typing import Any, Callable, Deque, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from collections import defaultdict, deque


SenderFn = Callable[[str, Dict[str, Any], int], Dict[str, Any]]


class MockTransport:
    def __init__(self) -> None:
        self._queues: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)

    def send(self, channel: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._queues[channel].append(dict(payload))
        return {"status": "QUEUED"}

    def receive(self, channel: str) -> Optional[Dict[str, Any]]:
        if not self._queues[channel]:
            return None
        return self._queues[channel].popleft()


class HTTPTransport:
    def __init__(
        self,
        base_url: str,
        sender: Optional[Callable[[str, Dict[str, Any], int, Optional[Dict[str, str]]], Dict[str, Any]]] = None,
        timeout_ms: int = 30000,
        jwt_token: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.sender = sender or self._default_sender
        self.timeout_ms = timeout_ms
        self.jwt_token = jwt_token

    def _default_sender(
        self, url: str, payload: Dict[str, Any], timeout_ms: int, headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=req_headers, method="POST")
        try:
            with urlopen(req, timeout=max(1, int(timeout_ms) / 1000)) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return {"status": int(getattr(resp, "status", 200)), "url": url, "timeout_ms": timeout_ms, "body": body}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            return {"status": int(getattr(exc, "code", 500)), "url": url, "timeout_ms": timeout_ms, "body": body}
        except URLError as exc:
            return {"status": 0, "url": url, "timeout_ms": timeout_ms, "error": str(exc)}

    def send(self, channel: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/{channel}"
        return self._call_sender(url, dict(payload), None)

    def receive(self, channel: str) -> Optional[Dict[str, Any]]:
        return None

    def send_envelope(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        header = envelope.get("header") or {}
        target = str(header.get("target") or "")
        url = f"{self.base_url}{endpoint_for_target(target)}"
        headers: Dict[str, str] = {}
        if self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"
        return self._call_sender(url, dict(envelope), headers)

    def _call_sender(self, url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> Dict[str, Any]:
        try:
            return self.sender(url, payload, self.timeout_ms, headers)
        except TypeError:
            return self.sender(url, payload, self.timeout_ms)


class MQTransport:
    def __init__(self) -> None:
        self._topics: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)

    def send(self, channel: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._topics[channel].append(dict(payload))
        return {"status": "PUBLISHED"}

    def receive(self, channel: str) -> Optional[Dict[str, Any]]:
        if not self._topics[channel]:
            return None
        return self._topics[channel].popleft()


def endpoint_for_target(target: str) -> str:
    t = target.strip().lower()
    mapping = {
        "a1": "/a1/research",
        "a2": "/a2/analysis",
        "a3": "/a3/strategy",
        "a4": "/a4/validation",
        "a5": "/a5/execution",
        "a6": "/a6/intelligence",
        "a7": "/a7/practice",
        "a8": "/a8/verification",
        "a9": "/a9/exit",
    }
    if t in mapping:
        return mapping[t]
    return f"/{t}"


class RedisConfig:
    def __init__(self, *, host: str, port: int, password: str, use_tls: bool) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.use_tls = use_tls


def _parse_redis_url(url: str) -> RedisConfig:
    raw = url.strip()
    use_tls = raw.startswith("rediss://")
    raw = raw.replace("redis://", "").replace("rediss://", "")

    password = ""
    if "@" in raw and raw.split("@", 1)[0]:
        auth, raw = raw.split("@", 1)
        password = auth.lstrip(":")

    host_port = raw.split("/", 1)[0]
    if ":" in host_port:
        host, port_s = host_port.split(":", 1)
        port = int(port_s)
    else:
        host = host_port
        port = 6379
    return RedisConfig(host=host, port=port, password=password, use_tls=use_tls)


class RedisStreamsTransport:
    def __init__(self, redis_url: str, timeout_ms: int = 30000) -> None:
        self.redis_url = redis_url
        self.timeout_ms = timeout_ms
        self._cfg = _parse_redis_url(redis_url)

    def topic_for_envelope(self, envelope: Dict[str, Any]) -> str:
        header = envelope.get("header") or {}
        loop_type = str(header.get("loop_type") or "")
        target = str(header.get("target") or "").lower()
        msg_type = str(header.get("type") or "").lower() or "event"
        payload = envelope.get("payload") or {}
        alert_level = str(payload.get("alert_level") or "")

        if loop_type == "intelligence":
            if alert_level:
                return f"dream.intelligence.a6.{alert_level}"
            return "dream.intelligence.a6.alert"

        if loop_type == "governance":
            if target == "a7":
                return "dream.governance.a7.event"
            if target == "a8" and msg_type == "feedback":
                return "dream.governance.a8.feedback"
            if target == "a8":
                return "dream.governance.a8.request"
            return f"dream.governance.{target}.{msg_type}"

        return f"dream.execution.{target}.{msg_type}"

    def send_envelope(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        stream = self.topic_for_envelope(envelope)
        return self.xadd(stream, {"envelope": json.dumps(envelope, ensure_ascii=False)})

    def xadd(self, stream: str, fields: Dict[str, str]) -> Dict[str, Any]:
        parts = ["XADD", stream, "*"]
        for k, v in fields.items():
            parts.extend([k, v])
        resp = self._execute(*parts)
        return {"status": "OK", "stream": stream, "response": resp}

    def _execute(self, *parts: str) -> Any:
        sock = socket.create_connection((self._cfg.host, self._cfg.port), timeout=max(1, int(self.timeout_ms) / 1000))
        try:
            if self._cfg.use_tls:
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=self._cfg.host)
            if self._cfg.password:
                self._send(sock, ["AUTH", self._cfg.password])
                _ = self._recv(sock)

            self._send(sock, list(parts))
            return self._recv(sock)
        finally:
            sock.close()

    def _send(self, sock: socket.socket, parts: list[str]) -> None:
        buf = f"*{len(parts)}\r\n".encode("utf-8")
        for p in parts:
            b = str(p).encode("utf-8")
            buf += f"${len(b)}\r\n".encode("utf-8") + b + b"\r\n"
        sock.sendall(buf)

    def _recv(self, sock: socket.socket) -> Any:
        def read_line() -> bytes:
            data = b""
            while not data.endswith(b"\r\n"):
                chunk = sock.recv(1)
                if not chunk:
                    break
                data += chunk
            return data[:-2]

        prefix = sock.recv(1)
        if not prefix:
            return None
        if prefix == b"+":
            return read_line().decode("utf-8", errors="replace")
        if prefix == b"-":
            raise RuntimeError(read_line().decode("utf-8", errors="replace"))
        if prefix == b":":
            return int(read_line().decode("utf-8", errors="replace"))
        if prefix == b"$":
            n = int(read_line().decode("utf-8", errors="replace"))
            if n == -1:
                return None
            buf = b""
            while len(buf) < n:
                buf += sock.recv(n - len(buf))
            _ = sock.recv(2)
            return buf.decode("utf-8", errors="replace")
        if prefix == b"*":
            n = int(read_line().decode("utf-8", errors="replace"))
            arr = []
            for _ in range(n):
                arr.append(self._recv(sock))
            return arr
        return None


class TransportRouter:
    def __init__(self, *, http: HTTPTransport, mq: Any) -> None:
        self.http = http
        self.mq = mq

    def send_envelope(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        header = envelope.get("header") or {}
        loop_type = str(header.get("loop_type") or "execution")
        if loop_type in {"execution", "governance"}:
            return self.http.send_envelope(envelope)
        if hasattr(self.mq, "send_envelope"):
            return self.mq.send_envelope(envelope)
        channel = loop_type
        if hasattr(self.mq, "send"):
            return self.mq.send(channel, envelope)
        raise ValueError("mq transport cannot send")


def build_default_transport_router() -> TransportRouter:
    http_base = os.environ.get("TRADING_HTTP_BASE_URL", "").strip()
    jwt = os.environ.get("TRADING_HTTP_JWT_TOKEN", "").strip()
    redis_url = os.environ.get("REDIS_URL", "").strip()

    http = HTTPTransport(base_url=http_base or "http://localhost:8080", jwt_token=jwt)
    mq: Any
    if redis_url:
        mq = RedisStreamsTransport(redis_url=redis_url)
    else:
        mq = MQTransport()
    return TransportRouter(http=http, mq=mq)
