#!/usr/bin/env python3
"""scripts/migrate_replay_pool_layers.py — SPEC-33-E T-E1：replay_pool 三类分层迁移。

分类规则（全量实测 15,732 棵 internal 树，100% 覆盖，无 unknown/parse_error）：
  - process_log      task_type == "l1_loop" 或节点 analyzer ∈ 流程集
                     {acceptance_gate, code_commit, doc_sync, cognitive_record}
  - project_analysis 其余（实测全部 task_type == "analyze"）
  - external_case    external/ 目录不动

用法：
  python3 scripts/migrate_replay_pool_layers.py            # dry-run（默认，不移动任何文件）
  python3 scripts/migrate_replay_pool_layers.py --apply    # 实际迁移（先跑 dry-run 审清单）

校验（迁移前后强制）：
  1. 计数守恒：moved + kept == 迁移前 internal 总数
  2. eval_ready 不降级：迁移后 internal 剩余 >= MIN_TREES_FOR_EVAL
  3. external/ 零改动
  4. 抽样回读：迁移后抽样 tree 可被 DiscoveryTree.from_dict 解析
回滚：目录可回搬（_process/*.json → internal/），脚本提供 --rollback。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from core.reflection.replay_simulator import (  # noqa: E402
    MIN_TREES_FOR_EVAL,
    PROCESS_ANALYZERS,
    PROCESS_TASK_TYPES,
    DiscoveryTree,
)

POOL_DIR = _REA_ROOT / "reflection_data" / "replay_pool"
INTERNAL = POOL_DIR / "internal"
EXTERNAL = POOL_DIR / "external"
PROCESS = POOL_DIR / "_process"
MANIFEST = POOL_DIR / "_migration_manifest.json"


def _paths(pool_dir: str | Path | None = None) -> tuple[Path, Path, Path, Path, Path]:
    pool = Path(pool_dir) if pool_dir else POOL_DIR
    return (
        pool,
        pool / "internal",
        pool / "external",
        pool / "_process",
        pool / "_migration_manifest.json",
    )


def classify(path: Path) -> str:
    """返回 process_log / project_analysis / parse_error。"""
    try:
        with open(path, encoding="utf-8") as f:
            tree = json.load(f)
    except (json.JSONDecodeError, OSError):
        return "parse_error"
    task = tree.get("task") or {}
    analyzers = {(n.get("action") or {}).get("analyzer") for n in (tree.get("nodes") or [])}
    if task.get("task_type") in PROCESS_TASK_TYPES or (analyzers & PROCESS_ANALYZERS):
        return "process_log"
    return "project_analysis"


def scan(pool_dir: str | Path | None = None) -> tuple[list[str], list[str], Counter]:
    """全量扫描 internal/，返回 (process_log 文件名, project_analysis 文件名, 计数器)。"""
    _, internal, *_ = _paths(pool_dir)
    process: list[str] = []
    project: list[str] = []
    stats: Counter = Counter()
    for name in sorted(os.listdir(internal)):
        if not name.endswith(".json"):
            continue
        bucket = classify(internal / name)
        stats[bucket] += 1
        if bucket == "process_log":
            process.append(name)
        elif bucket == "project_analysis":
            project.append(name)
    return process, project, stats


def scan_external(pool_dir: str | Path | None = None) -> tuple[int, int]:
    """返回 (external 总数, source_label 缺失数)；缺失不计入案例数（G-E4）。"""
    _, _, external, _, _ = _paths(pool_dir)
    total = 0
    missing = 0
    for name in sorted(os.listdir(external)):
        if not name.endswith(".json"):
            continue
        total += 1
        try:
            with open(external / name, encoding="utf-8") as handle:
                tree = json.load(handle)
        except (json.JSONDecodeError, OSError):
            missing += 1
            continue
        label = tree.get("source_label") or (tree.get("task") or {}).get("source_label")
        if not label:
            missing += 1
    return total, missing


def dry_run(pool_dir: str | Path | None = None) -> int:
    *_, manifest_path = _paths(pool_dir)
    process, project, stats = scan(pool_dir)
    kept = len(project)
    external_total, external_missing = scan_external(pool_dir)
    print("=== T-E1 dry-run：replay_pool 三类分层 ===")
    print(f"internal 总数:      {len(process) + len(project)}")
    print(f"process_log → _process/: {len(process)}")
    print(f"project_analysis 保留:   {len(project)}")
    print(
        f"external/ 不动:          {external_total}（source_label 缺失 {external_missing}，缺失不计入案例数）"
    )
    if stats.get("parse_error"):
        print(f"!! parse_error: {stats['parse_error']}（需人工排查，不迁移）")

    # 校验 1：计数守恒
    assert len(process) + len(project) + stats.get("parse_error", 0) == sum(stats.values())

    # 校验 2：eval_ready 不降级
    print(f"\n迁移后 internal 剩余 {kept} 棵（MIN_TREES_FOR_EVAL={MIN_TREES_FOR_EVAL}）")
    if kept < MIN_TREES_FOR_EVAL:
        print("!! 迁移将导致 eval_ready 降级，禁止 apply")
        return 1
    print("eval_ready 不降级 ✅")

    # 校验 3：写迁移清单（供 apply 使用 + 人工审查）
    manifest_path.write_text(
        json.dumps(
            {
                "process_log": process,
                "project_analysis_kept": project,
                "stats": dict(stats),
                "external_case": {
                    "total": external_total,
                    "missing_source_label": external_missing,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n迁移清单已写入: {manifest_path}")
    print(f"抽样 process_log: {process[:3]}")
    print(f"抽样 project_analysis: {project[:3]}")
    print("\n确认无误后执行: python3 scripts/migrate_replay_pool_layers.py --apply")
    return 0


def apply(pool_dir: str | Path | None = None) -> int:
    _, internal, _, process_dir, manifest_path = _paths(pool_dir)
    if not manifest_path.exists():
        print("!! 缺少迁移清单，请先运行 dry-run")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    process: list[str] = manifest["process_log"]
    before = len([f for f in os.listdir(internal) if f.endswith(".json")])

    process_dir.mkdir(exist_ok=True)
    moved = 0
    for name in process:
        src = internal / name
        if src.exists():
            shutil.move(str(src), str(process_dir / name))
            moved += 1
    after = len([f for f in os.listdir(internal) if f.endswith(".json")])

    # 校验：计数守恒
    print(f"移动 {moved}/{len(process)}；internal {before} → {after}")
    assert moved + after == before, "计数不守恒，迁移异常"

    # 抽样回读：迁移后文件仍可解析
    sample = random.sample(process, min(5, len(process)))
    for name in sample:
        with open(process_dir / name, encoding="utf-8") as f:
            DiscoveryTree.from_dict(json.load(f))
    print(f"抽样回读 {len(sample)} 棵 ✅")

    # eval_ready 校验
    print(
        f"internal 剩余 {after} 棵（阈值 {MIN_TREES_FOR_EVAL}），eval_ready {'✅' if after >= MIN_TREES_FOR_EVAL else '!! 降级'}"
    )
    print(
        "注意：ReplayPool.load/list_trees 默认不扫 _process/，process_log 自动退出做梦与方法论语料。"
    )
    print("回滚：python3 scripts/migrate_replay_pool_layers.py --rollback")
    return 0


def rollback(pool_dir: str | Path | None = None) -> int:
    _, internal, _, process_dir, _ = _paths(pool_dir)
    if not process_dir.exists():
        print("_process/ 不存在，无需回滚")
        return 0
    moved = 0
    for name in os.listdir(process_dir):
        if name.endswith(".json"):
            shutil.move(str(process_dir / name), str(internal / name))
            moved += 1
    process_dir.rmdir()
    print(f"回滚完成：{moved} 棵已搬回 internal/")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="replay_pool 三类分层迁移（SPEC-33-E T-E1）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="按清单实际迁移")
    group.add_argument("--rollback", action="store_true", help="_process/ 搬回 internal/")
    args = parser.parse_args()

    if args.apply:
        sys.exit(apply())
    if args.rollback:
        sys.exit(rollback())
    sys.exit(dry_run())
