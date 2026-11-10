"""verdict_dashboard 聚合逻辑测试。"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "metrics"))

import verdict_dashboard as vd  # noqa: E402


def test_build_dashboard_structure():
    dash = vd.build_dashboard()
    assert "entries" in dash
    assert "summary" in dash
    assert "generated_at" in dash
    experiments = {e["experiment"] for e in dash["entries"]}
    assert {"D2-A", "D3-A", "E2", "E3", "E5", "E1", "E4"} <= experiments


def test_d2a_verdict_present():
    dash = vd.build_dashboard()
    d2a = next(e for e in dash["entries"] if e["experiment"] == "D2-A")
    assert d2a["verdict"] in {"candidate", "falsified", "inconclusive", "not_run"}


def test_e2_falsified_when_zero_admitted():
    """E2: admitted=0 且 verify_status=ok → falsified。"""
    entry = vd._e2_verdict()
    # 当前数据 32 新颖 0 准入，应为 falsified
    assert entry["verdict"] == "falsified"
    assert entry["value"] == 0.0


def test_render_table_contains_all_experiments():
    dash = vd.build_dashboard()
    table = vd._render_table(dash)
    for exp in ["D2-A", "D3-A", "E2", "E3", "E5", "E1", "E4"]:
        assert exp in table
