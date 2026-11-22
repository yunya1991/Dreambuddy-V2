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
from typing import Any, Callable, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "22-执行引擎中心" / "runtime" / "position_ledger.db"

_EPS = 1e-9


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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
        # P0-1：多进程读写（entry23/exit23/15 巡检）下避免写锁互相饿死
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
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
                CREATE TABLE IF NOT EXISTS cooldowns (
                    inst_id TEXT PRIMARY KEY,
                    pos_side TEXT DEFAULT '',
                    close_ts TEXT NOT NULL,
                    realized_pnl REAL,
                    exit_reason TEXT DEFAULT '',
                    source TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                """)
            self._migrate_p0(conn)

    # ── 迁移（增量、幂等） ────────────────────────────────────────
    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _ensure_column(self, conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
        if name not in self._columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def _migrate_p0(self, conn: sqlite3.Connection) -> None:
        """P0-2 增量 schema：状态字段、心跳与 effective 只读视图（幂等）。"""
        for _name, _ddl in (
            ("seq", "seq INTEGER NOT NULL DEFAULT 0"),
            ("verified_at", "verified_at TEXT"),
            ("stale_since", "stale_since TEXT"),
            ("miss_count", "miss_count INTEGER NOT NULL DEFAULT 0"),
            ("status", "status TEXT NOT NULL DEFAULT 'open'"),
        ):
            self._ensure_column(conn, "positions", _name, _ddl)

        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_positions_effective
                ON positions (status, verified_at);
            CREATE TABLE IF NOT EXISTS ledger_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger_heartbeat (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                ts TEXT NOT NULL
            );
            CREATE VIEW IF NOT EXISTS v_effective_positions AS
            SELECT p.*
            FROM positions p
            JOIN ledger_settings s ON s.key = 'effective_ttl_seconds'
            WHERE p.qty > 1e-9
              AND p.status = 'open'
              AND p.verified_at IS NOT NULL
              AND (julianday('now') - julianday(p.verified_at)) * 86400.0
                  <= CAST(s.value AS REAL);
            """)
        conn.executescript("""
            INSERT OR IGNORE INTO ledger_settings(key, value) VALUES
              ('effective_ttl_seconds', '7200'),
              ('stale_after_seconds', '600'),
              ('close_after_seconds', '3600'),
              ('min_confirmations', '3'),
              ('feed_guard_action', 'fallback_raw'),
              ('janitor_heartbeat_seconds', '60');
            """)

        if (
            conn.execute("SELECT 1 FROM schema_migrations WHERE version='p0-001'").fetchone()
            is None
        ):
            conn.executescript("""
                UPDATE positions SET status='closed'
                 WHERE qty <= 1e-9 AND closed_at IS NOT NULL;
                UPDATE positions SET verified_at = COALESCE(verified_at, updated_at)
                 WHERE qty > 1e-9 AND status = 'open' AND verified_at IS NULL;
                """)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version, applied_at)"
                " VALUES('p0-001', ?)",
                (_utc_now(),),
            )

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
                    "UPDATE positions SET qty=?, avg_entry=?, entry_known=?,"
                    " source=CASE WHEN qty <= 0 THEN ? ELSE source END,"
                    " updated_at=?, closed_at=NULL WHERE inst_id=? AND pos_side=?",
                    (_new_qty, _new_avg, _known, source, _ts, inst_id, pos_side),
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
        exit_reason: str = "",
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
            _cooldown_set = _remaining <= _EPS
            if _cooldown_set:
                # 全部平仓 → 记录冷却（供开仓侧查询，替代 11 的 last_close_info）
                conn.execute(
                    "INSERT INTO cooldowns (inst_id, pos_side, close_ts, realized_pnl,"
                    " exit_reason, source) VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(inst_id) DO UPDATE SET pos_side=excluded.pos_side,"
                    " close_ts=excluded.close_ts, realized_pnl=excluded.realized_pnl,"
                    " exit_reason=excluded.exit_reason, source=excluded.source",
                    (inst_id, pos_side, _ts, _realized + (_pnl or 0.0), exit_reason, source),
                )
        return {
            "ok": True,
            "realized_pnl": _pnl,
            "remaining_qty": _remaining,
            "ratio": _ratio,
            "cooldown_set": _cooldown_set,
        }

    def reconcile(
        self,
        positions: List[Dict[str, Any]],
        source: str = "22-reconciled",
        ts: Optional[str] = None,
        fill_lookup: Optional[Callable[[str, str], Optional[Dict[str, Any]]]] = None,
        ghost_confirm: Optional[Callable[[str, str], bool]] = None,
    ) -> Dict[str, Any]:
        """存量仓一次性对账回填（幂等）。

        - 缺失持仓 → 补录；
        - 已存在但数量与交易所不一致 → 以交易所为准校正数量（真实流水保留原均价）；
        - 账本有、交易所已无 → 仅关闭本对账源（source）写入的陈旧行，避免每轮重复报幽灵仓；
          传 fill_lookup 时按交易所真实平仓成交价落账（否则回退均价，realized_pnl 记 0）；
        - 无开仓流水时 realized_pnl 保持 0，不臆造盈亏；
        - 每次校正/关闭都写一条 fills 审计，便于追溯。
        """
        _ts = ts or _utc_now()
        written: List[Dict[str, Any]] = []
        updated: List[Dict[str, Any]] = []
        closed: List[str] = []
        skipped: List[str] = []
        _active: set = set()
        for p in positions or []:
            inst_id = str(p.get("inst_id") or "")
            pos_side = str(p.get("pos_side") or "").lower()
            qty = float(p.get("qty") or p.get("pos") or 0.0)
            avg = float(p.get("avg_entry") or p.get("avg_px") or 0.0)
            if not inst_id or pos_side not in ("long", "short") or qty <= _EPS:
                skipped.append(f"{inst_id or '?'}:{pos_side or '?'}")
                continue
            _active.add((inst_id, pos_side))
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT qty, avg_entry, entry_known, source FROM positions"
                    " WHERE inst_id=? AND pos_side=?",
                    (inst_id, pos_side),
                ).fetchone()
                if row is not None and float(row["qty"]) > _EPS:
                    _old_qty = float(row["qty"])
                    _src = str(row["source"] or "")
                    _is_reconciled = _src.startswith(source)
                    # 自动管理源（对账/23/策略）以交易所为准；历史手工流水不覆盖
                    _is_managed = (
                        _is_reconciled
                        or _src.startswith("23-")
                        or _src
                        in (
                            "23",
                            "evolution",
                            "bcrm",
                            "strategy",
                            "event_arbitrage",
                        )
                    )
                    _old_avg = float(row["avg_entry"] or 0)
                    _avg_drift = _is_reconciled and avg > _EPS and abs(_old_avg - avg) > _EPS
                    if abs(_old_qty - qty) <= _EPS and not _avg_drift:
                        skipped.append(f"{inst_id}:{pos_side}")
                        continue
                    if not _is_managed:
                        skipped.append(f"{inst_id}:{pos_side}")
                        continue
                    # 数量/均价与交易所不一致 → 校正；真实流水保留原成本
                    _new_avg = avg if _is_reconciled and avg > _EPS else _old_avg
                    if _new_avg <= _EPS:
                        _new_avg = avg
                    conn.execute(
                        "UPDATE positions SET qty=?, avg_entry=?, entry_known=?, updated_at=?,"
                        " closed_at=NULL WHERE inst_id=? AND pos_side=?",
                        (
                            qty,
                            _new_avg,
                            1 if _new_avg > _EPS else 0,
                            _ts,
                            inst_id,
                            pos_side,
                        ),
                    )
                    conn.execute(
                        "INSERT INTO fills (ts, inst_id, pos_side, action, qty, px, fee,"
                        " realized_pnl, ratio, source) VALUES (?,?,?,?,?,?,0,NULL,NULL,?)",
                        (_ts, inst_id, pos_side, "reconcile_update", qty, _new_avg, source),
                    )
                    updated.append(
                        {
                            "inst_id": inst_id,
                            "pos_side": pos_side,
                            "qty": qty,
                            "avg_entry": _new_avg,
                        }
                    )
                    continue
                conn.execute(
                    "INSERT INTO positions (inst_id, pos_side, qty, avg_entry, entry_known,"
                    " realized_pnl, source, opened_at, updated_at, closed_at)"
                    " VALUES (?,?,?,?,?,0,?,?,?,NULL)"
                    " ON CONFLICT(inst_id, pos_side) DO UPDATE SET qty=excluded.qty,"
                    " avg_entry=excluded.avg_entry, entry_known=excluded.entry_known,"
                    " source=CASE WHEN positions.source != ''"
                    " AND positions.source NOT LIKE '22-reconciled%'"
                    " THEN positions.source ELSE excluded.source END,"
                    " updated_at=excluded.updated_at, closed_at=NULL",
                    (inst_id, pos_side, qty, avg, 1 if avg > 0 else 0, source, _ts, _ts),
                )
                conn.execute(
                    "INSERT INTO fills (ts, inst_id, pos_side, action, qty, px, fee, realized_pnl,"
                    " ratio, source) VALUES (?,?,?,?,?,?,0,NULL,NULL,?)",
                    (_ts, inst_id, pos_side, "reconcile", qty, avg, source),
                )
            written.append({"inst_id": inst_id, "pos_side": pos_side, "qty": qty, "avg_entry": avg})

        # 交易所已无持仓，但账本仍开着：只关闭本对账源写入的陈旧行
        with self._lock, self._connect() as conn:
            _rows = conn.execute(
                "SELECT inst_id, pos_side, qty, avg_entry, source FROM positions WHERE qty > ?",
                (_EPS,),
            ).fetchall()
        for row in _rows:
            _key = (row["inst_id"], row["pos_side"])
            if _key in _active:
                continue
            if not str(row["source"] or "").startswith(source):
                continue
            # 连续 N 轮确认缺失才平仓：OKX 持仓快照可能瞬时返回不完整列表，
            # 单轮"没返回"不等于已平仓，误判会产生假幽灵仓并让开仓闸门看到空仓。
            if ghost_confirm is not None and not ghost_confirm(
                str(row["inst_id"]), str(row["pos_side"])
            ):
                skipped.append(f"{row['inst_id']}:{row['pos_side']}")
                continue
            _fill: Dict[str, Any] = {}
            if callable(fill_lookup):
                try:
                    _fill = fill_lookup(row["inst_id"], row["pos_side"]) or {}
                except Exception:  # noqa: BLE001 — 查真实成交失败时回退均价
                    _fill = {}
            _fill_px = float(_fill.get("fill_px") or 0.0)
            _exit_px = _fill_px if _fill_px > _EPS else float(row["avg_entry"] or 0)
            _exit_ts = ts
            _fill_ts = int(_fill.get("ts") or 0)
            if _fill_ts > 0:
                try:
                    _exit_ts = (
                        datetime.fromtimestamp(_fill_ts / 1000, tz=timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
                except (OSError, OverflowError, ValueError):
                    _exit_ts = ts
            self.apply_partial_close(
                inst_id=row["inst_id"],
                pos_side=row["pos_side"],
                qty=float(row["qty"]),
                px=_exit_px,
                ratio=1.0,
                source=source,
                fee=float(_fill.get("fee") or 0.0),
                ts=_exit_ts,
                exit_reason="ghost_stale",
            )
            closed.append(f"{row['inst_id']}:{row['pos_side']}")
        return {
            "ok": True,
            "inserted": len(written),
            "updated": len(updated),
            "closed": len(closed),
            "skipped": len(skipped),
            "written": written,
            "updated_detail": updated,
            "closed_detail": closed,
            "skipped_detail": skipped,
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

    # ── P0-5：对账心跳与有效持仓读口径 ──────────────────────────────
    def heartbeat(self, ts: Optional[str] = None) -> str:
        """由对账方每轮成功后写入；心跳异常时闸门回退 raw 口径。"""
        _ts = ts or _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO ledger_heartbeat(id, ts) VALUES(1, ?)"
                " ON CONFLICT(id) DO UPDATE SET ts=excluded.ts",
                (_ts,),
            )
        return _ts

    def heartbeat_age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT ts FROM ledger_heartbeat WHERE id=1").fetchone()
        if row is None:
            return None
        dt = _parse_ts(row["ts"])
        if dt is None:
            return None
        ref = now or datetime.now(timezone.utc)
        return max(0.0, (ref - dt).total_seconds())

    def mark_verified(self, positions: List[Dict[str, Any]], ts: Optional[str] = None) -> int:
        """把交易所已确认的持仓刷新为 verified；stale 行重新出现时恢复 open。"""
        _ts = ts or _utc_now()
        _n = 0
        with self._lock, self._connect() as conn:
            for pos in positions or []:
                inst = str(pos.get("inst_id") or "")
                side = str(pos.get("pos_side") or "").lower()
                if not inst or side not in ("long", "short"):
                    continue
                cur = conn.execute(
                    "UPDATE positions SET verified_at=?, miss_count=0,"
                    " status=CASE WHEN status='stale' THEN 'open' ELSE status END,"
                    " stale_since=CASE WHEN status='stale' THEN NULL ELSE stale_since END"
                    " WHERE inst_id=? AND pos_side=? AND qty>?",
                    (_ts, inst, side, _EPS),
                )
                _n += int(cur.rowcount)
        return _n

    def list_effective_positions(
        self, max_heartbeat_age_seconds: float = 300.0
    ) -> List[Dict[str, Any]]:
        """容量/闸门唯一读口径。

        心跳缺失或过期时回退 raw `positions(qty>0)`，避免对账停摆后
        effective 视图变空而放开限额（SPEC §3.2 feed 陈旧保护）。
        """
        _age = self.heartbeat_age_seconds()
        if _age is None or _age > float(max_heartbeat_age_seconds):
            return self.list_positions()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM v_effective_positions ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fills ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_cooldown(self, inst_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM cooldowns WHERE inst_id=?", (inst_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_cooldowns(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cooldowns ORDER BY close_ts DESC LIMIT ?",
                (max(1, int(limit)),),
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
