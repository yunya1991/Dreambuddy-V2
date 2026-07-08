#!/usr/bin/env python3
"""
前端分类索引同步脚本 v1.0

从后端规范目录同步到前端 FeedClient 分类体系
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any
import sys

# 配置
ARTIFACTS_ROOT = Path.home() / ".workbuddy" / "artifacts"
FRONTEND_FEED_DIR = Path.home() / ".workbuddy" / "skills" / "dream-exit-skill-v2" / "web" / "app" / "feed"

# 分类定义（需与 FeedClient.tsx 同步）
CATEGORIES = {
    "masters": {"label": "蒸馏大师库", "emoji": "🏛️"},
    "tools": {"label": "OKX工具库", "emoji": "🛠️"},
    "macro": {"label": "宏观资产库", "emoji": "📊"},
    "risk": {"label": "风险库", "emoji": "⚠️"},
    "exit": {"label": "离场规则库", "emoji": "🚪"},
    "practice": {"label": "实践教训库", "emoji": "⚔️"},
    "web_strategy": {"label": "联网策略库", "emoji": "🌐"},
}


def scan_category(cat_id: str, cat_info: Dict) -> Dict[str, Any]:
    """扫描单个分类目录"""
    cat_path = ARTIFACTS_ROOT / cat_id
    if not cat_path.exists():
        return {"exists": False, "artifacts": [], "count": 0}

    artifacts = []
    
    # 读取 index.json（如果存在）
    index_path = cat_path / "index.json"
    if index_path.exists():
        try:
            with open(index_path) as f:
                index_data = json.load(f)
            return {
                "exists": True,
                "from_index": True,
                "artifacts": index_data.get("artifacts", []),
                "count": len(index_data.get("artifacts", [])),
                "statistics": index_data.get("statistics", {})
            }
        except:
            pass
    
    # 若无 index.json，扫描 .md 文件
    for md_file in cat_path.rglob("*.md"):
        rel_path = md_file.relative_to(cat_path)
        artifacts.append({
            "artifact_id": md_file.stem,
            "title": md_file.stem.replace("_", " ").title(),
            "filename": str(rel_path),
            "tags": [cat_id],
            "status": "active"
        })
    
    return {
        "exists": True,
        "from_index": False,
        "artifacts": artifacts,
        "count": len(artifacts)
    }


def sync_to_frontend(all_data: Dict[str, Any]) -> bool:
    """同步到前端（生成前端可读取的 JSON）"""
    frontend_data_dir = ARTIFACTS_ROOT / "_frontend_cache"
    frontend_data_dir.mkdir(exist_ok=True)
    
    # 生成每个分类的索引
    for cat_id, cat_data in all_data.items():
        if not cat_data["exists"]:
            continue
        
        frontend_file = frontend_data_dir / f"{cat_id}_index.json"
        with open(frontend_file, "w") as f:
            json.dump({
                "category": cat_id,
                "label": CATEGORIES[cat_id]["label"],
                "emoji": CATEGORIES[cat_id]["emoji"],
                "last_sync": str(Path.home()),
                "artifacts": cat_data["artifacts"]
            }, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ 已同步 {cat_id}_index.json ({cat_data['count']} 条)")
    
    return True


def generate_alignment_report(all_data: Dict[str, Any]) -> Dict[str, Any]:
    """生成对齐报告"""
    report = {
        "timestamp": str(Path.home()),
        "categories": {},
        "summary": {"total_artifacts": 0, "missing_categories": []}
    }
    
    for cat_id in CATEGORIES:
        cat_data = all_data.get(cat_id, {"exists": False})
        report["categories"][cat_id] = {
            "label": CATEGORIES[cat_id]["label"],
            "exists": cat_data["exists"],
            "count": cat_data.get("count", 0)
        }
        
        if cat_data["exists"]:
            report["summary"]["total_artifacts"] += cat_data["count"]
        else:
            report["summary"]["missing_categories"].append(cat_id)
    
    return report


def main():
    print("🔄 前后端产物对齐同步")
    print("=" * 60)
    
    # 1. 扫描所有分类
    print("\n📂 扫描后端分类目录...")
    all_data = {}
    
    for cat_id, cat_info in CATEGORIES.items():
        print(f"  扫描 {cat_id}...")
        cat_data = scan_category(cat_id, cat_info)
        all_data[cat_id] = cat_data
        
        status = "✅" if cat_data["exists"] else "❌"
        print(f"    {status} {cat_info['label']}: {cat_data.get('count', 0)} 个产物")
    
    # 2. 同步到前端缓存
    print("\n🔄 同步到前端缓存...")
    sync_to_frontend(all_data)
    
    # 3. 生成报告
    print("\n📊 生成对齐报告...")
    report = generate_alignment_report(all_data)
    
    # 4. 打印摘要
    print("\n" + "=" * 60)
    print("📋 同步摘要")
    print("=" * 60)
    print(f"总产物数: {report['summary']['total_artifacts']}")
    
    if report["summary"]["missing_categories"]:
        print(f"\n⚠️ 缺失分类: {', '.join(report['summary']['missing_categories'])}")
        print("   提示: 运行 migrate 脚本创建目录")
    
    print("\n💡 下一步:")
    print("  1. 检查报告确认对齐状态")
    print("  2. 执行迁移: python3 migrate.py")
    print("  3. 更新前端 FeedClient.tsx（如分类有变更）")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
