#!/usr/bin/env python3
"""
前后端产物对齐检查脚本 v1.0

检查后端存储结构是否与前端分类体系对齐
"""

import os
import json
import yaml
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# 配置
ARTIFACTS_ROOT = Path.home() / ".workbuddy" / "artifacts"
FRONTEND_DEFINITIONS = {
    "masters": {
        "label": "蒸馏大师库",
        "tags": ["master", "masters", "master_livermore", "master_druckenmiller",
                 "master_soros", "master_tharp", "master_turtle", "master_buffett",
                 "master_lynch", "master_paulson"]
    },
    "tools": {
        "label": "OKX工具库",
        "tags": ["okx_tools", "okx_strategy", "tools", "commands"]
    },
    "macro": {
        "label": "宏观资产库",
        "tags": ["macro_assets", "correlation", "cross_asset"]
    },
    "risk": {
        "label": "风险库",
        "tags": ["risk", "thresholds"]
    },
    "exit": {
        "label": "离场规则库",
        "tags": ["exit", "rules"]
    },
    "practice": {
        "label": "实践教训库",
        "tags": ["practice", "lessons"]
    },
    "web_strategy": {
        "label": "联网策略库",
        "tags": ["web_strategy"]
    }
}

ALL_VALID_TAGS = set()
for cat_info in FRONTEND_DEFINITIONS.values():
    ALL_VALID_TAGS.update(cat_info["tags"])


class AlignmentChecker:
    def __init__(self, artifacts_root: Path):
        self.root = artifacts_root
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "categories": {},
            "issues": [],
            "statistics": {"total_files": 0, "aligned": 0, "issues_count": 0}
        }

    def check_all(self, quick: bool = False) -> Dict[str, Any]:
        """执行完整检查"""
        print("🔍 开始前后端产物对齐检查...")
        print(f"📁 后端根目录: {self.root}")
        print("=" * 60)

        # 1. 检查目录结构
        self._check_directory_structure()

        # 2. 检查索引文件
        self._check_index_files()

        # 3. 检查文件标签
        self._check_file_tags()

        # 4. 统计汇总
        self._compute_statistics()

        return self.results

    def _check_directory_structure(self):
        """检查目录结构"""
        print("\n📂 检查目录结构...")

        for cat_id, cat_info in FRONTEND_DEFINITIONS.items():
            cat_path = self.root / cat_id
            exists = cat_path.exists()

            self.results["categories"][cat_id] = {
                "label": cat_info["label"],
                "path": str(cat_path),
                "exists": exists,
                "files_count": 0,
                "index_exists": False
            }

            if not exists:
                self.results["issues"].append({
                    "type": "missing_directory",
                    "severity": "HIGH",
                    "category": cat_id,
                    "message": f"目录 {cat_id}/ 不存在，需要创建"
                })
                print(f"  ❌ {cat_id}: 目录不存在")
            else:
                print(f"  ✅ {cat_id}: OK")

    def _check_index_files(self):
        """检查索引文件"""
        print("\n📋 检查索引文件...")

        for cat_id in FRONTEND_DEFINITIONS:
            cat_path = self.root / cat_id
            index_path = cat_path / "index.json"

            if cat_path.exists():
                if index_path.exists():
                    try:
                        with open(index_path) as f:
                            index_data = json.load(f)
                        self.results["categories"][cat_id]["index_exists"] = True
                        self.results["categories"][cat_id]["index_valid"] = True
                        self.results["categories"][cat_id]["index_data"] = index_data
                        print(f"  ✅ {cat_id}/index.json: 有效")
                    except Exception as e:
                        self.results["categories"][cat_id]["index_valid"] = False
                        self.results["issues"].append({
                            "type": "invalid_index",
                            "severity": "MEDIUM",
                            "category": cat_id,
                            "message": f"index.json 格式错误: {e}"
                        })
                        print(f"  ⚠️ {cat_id}/index.json: 格式错误")
                else:
                    self.results["categories"][cat_id]["index_exists"] = False
                    print(f"  ⚠️ {cat_id}/index.json: 不存在（将在下次同步时创建）")

    def _check_file_tags(self):
        """检查文件标签一致性"""
        print("\n🏷️ 检查文件标签...")

        for cat_id in FRONTEND_DEFINITIONS:
            cat_path = self.root / cat_id
            if not cat_path.exists():
                continue

            valid_tags = set(FRONTEND_DEFINITIONS[cat_id]["tags"])
            md_files = list(cat_path.rglob("*.md"))

            for md_file in md_files:
                if md_file.name == "index.json":
                    continue

                self.results["statistics"]["total_files"] += 1

                try:
                    with open(md_file) as f:
                        content = f.read()

                    # 提取 frontmatter
                    frontmatter = self._extract_frontmatter(content)
                    file_tags = frontmatter.get("tags", [])

                    # 检查标签有效性
                    invalid_tags = [t for t in file_tags if t not in ALL_VALID_TAGS]

                    if invalid_tags:
                        self.results["issues"].append({
                            "type": "invalid_tags",
                            "severity": "LOW",
                            "category": cat_id,
                            "file": str(md_file.relative_to(self.root)),
                            "message": f"无效标签: {invalid_tags}"
                        })

                    # 检查是否在正确分类
                    has_category_tag = any(t in valid_tags for t in file_tags)
                    if not has_category_tag:
                        self.results["issues"].append({
                            "type": "missing_category_tag",
                            "severity": "MEDIUM",
                            "category": cat_id,
                            "file": str(md_file.relative_to(self.root)),
                            "message": f"文件缺少分类标签（期望: {valid_tags}）"
                        })
                    else:
                        self.results["statistics"]["aligned"] += 1

                except Exception as e:
                    self.results["issues"].append({
                        "type": "read_error",
                        "severity": "LOW",
                        "category": cat_id,
                        "file": str(md_file.relative_to(self.root)),
                        "message": f"读取失败: {e}"
                    })

    def _extract_frontmatter(self, content: str) -> Dict[str, Any]:
        """提取 YAML frontmatter"""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    return yaml.safe_load(parts[1]) or {}
                except:
                    return {}
        return {}

    def _compute_statistics(self):
        """计算统计信息"""
        total = self.results["statistics"]["total_files"]
        aligned = self.results["statistics"]["aligned"]
        issues = len(self.results["issues"])

        self.results["statistics"]["alignment_rate"] = (
            aligned / total * 100 if total > 0 else 100.0
        )
        self.results["statistics"]["issues_count"] = issues

    def print_report(self):
        """打印报告"""
        print("\n" + "=" * 60)
        print("📊 对齐检查报告")
        print("=" * 60)

        # 目录状态
        print("\n📂 目录结构状态:")
        for cat_id, info in self.results["categories"].items():
            status = "✅" if info["exists"] else "❌"
            print(f"  {status} {cat_id}: {info['label']}")

        # 统计
        stats = self.results["statistics"]
        print(f"\n📈 统计:")
        print(f"  总文件数: {stats['total_files']}")
        print(f"  对齐文件: {stats['aligned']}")
        print(f"  对齐率: {stats['alignment_rate']:.1f}%")
        print(f"  问题数: {stats['issues_count']}")

        # 问题列表
        if self.results["issues"]:
            print(f"\n⚠️ 发现 {len(self.results['issues'])} 个问题:")
            for i, issue in enumerate(self.results["issues"], 1):
                severity_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(issue["severity"], "⚪")
                print(f"  {i}. {severity_icon} [{issue['severity']}] {issue['type']}")
                print(f"     {issue['message']}")
                if "file" in issue:
                    print(f"     文件: {issue['file']}")

        return self.results


def main():
    parser = argparse.ArgumentParser(description="前后端产物对齐检查")
    parser.add_argument("--quick", action="store_true", help="快速检查（仅统计）")
    parser.add_argument("--category", type=str, help="检查指定分类")
    parser.add_argument("--output", type=str, help="输出JSON报告路径")
    args = parser.parse_args()

    checker = AlignmentChecker(ARTIFACTS_ROOT)

    if args.quick:
        print("⚡ 快速模式")
        # 仅检查目录结构
        for cat_id in (FRONTEND_DEFINITIONS if not args.category else {args.category: FRONTEND_DEFINITIONS[args.category]}):
            cat_path = ARTIFACTS_ROOT / cat_id
            exists = cat_path.exists()
            count = len(list(cat_path.rglob("*.md"))) if exists else 0
            print(f"  {'✅' if exists else '❌'} {cat_id}: {count} 文件")
    else:
        results = checker.check_all()
        checker.print_report()

        if args.output:
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"\n💾 报告已保存: {args.output}")


if __name__ == "__main__":
    main()
