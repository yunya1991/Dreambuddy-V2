#!/usr/bin/env python3
"""为迁移文件添加正确的 frontmatter 标签"""

import re
from pathlib import Path
from typing import Dict, List

# 分类对应的标签
CAT_TAGS = {
    'masters': ['master', 'masters'],
    'tools': ['okx_tools', 'tools'],
    'macro': ['macro_assets', 'correlation', 'cross_asset'],
    'risk': ['risk', 'thresholds'],
    'exit': ['exit', 'rules'],
    'practice': ['practice', 'lessons'],
    'web_strategy': ['web_strategy']
}

ARTIFACTS_ROOT = Path.home() / ".workbuddy" / "artifacts"


def add_tags_to_file(md_file: Path, tags: List[str]) -> bool:
    """为文件添加或更新 tags"""
    try:
        content = md_file.read_text(encoding='utf-8')
        
        # 已有 frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                fm_text = parts[1]
                
                # 已有 tags？
                if re.search(r'^tags\s*:', fm_text, re.MULTILINE):
                    # 更新 tags
                    new_fm = re.sub(
                        r'(^tags\s*:).*$',
                        f'\\1 {tags}',
                        fm_text,
                        flags=re.MULTILINE
                    )
                    new_content = '---' + new_fm + '---' + parts[2]
                else:
                    # 添加 tags
                    fm_text = fm_text.rstrip() + f"\ntags: {tags}\n"
                    new_content = '---' + fm_text + '---' + parts[2]
                
                md_file.write_text(new_content, encoding='utf-8')
                return True
        else:
            # 无 frontmatter，创建
            title = md_file.stem.replace('_', ' ').title()
            fm = f"""---
title: "{title}"
department: knowledge
type: knowledge_article
tags: {tags}
status: active
---

"""
            new_content = fm + content
            md_file.write_text(new_content, encoding='utf-8')
            return True
    
    except Exception as e:
        print(f"  ❌ {md_file.name}: {e}")
        return False


def main():
    print("🏷️ 为迁移文件添加 frontmatter 标签...")
    print("=" * 60)
    
    total = 0
    success = 0
    
    for cat_dir in ARTIFACTS_ROOT.iterdir():
        if not cat_dir.is_dir() or cat_dir.name.startswith('_'):
            continue
        
        tags = CAT_TAGS.get(cat_dir.name, [])
        if not tags:
            continue
        
        cat_count = 0
        for md_file in cat_dir.rglob('*.md'):
            if md_file.name == 'INDEX.md':
                continue
            
            total += 1
            if add_tags_to_file(md_file, tags):
                success += 1
                cat_count += 1
        
        if cat_count > 0:
            print(f"  ✅ {cat_dir.name}: {cat_count} 个文件已添加标签")
    
    print("\n" + "=" * 60)
    print(f"✅ 完成: {success}/{total}")
    
    # 为 exit/ 目录创建 index.json（如果为空）
    exit_dir = ARTIFACTS_ROOT / "exit"
    exit_dir.mkdir(exist_ok=True)
    index_file = exit_dir / "index.json"
    
    if not index_file.exists():
        index_data = {
            "category": "exit",
            "label": "离场规则库",
            "last_updated": "2026-05-05T11:00:00",
            "artifacts": [],
            "statistics": {"total_artifacts": 0}
        }
        with open(index_file, "w") as f:
            import json
            json.dump(index_data, f, indent=2, ensure_ascii=False)
        print(f"  📋 创建 exit/index.json（空模板）")


if __name__ == "__main__":
    main()
