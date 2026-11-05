"""TDD RED — E6 需求单存储层测试（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E6）。

状态机：open → claimed → resolved / expired / rejected；open → expired / rejected。
"""

import capability_gaps as cg


def test_new_gap_schema(tmp_path):
    gap = cg.new_gap(
        gap_type="missing_market_data",
        evidence={"symbol": "BTC", "source": "bcrm2_real_verifier", "msg": "未找到 BTC 的K线数据"},
        expected_value="补齐 BTC 1H K线后可恢复实盘验证",
        target_domain_hint="19-数据访问层",
        created_by="test",
    )
    for key in (
        "gap_id",
        "gap_type",
        "evidence",
        "expected_value",
        "target_domain_hint",
        "created_by",
        "status",
        "created_at",
        "claimed_at",
        "claimed_by",
        "resolved_at",
        "resolution_note",
        "alert",
    ):
        assert key in gap, f"缺字段 {key}"
    assert gap["status"] == "open"
    assert gap["gap_id"].startswith("GAP-")
    assert gap["alert"] is False


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "gaps.jsonl"
    g1 = cg.new_gap("case_sparse", {"domain": "washout"}, created_by="t1")
    g2 = cg.new_gap("factor_insufficient_samples", {"factor": "f22"}, created_by="t2")
    assert cg.append_gap(g1, path) is True
    assert cg.append_gap(g2, path) is True
    loaded = cg.load_gaps(path)
    assert len(loaded) == 2
    assert loaded[0]["gap_id"] == g1["gap_id"]
    assert loaded[1]["gap_type"] == "factor_insufficient_samples"


def test_load_tolerates_bad_lines_and_missing_file(tmp_path):
    path = tmp_path / "gaps.jsonl"
    assert cg.load_gaps(path) == []  # 文件不存在 → 空，不抛异常
    path.write_text(
        '{"gap_id":"GAP-1","status":"open"}\nNOT-JSON\n{"gap_id":"GAP-2"}\n', encoding="utf-8"
    )
    loaded = cg.load_gaps(path)
    assert len(loaded) == 2


def test_status_machine_valid_path(tmp_path):
    path = tmp_path / "gaps.jsonl"
    gap = cg.new_gap("missing_market_data", {"symbol": "ETH"}, created_by="t")
    cg.append_gap(gap, path)
    assert cg.update_status(gap["gap_id"], "claimed", actor="19-数据访问层", path=path) is True
    assert cg.update_status(gap["gap_id"], "resolved", note="K线已回填", path=path) is True
    loaded = cg.load_gaps(path)
    assert loaded[0]["status"] == "resolved"
    assert loaded[0]["claimed_by"] == "19-数据访问层"
    assert loaded[0]["claimed_at"] is not None
    assert loaded[0]["resolved_at"] is not None


def test_status_machine_rejects_invalid_transition(tmp_path):
    path = tmp_path / "gaps.jsonl"
    gap = cg.new_gap("case_sparse", {"domain": "pump_dump"}, created_by="t")
    cg.append_gap(gap, path)
    # open → resolved 不允许（必须先 claimed，保证 time_to_capability 可度量）
    assert cg.update_status(gap["gap_id"], "resolved", path=path) is False
    # open → rejected 允许
    assert cg.update_status(gap["gap_id"], "rejected", note="重复单", path=path) is True
    # 终态不可再转移
    assert cg.update_status(gap["gap_id"], "claimed", path=path) is False


def test_update_missing_gap_id_returns_false(tmp_path):
    path = tmp_path / "gaps.jsonl"
    assert cg.update_status("GAP-NOT-EXIST", "claimed", path=path) is False
