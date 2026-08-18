#!/usr/bin/env python3
"""
A6情报自动复制脚本 v1.0
===========================
功能: A6产出情报简报后，自动复制到做梦部输入目录
触发: A6 Phase 5 报告生成完成后
位置: ~/.workbuddy/skills/dream-intelligence-monitor/scripts/a6_to_oneirology_broadcast.py

使用方式:
    python a6_to_oneirology_broadcast.py
    python a6_to_oneirology_broadcast.py --latest
    python a6_to_oneirology_broadcast.py --hours 2

修复问题:
    - A6→做梦部传导机制断裂
    - 做梦部情报输入目录为空
"""

import os
import sys
import glob
import shutil
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 配置路径
WORKSPACE = Path("/Users/zhangjiangtao/WorkBuddy/20260415144304")
REPORTS_DIR = WORKSPACE / "reports"
ONEIROLOGY_INPUT = Path("/Users/zhangjiangtao/.workbuddy/skills/dream-oneirology/intelligence_input")
SECRETARY_REPORTS = Path("/Users/zhangjiangtao/.workbuddy/skills/boss-secretary/reports/trading")

# 确保目标目录存在
ONEIROLOGY_INPUT.mkdir(parents=True, exist_ok=True)
SECRETARY_REPORTS.mkdir(parents=True, exist_ok=True)


def find_latest_intelligence_briefing():
    """查找最新的情报简报"""
    pattern = REPORTS_DIR / "intelligence_briefing_*.md"
    files = list(glob.glob(str(pattern)))

    if not files:
        # 尝试查找无时间戳的版本
        pattern2 = REPORTS_DIR / "reports" / "intelligence_briefing_*.md"
        files = list(glob.glob(str(pattern2)))

    if not files:
        return None

    # 返回最新的文件
    return max(files, key=os.path.getmtime)


def find_recent_intelligence_briefings(hours=24):
    """查找最近N小时内的情报简报"""
    pattern = REPORTS_DIR / "intelligence_briefing_*.md"
    files = glob.glob(str(pattern))

    if not files:
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    recent_files = []

    for f in files:
        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        if mtime > cutoff:
            recent_files.append((f, mtime))

    # 按时间倒序
    recent_files.sort(key=lambda x: x[1], reverse=True)
    return [f[0] for f in recent_files]


def copy_to_oneirology(source_file):
    """复制情报简报到做梦部输入目录"""
    filename = os.path.basename(source_file)
    dest_file = ONEIROLOGY_INPUT / filename

    try:
        shutil.copy2(source_file, dest_file)
        print(f"✅ 已复制到做梦部: {filename}")
        return True
    except Exception as e:
        print(f"❌ 复制失败: {e}")
        return False


def copy_to_secretary(source_file):
    """复制情报简报到秘书目录"""
    filename = os.path.basename(source_file)
    dest_file = SECRETARY_REPORTS / filename

    try:
        shutil.copy2(source_file, dest_file)
        print(f"✅ 已复制到秘书目录: {filename}")
        return True
    except Exception as e:
        print(f"❌ 复制到秘书目录失败: {e}")
        return False


def broadcast_to_oneirology():
    """广播最新情报到做梦部"""
    print("=" * 60)
    print("📡 A6情报自动广播到做梦部")
    print("=" * 60)

    # 查找最新的情报简报
    latest = find_latest_intelligence_briefing()

    if not latest:
        print("⚠️ 未找到情报简报，跳过广播")
        return False

    print(f"\n📄 最新情报简报: {os.path.basename(latest)}")
    print(f"   生成时间: {datetime.fromtimestamp(os.path.getmtime(latest))}")

    # 复制到做梦部
    success1 = copy_to_oneirology(latest)

    # 复制到秘书目录
    success2 = copy_to_secretary(latest)

    if success1 and success2:
        print("\n✅ A6→做梦部 传导链路已打通!")
        print(f"   做梦部将在下次运行时读取此情报")
        return True
    else:
        print("\n⚠️ 部分复制失败，请检查权限")
        return False


def broadcast_recent_to_oneirology(hours=24):
    """广播最近N小时的情报到做梦部"""
    print("=" * 60)
    print(f"📡 广播最近{hours}小时的情报到做梦部")
    print("=" * 60)

    recent_files = find_recent_intelligence_briefings(hours)

    if not recent_files:
        print(f"⚠️ 最近{hours}小时内未找到情报简报")
        return False

    print(f"\n找到 {len(recent_files)} 份情报简报:")

    success_count = 0
    for f in recent_files[:10]:  # 最多10份
        filename = os.path.basename(f)
        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        print(f"   - {filename} ({mtime.strftime('%H:%M')})")

        if copy_to_oneirology(f):
            success_count += 1

    print(f"\n✅ 成功广播 {success_count}/{len(recent_files[:10])} 份情报")
    return success_count > 0


def main():
    parser = argparse.ArgumentParser(description="A6情报自动复制脚本")
    parser.add_argument("--latest", action="store_true", help="仅复制最新情报")
    parser.add_argument("--hours", type=int, default=24, help="复制最近N小时的情报")
    parser.add_argument("--auto", action="store_true", help="自动模式（仅复制最新的1份）")

    args = parser.parse_args()

    if args.latest:
        return broadcast_to_oneirology()
    elif args.auto:
        return broadcast_to_oneirology()
    else:
        return broadcast_recent_to_oneirology(args.hours)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
