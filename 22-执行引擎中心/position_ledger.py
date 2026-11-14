"""22 统一持仓账本（P2）。

定位：22 是「持仓数量 + 已实现盈亏」的唯一真相源，NN 与 23 共用；
11 只读，不再承担 23 的部分减仓落账。

设计：
- 追加式 fills 表（每次成交一条）+ positions 聚合表（当前持仓）；
- 只落账，不做风控/决策；
- FAIL-OPEN：任何异常由调用方（Gateway）吞掉，不影响下单。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "22-执行引擎中心" / "runtime" / "position_ledger.db"

_EPS = 1e-9


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PositionLedger:
    """SQLite 持仓账本。线程安全（进程内锁 + 独立连接）。"""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        env_path = os.getenv("POSITION_LEDGER_PATH")
        self.path = Path(db_path or env_path or _DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ── 基础设施 ──────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    inst_id TEXT NOT NULL,
                    pos_side TEXT NOT NULL,
                    qty REAL NOT NULL DEFAULT 0,
                    avg_entry REAL NOT NULL DEFAULT 0,
                    entry_known INTEGER NOT NULL DEFAULT 1,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    source TEXT DEFAULT '',
                    opened_at TEXT,
                    updated_at TEXT,
                    closed_at TEXT,
                    PRIMARY KEY (inst_id, pos_side)
                );
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    inst_id TEXT NOT NULL,
                    pos_side TEXT NOT NULL,
                    action TEXT NOT NULL,
                    qty REAL NOT NULL DEFAULT 0,
                    px REAL NOT NULL DEFAULT 0,
                    fee REAL NOT NULL DEFAULT 0,
                    realized_pnl REAL,
                    ratio REAL,
                    source TEXT DEFAULT '',
                    decision_id TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_fills_inst
                    ON fills (inst_id, pos_side, id DESC);
                """)

    # ── 写 ────────────────────────────────────────────────────────
    def record_open(
        self,
        inst_id: str,
        pos_side: str,
        qty: float,
        px: float,
        source: str = "",
        ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """开仓/加仓：按数量加权更新均价。"""
        _qty, _px = float(qty or 0), float(px or 0)
        if _qty <= 0 or _px <= 0:
            return {"ok": False, "reason": "invalid_qty_or_px"}
        _ts = ts or _utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT qty, avg_entry, entry_known FROM positions WHERE inst_id=? AND pos_side=?",
                (inst_id, pos_side),
            ).fetchone()
            _old_qty = float(row["qty"]) if row else 0.0
            _old_avg = float(row["avg_entry"]) if row else 0.0
            _known = int(row["entry_known"]) if row else 1
            _new_qty = _old_qty + _qty
            _new_avg = (_old_qty * _old_avg + _qty * _px) / _new_qty if _new_qty > 0 else _px
            if row is None:
                conn.execute(
                    "INSERT INTO positions (inst_id, pos_side, qty, avg_entry, entry_known,"
                    " realized_pnl, source, opened_at, updated_at, closed_at)"
                    " VALUES (?,?,?,?,1,0,?,?,?,NULL)",
                    (inst_id, pos_side, _new_qty, _new_avg, source, _ts, _ts),
                )
            else:
                conn.execute(
                    "UPDATE positions SET qty=?, avg_entry=?, entry_known=?, updated_at=?,"
                    " closed_at=NULL WHERE inst_id=? AND pos_side=?",
                    (_new_qty, _new_avg, _known, _ts, inst_id, pos_side),
                )
            conn.execute(
                "INSERT INTO fills (ts, inst_id, pos_side, action, qty, px, fee, realized_pnl,"
                " ratio, source) VALUES (?,?,?,?,?,?,0,NULL,NULL,?)",
                (_ts, inst_id, pos_side, "open", _qty, _px, source),
            )
        return {"ok": True, "qty": _new_qty, "avg_entry": _new_avg}

    def apply_partial_close(
        self,
        inst_id: str,
        pos_side: str,
        qty: float,
        px: float,
        ratio: Optional[float] = None,
        source: str = "",
        decision_id: str = "",
        fee: float = 0.0,
        ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """部分/全部平仓：扣减数量并累计已实现盈亏。

        持仓未知（P2 之前开的仓）时 realized_pnl 返回 None，不臆造盈亏。
        """
        _qty = float(qty or 0)
        if _qty <= 0:
            return {"ok": False, "reason": "invalid_qty"}
        _px = float(px or 0)
        _ts = ts or _utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT qty, avg_entry, entry_known, realized_pnl FROM positions"
                " WHERE inst_id=? AND pos_side=?",
                (inst_id, pos_side),
            ).fetchone()
            if row is None:
                _before, _entry, _known, _realized = 0.0, 0.0, 0, 0.0
            else:
                _before = float(row["qty"])
                _entry = float(row["avg_entry"])
                _known = int(row["entry_known"])
                _realized = float(row["realized_pnl"])

            _close_qty = min(_qty, _before) if _before > _EPS else _qty
            _ratio = (
                float(ratio)
                if ratio is not None
                else (_close_qty / _before if _before > _EPS else 1.0)
            )
            _pnl = None
            if _known and _entry > 0 and _px > 0:
                _sign = 1.0 if pos_side == "long" else -1.0
                _pnl = (_px - _entry) * _close_qty * _sign - float(fee or 0.0)

            _remaining = max(0.0, _before - _close_qty)
            if row is None:
                conn.execute(
                    "INSERT INTO positions (inst_id, pos_side, qty, avg_entry, entry_known,"
                    " realized_pnl, source, opened_at, updated_at, closed_at)"
                    " VALUES (?,?,0,0,0,0,?,?,?,NULL)",
                    (inst_id, pos_side, source, _ts, _ts),
                )
            conn.execute(
                "UPDATE positions SET qty=?, realized_pnl=?, updated_at=?, closed_at=?"
                " WHERE inst_id=? AND pos_side=?",
                (
                    _remaining,
                    _realized + (_pnl or 0.0),
                    _ts,
                    _ts if _remaining <= _EPS else None,
                    inst_id,
                    pos_side,
                ),
            )
            conn.execute(
                "INSERT INTO fills (ts, inst_id, pos_side, action, qty, px, fee, realized_pnl,"
                " ratio, source, decision_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _ts,
                    inst_id,
                    pos_side,
                    "close" if _ratio >= 0.999 else "reduce",
                    _close_qty,
                    _px,
                    float(fee or 0.0),
                    _pnl,
                    _ratio,
                    source,
                    decision_id,
                ),
            )
        return {
            "ok": True,
            "realized_pnl": _pnl,
            "remaining_qty": _remaining,
            "ratio": _ratio,
        }

    # ── 读 ────────────────────────────────────────────────────────
    def get_position(self, inst_id: str, pos_side: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE inst_id=? AND pos_side=?",
                (inst_id, pos_side),
            ).fetchone()
        if row is None or float(row["qty"]) <= _EPS:
            return None
        return dict(row)

    def list_positions(self) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE qty > ? ORDER BY updated_at DESC", (_EPS,)
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fills ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)
            ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            pos = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(realized_pnl),0) AS pnl"
                " FROM positions WHERE qty > ?",
                (_EPS,),
            ).fetchone()
            fills = conn.execute("SELECT COUNT(*) AS n FROM fills").fetchone()
        return {
            "open_positions": int(pos["n"]),
            "realized_pnl_open": float(pos["pnl"]),
            "fills": int(fills["n"]),
            "db": str(self.path),
        }
