# -*- coding: utf-8 -*-
"""D-E18 资金流向导图（SPEC-54-L1交易层 §4.5，P0-5）。

覆盖：
  - `flow` 边严格 5 键、`kind="flow"`、`weight=min(1,|z|/3)`、`p_adj=None`（B-LT2）；
  - `flow` 边按 `|flow_z|` 降序 TopK，`meta.flows[].edge_index` 与边一一对应；
  - `direction` 只允许 `net_out_of_src` / `net_into_src`，非法回落并留痕；
  - 无流数据 → `corr`-only 降级 + `meta.reason="flow_unavailable"`（LT-G7，不伪造边）；
  - 流与相关网络都缺 → `ok=false` / `status=empty`；
  - 信封契约：`source_capability="D-E18"`、`quality_ref="quality"`、无内部字段。
"""

import json
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.capabilities.flow import (  # noqa: E402
    DIRECTIONS,
    EDGE_KEYS,
    flow_block,
    flow_edges,
    flow_graph,
)
from l1agg.capabilities.overview import (  # noqa: E402
    GRAPH_EDGE_KINDS,
    validate_graph_dataset,
)

DIRECTION_WORDS = ("看涨", "看跌", "建议", "目标价")

CORR_BLOCK = {
    "gate": "ok",
    "matrix": {"names": ["US100", "BTC"]},
    "relationship_topk": {"pairs": [{"a": "US100", "b": "BTC", "r": 0.62, "q": 0.01}]},
}


def _row(src="class:us_index", dst="class:crypto", z=1.8, **kwargs):
    row = {"src": src, "dst": dst, "flow_usdt": 1.2e9, "flow_z": z, "window": 5}
    row.update(kwargs)
    return row


# ------------------------------------------------------------ 边构造


def test_flow_edge_is_strict_five_keys():
    projected = flow_edges([_row(z=1.8)])
    assert len(projected["edges"]) == 1
    edge = projected["edges"][0]
    assert set(edge) == set(EDGE_KEYS) == {"src", "dst", "kind", "weight", "p_adj"}
    assert edge["kind"] == "flow"
    assert edge["weight"] == pytest.approx(0.6, abs=1e-9)
    assert edge["p_adj"] is None
    assert "flow" in GRAPH_EDGE_KINDS


def test_weight_capped_at_one():
    projected = flow_edges([_row(z=-9.0)])
    assert projected["edges"][0]["weight"] == 1.0
    assert projected["flows"][0]["direction"] in DIRECTIONS


def test_topk_ordering_and_edge_index_alignment():
    rows = [
        _row("A", "B", 0.5),
        _row("A", "C", -3.0),
        _row("B", "C", 1.2),
        _row("C", "D", 2.0),
        _row("D", "E", -0.1),
    ]
    projected = flow_edges(rows, topk=3)
    assert [(edge["src"], edge["dst"]) for edge in projected["edges"]] == [
        ("A", "C"),
        ("C", "D"),
        ("B", "C"),
    ]
    assert [item["edge_index"] for item in projected["flows"]] == [0, 1, 2]
    assert [abs(item["flow_z"]) for item in projected["flows"]] == [3.0, 2.0, 1.2]
    assert "flow_edges_truncated:2" in projected["flags"]


def test_invalid_rows_skipped():
    rows = [
        _row(),
        {"src": "", "dst": "B", "flow_z": 1.0},
        _row("A", "A", 1.0),
        {"src": "A", "dst": "B", "flow_z": "nan"},
        "not-a-row",
    ]
    projected = flow_edges(rows)
    assert len(projected["edges"]) == 1
    assert "flow_rows_skipped:4" in projected["flags"]


def test_direction_whitelist_and_default():
    projected = flow_edges(
        [_row(direction="into_src"), _row("X", "Y", 1.0, direction="net_into_src")]
    )
    assert projected["flows"][0]["direction"] in DIRECTIONS
    assert projected["flows"][1]["direction"] == "net_into_src"
    assert any(flag.startswith("direction_defaulted:") for flag in projected["flags"])


# ------------------------------------------------------------ 节点


def test_nodes_derived_from_endpoints():
    block = flow_block([_row(), _row("BTC", "class:precious_metal", 0.9)])
    groups = {node["id"]: node["group"] for node in block["nodes"]}
    assert groups["class:us_index"] == "class"
    assert groups["BTC"] == "asset"
    labels = {node["id"]: node["label"] for node in block["nodes"]}
    assert labels["class:us_index"] == "us_index"
    assert block["status"] == "flow"


def test_explicit_nodes_drop_missing_endpoints():
    block = flow_block(
        [_row(), _row("class:us_index", "BTC", 2.5)],
        nodes=[
            {"id": "class:us_index", "label": "美股指数", "group": "class"},
            {"id": "class:crypto", "label": "加密", "group": "class"},
        ],
    )
    assert [(edge["src"], edge["dst"]) for edge in block["edges"]] == [
        ("class:us_index", "class:crypto")
    ]
    assert "endpoint_missing:1" in block["flags"]
    assert len(block["meta"]["flows"]) == 1
    assert block["meta"]["flows"][0]["edge_index"] == 0


# ------------------------------------------------------------ 降级（LT-G7）


def test_corr_only_fallback_does_not_fabricate_edges():
    block = flow_block([], corr_block=CORR_BLOCK)
    assert block["status"] == "corr_only"
    assert block["reason"] == "flow_unavailable"
    assert block["meta"] == {"flows": [], "reason": "flow_unavailable"}
    assert {edge["kind"] for edge in block["edges"]} == {"corr"}
    validate_graph_dataset(block["visual"]["dataset"])


def test_corr_only_envelope_is_partial_and_says_degraded():
    out = flow_graph([], corr_block=CORR_BLOCK)
    assert out["ok"] is True
    assert out["capability"] == "D-E18"
    assert out["quality"]["status"] == "partial"
    assert out["quality"]["degraded_reason"] == "flow_unavailable"
    assert "降级" in out["answer"]
    assert out["data"]["visual"]["kind"] == "graph"
    assert out["data"]["capabilities"]["D-E18"]["status"] == "corr_only"


def test_no_flow_and_no_corr_is_empty():
    out = flow_graph([], corr_block=None)
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"
    assert "visual" not in out["data"]


def test_corr_block_with_failed_gate_is_treated_as_missing():
    out = flow_graph([], corr_block={"gate": "failed"})
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"


# ------------------------------------------------------------ 信封契约


def test_envelope_contract_flow_mode():
    out = flow_graph([_row(), _row("class:crypto", "class:us_index", 2.4)])
    assert out["ok"] is True
    assert out["quality"]["status"] == "good"
    visual = out["data"]["visual"]
    assert visual["kind"] == "graph"
    assert visual["spec_version"] == "1.0"
    assert visual["source_capability"] == "D-E18"
    assert visual["quality_ref"] == "quality"
    assert visual["encodings"]["group"] == "group"
    assert isinstance(visual["truncated"], bool)
    assert len(visual["title"]) <= 60
    assert len(visual["dataset"]["meta"]["flows"]) == len(visual["dataset"]["edges"])
    validate_graph_dataset(visual["dataset"])
    dumped = json.dumps(out, ensure_ascii=False)
    for word in ("signal", "order", "fill", "position", "comparison"):
        assert f'"{word}"' not in dumped
    for word in DIRECTION_WORDS:
        assert word not in dumped


def test_answer_has_no_direction_words():
    out = flow_graph([_row()])
    for word in DIRECTION_WORDS:
        assert word not in out["answer"]
    assert "历史统计，不代表未来" in out["answer"]


def test_deterministic_bytes():
    rows = [_row(), _row("class:crypto", "class:us_index", -2.4)]
    first = flow_graph(rows)
    second = flow_graph([dict(row) for row in rows])
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == json.dumps(
        second, sort_keys=True, ensure_ascii=False
    )
