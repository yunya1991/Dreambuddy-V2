"""通用定时任务：SQLite 台账 + cron 计算 + 幂等 run-due。

调度器入口只有一个 `run-due`（本机 launchd / 云端 systemd timer 都调它）：
- `run_key = job_key + scheduled_at` 唯一约束，天然幂等；
- 文件锁防重入；
- 停机错过只补最近一次（catch_up=latest），不雪崩。
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import plan  # noqa: E402
import workflow  # noqa: E402

AGENT_LABEL = "com.dreambuddy.jobs"
MINUTE = timedelta(minutes=1)


def db_path() -> Path:
    value = os.environ.get("DREAMBUDDY_JOBS_DB")
    if value:
        return Path(value)
    return plan.state_dir() / "jobs.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_key TEXT PRIMARY KEY,
            workflow TEXT NOT NULL,
            cron TEXT NOT NULL,
            next_run_at TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            catch_up TEXT NOT NULL DEFAULT 'latest',
            fail_count INTEGER NOT NULL DEFAULT 0,
            last_status TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_key TEXT PRIMARY KEY,
            job_key TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL,
            workflow_run_id TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT ''
        )
        """)
    conn.commit()
    return conn


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_field(expr: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            step = int(raw_step)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            raw_start, raw_end = part.split("-", 1)
            start, end = int(raw_start), int(raw_end)
        else:
            start = end = int(part)
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("E_CRON：空字段")
    if min(values) < low or max(values) > high:
        raise ValueError("E_CRON：字段越界 {}-{}".format(low, high))
    return values


class Cron:
    def __init__(self, expr: str) -> None:
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError("E_CRON：需要 5 段（分 时 日 月 周）")
        self.minute = _parse_field(fields[0], 0, 59)
        self.hour = _parse_field(fields[1], 0, 23)
        self.day = _parse_field(fields[2], 1, 31)
        self.month = _parse_field(fields[3], 1, 12)
        # cron 周：0/7=周日
        self.weekday = {item % 7 for item in _parse_field(fields[4], 0, 7)}
        self.expr = expr

    def matches(self, moment: datetime) -> bool:
        return (
            moment.minute in self.minute
            and moment.hour in self.hour
            and moment.day in self.day
            and moment.month in self.month
            and (moment.isoweekday() % 7) in self.weekday
        )

    def next_run(self, after: datetime) -> datetime:
        moment = after.replace(second=0, microsecond=0) + MINUTE
        limit = moment + timedelta(days=366)
        while moment < limit:
            if self.matches(moment):
                return moment
            moment += MINUTE
        raise ValueError("E_CRON：一年内没有匹配时间（{}）".format(self.expr))


def add(job_key: str, workflow_id: str, cron: str, catch_up: str = "latest") -> Dict[str, object]:
    workflow.load_workflow(workflow_id)
    schedule = Cron(cron)
    next_run = schedule.next_run(_now())
    conn = connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO jobs(job_key, workflow, cron, next_run_at, enabled, catch_up, fail_count, last_status, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?, 0, '', ?)",
            (
                job_key,
                workflow_id,
                cron,
                next_run.isoformat(),
                catch_up,
                _now().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"job_key": job_key, "next_run_at": next_run.isoformat(), "workflow": workflow_id}


def list_jobs() -> List[Dict[str, object]]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY job_key").fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def set_enabled(job_key: str, enabled: bool) -> int:
    conn = connect()
    try:
        cursor = conn.execute(
            "UPDATE jobs SET enabled=? WHERE job_key=?", (1 if enabled else 0, job_key)
        )
        conn.commit()
    finally:
        conn.close()
    return 0 if cursor.rowcount else 1


def remove(job_key: str) -> int:
    conn = connect()
    try:
        cursor = conn.execute("DELETE FROM jobs WHERE job_key=?", (job_key,))
        conn.commit()
    finally:
        conn.close()
    return 0 if cursor.rowcount else 1


def _lock() -> object:
    path = db_path().with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _run_job(row: sqlite3.Row, scheduled_at: datetime) -> Dict[str, object]:
    run_key = "{}:{}".format(row["job_key"], scheduled_at.isoformat())
    run_id = "job-{}-{}".format(row["job_key"], scheduled_at.strftime("%Y%m%dT%H%M%SZ"))
    conn = connect()
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO runs(run_key, job_key, scheduled_at, status, workflow_run_id, started_at) "
            "VALUES (?, ?, ?, 'running', ?, ?)",
            (run_key, row["job_key"], scheduled_at.isoformat(), run_id, _now().isoformat()),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return {"job_key": row["job_key"], "skipped": "duplicate", "run_key": run_key}
    finally:
        conn.close()

    code = workflow.run(str(row["workflow"]), run_id="", forced_id=run_id)
    status = "done" if code == 0 else "failed"
    next_run = Cron(str(row["cron"])).next_run(max(scheduled_at, _now()))
    conn = connect()
    try:
        conn.execute(
            "UPDATE runs SET status=?, finished_at=? WHERE run_key=?",
            (status, _now().isoformat(), run_key),
        )
        conn.execute(
            "UPDATE jobs SET next_run_at=?, last_status=?, fail_count=? WHERE job_key=?",
            (
                next_run.isoformat(),
                status,
                0 if code == 0 else int(row["fail_count"]) + 1,
                row["job_key"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    plan.audit("job.run", job_key=row["job_key"], run_key=run_key, status=status)
    return {
        "job_key": row["job_key"],
        "run_key": run_key,
        "workflow_run_id": run_id,
        "status": status,
    }


def run_due(now: Optional[datetime] = None) -> List[Dict[str, object]]:
    moment = now or _now()
    handle = _lock()
    results: List[Dict[str, object]] = []
    try:
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at",
                (moment.isoformat(),),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            results.append(_run_job(row, datetime.fromisoformat(row["next_run_at"])))
    finally:
        handle.close()
    return results


def run_now(job_key: str) -> int:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_key=?", (job_key,)).fetchone()
    finally:
        conn.close()
    if not row:
        print("E_JOB：找不到 {}".format(job_key))
        return 1
    result = _run_job(row, _now())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") != "failed" else 1


def agent_plist(python: str, entry: str) -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{entry}</string>
    <string>schedule</string>
    <string>run-due</string>
  </array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
""".format(
        label=AGENT_LABEL,
        python=python,
        entry=entry,
        log=str(plan.state_dir() / "jobs.log"),
    )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="59 域定时任务")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add")
    p_add.add_argument("workflow")
    p_add.add_argument("--cron", required=True)
    p_add.add_argument("--key", default="")
    p_add.add_argument("--catch-up", default="latest", choices=["latest", "none"])
    sub.add_parser("list")
    for name in ("pause", "resume", "rm", "run-now"):
        p = sub.add_parser(name)
        p.add_argument("job_key")
    p_due = sub.add_parser("run-due")
    p_due.add_argument("--print-agent", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "list":
        rows = list_jobs()
        if not rows:
            print(
                '（暂无 59 域定时任务）添加：dreambuddy schedule add <workflow> --cron "0 8 * * *"'
            )
            return 0
        for row in rows:
            print(
                "{job_key}  {workflow}  {cron}  next={next_run_at}  enabled={enabled}  last={last_status}".format(
                    **row
                )
            )
        return 0
    if args.cmd == "run-due":
        if args.print_agent:
            entry = str(TOOLS_DIR / "dreambuddy.py")
            print(agent_plist(sys.executable, entry))
            return 0
        results = run_due()
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0 if all(item.get("status") != "failed" for item in results) else 1
    if args.cmd == "add":
        key = args.key or args.workflow
        try:
            print(json.dumps(add(key, args.workflow, args.cron, args.catch_up), ensure_ascii=False))
        except ValueError as exc:
            print(str(exc))
            return 2
        return 0
    if args.cmd == "run-now":
        return run_now(args.job_key)
    enabled = args.cmd == "resume"
    if args.cmd in ("pause", "resume"):
        code = set_enabled(args.job_key, enabled)
    else:
        code = remove(args.job_key)
    if code:
        print("E_JOB：找不到 {}".format(args.job_key))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
