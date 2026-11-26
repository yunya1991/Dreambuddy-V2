"""ledger ghost 指标拆分：exchange_flat 与 stale 分开告警。"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from exporter.business_metrics_exporter import Collector  # noqa: E402


def _make_ledger(root: Path) -> None:
    runtime = root / "22-执行引擎中心/runtime"
    runtime.mkdir(parents=True)
    conn = sqlite3.connect(runtime / "position_ledger.db")
    conn.executescript("""
        CREATE TABLE positions (inst_id TEXT, pos_side TEXT, qty REAL);
        CREATE TABLE fills (ts TEXT, action TEXT);
        CREATE TABLE cooldowns (inst_id TEXT, exit_reason TEXT, close_ts TEXT);
        """)
    conn.execute("INSERT INTO fills VALUES ('2026-11-18T00:00:00Z','close')")
    rows = [("BTC-USDT-SWAP", "ghost_stale") for _ in range(12)]
    rows.append(("ETH-USDT-SWAP", "ghost_exchange_flat"))
    rows.extend([("XAG-USDT-SWAP", "exchange_sltp"), ("UNI-USDT-SWAP", "exchange_sltp")])
    conn.executemany("INSERT INTO cooldowns VALUES (?, ?, '2099-01-01T00:00:00Z')", rows)
    conn.commit()
    conn.close()


def test_ghost_metrics_split_by_reason(tmp_path: Path) -> None:
    _make_ledger(tmp_path)
    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.execution_metrics())

    assert "dreambuddy_ledger_ghost_stale_24h 12" in text
    assert "dreambuddy_ledger_ghost_exchange_flat_24h 1" in text
    assert "dreambuddy_ledger_exchange_sltp_24h 2" in text
    assert "dreambuddy_ledger_ghost_closed_24h 13" in text


def _write_sltp_summary(root: Path, *, failed: int, query_failed: int) -> None:
    audit = root / "22-执行引擎中心/audit"
    audit.mkdir(parents=True)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows = [
        {
            "ts": ts,
            "kind": "summary",
            "source": "22-sltp_reconcile",
            "patched": 0,
            "skipped": 11,
            "failed": failed,
            "deduped": 0,
            "query_failed": query_failed,
        }
    ]
    (audit / "sltp_reconcile.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def test_sltp_query_failures_do_not_feed_p1_patch_failures(tmp_path: Path) -> None:
    """50011 查询失败只进 query_failed（P3），不得计入 failed（P1 缺保护）。"""
    _write_sltp_summary(tmp_path, failed=0, query_failed=6)
    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.execution_metrics())

    assert "dreambuddy_sltp_reconcile_query_failed_1h 6" in text
    assert "dreambuddy_sltp_reconcile_failed_1h 0" in text
