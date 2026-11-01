"""OS 层定时逻辑只读旁路（C13）：解析 launchd/systemd 状态 → job_runs 记账。

硬约束（SPEC-L0 §6 C13 + §10）：
  - 只读旁路：只跑 `launchctl list` / `systemctl show` + 读日志 mtime，
    禁止改 ExecStart/plist（不写 unit、不 load/unload、不新增系统定时条目）；
  - 每端各 1 个非实盘周期任务（本地 com.dreambuddy.dbsync、
    云端 memory-cleanup.timer）；实盘进程一律不内嵌记账；
  - 只经 Store/Event port 落库，禁止直连 PG/SQLite；
  - FAIL-OPEN：探测失败只标 degraded，不抛错、不阻断调用方；
  - 幂等：run key = task_key@logical_window，重复旁路扫描不重复记账。
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional

from .job_runs import JobRunRecorder, run_key
from .registry import TaskRegistry, load_registry
from .windows import window_index

Runner = Callable[[List[str]], str]

_LAST_EXIT_RE = re.compile(r'"LastExitStatus"\s*=\s*(\d+)')
_PRINT_EXIT_RE = re.compile(r"last exit code\s*=\s*(\d+)")
_PID_RE = re.compile(r'"PID"\s*=\s*(\d+)')
_RUNNING_RE = re.compile(r"^\s*state\s*=\s*running\s*$", re.M)


def _default_runner(cmd: List[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return (proc.stdout or "") + (proc.stderr or "")


def _parse_systemd_timestamp(raw: str) -> Optional[float]:
    """LastTriggerUSec 两种形态解析：µs 整数（旧版）或本地格式化时间（新版）。

    systemd 新版直接输出本机本地时区时间（如 "Sun 2026-11-01 02:05:01 CST"），
    时区缩写不可靠（CST 歧义），故去掉星期/时区后缀按本机本地时间解释
    （探针与 systemctl 同机运行，口径一致）。
    """
    text = (raw or "").strip()
    if not text or text in ("0", "n/a"):
        return None
    try:
        usec = int(text)
        return usec / 1_000_000.0 if usec > 0 else None
    except ValueError:
        pass
    body = re.sub(r"^[A-Za-z]{3}\s+", "", text)
    body = re.sub(r"\s+[A-Za-z]{2,6}$", "", body)
    try:
        return time.mktime(time.strptime(body, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


# ── systemd timer 探针 ──────────────────────────────────────────────────────
def probe_systemd_timer(
    timer_unit: str, *, runner: Optional[Runner] = None, service_unit: str = ""
) -> Dict[str, Any]:
    """`systemctl show` 只读解析：上次触发时刻 + 退出码。FAIL-OPEN。"""
    runner = runner or _default_runner
    out: Dict[str, Any] = {
        "ok": False,
        "triggered": False,
        "started_ts": None,
        "exit_code": None,
        "result": "",
        "reason": "",
    }
    try:
        raw = runner(["systemctl", "show", timer_unit, "-p", "LastTriggerUSec", "--value"])
        started_ts = _parse_systemd_timestamp(raw)
        if started_ts is None or started_ts <= 0:
            out["ok"] = True
            out["reason"] = "never_triggered"
            return out
        out["triggered"] = True
        out["started_ts"] = started_ts
        svc = service_unit or timer_unit.replace(".timer", ".service")
        show = runner(["systemctl", "show", svc, "-p", "ExecMainStatus", "-p", "Result"])
        props = {}
        for line in (show or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        out["exit_code"] = int(props.get("ExecMainStatus") or 0)
        out["result"] = props.get("Result", "")
        out["ok"] = True
        return out
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out


# ── launchd agent 探针 ──────────────────────────────────────────────────────
def probe_launchd_agent(
    label: str, *, runner: Optional[Runner] = None, plist_path: Optional[str] = None
) -> Dict[str, Any]:
    """`launchctl list` + plist 日志 mtime 只读解析。launchd 不记运行时刻，
    以 plist StandardOutPath 的 mtime 为上次活动时间（只读口径）。FAIL-OPEN。"""
    runner = runner or _default_runner
    out: Dict[str, Any] = {
        "ok": False,
        "triggered": False,
        "started_ts": None,
        "exit_code": None,
        "result": "",
        "reason": "",
    }
    try:
        # 现代 macOS（Catalina+）legacy `list <label>` 查不到 gui 域 agent，
        # 优先 `print gui/<uid>/<label>`，查不到再回落 legacy list（两端同口径）。
        raw = ""
        negative = False
        for cmd in (
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            ["launchctl", "list", label],
        ):
            text = runner(cmd) or ""
            if "Could not find" in text:
                negative = True
                continue
            if text.strip():
                raw = text
                break
        if not raw:
            out["ok"] = True
            out["reason"] = "not_loaded" if negative else "no_output"
            return out
        exit_match = _LAST_EXIT_RE.search(raw) or _PRINT_EXIT_RE.search(raw)
        out["exit_code"] = int(exit_match.group(1)) if exit_match else 0
        out["result"] = "success" if out["exit_code"] == 0 else "exit-code"
        out["running"] = bool(_PID_RE.search(raw) or _RUNNING_RE.search(raw))
        plist_path = plist_path or os.path.expanduser(
            os.path.join("~", "Library", "LaunchAgents", f"{label}.plist")
        )
        log_path = ""
        if os.path.exists(plist_path):
            with open(plist_path, "rb") as f:
                plist = plistlib.load(f)
            log_path = str(plist.get("StandardOutPath") or "")
        if not log_path or not os.path.exists(log_path):
            out["ok"] = True
            out["reason"] = "no_log"
            return out
        out["triggered"] = True
        out["started_ts"] = os.path.getmtime(log_path)
        out["ok"] = True
        return out
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out


# ── 旁路同步：探测 → 幂等记账 ───────────────────────────────────────────────
def sync_sidecar(
    task_key: str,
    *,
    recorder: JobRunRecorder,
    registry: Optional[TaskRegistry] = None,
    runner: Optional[Runner] = None,
    plist_path: Optional[str] = None,
) -> Dict[str, Any]:
    """把 OS 单元的上次执行旁路记入 job_runs。FAIL-OPEN，永不抛错。"""
    try:
        registry = registry or recorder.registry or load_registry()
        spec = registry.get(task_key)
        if spec is None:
            return {
                "degraded": True,
                "error_code": "task_unavailable",
                "recorded": False,
                "reason": f"未注册的 task_key: {task_key}",
                "run_ids": [],
            }
        if spec.carrier in ("systemd", "systemd-timer"):
            probe = probe_systemd_timer(spec.unit, runner=runner)
        elif spec.carrier == "launchd":
            probe = probe_launchd_agent(spec.unit, runner=runner, plist_path=plist_path)
        else:
            return {
                "degraded": True,
                "error_code": "carrier_unsupported",
                "recorded": False,
                "reason": f"carrier={spec.carrier} 不支持旁路",
                "run_ids": [],
            }
        if not probe.get("ok"):
            return {
                "degraded": True,
                "error_code": "probe_failed",
                "recorded": False,
                "reason": probe.get("reason", ""),
                "run_ids": [],
            }
        if not probe.get("triggered"):
            return {
                "degraded": False,
                "error_code": "",
                "recorded": False,
                "reason": probe.get("reason") or "never_triggered",
                "run_ids": [],
            }
        started_ts = float(probe["started_ts"])
        window = window_index(started_ts, spec.window_sec)
        rid = run_key(spec.task_key, window)
        res = recorder.store.query(recorder.table, filters={"run_id": rid}, limit=2) or {}
        if res.get("rows"):
            return {
                "degraded": False,
                "error_code": "",
                "recorded": False,
                "reason": "duplicate",
                "run_ids": [rid],
            }
        exit_code = probe.get("exit_code")
        result = probe.get("result", "")
        error = ""
        if (exit_code not in (0, None)) or (result and result != "success"):
            error = f"result={result} exit={exit_code}"
        rows = recorder.record_run(
            spec.task_key, started_ts=started_ts, finished_ts=started_ts, error=error
        )
        return {
            "degraded": False,
            "error_code": "",
            "recorded": True,
            "reason": "",
            "run_ids": [r.get("run_id", rid) for r in rows],
        }
    except Exception as exc:  # FAIL-OPEN：旁路故障不得影响被观测任务
        return {
            "degraded": True,
            "error_code": "sidecar_failed",
            "recorded": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "run_ids": [],
        }
