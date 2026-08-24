"""顶层包导出测试 — 对齐 TECHNICAL_DESIGN.md §5.1。

from data_center import DataCenter, DataRecord 必须可用。
"""
import data_center


def test_top_level_exports():
    from data_center import DataCenter, DataRecord

    assert DataCenter is not None
    assert DataRecord is not None


def test_version_string():
    assert isinstance(data_center.__version__, str)
    assert data_center.__version__
