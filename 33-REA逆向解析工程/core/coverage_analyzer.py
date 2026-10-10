"""测试覆盖分析 — 解析覆盖率报告，识别未覆盖行。

支持的报告格式：
- coverage.xml (Cobertura XML, 由 pytest-cov / coverage.py 生成)

能力：
- 计算行覆盖率和分支覆盖率
- 每个文件的覆盖率统计
- 未覆盖行号列表
- 每条结论带 Evidence（来源 + known_gaps）
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any

from .evidence import Evidence


def analyze_coverage(target: str) -> dict[str, Any]:
    """分析目标目录的测试覆盖率。

    Args:
        target: 目录路径（查找 coverage.xml）

    Returns:
        {
            "files": [{filename, line_rate, branch_rate, lines: [{number, hits}]}],
            "line_rate": float,
            "branch_rate": float,
            "summary": str,
            "evidence": [Evidence],
        }
    """
    result: dict[str, Any] = {
        "files": [],
        "line_rate": 0.0,
        "branch_rate": 0.0,
        "summary": "",
        "evidence": [],
    }

    if not os.path.isdir(target):
        result["evidence"].append(Evidence(
            result=f"目标不是目录: {target}",
            provenance={"target": target},
            confidence=1.0,
            known_gaps=["无法分析非目录路径"],
            level="observation",
        ))
        return result

    # 查找 coverage.xml
    coverage_xml = os.path.join(target, "coverage.xml")
    if not os.path.isfile(coverage_xml):
        # 也查找 .coverage (SQLite) 但不直接解析
        result["evidence"].append(Evidence(
            result=f"未找到 coverage.xml: {coverage_xml}",
            provenance={"target": target},
            confidence=1.0,
            known_gaps=[
                "未检测到 coverage.xml，需要先运行 pytest --cov --cov-report=xml",
                ".coverage SQLite 格式未直接解析（需 coverage.py 运行时）",
                "无法评估测试覆盖率",
            ],
            level="unknown",
        ))
        result["summary"] = "未找到覆盖率报告文件"
        return result

    # 解析 XML
    try:
        tree = ET.parse(coverage_xml)
        root = tree.getroot()
    except ET.ParseError as e:
        result["evidence"].append(Evidence(
            result=f"coverage.xml 解析失败: {e}",
            provenance={"file": coverage_xml},
            confidence=1.0,
            known_gaps=["XML 格式错误，无法解析覆盖率数据"],
            level="unknown",
        ))
        result["summary"] = f"coverage.xml 解析失败: {e}"
        return result

    # 提取总体覆盖率
    result["line_rate"] = _safe_float(root.get("line-rate", "0"))
    result["branch_rate"] = _safe_float(root.get("branch-rate", "0"))

    # 提取每个文件的覆盖率
    files: list[dict[str, Any]] = []
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        if not filename:
            continue

        file_info: dict[str, Any] = {
            "filename": filename,
            "name": cls.get("name", os.path.basename(filename)),
            "line_rate": _safe_float(cls.get("line-rate", "0")),
            "branch_rate": _safe_float(cls.get("branch-rate", "0")),
            "lines": [],
        }

        # 提取行级覆盖数据
        lines_elem = cls.find("lines")
        if lines_elem is not None:
            for line in lines_elem.iter("line"):
                file_info["lines"].append({
                    "number": int(line.get("number", "0")),
                    "hits": int(line.get("hits", "0")),
                    "branch": line.get("branch", "false") == "true",
                })

        files.append(file_info)

    result["files"] = files

    # 统计未覆盖行
    total_lines = sum(len(f["lines"]) for f in files)
    uncovered_lines = sum(
        1 for f in files for l in f["lines"] if l["hits"] == 0
    )
    covered_lines = total_lines - uncovered_lines

    result["summary"] = (
        f"测试覆盖: line-rate={result['line_rate']:.1%}, "
        f"branch-rate={result['branch_rate']:.1%} | "
        f"{len(files)} 文件, "
        f"{covered_lines}/{total_lines} 行覆盖, "
        f"{uncovered_lines} 行未覆盖"
    )

    # 构建 Evidence
    result["evidence"] = _build_evidence(
        result, coverage_xml, files, uncovered_lines,
    )

    return result


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _safe_float(value: str) -> float:
    """安全转换字符串为浮点数。"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _build_evidence(
    result: dict[str, Any],
    coverage_xml: str,
    files: list[dict],
    uncovered_count: int,
) -> list[Evidence]:
    """构建覆盖率分析的 Evidence 列表。"""
    evidence: list[Evidence] = []

    evidence.append(Evidence(
        result=(
            f"覆盖率: line={result['line_rate']:.1%}, "
            f"branch={result['branch_rate']:.1%}"
        ),
        provenance={
            "file": coverage_xml,
            "engine": "coverage_xml",
            "format": "cobertura",
        },
        confidence=1.0,
        known_gaps=[
            "行覆盖不等于逻辑覆盖（可能行被执行但分支未完整测试）",
            "分支覆盖率仅统计显式 if/else 分支，不统计三元运算符",
            "未覆盖集成测试/E2E 场景的覆盖率",
            "mock 和 fixture 可能导致虚高覆盖率（测试执行了代码但未验证行为）",
        ],
        level="observation",
    ))

    if uncovered_count > 0:
        evidence.append(Evidence(
            result=f"{uncovered_count} 行未被任何测试覆盖",
            provenance={
                "file": coverage_xml,
                "engine": "coverage_xml",
                "analysis": "uncovered_lines",
            },
            confidence=1.0,
            known_gaps=[
                "未覆盖行可能包含错误处理路径（异常分支）",
                "未覆盖行可能包含调试/日志代码（非核心逻辑）",
                "未覆盖不等于需要覆盖（部分代码可能由设计决定不测试）",
            ],
            level="derivation",
        ))

    # 每个低覆盖率文件生成 Evidence
    for f in files:
        if f["line_rate"] < 0.5 and f["lines"]:
            evidence.append(Evidence(
                result=(
                    f"文件 {f['filename']} 覆盖率偏低: "
                    f"{f['line_rate']:.1%}"
                ),
                provenance={
                    "file": coverage_xml,
                    "source_file": f["filename"],
                    "engine": "coverage_xml",
                    "analysis": "low_coverage_file",
                },
                confidence=0.9,
                known_gaps=[
                    "低覆盖率可能是由于该文件包含难以测试的代码路径",
                    "建议优先补充该文件的测试用例",
                ],
                level="inference",
            ))

    return evidence
