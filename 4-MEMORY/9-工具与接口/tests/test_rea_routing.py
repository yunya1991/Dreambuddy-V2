#!/usr/bin/env python3
"""M1-T 路由表单测：默认表可用 / 命中确定性 / 未命中降级 / 缺表降级 / 预算硬门 / 结构校验。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.rea_routing import DEFAULT_TABLE, load_table, route  # noqa: E402


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "table.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_default_table_loads_within_budget():
    table = load_table()
    assert table["ok"] is True
    assert table["count"] == len(table["categories"])
    assert table["count"] <= table["budget"] <= 150
    assert DEFAULT_TABLE.exists()


def test_route_hits_expected_category():
    out = route("改这个函数的影响面有多大，回归风险高吗")
    assert out["ok"] is True
    assert out["category"] == "impact-analysis"
    assert out["tools"], "命中必须给出具体工具链"


def test_route_first_entry_wins_on_tie():
    """同分保持文件顺序：'入口 调用链' 只应命中 entry-point-trace。"""
    out = route("入口 调用链")
    assert out["category"] == "entry-point-trace"


def test_route_no_match_degrades():
    out = route("今天午饭吃什么")
    assert out["ok"] is False
    assert out["degraded_reason"] == "routing_no_match"
    assert out["next"] == "capability_gap_workorder"


def test_missing_table_degrades_not_crashes(tmp_path):
    out = route("影响面", tmp_path / "nope.yaml")
    assert out["ok"] is False
    assert out["degraded_reason"] == "routing_table_missing"
    assert out["next"] == "D3"


def test_budget_exceeded_fails_loud(tmp_path):
    text = """
version: 1
budget: 1
categories:
  - id: a
    keywords: [k1]
    tools: [mcp_rea_recall]
  - id: b
    keywords: [k2]
    tools: [mcp_rea_recall]
"""
    out = route("k1", _write(tmp_path, text))
    assert out["ok"] is False
    assert out["degraded_reason"] == "routing_budget_exceeded"
    assert out["count"] == 2 and out["budget"] == 1


def test_malformed_entry_rejected(tmp_path):
    text = """
version: 1
categories:
  - id: a
    keywords: [k1]
    tools: [not_a_rea_tool]
"""
    out = load_table(_write(tmp_path, text))
    assert out["ok"] is False
    assert out["degraded_reason"] == "routing_table_invalid"
    assert any("tools_malformed" in e for e in out["errors"])
