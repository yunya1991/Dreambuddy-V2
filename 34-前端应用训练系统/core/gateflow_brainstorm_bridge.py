# -*- coding: utf-8 -*-
"""P0-D3D Phase 2: GateFlow 驳回事件 → BrainstormTicket。

GateFlow 事件由前端/服务端导出为 append-only JSONL：
  {"run_id","flow_id","task_id","trace_id","type","node_id","at","detail"}
本模块只消费 `node.rejected`，生成立案票据；`node.rewound` 仅记录，不重复立案。

硬约束：
  - 只读 GateFlow 事件，不改 GateRun；
  - 幂等：同 (run_id, node_id, at) 只立一次；
  - FAIL-OPEN：坏行/坏文件跳过，不中断整轮。
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

from core.brainstorm_ticket import create_ticket
from core.tier_policy import TierInput

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# 与前端 `3.1-FRONTEND/.data/gateflow` 对齐；可用 GATEFLOW_EVENTS_DIR 覆盖。
_DEFAULT_GATEFLOW_DIR = os.environ.get("GATEFLOW_EVENTS_DIR") or os.path.join(
    _PROJECT_ROOT, "3.1-FRONTEND", ".data", "gateflow"
)
DEFAULT_EVENTS_DIR = _DEFAULT_GATEFLOW_DIR
DEFAULT_STATE_PATH = os.environ.get("GATEFLOW_BRAINSTORM_STATE") or os.path.join(
    _DEFAULT_GATEFLOW_DIR, "brainstorm-state.json"
)
DEFAULT_TICKETS_PATH = os.environ.get("GATEFLOW_BRAINSTORM_TICKETS") or os.path.join(
    _DEFAULT_GATEFLOW_DIR, "brainstorm_tickets.jsonl"
)


def _load_state(path: str) -> Dict[str, int]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {str(k): int(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_state(path: str, state: Dict[str, int]) -> bool:
    try:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return True
    except Exception:
        return False


def _existing_gap_keys(path: str) -> set:
    keys = set()
    if not path or not os.path.exists(path):
        return keys
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict) and item.get("gap_key"):
                    keys.add(str(item["gap_key"]))
    except Exception:
        return keys
    return keys


def _append_record(path: str, record: Any) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _append_ticket(path: str, ticket: Any) -> bool:
    return _append_record(path, ticket.to_dict())


def export_run_events(run: Any, path: str) -> int:
    """把 GateRun（含 events）导出为 append-only JSONL；供服务端路由调用。"""
    if not isinstance(run, dict) or not path:
        return 0
    run_id = str(run.get("run_id") or "")
    events = run.get("events")
    if not run_id or not isinstance(events, (list, tuple)):
        return 0
    count = 0
    for event in events:
        if not isinstance(event, dict) or not event.get("type"):
            continue
        record = {
            "run_id": run_id,
            "flow_id": str(run.get("flow_id") or ""),
            "task_id": str(run.get("task_id") or ""),
            "trace_id": str(run.get("trace_id") or ""),
            "type": event.get("type"),
            "node_id": event.get("node_id"),
            "at": event.get("at"),
            "detail": event.get("detail") if isinstance(event.get("detail"), dict) else {},
        }
        if _append_record(path, record):
            count += 1
    return count


def _gap_key(event: Dict[str, Any]) -> str:
    return "%s:%s:%s" % (
        str(event.get("run_id") or ""),
        str(event.get("node_id") or ""),
        str(event.get("at") or ""),
    )


def _tier_input(detail: Dict[str, Any]) -> TierInput:
    high_risk = bool(detail.get("high_risk"))
    risk_level = str(detail.get("risk_level") or ("critical" if high_risk else "low"))
    uncertainty = float(detail.get("uncertainty_score") or 0.5)
    if str(detail.get("rewind_to") or "") == "none":
        uncertainty = max(uncertainty, 0.7)  # 无回退目标 → 需要方案讨论
    return TierInput(
        risk_level=risk_level,
        reversible=bool(detail.get("reversible", True)),
        blast_radius=str(detail.get("blast_radius") or "single_task"),
        evidence_gap_count=int(detail.get("evidence_gap_count") or 1),
        option_count=int(detail.get("option_count") or 1),
        uncertainty_score=uncertainty,
    )


def consume_once(
    events_dir: str = DEFAULT_EVENTS_DIR,
    state_path: str = DEFAULT_STATE_PATH,
    tickets_path: str = DEFAULT_TICKETS_PATH,
    now: Optional[float] = None,
) -> Dict[str, int]:
    counts = {
        "scanned": 0,
        "rejected_events": 0,
        "tickets_created": 0,
        "duplicates": 0,
        "bad_lines": 0,
    }
    state = _load_state(state_path)
    existing = _existing_gap_keys(tickets_path)
    try:
        files = sorted(glob.glob(os.path.join(events_dir, "*.jsonl")))
    except Exception:
        return counts

    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except Exception:
            continue
        last = int(state.get(path, 0))
        if len(lines) < last:
            last = 0  # 文件截断自愈
        processed = 0
        for line in lines[last:]:
            text = line.strip()
            if not text:
                processed += 1
                continue
            try:
                event = json.loads(text)
            except Exception:
                counts["bad_lines"] += 1
                processed += 1
                continue
            if not isinstance(event, dict):
                counts["bad_lines"] += 1
                processed += 1
                continue
            counts["scanned"] += 1
            if event.get("type") != "node.rejected":
                processed += 1
                continue
            counts["rejected_events"] += 1
            key = _gap_key(event)
            if not key or key in existing:
                counts["duplicates"] += 1
                processed += 1
                continue
            detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
            refs = detail.get("evidence_refs")
            if not isinstance(refs, (list, tuple)) or not refs:
                refs = ("gate:%s" % str(event.get("run_id") or ""),)
            ticket = create_ticket(
                ticket_id="BT-%s-%s-%s"
                % (
                    str(event.get("run_id") or "run"),
                    str(event.get("node_id") or "node"),
                    int(float(event.get("at") or now or 0.0)),
                ),
                gap_key=key,
                gap_statement=str(
                    detail.get("reason") or "Gate rejected at %s" % event.get("node_id")
                ),
                source_layer="GateFlow",
                evidence_refs=refs,
                tier_input=_tier_input(detail),
                now=float(event.get("at") or now or 0.0),
            )
            if not _append_ticket(tickets_path, ticket):
                break  # 写失败不前进游标，下轮重试，避免丢事件
            existing.add(key)
            counts["tickets_created"] += 1
            processed += 1
        state[path] = last + processed

    _save_state(state_path, state)
    return counts


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="GateFlow 驳回 → D3D 立案消费者")
    parser.add_argument("--once", action="store_true", help="只跑一轮（launchd 用）")
    parser.add_argument("--interval", type=float, default=5.0, help="常驻轮询间隔秒")
    parser.add_argument("--events-dir", default=DEFAULT_EVENTS_DIR)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--tickets", default=DEFAULT_TICKETS_PATH)
    args = parser.parse_args(argv)

    while True:
        print(
            json.dumps(consume_once(args.events_dir, args.state, args.tickets), ensure_ascii=False)
        )
        if args.once:
            return 0
        time.sleep(max(0.5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
