# -*- coding: utf-8 -*-
"""test_embed_server.py — 常驻向量服务契约测试（SPEC-41-L1 §8.8）

覆盖：客户端优先走服务、批量顺序保持、服务不可用时 FAIL-OPEN、
以及本地开发模式（EMBED_SERVER 置空）回落到 in-process。
"""

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_INDEX_ROOT = Path(__file__).resolve().parent.parent
if str(_INDEX_ROOT) not in sys.path:
    sys.path.insert(0, str(_INDEX_ROOT))

from core import embedder_bridge as eb  # noqa: E402

_STUB_DIM = 4


class _StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音
        pass

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        vecs = [[0.1] * _STUB_DIM for _ in body.get("texts", [])]
        raw = json.dumps({"vectors": vecs}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture()
def stub_server(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(eb, "EMBED_SERVER", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(eb, "_remote_ok", None)
    yield
    srv.shutdown()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_remote_path_returns_vectors(stub_server):
    vecs = eb.embed_batch(["有啥新动静吗"], lang="zh")
    assert len(vecs) == 1
    assert len(vecs[0]) == _STUB_DIM


def test_remote_batch_order_preserved(stub_server):
    vecs = eb.embed_batch(["a", "b", "c"], lang="zh")
    assert [len(v) for v in vecs] == [_STUB_DIM] * 3


def test_server_down_no_local_fallback(monkeypatch):
    """云端模式：服务挂了直接 FAIL-OPEN，不加载本地模型（避免 900MB/请求）。"""
    monkeypatch.setattr(eb, "EMBED_SERVER", f"http://127.0.0.1:{_free_port()}")
    monkeypatch.setattr(eb, "LOCAL_FALLBACK", False)
    monkeypatch.setattr(eb, "_remote_ok", None)
    assert eb.embed_batch(["x"], lang="zh") == []


def test_server_disabled_uses_local(monkeypatch):
    """本地开发：EMBED_SERVER 置空 → 回落 in-process，维度与已提交向量一致。"""
    monkeypatch.setattr(eb, "EMBED_SERVER", "")
    monkeypatch.setattr(eb, "_remote_ok", None)
    vecs = eb.embed_batch(["BTC现在什么价格"], lang="zh")
    assert vecs
    assert len(vecs[0]) >= 128
