"""RED 测试：GitHistory — git log/blame 历史溯源。"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.git_history import trace_git_history


def _make_test_repo(tmpdir: str) -> str:
    """创建测试用 git 仓库，含2次提交。"""
    # git init
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmpdir, capture_output=True)

    # 第一次提交
    f1 = os.path.join(tmpdir, "sample.py")
    Path(f1).write_text("def func_a():\n    return 1\n")
    subprocess.run(["git", "add", "sample.py"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmpdir, capture_output=True)

    # 第二次提交（修改）
    Path(f1).write_text("def func_a():\n    return 42\n\ndef func_b():\n    return func_a()\n")
    subprocess.run(["git", "add", "sample.py"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add func_b"], cwd=tmpdir, capture_output=True)

    return f1


def test_git_history_returns_authors():
    """RED: 应返回作者列表。"""
    with tempfile.TemporaryDirectory() as d:
        f = _make_test_repo(d)
        result = trace_git_history(d, f)
        assert "authors" in result
        assert isinstance(result["authors"], list)
        assert len(result["authors"]) > 0


def test_git_history_returns_commit_info():
    """RED: 应返回首次和最后提交时间。"""
    with tempfile.TemporaryDirectory() as d:
        f = _make_test_repo(d)
        result = trace_git_history(d, f)
        assert "first_commit" in result
        assert "last_commit" in result
        assert result["first_commit"] is not None
        assert result["last_commit"] is not None


def test_git_history_returns_change_count():
    """RED: 应返回变更次数。"""
    with tempfile.TemporaryDirectory() as d:
        f = _make_test_repo(d)
        result = trace_git_history(d, f)
        assert "change_count" in result
        assert result["change_count"] >= 2  # 2次提交


def test_git_history_returns_hot_lines():
    """RED: 应返回热点行（变更频繁的行）。"""
    with tempfile.TemporaryDirectory() as d:
        f = _make_test_repo(d)
        result = trace_git_history(d, f)
        assert "hot_lines" in result
        assert isinstance(result["hot_lines"], list)


def test_git_history_returns_evidence():
    """RED: 应返回 Evidence 列表（带 provenance + known_gaps）。"""
    with tempfile.TemporaryDirectory() as d:
        f = _make_test_repo(d)
        result = trace_git_history(d, f)
        assert "evidence" in result
        assert len(result["evidence"]) > 0
        e = result["evidence"][0]
        assert e.provenance is not None
        assert isinstance(e.known_gaps, list)
        assert 0.0 <= e.confidence <= 1.0


def test_git_history_nonexistent_file():
    """RED: 文件不存在时应返回降级结果 + Evidence。"""
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init"], cwd=d, capture_output=True, check=True)
        result = trace_git_history(d, os.path.join(d, "nonexistent.py"))
        assert "evidence" in result
        assert len(result["evidence"]) > 0
        assert result["change_count"] == 0


def test_git_history_not_a_repo():
    """RED: 非 git 仓库应降级返回 + Evidence。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sample.py")
        Path(f).write_text("print('hello')\n")
        result = trace_git_history(d, f)
        assert "evidence" in result
        assert len(result["evidence"]) > 0
        assert result["change_count"] == 0
