"""F8：reflection 样本质量修复测试。

背景：22 reconcile 产生的平仓流水 realized_pnl 恒 0，被当作亏损计入胜率，
导致 reflection_ri 永久压在 0.5。修复后：
  - reconcile 来源的 fills 不进交易索引
  - realized_pnl 与 pnl_pct 均缺失的记录标记 pnl_valid=False，不参与胜率
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dreambuddy_evolution.engines.reflection_scanner import ReflectionScanner
from dreambuddy_evolution.engines.trade_index_builder import TradeIndexBuilder


def _make_ledger(root: Path) -> Path:
    runtime = root / "22-执行引擎中心/runtime"
    runtime.mkdir(parents=True)
    db = runtime / "position_ledger.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, inst_id TEXT NOT NULL,
            pos_side TEXT NOT NULL, action TEXT NOT NULL, qty REAL NOT NULL DEFAULT 0,
            px REAL NOT NULL DEFAULT 0, fee REAL NOT NULL DEFAULT 0, realized_pnl REAL,
            ratio REAL, source TEXT DEFAULT '', decision_id TEXT DEFAULT '')""")
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        # 真实盈利交易（23 自己开的）
        (now, "BTC-USDT-SWAP", "long", "close", 1.0, 100.0, 0.0, 5.0, 0.05, "23-evolution"),
        (now, "BTC-USDT-SWAP", "long", "close", 1.0, 100.0, 0.0, 3.0, 0.03, "23-evolution"),
        # reconcile 平仓：realized_pnl 恒 0，不应计入
        (now, "BTC-USDT-SWAP", "long", "close", 1.0, 100.0, 0.0, 0.0, 0.0, "22-reconciled"),
        (now, "BTC-USDT-SWAP", "long", "close", 1.0, 100.0, 0.0, 0.0, 0.0, "22-reconciled"),
        # 收益缺失（NULL）且无 pnl_pct，应标记 pnl_valid=False
        (now, "ETH-USDT-SWAP", "short", "close", 1.0, 100.0, 0.0, None, None, "11-yijing"),
    ]
    conn.executemany(
        "INSERT INTO fills (ts,inst_id,pos_side,action,qty,px,fee,realized_pnl,ratio,source)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db


def test_reconciled_fills_excluded_from_index(tmp_path: Path) -> None:
    _make_ledger(tmp_path)
    trades = TradeIndexBuilder(project_root=str(tmp_path)).get_trades(force=True)
    btc = [t for t in trades if t["coin"] == "BTC"]
    assert len(btc) == 2, f"reconcile 平仓应被排除，实际 {len(btc)} 条"
    assert all(t["pnl"] > 0 for t in btc)


def test_missing_pnl_marked_invalid(tmp_path: Path) -> None:
    _make_ledger(tmp_path)
    trades = TradeIndexBuilder(project_root=str(tmp_path)).get_trades(force=True)
    eth = [t for t in trades if t["coin"] == "ETH"]
    assert len(eth) == 1
    assert eth[0]["pnl_valid"] is False


def test_reflection_win_rate_ignores_invalid_samples(tmp_path: Path) -> None:
    _make_ledger(tmp_path)
    stats = ReflectionScanner(project_root=str(tmp_path)).scan(force=True)
    assert stats["BTC"]["n_trades"] == 2
    assert stats["BTC"]["win_rate"] == 1.0
    assert stats["BTC"]["eligible"] is True
    assert stats["BTC"]["reflection_ri"] > 0.55
    # ETH 唯一一笔收益缺失 → 不进入统计
    assert "ETH" not in stats
