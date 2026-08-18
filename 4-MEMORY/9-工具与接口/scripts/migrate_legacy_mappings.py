#!/usr/bin/env python3
"""
Task 13: template_mappings.json 迁移脚本（设计节 4.6 LEGACY_TO_NEW 退化映射表）

模式：
  --dry-run （默认）: 只打印迁移前后对比，不写盘
  --apply: 真正写盘覆盖 template_mappings.json，且先备份到同目录 .bak_20260801
  --restore: 从最近 .bak_* 文件恢复（回滚）

注意：--apply 前需要交互式确认或加 --force 标志。
"""

import argparse
import datetime
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

_SCRIPT_DIR = Path(__file__).parent
_META_DIR = _SCRIPT_DIR.parent / ".." / "0-元记忆"
MAPPINGS_FILE = _META_DIR / "template_mappings.json"

LEGACY_TO_NEW: Dict[str, str] = {
    "TDD-001":        "test-driven-development",
    "DEBUG-001":      "systematic-debugging",
    "REFACTOR-001":   "test-driven-development",
    "REVIEW-001":     "requesting-code-review",
    "DESIGN-001":     "brainstorming",
    "TDD-DEBUG-001":  "subagent-driven-development",
}


def load_mappings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        print(f"[ERROR] 文件不存在: {path}")
        sys.exit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[ERROR] 读取 JSON 失败: {e}")
        sys.exit(1)


def save_mappings(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def compute_migrated(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, List[str]], Dict[str, Dict[str, int]]]:
    """
    返回：
      (new_data, parent_change_map, merge_stats)
    parent_change_map: {new_parent: [old_parent_1, old_parent_2, ...]}
    merge_stats: {new_parent: {success, fail, total, merged_groups}}
    """
    mappings: List[Dict[str, Any]] = data.get("mappings", [])

    new_grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    parent_change_map: Dict[str, List[str]] = defaultdict(list)

    for entry in mappings:
        old_parent = entry.get("parent_id", "")
        applied_id = entry.get("applied_id", "")
        new_parent = LEGACY_TO_NEW.get(old_parent, old_parent)

        if new_parent != old_parent:
            if old_parent not in parent_change_map[new_parent]:
                parent_change_map[new_parent].append(old_parent)

        key = (new_parent, applied_id)
        if key not in new_grouped:
            new_grouped[key] = {
                "parent_id": new_parent,
                "applied_id": applied_id,
                "success_count": entry.get("success_count", 0),
                "fail_count": entry.get("fail_count", 0),
                "last_verified": entry.get("last_verified", 0.0),
            }
        else:
            existing = new_grouped[key]
            existing["success_count"] = existing.get("success_count", 0) + entry.get("success_count", 0)
            existing["fail_count"] = existing.get("fail_count", 0) + entry.get("fail_count", 0)
            existing["last_verified"] = max(
                existing.get("last_verified", 0.0),
                entry.get("last_verified", 0.0),
            )

    new_mappings: List[Dict[str, Any]] = []
    merge_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {
        "success": 0, "fail": 0, "total": 0, "merged_groups": 0
    })

    new_parent_to_old_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for (new_parent, applied_id), entry in new_grouped.items():
        sc = entry.get("success_count", 0)
        fc = entry.get("fail_count", 0)
        tc = sc + fc
        entry["total_count"] = tc
        entry["success_rate"] = (sc / tc) if tc > 0 else 0.0
        new_mappings.append(entry)

        merge_stats[new_parent]["success"] += sc
        merge_stats[new_parent]["fail"] += fc
        merge_stats[new_parent]["total"] += tc

        old_parents = parent_change_map.get(new_parent, [])
        for op in old_parents:
            new_parent_to_old_counts[new_parent][op] += 1

    for new_parent, old_count_map in new_parent_to_old_counts.items():
        merge_stats[new_parent]["merged_groups"] = len(old_count_map)

    new_data = {
        "version": data.get("version", 1),
        "updated_at": data.get("updated_at", 0),
        "mappings": new_mappings,
    }

    return new_data, dict(parent_change_map), dict(merge_stats)


def print_comparison(
    original_data: Dict[str, Any],
    new_data: Dict[str, Any],
    change_map: Dict[str, List[str]],
    merge_stats: Dict[str, Dict[str, int]],
) -> None:
    orig_mappings = original_data.get("mappings", [])
    new_mappings = new_data.get("mappings", [])

    print("=" * 70)
    print("📋 LEGACY → NEW 映射表")
    print("=" * 70)
    for old_k, new_k in LEGACY_TO_NEW.items():
        marker = "  "
        for old_list in change_map.values():
            if old_k in old_list:
                marker = "✅"
                break
        print(f"  {marker} {old_k:16s} → {new_k}")
    print()

    print("=" * 70)
    print("📊 迁移前后统计")
    print("=" * 70)
    print(f"  原始 mapping 条目数: {len(orig_mappings)}")
    print(f"  迁移后 mapping 条目数: {len(new_mappings)}")
    if len(orig_mappings) != len(new_mappings):
        print(f"  ⚠️  条目数变化: {len(orig_mappings)} → {len(new_mappings)} "
              f"(相差 {len(new_mappings) - len(orig_mappings)}，因同 parent+applied 合并)")
    print()

    print("=" * 70)
    print("🔀 parent_id 变更汇总")
    print("=" * 70)
    if change_map:
        for new_parent, old_list in sorted(change_map.items()):
            stats = merge_stats.get(new_parent, {})
            print(f"  🎯 {new_parent}")
            print(f"     来源旧 parent_id: {', '.join(old_list)}")
            if stats.get("merged_groups", 0) > 1:
                print(f"     ⚠️  合并 {stats['merged_groups']} 组旧 parent_id")
            print(f"     合并计数 success={stats.get('success', 0)} / "
                  f"fail={stats.get('fail', 0)} / total={stats.get('total', 0)}")
            print()
    else:
        print("  (无 parent_id 需要变更，所有已是新版 skill_id)")
        print()

    orig_parents = sorted({m.get("parent_id", "") for m in orig_mappings})
    new_parents = sorted({m.get("parent_id", "") for m in new_mappings})
    print("=" * 70)
    print("🗂️  parent_id 集合对比")
    print("=" * 70)
    print(f"  旧 parents ({len(orig_parents)}): {orig_parents}")
    print(f"  新 parents ({len(new_parents)}): {new_parents}")
    print()

    changed_applied = []
    for o, n in zip(
        sorted(orig_mappings, key=lambda x: (x.get("parent_id", ""), x.get("applied_id", ""))),
        sorted(new_mappings, key=lambda x: (x.get("parent_id", ""), x.get("applied_id", ""))),
    ):
        if o.get("parent_id") != n.get("parent_id") or \
           o.get("success_count") != n.get("success_count") or \
           o.get("fail_count") != n.get("fail_count"):
            changed_applied.append((o, n))

    if changed_applied:
        print("=" * 70)
        print(f"📝 变更明细（前 {min(10, len(changed_applied))} 条，共 {len(changed_applied)} 条）")
        print("=" * 70)
        for i, (o, n) in enumerate(changed_applied[:10], 1):
            print(f"  [{i}] applied_id={o.get('applied_id', '?')}")
            print(f"       旧: parent={o.get('parent_id')} sc={o.get('success_count', 0)} "
                  f"fc={o.get('fail_count', 0)} tc={o.get('total_count', 0)}")
            print(f"       新: parent={n.get('parent_id')} sc={n.get('success_count', 0)} "
                  f"fc={n.get('fail_count', 0)} tc={n.get('total_count', 0)}")
            print()


def find_latest_backup(mappings_file: Path) -> Path:
    dir_path = mappings_file.parent
    base = mappings_file.name
    backups = sorted(dir_path.glob(f"{base}.bak_*"))
    if not backups:
        print(f"[ERROR] 未找到备份文件 {mappings_file}.bak_*")
        sys.exit(1)
    return backups[-1]


def cmd_dry_run() -> None:
    print(f"[DRY-RUN] 读取: {MAPPINGS_FILE}")
    print(f"[DRY-RUN] 不写盘，仅显示差异\n")
    original = load_mappings(MAPPINGS_FILE)
    new_data, change_map, merge_stats = compute_migrated(original)
    print_comparison(original, new_data, change_map, merge_stats)
    print("=" * 70)
    print("✅ DRY-RUN 完成。使用 --apply --force 真正写盘。")
    print("=" * 70)


def cmd_apply(force: bool) -> None:
    print(f"[APPLY] 读取: {MAPPINGS_FILE}")
    original = load_mappings(MAPPINGS_FILE)
    new_data, change_map, merge_stats = compute_migrated(original)
    print_comparison(original, new_data, change_map, merge_stats)

    if not force:
        print()
        print("⚠️  =============================================================")
        print("⚠️  即将覆盖以下文件：")
        print(f"⚠️    {MAPPINGS_FILE}")
        print("⚠️  会先创建备份到同目录 .bak_YYYYMMDD_HHMMSS")
        print("⚠️  =============================================================")
        try:
            answer = input("Are you sure (yes/NO)? ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n[ABORT] 用户取消")
            sys.exit(1)
        if answer != "yes":
            print("[ABORT] 未输入 yes，取消执行")
            sys.exit(0)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = MAPPINGS_FILE.with_name(f"{MAPPINGS_FILE.name}.bak_{ts}")

    shutil.copy2(MAPPINGS_FILE, backup_path)
    print(f"\n[APPLY] 已备份: {backup_path}")

    new_data["updated_at"] = datetime.datetime.now().timestamp()
    save_mappings(MAPPINGS_FILE, new_data)
    print(f"[APPLY] 已写入: {MAPPINGS_FILE}")
    print(f"[APPLY] 如需回滚执行: python3 {Path(__file__).name} --restore")
    print("✅ APPLY 完成")


def cmd_restore() -> None:
    backup_path = find_latest_backup(MAPPINGS_FILE)
    print(f"[RESTORE] 找到最新备份: {backup_path}")
    print(f"[RESTORE] 目标路径: {MAPPINGS_FILE}")

    answer = "yes"
    try:
        resp = input("确认恢复 (yes/NO)? ").strip().lower()
        if resp:
            answer = resp
    except (EOFError, KeyboardInterrupt):
        pass

    if answer != "yes":
        print("[ABORT] 取消恢复")
        sys.exit(0)

    shutil.copy2(backup_path, MAPPINGS_FILE)
    print(f"[RESTORE] 已从备份恢复: {MAPPINGS_FILE}")
    print("✅ RESTORE 完成")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="template_mappings.json: 自创 parent_id (TDD-001 等) → 原版 Superpowers skill_id 迁移工具",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="默认模式：只打印迁移前后对比，不写盘")
    mode.add_argument("--apply", action="store_true",
                      help="真正写盘：先备份 .bak_时间戳 再覆盖写盘")
    mode.add_argument("--restore", action="store_true",
                      help="回滚：从最近的 .bak_* 备份文件恢复")
    parser.add_argument("--force", action="store_true",
                        help="--apply 时跳过交互式确认（脚本/CI 用）")
    args = parser.parse_args()

    if args.apply:
        cmd_apply(force=args.force)
    elif args.restore:
        cmd_restore()
    else:
        cmd_dry_run()


if __name__ == "__main__":
    main()
