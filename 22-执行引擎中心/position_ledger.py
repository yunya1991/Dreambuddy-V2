"""22 统一持仓账本（P2）。

定位：22 是「持仓数量 + 已实现盈亏」的唯一真相源，NN 与 23 共用；
11 只读，不再承担 23 的部分减仓落账。

设计：
- 追加式 fills 表（每次成交一条）+ positions 聚合表（当前持仓）；
- 只落账，不做风控/决策；
- FAIL-OPEN：任何异常由调用方（Gateway）吞掉，不影响下单。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "22-执行引擎中心" / "runtime" / "position_ledger.db"

_EPS = 1e-9

# SPEC §2：source → domain 唯一映射（保留原始 source 仅作追溯）
_DOMAIN_RULES: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("23-evolution", "evolution", "bcrm", "strategy", "event_arbitrage"), "23"),
    (("11-yijing", "11"), "11"),
    (("50-nn", "50"), "50"),
    (("6-trading", "6"), "6"),
    (("22-reconciled", "22-janitor", "sltp", "22"), "22"),
)


def domain_of(source: Optional[str]) -> str:
    """按 SPEC §2 把 source 前缀/取值映射到规范域编码；未知归 legacy。"""
    _src = str(source or "").strip().lower()
    if not _src:
        return "legacy"
    for prefixes, dom in _DOMAIN_RULES:
        for p in prefixes:
            if _src == p or _src.startswith(p):
                return dom
    return "legacy"


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

    @contextmanager
    def _tx(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """单事务写入口：immediate=True 时先取写锁，保证跨进程“读-判-写”原子。"""
        with self._lock:
            conn = self._connect()
            conn.isolation_level = None
            try:
                conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield conn
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                conn.close()

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
            self._migrate_p1(conn)

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

    def _migrate_p1(self, conn: sqlite3.Connection) -> None:
        """P1-1 增量 schema：域子账/批次/预占/工单/注册表 + 历史归属回填（幂等）。"""
        for _name, _ddl in (
            ("domain", "domain TEXT NOT NULL DEFAULT ''"),
            ("alloc_id", "alloc_id TEXT NOT NULL DEFAULT ''"),
            ("exchange_fill_id", "exchange_fill_id TEXT NOT NULL DEFAULT ''"),
            ("parent_fill_id", "parent_fill_id INTEGER"),
        ):
            self._ensure_column(conn, "fills", _name, _ddl)

        # 兼容更早期的 positions schema（缺 source/时间戳列时回填 SQL 才能执行）
        for _name, _ddl in (
            ("source", "source TEXT DEFAULT ''"),
            ("entry_known", "entry_known INTEGER NOT NULL DEFAULT 1"),
            ("realized_pnl", "realized_pnl REAL NOT NULL DEFAULT 0"),
            ("opened_at", "opened_at TEXT"),
            ("updated_at", "updated_at TEXT"),
            ("closed_at", "closed_at TEXT"),
        ):
            self._ensure_column(conn, "positions", _name, _ddl)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS domain_positions (
                inst_id       TEXT NOT NULL,
                pos_side      TEXT NOT NULL,
                domain        TEXT NOT NULL,
                qty           REAL NOT NULL DEFAULT 0,
                avg_entry     REAL NOT NULL DEFAULT 0,
                realized_pnl  REAL NOT NULL DEFAULT 0,
                entry_known   INTEGER NOT NULL DEFAULT 1,
                source_detail TEXT DEFAULT '',
                opened_at     TEXT,
                updated_at    TEXT,
                closed_at     TEXT,
                status        TEXT NOT NULL DEFAULT 'open'
                              CHECK (status IN ('open','stale','closed')),
                PRIMARY KEY (inst_id, pos_side, domain)
            );
            CREATE TABLE IF NOT EXISTS position_lots (
                lot_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                inst_id       TEXT NOT NULL,
                pos_side      TEXT NOT NULL,
                domain        TEXT NOT NULL,
                qty           REAL NOT NULL,
                remaining_qty REAL NOT NULL,
                px            REAL NOT NULL,
                opened_at     TEXT NOT NULL,
                source_detail TEXT DEFAULT '',
                decision_id   TEXT DEFAULT '',
                tier          TEXT DEFAULT '',
                status        TEXT NOT NULL DEFAULT 'open'
                              CHECK (status IN ('open','closed'))
            );
            CREATE INDEX IF NOT EXISTS idx_lots_open
                ON position_lots (inst_id, pos_side, domain, status, lot_id);
            CREATE TABLE IF NOT EXISTS reservations (
                reservation_id TEXT PRIMARY KEY,
                domain         TEXT NOT NULL,
                inst_id        TEXT NOT NULL,
                pos_side       TEXT NOT NULL,
                notional       REAL NOT NULL,
                state          TEXT NOT NULL DEFAULT 'held'
                               CHECK (state IN ('held','consumed','released','expired')),
                decision_id    TEXT DEFAULT '',
                created_at     TEXT NOT NULL,
                expires_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reservations_active
                ON reservations (domain, inst_id, pos_side, state, expires_at);
            CREATE TABLE IF NOT EXISTS recon_breaks (
                break_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                kind          TEXT NOT NULL
                              CHECK (kind IN ('missing_in_ledger','orphan_in_ledger','qty_drift',
                                              'price_drift','stale_position','over_close',
                                              'duplicate_open')),
                inst_id       TEXT NOT NULL,
                pos_side      TEXT NOT NULL,
                domain        TEXT NOT NULL DEFAULT '',
                detected_at   TEXT NOT NULL,
                state         TEXT NOT NULL DEFAULT 'OPEN'
                              CHECK (state IN ('OPEN','ACK','RESOLVED','WAIVED')),
                owner_domain  TEXT DEFAULT '',
                evidence_json TEXT DEFAULT '',
                sla_due_at    TEXT,
                resolved_at   TEXT,
                resolution    TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_recon_breaks_sla
                ON recon_breaks (state, sla_due_at);
            CREATE TABLE IF NOT EXISTS domain_registry (
                domain        TEXT PRIMARY KEY,
                enabled       INTEGER NOT NULL DEFAULT 1,
                owner_contact TEXT DEFAULT '',
                limits_json   TEXT NOT NULL DEFAULT '{}',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fills_domain
                ON fills (domain, inst_id, pos_side, id DESC);
        """)

        conn.executescript("""
            INSERT OR IGNORE INTO ledger_settings(key, value) VALUES
              ('lot_close_policy', 'fifo'),
              ('janitor_enforce', 'off'),
              ('reservation_ttl_seconds', '300');
            INSERT OR IGNORE INTO domain_registry(domain, enabled, limits_json, created_at, updated_at)
            VALUES
              ('11', 1, '{"max_positions":6,"max_notional":2000}', datetime('now'), datetime('now')),
              ('23', 1, '{"subpool_max":5,"probe_max":2,"max_direction_ratio":0.70}',
               datetime('now'), datetime('now')),
              ('50', 1, '{"max_positions":12,"position_scope":"registry"}',
               datetime('now'), datetime('now')),
              ('6',  1, '{}', datetime('now'), datetime('now')),
              ('22', 1, '{"role":"janitor"}', datetime('now'), datetime('now')),
              ('legacy', 0, '{}', datetime('now'), datetime('now'));
        """)

        # 批次级分层（probe/standard/trend）：供探索仓配额统计（须在建表之后）
        self._ensure_column(conn, "position_lots", "tier", "tier TEXT DEFAULT ''")

        if (
            conn.execute("SELECT 1 FROM schema_migrations WHERE version='p1-001'").fetchone()
            is None
        ):
            conn.executescript("""
                INSERT INTO domain_positions(
                    inst_id, pos_side, domain, qty, avg_entry, realized_pnl, entry_known,
                    source_detail, opened_at, updated_at, closed_at, status)
                SELECT
                    p.inst_id, p.pos_side,
                    CASE
                      WHEN p.source LIKE '23%' OR p.source IN
                           ('evolution','bcrm','strategy','event_arbitrage') THEN '23'
                      WHEN p.source LIKE '11%' THEN '11'
                      WHEN p.source LIKE '50%' THEN '50'
                      WHEN p.source LIKE '6%'  THEN '6'
                      WHEN p.source LIKE '22%' OR p.source LIKE 'sltp%' THEN '22'
                      ELSE 'legacy'
                    END,
                    p.qty, p.avg_entry, 0, p.entry_known,
                    p.source, p.opened_at, p.updated_at, p.closed_at,
                    CASE WHEN p.closed_at IS NULL AND p.qty > 1e-9 THEN 'open' ELSE 'closed' END
                FROM positions p
                WHERE p.qty > 1e-9 OR p.closed_at IS NOT NULL
                ON CONFLICT(inst_id, pos_side, domain) DO UPDATE SET
                    qty = excluded.qty,
                    avg_entry = excluded.avg_entry,
                    updated_at = excluded.updated_at,
                    closed_at = excluded.closed_at,
                    status = excluded.status;

                INSERT INTO position_lots(inst_id, pos_side, domain, qty, remaining_qty, px,
                                          opened_at, source_detail, decision_id, status)
                SELECT d.inst_id, d.pos_side, d.domain, d.qty, d.qty, d.avg_entry,
                       COALESCE(d.opened_at, datetime('now')), 'migration', '', 'open'
                FROM domain_positions d
                WHERE d.status = 'open' AND d.qty > 1e-9
                  AND NOT EXISTS (
                      SELECT 1 FROM position_lots l
                      WHERE l.inst_id = d.inst_id AND l.pos_side = d.pos_side
                        AND l.domain = d.domain AND l.source_detail = 'migration'
                  );

                UPDATE positions SET status = 'open', verified_at = COALESCE(verified_at, updated_at)
                 WHERE qty > 1e-9 AND status = 'open';
                UPDATE positions SET status = 'closed'
                 WHERE qty <= 1e-9 AND closed_at IS NOT NULL;
            """)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version, applied_at)"
                " VALUES('p1-001', ?)",
                (_utc_now(),),
            )

        # 历史 realized_pnl 无法精确拆域（SPEC §4.7 限制）：回填批次统一记 0，不用于结算
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_domain_positions_active_domain"
                " ON domain_positions (inst_id, pos_side)"
                " WHERE qty > 1e-9 AND status IN ('open','stale')"
            )
        except sqlite3.IntegrityError:
            # 存量数据存在同标的多活跃域时保留旧索引之外的运行能力，交由 break 工单人工收敛
            pass
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_recon_breaks_active"
            " ON recon_breaks (kind, inst_id, pos_side, domain)"
            " WHERE state IN ('OPEN','ACK')"
        )
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_fills_exchange_fill"
                " ON fills (exchange_fill_id) WHERE exchange_fill_id <> ''"
            )
        except sqlite3.IntegrityError:
            pass
        conn.execute(
            "CREATE VIEW IF NOT EXISTS v_domain_positions AS"
            " SELECT d.*, r.enabled AS domain_enabled, r.limits_json AS limits_json"
            " FROM domain_positions d"
            " LEFT JOIN domain_registry r ON r.domain = d.domain"
            " WHERE d.qty > 1e-9"
        )

    # ── 写 ────────────────────────────────────────────────────────
    # ── 写：成交落账（P1 单一事件流 + 域子账 + FIFO 批次） ────────────
    def _fill_domain(
        self, conn: sqlite3.Connection, inst_id: str, pos_side: str, domain: str
    ) -> str:
        """本次成交归属域：显式 domain 优先，其次沿用唯一活跃域，最后 legacy。"""
        _dom = str(domain or "").strip().lower()
        if _dom:
            return _dom
        row = conn.execute(
            "SELECT domain FROM domain_positions WHERE inst_id=? AND pos_side=?"
            " AND qty>? AND status IN ('open','stale') ORDER BY updated_at DESC LIMIT 1",
            (inst_id, pos_side, _EPS),
        ).fetchone()
        return str(row["domain"]) if row is not None else "legacy"

    def _ensure_domain_row(
        self, conn: sqlite3.Connection, inst_id: str, pos_side: str, domain: str, ts: str
    ) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO domain_positions(inst_id, pos_side, domain, qty, avg_entry,"
            " realized_pnl, entry_known, source_detail, opened_at, updated_at, closed_at, status)"
            " VALUES (?,?,?,0,0,0,1,'',?,?,NULL,'open')",
            (inst_id, pos_side, domain, ts, ts),
        )

    def _insert_fill_tx(
        self,
        conn: sqlite3.Connection,
        *,
        ts: str,
        inst_id: str,
        pos_side: str,
        action: str,
        qty: float,
        px: float,
        fee: float,
        realized_pnl: Optional[float],
        ratio: Optional[float],
        source: str,
        decision_id: str,
        domain: str,
        alloc_id: str,
        exchange_fill_id: str,
        parent_fill_id: Optional[int],
    ) -> int:
        cur = conn.execute(
            "INSERT INTO fills (ts, inst_id, pos_side, action, qty, px, fee, realized_pnl, ratio,"
            " source, decision_id, domain, alloc_id, exchange_fill_id, parent_fill_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ts,
                inst_id,
                pos_side,
                action,
                qty,
                px,
                fee,
                realized_pnl,
                ratio,
                source,
                decision_id,
                domain,
                alloc_id,
                exchange_fill_id,
                parent_fill_id,
            ),
        )
        return int(cur.lastrowid or 0)

    @staticmethod
    def _upsert_break_tx(
        conn: sqlite3.Connection,
        kind: str,
        inst_id: str,
        pos_side: str,
        domain: str,
        evidence: Optional[Dict[str, Any]],
        ts: str,
        sla_due_at: Optional[str] = None,
    ) -> int:
        """同一差异只保留一条活跃工单（唯一索引兜底），返回 break_id。"""
        try:
            cur = conn.execute(
                "INSERT INTO recon_breaks(kind, inst_id, pos_side, domain, detected_at, state,"
                " evidence_json, sla_due_at) VALUES (?,?,?,?,?,'OPEN',?,?)",
                (
                    kind,
                    inst_id,
                    pos_side,
                    domain,
                    ts,
                    json.dumps(evidence or {}, ensure_ascii=False),
                    sla_due_at,
                ),
            )
            return int(cur.lastrowid or 0)
        except sqlite3.IntegrityError:
            row = conn.execute(
                "SELECT break_id FROM recon_breaks WHERE kind=? AND inst_id=? AND pos_side=?"
                " AND domain=? AND state IN ('OPEN','ACK')",
                (kind, inst_id, pos_side, domain),
            ).fetchone()
            return int(row["break_id"]) if row is not None else 0

    def _consume_lots(
        self,
        conn: sqlite3.Connection,
        inst_id: str,
        pos_side: str,
        domain: str,
        qty: float,
        px: float,
        fee: float,
    ) -> Tuple[float, Optional[float], float]:
        """FIFO 扣减批次：返回 (实际扣减量, 批次 PnL, 缺口量)。

        fee 按扣减数量比例摊到各批次，尾差计入最后一批（SPEC §5.1）。
        """
        _sign = 1.0 if pos_side == "long" else -1.0
        rows = conn.execute(
            "SELECT lot_id, remaining_qty, px FROM position_lots"
            " WHERE inst_id=? AND pos_side=? AND domain=? AND status='open' AND remaining_qty>?"
            " ORDER BY lot_id ASC",
            (inst_id, pos_side, domain, _EPS),
        ).fetchall()
        if not rows:
            return 0.0, None, qty
        plan: List[Tuple[int, float, float, float]] = []
        left = qty
        take_total = 0.0
        for r in rows:
            if left <= _EPS:
                break
            avail = float(r["remaining_qty"])
            take = min(avail, left)
            plan.append((int(r["lot_id"]), take, float(r["px"]), avail))
            take_total += take
            left -= take
        _fee = float(fee or 0.0)
        pnl = 0.0
        fee_left = _fee
        for i, (lot_id, take, lot_px, avail) in enumerate(plan):
            if i == len(plan) - 1:
                fee_alloc = fee_left
            else:
                fee_alloc = _fee * (take / take_total) if take_total > _EPS else 0.0
                fee_left -= fee_alloc
            pnl += (px - lot_px) * take * _sign - fee_alloc
            new_rem = max(0.0, avail - take)
            conn.execute(
                "UPDATE position_lots SET remaining_qty=?, status=? WHERE lot_id=?",
                (new_rem, "closed" if new_rem <= _EPS else "open", lot_id),
            )
        return take_total, pnl, max(0.0, qty - take_total)

    def _record_fill_tx(
        self,
        conn: sqlite3.Connection,
        *,
        inst_id: str,
        pos_side: str,
        action: str,
        qty: float,
        px: float,
        fee: float = 0.0,
        ratio: Optional[float] = None,
        source: str = "",
        decision_id: str = "",
        domain: str = "",
        exchange_fill_id: str = "",
        alloc_id: str = "",
        parent_fill_id: Optional[int] = None,
        exit_reason: str = "",
        tier: str = "",
        ts: Optional[str] = None,
        set_cooldown: bool = True,
    ) -> Dict[str, Any]:
        """单事务写 fills + L1 + L2 + lots + cooldown（§3.1 三条铁律）。"""
        _ts = ts or _utc_now()
        _inst = str(inst_id or "")
        _side = str(pos_side or "").lower()
        _qty = float(qty or 0)
        _px = float(px or 0)
        _fee = float(fee or 0.0)
        _action = str(action or "").lower()
        _decision_id = str(decision_id or "")
        _alloc = str(alloc_id or "")
        _efid = str(exchange_fill_id or "")
        _sign = 1.0 if _side == "long" else -1.0

        if _action == "open":
            if _qty <= 0 or _px <= 0:
                return {"ok": False, "reason": "invalid_qty_or_px"}
            _dom = str(domain or "").strip().lower() or domain_of(source)
            active = conn.execute(
                "SELECT domain FROM domain_positions WHERE inst_id=? AND pos_side=?"
                " AND qty>? AND status IN ('open','stale')",
                (_inst, _side, _EPS),
            ).fetchone()
            if active is not None and str(active["domain"]) != _dom:
                # P1 一标的一域：冲突时沿用既有域并落 break，避免 L1/L2 撕开
                self._upsert_break_tx(
                    conn,
                    "duplicate_open",
                    _inst,
                    _side,
                    _dom,
                    {"active_domain": str(active["domain"]), "source": source},
                    _ts,
                )
                _dom = str(active["domain"])

            row = conn.execute(
                "SELECT qty, avg_entry, entry_known FROM positions WHERE inst_id=? AND pos_side=?",
                (_inst, _side),
            ).fetchone()
            old_qty = float(row["qty"]) if row else 0.0
            old_avg = float(row["avg_entry"]) if row else 0.0
            known = int(row["entry_known"]) if row else 1
            new_qty = old_qty + _qty
            new_avg = (old_qty * old_avg + _qty * _px) / new_qty if new_qty > _EPS else _px
            if row is None:
                conn.execute(
                    "INSERT INTO positions (inst_id, pos_side, qty, avg_entry, entry_known,"
                    " realized_pnl, source, opened_at, updated_at, closed_at)"
                    " VALUES (?,?,?,?,1,0,?,?,?,NULL)",
                    (_inst, _side, new_qty, new_avg, source, _ts, _ts),
                )
            else:
                conn.execute(
                    "UPDATE positions SET qty=?, avg_entry=?, entry_known=?,"
                    " source=CASE WHEN qty <= 0 THEN ? ELSE source END,"
                    " updated_at=?, closed_at=NULL WHERE inst_id=? AND pos_side=?",
                    (new_qty, new_avg, known, source, _ts, _inst, _side),
                )

            self._ensure_domain_row(conn, _inst, _side, _dom, _ts)
            drow = conn.execute(
                "SELECT qty, avg_entry FROM domain_positions"
                " WHERE inst_id=? AND pos_side=? AND domain=?",
                (_inst, _side, _dom),
            ).fetchone()
            d_qty = float(drow["qty"]) if drow else 0.0
            d_avg = float(drow["avg_entry"]) if drow else 0.0
            d_new_qty = d_qty + _qty
            d_new_avg = (d_qty * d_avg + _qty * _px) / d_new_qty if d_new_qty > _EPS else _px
            conn.execute(
                "UPDATE domain_positions SET qty=?, avg_entry=?, entry_known=1,"
                " source_detail=?, updated_at=?, closed_at=NULL, status='open'"
                " WHERE inst_id=? AND pos_side=? AND domain=?",
                (d_new_qty, d_new_avg, source, _ts, _inst, _side, _dom),
            )
            conn.execute(
                "INSERT INTO position_lots(inst_id, pos_side, domain, qty, remaining_qty, px,"
                " opened_at, source_detail, decision_id, tier, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,'open')",
                (_inst, _side, _dom, _qty, _qty, _px, _ts, source, _decision_id, str(tier or "")),
            )
            fill_id = self._insert_fill_tx(
                conn,
                ts=_ts,
                inst_id=_inst,
                pos_side=_side,
                action="open",
                qty=_qty,
                px=_px,
                fee=_fee,
                realized_pnl=None,
                ratio=None,
                source=source,
                decision_id=_decision_id,
                domain=_dom,
                alloc_id=_alloc,
                exchange_fill_id=_efid,
                parent_fill_id=parent_fill_id,
            )
            conn.execute(
                "UPDATE positions SET seq=? WHERE inst_id=? AND pos_side=?",
                (fill_id, _inst, _side),
            )
            return {
                "ok": True,
                "fill_id": fill_id,
                "domain": _dom,
                "qty": new_qty,
                "avg_entry": new_avg,
            }

        # close / reduce
        if _qty <= 0:
            return {"ok": False, "reason": "invalid_qty"}
        _dom = self._fill_domain(conn, _inst, _side, domain)
        drow = conn.execute(
            "SELECT qty, avg_entry, entry_known, realized_pnl FROM domain_positions"
            " WHERE inst_id=? AND pos_side=? AND domain=?",
            (_inst, _side, _dom),
        ).fetchone()
        d_avail = float(drow["qty"]) if drow else 0.0
        requested = _qty
        if drow is not None and _qty > d_avail + _EPS:
            # §5.1-4：不跨域借仓，按可用量截断并落 over_close 工单
            self._upsert_break_tx(
                conn,
                "over_close",
                _inst,
                _side,
                _dom,
                {"requested": _qty, "available": d_avail, "source": source},
                _ts,
            )
            _qty = max(0.0, d_avail)

        consumed, lot_pnl, _gap = self._consume_lots(conn, _inst, _side, _dom, _qty, _px, _fee)
        if drow is not None and consumed + _EPS < _qty:
            # 批次缺失（历史漂移）：按域均价补齐剩余量，避免漏记盈亏
            rest = _qty - consumed
            d_avg = float(drow["avg_entry"])
            if int(drow["entry_known"]) and d_avg > 0 and _px > 0:
                lot_pnl = (lot_pnl or 0.0) + (_px - d_avg) * rest * _sign

        row = conn.execute(
            "SELECT qty, avg_entry, entry_known, realized_pnl FROM positions"
            " WHERE inst_id=? AND pos_side=?",
            (_inst, _side),
        ).fetchone()
        before = float(row["qty"]) if row else 0.0
        entry = float(row["avg_entry"]) if row else 0.0
        known = int(row["entry_known"]) if row else 0
        realized = float(row["realized_pnl"]) if row else 0.0
        close_qty = min(_qty, before) if before > _EPS else _qty
        _ratio = (
            float(ratio) if ratio is not None else (close_qty / before if before > _EPS else 1.0)
        )
        l1_pnl: Optional[float] = None
        if known and entry > 0 and _px > 0:
            l1_pnl = (_px - entry) * close_qty * _sign - _fee
        pnl = lot_pnl if lot_pnl is not None else l1_pnl
        remaining = max(0.0, before - close_qty)
        if row is None:
            conn.execute(
                "INSERT INTO positions (inst_id, pos_side, qty, avg_entry, entry_known,"
                " realized_pnl, source, opened_at, updated_at, closed_at)"
                " VALUES (?,?,0,0,0,0,?,?,?,NULL)",
                (_inst, _side, source, _ts, _ts),
            )
        conn.execute(
            "UPDATE positions SET qty=?, realized_pnl=?, updated_at=?, closed_at=?"
            " WHERE inst_id=? AND pos_side=?",
            (
                remaining,
                realized + (pnl or 0.0),
                _ts,
                _ts if remaining <= _EPS else None,
                _inst,
                _side,
            ),
        )
        if drow is not None:
            d_new_qty = max(0.0, d_avail - _qty)
            conn.execute(
                "UPDATE domain_positions SET qty=?, realized_pnl=?, updated_at=?, closed_at=?,"
                " status=? WHERE inst_id=? AND pos_side=? AND domain=?",
                (
                    d_new_qty,
                    float(drow["realized_pnl"]) + (pnl or 0.0),
                    _ts,
                    _ts if d_new_qty <= _EPS else None,
                    "closed" if d_new_qty <= _EPS else "open",
                    _inst,
                    _side,
                    _dom,
                ),
            )
        cooldown_set = remaining <= _EPS
        if cooldown_set and set_cooldown:
            conn.execute(
                "INSERT INTO cooldowns (inst_id, pos_side, close_ts, realized_pnl,"
                " exit_reason, source) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(inst_id) DO UPDATE SET pos_side=excluded.pos_side,"
                " close_ts=excluded.close_ts, realized_pnl=excluded.realized_pnl,"
                " exit_reason=excluded.exit_reason, source=excluded.source",
                (_inst, _side, _ts, realized + (pnl or 0.0), exit_reason, source),
            )
        fill_id = self._insert_fill_tx(
            conn,
            ts=_ts,
            inst_id=_inst,
            pos_side=_side,
            action="close" if _ratio >= 0.999 else "reduce",
            qty=_qty,
            px=_px,
            fee=_fee,
            realized_pnl=pnl,
            ratio=_ratio,
            source=source,
            decision_id=_decision_id,
            domain=_dom,
            alloc_id=_alloc,
            exchange_fill_id=_efid,
            parent_fill_id=parent_fill_id,
        )
        conn.execute(
            "UPDATE positions SET seq=? WHERE inst_id=? AND pos_side=?",
            (fill_id, _inst, _side),
        )
        return {
            "ok": True,
            "fill_id": fill_id,
            "domain": _dom,
            "realized_pnl": pnl,
            "remaining_qty": remaining,
            "ratio": _ratio,
            "cooldown_set": cooldown_set,
            "executed_qty": _qty,
            "shortfall": max(0.0, requested - _qty),
        }

    def record_fill(
        self,
        inst_id: str,
        pos_side: str,
        action: str,
        qty: float,
        px: float,
        *,
        domain: str = "",
        source: str = "",
        decision_id: str = "",
        exchange_fill_id: str = "",
        alloc_id: str = "",
        parent_fill_id: Optional[int] = None,
        fee: float = 0.0,
        ratio: Optional[float] = None,
        exit_reason: str = "",
        tier: str = "",
        ts: Optional[str] = None,
        set_cooldown: bool = True,
    ) -> Dict[str, Any]:
        """P1 统一成交入口：同一事务写 fills + L1 + L2 + lots；exchange_fill_id 幂等。"""
        _efid = str(exchange_fill_id or "")
        if _efid:
            with self._lock, self._connect() as conn:
                dup = conn.execute(
                    "SELECT id FROM fills WHERE exchange_fill_id=? LIMIT 1", (_efid,)
                ).fetchone()
            if dup is not None:
                return {"ok": True, "duplicate": True, "fill_id": int(dup["id"])}
        try:
            with self._tx() as conn:
                return self._record_fill_tx(
                    conn,
                    inst_id=inst_id,
                    pos_side=pos_side,
                    action=action,
                    qty=qty,
                    px=px,
                    fee=fee,
                    ratio=ratio,
                    source=source,
                    decision_id=decision_id,
                    domain=domain,
                    exchange_fill_id=_efid,
                    alloc_id=alloc_id,
                    parent_fill_id=parent_fill_id,
                    exit_reason=exit_reason,
                    tier=tier,
                    ts=ts,
                    set_cooldown=set_cooldown,
                )
        except sqlite3.IntegrityError as exc:
            if _efid and "exchange_fill_id" in str(exc):
                return {"ok": True, "duplicate": True, "reason": "exchange_fill_id_conflict"}
            return {"ok": False, "reason": f"integrity_error: {exc}"}
        except sqlite3.Error as exc:
            return {"ok": False, "reason": f"db_error: {exc}"}

    def close_position(
        self,
        domain: str,
        inst_id: str,
        pos_side: str,
        qty: float,
        *,
        px: float = 0.0,
        source: str = "",
        decision_id: str = "",
        fee: float = 0.0,
        exit_reason: str = "",
        set_cooldown: bool = True,
        ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """仅允许关闭本域份额（§5.2）；janitor 关闭时传 set_cooldown=False。"""
        _dom = str(domain or "").strip().lower()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT qty FROM domain_positions WHERE inst_id=? AND pos_side=?"
                " AND domain=? AND qty>?",
                (inst_id, pos_side, _dom, _EPS),
            ).fetchone()
        if row is None:
            return {"ok": False, "reason": "domain_mismatch", "domain": _dom}
        return self.record_fill(
            inst_id,
            pos_side,
            "reduce",
            qty,
            px,
            domain=_dom,
            source=source or f"{_dom}-janitor",
            decision_id=decision_id,
            fee=fee,
            exit_reason=exit_reason,
            ts=ts,
            set_cooldown=set_cooldown,
        )

    def record_open(
        self,
        inst_id: str,
        pos_side: str,
        qty: float,
        px: float,
        source: str = "",
        ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """开仓/加仓：按数量加权更新均价（兼容旧 API，内部走 record_fill）。"""
        out = self.record_fill(inst_id, pos_side, "open", qty, px, source=source, ts=ts)
        if not out.get("ok"):
            return {"ok": False, "reason": out.get("reason")}
        return {"ok": True, "qty": out.get("qty"), "avg_entry": out.get("avg_entry")}

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
        """部分/全部平仓（兼容旧 API）：扣减数量并累计已实现盈亏。

        持仓未知（P2 之前开的仓）时 realized_pnl 返回 None，不臆造盈亏。
        """
        out = self.record_fill(
            inst_id,
            pos_side,
            "reduce",
            qty,
            px,
            ratio=ratio,
            source=source,
            decision_id=decision_id,
            fee=fee,
            exit_reason=exit_reason,
            ts=ts,
        )
        if not out.get("ok"):
            return {"ok": False, "reason": out.get("reason")}
        return {
            "ok": True,
            "realized_pnl": out.get("realized_pnl"),
            "remaining_qty": out.get("remaining_qty"),
            "ratio": out.get("ratio"),
            "cooldown_set": out.get("cooldown_set"),
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
                    "SELECT qty, avg_entry, entry_known, source, status FROM positions"
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
                    if (
                        abs(_old_qty - qty) <= _EPS
                        and not _avg_drift
                        and str(row["status"] or "open") == "open"
                    ):
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
                        " closed_at=NULL, status='open', stale_since=NULL, miss_count=0"
                        " WHERE inst_id=? AND pos_side=?",
                        (
                            qty,
                            _new_avg,
                            1 if _new_avg > _EPS else 0,
                            _ts,
                            inst_id,
                            pos_side,
                        ),
                    )
                    _dom = self._sync_domain_after_reconcile(
                        conn, inst_id, pos_side, source, _ts, qty, _new_avg
                    )
                    conn.execute(
                        "INSERT INTO fills (ts, inst_id, pos_side, action, qty, px, fee,"
                        " realized_pnl, ratio, source, domain)"
                        " VALUES (?,?,?,?,?,?,0,NULL,NULL,?,?)",
                        (_ts, inst_id, pos_side, "reconcile_update", qty, _new_avg, source, _dom),
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
                    " updated_at=excluded.updated_at, closed_at=NULL,"
                    # 交易所重新出现持仓：必须把 closed/stale 拉回 open，否则 effective
                    # 视图会漏计（2026-11-23 BNB 17 张 status=closed 但 qty>0）
                    " status=CASE WHEN excluded.qty > 1e-9 THEN 'open' ELSE positions.status END,"
                    " stale_since=CASE WHEN excluded.qty > 1e-9 THEN NULL"
                    " ELSE positions.stale_since END,"
                    " miss_count=CASE WHEN excluded.qty > 1e-9 THEN 0 ELSE positions.miss_count END",
                    (inst_id, pos_side, qty, avg, 1 if avg > 0 else 0, source, _ts, _ts),
                )
                _dom = self._sync_domain_after_reconcile(
                    conn, inst_id, pos_side, source, _ts, qty, avg
                )
                conn.execute(
                    "INSERT INTO fills (ts, inst_id, pos_side, action, qty, px, fee, realized_pnl,"
                    " ratio, source, domain) VALUES (?,?,?,?,?,?,0,NULL,NULL,?,?)",
                    (_ts, inst_id, pos_side, "reconcile", qty, avg, source, _dom),
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

    def _sync_domain_after_reconcile(
        self,
        conn: sqlite3.Connection,
        inst_id: str,
        pos_side: str,
        source: str,
        ts: str,
        qty: float,
        avg: float,
    ) -> str:
        """对账校正 L1 后同步 L2，保持 Σdomain_positions.qty == positions.qty；返回归属域。"""
        active = conn.execute(
            "SELECT domain FROM domain_positions WHERE inst_id=? AND pos_side=?"
            " AND qty>? AND status IN ('open','stale')",
            (inst_id, pos_side, _EPS),
        ).fetchone()
        # 归属沿用既有活跃域（一标的一域）；无活跃域时按对账源归 22
        _dom = str(active["domain"]) if active is not None else domain_of(source)
        self._ensure_domain_row(conn, inst_id, pos_side, _dom, ts)
        conn.execute(
            "UPDATE domain_positions SET qty=?, avg_entry=?, entry_known=?, updated_at=?,"
            " closed_at=NULL, status='open', source_detail=?"
            " WHERE inst_id=? AND pos_side=? AND domain=?",
            (qty, avg, 1 if avg > _EPS else 0, ts, source, inst_id, pos_side, _dom),
        )
        # 批次按当前交易所持仓重建为一条对账批，避免长期数量漂移累积
        conn.execute(
            "UPDATE position_lots SET remaining_qty=0, status='closed'"
            " WHERE inst_id=? AND pos_side=? AND domain=? AND status='open'",
            (inst_id, pos_side, _dom),
        )
        if qty > _EPS and avg > _EPS:
            conn.execute(
                "INSERT INTO position_lots(inst_id, pos_side, domain, qty, remaining_qty, px,"
                " opened_at, source_detail, decision_id, status)"
                " VALUES (?,?,?,?,?,?,?,'reconcile','','open')",
                (inst_id, pos_side, _dom, qty, qty, avg, ts),
            )
        return _dom

    # ── P1：域子账 / 批次 / 预占 / 对账工单 ─────────────────────────
    def list_domain_positions(
        self, domain: Optional[str] = None, include_closed: bool = False
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM domain_positions WHERE 1=1"
        params: List[Any] = []
        if not include_closed:
            sql += " AND qty > ?"
            params.append(_EPS)
        if domain:
            sql += " AND domain = ?"
            params.append(str(domain))
        sql += " ORDER BY updated_at DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_lots(
        self,
        inst_id: Optional[str] = None,
        pos_side: Optional[str] = None,
        domain: Optional[str] = None,
        only_open: bool = True,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM position_lots WHERE 1=1"
        params: List[Any] = []
        if inst_id:
            sql += " AND inst_id = ?"
            params.append(str(inst_id))
        if pos_side:
            sql += " AND pos_side = ?"
            params.append(str(pos_side))
        if domain:
            sql += " AND domain = ?"
            params.append(str(domain))
        if only_open:
            sql += " AND status = 'open'"
        sql += " ORDER BY lot_id ASC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def domain_qty_sum(self) -> float:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(qty),0) AS q FROM domain_positions WHERE qty > ?", (_EPS,)
            ).fetchone()
        return float(row["q"])

    def position_qty_sum(self) -> float:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(qty),0) AS q FROM positions WHERE qty > ?", (_EPS,)
            ).fetchone()
        return float(row["q"])

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM ledger_settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row is not None else default

    def domain_limits(self, domain: str) -> Dict[str, Any]:
        """读取域限额配置（domain_registry.limits_json）；缺失返回空 dict。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT limits_json, enabled FROM domain_registry WHERE domain=?",
                (str(domain),),
            ).fetchone()
        if row is None:
            return {}
        try:
            limits = json.loads(row["limits_json"] or "{}")
        except ValueError:
            limits = {}
        limits["_enabled"] = bool(row["enabled"])
        return limits

    def domain_notional(self, domain: str) -> float:
        """域内当前持仓名义（qty × avg_entry），用于限额判定。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(qty * avg_entry),0) AS n FROM domain_positions"
                " WHERE domain=? AND qty>?",
                (str(domain), _EPS),
            ).fetchone()
        return abs(float(row["n"])) if row else 0.0

    def set_setting(self, key: str, value: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO ledger_settings(key, value) VALUES(?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(key), str(value)),
            )

    # ── 预占额度（并发防超限） ──────────────────────────────────────
    def _expire_reservations_tx(self, conn: sqlite3.Connection, now_ts: str) -> int:
        cur = conn.execute(
            "UPDATE reservations SET state='expired', updated_at=?"
            " WHERE state='held' AND expires_at < ?",
            (now_ts, now_ts),
        )
        return int(cur.rowcount or 0)

    def reserve(
        self,
        domain: str,
        inst_id: str,
        pos_side: str,
        notional: float,
        decision_id: str = "",
        ttl: Optional[float] = None,
        limit_notional: Optional[float] = None,
        include_domain_positions: bool = False,
    ) -> Dict[str, Any]:
        """预占额度：与 active reservations 一起计算域限额，超限拒绝（U9 并发安全）。

        include_domain_positions=True 时把域内已有持仓名义也计入占用（P2-2 闸门口径）。
        """
        _notional = float(notional or 0)
        if _notional <= 0:
            return {"ok": False, "reason": "invalid_notional"}
        _dom = str(domain or "").strip().lower() or "legacy"
        _ttl = float(ttl if ttl is not None else 300.0)
        now = datetime.now(timezone.utc)
        now_ts = now.isoformat().replace("+00:00", "Z")
        exp_ts = (now + timedelta(seconds=_ttl)).isoformat().replace("+00:00", "Z")
        rid = f"resv-{uuid.uuid4().hex[:16]}"
        with self._tx() as conn:
            self._expire_reservations_tx(conn, now_ts)
            if limit_notional is not None:
                held_row = conn.execute(
                    "SELECT COALESCE(SUM(notional),0) AS n FROM reservations"
                    " WHERE domain=? AND state='held'",
                    (_dom,),
                ).fetchone()
                _held = float(held_row["n"]) if held_row else 0.0
                if include_domain_positions:
                    pos_row = conn.execute(
                        "SELECT COALESCE(SUM(qty * avg_entry),0) AS n FROM domain_positions"
                        " WHERE domain=? AND qty>?",
                        (_dom, _EPS),
                    ).fetchone()
                    _held += abs(float(pos_row["n"])) if pos_row else 0.0
                if _held + _notional > float(limit_notional) + _EPS:
                    return {"ok": False, "reason": "limit_exceeded", "held": _held}
            conn.execute(
                "INSERT INTO reservations(reservation_id, domain, inst_id, pos_side, notional,"
                " state, decision_id, created_at, expires_at, updated_at)"
                " VALUES (?,?,?,?,?,'held',?,?,?,?)",
                (
                    rid,
                    _dom,
                    str(inst_id),
                    str(pos_side),
                    _notional,
                    str(decision_id or ""),
                    now_ts,
                    exp_ts,
                    now_ts,
                ),
            )
        return {"ok": True, "reservation_id": rid, "expires_at": exp_ts}

    def release(self, reservation_id: str, state: str = "released") -> Dict[str, Any]:
        _state = str(state or "released")
        if _state not in ("consumed", "released", "expired"):
            _state = "released"
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE reservations SET state=?, updated_at=? WHERE reservation_id=?"
                " AND state='held'",
                (_state, _utc_now(), str(reservation_id)),
            )
            return {"ok": bool(cur.rowcount), "state": _state}

    def list_reservations(self, domain: Optional[str] = None, state: str = "held") -> List[Dict]:
        sql = "SELECT * FROM reservations WHERE state=?"
        params: List[Any] = [str(state)]
        if domain:
            sql += " AND domain=?"
            params.append(str(domain))
        sql += " ORDER BY created_at ASC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def held_notional(self, domain: str) -> float:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(notional),0) AS n FROM reservations"
                " WHERE domain=? AND state='held'",
                (str(domain),),
            ).fetchone()
        return float(row["n"]) if row else 0.0

    def expire_reservations(self) -> int:
        with self._tx() as conn:
            return self._expire_reservations_tx(conn, _utc_now())

    # ── 对账工单状态机 ─────────────────────────────────────────────
    def upsert_break(
        self,
        kind: str,
        inst_id: str,
        pos_side: str,
        domain: str = "",
        evidence: Optional[Dict[str, Any]] = None,
        sla_due_at: Optional[str] = None,
        ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        _ts = ts or _utc_now()
        with self._tx() as conn:
            bid = self._upsert_break_tx(
                conn,
                kind,
                str(inst_id),
                str(pos_side),
                str(domain or ""),
                evidence,
                _ts,
                sla_due_at,
            )
        return {"ok": True, "break_id": bid}

    def ack_break(self, break_id: int, owner_domain: str = "") -> Dict[str, Any]:
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE recon_breaks SET state='ACK', owner_domain=?"
                " WHERE break_id=? AND state='OPEN'",
                (str(owner_domain or ""), int(break_id)),
            )
        return {"ok": bool(cur.rowcount), "break_id": int(break_id)}

    def resolve_break(
        self, break_id: int, resolution: str = "", state: str = "RESOLVED"
    ) -> Dict[str, Any]:
        _state = str(state or "RESOLVED").upper()
        if _state not in ("RESOLVED", "WAIVED"):
            _state = "RESOLVED"
        _ts = _utc_now()
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE recon_breaks SET state=?, resolution=?, resolved_at=?"
                " WHERE break_id=? AND state IN ('OPEN','ACK')",
                (_state, str(resolution or ""), _ts, int(break_id)),
            )
        return {"ok": bool(cur.rowcount), "break_id": int(break_id), "state": _state}

    def list_breaks(
        self,
        state: Optional[str] = None,
        kind: Optional[str] = None,
        domain: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM recon_breaks WHERE 1=1"
        params: List[Any] = []
        if state:
            sql += " AND state=?"
            params.append(str(state))
        if kind:
            sql += " AND kind=?"
            params.append(str(kind))
        if domain:
            sql += " AND domain=?"
            params.append(str(domain))
        sql += " ORDER BY break_id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count_breaks(self, state: str = "OPEN") -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM recon_breaks WHERE state=?", (str(state),)
            ).fetchone()
        return int(row["n"]) if row else 0

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

    def note_miss(self, inst_id: str, pos_side: str, ts: Optional[str] = None) -> Dict[str, Any]:
        """janitor 记一次“交易所缺失”：维护首次缺失时间与 miss_count，不改 status。"""
        _ts = ts or _utc_now()
        with self._tx() as conn:
            row = conn.execute(
                "SELECT miss_count, stale_since, status FROM positions"
                " WHERE inst_id=? AND pos_side=? AND qty>?",
                (inst_id, pos_side, _EPS),
            ).fetchone()
            if row is None:
                return {"ok": False, "reason": "no_position"}
            _first = row["stale_since"] or _ts
            _miss = int(row["miss_count"] or 0) + 1
            conn.execute(
                "UPDATE positions SET miss_count=?, stale_since=? WHERE inst_id=? AND pos_side=?",
                (_miss, _first, inst_id, pos_side),
            )
            return {
                "ok": True,
                "miss_count": _miss,
                "first_miss_at": _first,
                "status": str(row["status"] or "open"),
            }

    def set_status(
        self,
        inst_id: str,
        pos_side: str,
        status: str,
        *,
        ts: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> bool:
        """janitor 状态迁移（open→stale→closed）；同时作用于 L1 与 L2 对应行。"""
        _status = str(status)
        if _status not in ("open", "stale", "closed"):
            return False
        _ts = ts or _utc_now()
        with self._tx() as conn:
            if _status == "stale":
                cur = conn.execute(
                    "UPDATE positions SET status='stale', stale_since=COALESCE(stale_since, ?),"
                    " updated_at=? WHERE inst_id=? AND pos_side=? AND qty>? AND status='open'",
                    (_ts, _ts, inst_id, pos_side, _EPS),
                )
            elif _status == "closed":
                cur = conn.execute(
                    "UPDATE positions SET status='closed', updated_at=?, closed_at=?"
                    " WHERE inst_id=? AND pos_side=? AND status IN ('open','stale')",
                    (_ts, _ts, inst_id, pos_side),
                )
            else:
                cur = conn.execute(
                    "UPDATE positions SET status='open', stale_since=NULL, miss_count=0,"
                    " updated_at=? WHERE inst_id=? AND pos_side=?",
                    (_ts, inst_id, pos_side),
                )
            if domain:
                conn.execute(
                    "UPDATE domain_positions SET status=?, updated_at=? WHERE inst_id=?"
                    " AND pos_side=? AND domain=? AND qty>?",
                    (_status, _ts, inst_id, pos_side, str(domain), _EPS),
                )
            return bool(cur.rowcount)

    def set_feed_state(self, state: str, ts: Optional[str] = None) -> None:
        _ts = ts or _utc_now()
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO ledger_settings(key, value) VALUES('feed_state', ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(state),),
            )
            conn.execute(
                "INSERT INTO ledger_settings(key, value) VALUES('feed_state_updated_at', ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_ts,),
            )

    def get_feed_state(self) -> str:
        return str(self.get_setting("feed_state", "ok") or "ok")

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

    def probe_position_count(self, domain: str = "23") -> int:
        """统计指定域当前存活 probe 批次覆盖的标的数据（探索仓配额用）。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT inst_id) AS n FROM position_lots"
                " WHERE domain=? AND status='open' AND remaining_qty > ? AND lower(tier)='probe'",
                (str(domain), _EPS),
            ).fetchone()
        return int(row["n"]) if row else 0

    def active_holders(self, inst_id: str) -> List[Dict[str, Any]]:
        """该标的全部活跃持有明细（域、方向、数量），跨域互斥守卫用。"""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT domain, pos_side, qty FROM domain_positions"
                " WHERE inst_id=? AND qty > ? AND status IN ('open','stale')"
                " ORDER BY domain, pos_side",
                (inst_id, _EPS),
            ).fetchall()
        return [
            {
                "domain": str(r["domain"] or ""),
                "pos_side": str(r["pos_side"] or ""),
                "qty": float(r["qty"]),
            }
            for r in rows
        ]

    def active_domain_holders(self, inst_id: str, pos_side: Optional[str] = None) -> List[str]:
        """该标的前持有域（跨域互斥守卫用）：qty>0 且未平仓的 domain 集合。

        P1 不变量为「一标的一域」，23/50 经 shared_outcomes 共享单出口时，
        由调用方据此拒绝他域已在持的开仓，避免同标的双向恶性竞争。
        """
        sql = (
            "SELECT DISTINCT domain FROM domain_positions"
            " WHERE inst_id=? AND qty > ? AND status IN ('open','stale')"
        )
        params: List[Any] = [inst_id, _EPS]
        if pos_side:
            sql += " AND pos_side=?"
            params.append(pos_side)
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY domain", params).fetchall()
        return [str(r[0] or "") for r in rows if r[0]]

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
