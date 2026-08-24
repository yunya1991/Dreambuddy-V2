"""T18 · Lineage + Versioning 测试

T18-1: 血缘断链检测
T18-2: semver 版本号校验
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "21-特征工程中心"))


# ============================================================
# T18-1  血缘断链检测
# ============================================================
def test_t18_1_lineage_closed_chain():
    """注册 A(输入→输出) → B(输入来自A输出) → 无断链"""
    from feature_hub.hub.lineage import LineageTracker

    tracker = LineageTracker()
    tracker.add("module_a", input_cols=["x", "y"], output_cols=["x2", "y2"])
    tracker.add("module_b", input_cols=["x2"], output_cols=["x3"])
    # 无断链 → 不抛异常
    tracker.verify_closed()


def test_t18_1_lineage_broken_link_raises():
    """断链（B的输入不在任何A的输出中）→ 抛异常"""
    from feature_hub.hub.lineage import LineageTracker

    tracker = LineageTracker()
    tracker.add("module_a", input_cols=["x"], output_cols=["x2"])
    tracker.add("module_b", input_cols=["missing_col"], output_cols=["x3"])
    with pytest.raises(Exception, match="broken"):
        tracker.verify_closed()


# ============================================================
# T18-2  版本号校验
# ============================================================
def test_t18_2_version_register_and_query():
    """注册 version=2.1.0 → 查询返回 2.1.0"""
    from feature_hub.hub.versioning import VersionRegistry

    reg = VersionRegistry()
    reg.register("morphology_core", "2.1.0")
    assert reg.get_version("morphology_core") == "2.1.0"


def test_t18_2_version_duplicate_raises():
    """重名+同版本 → Fail-Fast"""
    from feature_hub.hub.versioning import VersionRegistry

    reg = VersionRegistry()
    reg.register("morphology_core", "2.1.0")
    with pytest.raises(Exception, match="already registered"):
        reg.register("morphology_core", "2.1.0")


def test_t18_2_invalid_semver_raises():
    """非法 semver → Fail-Fast"""
    from feature_hub.hub.versioning import VersionRegistry

    reg = VersionRegistry()
    with pytest.raises(Exception, match="invalid.*version"):
        reg.register("bad_module", "v2.1")
