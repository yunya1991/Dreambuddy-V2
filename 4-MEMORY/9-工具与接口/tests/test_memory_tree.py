#!/usr/bin/env python3
"""记忆树 memory_tree.py 单测：构建 / D1 查询 / D2 遍历 / D3-D4 回写 / 容量门。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_tree import (  # noqa: E402
    PIN_BUDGET,
    MemoryTree,
    heading_keywords,
    tokenize,
)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    proj = repo / "18-数据获取中心"
    (proj / "backfill").mkdir(parents=True)
    (proj / "README.md").write_text("# 数据获取中心\n\n## 外部数据源接入\n", encoding="utf-8")
    (proj / "backfill" / "INDEX.md").write_text("# 回填子模块\n", encoding="utf-8")
    (proj / "backfill" / "新闻快讯回填说明.md").write_text(
        "# 新闻快讯回填\n\n## 幂等写入\n", encoding="utf-8"
    )
    (repo / "mcp_shells").mkdir()
    (repo / "__pycache__").mkdir()
    return repo


def test_tokenize_splits_connectors_and_strips_suffix():
    tokens = tokenize("记忆树与求解级联")
    assert "记忆树" in tokens and "求解级联" in tokens
    assert "数据获取" in tokenize("数据获取中心")


def test_build_three_levels_and_anchors(tmp_path):
    tree = MemoryTree.build(_make_repo(tmp_path))
    stats = tree.stats()
    assert stats["projects"] == 1, "只有编号目录算项目，mcp_shells / __pycache__ 不收录"
    assert stats["dirs"] == 1
    assert stats["chapters"] == 1
    assert stats["with_anchor"] == stats["nodes"]

    proj = tree.nodes["18-数据获取中心"]
    assert proj["level"] == 1 and proj["module_paths"] == ["18-数据获取中心"]
    assert "18-数据获取中心/README.md" in proj["doc_anchors"]
    # 目录名与标题都应成为关键词
    assert "数据获取" in proj["keywords"] and "外部数据源接入" in proj["keywords"]


def test_query_hit_and_miss_degraded(tmp_path):
    tree = MemoryTree.build(_make_repo(tmp_path))
    hits = tree.query("新闻快讯 回填")
    assert hits and hits[0]["path"].endswith("新闻快讯回填说明.md")
    assert hits[0]["doc_anchors"], "命中节点必须带文档锚点，供 D1 展开"

    assert tree.query("加密货币 期权 做市") == []


def test_walk_ancestors_children_and_missing(tmp_path):
    tree = MemoryTree.build(_make_repo(tmp_path))
    cur = "18-数据获取中心/backfill/新闻快讯回填说明.md"
    walked = tree.walk(cur)
    assert walked["ok"] and walked["ancestors"] == ["18-数据获取中心", "18-数据获取中心/backfill"]
    assert tree.walk("18-数据获取中心", depth=2)["children"]

    missing = tree.walk("99-不存在")
    assert missing["ok"] is False and missing["degraded_reason"] == "node_not_found"


def test_upsert_writeback_creates_chain_and_truncates_note(tmp_path):
    tree = MemoryTree.build(_make_repo(tmp_path))
    res = tree.upsert(
        "33-REA逆向解析工程/图结构/调用链",
        keywords=["调用链", "依赖环"],
        module_paths=["33-REA逆向解析工程/graph"],
        note="x" * 500,
    )
    assert res["ok"] and res["level"] == 3
    node = tree.nodes["33-REA逆向解析工程/图结构/调用链"]
    assert node["parent"] == "33-REA逆向解析工程/图结构"
    assert "调用链" in node["keywords"] and node["origin"] == "rea"
    assert len(node["note"]) == 120, "回写只允许指针摘要，禁止存细节"
    assert tree.nodes["33-REA逆向解析工程"]["level"] == 1, "缺父链必须自动补齐"

    tree.save(tmp_path / "tree.json")
    reloaded = MemoryTree.load(tmp_path / "tree.json")
    assert reloaded.nodes["33-REA逆向解析工程/图结构/调用链"]["keywords"]
    assert json.loads((tmp_path / "tree.json").read_text(encoding="utf-8"))["stats"]["nodes"] > 0


def test_pin_budget_enforced(tmp_path):
    with pytest.raises(ValueError):
        MemoryTree.build(_make_repo(tmp_path), pins=[f"p{i}" for i in range(PIN_BUDGET + 1)])


def test_heading_keywords_reads_headings_only(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("# 标题一\n\n正文不应成为关键词\n\n## 记忆树与求解级联\n", encoding="utf-8")
    kws = heading_keywords(doc)
    assert "记忆树" in kws and "求解级联" in kws
    assert "正文不应成为关键词" not in kws
