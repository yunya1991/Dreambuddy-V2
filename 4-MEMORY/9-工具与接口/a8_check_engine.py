#!/usr/bin/env python3
"""
A8 理论实践校验引擎 — 认知闭环的"观察"节点

功能：对比 API_SPEC.md 中声明的接口与实际代码中的函数定义，
      检测文档-代码不一致，生成校验报告。
      
      本引擎在认知架构中承担"观察（Observation）"角色：
      1. 作为认知闭环的第五步，产生实践层的观察结果
      2. 为 BayesianMemoryUpdater 提供输入，驱动记忆置信度更新
      3. 连接"实践层(代码)"与"认知层(记忆系统)"的关键桥梁

用法：
    python3 a8_check_engine.py /path/to/subsystem

输出：
    控制台报告 + a8_report.json
    
集成：
    与 auto_update_trigger.py 集成，形成完整的认知闭环流程
    与 bayesian_memory_updater.py 集成，实现贝叶斯记忆更新
"""

import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple


@dataclass
class A8Report:
    """A8 校验报告"""
    subsystem: str
    doc_functions: Set[str] = field(default_factory=set)
    code_functions: Set[str] = field(default_factory=set)
    matched: List[str] = field(default_factory=list)
    doc_only: List[str] = field(default_factory=list)   # 文档有，代码没有
    code_only: List[str] = field(default_factory=list)  # 代码有，文档没有
    score: float = 0.0  # 一致性得分 0~100

    def to_dict(self) -> dict:
        return {
            "subsystem": self.subsystem,
            "summary": {
                "doc_declared": len(self.doc_functions),
                "code_implemented": len(self.code_functions),
                "matched": len(self.matched),
                "doc_only": len(self.doc_only),
                "code_only": len(self.code_only),
                "consistency_score": round(self.score, 2),
            },
            "matched_functions": sorted(self.matched),
            "doc_only_functions": sorted(self.doc_only),
            "code_only_functions": sorted(self.code_only),
        }


def extract_functions_from_spec(spec_path: Path) -> Set[str]:
    """从 API_SPEC.md 中提取声明的函数名。"""
    functions = set()
    if not spec_path.exists():
        return functions

    content = spec_path.read_text(encoding="utf-8")

    # 策略1: 匹配 `def function_name(` 代码块
    # API_SPEC 中常用 ```python\ndef name(...``` 展示签名
    code_blocks = re.findall(r"```python\n(.*?)```", content, re.DOTALL)
    for block in code_blocks:
        for line in block.splitlines():
            match = re.match(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", line)
            if match:
                functions.add(match.group(1))

    # 策略2: 匹配行内 `function_name(` 引用（接口概览表格）
    # 例如: `fetch_all_positions(systems)`, `SkillEngine.execute()`
    inline_funcs = re.findall(r"`([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", content)
    functions.update(inline_funcs)

    # 策略3: 匹配类方法引用 Class.method(
    class_methods = re.findall(r"`([a-zA-Z_][a-zA-Z0-9_]*\.\w+)\s*\(", content)
    for cm in class_methods:
        functions.add(cm)

    return functions


def extract_functions_from_code(code_dir: Path) -> Set[str]:
    """从 Python 代码目录中提取所有顶层函数和类方法定义。"""
    functions = set()

    for py_file in code_dir.rglob("*.py"):
        # 跳过测试文件和 __pycache__
        if "test" in py_file.name or "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # 跳过私有函数（单下划线开头但不包括 __init__ 等 dunder）
                if node.name.startswith("_") and not node.name.startswith("__"):
                    continue
                functions.add(node.name)
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        # 跳过私有方法
                        if item.name.startswith("_") and not item.name.startswith("__"):
                            continue
                        # 记录为 Class.method 格式，也记录裸方法名
                        functions.add(f"{node.name}.{item.name}")
                        functions.add(item.name)

    return functions


def calculate_score(report: A8Report) -> float:
    """计算一致性得分。"""
    total_doc = len(report.doc_functions)
    total_code = len(report.code_functions)
    matched = len(report.matched)

    if total_doc == 0 and total_code == 0:
        return 100.0

    # 得分 = (匹配数 / max(文档声明数, 代码实现数)) * 100
    denominator = max(total_doc, total_code)
    if denominator == 0:
        return 100.0

    return (matched / denominator) * 100


def run_a8_check(subsystem_dir: Path) -> A8Report:
    """对指定子系统执行 A8 校验。"""
    subsystem_name = subsystem_dir.name
    spec_path = subsystem_dir / "docs" / "API_SPEC.md"

    # 确定代码目录
    code_dirs = []
    for candidate in ["core", "scripts", "src", subsystem_dir.name.split("-")[-1]]:
        d = subsystem_dir / candidate
        if d.exists() and d.is_dir():
            code_dirs.append(d)

    if not code_dirs:
        #  fallback: 扫描整个子系统（排除 docs/ data/ 等）
        for d in subsystem_dir.iterdir():
            if d.is_dir() and d.name not in ("docs", "data", "__pycache__", ".git"):
                code_dirs.append(d)

    report = A8Report(subsystem=subsystem_name)

    # 提取文档函数
    report.doc_functions = extract_functions_from_spec(spec_path)

    # 提取代码函数
    report.code_functions = set()
    for code_dir in code_dirs:
        report.code_functions.update(extract_functions_from_code(code_dir))

    # 对比
    report.matched = sorted(report.doc_functions & report.code_functions)
    report.doc_only = sorted(report.doc_functions - report.code_functions)
    report.code_only = sorted(report.code_functions - report.doc_functions)
    report.score = calculate_score(report)

    return report


def print_report(report: A8Report) -> None:
    """打印校验报告到控制台。"""
    print(f"\n{'='*60}")
    print(f"A8 校验报告 — {report.subsystem}")
    print(f"{'='*60}")

    summary = report.to_dict()["summary"]
    print(f"\n📊 概览:")
    print(f"   文档声明函数: {summary['doc_declared']}")
    print(f"   代码实现函数: {summary['code_implemented']}")
    print(f"   ✅ 匹配: {summary['matched']}")
    print(f"   ⚠️  文档超前(未实现): {summary['doc_only']}")
    print(f"   ❓ 代码超前(未文档化): {summary['code_only']}")
    print(f"   📈 一致性得分: {summary['consistency_score']}%")

    if report.doc_only:
        print(f"\n⚠️  文档声明但未在代码中找到:")
        for f in report.doc_only[:10]:
            print(f"   - {f}")
        if len(report.doc_only) > 10:
            print(f"   ... 等共 {len(report.doc_only)} 项")

    if report.code_only:
        print(f"\n❓ 代码实现但未在文档中找到:")
        for f in report.code_only[:10]:
            print(f"   - {f}")
        if len(report.code_only) > 10:
            print(f"   ... 等共 {len(report.code_only)} 项")

    print(f"\n{'='*60}\n")


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 a8_check_engine.py <子系统目录>")
        print("示例: python3 a8_check_engine.py /path/to/16-调控系统")
        return 1

    subsystem_dir = Path(sys.argv[1])
    if not subsystem_dir.exists():
        print(f"错误: 目录不存在: {subsystem_dir}")
        return 1

    report = run_a8_check(subsystem_dir)
    print_report(report)

    # 保存 JSON 报告
    report_file = subsystem_dir / "a8_report.json"
    report_file.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    print(f"报告已保存: {report_file}")

    return 0 if report.score >= 80 else 1


if __name__ == "__main__":
    sys.exit(main())
