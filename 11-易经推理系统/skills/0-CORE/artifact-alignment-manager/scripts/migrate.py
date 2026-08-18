#!/usr/bin/env python3
"""
智能迁移脚本 v1.0

将 .knowledge_base/ 迁移到新结构
"""

import os
import json
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

# 迁移映射
MIGRATION_MAP = {
    "1_regime_patterns": "macro",          # 宏观资产库
    "2_classic_strategies": "web_strategy", # 联网策略库
    "3_trading_tools": "tools",            # OKX工具库（部分→risk）
    "4_master_profiles": "masters",        # 蒸馏大师库
    "5_practice_strategies": "practice",   # 实践教训库
}

# 特殊情况映射（子目录或文件名）
SPECIAL_MAP = {
    "3_trading_tools/risk": "risk",        # 风险库
    "3_trading_tools": "tools",            # 其余工具
}


def analyze_source(source_dir: Path) -> List[Tuple[Path, str]]:
    """分析源文件并决定目标分类"""
    migrations = []
    
    for md_file in source_dir.rglob("*.md"):
        rel_path = md_file.relative_to(source_dir)
        parts = rel_path.parts
        
        # 确定目标分类
        target_cat = None
        
        # 一级目录映射
        if len(parts) >= 1:
            top_dir = parts[0]
            if top_dir in MIGRATION_MAP:
                target_cat = MIGRATION_MAP[top_dir]
        
        # 特殊处理：风险文件
        if len(parts) >= 2 and parts[0] == "3_trading_tools":
            if "risk" in parts[1].lower() or "stop" in parts[1].lower():
                target_cat = "risk"
        
        if target_cat:
            migrations.append((md_file, target_cat))
    
    return migrations


def migrate_file(src: Path, target_cat: str, artifacts_root: Path) -> bool:
    """迁移单个文件"""
    target_dir = artifacts_root / target_cat
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 保持子目录结构
    rel_path = src.relative_to(src.parent.parent.parent)  # 去掉顶层
    target_file = target_dir / src.name  # 简化为直接使用文件名
    
    try:
        shutil.copy2(src, target_file)
        print(f"  ✅ {src.name} → {target_cat}/")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False


def create_index_json(target_dir: Path, category: str):
    """为分类创建 index.json"""
    artifacts = []
    
    for md_file in target_dir.rglob("*.md"):
        artifacts.append({
            "artifact_id": md_file.stem,
            "title": md_file.stem.replace("_", " ").title(),
            "filename": str(md_file.relative_to(target_dir)),
            "tags": [category],
            "status": "active"
        })
    
    index_data = {
        "category": category,
        "last_updated": "2026-05-05T10:45:00",
        "artifacts": artifacts,
        "statistics": {
            "total_artifacts": len(artifacts)
        }
    }
    
    index_file = target_dir / "index.json"
    with open(index_file, "w") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)
    
    print(f"  📋 创建 {category}/index.json ({len(artifacts)} 条)")


def main():
    source_dir = Path.home() / "WorkBuddy" / "20260415144304" / ".knowledge_base"
    artifacts_root = Path.home() / ".workbuddy" / "artifacts"
    
    print("🚀 开始迁移 .knowledge_base/ → artifacts/")
    print(f"   源: {source_dir}")
    print(f"   目标: {artifacts_root}")
    print("=" * 60)
    
    # 1. 分析
    print("\n🔍 分析源文件...")
    migrations = analyze_source(source_dir)
    print(f"   发现 {len(migrations)} 个文件待迁移")
    
    # 2. 按分类分组
    by_category = {}
    for src, cat in migrations:
        by_category.setdefault(cat, []).append(src)
    
    # 3. 执行迁移
    print("\n📦 执行迁移...")
    success_count = 0
    
    for cat in ["masters", "tools", "macro", "risk", "exit", "practice", "web_strategy"]:
        if cat not in by_category:
            continue
        
        print(f"\n  处理 {cat} ({len(by_category[cat])} 文件):")
        for src in by_category[cat]:
            if migrate_file(src, cat, artifacts_root):
                success_count += 1
    
    # 4. 创建 index.json
    print("\n📋 创建索引文件...")
    for cat in ["masters", "tools", "macro", "risk", "exit", "practice", "web_strategy"]:
        target_dir = artifacts_root / cat
        if target_dir.exists() and any(target_dir.iterdir()):
            create_index_json(target_dir, cat)
    
    # 5. 结果汇总
    print("\n" + "=" * 60)
    print("✅ 迁移完成")
    print(f"   成功: {success_count}/{len(migrations)}")
    print("\n💡 下一步:")
    print("  1. 运行 check_alignment.py 验证")
    print("  2. 检查产物标签是否正确")
    print("  3. 更新前端 FeedClient.tsx（如需要）")


if __name__ == "__main__":
    main()
