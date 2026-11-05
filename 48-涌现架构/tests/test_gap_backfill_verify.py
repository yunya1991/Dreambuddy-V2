"""TDD RED — E6 回填验证测试（SPEC v0.5 §4 E6 P1 M7 口径）。

口径修正（2026-11-05 落地时实证）：SPEC 原文数据源 all_trades.jsonl 更新止于 2026-10-13，
改用 E0b 同源 bcrm_trades.db（trades 表 exit_time + pnl_pct，实盘真实成交）。
前后各 14 个自然日，无交易日 pnl 计 0，Wilcoxon signed-rank 配对检验。
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import capability_gaps as cg
import gap_backfill_verify as gv


def _mk_db(path, rows):
    """rows: [(exit_time_iso, pnl_pct), ...]"""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, "
        "exit_time TEXT, pnl_pct REAL)"
    )
    conn.executemany("INSERT INTO trades (symbol, exit_time, pnl_pct) VALUES ('BTC', ?, ?)", rows)
    conn.commit()
    conn.close()


def _mk_resolved_gap(path, resolved_at):
    gap = cg.new_gap("missing_market_data", {"symbol": "BTC"}, created_by="t")
    cg.append_gap(gap, path)
    cg.update_status(gap["gap_id"], "claimed", actor="19-数据访问层", path=path)
    cg.update_status(gap["gap_id"], "resolved", note="已补齐", path=path)
    loaded = cg.load_gaps(path)[0]
    # 测试直接覆写 resolved_at（绕过真实时间）
    loaded["resolved_at"] = resolved_at.isoformat()
    path.write_text(
        "\n".join(__import__("json").dumps(g, ensure_ascii=False) for g in [loaded]) + "\n",
        encoding="utf-8",
    )
    return loaded


def test_verify_improvement_significant(tmp_path):
    gaps_path = tmp_path / "gaps.jsonl"
    db_path = tmp_path / "trades.db"
    t0 = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
    rows = []
    # 前 14 天：每日一笔亏损单（-1%），d=14 对齐窗口左界内 3 小时
    for d in range(14, 0, -1):
        rows.append(((t0 - timedelta(days=d) + timedelta(hours=3)).isoformat(), -0.01))
    # 后 14 天：每日一笔盈利单（+2%）
    for d in range(0, 14):
        rows.append(((t0 + timedelta(days=d, hours=5)).isoformat(), 0.02))
    _mk_db(db_path, rows)
    gap = _mk_resolved_gap(gaps_path, t0)

    result = gv.verify_gap_resolution(gap["gap_id"], gaps_path=gaps_path, db_path=db_path)
    assert result["status"] == "ok"
    assert result["improved"] is True
    assert result["p_value"] < 0.05
    assert result["significant"] is True
    assert result["before_active_days"] == 14
    assert result["after_active_days"] == 14
    assert result["after_mean"] > result["before_mean"]


def test_verify_no_improvement(tmp_path):
    gaps_path = tmp_path / "gaps.jsonl"
    db_path = tmp_path / "trades.db"
    t0 = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
    rows = [((t0 - timedelta(days=d, hours=3)).isoformat(), 0.01) for d in range(14, 0, -1)]
    rows += [((t0 + timedelta(days=d, hours=5)).isoformat(), -0.01) for d in range(0, 14)]
    _mk_db(db_path, rows)
    gap = _mk_resolved_gap(gaps_path, t0)

    result = gv.verify_gap_resolution(gap["gap_id"], gaps_path=gaps_path, db_path=db_path)
    assert result["status"] == "ok"
    assert result["improved"] is False
    assert result["significant"] is False


def test_verify_insufficient_data(tmp_path):
    gaps_path = tmp_path / "gaps.jsonl"
    db_path = tmp_path / "trades.db"
    t0 = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
    # 只有前窗口 3 天有交易，后窗口无交易 → 不足 min_days
    rows = [((t0 - timedelta(days=d, hours=3)).isoformat(), 0.01) for d in (3, 2, 1)]
    _mk_db(db_path, rows)
    gap = _mk_resolved_gap(gaps_path, t0)

    result = gv.verify_gap_resolution(gap["gap_id"], gaps_path=gaps_path, db_path=db_path)
    assert result["status"] == "insufficient_data"
    assert "improved" not in result


def test_verify_gap_not_resolved_or_missing(tmp_path):
    gaps_path = tmp_path / "gaps.jsonl"
    db_path = tmp_path / "trades.db"
    _mk_db(db_path, [])
    gap = cg.new_gap("case_sparse", {"d": 1}, created_by="t")
    cg.append_gap(gap, gaps_path)
    # 未 resolved
    r1 = gv.verify_gap_resolution(gap["gap_id"], gaps_path=gaps_path, db_path=db_path)
    assert r1["status"] == "skip_not_resolved"
    # gap 不存在
    r2 = gv.verify_gap_resolution("GAP-NOPE", gaps_path=gaps_path, db_path=db_path)
    assert r2["status"] == "error"
