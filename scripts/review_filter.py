#!/usr/bin/env python3
"""
review_filter.py — 多级审查过滤管道 (Three-Stage Filter Pipeline)

对标: Ellipsis 的多级过滤架构
用途: 对 E2 / A3-Review 的原始审查输出执行三道过滤:
  Stage 1: 置信度过滤 — 按严重等级保留高置信度发现
  Stage 2: 去重合并 — 同一文件同一问题的多条发现合并
  Stage 3: 幻觉检测 — 交叉验证引用的代码行/文件是否存在

用法:
  # 管道模式: 原始JSON → 过滤后JSON
  python3 review_filter.py --input review_raw.json --output review_filtered.json

  # 管道模式: 原始Markdown → 过滤后Markdown
  python3 review_filter.py --input review_raw.md --output review_filtered.md

  # 预览模式: 只看过滤效果统计
  python3 review_filter.py --input review_raw.json --stats
"""

import json
import sys
import os
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─── 数据模型 ──────────────────────────────────────────────────────────

@dataclass
class Finding:
    """单条审查发现"""
    id: str = ""
    severity: str = "MEDIUM"       # CRITICAL / HIGH / MEDIUM / LOW / SUGGESTION
    category: str = ""             # security / bug / perf / quality / style / test
    title: str = ""
    description: str = ""
    file_path: str = ""            # 引用文件路径
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    evidence: str = ""             # 证据片段
    confidence: float = 0.0        # 0.0 - 1.0
    source_agent: str = ""         # E2 / A3-Review / manual

@dataclass
class FilterReport:
    """过滤管道输出"""
    original_count: int = 0
    after_confidence: int = 0
    after_dedupe: int = 0
    after_hallucination: int = 0
    removed_confidence: list = field(default_factory=list)
    removed_dedupe: list = field(default_factory=list)
    removed_hallucination: list = field(default_factory=list)
    findings: list = field(default_factory=list)


# ─── 置信度阈值配置 ──────────────────────────────────────────────────

CONFIDENCE_THRESHOLDS = {
    "CRITICAL":  0.50,   # 致命问题: 置信度 > 50% 即保留
    "HIGH":      0.65,   # 严重问题: 置信度 > 65% 保留
    "MEDIUM":    0.75,   # 中等问题: 置信度 > 75% 保留
    "LOW":       0.85,   # 轻微问题: 置信度 > 85% 保留
    "SUGGESTION": 0.90,  # 建议: 置信度 > 90% 保留
}

DEFAULT_CONFIDENCE = 0.80  # 未标注严重等级时的默认阈值


# ─── Stage 1: 置信度过滤 ──────────────────────────────────────────────

def filter_by_confidence(findings: list[Finding],
                         thresholds: dict[str, float] = None) -> tuple[list[Finding], list[Finding]]:
    """按置信度阈值过滤"""
    if thresholds is None:
        thresholds = CONFIDENCE_THRESHOLDS

    passed = []
    removed = []

    for f in findings:
        threshold = thresholds.get(f.severity.upper(), DEFAULT_CONFIDENCE)
        if f.confidence >= threshold:
            passed.append(f)
        else:
            removed.append(f)

    return passed, removed


# ─── Stage 2: 去重合并 ────────────────────────────────────────────────

def dedupe_findings(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """合并重复发现（同一文件 + 同类问题）"""
    seen = {}  # key: (file_path, category) → Finding
    removed = []

    for f in findings:
        key = (f.file_path, f.category)

        if key in seen:
            existing = seen[key]
            # 合并: 保留更高严重度、更高置信度
            severity_rank = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "SUGGESTION": 1}

            if severity_rank.get(f.severity.upper(), 0) > severity_rank.get(existing.severity.upper(), 0):
                existing.severity = f.severity

            if f.confidence > existing.confidence:
                existing.confidence = f.confidence

            # 合并描述
            existing.description += f"\n  [合并] {f.title}: {f.description}"
            removed.append(f)
        else:
            seen[key] = f

    return list(seen.values()), removed


# ─── Stage 3: 幻觉检测 ────────────────────────────────────────────────

def validate_hallucination(findings: list[Finding],
                           project_root: str = ".") -> tuple[list[Finding], list[Finding]]:
    """交叉验证引用的文件/行号是否存在"""
    passed = []
    removed = []

    project_path = Path(project_root).expanduser().resolve()

    for f in findings:
        if not f.file_path:
            passed.append(f)
            continue

        # 解析文件路径
        ref_path = project_path / f.file_path.lstrip("/")

        if not ref_path.exists():
            # 尝试相对路径
            alt_path = Path(f.file_path)
            if not alt_path.exists():
                removed.append(f)
                continue

        # 如果引用了行号，检查行号是否在文件范围内
        if f.line_start and f.line_start > 0:
            try:
                with open(ref_path, 'r') as fh:
                    total_lines = sum(1 for _ in fh)
                if f.line_start > total_lines:
                    # 行号超出范围 — 可能是幻觉
                    f.description += f"\n  [注意] 引用的行号 {f.line_start} 超出文件范围（共 {total_lines} 行）"
                    f.confidence = max(0.3, f.confidence - 0.2)  # 降低置信度
            except (IOError, OSError):
                pass  # 读不了文件就放行

        passed.append(f)

    return passed, removed


# ─── 主管道 ────────────────────────────────────────────────────────────

def run_pipeline(findings: list[Finding],
                 project_root: str = ".",
                 thresholds: dict = None) -> FilterReport:
    """运行完整的三级过滤管道"""
    report = FilterReport(original_count=len(findings))
    current = findings[:]

    # Stage 1: 置信度过滤
    current, removed_c = filter_by_confidence(current, thresholds)
    report.after_confidence = len(current)
    report.removed_confidence = [f.title for f in removed_c]

    # Stage 2: 去重合并
    current, removed_d = dedupe_findings(current)
    report.after_dedupe = len(current)
    report.removed_dedupe = [f.title for f in removed_d]

    # Stage 3: 幻觉检测
    current, removed_h = validate_hallucination(current, project_root)
    report.after_hallucination = len(current)
    report.removed_hallucination = [f.title for f in removed_h]

    report.findings = current
    return report


# ─── Markdown 解析（回退方案） ───────────────────────────────────────

def parse_markdown_findings(md_text: str) -> list[Finding]:
    """从 Markdown 审查报告中提取发现"""
    findings = []

    # 按章节提取
    sections = re.split(r'^###?\s+', md_text, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue

        finding = Finding()

        # 检测严重等级
        for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if level in section.upper():
                finding.severity = level
                break

        # 检测类别
        for cat in ["Security", "Bug", "Performance", "Quality", "Test", "Suggestion"]:
            if cat.lower() in section.lower():
                finding.category = cat.upper()
                break

        # 提取文件路径
        file_matches = re.findall(r'`([^`]+\.[a-z]+)`', section)
        if file_matches:
            finding.file_path = file_matches[0]

        # 提取行号
        line_match = re.search(r':(\d+)', section)
        if line_match:
            finding.line_start = int(line_match.group(1))

        # 标题 = 章节第一行
        lines = section.strip().split('\n')
        if lines:
            finding.title = lines[0][:100]

        finding.description = section[:500]

        if finding.title:
            findings.append(finding)

    return findings


# ─── 统计输出 ──────────────────────────────────────────────────────────

def format_stats(report: FilterReport) -> str:
    """格式化过滤统计"""
    total_removed = len(report.removed_confidence) + len(report.removed_dedupe) + len(report.removed_hallucination)

    lines = [
        "╔══════════════════════════════════════════════╗",
        "║        审查过滤管道 — 效果统计               ║",
        "╠══════════════════════════════════════════════╣",
        f"║  原始发现:        {report.original_count:>4} 条           ║",
        f"║  Stage 1 置信度:  -{len(report.removed_confidence):>3} 条 (阈值15-50%)  ║",
        f"║  Stage 2 去重:    -{len(report.removed_dedupe):>3} 条           ║",
        f"║  Stage 3 幻觉:    -{len(report.removed_hallucination):>3} 条           ║",
        "╠══════════════════════════════════════════════╣",
        f"║  最终有效发现:    {report.after_hallucination:>4} 条           ║",
        f"║  总过滤率:        {total_removed/report.original_count*100:>5.1f}%            ║",
        "╚══════════════════════════════════════════════╝",
    ]
    return "\n".join(lines)


# ─── CLI 入口 ──────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="多级审查过滤管道")
    parser.add_argument("--input", "-i", required=True, help="输入文件 (.json 或 .md)")
    parser.add_argument("--output", "-o", help="输出文件（可选）")
    parser.add_argument("--project-root", default=".", help="项目根目录（幻觉检测用）")
    parser.add_argument("--stats", action="store_true", help="只输出统计，不写文件")
    args = parser.parse_args()

    # 读取输入
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ 输入文件不存在: {args.input}")
        sys.exit(1)

    content = input_path.read_text(encoding="utf-8")

    # 解析为 Finding 列表
    if args.input.endswith(".json"):
        try:
            raw_data = json.loads(content)
            if isinstance(raw_data, list):
                findings = [Finding(**item) for item in raw_data]
            elif isinstance(raw_data, dict) and "findings" in raw_data:
                findings = [Finding(**item) for item in raw_data["findings"]]
            else:
                print("❌ JSON 格式不支持：需要 findings 列表")
                sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")
            sys.exit(1)
    else:
        findings = parse_markdown_findings(content)
        print(f"📝 从 Markdown 解析出 {len(findings)} 条发现")

    # 运行管道
    report = run_pipeline(findings, args.project_root)

    # 输出
    if args.stats:
        print(format_stats(report))
        return

    if report.removed_confidence:
        print(f"📊 Stage 1 置信度过滤: 移除 {len(report.removed_confidence)} 条")
        for t in report.removed_confidence:
            print(f"   ❌ {t[:80]}")

    if report.removed_dedupe:
        print(f"📊 Stage 2 去重合并: 合并 {len(report.removed_dedupe)} 条")
        for t in report.removed_dedupe[:5]:
            print(f"   🔄 {t[:80]}")

    if report.removed_hallucination:
        print(f"📊 Stage 3 幻觉检测: 移除 {len(report.removed_hallucination)} 条")
        for t in report.removed_hallucination:
            print(f"   👻 {t[:80]}")

    # 输出过滤结果
    if args.output:
        output = {
            "filter_stats": {
                "original": report.original_count,
                "after_confidence": report.after_confidence,
                "after_dedupe": report.after_dedupe,
                "after_hallucination": report.after_hallucination,
            },
            "findings": [
                {
                    "id": f.id,
                    "severity": f.severity,
                    "category": f.category,
                    "title": f.title,
                    "description": f.description[:300],
                    "file_path": f.file_path,
                    "line_start": f.line_start,
                    "confidence": f.confidence,
                }
                for f in report.findings
            ]
        }
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 过滤后写入: {args.output} ({len(report.findings)} 条)")
    else:
        print(format_stats(report))


if __name__ == "__main__":
    main()
