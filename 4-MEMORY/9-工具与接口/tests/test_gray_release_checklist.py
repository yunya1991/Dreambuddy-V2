"""灰度观察期检查脚本单测（设计节 6.5 检查表 7 项）。"""
import sys
import types
from pathlib import Path
from unittest.mock import patch

_MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MODULE_DIR))

# 本目录 scripts/ 与仓库根 scripts/ 都是无 __init__.py 的命名空间包，而
# 11-易经推理系统/scripts 是常规包（含 __init__.py）。按 PEP 420，常规包优先于
# 命名空间包，仓库根 conftest 注入该目录后，pytest 内 `import scripts` 会命中
# 常规包，导致本目录 scripts.gray_release_checklist 不可见（ModuleNotFoundError）。
# 这里预先注册命名空间包，按 sys.path 顺序收集所有 scripts 目录，
# 复现无遮蔽时的命名空间解析语义。
_pkg = sys.modules.get("scripts")
if _pkg is None or not hasattr(_pkg, "__path__"):
    _pkg = types.ModuleType("scripts")
    _pkg.__path__ = []
    sys.modules["scripts"] = _pkg
_local_scripts = str(_MODULE_DIR / "scripts")
if _local_scripts not in _pkg.__path__:
    _pkg.__path__.insert(0, _local_scripts)
for _entry in sys.path:
    _cand = str(Path(_entry) / "scripts")
    if _cand != _local_scripts and Path(_cand).is_dir() and _cand not in _pkg.__path__:
        _pkg.__path__.append(_cand)

from scripts.gray_release_checklist import (  # noqa: E402  命名空间包注册必须先于 import
    GrayCheckResult,
    run_gray_check,
)


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
