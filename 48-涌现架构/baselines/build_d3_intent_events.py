#!/usr/bin/env python3
"""生成 D3 意图事件代理基线（P0-2 前置产物）。

从 `.cognitive/sessions/*/session.json` + `action_chain.jsonl` 提取每会话一行事件：
  - session_id / ts / end_ts / status / action_count
  - intent_proxy = session.task_type（粗粒度代理）
  - intent_label / intent_stable / intent_trajectory / intent_signals / intent_label_confidence
    （P0-2 直接意图标签：结构化启发式，确定性可复现，无自由文本）
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


def _intent_trajectory(final_task_type: str | None, transitions: list[dict]) -> list[str]:
    """还原意图演化轨迹：初始 task_type → 每次跃迁后的 to。

    无跃迁时返回 [final_task_type]。左闭右开地保留每个状态；重复相邻状态折叠。
    """
    states: list[str] = []
    if transitions:
        first = transitions[0].get("from")
        if first:
            states.append(first)
    for t in transitions:
        to = t.get("to")
        if to and (not states or states[-1] != to):
            states.append(to)
    if not states:
        states = [final_task_type] if final_task_type else []
    elif final_task_type and states[-1] != final_task_type:
        states.append(final_task_type)
    return states


def _intent_signals(session: dict, action_files: set[str]) -> dict:
    """结构化意图信号（不含自由文本）：技能数、文件域、跃迁数、稳定性。"""
    files = session.get("files_touched") or []
    domains = sorted({str(f).split("/", 1)[0] for f in files if f and isinstance(f, str)})
    if not domains:
        domains = sorted({str(f).split("/", 1)[0] for f in action_files if f})
    return {
        "recalled_skill_count": len(
            {
                p.get("skill_id")
                for p in session.get("recalled_processes", [])
                if isinstance(p, dict) and p.get("skill_id")
            }
        ),
        "file_domains": domains,
        "transition_count": len(session.get("task_type_history") or []),
    }


def _intent_label(final_task_type: str | None, trajectory: list[str], signals: dict) -> dict:
    """确定性直接意图标签：<task_type>:<stable|drifted-N>[:primary_domain]。

    - stable：无跃迁；drifted-N：N 次跃迁。
    - primary_domain：信号中出现的首个文件域（结构化，非自由文本）。
    - confidence：1.0 稳定，随跃迁数衰减；无 task_type 时 0.0。
    """
    n = signals.get("transition_count", 0)
    stable = n == 0
    domain = signals.get("file_domains", [None])[0] if signals.get("file_domains") else None
    parts = [final_task_type or "unknown", "stable" if stable else f"drifted-{n}"]
    if domain:
        parts.append(domain)
    confidence = 1.0 if stable else max(0.4, 1.0 - 0.15 * n)
    if not final_task_type:
        confidence = 0.0
    return {"label": ":".join(parts), "stable": stable, "confidence": round(confidence, 3)}


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
        trajectory = _intent_trajectory(s.get("task_type"), transitions)
        signals = _intent_signals(s, action_files)
        label = _intent_label(s.get("task_type"), trajectory, signals)
        events.append(
            {
                "session_id": s.get("id", sdir.name),
                "ts": s.get("start_time"),
                "end_ts": s.get("end_time"),
                "status": s.get("status"),
                "action_count": s.get("action_count", 0),
                "intent_proxy": s.get("task_type"),
                # ---- P0-2 直接意图标签（结构化、确定性、无自由文本）----
                "intent_label": label["label"],
                "intent_stable": label["stable"],
                "intent_trajectory": trajectory,
                "intent_signals": signals,
                "intent_label_confidence": label["confidence"],
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
        "intent_label_count": sum(1 for e in events if e.get("intent_label")),
        "intent_stable_count": sum(1 for e in events if e.get("intent_stable")),
        "date_range": [
            datetime.fromtimestamp(min(tss), tz=timezone.utc).isoformat() if tss else None,
            datetime.fromtimestamp(max(tss), tz=timezone.utc).isoformat() if tss else None,
        ],
        "split": {k: split[k] for k in ("train_ratio", "total", "train_count", "test_count")},
        "limitations": [
            "intent_label 为结构化启发式标签（task_type + 稳定性 + 文件域），非用户自由文本意图",
            "intent_proxy = session.task_type；intent_label 在其基础上叠加轨迹/信号，确定性可复现",
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
