#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""embed_server.py — L1 常驻向量服务（SPEC-41-L1 新闻意图检索 §8.8）

背景：前端 /api/data/query 每次请求 spawn 新 python 进程，SentenceTransformer
冷启动实测 10–12s、常驻 RSS ~900MB；并发语义请求会 N 倍放大内存（OOM 风险）。

本服务把模型加载收敛到**一个常驻进程**：
- 启动即后台预热，之后单次 /embed 约 30–60ms
- 内存只有一份（systemd MemoryMax 兜底）

协议（仅监听回环地址）：
    GET  /health          → {"ok":true,"ready":bool,"zh_model":..,"zh_dim":..,"rss_mb":..}
    POST /embed           → {"vectors":[[...]]}
         body: {"texts":["..."],"lang":"zh"}

FAIL-OPEN：模型加载失败返回 503，调用方（embedder_bridge）降级为纯正则。
"""

import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_INDEX_ROOT = _HERE.parent
_WORKSPACE_ROOT = _INDEX_ROOT.parent
_RAG_INFRA = str(_WORKSPACE_ROOT / "2-KNOWLEDGE" / "9-RAG-INFRA")
if _RAG_INFRA not in sys.path:
    sys.path.insert(0, _RAG_INFRA)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("embed_server")

HOST = os.environ.get("L1_EMBED_HOST", "127.0.0.1")
PORT = int(os.environ.get("L1_EMBED_PORT", "8099"))
ZH_MODEL = os.environ.get("L1_ZH_MODEL", "BAAI/bge-base-zh-v1.5")
EN_MODEL = os.environ.get("L1_EN_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MAX_TEXTS = 64
MAX_TEXT_LEN = 2000

_embedders: Dict[str, object] = {}
_load_lock = threading.Lock()
_encode_lock = threading.Lock()  # torch CPU 推理串行化，避免线程争抢
_last_error: Optional[str] = None


def _model_for(lang: str) -> str:
    return ZH_MODEL if (lang or "zh").lower() == "zh" else EN_MODEL


def _get_embedder(lang: str):
    """懒加载并缓存 embedder（每种语言一份）。失败抛异常。"""
    lang = (lang or "zh").lower()
    if lang in _embedders:
        return _embedders[lang]
    with _load_lock:
        if lang in _embedders:
            return _embedders[lang]
        from vector_store.embedder import Embedder

        model = _model_for(lang)
        logger.info("加载模型 %s (lang=%s) ...", model, lang)
        emb = Embedder(model)
        emb.embed_batch(["自检"])  # 触发真实加载并验证可用
        _embedders[lang] = emb
        logger.info("模型就绪: %s", model)
        return emb


def _warmup() -> None:
    """后台预热中文模型，避免首个请求吃 10s 冷启动。"""
    global _last_error
    try:
        _get_embedder("zh")
    except Exception as e:  # noqa: BLE001
        _last_error = f"{type(e).__name__}: {e}"
        logger.error("预热失败: %s", _last_error)


def _rss_mb() -> Optional[float]:
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 降噪：只记错误
        if str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            logger.warning("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path != "/health":
            self._send(404, {"ok": False, "error": "not_found"})
            return
        zh_dim = None
        try:
            emb = _embedders.get("zh")
            if emb is not None:
                zh_dim = len(emb.embed_batch(["自检"])[0])
        except Exception as e:  # noqa: BLE001
            logger.warning("health 探测维度失败: %s", e)
        self._send(
            200,
            {
                "ok": True,
                "ready": "zh" in _embedders,
                "zh_model": ZH_MODEL,
                "zh_dim": zh_dim,
                "pid": os.getpid(),
                "rss_mb": _rss_mb(),
                "last_error": _last_error,
            },
        )

    def do_POST(self):  # noqa: N802
        if self.path != "/embed":
            self._send(404, {"ok": False, "error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            texts: List[str] = body.get("texts") or []
            lang = (body.get("lang") or "zh").lower()
            if not isinstance(texts, list) or not texts:
                self._send(400, {"ok": False, "error": "empty_texts"})
                return
            if len(texts) > MAX_TEXTS or any(len(t) > MAX_TEXT_LEN for t in texts):
                self._send(400, {"ok": False, "error": "too_large"})
                return
            emb = _get_embedder(lang)
            with _encode_lock:
                vecs = emb.embed_batch([str(t) for t in texts])
            self._send(200, {"vectors": [v.tolist() for v in vecs]})
        except Exception as e:  # noqa: BLE001
            logger.error("/embed 失败: %s", e)
            self._send(503, {"ok": False, "error": f"{type(e).__name__}: {e}"})


def main() -> None:
    threading.Thread(target=_warmup, name="warmup", daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    logger.info("embed_server 监听 http://%s:%d（zh=%s）", HOST, PORT, ZH_MODEL)
    srv.serve_forever()


if __name__ == "__main__":
    main()
