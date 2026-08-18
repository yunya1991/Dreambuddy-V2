#!/usr/bin/env python3
"""
A系列研报 桥接同步脚本
================================

功能：
  1. 扫描 ~/.workbuddy/skills/boss-secretary/reports/trading/ 中的 A1 JSON 和 A6 MD 报告
  2. 将最新报告同步到 experiments/ab-trading/A系列研报/A1研报/ 和 A6研报/
  3. 防止重复文件（按内容 hash 去重）

用法：
  python sync_a_reports.py              # 执行一次同步
  python sync_a_reports.py --watch     # 持续监听（每 60 秒检查一次）
  python sync_a_reports.py --dry-run   # 仅打印，不实际复制
"""

import argparse
import hashlib
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple


# ── 路径配置 ────────────────────────────────────────────────────────────────

_SRC_DIR = Path.home() / ".workbuddy" / "skills" / "boss-secretary" / "reports" / "trading"
_SRC_SCREEN1_DIR = Path.home() / ".workbuddy" / "skills" / "boss-secretary" / "reports" / "trading" / "6-trading" / "screen1"
_DST_A1  = Path(__file__).resolve().parent.parent / "A系列研报" / "A1研报"
_DST_A6  = Path(__file__).resolve().parent.parent / "A系列研报" / "A6研报"
_DST_WEEKLY = Path(__file__).resolve().parent.parent / "A系列研报" / "周报"

# 确保目标目录存在
_DST_A1.mkdir(parents=True, exist_ok=True)
_DST_A6.mkdir(parents=True, exist_ok=True)
_DST_WEEKLY.mkdir(parents=True, exist_ok=True)

# 文件年龄阈值（秒）—— 超过此年龄的源文件不再同步（避免同步陈旧报告）
_MAX_AGE_SECS = 86400  # 24 小时 (A1/A6)
_MAX_AGE_WEEKLY = 86400 * 14  # 14 天 (周报，因为每周才生成一次)


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _file_hash(filepath: Path) -> str:
    """计算文件内容 SHA-256，用于去重"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _list_src_a1_reports() -> List[Tuple[Path, float]]:
    """
    列出源目录中所有 A1 报告 JSON 文件，按修改时间排序（新→旧）
    返回 [(path, mtime), ...]
    使用 set 去重，避免多 pattern 匹配同一文件。
    """
    if not _SRC_DIR.exists():
        return []
    seen: set = set()
    files: List[Tuple[Path, float]] = []
    for pattern in ["a1_regime_*.json", "a1_research_*.json", "a1_*.json"]:
        for p in _SRC_DIR.glob(pattern):
            if p.is_file() and p not in seen:
                seen.add(p)
                files.append((p, p.stat().st_mtime))
    files.sort(key=lambda x: x[1], reverse=True)
    return files


def _list_src_a6_reports() -> List[Tuple[Path, float]]:
    """
    列出源目录中所有 A6 情报报告 MD 文件，按修改时间排序（新→旧）
    返回 [(path, mtime), ...]
    使用 set 去重，避免多 pattern 匹配同一文件。
    """
    if not _SRC_DIR.exists():
        return []
    seen: set = set()
    files: List[Tuple[Path, float]] = []
    for pattern in ["a6_intelligence_*.md", "intelligence_briefing_*.md", "a6_*.md"]:
        for p in _SRC_DIR.glob(pattern):
            if p.is_file() and p not in seen:
                seen.add(p)
                files.append((p, p.stat().st_mtime))
    files.sort(key=lambda x: x[1], reverse=True)
    return files


def _list_src_weekly_reports() -> List[Tuple[Path, float]]:
    """
    列出源目录中所有第一屏周报 screen1_*.md 文件，按修改时间排序（新→旧）
    返回 [(path, mtime), ...]
    使用 set 去重，避免多 pattern 匹配同一文件。
    """
    if not _SRC_SCREEN1_DIR.exists():
        return []
    seen: set = set()
    files: List[Tuple[Path, float]] = []
    for pattern in ["screen1_*.md"]:
        for p in _SRC_SCREEN1_DIR.glob(pattern):
            if p.is_file() and p not in seen:
                seen.add(p)
                files.append((p, p.stat().st_mtime))
    files.sort(key=lambda x: x[1], reverse=True)
    return files


def _already_synced(filepath: Path, dst_dir: Path) -> bool:
    """检查文件是否已同步过（按文件名或内容 hash 判断）"""
    # 方式1：同名文件已存在
    if (dst_dir / filepath.name).exists():
        return True
    # 方式2：内容相同的文件已存在（hash 去重）
    src_hash = _file_hash(filepath)
    for existing in dst_dir.iterdir():
        if existing.is_file() and existing.suffix == filepath.suffix:
            if _file_hash(existing) == src_hash:
                return True
    return False


def _copy_report(src: Path, dst_dir: Path, dry_run: bool = False) -> bool:
    """复制单个报告到目标目录，返回是否成功"""
    dst = dst_dir / src.name
    if _already_synced(src, dst_dir):
        print(f"  ⏭️  已存在，跳过: {src.name}")
        return False

    if dry_run:
        print(f"  [dry-run] 将复制: {src.name} → {dst_dir.name}/")
        return True

    shutil.copy2(src, dst)
    print(f"  ✅ 已复制: {src.name} → {dst_dir.name}/")
    return True


# ── 核心同步逻辑 ────────────────────────────────────────────────────────────

def sync_a1_reports(dry_run: bool = False) -> int:
    """
    同步 A1 报告：
      - 从 _SRC_DIR 读取最新 a1_regime_*.json
      - 复制到 _DST_A1
      - 只同步最近 24 小时内的文件
    返回：同步的文件数量
    """
    print("\n📊 同步 A1 研报（战略调研）")
    reports = _list_src_a1_reports()
    if not reports:
        print("  ℹ️  源目录无 A1 报告文件")
        return 0

    now = time.time()
    synced = 0
    for src, mtime in reports:
        age = now - mtime
        if age > _MAX_AGE_SECS:
            print(f"  ⏳  跳过过期文件 ({age/3600:.1f}h): {src.name}")
            continue
        if _copy_report(src, _DST_A1, dry_run):
            synced += 1
        # 每次同步最多复制 3 个最新文件（避免历史文件批量涌入）
        if synced >= 3:
            break

    # 同时检查 dreambuddy-v2 下的 A1 报告（如有）
    alt_src = Path.home() / "WorkBuddy" / "dreambuddy-v2" / "6-TRADING" / "reports" / "trading"
    if alt_src.exists():
        for pattern in ["a1_regime_*.json", "a1_research_*.json"]:
            for src in sorted(alt_src.glob(pattern), key=os.path.getmtime, reverse=True)[:3]:
                age = now - src.stat().st_mtime
                if age > _MAX_AGE_SECS:
                    continue
                if _copy_report(src, _DST_A1, dry_run):
                    synced += 1

    print(f"  📋 A1 同步完成：{synced} 个文件")
    return synced


def sync_a6_reports(dry_run: bool = False) -> int:
    """
    同步 A6 报告：
      - 从 _SRC_DIR 读取最新 a6_intelligence_*.md / intelligence_briefing_*.md
      - 复制到 _DST_A6
      - 只同步最近 24 小时内的文件
    返回：同步的文件数量
    """
    print("\n📡 同步 A6 研报（情报监控）")
    reports = _list_src_a6_reports()
    if not reports:
        print("  ℹ️  源目录无 A6 报告文件")
        return 0

    now = time.time()
    synced = 0
    for src, mtime in reports:
        age = now - mtime
        if age > _MAX_AGE_SECS:
            print(f"  ⏳  跳过过期文件 ({age/3600:.1f}h): {src.name}")
            continue
        if _copy_report(src, _DST_A6, dry_run):
            synced += 1
        if synced >= 5:  # A6 报告更频繁，最多同步 5 个
            break

    print(f"  📋 A6 同步完成：{synced} 个文件")
    return synced


def sync_weekly_reports(dry_run: bool = False) -> int:
    """
    同步第一屏周报：
      - 从 _SRC_SCREEN1_DIR 读取最新 screen1_*.md
      - 复制到 _DST_WEEKLY
      - 同步最近 14 天内的文件（周报每周生成，保留两周）
    返回：同步的文件数量
    """
    print("\n📅 同步周报（第一屏周度方向）")
    reports = _list_src_weekly_reports()
    if not reports:
        print("  ℹ️  源目录无周报文件")
        return 0

    now = time.time()
    synced = 0
    for src, mtime in reports:
        age = now - mtime
        if age > _MAX_AGE_WEEKLY:
            print(f"  ⏳  跳过过期文件 ({age/86400:.1f}d): {src.name}")
            continue
        if _copy_report(src, _DST_WEEKLY, dry_run):
            synced += 1
        # 周报最多同步最近 3 份
        if synced >= 3:
            break

    print(f"  📋 周报同步完成：{synced} 个文件")
    return synced


def run_once(dry_run: bool = False) -> Dict[str, int]:
    """执行一次同步"""
    print("=" * 60)
    print(f"🚀 A系列研报同步  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   源: {_SRC_DIR}")
    print(f"   A1 → {_DST_A1}")
    print(f"   A6 → {_DST_A6}")
    print(f"   周报 → {_DST_WEEKLY}")
    print(f"   dry_run={dry_run}")
    print("=" * 60)

    a1_count = sync_a1_reports(dry_run)
    a6_count = sync_a6_reports(dry_run)
    weekly_count = sync_weekly_reports(dry_run)

    print(f"\n✅ 同步完成  A1={a1_count}  A6={a6_count}  周报={weekly_count}")
    return {"a1": a1_count, "a6": a6_count, "weekly": weekly_count}


def run_watch(interval_sec: int = 60, dry_run: bool = False):
    """持续监听模式：每 interval_sec 秒检查一次"""
    print(f"👁️  持续监听模式（间隔 {interval_sec}s），Ctrl+C 退出")
    try:
        while True:
            run_once(dry_run)
            print(f"\n⏰  等待 {interval_sec} 秒后下次检查...")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n👋 监听已停止")


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="A系列研报桥接同步脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python sync_a_reports.py                  # 同步一次
  python sync_a_reports.py --dry-run       # 预览，不实际复制
  python sync_a_reports.py --watch         # 持续监听（每60秒）
  python sync_a_reports.py --watch -i 300  # 持续监听（每5分钟）
"""
    )
    parser.add_argument("--watch", "-w", action="store_true",
                        help="持续监听模式")
    parser.add_argument("--interval", "-i", type=int, default=60,
                        help="监听模式下的检查间隔（秒），默认 60")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="仅打印操作，不实际复制文件")
    args = parser.parse_args()

    if args.watch:
        run_watch(interval_sec=args.interval, dry_run=args.dry_run)
    else:
        run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
