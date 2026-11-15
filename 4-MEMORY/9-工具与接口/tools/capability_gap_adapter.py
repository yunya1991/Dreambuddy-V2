#!/usr/bin/env python3
"""能力缺口薄适配层 — 复用 `48-涌现架构/registry/capability_gaps.py`。

职责只有两条（SPEC §3.5 / G8）：
1. **按问题类别聚合**：同一 (问题类别, 失败模式, 缺失工具) 只保留 1 条，复现次数累加。
2. **复现计数**：≥2 次标 `escalate=True`，交上游升级为工具增强任务。

硬约束：**禁止新建平行存储**。所有读写都落在 registry 自己的
`capability_gaps.jsonl`（由 `capability_gaps.py` 的 new_gap/append_gap/load_gaps 负责），
本层不定义字段外的第二份清单。

用法:
    python tools/capability_gap_adapter.py report \
        --category "大数据量向量去重" --failure-mode "OOM" \
        --missing-tool "分块相似度矩阵" --expected "支持 10 万级分块"
    python tools/capability_gap_adapter.py list
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_FILE = _REPO_ROOT / "48-涌现架构" / "registry" / "capability_gaps.py"


def _load_registry():
    """按文件路径加载 registry 模块（目录名以数字开头，不能直接 import）。"""
    spec = importlib.util.spec_from_file_location("capability_gaps_registry", _REGISTRY_FILE)
    if spec is None or spec.loader is None:  # pragma: no cover - 文件缺失即配置错误
        raise ImportError(f"cannot load {_REGISTRY_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _key(evidence: dict) -> tuple:
    return (
        str(evidence.get("problem_category") or ""),
        str(evidence.get("failure_mode") or ""),
        str(evidence.get("missing_tool") or ""),
    )


def _bump(gap_id: str, path: Path, registry) -> bool:
    """在 registry 自己的 JSONL 内累加复现次数（重写整文件，与其 update_status 同款）。"""
    gaps = registry.load_gaps(path)
    hit = False
    for gap in gaps:
        if gap.get("gap_id") != gap_id:
            continue
        evidence = gap.setdefault("evidence", {})
        evidence["occurrences"] = int(evidence.get("occurrences") or 1) + 1
        evidence["last_seen"] = registry._now_iso()
        hit = True
    if not hit:
        return False
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(g, ensure_ascii=False) + "\n" for g in gaps), encoding="utf-8"
    )
    tmp.replace(path)
    return True


def report_gap(
    problem_category: str,
    failure_mode: str,
    missing_tool: str,
    expected_enhancement: str = "",
    evidence: dict[str, Any] | None = None,
    created_by: str = "agent",
    path: Path | None = None,
    dry_run: bool = True,
) -> dict:
    """落一张能力缺口；同类已存在则只累加复现次数，不新增记录。"""
    registry = _load_registry()
    target = Path(path) if path else registry.DEFAULT_GAPS_PATH
    evidence = dict(evidence or {})
    evidence.update(
        {
            "problem_category": problem_category,
            "failure_mode": failure_mode,
            "missing_tool": missing_tool,
            "expected_enhancement": expected_enhancement,
            "occurrences": int(evidence.get("occurrences") or 1),
        }
    )

    matches = [
        g
        for g in registry.load_gaps(target)
        if g.get("status") not in registry.TERMINAL_STATUSES
        and _key(g.get("evidence") or {}) == _key(evidence)
    ]
    if matches:
        existing = matches[0]
        occurrences = int((existing.get("evidence") or {}).get("occurrences") or 1) + 1
        result = {
            "ok": True,
            "action": "aggregated",
            "gap_id": existing["gap_id"],
            "occurrences": occurrences,
            "escalate": occurrences >= 2,
            "dry_run": dry_run,
        }
        if not dry_run:
            result["ok"] = _bump(existing["gap_id"], target, registry)
        return result

    gap = registry.new_gap(
        gap_type=problem_category,
        evidence=evidence,
        expected_value=expected_enhancement,
        target_domain_hint=missing_tool,
        created_by=created_by,
    )
    result = {
        "ok": True,
        "action": "created",
        "gap_id": gap["gap_id"],
        "occurrences": 1,
        "escalate": False,
        "dry_run": dry_run,
    }
    if not dry_run:
        result["ok"] = registry.append_gap(gap, target)
    return result


def list_aggregated(path: Path | None = None) -> dict:
    """按 (类别, 失败模式, 缺失工具) 聚合，输出复现次数与升级标记。"""
    registry = _load_registry()
    target = Path(path) if path else registry.DEFAULT_GAPS_PATH
    groups: dict[tuple, dict] = {}
    for gap in registry.load_gaps(target):
        if gap.get("status") in registry.TERMINAL_STATUSES:
            continue
        evidence = gap.get("evidence") or {}
        if not evidence.get("problem_category"):
            continue  # 非本适配层写入的缺口（registry 其他用途）不参与聚合
        key = _key(evidence)
        item = groups.setdefault(
            key,
            {
                "problem_category": key[0],
                "failure_mode": key[1],
                "missing_tool": key[2],
                "occurrences": 0,
                "gap_ids": [],
                "status": gap.get("status"),
            },
        )
        item["occurrences"] += int(evidence.get("occurrences") or 1)
        item["gap_ids"].append(gap.get("gap_id"))
    items = sorted(groups.values(), key=lambda x: -x["occurrences"])
    for item in items:
        item["escalate"] = item["occurrences"] >= 2
    return {
        "ok": True,
        "count": len(items),
        "escalated": sum(1 for i in items if i["escalate"]),
        "items": items,
    }


def _cli(args) -> int:
    if args.command == "report":
        out = report_gap(
            problem_category=args.category,
            failure_mode=args.failure_mode,
            missing_tool=args.missing_tool,
            expected_enhancement=args.expected,
            path=Path(args.path) if args.path else None,
            dry_run=not args.apply,
        )
    elif args.command == "list":
        out = list_aggregated(Path(args.path) if args.path else None)
    else:
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="能力缺口适配层（复用 registry，不建平行存储）")
    sub = parser.add_subparsers(dest="command")
    p_rep = sub.add_parser("report", help="登记一张缺口（同类自动聚合，默认 dry-run）")
    p_rep.add_argument("--category", required=True, help="问题类别")
    p_rep.add_argument("--failure-mode", required=True, help="失败模式")
    p_rep.add_argument("--missing-tool", required=True, help="缺失工具")
    p_rep.add_argument("--expected", default="", help="期望增强")
    p_rep.add_argument("--path", default="", help="覆盖 capability_gaps.jsonl 路径")
    p_rep.add_argument("--apply", action="store_true", help="实际写入（缺省仅 dry-run）")
    p_ls = sub.add_parser("list", help="按类别聚合输出")
    p_ls.add_argument("--path", default="")

    raise SystemExit(_cli(parser.parse_args()))
