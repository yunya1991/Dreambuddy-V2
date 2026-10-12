"""RED 测试：P2-3/P2-4/P2-5 REA 工具修复（SPEC 维度 F）。

- P2-3: investigation_workflow evidence 按 evidence_id 去重
- P2-4: git_history 路径解析失败返回 unknown 而非静默空
- P2-5: algorithm_reducer 模式库扩展（梯度更新/相似性检索/贝叶斯更新/状态机）
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.evidence import Evidence
from core.investigation_workflow import investigate, InvestigationWorkflow
from core.git_history import trace_git_history


# ---------------------------------------------------------------------------
# P2-3: evidence 去重
# ---------------------------------------------------------------------------

SAMPLE_PROJECT = '''
def main():
    svc = UserService()
    users = svc.get_users()
    for u in users:
        print(u)
'''


def _setup_project(d):
    Path(os.path.join(d, "main.py")).write_text(
        "from service import UserService\n\n" + SAMPLE_PROJECT.strip()
    )
    Path(os.path.join(d, "service.py")).write_text(
        "class UserService:\n"
        "    def get_users(self):\n"
        "        data = self._fetch()\n"
        "        return data\n"
        "    def _fetch(self):\n"
        "        return [1]\n"
    )


def test_investigate_top_level_evidence_no_duplicate_ids():
    """P2-3: investigate 顶层 evidence 不应有重复 evidence_id（8 条≠16 条）。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)

    ids = [e.evidence_id for e in result["evidence"]]
    assert len(ids) > 0
    assert len(ids) == len(set(ids)), (
        f"evidence 存在重复: {len(ids)} 条中仅 {len(set(ids))} 唯一"
    )


def test_phase_annotate_dedup_keeps_first_occurrence():
    """P2-3: _phase_annotate 聚合时按 evidence_id 去重且保持首次出现顺序。"""
    shared = Evidence(result="共享证据", level="observation")
    only_a = Evidence(result="仅A证据", level="observation")
    only_b = Evidence(result="仅B证据", level="observation")

    phases = {
        "locate": {"evidence": [shared, only_a]},
        "trace": {"evidence": [shared, only_b]},
    }

    wf = InvestigationWorkflow()
    annotate = wf._phase_annotate(phases, "/tmp/fake", None)

    ids = [e.evidence_id for e in annotate["evidence"]]
    assert len(ids) == len(set(ids)), "标注阶段 evidence 未去重"
    # 共享证据应只出现一次，且顺序为首次出现（locate 在前）
    assert ids[0] == shared.evidence_id
    assert set(ids) == {shared.evidence_id, only_a.evidence_id, only_b.evidence_id}


# ---------------------------------------------------------------------------
# P2-4: git_history 路径失败返回 unknown
# ---------------------------------------------------------------------------

def test_git_history_nonexistent_file_returns_unknown_level():
    """P2-4: 不存在路径应返回 level=unknown 的 Evidence 且 known_gaps 非空。"""
    with tempfile.TemporaryDirectory() as d:
        import subprocess
        subprocess.run(["git", "init"], cwd=d, capture_output=True, check=True)
        result = trace_git_history(d, os.path.join(d, "不存在_嵌套/missing.py"))

    assert len(result["evidence"]) > 0
    unknown_evs = [
        e for e in result["evidence"]
        if (e.level.value if hasattr(e.level, "value") else str(e.level)) == "unknown"
    ]
    assert unknown_evs, "文件不存在时应返回 level=unknown 的 Evidence"
    assert any(e.known_gaps for e in unknown_evs), "unknown Evidence 的 known_gaps 应非空"
    assert any("路径解析失败" in g for e in unknown_evs for g in e.known_gaps), (
        "known_gaps 应包含 '路径解析失败' 及原因"
    )


def test_git_history_git_log_failure_returns_unknown(monkeypatch):
    """P2-4: git log 执行失败（rc!=0）应返回 unknown Evidence 而非静默空。"""
    import core.git_history as gh

    real_run = gh._run_git

    def fake_run(args, cwd):
        if "log" in args:
            return 128, "", "fatal: 路径解析失败模拟"
        return real_run(args, cwd)

    monkeypatch.setattr(gh, "_run_git", fake_run)

    with tempfile.TemporaryDirectory() as d:
        import subprocess
        subprocess.run(["git", "init"], cwd=d, capture_output=True, check=True)
        f = os.path.join(d, "sample.py")
        Path(f).write_text("def a():\n    return 1\n")
        result = trace_git_history(d, f)

    unknown_evs = [
        e for e in result["evidence"]
        if (e.level.value if hasattr(e.level, "value") else str(e.level)) == "unknown"
    ]
    assert unknown_evs, "git log 失败时应返回 level=unknown 的 Evidence"
    assert any("路径解析失败" in g for e in unknown_evs for g in e.known_gaps)


def test_git_history_normal_path_unchanged():
    """P2-4: 正常路径行为不变（有提交历史时仍返回 observation/derivation 证据）。"""
    with tempfile.TemporaryDirectory() as d:
        import subprocess
        subprocess.run(["git", "init"], cwd=d, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=d, capture_output=True)
        f = os.path.join(d, "sample.py")
        Path(f).write_text("def a():\n    return 1\n")
        subprocess.run(["git", "add", "sample.py"], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)

        result = trace_git_history(d, f)

    assert result["change_count"] >= 1
    levels = {
        (e.level.value if hasattr(e.level, "value") else str(e.level))
        for e in result["evidence"]
    }
    assert "unknown" not in levels, "正常路径不应出现 unknown 证据"
