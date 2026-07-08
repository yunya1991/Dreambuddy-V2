import importlib.util
import json
import socket
import threading
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeRedisServer:
    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.host, self.port = self._sock.getsockname()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stop = threading.Event()
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            socket.create_connection((self.host, self.port), timeout=0.2).close()
        except Exception:
            pass
        self._thread.join(timeout=2)
        self._sock.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            t.start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            while True:
                cmd = self._recv_array(conn)
                if cmd is None:
                    return
                if not cmd:
                    continue
                op = str(cmd[0]).upper()
                if op == "AUTH":
                    self._send_simple(conn, "OK")
                    continue
                if op == "XADD":
                    stream = str(cmd[1])
                    fields = {}
                    i = 3
                    while i + 1 < len(cmd):
                        fields[str(cmd[i])] = str(cmd[i + 1])
                        i += 2
                    self._streams.setdefault(stream, []).append(("1-0", fields))
                    self._send_bulk(conn, "1-0")
                    continue
                if op == "XREAD":
                    stream = str(cmd[-2])
                    last_id = str(cmd[-1])
                    entries = []
                    for eid, fields in self._streams.get(stream, []):
                        if last_id in {"$", "0-0"} or eid > last_id:
                            kv = []
                            for k, v in fields.items():
                                kv.extend([k, v])
                            entries.append([eid, kv])
                    if not entries:
                        self._send_null(conn)
                    else:
                        self._send_array(conn, [[stream, entries]])
                    continue
                self._send_simple(conn, "OK")

    def _read_line(self, conn: socket.socket) -> bytes:
        data = b""
        while not data.endswith(b"\r\n"):
            chunk = conn.recv(1)
            if not chunk:
                break
            data += chunk
        return data[:-2]

    def _recv_array(self, conn: socket.socket):
        prefix = conn.recv(1)
        if not prefix:
            return None
        if prefix != b"*":
            return None
        n = int(self._read_line(conn).decode("utf-8"))
        items = []
        for _ in range(n):
            t = conn.recv(1)
            if t != b"$":
                return None
            size = int(self._read_line(conn).decode("utf-8"))
            buf = b""
            while len(buf) < size:
                buf += conn.recv(size - len(buf))
            _ = conn.recv(2)
            items.append(buf.decode("utf-8"))
        return items

    def _send_simple(self, conn: socket.socket, msg: str) -> None:
        conn.sendall(f"+{msg}\r\n".encode("utf-8"))

    def _send_bulk(self, conn: socket.socket, msg: str) -> None:
        b = msg.encode("utf-8")
        conn.sendall(f"${len(b)}\r\n".encode("utf-8") + b + b"\r\n")

    def _send_null(self, conn: socket.socket) -> None:
        conn.sendall(b"$-1\r\n")

    def _send_array(self, conn: socket.socket, value) -> None:
        def enc(v) -> bytes:
            if v is None:
                return b"$-1\r\n"
            if isinstance(v, str):
                b = v.encode("utf-8")
                return f"${len(b)}\r\n".encode("utf-8") + b + b"\r\n"
            if isinstance(v, list):
                out = f"*{len(v)}\r\n".encode("utf-8")
                for item in v:
                    out += enc(item)
                return out
            raise TypeError(type(v))

        conn.sendall(enc(value))


def test_demo_redis_consumer_reads_envelope_from_stream():
    fake = _FakeRedisServer()
    fake.start()
    try:
        adapters = _load("workflows/trading-decision/transports/adapters.py")
        consumer = _load("scripts/trading_demo/redis_streams_consumer.py")
        redis_url = f"redis://{fake.host}:{fake.port}"
        tp = adapters.RedisStreamsTransport(redis_url=redis_url, timeout_ms=1000)
        env = {
            "header": {"trace_id": "t1", "loop_type": "intelligence", "target": "A4", "type": "EVENT"},
            "payload": {"trace_id": "t1", "alert_level": "L1"},
        }
        tp.send_envelope(env)
        out = consumer.consume_once(redis_url=redis_url, stream="dream.intelligence.a6.L1", last_id="0-0", block_ms=1)
        assert out
        assert out[0]["header"]["trace_id"] == "t1"
    finally:
        fake.stop()

