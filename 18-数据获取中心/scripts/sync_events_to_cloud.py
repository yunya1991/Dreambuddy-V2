#!/usr/bin/env python3
"""本地采集中文财经事件 → 增量同步到云端 → 触发云端 39 语义打分。

背景：云端出口被拦，jin10 / wallstreetcn / cls / sina_finance 四个中文源
采集恒为 0 事件；本地网络可正常抓取。因此把「采集」放在本地，把
「事件流 → 9 FinBERT（finbert-tone-chinese，模型在 18/models）打分 → 39
hot_news.json」留在云端。

流程（每次运行）：
  1. 本地跑 `python -m data_center.cli.collect_events --source cn --days 1`
     （失败 FAIL-OPEN：仍同步已有文件）
  2. 把本地 events.jsonl / bodies.jsonl 整文件传到云端 /tmp
  3. 云端用 18 的 append_events / append_bodies 按 event_id / body_id
     幂等合并（只追加新行，不覆盖云端官方源事件）
  4. 有新事件时触发云端 39 打分（detached + 文件日志，避免 SSH 断连杀进程）

用法：
  /opt/anaconda3/bin/python3 scripts/sync_events_to_cloud.py
  EVENTS_SYNC_DRY_RUN=1 ...  # 只采集不推云
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]  # 18-数据获取中心
EVENTS_PATH = PROJECT / "data_center" / "events" / "events.jsonl"
BODIES_PATH = PROJECT / "data_center" / "events" / "bodies.jsonl"

SSH_HOST = os.environ.get("EVENTS_SYNC_SSH_HOST", "dreambuddy-remote")
REMOTE_REPO = os.environ.get("EVENTS_SYNC_REMOTE_REPO", "/home/luke/dreambuddy")
REMOTE_PYTHON = os.environ.get("EVENTS_SYNC_REMOTE_PYTHON", "/home/luke/venv-trading/bin/python")
COLLECT_TIMEOUT = int(os.environ.get("EVENTS_SYNC_COLLECT_TIMEOUT", "600"))
DRY_RUN = os.environ.get("EVENTS_SYNC_DRY_RUN", "0") == "1"

REMOTE_SCRIPT = f"""set -u
cd '{REMOTE_REPO}/18-数据获取中心' || exit 1
merge_out=$(PYTHONPATH='{REMOTE_REPO}/18-数据获取中心:{REMOTE_REPO}/20-数据清洗中心' \\
'{REMOTE_PYTHON}' - <<'PY'
import json
from data_center.events.store import append_events
from data_center.events.body_store import append_bodies

with open('/tmp/events_sync.jsonl', encoding='utf-8') as f:
    ev = [json.loads(line) for line in f if line.strip()]
with open('/tmp/bodies_sync.jsonl', encoding='utf-8') as f:
    bd = [json.loads(line) for line in f if line.strip()]
ea, es = append_events(ev)
ba, bs = append_bodies(bd)
print(f'MERGED_EVENTS={{ea}} SKIPPED={{es}} BODIES_ADDED={{ba}} BODIES_SKIPPED={{bs}}')
PY
)
printf '%s\\n' "$merge_out"
added=$(printf '%s\\n' "$merge_out" | sed -n 's/.*MERGED_EVENTS=\\([0-9]*\\).*/\\1/p')
rm -f /tmp/events_sync.jsonl /tmp/bodies_sync.jsonl
if [ "${{added:-0}}" -gt 0 ]; then
  if pgrep -f 'gen_semantic_events.py --source events' >/dev/null; then
    echo 'GEN_ALREADY_RUNNING'
  else
    sudo -n -u luke -H sh -c "cd '{REMOTE_REPO}/39-金融语义蒸馏系统' && PYTHONUNBUFFERED=1 setsid nohup '{REMOTE_PYTHON}' scripts/gen_semantic_events.py --source events > /tmp/gen_sem_sync.log 2>&1 < /dev/null & echo GEN_STARTED"
  fi
else
  echo 'GEN_SKIPPED_NO_NEW'
fi
"""


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def collect() -> None:
    log("collect_events --source cn --days 1 ...")
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "data_center.cli.collect_events",
                "--source",
                "cn",
                "--days",
                "1",
            ],
            cwd=str(PROJECT),
            capture_output=True,
            text=True,
            timeout=COLLECT_TIMEOUT,
        )
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-6:]
        log(f"collect rc={proc.returncode} :: " + " | ".join(tail))
    except Exception as exc:  # noqa: BLE001 — 采集失败不阻断同步
        log(f"collect FAILED（继续同步已有文件）：{type(exc).__name__}: {exc}")


def push(local: Path, remote: str) -> None:
    subprocess.run(
        ["scp", "-q", "-o", "ConnectTimeout=15", str(local), f"{SSH_HOST}:{remote}"],
        check=True,
        timeout=180,
    )


def main() -> int:
    if not EVENTS_PATH.is_file():
        log(f"events.jsonl 不存在：{EVENTS_PATH}")
        return 1
    collect()
    if DRY_RUN:
        log("DRY_RUN=1，跳过同步")
        return 0

    log(f"上传 events/bodies → {SSH_HOST}")
    push(EVENTS_PATH, "/tmp/events_sync.jsonl")
    push(BODIES_PATH, "/tmp/bodies_sync.jsonl")

    log("云端幂等合并 ...")
    proc = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=15", SSH_HOST, "sudo -n -u luke -H bash -s"],
        input=REMOTE_SCRIPT,
        text=True,
        capture_output=True,
        timeout=300,
    )
    out = (proc.stdout or "").strip()
    for line in out.splitlines():
        log(f"remote: {line}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-5:]
        log(f"云端合并失败 rc={proc.returncode} :: " + " | ".join(err))
        return 1
    if "MERGED_EVENTS=0" in out:
        log("无新增事件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
