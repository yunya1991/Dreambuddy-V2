"""RED 测试：DependencyAudit — 依赖版本审计。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.dependency_audit import audit_dependencies


PYPROJECT_SAMPLE = '''
[project]
name = "test-project"
version = "0.1.0"
dependencies = [
    "requests>=2.28.0",
    "numpy>=1.21.0",
    "pandas>=1.4.0",
]
'''

REQUIREMENTS_SAMPLE = '''requests>=2.28.0
numpy>=1.21.0
flask==2.0.0
'''

PACKAGE_JSON_SAMPLE = '''
{
  "name": "test-project",
  "dependencies": {
    "express": "^4.18.0",
    "lodash": "^4.17.0"
  }
}
'''


def test_audit_dependencies_pyproject_toml():
    """RED: 应解析 pyproject.toml 声明的依赖。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "pyproject.toml")
        Path(f).write_text(PYPROJECT_SAMPLE)
        result = audit_dependencies(d)
        assert "declared" in result
        assert len(result["declared"]) >= 3
        assert any(dep["name"] == "requests" for dep in result["declared"])


def test_audit_dependencies_requirements_txt():
    """RED: 应解析 requirements.txt 声明的依赖。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "requirements.txt")
        Path(f).write_text(REQUIREMENTS_SAMPLE)
        result = audit_dependencies(d)
        assert "declared" in result
        assert len(result["declared"]) >= 3
        assert any(dep["name"] == "flask" for dep in result["declared"])


def test_audit_dependencies_package_json():
    """RED: 应解析 package.json 声明的依赖。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "package.json")
        Path(f).write_text(PACKAGE_JSON_SAMPLE)
        result = audit_dependencies(d)
        assert "declared" in result
        assert len(result["declared"]) >= 2
        assert any(dep["name"] == "express" for dep in result["declared"])


def test_audit_dependencies_returns_evidence():
    """RED: 应返回 Evidence 列表。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "requirements.txt")
        Path(f).write_text(REQUIREMENTS_SAMPLE)
        result = audit_dependencies(d)
        assert "evidence" in result
        assert len(result["evidence"]) > 0
        e = result["evidence"][0]
        assert e.provenance is not None
        assert isinstance(e.known_gaps, list)


def test_audit_dependencies_no_manifest():
    """RED: 无依赖清单文件应降级返回 + Evidence。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text("print('hello')\n")
        result = audit_dependencies(d)
        assert "evidence" in result
        assert len(result["evidence"]) > 0
        assert len(result["declared"]) == 0


def test_audit_dependencies_returns_summary():
    """RED: 应返回摘要信息。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "requirements.txt")
        Path(f).write_text(REQUIREMENTS_SAMPLE)
        result = audit_dependencies(d)
        assert "summary" in result
        assert len(result["summary"]) > 0
