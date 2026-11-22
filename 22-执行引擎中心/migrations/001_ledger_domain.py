#!/usr/bin/env python3
"""P1-1/P1-4 增量迁移入口（幂等，可重复执行）。

DDL 与历史归属回填内聚在 `position_ledger._migrate_p1`，本脚本仅负责：
  1. 触发迁移（构造 PositionLedger 即自动执行）；
  2. 校验 L1/L2 控制总数一致（Σpositions.qty == Σdomain_positions.qty）；
  3. 输出域分布与迁移批次统计，供云端部署后人工确认。

只做增量变更（ADD COLUMN / CREATE TABLE），旧代码可继续运行；
历史 realized_pnl 无法精确拆域，回填统一记 0（SPEC §4.7），不得用于绩效结算。

用法：
  POSITION_LEDGER_PATH=/path/ledger.db python3 migrations/001_ledger_domain.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from position_ledger import PositionLedger  # noqa: E402

_TABLES = (
    "domain_positions",
    "position_lots",
    "reservations",
    "recon_breaks",
    "domain_registry",
)
_VIEWS = ("v_effective_positions", "v_domain_positions")


def _schema_objects(led: PositionLedger, kind: str) -> set:
    with led._connect() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type=?", (kind,)).fetchall()
    return {str(r[0]) for r in rows}


def _migrations(led: PositionLedger) -> list:
    with led._connect() as conn:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [str(r[0]) for r in rows]


def main() -> int:
    led = PositionLedger(os.getenv("POSITION_LEDGER_PATH"))
    tables = _schema_objects(led, "table")
    views = _schema_objects(led, "view")
    pos_sum = led.position_qty_sum()
    dom_sum = led.domain_qty_sum()
    balanced = abs(pos_sum - dom_sum) <= 1e-9
    out = {
        "db": str(led.path),
        "migrations": _migrations(led),
        "tables_ok": {t: (t in tables) for t in _TABLES},
        "views_ok": {v: (v in views) for v in _VIEWS},
        "positions_qty_total": round(pos_sum, 9),
        "domain_qty_total": round(dom_sum, 9),
        "balances": balanced,
        "domains": [
            {
                "domain": d.get("domain"),
                "inst_id": d.get("inst_id"),
                "pos_side": d.get("pos_side"),
                "qty": d.get("qty"),
                "avg_entry": d.get("avg_entry"),
            }
            for d in led.list_domain_positions(include_closed=False)
        ],
        "open_lots": len(led.list_lots(only_open=True)),
        "settings": {
            k: led.get_setting(k)
            for k in (
                "effective_ttl_seconds",
                "stale_after_seconds",
                "close_after_seconds",
                "min_confirmations",
                "lot_close_policy",
                "janitor_enforce",
            )
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if balanced and all(out["tables_ok"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
