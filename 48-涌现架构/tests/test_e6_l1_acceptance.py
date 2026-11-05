"""E6 L1 链路验收（SPEC v0.5 §4 E6 验收分级 L1）：构造 3 个已知可解缺口，跑通
写入 → 路由 → 认领 → 解决 → 回填验证 全链路。

三个缺口覆盖三类信号源：missing_market_data（K线缺失）、case_sparse（CBR 案例稀疏）、
factor_insufficient_samples（因子样本不足，走 proposals 外的已知映射）。
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import capability_gaps as cg
import gap_backfill_verify as gv
import gap_router as gr


def _mk_db(path, t0):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, "
        "exit_time TEXT, pnl_pct REAL)"
    )
    rows = [
        ("BTC", (t0 - timedelta(days=d, hours=3)).isoformat(), -0.005) for d in range(14, 0, -1)
    ]
    rows += [("BTC", (t0 + timedelta(days=d, hours=5)).isoformat(), 0.015) for d in range(0, 14)]
    conn.executemany("INSERT INTO trades (symbol, exit_time, pnl_pct) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_e6_l1_full_loop_three_gaps(tmp_path):
    gaps_path = tmp_path / "capability_gaps.jsonl"
    proposals_path = tmp_path / "gap_type_proposals.jsonl"
    db_path = tmp_path / "trades.db"
    t0 = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
    _mk_db(db_path, t0)

    gap_specs = [
        (
            "missing_market_data",
            {"symbol": "BTC", "source": "bcrm2_real_verifier", "msg": "未找到 BTC 的K线数据"},
        ),
        ("case_sparse", {"domain": "washout_reversal", "case_count": 2, "min_required": 10}),
        ("factor_insufficient_samples", {"factor": "exogenous_f22", "n": 30, "min_samples": 200}),
    ]

    for i, (gap_type, evidence) in enumerate(gap_specs):
        # 1. 缺口信号 → 需求单落盘（stigmergy 广播）
        gap = cg.new_gap(
            gap_type, evidence, expected_value=f"L1 验收缺口{i}", created_by="l1_acceptance"
        )
        assert cg.append_gap(gap, gaps_path) is True

        # 2. 自动路由到正确能力域（非人工指派）
        domain = gr.route_gap(gap, gaps_path=gaps_path, proposals_path=proposals_path)
        assert domain is not None, f"{gap_type} 未路由成功"

        # 3. 能力域认领 → 补齐 → 标记 resolved
        assert cg.update_status(gap["gap_id"], "claimed", actor=domain, path=gaps_path) is True
        assert (
            cg.update_status(gap["gap_id"], "resolved", note="L1 模拟补齐", path=gaps_path) is True
        )

        # 4. 回填验证（resolved_at 对齐到 t0，使前后窗口覆盖构造数据）
        loaded = [g for g in cg.load_gaps(gaps_path) if g["gap_id"] == gap["gap_id"]][0]
        loaded["resolved_at"] = t0.isoformat()
        all_gaps = cg.load_gaps(gaps_path)
        import json

        with gaps_path.open("w", encoding="utf-8") as fh:
            for g in all_gaps:
                fh.write(json.dumps(g, ensure_ascii=False) + "\n")

        result = gv.verify_gap_resolution(gap["gap_id"], gaps_path=gaps_path, db_path=db_path)
        assert result["status"] == "ok", f"缺口{i} 回填验证失败: {result}"
        assert result["improved"] is True

    # 汇总：3 单全部 resolved，路由率 100%
    final = cg.load_gaps(gaps_path)
    assert len(final) == 3
    assert all(g["status"] == "resolved" for g in final)
    assert all(g["claimed_by"] for g in final)
    # 无未知类型 → proposals 文件不应存在
    assert not proposals_path.exists()
