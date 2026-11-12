#!/usr/bin/env python3
"""scripts/rea_recall_gate.py — SPEC-33-D T-D11：分析前 recall 去重。

问题：同一工程同一 scope 被反复 submit，既烧 token 又重复落快照。
做法：用「工程真实路径 + git HEAD + scope」生成 12 位指纹，作为 recall 查询词与
认知记录标记；命中同指纹且未过期时直接复用 snapshot_id，不再分析。

用法：
  python3 scripts/rea_recall_gate.py --target 3.1-FRONTEND --scope summary
  → 输出 {fingerprint, recall_query, record_marker}
  然后以 recall_query 调 recall；按 decide() 的结论决定复用还是重新分析。

记录约定（SKILL §5）：poll 成功后写认知时，content 末尾必须追加 record_marker，
下次才能命中。指纹变化（HEAD 前进 / scope 改变 / 路径变化）即视为需要重新分析。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

FP_TAG = "rea-fp:"
DEFAULT_MAX_AGE_DAYS = 7


def fingerprint(target: str | Path, scope: str = "summary", git_head: str = "") -> str:
    """返回 12 位稳定指纹；输入变化即变化。"""
    key = f"{os.path.realpath(str(target))}|{git_head}|{scope}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def resolve_git_head(target: str | Path, timeout: int = 5) -> str:
    """取目标所在仓库的短 HEAD；非 git 目录返回 nogit（不抛错）。"""
    path = Path(target).resolve()
    cwd = path if path.is_dir() else path.parent
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "nogit"
    head = (completed.stdout or "").strip()
    return head if completed.returncode == 0 and head else "nogit"


def record_marker(fp: str) -> str:
    return f"{FP_TAG}{fp}"


def build_query(target: str | Path, scope: str, fp: str) -> str:
    name = Path(str(target)).name or str(target)
    return f"REA 架构事实 {name} scope={scope} {record_marker(fp)}"


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def decide(
    hits: Iterable[Dict[str, Any]],
    fp: str,
    *,
    now: Optional[datetime] = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> Dict[str, Any]:
    """命中同指纹且未过期 → reuse；否则 reanalyze。"""
    now = now or datetime.now(timezone.utc)
    marker = record_marker(fp)
    matched_seen = False
    for hit in hits or []:
        content = str((hit or {}).get("content") or "")
        if marker not in content:
            continue
        matched_seen = True
        created = _parse_ts(
            (hit or {}).get("promoted_at")
            or (hit or {}).get("created_at")
            or (hit or {}).get("created")
        )
        if created is None:
            continue
        age = now - created
        if age.total_seconds() > max_age_days * 86400:
            return {
                "decision": "reanalyze",
                "reason": f"命中但已过期（{age.days} 天 > {max_age_days} 天）",
                "snapshot_id": None,
            }
        snapshot_id = (hit or {}).get("snapshot_id") or ((hit or {}).get("metadata") or {}).get(
            "snapshot_id"
        )
        return {
            "decision": "reuse",
            "reason": f"命中同指纹（{age.total_seconds() / 3600:.1f}h 前），复用快照",
            "snapshot_id": snapshot_id,
        }
    if matched_seen:
        return {
            "decision": "reanalyze",
            "reason": "命中但无时间戳，无法判断时效",
            "snapshot_id": None,
        }
    return {
        "decision": "reanalyze",
        "reason": "无同指纹命中（指纹不同或从未分析）",
        "snapshot_id": None,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="分析前 recall 去重（SPEC-33-D T-D11）")
    parser.add_argument("--target", required=True, help="工程根或文件路径")
    parser.add_argument("--scope", default="summary", choices=["summary", "architecture", "full"])
    parser.add_argument("--git-head", default="", help="显式指定 HEAD（默认自动探测）")
    args = parser.parse_args(argv)

    head = args.git_head or resolve_git_head(args.target)
    fp = fingerprint(args.target, args.scope, head)
    print(
        json.dumps(
            {
                "target": args.target,
                "scope": args.scope,
                "git_head": head,
                "fingerprint": fp,
                "recall_query": build_query(args.target, args.scope, fp),
                "record_marker": record_marker(fp),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
