# -*- coding: utf-8 -*-
"""L1 建议器影子模式（SPEC v1.4 §9.3 E2-B）。

定位：只**记录**语义 top3 候选，不改变任何返回字段、不参与判决、不阻塞主链路。
用途：积累线上真实问法下"模型推荐质量"，为是否上前端建议卡片提供证据。

开关（默认关闭，生产零影响）：
  L1_SUGGEST_SHADOW=1
日志路径（默认 <repo>/logs/l1_suggest_shadow.jsonl）：
  L1_SUGGEST_SHADOW_LOG=/path/to.jsonl

统计：
  python3 l1_suggest_shadow.py --summary
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from collections import Counter
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_LOG = os.path.abspath(os.path.join(_HERE, "..", "..", "logs", "l1_suggest_shadow.jsonl"))
_QUEUE_MAX = 1000

_queue: "queue.Queue" = queue.Queue(maxsize=_QUEUE_MAX)
_lock = threading.Lock()
_worker_started = False


def enabled() -> bool:
    return (os.environ.get("L1_SUGGEST_SHADOW", "0") or "0").strip().lower() in (
        "1",
        "true",
        "on",
        "yes",
    )


def log_path() -> str:
    return os.environ.get("L1_SUGGEST_SHADOW_LOG") or _DEFAULT_LOG


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        t = threading.Thread(target=_run, name="l1-suggest-shadow", daemon=True)
        t.start()
        _worker_started = True


def _run() -> None:
    while True:
        item = _queue.get()
        try:
            if item is None:
                return
            _write(item)
        except Exception:  # noqa: BLE001 — 影子模式任何异常都不得影响主链路
            pass
        finally:
            _queue.task_done()


def _write(item: dict) -> None:
    # 延迟导入：避免与 l1_route_signal 形成循环依赖
    from l1_route_signal import semantic_candidates  # noqa: PLC0415

    t0 = time.perf_counter()
    error = None
    try:
        top = semantic_candidates(item["message"], k=3)
    except Exception as e:  # noqa: BLE001 — FAIL-OPEN
        top, error = [], str(e)[:120]
    row = dict(item)
    row.update(
        {
            "top": [[i, round(s, 4)] for i, s in top],
            "empty": not top,
            "error": error,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
    )
    path = log_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def record(
    message: str, intent: str = "", decision: str = "", trace_id: str = "", strategy: str = ""
) -> None:
    """非阻塞写入影子队列；关闭/异常/队列满时静默丢弃。"""
    if not enabled() or not message:
        return
    _ensure_worker()
    try:
        _queue.put_nowait(
            {
                "message": message,
                "intent": intent,
                "decision": decision,
                "strategy": strategy,
                "trace_id": trace_id,
            }
        )
    except queue.Full:
        pass


def flush(timeout: float = 10.0) -> bool:
    """等待队列排空（测试与优雅退出用）。"""
    if not _worker_started:
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _queue.unfinished_tasks == 0:
            return True
        time.sleep(0.02)
    return False


def summarize(path: str = "") -> dict:
    """离线统计：样本量、空候选率、延迟、top1 分布、按意图分布。"""
    path = path or log_path()
    if not os.path.exists(path):
        return {"path": path, "n": 0}
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    n = len(rows)
    lat = sorted(r.get("latency_ms", 0.0) for r in rows)
    top1 = Counter(r["top"][0][0] for r in rows if r.get("top"))
    by_decision = Counter(r.get("decision", "") for r in rows)
    return {
        "path": path,
        "n": n,
        "empty_rate": sum(1 for r in rows if r.get("empty")) / n if n else 0.0,
        "error_rate": sum(1 for r in rows if r.get("error")) / n if n else 0.0,
        "latency_p50_ms": lat[n // 2] if n else 0.0,
        "latency_p95_ms": lat[min(n - 1, int(0.95 * n))] if n else 0.0,
        "top1_dist": top1.most_common(8),
        "by_decision": dict(by_decision),
    }


def main() -> int:
    if "--summary" in sys.argv:
        path = ""
        if "--path" in sys.argv:
            path = sys.argv[sys.argv.index("--path") + 1]
        print(json.dumps(summarize(path), ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
