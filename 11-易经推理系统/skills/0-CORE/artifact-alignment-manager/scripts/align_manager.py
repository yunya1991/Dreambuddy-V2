#!/usr/bin/env python3
"""
前后端产物对齐管理器 v2.0

完整闭环: 检测 → 诊断 → 修复 → 验证 → 报告
"""

import os
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# 配置
ARTIFACTS_ROOT = Path.home() / ".workbuddy" / "artifacts"
SKILL_ROOT = Path.home() / ".workbuddy" / "skills" / "artifact-alignment-manager"
AUDIT_DIR = ARTIFACTS_ROOT / "audit"

# 分类定义
CATEGORIES = {
    "masters": {"label": "蒸馏大师库", "tags": ["master", "masters"]},
    "tools": {"label": "OKX工具库", "tags": ["okx_tools", "tools", "commands"]},
    "macro": {"label": "宏观资产库", "tags": ["macro_assets", "correlation", "cross_asset"]},
    "risk": {"label": "风险库", "tags": ["risk", "thresholds"]},
    "exit": {"label": "离场规则库", "tags": ["exit", "rules"]},
    "practice": {"label": "实践教训库", "tags": ["practice", "lessons"]},
    "web_strategy": {"label": "联网策略库", "tags": ["web_strategy"]},
}

# 收集所有有效标签
ALL_TAGS = set()
for cat_info in CATEGORIES.values():
    ALL_TAGS.update(cat_info["tags"])


class AlignmentManager:
    """前后端产物对齐管理器"""

    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "phases": {},
            "issues": [],
            "fixes": [],
            "statistics": {"total_files": 0, "aligned": 0, "fixed": 0}
        }

    def run(self, mode: str = "check", category: Optional[str] = None):
        """执行主流程"""
        print("=" * 70)
        print("🔧 前后端产物对齐管理器 v2.0")
        print("=" * 70)
        print(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📋 执行模式: {mode}")
        print(f"📁 后端目录: {ARTIFACTS_ROOT}")
        print("=" * 70)

        # 确保目录存在
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)

        # 执行各阶段检查
        self.phase1_directory_structure(category)
        self.phase2_index_files(category)
        self.phase3_tags_consistency(category)
        self.phase4_frontmatter(category)

        # 统计
        self.compute_statistics()

        # 根据模式执行修复
        if mode in ["fix", "full"]:
            self.auto_fix()

        # 验证
        if mode == "full":
            self.verify_fixes()

        # 生成报告
        report = self.generate_report(mode)
        self.save_report(report)

        # 打印摘要
        self.print_summary(mode)

        return self.results

    def phase1_directory_structure(self, category: Optional[str] = None):
        """Phase 1: 目录结构检查"""
        print("\n📂 Phase 1: 目录结构检查")
        print("-" * 50)

        self.results["phases"]["directory"] = {}
        cats_to_check = {category: CATEGORIES[category]} if category else CATEGORIES

        for cat_id, cat_info in cats_to_check.items():
            cat_path = ARTIFACTS_ROOT / cat_id
            exists = cat_path.exists()

            self.results["phases"]["directory"][cat_id] = {
                "path": str(cat_path),
                "exists": exists,
                "status": "OK" if exists else "MISSING"
            }

            if not exists:
                print(f"  ❌ {cat_id}: 目录不存在")
                self.results["issues"].append({
                    "phase": "directory",
                    "severity": "HIGH",
                    "category": cat_id,
                    "issue": f"目录 {cat_id}/ 不存在",
                    "fix_action": "create_directory"
                })
            else:
                print(f"  ✅ {cat_id}: OK ({cat_info['label']})")

    def phase2_index_files(self, category: Optional[str] = None):
        """Phase 2: 索引文件检查"""
        print("\n📋 Phase 2: 索引文件检查")
        print("-" * 50)

        self.results["phases"]["index"] = {}
        cats_to_check = {category: CATEGORIES[category]} if category else CATEGORIES

        for cat_id in cats_to_check:
            cat_path = ARTIFACTS_ROOT / cat_id
            index_path = cat_path / "index.json"

            if not cat_path.exists():
                continue

            exists = index_path.exists()
            valid = False

            if exists:
                try:
                    with open(index_path) as f:
                        data = json.load(f)
                    valid = "category" in data and "artifacts" in data
                except:
                    valid = False

            self.results["phases"]["index"][cat_id] = {
                "exists": exists,
                "valid": valid,
                "status": "OK" if (exists and valid) else "INVALID"
            }

            if not exists:
                print(f"  ⚠️ {cat_id}/index.json: 不存在")
                self.results["issues"].append({
                    "phase": "index",
                    "severity": "MEDIUM",
                    "category": cat_id,
                    "issue": f"{cat_id}/index.json 不存在",
                    "fix_action": "rebuild_index"
                })
            elif not valid:
                print(f"  ⚠️ {cat_id}/index.json: 格式无效")
                self.results["issues"].append({
                    "phase": "index",
                    "severity": "MEDIUM",
                    "category": cat_id,
                    "issue": f"{cat_id}/index.json 格式无效",
                    "fix_action": "rebuild_index"
                })
            else:
                print(f"  ✅ {cat_id}/index.json: OK")

    def phase3_tags_consistency(self, category: Optional[str] = None):
        """Phase 3: 标签一致性检查"""
        print("\n🏷️ Phase 3: 标签一致性检查")
        print("-" * 50)

        self.results["phases"]["tags"] = {}
        cats_to_check = {category: CATEGORIES[category]} if category else CATEGORIES

        for cat_id, cat_info in cats_to_check.items():
            cat_path = ARTIFACTS_ROOT / cat_id
            if not cat_path.exists():
                continue

            valid_tags = set(cat_info["tags"])
            files_checked = 0
            files_ok = 0
            issues = []

            for md_file in cat_path.rglob("*.md"):
                if md_file.name == "index.json":
                    continue

                files_checked += 1
                self.results["statistics"]["total_files"] += 1

                try:
                    content = md_file.read_text(encoding="utf-8")
                    frontmatter = self.extract_frontmatter(content)
                    file_tags = frontmatter.get("tags", [])

                    # 检查标签
                    if not file_tags:
                        issues.append({
                            "file": str(md_file.relative_to(ARTIFACTS_ROOT)),
                            "issue": "缺少tags",
                            "status": "missing_tags"
                        })
                    elif not any(t in valid_tags for t in file_tags):
                        issues.append({
                            "file": str(md_file.relative_to(ARTIFACTS_ROOT)),
                            "issue": f"标签错误: {file_tags}",
                            "status": "wrong_tags",
                            "expected": list(valid_tags)
                        })
                    else:
                        files_ok += 1
                        self.results["statistics"]["aligned"] += 1

                except Exception as e:
                    issues.append({
                        "file": str(md_file.relative_to(ARTIFACTS_ROOT)),
                        "issue": f"读取失败: {e}",
                        "status": "read_error"
                    })

            self.results["phases"]["tags"][cat_id] = {
                "files_checked": files_checked,
                "files_ok": files_ok,
                "issues": issues,
                "alignment_rate": files_ok / files_checked if files_checked > 0 else 100
            }

            # 报告问题
            for issue in issues:
                self.results["issues"].append({
                    "phase": "tags",
                    "severity": "LOW",
                    "category": cat_id,
                    "file": issue["file"],
                    "issue": issue["issue"],
                    "fix_action": "fix_tags" if issue["status"] in ["missing_tags", "wrong_tags"] else "manual"
                })

            rate = self.results["phases"]["tags"][cat_id]["alignment_rate"] * 100
            print(f"  {'✅' if rate == 100 else '⚠️'} {cat_id}: {files_ok}/{files_checked} ({rate:.0f}%)")

    def phase4_frontmatter(self, category: Optional[str] = None):
        """Phase 4: frontmatter完整性检查"""
        print("\n📝 Phase 4: frontmatter完整性检查")
        print("-" * 50)

        self.results["phases"]["frontmatter"] = {}
        cats_to_check = {category: CATEGORIES[category]} if category else CATEGORIES

        for cat_id in cats_to_check:
            cat_path = ARTIFACTS_ROOT / cat_id
            if not cat_path.exists():
                continue

            files_checked = 0
            files_ok = 0
            issues = []

            for md_file in cat_path.rglob("*.md"):
                if md_file.name == "index.json":
                    continue

                files_checked += 1

                try:
                    content = md_file.read_text(encoding="utf-8")
                    fm = self.extract_frontmatter(content)

                    required_fields = ["title", "department", "type", "tags", "status"]
                    missing = [f for f in required_fields if f not in fm]

                    if missing:
                        issues.append({
                            "file": str(md_file.relative_to(ARTIFACTS_ROOT)),
                            "missing": missing
                        })
                    else:
                        files_ok += 1

                except Exception as e:
                    issues.append({
                        "file": str(md_file.relative_to(ARTIFACTS_ROOT)),
                        "error": str(e)
                    })

            self.results["phases"]["frontmatter"][cat_id] = {
                "files_checked": files_checked,
                "files_ok": files_ok,
                "issues": issues
            }

            for issue in issues:
                self.results["issues"].append({
                    "phase": "frontmatter",
                    "severity": "MEDIUM",
                    "category": cat_id,
                    "file": issue["file"],
                    "issue": f"缺少字段: {issue.get('missing', issue.get('error'))}",
                    "fix_action": "add_frontmatter"
                })

            print(f"  {'✅' if files_ok == files_checked else '⚠️'} {cat_id}: {files_ok}/{files_checked} 完整")

    def extract_frontmatter(self, content: str) -> Dict[str, Any]:
        """提取YAML frontmatter"""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    import yaml
                    return yaml.safe_load(parts[1]) or {}
                except:
                    return {}
        return {}

    def compute_statistics(self):
        """计算统计信息"""
        total = self.results["statistics"]["total_files"]
        aligned = self.results["statistics"]["aligned"]

        self.results["statistics"]["alignment_rate"] = (
            aligned / total * 100 if total > 0 else 100.0
        )
        self.results["statistics"]["issues_count"] = len(self.results["issues"])

    def auto_fix(self):
        """自动修复"""
        print("\n🔧 自动修复")
        print("-" * 50)

        fixes_applied = []

        for issue in self.results["issues"]:
            fix_result = self.apply_fix(issue)
            if fix_result:
                fixes_applied.append(fix_result)

        self.results["statistics"]["fixed"] = len(fixes_applied)
        self.results["fixes"] = fixes_applied

        print(f"\n  ✅ 已修复 {len(fixes_applied)} 项")

    def apply_fix(self, issue: Dict) -> Optional[Dict]:
        """应用单个修复"""
        action = issue.get("fix_action")
        cat_id = issue.get("category")
        file_path = issue.get("file")

        if not cat_id:
            return None

        try:
            if action == "create_directory":
                cat_path = ARTIFACTS_ROOT / cat_id
                cat_path.mkdir(parents=True, exist_ok=True)
                self.rebuild_index(cat_id)
                return {"action": "created_directory", "target": cat_id}

            elif action == "rebuild_index":
                self.rebuild_index(cat_id)
                return {"action": "rebuilt_index", "target": cat_id}

            elif action in ["fix_tags", "add_frontmatter"]:
                if file_path:
                    full_path = ARTIFACTS_ROOT / file_path
                    if full_path.exists():
                        self.fix_file_tags(full_path, cat_id)
                        return {"action": "fixed_file", "target": file_path}

            elif action == "manual":
                return None

        except Exception as e:
            print(f"  ❌ 修复失败: {issue.get('issue')} - {e}")

        return None

    def fix_file_tags(self, file_path: Path, category: str):
        """修复文件标签"""
        valid_tags = CATEGORIES[category]["tags"]
        content = file_path.read_text(encoding="utf-8")
        fm = self.extract_frontmatter(content)

        # 确保有frontmatter
        if not content.startswith("---"):
            title = file_path.stem.replace("_", " ").title()
            new_fm = f"""---
title: "{title}"
department: knowledge
type: knowledge_article
tags: {valid_tags}
status: active
---

"""
            content = new_fm + content
        else:
            parts = content.split("---", 2)
            fm_text = parts[1]

            # 添加/更新tags
            if "tags:" in fm_text:
                fm_text = re.sub(r"tags:\s*\[.*?\]", f"tags: {valid_tags}", fm_text)
            else:
                fm_text = fm_text.rstrip() + f"\ntags: {valid_tags}\n"

            # 确保其他必需字段
            if "department:" not in fm_text:
                fm_text = fm_text.rstrip() + "\ndepartment: knowledge\n"
            if "type:" not in fm_text:
                fm_text = fm_text.rstrip() + "\ntype: knowledge_article\n"
            if "status:" not in fm_text:
                fm_text = fm_text.rstrip() + "\nstatus: active\n"

            content = "---" + fm_text + "---" + parts[2]

        file_path.write_text(content, encoding="utf-8")

    def rebuild_index(self, category: str):
        """重建索引文件"""
        cat_path = ARTIFACTS_ROOT / category
        if not cat_path.exists():
            return

        artifacts = []
        for md_file in cat_path.rglob("*.md"):
            if md_file.name == "index.json":
                continue

            fm = self.extract_frontmatter(md_file.read_text(encoding="utf-8"))

            artifacts.append({
                "artifact_id": md_file.stem,
                "title": fm.get("title", md_file.stem.replace("_", " ").title()),
                "filename": str(md_file.relative_to(cat_path)),
                "tags": fm.get("tags", CATEGORIES[category]["tags"]),
                "frontmatter": {
                    "department": fm.get("department", "knowledge"),
                    "type": fm.get("type", "knowledge_article"),
                    "status": fm.get("status", "active")
                },
                "status": fm.get("status", "active")
            })

        index_data = {
            "category": category,
            "label": CATEGORIES[category]["label"],
            "last_updated": datetime.now().isoformat(),
            "artifacts": artifacts,
            "statistics": {
                "total_artifacts": len(artifacts)
            }
        }

        index_path = cat_path / "index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)

    def verify_fixes(self):
        """验证修复"""
        print("\n🔍 验证修复")
        print("-" * 50)

        # 重新检查所有分类
        for cat_id in CATEGORIES:
            cat_path = ARTIFACTS_ROOT / cat_id
            if not cat_path.exists():
                continue

            valid_tags = set(CATEGORIES[cat_id]["tags"])
            issues_found = 0

            for md_file in cat_path.rglob("*.md"):
                if md_file.name == "index.json":
                    continue

                content = md_file.read_text(encoding="utf-8")
                fm = self.extract_frontmatter(content)
                file_tags = fm.get("tags", [])

                if not file_tags or not any(t in valid_tags for t in file_tags):
                    issues_found += 1

            status = "✅ 已修复" if issues_found == 0 else f"⚠️ 还有{issues_found}个问题"
            print(f"  {status}: {cat_id}")

    def generate_report(self, mode: str) -> str:
        """生成报告"""
        stats = self.results["statistics"]

        report = f"""# 前后端产物对齐审计报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**执行模式**: {mode}
**后端目录**: {ARTIFACTS_ROOT}

---

## 一、总体状态

| 指标 | 数值 |
|:---|:---|
| 总文件数 | {stats['total_files']} |
| 已对齐文件 | {stats['aligned']} |
| 对齐率 | {stats.get('alignment_rate', 0):.1f}% |
| 发现问题 | {stats['issues_count']} |
| 已修复 | {stats.get('fixed', 0)} |

---

## 二、各分类状态

| 分类 | 目录 | 索引 | 标签 | frontmatter |
|:---|:---:|:---:|:---:|:---:|
"""

        for cat_id, cat_info in CATEGORIES.items():
            dir_status = self.results["phases"]["directory"].get(cat_id, {}).get("exists", False)
            idx_status = self.results["phases"]["index"].get(cat_id, {}).get("valid", False)
            tags_data = self.results["phases"]["tags"].get(cat_id, {})
            fm_data = self.results["phases"]["frontmatter"].get(cat_id, {})

            tags_rate = tags_data.get("alignment_rate", 1) * 100
            fm_rate = (fm_data.get("files_ok", 0) / fm_data.get("files_checked", 1) * 100) if fm_data.get("files_checked", 0) > 0 else 100

            report += f"| {cat_info['label']} | {'✅' if dir_status else '❌'} | {'✅' if idx_status else '❌'} | {tags_rate:.0f}% | {fm_rate:.0f}% |\n"

        # 问题列表
        if self.results["issues"]:
            report += f"\n## 三、发现问题 ({len(self.results['issues'])}项)\n\n"
            for i, issue in enumerate(self.results["issues"], 1):
                severity_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(issue["severity"], "⚪")
                report += f"{i}. {severity_icon} [{issue['severity']}] {issue['issue']}\n"
                if "file" in issue:
                    report += f"   - 文件: `{issue['file']}`\n"
                report += f"   - 修复动作: `{issue.get('fix_action', 'manual')}`\n"

        # 修复记录
        if self.results["fixes"]:
            report += f"\n## 四、已修复 ({len(self.results['fixes'])}项)\n\n"
            for fix in self.results["fixes"]:
                report += f"- ✅ `{fix['action']}`: {fix['target']}\n"

        report += f"\n---\n\n**报告生成器**: artifact-alignment-manager v2.0\n"

        return report

    def save_report(self, report: str):
        """保存报告"""
        filename = f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path = AUDIT_DIR / filename
        report_path.write_text(report, encoding="utf-8")

        # 同时保存最新报告
        latest_path = AUDIT_DIR / "latest.md"
        latest_path.write_text(report, encoding="utf-8")

        print(f"\n📄 报告已保存: {report_path}")
        print(f"📄 最新报告: {latest_path}")

    def print_summary(self, mode: str):
        """打印摘要"""
        stats = self.results["statistics"]

        print("\n" + "=" * 70)
        print("📊 执行摘要")
        print("=" * 70)
        print(f"总文件数: {stats['total_files']}")
        print(f"对齐文件: {stats['aligned']}")
        print(f"对齐率: {stats.get('alignment_rate', 0):.1f}%")
        print(f"发现问题: {stats['issues_count']}")

        if mode in ["fix", "full"]:
            print(f"已修复: {stats.get('fixed', 0)}")

        if self.results["issues"] and mode == "check":
            print(f"\n💡 提示: 运行 --fix 模式自动修复问题")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="前后端产物对齐管理器 v2.0")
    parser.add_argument("--check", action="store_true", help="仅检测模式")
    parser.add_argument("--fix", action="store_true", help="自动修复模式")
    parser.add_argument("--full", action="store_true", help="完整模式(check+fix+verify)")
    parser.add_argument("--audit", action="store_true", help="审计模式(生成报告)")
    parser.add_argument("--category", type=str, help="指定分类")

    args = parser.parse_args()

    # 确定模式
    mode = "check"
    if args.full:
        mode = "full"
    elif args.fix:
        mode = "fix"
    elif args.audit:
        mode = "audit"

    manager = AlignmentManager()
    results = manager.run(mode=mode, category=args.category)

    # 返回退出码
    if results["statistics"]["issues_count"] > 0 and mode == "check":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
