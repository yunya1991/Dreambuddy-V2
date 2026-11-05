"""TDD RED — E6 路由器测试（gap_type → 能力域映射 + 超时扫描 + FAIL-OPEN）。"""

import json
from datetime import datetime, timedelta, timezone

import capability_gaps as cg
import gap_router as gr


def _mk_gap(path, gap_type, created_at):
    gap = cg.new_gap(gap_type, {"probe": True}, created_by="test")
    gap["created_at"] = created_at
    cg.append_gap(gap, path)
    return gap


def test_route_known_types(tmp_path):
    path = tmp_path / "gaps.jsonl"
    proposals = tmp_path / "proposals.jsonl"
    cases = {
        "missing_market_data": "19-数据访问层",
        "missing_fundamental_data": "19-数据访问层",
        "factor_insufficient_samples": "因子工程",
        "case_sparse": "evolution-case-ingest",
        "coupling_unsupported": "19-数据访问层",
    }
    for gap_type, expected_domain in cases.items():
        gap = cg.new_gap(gap_type, {"probe": True}, created_by="t")
        assert gr.route_gap(gap, gaps_path=path, proposals_path=proposals) == expected_domain


def test_route_unknown_type_goes_to_proposals(tmp_path):
    path = tmp_path / "gaps.jsonl"
    proposals = tmp_path / "proposals.jsonl"
    gap = cg.new_gap("totally_new_gap_kind", {"x": 1}, created_by="t")
    assert gr.route_gap(gap, gaps_path=path, proposals_path=proposals) is None  # FAIL-OPEN
    lines = proposals.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    proposal = json.loads(lines[0])
    assert proposal["gap_type"] == "totally_new_gap_kind"
    assert proposal["status"] == "pending_human_review"


def test_scan_timeouts_alert_and_expire(tmp_path):
    path = tmp_path / "gaps.jsonl"
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    # 49 小时前创建，仍 open → 应 alert
    g_alert = _mk_gap(path, "case_sparse", (now - timedelta(hours=49)).isoformat())
    # 8 天前创建，仍 open → 应 expired
    g_expire = _mk_gap(path, "case_sparse", (now - timedelta(days=8)).isoformat())
    # 1 小时前创建 → 不动
    g_fresh = _mk_gap(path, "case_sparse", (now - timedelta(hours=1)).isoformat())

    result = gr.scan_timeouts(gaps_path=path, now=now)
    assert g_alert["gap_id"] in result["alerted"]
    assert g_expire["gap_id"] in result["expired"]
    assert g_fresh["gap_id"] not in result["alerted"] + result["expired"]

    loaded = {g["gap_id"]: g for g in cg.load_gaps(path)}
    assert loaded[g_alert["gap_id"]]["alert"] is True
    assert loaded[g_alert["gap_id"]]["status"] == "open"
    assert loaded[g_expire["gap_id"]]["status"] == "expired"


def test_scan_timeouts_fail_open_on_missing_file(tmp_path):
    result = gr.scan_timeouts(gaps_path=tmp_path / "nonexistent.jsonl")
    assert result == {"alerted": [], "expired": []}
