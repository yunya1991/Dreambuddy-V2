"""SPEC-33-F T-F16：语义检索复用现有检索系统（41 向量桥）。

验收：
  - 默认关闭：未设 `REA_SEMANTIC_ENABLED=1` 时不发起检索，返回 degraded + known_gaps。
  - 复用本机 Unix socket 通道，命中按 score 降序、同路径去重、分数夹紧到 [0,1]。
  - 通道缺失/超时/响应损坏 → FAIL-OPEN（degraded=true，不抛异常，不伪造命中）。
  - 无路径的命中被丢弃并计入 known_gaps（不可溯源）。
  - `get_rea_snapshot(section="semantic")` 透出 hits，且 MCP schema 已登记该 section。
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import uuid
from pathlib import Path

import pytest

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import dsh_nodes  # noqa: E402
from adapters.semantic_adapter import search_semantic  # noqa: E402

_BRIDGE_RESPONSE = {
    "ok": True,
    "results": [
        {"source_file": "src/b.py", "score": 0.42, "snippet": "beta"},
        {"source_file": "src/a.py", "score": 0.91, "heading": "Alpha", "snippet": "alpha"},
        {"source_file": "src/b.py", "score": 0.77, "snippet": "beta-2"},
        {"score": 0.99, "snippet": "missing path"},
    ],
}


class _FakeBridge(threading.Thread):
    """一次性 Unix socket 服务：收一行请求，回一段原始字节。"""

    def __init__(self, path: Path, payload: bytes) -> None:
        super().__init__(daemon=True)
        self.path = path
        self.payload = payload
        self.ready = threading.Event()

    def run(self) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.path))
            server.listen(1)
            self.ready.set()
            try:
                conn, _ = server.accept()
                with conn:
                    conn.recv(65536)
                    conn.sendall(self.payload)
            except OSError:
                return
            finally:
                try:
                    self.path.unlink()
                except OSError:
                    pass


def _start_bridge(payload: bytes) -> _FakeBridge:
    # Unix socket 路径受 104 字节限制，统一放在 /tmp 下用短名
    bridge = _FakeBridge(Path("/tmp") / f"rea-sem-{uuid.uuid4().hex[:8]}.sock", payload)
    bridge.start()
    assert bridge.ready.wait(2)
    return bridge


def test_disabled_by_default_does_not_query(monkeypatch):
    monkeypatch.delenv("REA_SEMANTIC_ENABLED", raising=False)
    report = search_semantic("订单超时重试")
    assert report["degraded"] is True
    assert report["hits"] == []
    assert report["engine"] == "disabled"
    assert any("未启用" in gap for gap in report["known_gaps"])


def test_socket_hits_are_sorted_deduped_and_traceable(tmp_path, monkeypatch):
    payload = json.dumps(_BRIDGE_RESPONSE).encode("utf-8")
    bridge = _start_bridge(payload)
    monkeypatch.setenv("REA_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("REA_SEMANTIC_SOCK", str(bridge.path))
    monkeypatch.delenv("REA_SEMANTIC_CMD", raising=False)

    report = search_semantic("库存扣减", top_k=10)
    assert report["degraded"] is False
    assert report["engine"] == "fis-vector-bridge"
    assert [hit["path"] for hit in report["hits"]] == ["src/a.py", "src/b.py"]
    assert report["hits"][0]["score"] == 0.91
    assert report["hits"][1]["score"] == 0.77  # 同路径取最高分
    assert [hit["rank"] for hit in report["hits"]] == [1, 2]
    assert all(hit["path"] for hit in report["evidence"])
    assert any("缺少文件路径" in gap for gap in report["known_gaps"])


def test_malformed_response_fails_open(tmp_path, monkeypatch):
    bridge = _start_bridge(b"not-json")
    monkeypatch.setenv("REA_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("REA_SEMANTIC_SOCK", str(bridge.path))
    monkeypatch.delenv("REA_SEMANTIC_CMD", raising=False)

    report = search_semantic("任意查询")
    assert report["degraded"] is True
    assert report["hits"] == []
    assert report["engine"] == "disabled"


def test_missing_channels_fail_open(tmp_path, monkeypatch):
    monkeypatch.setenv("REA_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("REA_SEMANTIC_SOCK", str(tmp_path / "absent.sock"))
    monkeypatch.delenv("REA_SEMANTIC_CMD", raising=False)

    report = search_semantic("任意查询")
    assert report["degraded"] is True
    assert report["hits"] == []
    assert len(report["known_gaps"]) == 2  # socket 与命令通道都不可用


def test_command_channel_fallback(tmp_path, monkeypatch):
    script = tmp_path / "fake_semantic.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read() or '{}')\n"
        "print(json.dumps({'results': [{'path': payload['query'] + '.py', 'score': 1.5}]}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REA_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("REA_SEMANTIC_SOCK", str(tmp_path / "absent.sock"))
    monkeypatch.setenv("REA_SEMANTIC_CMD", f"{sys.executable} {script}")

    report = search_semantic("checkout")
    assert report["degraded"] is False
    assert report["engine"] == "semantic-command"
    assert report["hits"][0]["path"] == "checkout.py"
    assert report["hits"][0]["score"] == 1.0  # 越界分数被夹紧


def test_snapshot_section_semantic(tmp_path, monkeypatch):
    payload = json.dumps(_BRIDGE_RESPONSE).encode("utf-8")
    bridge = _start_bridge(payload)
    monkeypatch.setenv("REA_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("REA_SEMANTIC_SOCK", str(bridge.path))
    monkeypatch.delenv("REA_SEMANTIC_CMD", raising=False)

    snapshot_id = "snap-test-semantic"
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / f"{snapshot_id}.json").write_text(
        json.dumps({"target": str(tmp_path), "evidence": [], "raw": {"modules": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshots)

    result = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": snapshot_id, "section": "semantic", "query": "库存扣减"}
    )
    assert result["ok"] is True
    assert result["result"]["section"] == "semantic"
    assert result["result"]["total"] == 2
    assert result["result"]["report"]["engine"] == "fis-vector-bridge"
    assert result["result"]["items"][0]["path"] == "src/a.py"


def test_snapshot_semantic_without_query_is_degraded(tmp_path, monkeypatch):
    monkeypatch.delenv("REA_SEMANTIC_ENABLED", raising=False)
    snapshot_id = "snap-test-semantic-empty"
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / f"{snapshot_id}.json").write_text(
        json.dumps({"target": str(tmp_path), "raw": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshots)

    result = dsh_nodes.get_rea_snapshot({"snapshot_id": snapshot_id, "section": "semantic"})
    assert result["ok"] is True
    assert result["result"]["items"] == []
    assert result["result"]["report"]["degraded"] is True
    assert any("query" in gap for gap in result["result"]["report"]["known_gaps"])


def test_mcp_schema_registers_semantic_section():
    from mcp_shells.l0_rea import server as rea_server

    schema = rea_server.TOOL_DEFS["get_rea_snapshot"]["inputSchema"]["properties"]["section"]
    assert "semantic" in schema["enum"]


@pytest.mark.parametrize("query", ["", "   "])
def test_blank_query_is_rejected(query, monkeypatch):
    monkeypatch.setenv("REA_SEMANTIC_ENABLED", "1")
    report = search_semantic(query)
    assert report["degraded"] is True
    assert report["hits"] == []
    assert any("query" in gap for gap in report["known_gaps"])
