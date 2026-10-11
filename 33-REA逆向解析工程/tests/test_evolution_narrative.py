"""RED 测试：EvolutionNarrative — 演化叙事生成（架构成长史）。

Task 3 of PoE 工程实践复现器 SPEC。
依据：TASKS-工程实践复现器.md TR-3.1 / TR-3.2 / TR-3.3
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# RED: 模块尚未实现，import 应失败
from core.evolution_narrative import (
    EvolutionNarrator,
    generate_narrative,
)


def _git(repo: str, *args: str) -> str:
    """执行 git 命令并返回 stdout。"""
    proc = subprocess.run(
        ["git"] + list(args),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {proc.stderr}")
    return proc.stdout


def _make_git_repo(repo: str) -> None:
    """初始化一个 git 仓库并配置测试作者。"""
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _commit(repo: str, msg: str) -> str:
    """提交当前变更，返回 commit hash。"""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD").strip()


# ---------- 测试用例 ----------


def test_generate_narrative_detects_turning_point():
    """TR-3.1: 含重构历史的 git fixture → 输出 ≥1 个转折点，含 commit hash（在 git log）+ 变更统计非零。"""
    with tempfile.TemporaryDirectory() as d:
        _make_git_repo(d)
        # 初始版本：单文件
        Path(d, "app.py").write_text("def main():\n    pass\n")
        _commit(d, "feat: initial commit")
        # 重构：拆分模块（架构转折）
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        Path(d, "app.py").unlink()
        Path(d, "models", "user.py").write_text("class User:\n    pass\n")
        _commit(d, "refactor: split app into MVC modules")
        # 后续增量
        Path(d, "models", "user.py").write_text("class User:\n    def __init__(self, name):\n        self.name = name\n")
        _commit(d, "feat: add User name field")

        result = generate_narrative(d)
        assert "turning_points" in result
        turning_points = result["turning_points"]
        assert isinstance(turning_points, list)
        assert len(turning_points) >= 1, "应至少检测到 1 个转折点"

        # 获取 git log 中所有 commit hash 用于校验
        log_out = _git(d, "log", "--format=%H").strip()
        all_hashes = set(log_out.split("\n")) if log_out else set()

        tp = turning_points[0]
        assert "commit" in tp, "转折点应含 commit hash"
        assert tp["commit"] in all_hashes, f"commit hash 必须存在于 git log (TR-3.1): {tp['commit']}"
        assert "change_stats" in tp, "转折点应含变更统计"
        assert tp["change_stats"].get("files_changed", 0) > 0, "变更统计非零 (TR-3.1)"


def test_generate_narrative_non_git_failopen():
    """TR-3.2: 非 git 仓库调用时输出 level=unknown Evidence 说明降级原因，不抛异常。"""
    with tempfile.TemporaryDirectory() as d:
        # 不执行 git init
        Path(d, "script.py").write_text("print('hello')\n")
        result = generate_narrative(d)

        assert "turning_points" in result
        assert result["turning_points"] == []
        evidence_list = result.get("evidence", [])
        assert len(evidence_list) > 0
        unknown_evs = [e for e in evidence_list if e.level.value == "unknown"]
        assert len(unknown_evs) >= 1, "应含 level=unknown Evidence (TR-3.2)"
        assert unknown_evs[0].known_gaps, "known_gaps 必须非空 (TR-3.2)"


def test_generate_narrative_tech_debt_timeline():
    """TR-3.3: 技术债时间线中每条 TODO 记录带 commit hash 和文件路径。"""
    with tempfile.TemporaryDirectory() as d:
        _make_git_repo(d)
        # 引入 TODO
        Path(d, "service.py").write_text("# TODO: 待重构为事件驱动\nclass Service:\n    pass\n")
        _commit(d, "feat: add service with TODO")

        result = generate_narrative(d)
        debt_timeline = result.get("tech_debt_timeline", [])
        # 检测到 TODO 则每条必须有 commit + file
        for item in debt_timeline:
            assert "commit" in item, "技术债条目必须含 commit hash (TR-3.3)"
            assert "file" in item, "技术债条目必须含文件路径 (TR-3.3)"


def test_generate_narrative_returns_evidence():
    """应返回 Evidence 列表。"""
    with tempfile.TemporaryDirectory() as d:
        _make_git_repo(d)
        Path(d, "app.py").write_text("def main():\n    pass\n")
        _commit(d, "feat: initial")
        result = generate_narrative(d)
        assert "evidence" in result
        assert len(result["evidence"]) > 0
        e = result["evidence"][0]
        assert e.provenance is not None
        assert isinstance(e.known_gaps, list)


def test_generate_narrative_nonexistent_repo_failopen():
    """FAIL-OPEN: 不存在的目录返回 level=unknown Evidence，不抛异常。"""
    result = generate_narrative("/nonexistent/repo/xyz")
    assert "turning_points" in result
    assert result["turning_points"] == []
    assert any(e.level.value == "unknown" for e in result.get("evidence", []))


def test_evolution_narrator_class_usable():
    """EvolutionNarrator 类可直接实例化。"""
    with tempfile.TemporaryDirectory() as d:
        _make_git_repo(d)
        Path(d, "app.py").write_text("def main():\n    pass\n")
        _commit(d, "feat: init")
        narrator = EvolutionNarrator()
        result = narrator.generate(d)
        assert "turning_points" in result
