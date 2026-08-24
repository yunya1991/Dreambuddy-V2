"""
SqliteRiskRepository — 风控状态 + 案例（rs_state + rs_cases）
=============================================================

【字段映射策略】
SCHEMA_DESIGN.md §6 定义的 rs_state 是「风控引擎开关」表（circuit_breaker / kill_switch /
halt 等列），但 P0 Protocol 的 RiskState 是「全系统综合风险快照」（total_equity_usd /
五计庙算 war_state / 权益曲线指标等）。为了不重写 Schema + 保持乐观锁触发器复用，本实现
对 rs_state 做**幂等补列**，覆盖 RiskState 全部 22 字段；_version 乐观锁列保持
SCHEMA_DESIGN 触发器自动 +1。

对 rs_cases（§6.2 风控告警案例）：RiskCaseRecord 字段是 rule_id / rule_name /
severity_score / resolution_notes 等，rs_cases DDL 列名不完全一致 → 全部补列 + 旧列兼容。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.protocols.risk_repo import RiskRepository
from dreambuddy_dal.unified_models import (
    RiskCaseRecord,
    RiskLevel,
    RiskState,
    TradeDirection,
)

from .schema_init import _add_column_if_missing, _ensure_singleton_row


# ---------------------------------------------------------------------------
# 通用小工具（复用 trade_impl / position_impl 同风格）
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


def _enum_val(v) -> Optional[str]:
    if v is None:
        return None
    return v.value if hasattr(v, "value") else str(v)


# ============================================================
# Repository
# ============================================================
class SqliteRiskRepository(RiskRepository):
    """rs_state（单行 id=1 + 乐观锁 _version 触发器）和 rs_cases（风控案例）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_columns()
        self._ensure_singleton()

    # ------------------------------------------------------------------
    # 补列：rs_state 列集合 ⊇ RiskState SSoT 字段集合
    # ------------------------------------------------------------------
    def _ensure_columns(self) -> None:
        # rs_state 新增列（RiskState 14 个核心字段 + 可选列 + extra_payload）
        state_ddls = [
            "total_equity_usd TEXT DEFAULT '0'",
            "gross_exposure_usd TEXT DEFAULT '0'",
            "net_exposure_usd TEXT DEFAULT '0'",
            "gross_leverage TEXT DEFAULT '0'",
            "max_position_pct_usd TEXT DEFAULT '0'",
            "win_rate_7d TEXT DEFAULT '0'",
            "max_drawdown_active TEXT DEFAULT '0'",
            "equity_curve_avg TEXT DEFAULT '0'",
            "equity_curve_std TEXT DEFAULT '0'",
            "active_symbols_count INTEGER DEFAULT 0",
            "overall_risk TEXT DEFAULT 'MEDIUM'",
            "next_allowed_trade_ts TEXT",
            "active_alert_ids TEXT DEFAULT ''",
            "war_state TEXT",
            "strategy_mask INTEGER",
            "style_exposure TEXT",
            "extra_payload TEXT",
            "created_at TEXT",  # ← RiskState.created_at 需要
        ]
        # rs_cases 新增列（RiskCaseRecord 用）
        case_ddls = [
            "rule_name TEXT DEFAULT ''",
            "risk_level TEXT DEFAULT 'LOW'",
            "symbol TEXT",
            "direction TEXT",
            "severity_score INTEGER",
            "evidence_json TEXT",
            "resolution_notes TEXT",
            "resolved_at TEXT",
            "extra_payload TEXT",
            # RiskCaseRecord.detected_at 在 schema 里叫 alert_ts → 也补 detected_at 方便直接映射
            "detected_at TEXT",
            # RiskCaseRecord.trade_id 在 schema 里叫 related_trade_id → 也补 trade_id
            "trade_id TEXT",
            # RiskCaseRecord.rule_id 在 schema 里叫 case_type → 也补 rule_id
            "rule_id TEXT DEFAULT ''",
        ]
        with get_sqlite_connection(self.db_path) as conn:
            for ddl in state_ddls:
                col = ddl.split()[0]
                _add_column_if_missing(conn, "rs_state", col, ddl)
            for ddl in case_ddls:
                col = ddl.split()[0]
                _add_column_if_missing(conn, "rs_cases", col, ddl)
            # rs_cases.related_trade_id REFERENCES tr_trades(trade_id)：
            # 给 trade_id=None 时用占位行 __NO_LINK__（和 po_positions 同一占位）
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

    def _ensure_singleton(self) -> None:
        """rs_state 强制单行 id=1（空表时用最小 seed 值占位；第一次 update_state 会覆盖真实列）。"""
        defaults: Dict[str, Any] = {
            "daily_pnl": 0,
            "total_risk_exposure": "0",
            "open_positions_count": 0,
            "daily_realized_pnl": "0",
            "daily_loss_limit": -1000,
            "loss_limit_pct": 0.20,
            "daily_drawdown_pct": 0,
            "circuit_breaker_active": 0,
            "kill_switch_active": 0,
            "current_consecutive_losses": 0,
            "max_consecutive_losses": 0,
            "trading_halted": 0,
            # 以下 RiskState 列也给默认，避免第一次 SELECT 回来是 None
            "total_equity_usd": "0",
            "gross_exposure_usd": "0",
            "net_exposure_usd": "0",
            "gross_leverage": "0",
            "max_position_pct_usd": "0",
            "win_rate_7d": "0",
            "max_drawdown_active": "0",
            "equity_curve_avg": "0",
            "equity_curve_std": "0",
            "active_symbols_count": 0,
            "overall_risk": "MEDIUM",
            "version": 1,  # DB 触发器会维护，INSERT 初始给 1
        }
        with get_sqlite_connection(self.db_path) as conn:
            _ensure_singleton_row(conn, "rs_state", defaults)

    # ============================================================
    # RiskRepository 4 个抽象方法
    # ============================================================
    def get_state(self, id: int = 1) -> Optional[RiskState]:
        cols = """id, total_equity_usd, gross_exposure_usd, net_exposure_usd,
          gross_leverage, max_position_pct_usd, win_rate_7d, max_drawdown_active,
          equity_curve_avg, equity_curve_std, active_symbols_count, overall_risk,
          next_allowed_trade_ts, active_alert_ids, war_state, strategy_mask,
          style_exposure, extra_payload,
          version, created_at, updated_at"""
        with get_sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {cols} FROM rs_state WHERE id = ?", (id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_risk_state(row)

    def update_state(
        self,
        new_state: RiskState,
        *,
        expected_version: Optional[int] = None,
    ) -> bool:
        """
        乐观锁写入：
        - expected_version=None：首次或强制写入（INSERT OR REPLACE 单行；WHERE 不加 version）
        - expected_version=N：只在 _version=N 时更新；rowcount=0 返回 False（并发冲突）
        version 永远不读 Python 层 new_state.version（只读 DB 触发器维护的 _version）。
        """
        bind: List[Any] = [
            str(new_state.total_equity_usd),
            str(new_state.gross_exposure_usd),
            str(new_state.net_exposure_usd),
            str(new_state.gross_leverage),
            str(new_state.max_position_pct_usd),
            str(new_state.win_rate_7d),
            str(new_state.max_drawdown_active),
            str(new_state.equity_curve_avg),
            str(new_state.equity_curve_std),
            int(new_state.active_symbols_count),
            _enum_val(new_state.overall_risk),
            _iso_z(new_state.next_allowed_trade_ts),
            new_state.active_alert_ids or "",
            new_state.war_state,
            int(new_state.strategy_mask) if new_state.strategy_mask is not None else None,
            new_state.style_exposure,
            (
                json.dumps(new_state.extra_payload, ensure_ascii=False)
                if isinstance(new_state.extra_payload, dict) and new_state.extra_payload
                else None
            ),
        ]
        if expected_version is None:
            sql = """
            INSERT INTO rs_state (id, total_equity_usd, gross_exposure_usd, net_exposure_usd,
                gross_leverage, max_position_pct_usd, win_rate_7d, max_drawdown_active,
                equity_curve_avg, equity_curve_std, active_symbols_count, overall_risk,
                next_allowed_trade_ts, active_alert_ids, war_state, strategy_mask,
                style_exposure, extra_payload)
            VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                total_equity_usd=excluded.total_equity_usd,
                gross_exposure_usd=excluded.gross_exposure_usd,
                net_exposure_usd=excluded.net_exposure_usd,
                gross_leverage=excluded.gross_leverage,
                max_position_pct_usd=excluded.max_position_pct_usd,
                win_rate_7d=excluded.win_rate_7d,
                max_drawdown_active=excluded.max_drawdown_active,
                equity_curve_avg=excluded.equity_curve_avg,
                equity_curve_std=excluded.equity_curve_std,
                active_symbols_count=excluded.active_symbols_count,
                overall_risk=excluded.overall_risk,
                next_allowed_trade_ts=excluded.next_allowed_trade_ts,
                active_alert_ids=excluded.active_alert_ids,
                war_state=excluded.war_state,
                strategy_mask=excluded.strategy_mask,
                style_exposure=excluded.style_exposure,
                extra_payload=excluded.extra_payload
            """
            final_bind: List[Any] = bind  # id=1 在 VALUES 字面量写死，所以不用 prepend
        else:
            sql = """
            UPDATE rs_state SET
                total_equity_usd=?, gross_exposure_usd=?, net_exposure_usd=?,
                gross_leverage=?, max_position_pct_usd=?, win_rate_7d=?,
                max_drawdown_active=?, equity_curve_avg=?, equity_curve_std=?,
                active_symbols_count=?, overall_risk=?,
                next_allowed_trade_ts=?, active_alert_ids=?, war_state=?,
                strategy_mask=?, style_exposure=?, extra_payload=?
            WHERE id = 1 AND version = ?
            """
            final_bind = bind + [int(expected_version)]
        with get_sqlite_connection(self.db_path) as conn:
            cur = conn.execute(sql, final_bind)
        # UPDATE 时：rowcount=0 → 并发冲突（version 不匹配）→ False
        # INSERT 时：rowcount 不管 → True
        if expected_version is None:
            return True
        return cur.rowcount > 0

    def add_case(self, case: RiskCaseRecord) -> bool:
        """幂等：重复 case_id → INSERT IGNORE 0 row → 返回 False。"""
        sql = """
        INSERT OR IGNORE INTO rs_cases (
            case_id, rule_id, rule_name, case_type,
            severity_score, severity, risk_level,
            symbol, direction, trade_id, related_trade_id,
            alert_ts, detected_at, action_taken,
            evidence_json, state_snapshot, resolution_notes,
            resolved_at, extra_payload
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        detected_s = _iso_z(case.detected_at)
        resolved_s = _iso_z(case.resolved_at)
        direction_db = _enum_val(case.direction)
        if direction_db is not None:
            direction_db = direction_db.lower()  # 与 schema direction CHECK('long','short') 对齐
        risk_val = _enum_val(case.risk_level)
        evidence_json = case.evidence_json
        if not evidence_json:
            evidence_json = "{}"
        state_snapshot = (
            json.dumps(case.extra_payload, ensure_ascii=False)
            if isinstance(case.extra_payload, dict) and case.extra_payload
            else "{}"
        )
        extra_s = (
            json.dumps(case.extra_payload, ensure_ascii=False)
            if isinstance(case.extra_payload, dict) and case.extra_payload
            else None
        )
        severity_score_raw = (
            int(case.severity_score) if case.severity_score is not None else 0
        )
        # rs_cases.severity（旧列）CHECK 0-5；severity_score（补列）保持 0-100 原值
        severity_0_5 = max(0, min(5, severity_score_raw // 20))
        # rs_cases.related_trade_id REFERENCES tr_trades(trade_id)：
        # 旧列统一用占位行 __NO_LINK__ 以避免 FK 失败（case.trade_id 原值存补列 trade_id）
        fk_trade_id = "__NO_LINK__"
        bind = (
            case.case_id,                                  # case_id PK
            case.rule_id,                                  # rule_id（补列）
            case.rule_name,                                # rule_name（补列）
            case.rule_id,                                  # case_type（旧列）= rule_id
            case.severity_score,                           # severity_score（补列）
            severity_0_5,                                  # severity（旧列 INTEGER CHECK 0-5）
            risk_val,                                      # risk_level（补列 TEXT）
            case.symbol,
            direction_db,
            case.trade_id,                                 # trade_id（补列）
            fk_trade_id,                                   # related_trade_id（旧列 FK）
            detected_s,                                    # alert_ts（旧列）
            detected_s,                                    # detected_at（补列）
            case.action_taken,
            evidence_json,                                 # evidence_json（补列）
            state_snapshot,                                # state_snapshot（旧列 NOT NULL）
            case.resolution_notes,
            resolved_s,
            extra_s,
        )
        with get_sqlite_connection(self.db_path) as conn:
            cur = conn.execute(sql, bind)
        return cur.rowcount > 0

    def query_cases(
        self,
        *,
        start_ts: Optional[datetime] = None,
        end_ts: Optional[datetime] = None,
        min_severity: Optional[int] = None,
        risk_level: Optional[RiskLevel] = None,
        symbol: Optional[str] = None,
        limit: int = 500,
    ) -> List[RiskCaseRecord]:
        cols = """case_id, COALESCE(detected_at, alert_ts) AS detected_at,
          COALESCE(risk_level, 'LOW') AS risk_level,
          COALESCE(rule_id, case_type) AS rule_id,
          rule_name, action_taken, symbol, direction,
          COALESCE(severity_score, severity) AS severity_score,
          trade_id, evidence_json, resolution_notes, resolved_at,
          extra_payload"""
        sql = f"SELECT {cols} FROM rs_cases WHERE 1=1"
        params: List[Any] = []
        if start_ts is not None:
            sql += " AND COALESCE(detected_at, alert_ts) >= ?"
            params.append(_iso_z(start_ts))
        if end_ts is not None:
            sql += " AND COALESCE(detected_at, alert_ts) <= ?"
            params.append(_iso_z(end_ts))
        if min_severity is not None:
            sql += " AND COALESCE(severity_score, severity) >= ?"
            params.append(int(min_severity))
        if risk_level is not None:
            sql += " AND COALESCE(risk_level, 'LOW') = ?"
            params.append(_enum_val(risk_level))
        if symbol is not None:
            sql += " AND symbol = ?"
            params.append(symbol)
        sql += " ORDER BY COALESCE(detected_at, alert_ts) DESC LIMIT ?"
        params.append(int(limit))
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_case(r) for r in rows]


# ============================================================
# Row → 对象
# ============================================================
def _row_to_risk_state(row) -> RiskState:
    (
        id_, total_equity_usd, gross_exposure_usd, net_exposure_usd,
        gross_leverage, max_position_pct_usd, win_rate_7d, max_drawdown_active,
        equity_curve_avg, equity_curve_std, active_symbols_count, overall_risk,
        next_allowed_trade_ts, active_alert_ids, war_state, strategy_mask,
        style_exposure, extra_payload_raw, version, _ca, _ua,
    ) = row
    extra: Dict[str, Any] = {}
    if extra_payload_raw:
        try:
            extra = json.loads(str(extra_payload_raw))
            if not isinstance(extra, dict):
                extra = {}
        except Exception:
            extra = {}
    return RiskState(
        id=int(id_ or 1),
        total_equity_usd=_to_dec(total_equity_usd),
        gross_exposure_usd=_to_dec(gross_exposure_usd),
        net_exposure_usd=_to_dec(net_exposure_usd),
        gross_leverage=_to_dec(gross_leverage),
        max_position_pct_usd=_to_dec(max_position_pct_usd),
        win_rate_7d=_to_dec(win_rate_7d),
        max_drawdown_active=_to_dec(max_drawdown_active),
        equity_curve_avg=_to_dec(equity_curve_avg),
        equity_curve_std=_to_dec(equity_curve_std),
        active_symbols_count=int(active_symbols_count or 0),
        overall_risk=_from_enum(RiskLevel, overall_risk, RiskLevel.MEDIUM),
        next_allowed_trade_ts=_parse_iso_utc(next_allowed_trade_ts),
        active_alert_ids=str(active_alert_ids or ""),
        war_state=str(war_state) if war_state not in (None, "") else None,
        strategy_mask=(
            int(strategy_mask) if strategy_mask is not None else None
        ),
        style_exposure=str(style_exposure) if style_exposure not in (None, "") else None,
        extra_payload=extra,
        version=int(version or 0),
        created_at=_parse_iso_utc(_ca),
        updated_at=_parse_iso_utc(_ua),
    )


def _row_to_case(row) -> RiskCaseRecord:
    (
        case_id, detected_at, risk_level_raw, rule_id, rule_name,
        action_taken, symbol, direction_raw, severity_score, trade_id,
        evidence_json, resolution_notes, resolved_at, extra_payload_raw,
    ) = row
    extra: Dict[str, Any] = {}
    if extra_payload_raw:
        try:
            extra = json.loads(str(extra_payload_raw))
            if not isinstance(extra, dict):
                extra = {}
        except Exception:
            extra = {}
    return RiskCaseRecord(
        case_id=str(case_id or ""),
        detected_at=_parse_iso_utc(detected_at) or datetime.now(timezone.utc),
        risk_level=_from_enum(RiskLevel, risk_level_raw, RiskLevel.LOW),
        rule_id=str(rule_id or ""),
        rule_name=str(rule_name or ""),
        action_taken=str(action_taken or ""),
        symbol=str(symbol) if symbol not in (None, "") else None,
        direction=_from_enum(TradeDirection, direction_raw, None, case_insensitive=True),
        severity_score=(
            int(severity_score) if severity_score is not None else None
        ),
        trade_id=str(trade_id) if trade_id not in (None, "") else None,
        evidence_json=str(evidence_json) if evidence_json not in (None, "") else None,
        resolution_notes=(
            str(resolution_notes) if resolution_notes not in (None, "") else None
        ),
        resolved_at=_parse_iso_utc(resolved_at),
        extra_payload=extra,
    )
