#!/usr/bin/env python3
"""vector_bridge_daemon.py — L3 向量检索常驻桥接（§13.6 优化项）
================================================================
以 luke 用户 + venv-trading 运行（chromadb 仅安装于该 venv）。
监听 Unix socket /tmp/fis_vector_bridge.sock，行分隔 JSON 协议：
  请求行: {"query": ..., "top_k": ...}
  响应行: {"ok": true, "results": [{"source_file", "score", "snippet", "heading"}]}
         或 {"ok": false}
特性：
  1. 空闲 600 秒自动退出（由调用方或 systemd 拉起）
  2. 单次查询异常不退出（返回 ok:false）
  3. socket 权限 666（ubuntu 侧 searcher 可连接）
  4. 启动时预加载 chromadb（消除首查冷启动）
"""
import json
import os
import socket
import sys
import time

SOCK_PATH = "/tmp/fis_vector_bridge.sock"
IDLE_TIMEOUT = 600  # 秒
RAG_INFRA = "/home/luke/dreambuddy/2-KNOWLEDGE/9-RAG-INFRA"


def load_search():
    sys.path.insert(0, RAG_INFRA)
    from vector_store.search import search
    return search


def handle(search_fn, req):
    query = str(req.get("query", "")).strip()
    top_k = max(1, min(int(req.get("top_k", 5)), 50))
    if not query:
        return {"ok": True, "results": []}
    results = search_fn(query, top_k=top_k) or []
    out = []
    for r in results:
        out.append({
            "source_file": str(r.get("source_file") or "").strip("/"),
            "score": float(r.get("score") or 0.0),
            "snippet": str(r.get("content") or "")[:200],
            "heading": str(r.get("heading") or ""),
        })
    return {"ok": True, "results": out}


def main() -> None:
    # 预加载向量检索（启动时付一次冷启动成本）
    try:
        search_fn = load_search()
    except Exception as e:
        print(f"daemon load failed: {e}", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(SOCK_PATH):
        os.unlink(SOCK_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o666)
    srv.listen(8)
    srv.settimeout(IDLE_TIMEOUT)
    print(f"daemon ready on {SOCK_PATH}", file=sys.stderr, flush=True)

    while True:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            print("daemon idle exit", file=sys.stderr, flush=True)
            break
        conn.settimeout(30)
        try:
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
            if line:
                try:
                    resp = handle(search_fn, json.loads(line))
                except Exception:
                    resp = {"ok": False}
                conn.sendall(json.dumps(resp, ensure_ascii=False).encode("utf-8") + b"\n")
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        os.unlink(SOCK_PATH)
    except Exception:
        pass


if __name__ == "__main__":
    main()
