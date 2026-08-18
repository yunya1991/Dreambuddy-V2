"""最终签收脚本单测（V1-V15 全量验收，设计节 6.2 + 7.9）。"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.final_signoff import run_all_acceptance, AcceptanceItem


def test_acceptance_returns_15_items():
    """V1-V15 共 15 项验收。"""
    with patch("scripts.final_signoff._run_acceptance_check") as mock_check:
        mock_check.return_value = True
        results = run_all_acceptance()
    assert len(results) == 15
    ids = [r.vid for r in results]
    assert ids == [f"V{i}" for i in range(1, 16)]


def test_all_acceptance_items_have_fields():
    """每个验收项含 vid/name/method/criteria/passed 字段。"""
    with patch("scripts.final_signoff._run_acceptance_check") as mock_check:
        mock_check.return_value = True
        results = run_all_acceptance()
    for r in results:
        assert isinstance(r, AcceptanceItem)
        assert r.vid != ""
        assert r.name != ""
        assert r.method != ""
        assert r.criteria != ""
        assert r.passed in (True, False)


def test_v14_quarantine_filter_check():
    """V14：quarantined 的 Solution Path recall 不召回。"""
    from scripts.final_signoff import _check_v14
    with patch("scripts.final_signoff._run_cli") as mock_cli:
        # recall 返回不含 quarantined 的 applied
        mock_cli.return_value = {
            "processes": {
                "applied": [
                    {"applied_id": "APP-1", "quality_level": "B"},
                    {"applied_id": "APP-2", "quality_level": "A"},
                ]
            }
        }
        result = _check_v14()
    assert result.passed is True
    assert "quarantined" not in result.actual or "0" in result.actual
