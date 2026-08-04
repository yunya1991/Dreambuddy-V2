"""评测闭环集成测试：会话结束 → 压缩 → A/B → 决策 → 反哺 recall（设计节 7.2/7.7）。"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_closed_loop_runs_evaluation_on_session_end():
    """会话结束时应触发评测闭环。"""
    from cognitive_session import CognitiveSession, RecalledProcessItem, _run_evaluation_closed_loop
    from cognitive_superpowers import SuperpowersSkill

    sess = CognitiveSession()
    sess.status = "ended"
    skill = SuperpowersSkill(
        skill_id="test-driven-development", display_name="TDD", description="",
        version="v1", raw_skill_md="", hard_gates=["NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"],
        checklists=["Write a failing test"], trigger_keywords=[],
        supplement=None, md5_of_base="x", localized=False,
    )
    sess.recalled_processes.append(RecalledProcessItem(
        kind="meta", meta=skill, applied=None, match_score=0.8,
        match_reason="tdd", skill_id="test-driven-development", applied_id=None,
    ))
    sess.action_chain = [
        {"action_type": "file_change", "file": "tests/test_foo.py", "detail": "add test"},
        {"action_type": "file_change", "file": "foo.py", "detail": "edit foo.py"},
        {"action_type": "git_commit", "detail": "commit", "commit_hash": "abc"},
    ]
    sess._meta_processes = sess.recalled_processes
    sess._verify_reports = {"test-driven-development": {"score": 0.7, "followed": True,
                                                         "gate_violations": [], "checklist_matched": [],
                                                         "checklist_missed": []}}

    result = _run_evaluation_closed_loop(sess, applied_id="APP-test")
    assert "path_advantage" in result
    assert "decision" in result
    assert result["decision"] in ("upgrade", "alert", "quarantine", "observe")


def test_supplement_auto_distill_after_three_validations(tmp_path):
    """设计节 7.5：同一本土经验被验证 ≥ 3 次后写入 supplement。"""
    from cognitive_session import _maybe_distill_supplement
    supp_file = tmp_path / "dreambuddy-supplement.md"
    supp_file.write_text("# Dreambuddy 本土补充 — test-driven-development\n## 场景适配（TODO 占位）\n", encoding="utf-8")

    for _ in range(3):
        _maybe_distill_supplement(
            skill_id="test-driven-development",
            supplement_path=supp_file,
            local_experience="交易系统测试文件放在 11-易经推理系统/tests/",
            validation_passed=True,
        )
    content = supp_file.read_text(encoding="utf-8")
    assert "11-易经推理系统" in content or "交易系统" in content


def test_meta_injection_includes_history_eval_line():
    """设计节 7.7：process_block 注入时附带历史评测行。"""
    from cognitive_superpowers import SkillLoader, SuperpowersSkill
    skill = SuperpowersSkill(
        skill_id="tdd", display_name="TDD", description="",
        version="v1", raw_skill_md="", hard_gates=[], checklists=[],
        trigger_keywords=[], supplement=None, md5_of_base="x", localized=False,
    )
    loader = SkillLoader()
    loader.skills = {"tdd": skill}
    applied = {
        "applied_id": "APP-1", "title": "test", "quality_level": "B",
        "confidence": 0.72, "verify_count": 8, "parent_skill": "tdd",
        "path_advantage": 0.38, "evaluation_count": 8,
        "injection": "## test",
    }
    result = loader.retrieve("tdd", top_meta=0, top_applied=1,
                              applied_loader=MagicMock(retrieve_applied=MagicMock(return_value=[applied])))
    assert result["applied"], "applied 不应为空"
    injection = result["applied"][0].get("injection", "")
    assert "历史评测" in injection or "path_advantage" in injection, f"injection 缺历史评测行: {injection}"
