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
