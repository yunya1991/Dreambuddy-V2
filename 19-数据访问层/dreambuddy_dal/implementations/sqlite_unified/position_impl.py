"""
SqlitePositionRepository — 净持仓快照 Repository（po_positions）
=================================================================

【字段映射策略 — 最小化 Schema 迁移】
SCHEMA_DESIGN.md §4.1 po_positions 原本是「逐笔持仓明细」风格（inst_id PK, trade_id FK）。
P0 Protocol 的 PositionState SSoT 是「净持仓汇总」风格（position_id={s}:{d}:{sub},
avg_entry_price + open_quantity + source_trade_ids）。
因此在本实现中：
1. 复用 po_positions 表（不新建表），通过 `_add_column_if_missing` 把 PositionState
   需要的列补齐（avg_entry_price / open_quantity / cost_basis / leverage / margin_used /
   last_price_refresh_ts / source_trade_ids / extra_payload）。
2. 「双写」保持与旧列兼容：
   - avg_entry_price ←→ entry_price（同时写两列，读优先 avg_entry_price）
   - open_quantity   ←→ quantity（同时写）
   - last_price_refresh_ts ←→ last_price_refresh_at（同时写 ISO UTC TEXT）
3. PK 复用：DB 的 inst_id PK 直接存 position_id（PositionState 的天然唯一键）。
4. ADR-19-004：所有 Decimal 字段一律 TEXT（SQLite 不存 REAL 防精度丢失）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.protocols.position_repo import PositionRepository
from dreambuddy_dal.unified_models import PositionState, TradeDirection

from .schema_init import _add_column_if_missing


# ---------------------------------------------------------------------------
# 辅助函数（和 trade_impl 保持同风格；TradeDirection.lower 存 → case_insensitive 重建）
# ---------------------------------------------------------------------------
def _to_dec(x: Any) -> Decimal:
    if x is None or x == "":
        return Decimal("0")
    return Decimal(str(x))


def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif dt.utcoffset() is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_iso_utc(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _enum_val_lower(v) -> Optional[str]:
    """enum.value 或 str → 小写（适配 CHECK(direction IN ('long','short'))）。"""
    if v is None:
        return None
    raw = v.value if hasattr(v, "value") else str(v)
    return str(raw).lower()


def _from_enum(enum_cls, raw, default, *, case_insensitive: bool = False):
    if raw is None:
        return default
    raw_str = str(raw)
    try:
        return enum_cls(raw_str)
    except ValueError:
        if case_insensitive:
            for e in enum_cls:
                if e.value.lower() == raw_str.lower():
                    return e
        return default


# ============================================================
# Repository
# ============================================================
class SqlitePositionRepository(PositionRepository):
    """po_positions 净持仓快照（SCHEMA_DESIGN 旧列 + 补列映射）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_columns()

    # ----------------------------------------------------------
    # 补列（幂等）：让 po_positions 列集合 ⊇ PositionState 字段集合
    # ----------------------------------------------------------
    def _ensure_columns(self) -> None:
        # 每个元素是完整的 ALTER TABLE ADD COLUMN 右半段（含列名、类型、DEFAULT）
        col_ddls = [
            "position_id TEXT DEFAULT ''",
            "avg_entry_price TEXT DEFAULT '0'",     # ← 主列（和 entry_price 双写）
            "open_quantity TEXT DEFAULT '0'",       # ← 主列（和 quantity 双写）
            "cost_basis TEXT",
            "leverage INTEGER DEFAULT 1",
            "margin_used TEXT",
            "last_price_refresh_ts TEXT",           # ← 主列（和 last_price_refresh_at 双写）
            "source_trade_ids TEXT DEFAULT ''",
            "extra_payload TEXT",
        ]
        with get_sqlite_connection(self.db_path) as conn:
            # 1) 补列
            for col_ddl in col_ddls:
                col_name = col_ddl.split()[0]
                _add_column_if_missing(conn, "po_positions", col_name, col_ddl)
            # 2) 虚拟占位 trade 行（po_positions.trade_id FK REFERENCES tr_trades）。
            #    SCHEMA_DESIGN po_positions 是逐笔持仓模型（trade_id NOT NULL FK），
            #    本 Repository 把 po_positions 改做净持仓用，不绑定具体 Trade，
            #    用虚拟占位 trade_id="__NO_LINK__" 满足 FK 约束。
            now_iso = _iso_z(datetime.now(timezone.utc))
            conn.execute(
                """
                INSERT OR IGNORE INTO tr_trades (
                    trade_id, symbol, entry_price, quantity, entry_ts,
                    direction, risk_level_cn
                ) VALUES (?, 'PLACEHOLDER', '0', '0', ?, 'long', 'MEDIUM')
                """,
                ("__NO_LINK__", now_iso),
            )

    # ============================================================
    # PositionRepository 4 个抽象方法
    # ============================================================
    def upsert_position(self, position: PositionState) -> bool:
        """主键 position_id 幂等写入（INSERT OR REPLACE）。"""
        # PositionState 的 __post_init__ 已经保证 position_id、cost_basis
        pos_id = position.position_id or (
            f"{position.symbol}:{position.direction.value}:{position.sub_system}"
        )
        direction_db = _enum_val_lower(position.direction)
        avg_ep = str(position.avg_entry_price)
        oq = str(position.open_quantity)
        cost_b = str(position.cost_basis) if position.cost_basis is not None else None
        margin_u = str(position.margin_used) if position.margin_used is not None else None
        mark_p = str(position.mark_price) if position.mark_price is not None else None
        liq_p = str(position.liquidation_price) if position.liquidation_price is not None else None
        unreal = str(position.unrealized_pnl)
        lr_ts = _iso_z(position.last_price_refresh_ts)
        # 两列都是 NOT NULL DEFAULT CURRENT_TIMESTAMP；传 None 进 NOT NULL 会约束失败
        if lr_ts is None:
            lr_ts = _iso_z(datetime.now(timezone.utc))
        extra_s = (
            json.dumps(position.extra_payload, ensure_ascii=False)
            if isinstance(position.extra_payload, dict) and position.extra_payload
            else "{}"
        )
        source_ids = position.source_trade_ids or ""
        opened_at = _iso_z(datetime.now(timezone.utc))

        # 24 列 = VALUES 24 个 ?（严格顺序，不要 CURRENT_TIMESTAMP 字面量；Python 层传字符串）
        sql = """
        INSERT INTO po_positions (
            inst_id, position_id, trade_id, sub_system, symbol, direction,
            entry_price, avg_entry_price, quantity, open_quantity, opened_at,
            mark_price, unrealized_pnl, liquidation_price, current_leverage,
            leverage, margin_used, cost_basis, last_price_refresh_at,
            last_price_refresh_ts, source_trade_ids, is_trial, extra_payload,
            updated_at
        ) VALUES (?,?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?)
        ON CONFLICT(inst_id) DO UPDATE SET
            position_id=excluded.position_id,
            sub_system=excluded.sub_system,
            symbol=excluded.symbol,
            direction=excluded.direction,
            entry_price=excluded.entry_price,
            avg_entry_price=excluded.avg_entry_price,
            quantity=excluded.quantity,
            open_quantity=excluded.open_quantity,
            mark_price=excluded.mark_price,
            unrealized_pnl=excluded.unrealized_pnl,
            liquidation_price=excluded.liquidation_price,
            current_leverage=excluded.current_leverage,
            leverage=excluded.leverage,
            margin_used=excluded.margin_used,
            cost_basis=excluded.cost_basis,
            last_price_refresh_at=excluded.last_price_refresh_at,
            last_price_refresh_ts=excluded.last_price_refresh_ts,
            source_trade_ids=excluded.source_trade_ids,
            is_trial=excluded.is_trial,
            extra_payload=excluded.extra_payload,
            updated_at=CURRENT_TIMESTAMP
        """
        bind = (
            pos_id, pos_id, "__NO_LINK__", position.sub_system, position.symbol, direction_db,  # 6
            avg_ep, avg_ep, oq, oq, opened_at,                                        # +5 = 11
            mark_p, unreal, liq_p, float(position.leverage),                         # +4 = 15
            position.leverage, margin_u, cost_b,                                      # +3 = 18
            lr_ts, lr_ts,                                                             # +2 = 20
            source_ids, 1 if position.is_trial else 0, extra_s,                      # +3 = 23
            lr_ts,  # updated_at（Python 层给；ON CONFLICT UPDATE 覆盖为 CURRENT_TIMESTAMP）
        )                                                                              # +1 = 24
        with get_sqlite_connection(self.db_path) as conn:
            conn.execute(sql, bind)
        return True

    def get_position(
        self,
        symbol: str,
        sub_system: Optional[str] = None,
        direction: Optional[TradeDirection] = None,
    ) -> Optional[PositionState]:
        sql = """SELECT symbol, sub_system, direction,
                        COALESCE(avg_entry_price, entry_price) AS avg_entry_price,
                        COALESCE(open_quantity, quantity) AS open_quantity,
                        unrealized_pnl, cost_basis,
                        COALESCE(leverage, CAST(ROUND(COALESCE(current_leverage,1)) AS INT)) AS leverage,
                        margin_used, mark_price, liquidation_price,
                        COALESCE(last_price_refresh_ts, last_price_refresh_at) AS last_price_refresh_ts,
                        source_trade_ids, is_trial, extra_payload, position_id, created_at, updated_at
                 FROM po_positions
                 WHERE symbol = ?"""
        params: List[Any] = [symbol]
        if sub_system is not None:
            sql += " AND sub_system = ?"
            params.append(sub_system)
        if direction is not None:
            sql += " AND direction = ?"
            params.append(_enum_val_lower(direction))
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        if len(rows) == 0:
            return None
        if len(rows) > 1 and sub_system is None:
            raise ValueError(
                f"get_position({symbol=}, sub_system=None, direction={direction}) "
                f"命中 {len(rows)} 条持仓，必须显式指定 sub_system 避免歧义。"
            )
        return _row_to_position(rows[0])

    def list_positions(
        self,
        sub_system: Optional[str] = None,
        *,
        symbol: Optional[str] = None,
    ) -> List[PositionState]:
        sql = """SELECT symbol, sub_system, direction,
                        COALESCE(avg_entry_price, entry_price) AS avg_entry_price,
                        COALESCE(open_quantity, quantity) AS open_quantity,
                        unrealized_pnl, cost_basis,
                        COALESCE(leverage, CAST(ROUND(COALESCE(current_leverage,1)) AS INT)) AS leverage,
                        margin_used, mark_price, liquidation_price,
                        COALESCE(last_price_refresh_ts, last_price_refresh_at) AS last_price_refresh_ts,
                        source_trade_ids, is_trial, extra_payload, position_id, created_at, updated_at
                 FROM po_positions WHERE 1=1"""
        params: List[Any] = []
        if sub_system is not None:
            sql += " AND sub_system = ?"
            params.append(sub_system)
        if symbol is not None:
            sql += " AND symbol = ?"
            params.append(symbol)
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_position(r) for r in rows]

    def refresh_mark_price(
        self,
        position_id: str,
        mark_price: Decimal,
        unrealized_pnl: Decimal,
        refresh_ts: datetime,
        *,
        liquidation_price: Optional[Decimal] = None,
    ) -> bool:
        ts = _iso_z(refresh_ts)
        sql = """
        UPDATE po_positions SET
            mark_price = ?,
            unrealized_pnl = ?,
            liquidation_price = COALESCE(?, liquidation_price),
            last_price_refresh_at = ?,
            last_price_refresh_ts = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE position_id = ? OR inst_id = ?
        """
        bind = [
            str(mark_price),
            str(unrealized_pnl),
            str(liquidation_price) if liquidation_price is not None else None,
            ts,
            ts,
            position_id,
            position_id,
        ]
        with get_sqlite_connection(self.db_path) as conn:
            cur = conn.execute(sql, bind)
        return cur.rowcount > 0


# ============================================================
# Row → PositionState
# ============================================================
def _row_to_position(row) -> PositionState:
    (
        symbol, sub_system, direction_raw, avg_entry_price, open_quantity,
        unrealized_pnl, cost_basis, leverage, margin_used, mark_price,
        liquidation_price, lp_ts, source_trade_ids, is_trial, extra_payload_raw,
        position_id, _ca, _ua,
    ) = row

    extra: Dict[str, Any] = {}
    if extra_payload_raw:
        try:
            extra = json.loads(str(extra_payload_raw))
            if not isinstance(extra, dict):
                extra = {}
        except Exception:
            extra = {}

    return PositionState(
        symbol=str(symbol or ""),
        sub_system=str(sub_system or ""),
        direction=_from_enum(TradeDirection, direction_raw, TradeDirection.LONG, case_insensitive=True),
        avg_entry_price=_to_dec(avg_entry_price),
        open_quantity=_to_dec(open_quantity),
        unrealized_pnl=_to_dec(unrealized_pnl),
        cost_basis=_to_dec(cost_basis) if cost_basis not in (None, "") else None,
        leverage=int(leverage) if leverage is not None else 1,
        margin_used=_to_dec(margin_used) if margin_used not in (None, "") else None,
        mark_price=_to_dec(mark_price) if mark_price not in (None, "") else None,
        liquidation_price=_to_dec(liquidation_price) if liquidation_price not in (None, "") else None,
        last_price_refresh_ts=_parse_iso_utc(lp_ts),
        source_trade_ids=str(source_trade_ids or ""),
        is_trial=bool(is_trial),
        extra_payload=extra,
        position_id=str(position_id or ""),
        created_at=_parse_iso_utc(_ca),
        updated_at=_parse_iso_utc(_ua),
    )
