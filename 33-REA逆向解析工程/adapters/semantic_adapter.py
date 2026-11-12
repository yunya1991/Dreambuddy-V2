"""语义检索适配层（SPEC-33-F T-F16）。

设计边界（SPEC-F §2.1）：
  - 复用 41-文件索引系统 已有的向量桥（本机 Unix socket），不在 33 内自建
    embedding 模型或向量库；
  - 内核零网络：只允许本机 Unix socket 或本机子进程（`REA_SEMANTIC_CMD`），
    不访问任何远程服务；
  - 默认关闭（`REA_SEMANTIC_ENABLED` 未开启时直接返回 degraded），任何通道
    不可用/超时/响应损坏都 FAIL-OPEN：返回空命中 + `known_gaps`，绝不伪造数据；
  - 结果必须可溯源（命中项必须有文件路径），否则丢弃并计入 `known_gaps`。
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
from typing import Any

DEFAULT_SOCK = "/tmp/fis_vector_bridge.sock"
DEFAULT_TIMEOUT = 2.0
MAX_TIMEOUT = 5.0
MAX_TOP_K = 20
MAX_SNIPPET = 400
MAX_EVIDENCE = 20
_ENABLED_VALUES = {"1", "true", "yes", "on"}


def semantic_enabled() -> bool:
    """语义检索是否显式开启（默认关闭）。"""
    return str(os.environ.get("REA_SEMANTIC_ENABLED") or "").strip().lower() in _ENABLED_VALUES


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score != score:  # NaN
        return 0.0
    return round(min(max(score, 0.0), 1.0), 4)


def _pick(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    """兼容向量桥的多种返回形状，只取带文件路径的条目。"""
    if not isinstance(payload, dict):
        return []
    rows: Any = payload.get("results")
    if rows is None:
        rows = payload.get("hits")
    if rows is None and isinstance(payload.get("data"), dict):
        rows = payload["data"].get("results")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize(rows: list[dict[str, Any]], top_k: int) -> tuple[list[dict[str, Any]], list[str]]:
    """归一化命中：路径必填、按路径去重取最高分、按分数降序 + 路径升序稳定排序。"""
    known_gaps: list[str] = []
    best: dict[str, dict[str, Any]] = {}
    dropped = 0
    for row in rows:
        path = _pick(row, "path", "source_file", "file", "source")
        if not isinstance(path, str) or not path.strip():
            dropped += 1
            continue
        path = path.strip()
        score = _clamp_score(_pick(row, "score", "similarity", "relevance"))
        hit = {
            "path": path,
            "score": score,
            "heading": str(_pick(row, "heading", "title") or ""),
            "snippet": str(_pick(row, "snippet", "text", "chunk", "content") or "")[:MAX_SNIPPET],
        }
        current = best.get(path)
        if current is None or hit["score"] > current["score"]:
            best[path] = hit
    if dropped:
        known_gaps.append(f"语义检索有 {dropped} 条命中缺少文件路径，已丢弃（不可溯源）")
    hits = sorted(best.values(), key=lambda item: (-item["score"], item["path"]))[:top_k]
    for index, hit in enumerate(hits, start=1):
        hit["rank"] = index
    return hits, known_gaps


def _query_socket(query: str, top_k: int, timeout: float) -> tuple[Any, str | None]:
    sock_path = str(os.environ.get("REA_SEMANTIC_SOCK") or DEFAULT_SOCK).strip()
    if not sock_path:
        return None, "未配置语义检索 socket 路径"
    if not os.path.exists(sock_path):
        return None, f"语义检索通道不可用：socket 不存在（{sock_path}）"
    payload = json.dumps({"query": query, "top_k": top_k}, ensure_ascii=False).encode("utf-8")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(sock_path)
            client.sendall(payload + b"\n")
            chunks: list[bytes] = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(len(part) for part in chunks) > 1_000_000:
                    return None, "语义检索响应超过 1MB，已中止"
    except (OSError, socket.timeout) as exc:
        return None, f"语义检索通道不可用：{type(exc).__name__}"
    try:
        return json.loads(b"".join(chunks).decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "语义检索响应不是合法 JSON"


def _query_command(query: str, top_k: int, timeout: float) -> tuple[Any, str | None]:
    raw = str(os.environ.get("REA_SEMANTIC_CMD") or "").strip()
    if not raw:
        return None, "未配置语义检索命令通道"
    try:
        argv = shlex.split(raw)
    except ValueError:
        return None, "REA_SEMANTIC_CMD 无法解析"
    if not argv:
        return None, "REA_SEMANTIC_CMD 为空"
    request = json.dumps({"query": query, "top_k": top_k}, ensure_ascii=False)
    try:
        proc = subprocess.run(
            argv,
            input=request,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"语义检索命令不可用：{type(exc).__name__}"
    if proc.returncode != 0:
        return None, f"语义检索命令返回非零退出码（{proc.returncode}）"
    try:
        return json.loads(proc.stdout or ""), None
    except json.JSONDecodeError:
        return None, "语义检索命令输出不是合法 JSON"


def search_semantic(
    query: str,
    *,
    top_k: int = 10,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """按语义检索代码/文档片段（只读，可失败降级）。

    Args:
        query: 检索语句（必填，空白直接返回 degraded）。
        top_k: 返回条数（1..20）。
        timeout: 单通道超时秒数（<=5）。
    """
    text = str(query or "").strip()
    limit = min(max(_as_int(top_k, 10), 1), MAX_TOP_K)
    wait = min(max(float(timeout or DEFAULT_TIMEOUT), 0.1), MAX_TIMEOUT)
    report: dict[str, Any] = {
        "section": "semantic",
        "engine": "disabled",
        "query": text,
        "hits": [],
        "total": 0,
        "degraded": True,
        "evidence": [],
        "known_gaps": [],
    }
    if not text:
        report["known_gaps"] = ["缺少检索语句（query），无法执行语义检索"]
        return report
    if not semantic_enabled():
        report["known_gaps"] = [
            "语义检索未启用（REA_SEMANTIC_ENABLED 未设为 1）；本次未发起任何检索"
        ]
        return report

    engine = "fis-vector-bridge"
    payload, error = _query_socket(text, limit, wait)
    if error is not None:
        payload, cmd_error = _query_command(text, limit, wait)
        if cmd_error is not None:
            report["known_gaps"] = [error, cmd_error]
            return report
        engine = "semantic-command"

    hits, gaps = _normalize(_extract_rows(payload), limit)
    report.update(
        {
            "engine": engine,
            "hits": hits,
            "total": len(hits),
            "degraded": False,
            "known_gaps": gaps,
        }
    )
    report["evidence"] = [
        {
            "kind": "semantic_hit",
            "source": f"semantic:{engine}",
            "path": hit["path"],
            "score": hit["score"],
            "level": "observation",
            "confidence": hit["score"],
        }
        for hit in hits[:MAX_EVIDENCE]
    ]
    if not hits:
        report["known_gaps"].append("语义检索通道正常但无命中；可改用 trace/analyze 的结构路径")
    return report
