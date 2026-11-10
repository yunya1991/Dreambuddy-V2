# ruff: noqa: E402
"""测试隔离：ASIL 写入一律使用临时认知库，禁止污染生产记忆。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_cognitive_writeback(tmp_path, monkeypatch):
    monkeypatch.setenv("ASIL_WRITEBACK_STORAGE", str(tmp_path / "cognitive_test.db"))
    monkeypatch.setenv("ASIL_WRITEBACK_DISTILL", "0")
