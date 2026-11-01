"""调度/能力健康聚合（C12）：job_runs 统计 + capabilities.yaml health_cmd 探活。

硬约束：
  - 探测以 capabilities.yaml 的 health_cmd 为唯一依据，
    不依赖 systemd/launchd 内部状态（SPEC-L0 §6 C12）；
  - 只经 Store port 读 job_runs，禁止直连 PG/SQLite；
  - FAIL-OPEN：单项故障只标 degraded，不抛错、不拖垮其他分项；
  - 两端同口径：health_cmd 一律以仓库根为 cwd 执行，host 过滤任务归属。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Optional, Tuple

import yaml

from .registry import TaskRegistry, load_registry

OPEN_STATES = ("pending", "claimed", "running")
TERMINAL_STATES = ("succeeded", "failed", "timeout", "dead")
FAIL_STATES = ("failed", "timeout", "dead", "missed_run")

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_CAPABILITIES_PATH = os.path.join(_REPO_ROOT, "0-系统文档管理", "capabilities.yaml")
DEFAULT_JOB_RUNS_PATH = os.path.join(_REPO_ROOT, "logs", "job_runs.jsonl")

Runner = Callable[..., Tuple[int, str]]


def _default_runner(cmd: str, *, cwd: str, timeout: float) -> Tuple[int, str]:
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "").strip()[-200:]


def _detect_host() -> str:
    return "local" if sys.platform == "darwin" else "cloud"


def _default_store(repo_root: str, job_runs_path: str):
    from ..adapters.jsonl import JsonlStore

    path = (
        job_runs_path
        or os.environ.get("JOB_RUNS_PATH")
        or os.path.join(repo_root, "logs", "job_runs.jsonl")
    )
    return JsonlStore(path)


# ── 调度分项：跑没跑 / 成功率 / 最老滞留 / missed streak ────────────────────
def _task_stats(rows, *, now: float, streak_alert: int) -> Dict[str, Any]:
    state_counts: Dict[str, int] = {}
    for r in rows:
        state = str(r.get("state", "unknown"))
        state_counts[state] = state_counts.get(state, 0) + 1
    terminal = sum(state_counts.get(s, 0) for s in TERMINAL_STATES)
    succeeded = state_counts.get("succeeded", 0)
    open_starts = [
        float(r.get("started_at") or 0)
        for r in rows
        if r.get("state") in OPEN_STATES and r.get("started_at")
    ]
    finished = [float(r.get("finished_at") or 0) for r in rows if r.get("finished_at")]
    ordered = sorted(rows, key=lambda r: int(r.get("logical_window", 0)))
    streak = 0
    for r in reversed(ordered):
        if r.get("state") == "missed_run":
            streak += 1
        else:
            break
    return {
        "has_run": bool(rows),
        "total": len(rows),
        "state_counts": state_counts,
        "success_rate": (succeeded / terminal) if terminal else None,
        "oldest_open_age_sec": (now - min(open_starts)) if open_starts else None,
        "last_finished_at": max(finished) if finished else None,
        "missed_streak": streak,
        "alert": streak >= streak_alert,
    }


def _scheduling_section(
    store: Any, registry: Optional[TaskRegistry], *, host: str, now: float
) -> Tuple[Dict[str, Any], str, Dict[str, int]]:
    """返回 (分项, error_code, 降级原因分布)。任何单步故障只降级不抛错。"""
    reasons: Dict[str, int] = {}
    if registry is None:
        return (
            {"degraded": True, "error_code": "registry_unavailable", "tasks": {}},
            "registry_unavailable",
            reasons,
        )
    try:
        res = store.query("job_runs", limit=5000) or {}
        all_rows = res.get("rows") or []
    except Exception:
        return (
            {"degraded": True, "error_code": "store_unavailable", "tasks": {}},
            "store_unavailable",
            reasons,
        )
    by_task: Dict[str, list] = {}
    for row in all_rows:
        by_task.setdefault(str(row.get("task_key", "")), []).append(row)
    tasks: Dict[str, Any] = {}
    error_code = ""
    for spec in registry.list():
        if host and spec.host and spec.host != host:
            continue
        stats = _task_stats(
            by_task.get(spec.task_key, []),
            now=now,
            streak_alert=registry.missed_streak_alert,
        )
        stats.update(
            {
                "host": spec.host,
                "enabled": spec.enabled,
                "window_sec": spec.window_sec,
            }
        )
        tasks[spec.task_key] = stats
        for state in FAIL_STATES:
            count = stats["state_counts"].get(state, 0)
            if count:
                key = f"job:{state}"
                reasons[key] = reasons.get(key, 0) + count
        if stats["alert"] and not error_code:
            error_code = "scheduling_missed_run"
    return (
        {"degraded": bool(error_code), "tasks": tasks, "open_states": list(OPEN_STATES)},
        error_code,
        reasons,
    )


# ── 能力分项：health_cmd 探活 ───────────────────────────────────────────────
def _probe(cap: Dict[str, Any], *, runner: Runner, cwd: str, timeout: float) -> Dict[str, Any]:
    entry = {
        "port": str(cap.get("port") or ""),
        "declared_status": str(cap.get("status") or ""),
        "declared_degraded_reason": str(cap.get("degraded_reason") or ""),
        "health": "error",
        "latency_ms": 0,
        "detail": "",
    }
    cmd = str(cap.get("health_cmd") or "")
    if not cmd:
        entry["health"] = "missing"
        entry["detail"] = "health_cmd 未声明"
        return entry
    started = time.monotonic()
    try:
        code, out = runner(cmd, cwd=cwd, timeout=timeout)
        entry["latency_ms"] = int((time.monotonic() - started) * 1000)
        entry["detail"] = str(out or "")[-200:]
        if code == 0:
            entry["health"] = "ok" if str(out).strip() == "ok" else "missing"
        else:
            entry["health"] = "error"
    except subprocess.TimeoutExpired:
        entry["latency_ms"] = int((time.monotonic() - started) * 1000)
        entry["health"] = "timeout"
        entry["detail"] = f"timeout>{timeout}s"
    except Exception as exc:  # FAIL-OPEN：单能力探测失败不影响其他
        entry["latency_ms"] = int((time.monotonic() - started) * 1000)
        entry["health"] = "error"
        entry["detail"] = f"{type(exc).__name__}: {exc}"
    return entry


def _capabilities_section(
    capabilities_path: str, *, runner: Runner, cwd: str, timeout: float
) -> Tuple[Dict[str, Any], str, Dict[str, int]]:
    reasons: Dict[str, int] = {}
    try:
        with open(capabilities_path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        caps = doc.get("capabilities") or []
    except Exception:
        return {}, "capabilities_unavailable", reasons
    out: Dict[str, Any] = {}
    error_code = ""
    for cap in caps:
        cid = str(cap.get("capability_id") or "")
        if not cid:
            continue
        entry = _probe(cap, runner=runner, cwd=cwd, timeout=timeout)
        out[cid] = entry
        if entry["health"] != "ok":
            key = f"capability:{cid}:{entry['health']}"
            reasons[key] = reasons.get(key, 0) + 1
            if not error_code:
                error_code = "capability_unhealthy"
    return out, error_code, reasons


# ── 主入口 ─────────────────────────────────────────────────────────────────
def collect_l0_health(
    *,
    store: Any = None,
    registry: Optional[TaskRegistry] = None,
    capabilities_path: Optional[str] = None,
    repo_root: Optional[str] = None,
    host: str = "",
    now: Optional[float] = None,
    runner: Optional[Runner] = None,
    timeout_sec: float = 5.0,
    job_runs_path: str = "",
) -> Dict[str, Any]:
    """聚合 job_runs 与五能力 health，供 cognitive health 挂接。FAIL-OPEN。"""
    now = time.time() if now is None else float(now)
    repo_root = repo_root or _REPO_ROOT
    host = host or _detect_host()
    runner = runner or _default_runner
    capabilities_path = capabilities_path or os.path.join(
        repo_root, "0-系统文档管理", "capabilities.yaml"
    )
    if registry is None:
        try:
            registry = load_registry()
        except Exception:  # FAIL-OPEN：注册表损坏不拖垮健康聚合
            registry = None
    if store is None:
        try:
            store = _default_store(repo_root, job_runs_path)
        except Exception:
            store = None

    if store is None:
        scheduling = {"degraded": True, "error_code": "store_unavailable", "tasks": {}}
        sched_code = "store_unavailable"
        sched_reasons: Dict[str, int] = {}
    else:
        scheduling, sched_code, sched_reasons = _scheduling_section(
            store, registry, host=host, now=now
        )
    caps, caps_code, caps_reasons = _capabilities_section(
        capabilities_path, runner=runner, cwd=repo_root, timeout=timeout_sec
    )

    reasons = dict(sched_reasons)
    for key, count in caps_reasons.items():
        reasons[key] = reasons.get(key, 0) + count
    # error_code 优先级：存储 > 注册表 > 调度滞留 > 能力异常 > 声明缺失
    error_code = ""
    for code in (
        "store_unavailable",
        "registry_unavailable",
        "scheduling_missed_run",
        "capability_unhealthy",
        "capabilities_unavailable",
    ):
        if code in (sched_code, caps_code):
            error_code = code
            break
    return {
        "ok": not error_code,
        "degraded": bool(error_code),
        "error_code": error_code,
        "generated_at": now,
        "host": host,
        "scheduling": scheduling,
        "capabilities": caps,
        "degraded_reasons": reasons,
    }
