# -*- coding: utf-8 -*-
"""裁决事件消费者（P2.5 运行时接线，DSH 事件循环侧）。

链路：前端写入 L0 task-board `verdict.updated` 事件
  → 本消费者扫描增量事件（按 task 的 seq 游标）
  → verdict_resume_bridge 唤醒 paused(waiting_verdict) Ticket
  → paused → live，回写 L0。

部署：launchd `WatchPaths` 监视 .data/task-board 目录，文件变化触发 `--once`，
不做忙轮询。

硬约束：
  HC-1 FAIL-OPEN：坏行/坏文件/IO 异常跳过，不中断整轮
  HC-2 幂等：每个 task 只处理 seq 大于游标的事件
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, Optional

from .ticket_store import JsonlTicketStore
from .verdict_resume_bridge import VERDICT_EVENT_TYPE, apply_verdict_event

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
DEFAULT_EVENTS_DIR = os.environ.get("TASK_BOARD_DIR") or os.path.join(
    _PROJECT_ROOT, ".data", "task-board"
)
DEFAULT_STATE_PATH = os.environ.get("VERDICT_CONSUMER_STATE") or os.path.join(
    _PROJECT_ROOT, ".data", "verdict-consumer", "state.json"
)


def load_state(path: str) -> Dict[str, int]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): int(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_state(path: str, state: Dict[str, int]) -> bool:
    """原子写游标；失败不影响本轮已完成的唤醒。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return True
    except Exception:
        return False


def consume_once(
    store: Any,
    events_dir: str = DEFAULT_EVENTS_DIR,
    state_path: str = DEFAULT_STATE_PATH,
    now: Optional[float] = None,
) -> Dict[str, int]:
    """扫描一轮增量事件并唤醒 Ticket；返回计数（FAIL-OPEN）。"""
    counts = {"scanned": 0, "verdict_events": 0, "resumed": 0, "tasks": 0}
    if store is None or not events_dir:
        return counts

    state = load_state(state_path)
    try:
        files = sorted(glob.glob(os.path.join(events_dir, "*.jsonl")))
    except Exception:
        return counts

    for path in files:
        task_id = os.path.splitext(os.path.basename(path))[0]
        last = int(state.get(task_id, -1))
        max_seq = last
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue

        for line in lines:
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            counts["scanned"] += 1
            seq = event.get("seq")
            if not isinstance(seq, int):
                continue
            max_seq = max(max_seq, seq)
            if event.get("type") != VERDICT_EVENT_TYPE or seq <= last:
                continue
            counts["verdict_events"] += 1
            counts["resumed"] += len(apply_verdict_event(store, event, now=now))

        if max_seq > last:
            state[task_id] = max_seq
            counts["tasks"] += 1

    save_state(state_path, state)
    return counts


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="DreamBuddy 裁决事件消费者")
    parser.add_argument("--once", action="store_true", help="只跑一轮（launchd 用）")
    parser.add_argument("--interval", type=float, default=5.0, help="常驻轮询间隔秒")
    parser.add_argument("--events-dir", default=DEFAULT_EVENTS_DIR)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--store-root", default=_PROJECT_ROOT)
    args = parser.parse_args(argv)

    store = JsonlTicketStore(args.store_root)
    while True:
        counts = consume_once(store, args.events_dir, args.state)
        print(json.dumps(counts, ensure_ascii=False))
        if args.once:
            return 0
        time.sleep(max(0.5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
