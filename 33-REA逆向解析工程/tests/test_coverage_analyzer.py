"""RED 测试：CoverageAnalyzer — 测试覆盖分析。

测试策略：创建临时 coverage.xml 文件，验证解析逻辑。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.coverage_analyzer import analyze_coverage


# Cobertura XML 格式示例
SAMPLE_COVERAGE_XML = '''<?xml version="1.0" ?>
<coverage version="6.5.0" timestamp="1700000000000" lines-valid="100" lines-covered="80" line-rate="0.8" branches-covered="5" branches-valid="8" branch-rate="0.625" complexity="0">
  <packages>
    <package name="core" line-rate="0.8" branch-rate="0.625" complexity="0">
      <classes>
        <class name="analyzer.py" filename="core/analyzer.py" line-rate="0.9" branch-rate="0.8" complexity="0">
          <lines>
            <line number="1" hits="1"/>
            <line number="5" hits="1"/>
            <line number="10" hits="0"/>
            <line number="15" hits="1"/>
          </lines>
        </class>
        <class name="evidence.py" filename="core/evidence.py" line-rate="0.75" branch-rate="0.5" complexity="0">
          <lines>
            <line number="1" hits="1"/>
            <line number="10" hits="0"/>
            <line number="20" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
    <package name="adapters" line-rate="0.7" branch-rate="0.5" complexity="0">
      <classes>
        <class name="rea_mcp.py" filename="adapters/rea_mcp.py" line-rate="0.7" branch-rate="0.5" complexity="0">
          <lines>
            <line number="1" hits="1"/>
            <line number="5" hits="0"/>
            <line number="10" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
'''


def test_coverage_analyzer_parses_xml():
    """RED: 应解析 coverage.xml 文件。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "coverage.xml")
        Path(f).write_text(SAMPLE_COVERAGE_XML)
        result = analyze_coverage(d)

    assert "files" in result
    assert len(result["files"]) >= 3


def test_coverage_analyzer_calculates_rates():
    """RED: 应计算行覆盖率和分支覆盖率。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "coverage.xml")
        Path(f).write_text(SAMPLE_COVERAGE_XML)
        result = analyze_coverage(d)

    assert "line_rate" in result
    assert 0.0 <= result["line_rate"] <= 1.0
    assert "branch_rate" in result
    assert 0.0 <= result["branch_rate"] <= 1.0


def test_coverage_analyzer_identifies_uncovered_lines():
    """RED: 应识别未覆盖行。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "coverage.xml")
        Path(f).write_text(SAMPLE_COVERAGE_XML)
        result = analyze_coverage(d)

    # 找到 analyzer.py 的未覆盖行
    analyzer_file = [
        f for f in result["files"]
        if "analyzer.py" in f.get("filename", "")
    ]
    assert len(analyzer_file) == 1
    uncovered = [l for l in analyzer_file[0].get("lines", []) if l.get("hits") == 0]
    assert len(uncovered) >= 1
    assert 10 in [l["number"] for l in uncovered]


def test_coverage_analyzer_returns_evidence():
    """RED: 应返回 Evidence 列表。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "coverage.xml")
        Path(f).write_text(SAMPLE_COVERAGE_XML)
        result = analyze_coverage(d)

    assert "evidence" in result
    assert len(result["evidence"]) > 0
    e = result["evidence"][0]
    assert e.provenance is not None
    assert isinstance(e.known_gaps, list)


def test_coverage_analyzer_no_coverage_file():
    """RED: 无 coverage.xml 应降级返回 + Evidence。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text("print('hello')\n")
        result = analyze_coverage(d)

    assert "evidence" in result
    assert len(result["evidence"]) > 0
    assert result.get("line_rate", 0) == 0 or "line_rate" not in result


def test_coverage_analyzer_returns_summary():
    """RED: 应返回可读摘要。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "coverage.xml")
        Path(f).write_text(SAMPLE_COVERAGE_XML)
        result = analyze_coverage(d)

    assert "summary" in result
    assert len(result["summary"]) > 0


def test_coverage_analyzer_known_gaps_for_coverage_limitations():
    """RED: Evidence 应标注覆盖率分析的已知局限。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "coverage.xml")
        Path(f).write_text(SAMPLE_COVERAGE_XML)
        result = analyze_coverage(d)

    all_gaps = []
    for e in result["evidence"]:
        all_gaps.extend(e.known_gaps)
    assert len(all_gaps) > 0


def test_coverage_analyzer_per_file_stats():
    """RED: 应返回每个文件的覆盖率统计。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "coverage.xml")
        Path(f).write_text(SAMPLE_COVERAGE_XML)
        result = analyze_coverage(d)

    files = result["files"]
    assert len(files) >= 3
    # 每个文件应有 line_rate
    for file_info in files:
        assert "line_rate" in file_info
        assert 0.0 <= file_info["line_rate"] <= 1.0
        assert "filename" in file_info
        assert "lines" in file_info
