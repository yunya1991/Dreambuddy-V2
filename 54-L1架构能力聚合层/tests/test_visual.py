# -*- coding: utf-8 -*-
"""T1 表格生产者 + B10 基线冻结（SPEC-54-统计图表化能力 §4.2/§4.3/§5/§7）。

覆盖：
  - V-AC5：D-E12 固定 8 列、`n_scope="per_row"`；
  - V-AC6：`partial` 表格首列 `degraded_reason`；
  - V-AC7：`L1_VISUAL_ENABLED=0` 全无 `visual`；
  - V-AC1（B10）：14 个基线出口契约冻结；
  - T1 元表：能力清单表 + 方法审计 386×6 矩阵表。
"""

import datetime
import json
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.capabilities import build, manifest, quality_for, run_capability, supported  # noqa: E402
from l1agg.capabilities.visual import (  # noqa: E402
    AUDIT_CHECKS,
    SLOPE_COLUMNS,
    capability_table,
    method_audit_table,
    slope_table,
)

# B10 基线冻结：SPEC §7 V-AC1 的 `baseline_outlets`（2026-11-15 实测 14 条）。
BASELINE_OUTLETS = {
    "D-A14": {
        "intent": "metric_percentile",
        "mode": "deterministic",
        "methods": ["F26"],
        "min_n": 60,
    },
    "D-E01": {
        "intent": "conditional_return",
        "mode": "deterministic",
        "methods": ["B02", "B05", "F01", "H01"],
        "min_n": 250,
    },
    "D-E02": {
        "intent": "metric_percentile",
        "mode": "deterministic",
        "methods": ["I30", "R02"],
        "min_n": 250,
    },
    "D-E03": {
        "intent": "seasonality_query",
        "mode": "deterministic",
        "methods": ["C01", "C02", "C03", "C04", "C05", "C07", "C09", "C12", "C13", "C14", "C15"],
        "min_n": 60,
    },
    "D-E04": {
        "intent": "event_study",
        "mode": "deterministic",
        "methods": ["F19", "F21", "F23"],
        "min_n": 250,
    },
    "D-E05": {
        "intent": "correlation_query",
        "mode": "deterministic",
        "methods": ["M01", "M02", "M03", "M04", "M05", "M06", "M07", "M23"],
        "min_n": 60,
    },
    "D-E06": {
        "intent": "correlation_query",
        "mode": "deterministic",
        "methods": ["T03", "T04", "M11", "M12"],
        "min_n": 120,
    },
    "D-E07": {
        "intent": "state_transition",
        "mode": "deterministic",
        "methods": ["B02", "B06", "B07", "B08", "B09"],
        "min_n": 100,
    },
    "D-E08": {
        "intent": "conditional_return",
        "mode": "deterministic",
        "methods": ["B11", "B13", "B14"],
        "min_n": 250,
    },
    "D-E09": {
        "intent": "metric_series",
        "mode": "deterministic",
        "methods": ["R09", "B17", "R10"],
        "min_n": 3,
    },
    "D-E10": {
        "intent": "drawdown_query",
        "mode": "deterministic",
        "methods": ["D20", "D21"],
        "min_n": 250,
    },
    "D-E11": {
        "intent": "cross_check",
        "mode": "gated",
        "methods": ["M23", "M24", "M25", "C18"],
        "min_n": 60,
    },
    "D-E12": {"intent": "cross_check", "mode": "gated", "methods": ["R18"], "min_n": 30},
    "D-G22": {
        "intent": "significance_query",
        "mode": "deterministic",
        "methods": ["Q06", "Q07"],
        "min_n": 250,
    },
}


def _dates(n=40, start=datetime.date(2024, 1, 1)):
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _alignment_kwargs(n=40):
    return {
        "series": {
            "BTC": [100.0 + i for i in range(n)],
            "ETH": [50.0 + 2 * i for i in range(n)],
        },
        "dates": _dates(n),
        "window": min(n, 30),
    }


def _degraded_visual(status="partial"):
    data = {
        "capabilities": {
            "D-E12": {
                "gate": "ok",
                "methods": ["R18"],
                "window": "2024-01-01~2024-01-30",
                "window_rows": [
                    {
                        "asset": "BTC",
                        "start_value": 100.0,
                        "end_value": 129.0,
                        "ret": 0.29,
                        "n_obs": 12,
                        "stale_ratio": 0.6,
                        "first_date": "2024-01-01",
                        "last_date": "2024-01-30",
                    }
                ],
            }
        }
    }
    block = quality_for(12, min_n=30) if status == "partial" else None
    from l1agg.capabilities.visual import build_visual

    return build_visual(capability="D-E12", data=data, quality_block=block)


# ---------------- V-AC5：D-E12 表格 ----------------


def test_d_e12_visual_is_fixed_eight_column_table():
    out = run_capability("D-E12", **_alignment_kwargs())
    visual = out["data"]["visual"]
    assert visual["kind"] == "table"
    assert visual["spec_version"] == "1.0"
    assert visual["source_capability"] == "D-E12"
    assert visual["n_scope"] == "per_row"
    assert visual["quality_ref"] == "quality"
    assert visual["caveat"] == "历史统计，不代表未来"
    assert visual["truncated"] is False
    assert len(visual["title"]) <= 60
    keys = [col["key"] for col in visual["dataset"]["columns"]]
    assert keys == [
        "asset",
        "start_value",
        "end_value",
        "ret",
        "n_obs",
        "stale_ratio",
        "first_date",
        "last_date",
    ]
    rows = {row["asset"]: row for row in visual["dataset"]["rows"]}
    block_rows = {row["asset"]: row for row in out["data"]["capabilities"]["D-E12"]["window_rows"]}
    assert rows == block_rows
    assert visual["dataset"]["groups"] == ["asset"]


def test_d_e12_visual_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    out = run_capability("D-E12", **_alignment_kwargs())
    jsonschema.validate(instance=out, schema=schema)


# ---------------- V-AC6 / V-G1 / V-G2：降级与不产图 ----------------


def test_partial_quality_puts_degraded_reason_first():
    visual = _degraded_visual()
    assert visual["dataset"]["columns"][0]["key"] == "degraded_reason"
    assert len(visual["dataset"]["columns"]) == 9
    assert visual["dataset"]["rows"][0]["degraded_reason"] == "insufficient_samples"


def test_empty_quality_or_bad_gate_produces_no_visual(monkeypatch):
    out = run_capability("D-E12", **_alignment_kwargs(10))
    assert out["ok"] is False
    assert "visual" not in out["data"]

    from l1agg.capabilities.visual import build_visual

    data = {"capabilities": {"D-E12": {"gate": "insufficient_samples", "methods": ["R18"]}}}
    q = quality_for(40, min_n=30)
    assert build_visual(capability="D-E12", data=data, quality_block=q) is None


# ---------------- V-AC7：开关 + 加法式唯一差异 ----------------


def test_visual_is_additive_only_and_switchable(monkeypatch):
    enabled_out = run_capability("D-E12", **_alignment_kwargs())
    assert "visual" in enabled_out["data"]
    monkeypatch.setenv("L1_VISUAL_ENABLED", "0")
    disabled_out = run_capability("D-E12", **_alignment_kwargs())
    assert "visual" not in disabled_out["data"]
    stripped = dict(enabled_out["data"])
    stripped.pop("visual")
    assert stripped == disabled_out["data"]


# ---------------- 信封契约校验 ----------------


def test_envelope_rejects_visual_contract_violations():
    q = quality_for(40, min_n=30)
    bad = {
        "kind": "table",
        "spec_version": "1.0",
        "title": "测试",
        "source_capability": "D-E10",
        "n_scope": "per_row",
        "dataset": {"columns": [], "rows": [], "groups": []},
        "encodings": {},
        "quality_ref": "quality",
        "caveat": "历史统计，不代表未来",
        "truncated": False,
    }
    with pytest.raises(ValueError):
        build(
            capability="D-E12",
            intent="cross_check",
            answer="对齐完成",
            data={},
            quality_block=q,
            visual=bad,
        )

    overflow = dict(bad)
    overflow["source_capability"] = "D-E12"
    overflow["dataset"] = {
        "columns": [{"key": "asset", "label": "资产", "type": "string"}],
        "rows": [{"asset": "X"}] * 501,
        "groups": [],
    }
    with pytest.raises(ValueError):
        build(
            capability="D-E12",
            intent="cross_check",
            answer="对齐完成",
            data={},
            quality_block=q,
            visual=overflow,
        )


# ---------------- T1 元表 ----------------


def test_capability_table_covers_manifest():
    table = capability_table()
    caps = manifest().capabilities
    assert len(table["rows"]) == len(caps)
    assert [row["id"] for row in table["rows"]] == [cap.id for cap in caps]
    by_id = {row["id"]: row for row in table["rows"]}
    assert by_id["D-E15"]["visibility"] == "public"
    for cap in caps:
        row = by_id[cap.id]
        assert row["intent"] == cap.intent
        assert row["mode"] == cap.mode
        assert row["visibility"] == cap.visibility
        assert row["methods"] == ",".join(cap.methods)
        assert row["n_methods"] == len(cap.methods)
        assert row["min_n"] == cap.min_n
    assert table["groups"] == ["intent", "mode", "visibility"]
    assert [col["key"] for col in table["columns"]][:2] == ["id", "intent"]


def test_method_audit_table_is_386_by_6_matrix():
    path = os.path.join(_MODULE_ROOT, "docs", "method_audit.json")
    if not os.path.exists(path):
        pytest.skip("method_audit.json 未生成")
    with open(path, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    table = method_audit_table(path)
    assert len(table["rows"]) == report["summary"]["implemented"]
    assert [col["key"] for col in table["columns"]] == ["method_id", *AUDIT_CHECKS]
    allowed = {"pass", "fail", "n/a", "missing"}
    for row in table["rows"]:
        assert set(row) == {"method_id", *AUDIT_CHECKS}
        assert all(row[name] in allowed for name in AUDIT_CHECKS)


# ---------------- B10 基线冻结 ----------------


def test_baseline_outlets_are_frozen():
    m = manifest()
    for cap_id, spec in BASELINE_OUTLETS.items():
        cap = m.get(cap_id)
        assert cap.intent == spec["intent"], cap_id
        assert cap.mode == spec["mode"], cap_id
        assert list(cap.methods) == spec["methods"], cap_id
        assert cap.min_n == spec["min_n"], cap_id
        assert cap.visibility == "public", cap_id
    assert set(BASELINE_OUTLETS) <= set(supported())


# ---------------- T2：D-E10 回撤曲线 ----------------


def _drawdown_kwargs(n=400):
    prices = []
    for i in range(n):
        if i < 100:
            prices.append(100.0 + i)
        elif i < 200:
            prices.append(200.0 - 0.4 * (i - 100))
        else:
            prices.append(160.0 + 0.2 * (i - 200))
    return {"prices": prices, "dates": _dates(n), "symbol": "BTC"}


def test_d_e10_visual_is_series_matching_block_scalars():
    out = run_capability("D-E10", **_drawdown_kwargs())
    block = out["data"]["capabilities"]["D-E10"]
    visual = out["data"]["visual"]
    assert visual["kind"] == "series"
    assert visual["spec_version"] == "1.0"
    assert visual["source_capability"] == "D-E10"
    assert visual["n_scope"] == "global"
    assert visual["truncated"] is False
    assert len(visual["title"]) <= 60
    points = visual["dataset"]["points"]
    assert 1 <= len(points) <= 500
    assert points[0]["y"] == 0.0
    assert points[-1]["y"] == pytest.approx(block["current_drawdown"])
    assert max(point["y"] for point in points) == pytest.approx(block["mdd"])
    meta = visual["dataset"]["meta"]
    assert meta["smoothing"] == {"method": "none", "window": 1}
    assert meta["unit"] == "ratio"
    assert meta["n"] == 400


def test_d_e10_visual_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    out = run_capability("D-E10", **_drawdown_kwargs())
    jsonschema.validate(instance=out, schema=schema)


def test_drawdown_path_without_dates_uses_index_as_x():
    kwargs = _drawdown_kwargs()
    kwargs.pop("dates")
    out = run_capability("D-E10", **kwargs)
    assert out["data"]["visual"]["dataset"]["points"][0]["x"] == 0


# ---------------- T2：D-E15 曲线 + 斜率表 ----------------


def _trend_kwargs(n=700):
    prices = [100.0 + i * 0.1 + (i % 7) * 0.5 for i in range(n)]
    return {"prices": prices, "dates": _dates(n), "symbol": "BTC"}


def test_d_e15_visual_is_series_with_smoothing_meta():
    out = run_capability("D-E15", **_trend_kwargs())
    block = out["data"]["capabilities"]["D-E15"]
    visual = out["data"]["visual"]
    assert visual["kind"] == "series"
    assert visual["source_capability"] == "D-E15"
    assert len(visual["title"]) <= 60
    points = visual["dataset"]["points"]
    assert len(points) == len(block["smoothed"]) <= 500
    assert points[-1]["y"] == block["prices"][-1]
    assert points[-1]["smoothed"] == block["smoothed"][-1]["ema26"]
    meta = visual["dataset"]["meta"]
    assert meta["smoothing"] == {"method": "EMA", "window": 26}
    assert meta["unit"] == "price"
    assert meta["n"] == 700
    assert meta["periods"] == [12, 26, 50]
    assert meta["slope_windows"] == [20, 60, 120, 250]


def test_d_e15_visual_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    out = run_capability("D-E15", **_trend_kwargs())
    jsonschema.validate(instance=out, schema=schema)


def test_slope_table_has_fixed_six_columns_and_keeps_nulls():
    out = run_capability("D-E15", **_trend_kwargs(n=120))
    block = out["data"]["capabilities"]["D-E15"]
    table = slope_table(block)
    assert [col["key"] for col in table["columns"]] == [
        "window",
        "slope",
        "se",
        "t",
        "r2",
        "hac_corrected",
    ]
    assert table["columns"] == SLOPE_COLUMNS
    assert [row["window"] for row in table["rows"]] == [20, 60, 120, 250]
    assert all(row["hac_corrected"] is False for row in table["rows"])
    long_row = next(row for row in table["rows"] if row["window"] == 250)
    assert long_row["slope"] is None
    assert long_row["hac_corrected"] is False


def test_visual_titles_and_answers_have_no_direction_wording():
    banned = ("看涨", "看跌", "买入", "卖出", "建议", "目标价", "阻力最小方向是")
    for out in (
        run_capability("D-E10", **_drawdown_kwargs()),
        run_capability("D-E15", **_trend_kwargs()),
    ):
        text = out["answer"] + out["data"]["visual"]["title"]
        assert not any(word in text for word in banned)


def test_envelope_rejects_series_without_meta():
    q = quality_for(40, min_n=30)
    visual = {
        "kind": "series",
        "spec_version": "1.0",
        "title": "测试曲线",
        "source_capability": "D-E10",
        "n_scope": "global",
        "dataset": {"points": [{"x": "2024-01-01", "y": 0.0}]},
        "encodings": {"x": "date", "y": "value"},
        "quality_ref": "quality",
        "caveat": "历史统计，不代表未来",
        "truncated": False,
    }
    with pytest.raises(ValueError):
        build(
            capability="D-E10",
            intent="drawdown_query",
            answer="回撤完成",
            data={},
            quality_block=q,
            visual=visual,
        )


# ---------------- T3：全景思维导图（tree + graph，B8 降级契约） ----------------


def _overview_blocks():
    return {
        "D-E05": {
            "gate": "ok",
            "methods": ["M05", "M06", "M07"],
            "matrix": {
                "names": ["BTC", "ETH", "SOL"],
                "matrix": [[1.0, 0.81, 0.42], [0.81, 1.0, 0.55], [0.42, 0.55, 1.0]],
                "n": 200,
            },
            "average_correlation": {"avg_abs_r": 0.5933333, "n": 3},
            "relationship_topk": {
                "pairs": [
                    {"a": "BTC", "b": "ETH", "r": 0.81, "p": 0.0, "q": 0.01},
                    {"a": "ETH", "b": "SOL", "r": 0.55, "p": 0.001, "q": 0.02},
                ],
                "topk": [
                    {"a": "BTC", "b": "ETH", "r": 0.81, "p": 0.0, "q": 0.01},
                    {"a": "ETH", "b": "SOL", "r": 0.55, "p": 0.001, "q": 0.02},
                ],
            },
        },
        "D-E06": {"gate": "ok", "best_lag": 2, "best_ccf": 0.3100001, "best_q": 0.02},
        "D-E11": {"gate": "ok", "cycle_alignment": {"ratio": 0.67, "n": 24}},
        "D-G22": {"gate": "ok", "newey_west": {"t_nw": 2.43, "se": 0.01, "lag": 5}},
        "D-E10": {"gate": "ok", "mdd": 0.3123, "current_drawdown": 0.0543},
        "D-A14": {"gate": "ok", "score": 0.71, "percentile": 83.2, "level": "拥挤"},
        "D-E12": {
            "gate": "ok",
            "window": "2024-01-01~2024-06-30",
            "window_rows": [
                {"asset": "BTC", "n_obs": 180, "stale_ratio": 0.0},
                {"asset": "ETH", "n_obs": 0, "stale_ratio": 1.0},
            ],
        },
    }


def _walk_tree(node, out=None):
    out = {} if out is None else out
    out[node["id"]] = node
    for child in node.get("children") or ():
        _walk_tree(child, out)
    return out


def _leaves(node):
    if not node.get("children"):
        yield node
    for child in node.get("children") or ():
        yield from _leaves(child)


def test_t3_tree_leaves_project_capability_blocks_without_recompute():
    from l1agg.capabilities.overview import TREE_LAYOUT, _dig, build_tree

    blocks = _overview_blocks()
    visual = build_tree(blocks=blocks, as_of="2024-06-30")
    assert visual["kind"] == "tree"
    assert visual["spec_version"] == "1.0"
    assert visual["source_capability"] == "T3"
    assert visual["n_scope"] == "global"
    assert visual["encodings"] == {"label": "label", "value": "value"}
    assert visual["truncated"] is False
    nodes = _walk_tree(visual["dataset"]["root"])
    assert len(nodes) <= 300

    checked = 0
    for category_id, _, specs in TREE_LAYOUT:
        for leaf_id, _, capability, path, _unit in specs:
            node = nodes[f"{category_id}.{leaf_id}"]
            expected = _dig(blocks[capability], path)
            assert node["meta"]["capability"] == capability
            assert abs(node["value"] - expected) <= 1e-9
            checked += 1
    assert checked == 12

    # D-E12 逐资产 n_obs 也必须是原样投影（0 保留，不隐藏）
    assert nodes["resonance.alignment.0"]["value"] == 180
    assert nodes["resonance.alignment.1"]["value"] == 0


def test_t3_tree_marks_missing_sources_as_unavailable():
    from l1agg.capabilities.overview import build_tree, validate_tree_dataset

    visual = build_tree(blocks={}, as_of="2024-06-30")
    validate_tree_dataset(visual["dataset"])
    for leaf in _leaves(visual["dataset"]["root"]):
        meta = leaf["meta"]
        if "capability" in meta or "series_id" in meta:
            assert leaf["value"] is None
            assert meta.get("reason"), leaf["id"]
    nodes = _walk_tree(visual["dataset"]["root"])
    assert nodes["relationship_recommend.s5"]["value"] is None
    assert nodes["relationship_recommend.s5"]["meta"]["reason"] == "S5 未开放"
    assert nodes["flow.netflow"]["value"] is None
    assert "加密巨鲸" in nodes["flow.netflow"]["meta"]["reason"]

    # 门禁未通过同样必须显式降级，不得给 0
    degraded = _overview_blocks()
    degraded["D-E10"] = {"gate": "insufficient_history"}
    visual = build_tree(blocks=degraded)
    nodes = _walk_tree(visual["dataset"]["root"])
    assert nodes["performance.mdd"]["value"] is None
    assert "门禁未通过" in nodes["performance.mdd"]["meta"]["reason"]


def test_t3_series_leaf_requires_proxy_unit_sign_flip_and_crypto_scope():
    from l1agg.capabilities.overview import SERIES_REGISTRY, build_tree

    series_id = "exchanges_whales::whale_netflow_to_ex_usd"
    spec = SERIES_REGISTRY[series_id]
    visual = build_tree(
        blocks=_overview_blocks(),
        series_inputs=[{"asset": "BTC", "series_id": series_id, "value": 2.5}],
    )
    nodes = _walk_tree(visual["dataset"]["root"])
    leaf = nodes["flow.0"]
    assert leaf["meta"]["series_id"] == series_id
    assert leaf["meta"]["proxy"] is True
    assert leaf["meta"]["unit"] == spec["unit"]
    assert leaf["meta"]["sign_flip"] == -1.0
    # 落库为「转出-转入」，展示净流入必须乘 sign_flip
    assert leaf["value"] == pytest.approx(2.5 * -1.0)

    # 非加密资产禁止用加密巨鲸口径冒充资金流
    visual = build_tree(
        blocks=_overview_blocks(),
        series_inputs=[{"asset": "AAPL", "series_id": series_id, "value": 2.5}],
    )
    leaf = _walk_tree(visual["dataset"]["root"])["flow.0"]
    assert leaf["value"] is None
    assert "非加密资产" in leaf["meta"]["reason"]

    # 未登记序列不冒充，降级为 unavailable
    visual = build_tree(
        blocks={}, series_inputs=[{"asset": "BTC", "series_id": "mystery::flow", "value": 1.0}]
    )
    leaf = _walk_tree(visual["dataset"]["root"])["flow.0"]
    assert leaf["value"] is None
    assert "未登记的 L0 序列" in leaf["meta"]["reason"]

    from l1agg.capabilities.overview import _leaf

    with pytest.raises(ValueError):
        _leaf(
            node_id="x",
            label="x",
            value=1.0,
            series_id="mystery::flow",
            proxy=True,
            unit="亿美元",
            sign_flip=-1.0,
        )

    with pytest.raises(ValueError):
        _leaf(
            node_id="x",
            label="x",
            value=1.0,
            series_id=series_id,
            proxy=False,
            unit=spec["unit"],
            sign_flip=-1.0,
        )
    with pytest.raises(ValueError):
        _leaf(
            node_id="x",
            label="x",
            value=1.0,
            series_id=series_id,
            proxy=True,
            unit="",
            sign_flip=-1.0,
        )
    with pytest.raises(ValueError):
        _leaf(
            node_id="x",
            label="x",
            value=1.0,
            series_id=series_id,
            proxy=True,
            unit=spec["unit"],
            sign_flip=1.0,
        )


def test_t3_graph_edges_use_whitelisted_kind_and_caps():
    from l1agg.capabilities.overview import GRAPH_EDGE_KINDS, build_graph, validate_graph_dataset

    visual = build_graph(blocks=_overview_blocks())
    assert visual["kind"] == "graph"
    assert visual["source_capability"] == "T3"
    assert visual["encodings"] == {"group": "group"}
    dataset = visual["dataset"]
    assert [node["id"] for node in dataset["nodes"]] == ["BTC", "ETH", "SOL"]
    assert len(dataset["edges"]) == 2
    for edge in dataset["edges"]:
        assert edge["kind"] in GRAPH_EDGE_KINDS
        assert set(edge) == {"src", "dst", "kind", "weight", "p_adj"}
    assert dataset["edges"][0]["weight"] == 0.81
    assert dataset["edges"][0]["p_adj"] == 0.01

    bad = {
        "nodes": [{"id": "A", "label": "A"}],
        "edges": [{"src": "A", "dst": "B", "kind": "corr", "weight": 1.0, "p_adj": None}],
    }
    with pytest.raises(ValueError):
        validate_graph_dataset(bad)
    bad_kind = {
        "nodes": [{"id": "A", "label": "A"}, {"id": "B", "label": "B"}],
        "edges": [{"src": "A", "dst": "B", "kind": "causal", "weight": 1.0, "p_adj": None}],
    }
    with pytest.raises(ValueError):
        validate_graph_dataset(bad_kind)
    assert build_graph(blocks={"D-E05": {"gate": "insufficient_history"}}) is None


def test_envelope_rejects_tree_leaves_without_source():
    from l1agg.capabilities.overview import build_tree

    q = quality_for(40, min_n=30)
    visual = build_tree(blocks=_overview_blocks())
    broken = json.loads(json.dumps(visual))
    broken["dataset"]["root"]["children"][0]["children"][0]["meta"] = {}
    with pytest.raises(ValueError):
        build(
            capability="T3",
            intent="cross_check",
            answer="全景完成",
            data={},
            quality_block=q,
            visual=broken,
        )

    ok = build(
        capability="T3",
        intent="cross_check",
        answer="全景完成",
        data={},
        quality_block=q,
        visual=visual,
    )
    assert ok["data"]["visual"]["kind"] == "tree"


def test_t3_visuals_validate_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    from l1agg.capabilities.overview import build_graph, build_tree

    jsonschema.validate(
        instance=build_tree(blocks=_overview_blocks()), schema=schema["$defs"]["visual"]
    )
    jsonschema.validate(
        instance=build_graph(blocks=_overview_blocks()), schema=schema["$defs"]["visual"]
    )


def test_t3_tree_has_no_direction_wording():
    from l1agg.capabilities.overview import build_tree

    banned = ("看涨", "看跌", "买入", "卖出", "建议", "目标价", "阻力最小方向是")
    visual = build_tree(blocks=_overview_blocks(), as_of="2024-06-30")
    for leaf in _leaves(visual["dataset"]["root"]):
        text = leaf["label"] + str(leaf["meta"].get("reason") or "")
        assert not any(word in text for word in banned)
    assert not any(word in visual["title"] for word in banned)
