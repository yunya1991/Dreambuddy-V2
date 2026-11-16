# -*- coding: utf-8 -*-
"""评估层只读出口测试（D-K01 方法推荐 / D-K02 发现查询）。"""

import json
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.capabilities import manifest, run_capability  # noqa: E402
from l1agg.capabilities.envelope import STATUS_EMPTY, STATUS_GOOD, STATUS_PARTIAL  # noqa: E402
from l1agg.capabilities.eval_exports import (  # noqa: E402
    discovery_query,
    recommend_relationship,
)
from l1agg.mers import RelationshipRegistry  # noqa: E402


def _make_registry(path, rows):
    RelationshipRegistry(path)  # 复用同一 DDL，保证表结构与生产一致
    conn = sqlite3.connect(path)
    try:
        conn.executemany(
            "INSERT INTO relationship_eval "
            "(eval_id, unit_id, method, transform, target, horizon, n, rank_ic, p_adj, "
            " stability, status, eval_at, data_version, gate_pass) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return str(path)


def _row(eval_id, method, rank_ic, status="candidate", n=300, gate_pass=1, horizon=5):
    return (
        eval_id,
        f"unit-{eval_id}",
        method,
        "pct",
        "BTC",
        horizon,
        n,
        rank_ic,
        0.01,
        0.8,
        status,
        "2026-11-15T03:10:00Z",
        "dv-1",
        gate_pass,
    )


def test_recommend_missing_registry_is_empty(tmp_path):
    out = recommend_relationship(db_path=str(tmp_path / "none.db"), target="BTC", horizon=5)
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert out["capability"] == "D-K01"


def test_recommend_without_matching_rows_is_empty(tmp_path):
    path = _make_registry(tmp_path / "r.db", [_row("e1", "M11", 0.05)])
    out = recommend_relationship(db_path=path, target="ETH", horizon=5)
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY


def test_recommend_candidate_degrades_to_partial_and_sorts_by_abs_ic(tmp_path):
    path = _make_registry(
        tmp_path / "r.db",
        [_row("e1", "M11", 0.05), _row("e2", "B13", -0.30, n=420), _row("e3", "R01", 0.12)],
    )
    out = recommend_relationship(db_path=path, target="BTC", horizon=5, top=2)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "candidate_only"
    assert out["quality"]["sample_n"] == 420
    assert "历史 420 个样本上" in out["answer"] and "|RankIC|=0.3000" in out["answer"]
    assert "候选" in out["answer"]
    block = out["data"]["capabilities"]["D-K01"]
    assert [item["method"] for item in block["rows"]] == ["B13", "R01"]
    assert block["rows"][0]["abs_rank_ic"] == pytest.approx(0.30)
    assert set(block["methods"]) <= set(manifest().get("D-K01").methods)


def test_recommend_stable_is_good_and_skips_failed_gate(tmp_path):
    path = _make_registry(
        tmp_path / "r.db",
        [
            _row("e1", "M11", 0.90, status="stable", gate_pass=0),
            _row("e2", "M02", 0.20, status="stable"),
        ],
    )
    out = recommend_relationship(db_path=path, target="BTC", horizon=5)
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["degraded_reason"] is None
    assert out["data"]["capabilities"]["D-K01"]["rows"][0]["method"] == "M02"


def test_recommend_requires_target_and_positive_horizon(tmp_path):
    with pytest.raises(ValueError):
        recommend_relationship(db_path=str(tmp_path / "r.db"), target="", horizon=5)
    with pytest.raises(ValueError):
        recommend_relationship(db_path=str(tmp_path / "r.db"), target="BTC", horizon=0)


def _write_report(root, name, findings, manifest_extra=None):
    directory = os.path.join(str(root), name)
    os.makedirs(directory, exist_ok=True)
    payload = {"space_hash": "abc", "data_version": "dv-1", "units": 5000}
    payload.update(manifest_extra or {})
    with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    with open(os.path.join(directory, "findings.jsonl"), "w", encoding="utf-8") as fh:
        for item in findings:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    return directory


def _finding(method, rank_ic, series="BTC", n=300):
    return {
        "method": method,
        "series": series,
        "transform": "pct",
        "target": "price_forward_return",
        "horizon": 5,
        "n": n,
        "rank_ic": rank_ic,
        "p_adj": 0.01,
        "stability": 0.7,
        "holdout_ic": rank_ic / 2,
        "status": "candidate",
    }


def test_discovery_missing_reports_is_empty(tmp_path):
    out = discovery_query(reports_dir=str(tmp_path / "nope"))
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY


def test_discovery_reads_latest_report_and_sorts(tmp_path):
    _write_report(tmp_path, "20261001-0310", [_finding("M11", 0.9)])
    _write_report(
        tmp_path,
        "20261115-0310",
        [_finding("M11", 0.10), _finding("B13", -0.40, series="ETH")],
    )
    out = discovery_query(reports_dir=str(tmp_path), top=5)
    assert out["quality"]["status"] == STATUS_GOOD
    block = out["data"]["capabilities"]["D-K02"]
    assert block["report"] == "20261115-0310"
    assert [item["series"] for item in block["items"]] == ["ETH", "BTC"]
    assert block["items"][0]["status"] == "candidate"
    assert "最近一期发现" in out["answer"] and "candidate" in out["answer"]
    assert set(block["methods"]) <= set(manifest().get("D-K02").methods)


def test_discovery_without_findings_degrades(tmp_path):
    _write_report(tmp_path, "20261115-0310", [])
    out = discovery_query(reports_dir=str(tmp_path))
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "no_findings"
    assert "无候选" in out["answer"]


def test_dispatcher_routes_both_capabilities(tmp_path):
    path = _make_registry(tmp_path / "r.db", [_row("e1", "M11", 0.05, status="stable")])
    out = run_capability("D-K01", db_path=path, target="BTC", horizon=5)
    assert out["capability"] == "D-K01" and out["intent"] == "relationship_recommend"

    _write_report(tmp_path / "reports", "20261115-0310", [_finding("M11", 0.05)])
    out = run_capability("D-K02", reports_dir=str(tmp_path / "reports"))
    assert out["capability"] == "D-K02" and out["intent"] == "discovery_query"


def _enrich(path, eval_id, **fields):
    keys = sorted(fields)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE relationship_eval SET "
            + ", ".join(f"{key} = ?" for key in keys)
            + " WHERE eval_id = ?",
            [fields[key] for key in keys] + [eval_id],
        )
        conn.commit()
    finally:
        conn.close()


_SCOPE = {
    "time_range": ["2020-01-01", "2026-01-01"],
    "markets": ["BTC"],
    "params": {"transform": "pct", "horizon": 5, "hit_extreme_z": 1.0},
    "sample": {"n": 300, "n_eff": 60, "n_hit": 96, "periods": 1},
}


def _gate_fields(**overrides):
    fields = {
        "hit_rate": 0.63,
        "base_rate": 0.53,
        "excess_hit": 0.10,
        "hit_rate_lb": 0.57,
        "n_eff": 60,
        "holdout_hit_rate": 0.59,
        "holdout_base_rate": 0.52,
        "holdout_agree": 1,
        "holdout_used_at": "2026-11-15T03:10:00Z",
        "effect_bps": 18.4,
        "cost_bps": 10.0,
        "perm_p": 0.002,
        "scope_json": json.dumps(_SCOPE),
    }
    fields.update(overrides)
    return fields


def test_recommend_card_exposes_gate_fields_and_table(tmp_path):
    path = _make_registry(tmp_path / "r.db", [_row("e1", "B14", 0.30)])
    _enrich(path, "e1", **_gate_fields())
    out = recommend_relationship(db_path=path, target="BTC", horizon=5)
    row = out["data"]["capabilities"]["D-K01"]["rows"][0]
    assert row["relation_type"] == "R1"
    assert row["base_rate"] == pytest.approx(0.53)
    assert row["excess_hit"] == pytest.approx(0.10)
    assert row["n_eff"] == 60
    assert row["perm_p"] == pytest.approx(0.002)
    assert row["holdout_agree"] is True
    assert row["scope"]["time_range"] == ["2020-01-01", "2026-01-01"]
    assert row["scope"]["sample"]["n_hit"] == 96
    assert "超额 +10.0%" in out["answer"] and "基线 53.0%" in out["answer"]

    visual = out["data"]["visual"]
    assert visual["kind"] == "table"
    assert visual["source_capability"] == "D-K01"
    keys = [column["key"] for column in visual["dataset"]["columns"]]
    assert keys[0] == "degraded_reason"  # candidate → partial，V-AC6
    for key in (
        "base_rate",
        "excess_hit",
        "hit_rate_lb",
        "n_eff",
        "effect_bps",
        "cost_bps",
        "perm_p",
    ):
        assert key in keys


def test_recommend_visual_variants(tmp_path):
    path = _make_registry(
        tmp_path / "r.db",
        [
            _row("e1", "B14", 0.30, status="stable"),
            _row("e2", "M11", 0.20, status="stable"),
            _row("e3", "B14", 0.10, status="stable", horizon=20),
            _row("e4", "B14", 0.24, status="stable"),
        ],
    )
    for eval_id in ("e1", "e2", "e3", "e4"):
        _enrich(path, eval_id, **_gate_fields())
    _enrich(path, "e4", eval_at="2026-09-01T00:00:00Z")

    matrix = recommend_relationship(db_path=path, target="BTC", horizon=5, viz="matrix")
    visual = matrix["data"]["visual"]
    assert visual["kind"] == "matrix"
    assert "R1" in visual["dataset"]["row_labels"]
    assert visual["dataset"]["col_labels"] == ["h5", "h20"]

    series = recommend_relationship(db_path=path, target="BTC", horizon=5, viz="series", top=1)
    visual = series["data"]["visual"]
    assert visual["kind"] == "series"
    assert len(visual["dataset"]["points"]) == 2
    assert visual["dataset"]["meta"]["smoothing"]["method"] == "none"

    graph = recommend_relationship(db_path=path, target="BTC", horizon=5, viz="graph")
    visual = graph["data"]["visual"]
    assert visual["kind"] == "graph"
    assert visual["dataset"]["nodes"][0]["id"] == "target:BTC"
    assert all(
        set(edge) == {"src", "dst", "kind", "weight", "p_adj"}
        for edge in visual["dataset"]["edges"]
    )


def test_recommend_rejects_unknown_viz(tmp_path):
    path = _make_registry(tmp_path / "r.db", [_row("e1", "M11", 0.05)])
    with pytest.raises(ValueError):
        recommend_relationship(db_path=path, target="BTC", horizon=5, viz="pie")
