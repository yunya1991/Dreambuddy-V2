#!/usr/bin/env python3
"""
三邮箱状态检查脚本
检查秘书、调研部、待修复三个邮箱的状态
（顾问邮箱已于2026-04-26废弃，顾问评审已内嵌到各SKILL中直接调用）
"""

import os
from pathlib import Path
from datetime import datetime, timedelta

# ==================== 配置 ====================
WORKSPACE = Path.home() / "WorkBuddy" / "20260415144304"

# 邮箱目录配置（按宪法§12 v2.8 三邮箱规范）
# 注：顾问邮箱已于2026-04-26废弃，顾问评审内嵌到各SKILL直接调用
MAILBOXES = {
    "秘书邮箱": {
        "path": WORKSPACE / ".workbuddy" / "mailbox" / "secretary",
        "description": "各部门报告汇总",
        "check_age_hours": 4,  # 超过4小时无新文件则警告
    },
    "调研部邮箱": {
        "path": WORKSPACE / ".workbuddy" / "mailbox" / "research",
        "description": "深度调研报告",
        "check_age_hours": 24,
    },
    # "顾问邮箱" 已废弃(2026-04-26): 顾问评审内嵌到各SKILL
    "待修复邮箱": {
        "path": WORKSPACE / ".workbuddy" / "mailbox" / "pending",
        "description": "待执行修复任务",
        "check_age_hours": 8,
    },
    "交易邮箱": {
        "path": WORKSPACE / ".workbuddy" / "mailbox" / "trading",
        "description": "A1-A5决策链路专用",
        "check_age_hours": 1,
    },
}

# 提案目录
PROPOSALS_DIR = WORKSPACE / "reports" / "proposals"

# ==================== 检查函数 ====================

def check_mailbox(name: str, config: dict) -> dict:
    """检查单个邮箱状态"""
    path = config["path"]
    check_hours = config["check_age_hours"]
    
    result = {
        "name": name,
        "path": str(path),
        "description": config["description"],
        "exists": path.exists(),
        "files": [],
        "file_count": 0,
        "total_size_kb": 0,
        "oldest_file": None,
        "newest_file": None,
        "status": "OK",
        "warnings": [],
    }
    
    if not path.exists():
        result["status"] = "MISSING"
        result["warnings"].append("邮箱目录不存在")
        return result
    
    # 扫描文件
    cutoff = datetime.now() - timedelta(hours=check_hours)
    
    for f in sorted(path.iterdir(), key=lambda x: x.stat().st_mtime if x.is_file() else 0):
        if not f.is_file():
            continue
        
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            size_kb = f.stat().st_size / 1024
            
            result["files"].append({
                "name": f.name,
                "size_kb": round(size_kb, 1),
                "modified": mtime.strftime("%m-%d %H:%M"),
                "age_hours": round((datetime.now() - mtime).total_seconds() / 3600, 1),
            })
            result["total_size_kb"] += size_kb
            
            if result["oldest_file"] is None or mtime < datetime.fromtimestamp(result["oldest_file"]["time"]):
                result["oldest_file"] = {"name": f.name, "time": mtime}
            
            if result["newest_file"] is None or mtime > datetime.fromtimestamp(result["newest_file"]["time"]):
                result["newest_file"] = {"name": f.name, "time": mtime}
            
            # 检查是否超时
            if mtime < cutoff and check_hours > 0:
                result["warnings"].append(f"文件 {f.name} 超过{check_hours}h无更新")
                
        except Exception as e:
            result["warnings"].append(f"读取 {f.name} 失败: {e}")
    
    result["file_count"] = len(result["files"])
    
    # 判断状态
    if result["file_count"] == 0:
        if name in ["秘书邮箱", "交易邮箱"]:
            result["status"] = "WARNING"
            result["warnings"].append("重要邮箱为空")
        else:
            result["status"] = "OK"
    
    if result["warnings"]:
        result["status"] = "WARNING"
    
    return result


def check_proposals() -> dict:
    """检查提案状态"""
    result = {
        "pending": [],
        "archive": [],
        "today_count": 0,
        "status": "OK",
    }
    
    if not PROPOSALS_DIR.exists():
        result["status"] = "MISSING"
        return result
    
    today = datetime.now().strftime("%Y%m%d")
    
    for f in PROPOSALS_DIR.iterdir():
        if not f.is_file() or not f.name.endswith(".md"):
            continue
        
        if today in f.name:
            result["today_count"] += 1
        elif "archive" in str(f):
            result["archive"].append(f.name)
        else:
            result["pending"].append(f.name)
    
    if result["pending"]:
        result["status"] = "WARNING"
    
    return result


def generate_report() -> str:
    """生成四邮箱状态报告"""
    lines = [
        "# 📬 四邮箱状态检查报告",
        f"**检查时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "---",
        "",
    ]
    
    all_ok = True
    total_warnings = 0
    
    # 检查各邮箱
    for name, config in MAILBOXES.items():
        result = check_mailbox(name, config)
        
        status_icon = {
            "OK": "🟢",
            "WARNING": "🟡",
            "MISSING": "🔴",
        }.get(result["status"], "⚪")
        
        lines.append(f"## {status_icon} {name}")
        lines.append(f"**描述**: {result['description']}")
        lines.append(f"**路径**: `{result['path']}`")
        lines.append(f"**状态**: {result['status']}")
        lines.append(f"**文件数**: {result['file_count']}")
        
        if result["file_count"] > 0:
            lines.append(f"**最新文件**: {result['newest_file']['name']} ({result['newest_file']['time'].strftime('%m-%d %H:%M')})")
        
        if result["warnings"]:
            all_ok = False
            total_warnings += len(result["warnings"])
            lines.append("**⚠️ 警告**:")
            for w in result["warnings"]:
                lines.append(f"  - {w}")
        
        lines.append("")
    
    # 检查提案
    proposals = check_proposals()
    lines.append("## 📋 提案状态")
    
    if proposals["status"] == "MISSING":
        lines.append("🔴 **提案目录不存在**")
    else:
        lines.append(f"**今日提案**: {proposals['today_count']} 个")
        
        if proposals["pending"]:
            all_ok = False
            total_warnings += len(proposals["pending"])
            lines.append(f"**🟡 待处理提案**: {len(proposals['pending'])} 个")
            for p in proposals["pending"]:
                lines.append(f"  - {p}")
        
        if proposals["archive"]:
            lines.append(f"**归档提案**: {len(proposals['archive'])} 个")
    
    lines.append("")
    
    # 汇总
    if all_ok:
        lines.append("## ✅ 总体状态: 正常")
    else:
        lines.append(f"## ⚠️ 总体状态: 有{total_warnings}个警告")
    
    lines.extend([
        "",
        "---",
        "*报告生成时间: auto-repair v1.0*",
    ])
    
    return "\n".join(lines)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="四邮箱状态检查")
    parser.add_argument("--output", "-o", help="输出文件路径")
    args = parser.parse_args()
    
    report = generate_report()
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已保存: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
