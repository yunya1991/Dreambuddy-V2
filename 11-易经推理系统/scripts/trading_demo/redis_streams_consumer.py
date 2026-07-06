import json
import socket
import ssl
from pathlib import Path
from typing import Any, Optional


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


def _send(sock: socket.socket, parts: list[str]) -> None:
    buf = f"*{len(parts)}\r\n".encode("utf-8")
    for p in parts:
        b = str(p).encode("utf-8")
        buf += f"${len(b)}\r\n".encode("utf-8") + b + b"\r\n"
    sock.sendall(buf)


def _recv(sock: socket.socket) -> Any:
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
            arr.append(_recv(sock))
        return arr
    return None


def _execute(redis_url: str, timeout_ms: int, parts: list[str]) -> Any:
    cfg = _parse_redis_url(redis_url)
    sock = socket.create_connection((cfg.host, cfg.port), timeout=max(1, int(timeout_ms) / 1000))
    try:
        if cfg.use_tls:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=cfg.host)
        if cfg.password:
            _send(sock, ["AUTH", cfg.password])
            _ = _recv(sock)
        _send(sock, parts)
        return _recv(sock)
    finally:
        sock.close()


def consume_once(*, redis_url: str, stream: str, last_id: str = "0-0", block_ms: int = 5000) -> list[dict]:
    resp = _execute(
        redis_url,
        30000,
        ["XREAD", "BLOCK", str(block_ms), "COUNT", "10", "STREAMS", stream, last_id],
    )
    if not resp:
        return []

    out: list[dict] = []
    for item in resp:
        _stream, entries = item[0], item[1]
        for entry in entries:
            _id, kv = entry[0], entry[1]
            fields = {str(kv[i]): kv[i + 1] for i in range(0, len(kv), 2)}
            raw = fields.get("envelope")
            if raw:
                out.append(json.loads(raw))
    return out


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--stream", required=True)
    parser.add_argument("--last-id", default="0-0")
    parser.add_argument("--block-ms", type=int, default=5000)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    out_dir: Optional[Path] = Path(args.out_dir) if args.out_dir else None
    envelopes = consume_once(redis_url=args.redis_url, stream=args.stream, last_id=args.last_id, block_ms=args.block_ms)
    for env in envelopes:
        print(json.dumps(env, ensure_ascii=False))
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            trace_id = str((env.get("header") or {}).get("trace_id") or "no-trace")
            out_path = out_dir / f"{trace_id}.json"
            out_path.write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

