"""P1-3 auto_register_skill → doc-sync 触发 TDD RED 测试

验证 auto_register_skill.register_skills() 注册成功后：
  1. 通过认知系统 record(tags="doc-sync,...") 记录经验
  2. report 中包含 triggered_skills: ["dream-doc-sync-workflow"]
  3. report 中包含 doc_sync_memory_id 字段
  4. 认知系统不可用时 FAIL-OPEN（主流程不中断）
  5. 无新 SKILL 时不触发 doc-sync

RED 契约：
  - 当前 register_skills() 不调用 record，report 无 triggered_skills 字段 → 断言失败
  - 当前 report 无 doc_sync_memory_id 字段 → 断言失败

参考：SPEC-CognitiveSystem-Evolution.md §2.2.3 P1-3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 添加 auto_register_skill.py 所在目录到 sys.path
_SI_DIR = (
    Path(__file__).resolve().parents[2]
    / "1-ARCHITECTURE" / "skills" / "dream-skill-index-governance"
)
if str(_SI_DIR) not in sys.path:
    sys.path.insert(0, str(_SI_DIR))


# ─────────────────────────────── 辅助 fixture ───────────────────────────────

@pytest.fixture
def fake_skill_dir(tmp_path):
    """构造一个临时 SKILL 目录，含合法 SKILL.md frontmatter。"""
    skill_dir = tmp_path / "dream-test-p1-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: dream-test-p1-skill\n"
        "description: 'test skill for P1-3'\n"
        "version: 1.0.0\n"
        "status: active\n"
        "---\n"
        "## Test\n",
        encoding="utf-8",
    )
    return skill_dir


@pytest.fixture
def mock_build_result():
    """模拟 build() 返回值（含 registry + conflicts + drift）。"""
    return {
        "registry": {"total_count": 205, "skills": []},
        "conflicts": {},
        "drift": {},
    }


# ─────────────────────────────── RED: triggered_skills 字段 ───────────────────────────────

def test_register_success_returns_triggered_skills(fake_skill_dir, mock_build_result):
    """RED: register_skills() 成功后 report 应包含 triggered_skills 字段。"""
    from auto_register_skill import register_skills
    with patch("auto_register_skill.validate") as mock_val, \
         patch("auto_register_skill.build", return_value=mock_build_result), \
         patch("auto_register_skill._get_cle_or_none") as mock_get_cle:
        mock_val.return_value = {"valid": True, "errors": [], "warnings": []}
        mock_cle = MagicMock()
        mock_cle.record.return_value = "VM-TEST-P1-3"
        mock_get_cle.return_value = mock_cle
        report = register_skills(skill_dirs=[fake_skill_dir], auto_detect=False)
    assert "triggered_skills" in report, (
        "P1-3 RED: register_skills() report 应包含 triggered_skills 字段"
    )


def test_register_success_triggered_skills_contains_doc_sync(fake_skill_dir, mock_build_result):
    """RED: triggered_skills 应包含 'dream-doc-sync-workflow'。"""
    from auto_register_skill import register_skills
    with patch("auto_register_skill.validate") as mock_val, \
         patch("auto_register_skill.build", return_value=mock_build_result), \
         patch("auto_register_skill._get_cle_or_none") as mock_get_cle:
        mock_val.return_value = {"valid": True, "errors": [], "warnings": []}
        mock_cle = MagicMock()
        mock_cle.record.return_value = "VM-TEST-P1-3"
        mock_get_cle.return_value = mock_cle
        report = register_skills(skill_dirs=[fake_skill_dir], auto_detect=False)
    assert "dream-doc-sync-workflow" in report.get("triggered_skills", []), (
        "P1-3 RED: triggered_skills 应包含 'dream-doc-sync-workflow'"
    )


# ─────────────────────────────── RED: record 调用验证 ───────────────────────────────

def test_register_success_calls_record_with_doc_sync_tag(fake_skill_dir, mock_build_result):
    """RED: 注册成功后应调用认知系统 record()，且 tags 含 'doc-sync'。"""
    from auto_register_skill import register_skills
    with patch("auto_register_skill.validate") as mock_val, \
         patch("auto_register_skill.build", return_value=mock_build_result), \
         patch("auto_register_skill._get_cle_or_none") as mock_get_cle:
        mock_val.return_value = {"valid": True, "errors": [], "warnings": []}
        mock_cle = MagicMock()
        mock_cle.record.return_value = "VM-TEST-P1-3-RECORD"
        mock_get_cle.return_value = mock_cle
        register_skills(skill_dirs=[fake_skill_dir], auto_detect=False)
    # record 应被调用
    mock_cle.record.assert_called_once()
    # tags 参数应包含 'doc-sync'
    call_kwargs = mock_cle.record.call_args
    tags_arg = call_kwargs.kwargs.get("tags") or call_kwargs.args[3]  # 第4个位置参数
    assert "doc-sync" in tags_arg, (
        "P1-3 RED: record() 的 tags 参数应包含 'doc-sync'"
    )


def test_register_success_returns_doc_sync_memory_id(fake_skill_dir, mock_build_result):
    """RED: report 应包含 doc_sync_memory_id 字段，值为 record 返回的 memory_id。"""
    from auto_register_skill import register_skills
    with patch("auto_register_skill.validate") as mock_val, \
         patch("auto_register_skill.build", return_value=mock_build_result), \
         patch("auto_register_skill._get_cle_or_none") as mock_get_cle:
        mock_val.return_value = {"valid": True, "errors": [], "warnings": []}
        mock_cle = MagicMock()
        mock_cle.record.return_value = "VM-TEST-P1-3-MID"
        mock_get_cle.return_value = mock_cle
        report = register_skills(skill_dirs=[fake_skill_dir], auto_detect=False)
    assert report.get("doc_sync_memory_id") == "VM-TEST-P1-3-MID", (
        "P1-3 RED: report.doc_sync_memory_id 应为 record 返回的 memory_id"
    )


# ─────────────────────────────── RED: FAIL-OPEN ───────────────────────────────

def test_register_fail_open_when_cognitive_unavailable(fake_skill_dir, mock_build_result):
    """FAIL-OPEN: 认知系统不可用时，注册仍成功，triggered_skills 为空列表。"""
    from auto_register_skill import register_skills
    with patch("auto_register_skill.validate") as mock_val, \
         patch("auto_register_skill.build", return_value=mock_build_result), \
         patch("auto_register_skill._get_cle_or_none", return_value=None):
        mock_val.return_value = {"valid": True, "errors": [], "warnings": []}
        report = register_skills(skill_dirs=[fake_skill_dir], auto_detect=False)
    assert report["status"] == "success"
    assert report.get("triggered_skills") == []
    assert report.get("doc_sync_memory_id") is None


# ─────────────────────────────── RED: 无新 SKILL 时不触发 ───────────────────────────────

def test_register_no_trigger_when_no_new_skills(mock_build_result):
    """RED: 无新 SKILL 时不触发 doc-sync（status == 'no_new_skills'）。"""
    from auto_register_skill import register_skills
    with patch("auto_register_skill._get_cle_or_none") as mock_get_cle:
        mock_cle = MagicMock()
        mock_get_cle.return_value = mock_cle
        report = register_skills(skill_dirs=[], auto_detect=False)
    assert report["status"] == "no_new_skills"
    # record 不应被调用
    mock_cle.record.assert_not_called()
    assert report.get("triggered_skills") == []


# ─────────────────────────────── RED: 验证失败时不触发 ───────────────────────────────

def test_register_no_trigger_when_validation_failed(fake_skill_dir, mock_build_result):
    """RED: SKILL 验证失败时不触发 doc-sync。"""
    from auto_register_skill import register_skills
    with patch("auto_register_skill.validate") as mock_val, \
         patch("auto_register_skill.build", return_value=mock_build_result), \
         patch("auto_register_skill._get_cle_or_none") as mock_get_cle:
        mock_val.return_value = {"valid": False, "errors": ["bad"], "warnings": []}
        mock_cle = MagicMock()
        mock_get_cle.return_value = mock_cle
        report = register_skills(skill_dirs=[fake_skill_dir], auto_detect=False)
    # 验证失败 → status 非 "success" → 不触发 doc-sync
    assert report["status"] != "success"
    mock_cle.record.assert_not_called()
    assert report.get("triggered_skills") == []
