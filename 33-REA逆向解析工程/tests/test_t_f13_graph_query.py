"""SPEC-33-F T-F13：`section=graph` 受限图查询 DSL。

约束：只读快照既有图数据；白名单字段；无 eval；非法输入返回 invalid_query。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

import dsh_nodes  # noqa: E402
import pytest  # noqa: E402
from core.graph_query import run_graph_query  # noqa: E402

PAYLOAD = {
    "raw": {
        "modules": [
            {"name": "src/stores/cartStore.ts", "type": "store", "path": "src/stores/cartStore.ts"},
            {"name": "src/stores/userStore.ts", "type": "store", "path": "src/stores/userStore.ts"},
            {"name": "src/api/cart.ts", "type": "api", "path": "src/api/cart.ts"},
        ],
        "dependencies": {
            "src/stores/cartStore.ts": ["src/api/cart.ts"],
            "src/api/cart.ts": ["src/api/client.ts"],
            "src/api/client.ts": [],
        },
    }
}


def test_nodes_exact_and_regex_filter():
    assert run_graph_query(PAYLOAD, "nodes type=store")["total"] == 2
    regex = run_graph_query(PAYLOAD, "nodes name~=cart")
    assert regex["total"] == 2
    assert {item["name"] for item in regex["items"]} == {
        "src/stores/cartStore.ts",
        "src/api/cart.ts",
    }


def test_edges_and_neighbors():
    edges = run_graph_query(PAYLOAD, "edges source=src/api/cart.ts")
    assert edges["items"] == [{"source": "src/api/cart.ts", "target": "src/api/client.ts"}]

    two_hops = run_graph_query(PAYLOAD, "neighbors src/stores/cartStore.ts depth=2")
    assert two_hops["total"] == 2
    assert {"source": "src/stores/cartStore.ts", "target": "src/api/cart.ts"} in two_hops["items"]


def test_pagination():
    page = run_graph_query(PAYLOAD, "nodes", cursor=1, limit=1)
    assert page["total"] == 3
    assert len(page["items"]) == 1
    assert page["next_cursor"] == 2


@pytest.mark.parametrize(
    "query",
    [
        "",
        "drop nodes",
        "nodes unknown_field=x",
        "nodes name~=[",
        "neighbors",
        "neighbors a depth=9",
        "edges source~=a depth=2",
    ],
)
def test_invalid_queries_rejected(query):
    with pytest.raises(ValueError):
        run_graph_query(PAYLOAD, query)


def test_snapshot_section_graph(tmp_path, monkeypatch):
    snapshot_id = "snap-test-graph"
    (tmp_path / f"{snapshot_id}.json").write_text(
        json.dumps({"target": str(tmp_path), "evidence": [], "raw": PAYLOAD["raw"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", tmp_path)

    ok = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": snapshot_id, "section": "graph", "query": "nodes type=store"}
    )
    assert ok["ok"] is True
    assert ok["result"]["section"] == "graph"
    assert ok["result"]["total"] == 2

    bad = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": snapshot_id, "section": "graph", "query": "drop nodes"}
    )
    assert bad["ok"] is False
    assert bad["error"].startswith("invalid_query:")
