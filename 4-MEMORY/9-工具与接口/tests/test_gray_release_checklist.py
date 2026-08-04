"""灰度观察期检查脚本单测（设计节 6.5 检查表 7 项）。"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.gray_release_checklist import run_gray_check, GrayCheckResult


def test_gray_check_returns_7_items():
    """设计节 6.5：检查表返回 7 项。"""
    with patch("scripts.gray_release_checklist._run_cli") as mock_cli:
        # 模拟 CLI 返回值
        mock_cli.side_effect = [
            {"status": "healthy"},                           # daemon 健康
            {"skills": [{"name": f"s{i}", "loaded": True} for i in range(14)]},  # SKILL.md 完整性
            {"process_hit_rate": 0.75},                      # recall 命中率
            {"injection_count": 8},                          # process_block 注入次数
            {"applied": [{"parent_skill_ids": ["tdd"]}] * 5
             + [{"parent_skill_ids": ["custom-path"]}] * 2}, # 新 applied 关联率
            {"mapping_stats": {"test-driven-development": {"success": 4}}},  # mapping 累积
            "",                                              # 异常日志（空=无 ERROR）
        ]
        results = run_gray_check()
    assert len(results) == 7
    # 所有项都应是 GrayCheckResult
    for r in results:
        assert isinstance(r, GrayCheckResult)
        assert r.name != ""
        assert r.passed in (True, False)


def test_gray_check_daemon_health_pass():
    """检查项 1：daemon healthy → pass。"""
    with patch("scripts.gray_release_checklist._run_cli") as mock_cli:
        mock_cli.return_value = {"status": "healthy"}
        from scripts.gray_release_checklist import _check_daemon_health
        result = _check_daemon_health()
    assert result.passed is True


def test_gray_check_recall_hit_rate_threshold():
    """检查项 3：process_hit_rate > 60% → pass。"""
    with patch("scripts.gray_release_checklist._run_cli") as mock_cli:
        mock_cli.return_value = {"process_hit_rate": 0.65}
        from scripts.gray_release_checklist import _check_recall_hit_rate
        result = _check_recall_hit_rate()
    assert result.passed is True
    assert "65%" in result.detail or "0.65" in result.detail


def test_gray_check_applied_association_rate():
    """检查项 5：新 applied 关联率 > 60% → pass（parent_skill_ids != custom-path）。"""
    with patch("scripts.gray_release_checklist._run_cli") as mock_cli:
        mock_cli.return_value = {
            "applied": [
                {"parent_skill_ids": ["tdd"]},
                {"parent_skill_ids": ["tdd"]},
                {"parent_skill_ids": ["tdd"]},
                {"parent_skill_ids": ["custom-path"]},
            ]
        }
        from scripts.gray_release_checklist import _check_applied_association
        result = _check_applied_association()
    # 3/4 = 75% > 60% → pass
    assert result.passed is True
