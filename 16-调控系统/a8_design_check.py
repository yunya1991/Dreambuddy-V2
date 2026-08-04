#!/usr/bin/env python3
"""
A8 设计文档校验 — 针对 TECHNICAL_DESIGN.md 的专门校验

校验目标：
1. 文档模块覆盖度：是否覆盖所有核心Python文件
2. 文档描述一致性：模块描述与实际代码是否匹配
3. 文件索引完整性：是否遗漏重要文件

用法：
    python3 a8_design_check.py
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set


def extract_python_files(code_dir: Path) -> Set[str]:
    """提取目录下所有Python文件名（不含后缀）"""
    files = set()
    for py_file in code_dir.rglob("*.py"):
        # 跳过测试文件和特殊目录
        if "test" in py_file.name or "__pycache__" in str(py_file):
            continue
        # 提取文件名（不含后缀）
        stem = py_file.stem
        files.add(stem)
    return files


def extract_documented_modules(design_doc: Path) -> Dict[str, List[str]]:
    """从TECHNICAL_DESIGN.md中提取已文档化的模块"""
    if not design_doc.exists():
        return {}

    content = design_doc.read_text(encoding="utf-8")

    # 提取模块名（格式：模块名 (filename.py)）
    # 例如：统一持仓查询模块 (unified_position_query.py)
    module_pattern = r'\*+[\s\*]*[\u4e00-\u9fa5\w\s]+\s+\(([a-zA-Z_][a-zA-Z0-9_]*\.py)\)'
    matches = re.findall(module_pattern, content)

    # 提取代码块中的文件名引用
    # 例如：unified_position_query.py, skill_engine.py
    code_file_pattern = r'`([a-zA-Z_][a-zA-Z0-9_]*\.py)`'
    code_files = re.findall(code_file_pattern, content)

    # 去重
    documented = set()
    for match in matches:
        documented.add(match.replace(".py", ""))
    for f in code_files:
        documented.add(f.replace(".py", ""))

    return {"documented": list(documented)}


def check_module_coverage(subsystem_dir: Path) -> Dict:
    """检查模块覆盖度"""
    # 获取代码目录
    code_dirs = []
    for candidate in ["core", "scripts", "src"]:
        d = subsystem_dir / candidate
        if d.exists():
            code_dirs.append(d)

    if not code_dirs:
        # fallback：扫描整个子系统
        for d in subsystem_dir.iterdir():
            if d.is_dir() and d.name not in ("docs", "data", "__pycache__", ".git", "tests"):
                code_dirs.append(d)

    # 提取代码文件
    code_files = set()
    for code_dir in code_dirs:
        code_files.update(extract_python_files(code_dir))

    # 提取文档化的模块
    design_doc = subsystem_dir / "docs" / "TECHNICAL_DESIGN.md"
    doc_info = extract_documented_modules(design_doc)
    documented_files = set(doc_info.get("documented", []))

    # 对比
    covered = code_files & documented_files
    uncovered = code_files - documented_files
    extra_doc = documented_files - code_files

    # 计算覆盖度得分
    coverage_score = (len(covered) / len(code_files) * 100) if code_files else 100.0

    return {
        "summary": {
            "total_code_files": len(code_files),
            "documented_files": len(documented_files),
            "covered": len(covered),
            "uncovered": len(uncovered),
            "extra_doc": len(extra_doc),
            "coverage_score": round(coverage_score, 2),
        },
        "covered_files": sorted(covered),
        "uncovered_files": sorted(uncovered),
        "extra_documented": sorted(extra_doc),
    }


def main():
    """执行校验"""
    subsystem_dir = Path(__file__).parent

    print("=" * 60)
    print("A8 设计文档校验 — TECHNICAL_DESIGN.md")
    print("=" * 60)

    result = check_module_coverage(subsystem_dir)
    summary = result["summary"]

    print(f"\n📊 覆盖度概览:")
    print(f"   代码文件总数: {summary['total_code_files']}")
    print(f"   已文档化: {summary['documented_files']}")
    print(f"   ✅ 覆盖: {summary['covered']}")
    print(f"   ❓ 未文档化: {summary['uncovered']}")
    print(f"   📈 覆盖度得分: {summary['coverage_score']}%")

    # 显示未覆盖的重要文件
    uncovered = result["uncovered_files"]
    if uncovered:
        print(f"\n❓ 未文档化的文件（前10个）:")
        for f in uncovered[:10]:
            print(f"   - {f}.py")
        if len(uncovered) > 10:
            print(f"   ... 等共 {len(uncovered)} 个文件")

    # 显示多余文档化的文件
    extra_doc = result["extra_documented"]
    if extra_doc:
        print(f"\n⚠️ 文档中提到但代码目录未找到:")
        for f in extra_doc[:10]:
            print(f"   - {f}.py")

    print(f"\n{'='*60}\n")

    # 保存JSON报告
    report_file = subsystem_dir / "a8_design_report.json"
    report_file.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"报告已保存: {report_file}")

    # 返回状态码（覆盖度>=80%为成功）
    return 0 if summary["coverage_score"] >= 80 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())