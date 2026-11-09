#!/usr/bin/env python3
"""生成 D3 意图事件代理基线（P0-2 前置产物）。

从 `.cognitive/sessions/*/session.json` + `action_chain.jsonl` 提取每会话一行事件：
  - session_id / ts / end_ts / status / action_count
  - intent_proxy = session.task_type（**不是用户意图标签**）
  - recalled_memory_ids / recalled_skills / files_touched
  - task_type_transitions / correction_count
  - action_type 分布 + 涉及文件列表（**不复制 detail 用户原文**）

同时产出：
  - intent_summary.json : session 数、task_type 分布、日期范围、局限
  - split_manifest.json : 按时间 train_ratio 时序切分的 train/test 清单
  - manifest.json       : git commit、sha256、字节数

隐私约束（SPEC v0.4 §6.3）：不输出 action detail / 建议原文等自由文本；
产物中的 session id 与文件路径属内部 runtime 数据，raw JSONL 不入库提交。
FAIL-OPEN：单个 session 解析失败跳过并计数。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SESSIONS = REPO_ROOT / ".cognitive" / "sessions"
DEFAULT_OUT = Path(__file__).resolve().parent / "artifacts" / "d3_intent_events"


def load_events(sessions_dir: Path) -> tuple[list[dict], list[dict]]:
    """加载全部 session 事件。返回 (events, errors)。"""
    events: list[dict] = []
    errors: list[dict] = []
    if not sessions_dir.is_dir():
        return events, errors
    for sdir in sorted(sessions_dir.iterdir()):
        sjson = sdir / "session.json"
        if not sdir.is_dir() or not sjson.exists() or sjson.stat().st_size == 0:
            continue
        try:
            s = json.loads(sjson.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append({"session_dir": sdir.name, "error": f"{type(exc).__name__}: {exc}"})
            continue

        # recalled_skills：从 recalled_processes 提取 skill_id（去重排序）
        skills = sorted(
            {
                p.get("skill_id")
                for p in s.get("recalled_processes", [])
                if isinstance(p, dict) and p.get("skill_id")
            }
        )

        # action_chain：只保留 action_type 分布与文件列表，不复制 detail 原文
        action_types: dict[str, int] = {}
        action_files: set[str] = set()
        chain = sdir / "action_chain.jsonl"
        if chain.exists():
            try:
                for line in chain.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    a = json.loads(line)
                    at = a.get("action_type")
                    if at:
                        action_types[at] = action_types.get(at, 0) + 1
                    if a.get("file"):
                        action_files.add(a["file"])
            except (json.JSONDecodeError, OSError):
                errors.append({"session_dir": sdir.name, "error": "action_chain parse failed"})

        transitions = s.get("task_type_history", []) or []
        events.append(
            {
                "session_id": s.get("id", sdir.name),
                "ts": s.get("start_time"),
                "end_ts": s.get("end_time"),
                "status": s.get("status"),
                "action_count": s.get("action_count", 0),
                "intent_proxy": s.get("task_type"),
                "recalled_memory_ids": sorted(s.get("recalled_memory_ids", []) or []),
                "recalled_skills": skills,
                "files_touched": sorted(s.get("files_touched", []) or []),
                "task_type_transitions": [
                    {"from": t.get("from"), "to": t.get("to"), "timestamp": t.get("timestamp")}
                    for t in transitions
                    if isinstance(t, dict)
                ],
                "correction_count": len(transitions),
                "action_type_distribution": dict(sorted(action_types.items())),
                "action_files": sorted(action_files),
            }
        )
    events.sort(key=lambda e: (e["ts"] is None, e["ts"] or 0, e["session_id"]))
    return events, errors


def split_events(events: list[dict], train_ratio: float) -> dict:
    """按时间顺序切分 train/test（时序 holdout，不打乱）。"""
    n = len(events)
    cut = int(n * train_ratio)
    train = events[:cut]
    test = events[cut:]
    return {
        "train_ratio": train_ratio,
        "total": n,
        "train_count": len(train),
        "test_count": len(test),
        "train_sessions": [e["session_id"] for e in train],
        "test_sessions": [e["session_id"] for e in test],
        "train_ts_range": _ts_range(train),
        "test_ts_range": _ts_range(test),
    }


def _ts_range(events: list[dict]) -> list[float | None]:
    tss = [e["ts"] for e in events if e["ts"] is not None]
    return [min(tss), max(tss)] if tss else [None, None]


def build_summary(events: list[dict], errors: list[dict], split: dict) -> dict:
    tt_dist: dict[str, int] = {}
    for e in events:
        k = e["intent_proxy"] or "unknown"
        tt_dist[k] = tt_dist.get(k, 0) + 1
    tss = [e["ts"] for e in events if e["ts"] is not None]
    return {
        "session_count": len(events),
        "parse_error_count": len(errors),
        "parse_errors": errors[:50],
        "task_type_distribution": dict(sorted(tt_dist.items(), key=lambda x: -x[1])),
        "date_range": [
            datetime.fromtimestamp(min(tss), tz=timezone.utc).isoformat() if tss else None,
            datetime.fromtimestamp(max(tss), tz=timezone.utc).isoformat() if tss else None,
        ],
        "split": {k: split[k] for k in ("train_ratio", "total", "train_count", "test_count")},
        "limitations": [
            "intent_proxy 是 session.task_type 代理标签，不是用户直接意图标签",
            "P0-2 关闭（直接意图标签补采）前不得申报「意图涌现」，D3-A 仅限 task_type 预测",
            "actions 只保留 action_type/文件列表，未复制用户自由文本",
        ],
    }


def _sha256_jsonl(events: list[dict]) -> tuple[str, bytes]:
    blob = "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in events).encode(
        "utf-8"
    )
    return hashlib.sha256(blob).hexdigest(), blob


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def run(sessions_dir: Path, out_dir: Path, train_ratio: float) -> dict:
    events, errors = load_events(sessions_dir)
    split = split_events(events, train_ratio)
    summary = build_summary(events, errors, split)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()

    sha, blob = _sha256_jsonl(events)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "intent_events.jsonl").write_bytes(blob)
    (out_dir / "intent_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "split_manifest.json").write_text(
        json.dumps(split, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    manifest = {
        "generated_at": summary["generated_at"],
        "git_commit": _git_commit(REPO_ROOT),
        "artifacts": {
            "intent_events.jsonl": {"sha256": sha, "bytes": len(blob)},
        },
        "train_ratio": train_ratio,
        "privacy": "raw JSONL 含内部 session id/文件路径，不入库提交；仅 summary/split/manifest 可入库",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    summary["sha256"] = sha
    summary["bytes"] = len(blob)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 D3 意图事件代理基线")
    ap.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--train-ratio", type=float, default=0.75)
    args = ap.parse_args(argv)
    summary = run(Path(args.sessions_dir), Path(args.out), args.train_ratio)
    print(
        f"[build_d3] sessions={summary['session_count']} "
        f"train={summary['split']['train_count']} test={summary['split']['test_count']} "
        f"errors={summary['parse_error_count']} sha256={summary['sha256'][:12]}..."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
