"""上游命中归一与入队。

上游对接方式（只读公开 CLI，不 import、不写死上游路径）：
- `ra report --json`      取命中（reservation.v1）
- `ra watch list --json`  取任务目标明细（target_id / session / price_tier / max_price）

也可从本地 feed 文件（reservation.v1 或规范化命中列表）导入，便于离线/测试。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

TERMINAL_SUBMIT = ("submitted", "unknown", "closed")


def build_hit(
    adapter: str,
    task_id: str,
    fingerprint: str,
    at: int,
    target: dict | None = None,
    max_price: float | None = None,
) -> dict:
    return {
        "adapter": adapter,
        "task_id": task_id,
        "fingerprint": fingerprint,
        "at": int(at),
        "target": target or {},
        "max_price": max_price,
    }


def task_meta_from_watch(watch: dict) -> dict[str, dict]:
    """把 `watch list --json` 的 tasks 归一为 {id: {...}}。"""
    meta: dict[str, dict] = {}
    for row in watch.get("tasks") or []:
        tid = row.get("id")
        if not tid:
            continue
        meta[tid] = {
            "adapter": row.get("adapter", ""),
            "target": {
                "target_id": row.get("target_id", ""),
                "session": row.get("session", ""),
                "price_tier": row.get("price_tier", ""),
            },
            "max_price": row.get("max_price"),
        }
    return meta


def hits_from_report(report: dict, task_meta: dict[str, dict] | None = None) -> list[dict]:
    """把 reservation.v1 报告归一为命中列表；跳过已终态的命中。"""
    task_meta = task_meta or {}
    result: list[dict] = []
    for hit in report.get("hits") or []:
        if (hit.get("submit_state") or "") in TERMINAL_SUBMIT:
            continue
        task_id = hit.get("task_id", "")
        fingerprint = hit.get("fingerprint", "")
        if not fingerprint:
            continue
        meta = task_meta.get(task_id, {})
        target = hit.get("target") or meta.get("target") or {}
        adapter = hit.get("adapter") or meta.get("adapter") or ""
        result.append(
            build_hit(
                adapter=adapter,
                task_id=task_id,
                fingerprint=fingerprint,
                at=int(hit.get("at") or 0),
                target=target,
                max_price=hit.get("max_price", meta.get("max_price")),
            )
        )
    return result


def hits_from_list(items: list[dict]) -> list[dict]:
    """规范化命中列表（每项自带 adapter/task_id/fingerprint）。"""
    result: list[dict] = []
    for item in items:
        if not item.get("fingerprint"):
            continue
        result.append(
            build_hit(
                adapter=item.get("adapter", ""),
                task_id=item.get("task_id", ""),
                fingerprint=item["fingerprint"],
                at=int(item.get("at") or 0),
                target=item.get("target") or {},
                max_price=item.get("max_price"),
            )
        )
    return result


def _run_ra_json(ra_cli: str, *args: str) -> dict:
    proc = subprocess.run(
        [str(ra_cli), *args], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "上游 CLI 失败（exit {}）：{}".format(proc.returncode, proc.stderr.strip()[:200])
        )
    return json.loads(proc.stdout)


def load_hits(ra_cli: str | None = None, source: str | None = None) -> list[dict]:
    """统一入口：优先 --source file:path；否则需 --ra-cli。"""
    if source:
        if not source.startswith("file:"):
            raise ValueError("--source 仅支持 file:<path>")
        data = json.loads(Path(source[len("file:"):]).read_text(encoding="utf-8"))
        if isinstance(data, list):
            return hits_from_list(data)
        meta = task_meta_from_watch(data.get("watch") or {})
        return hits_from_report(data, meta)
    if not ra_cli:
        raise ValueError("需要 --ra-cli <ra.py> 或 --source file:<path>")
    report = _run_ra_json(ra_cli, "report", "--json")
    watch = _run_ra_json(ra_cli, "watch", "list", "--json")
    return hits_from_report(report, task_meta_from_watch(watch))


def ingest_into(store, hits: list[dict]) -> dict:
    """入队；返回新增/跳过计数。"""
    added = 0
    skipped = 0
    for hit in hits:
        if store.enqueue_job(hit):
            added += 1
            store.add_event("info", "job_enqueued", hit["task_id"], {"fingerprint": hit["fingerprint"][:12]})
        else:
            skipped += 1
    return {"added": added, "skipped": skipped, "total": len(hits)}
