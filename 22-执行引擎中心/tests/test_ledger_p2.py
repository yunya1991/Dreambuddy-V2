"""P2 测试：域限额预占、日终对账、drop-copy 导入、监控指标（SPEC §7 P2）。

P2-1（enforce=on 灰度）依赖云端真实数据，不在单测覆盖；
此处验证代码路径与 shadow/enforce 开关语义（janitor 侧已由 test_ledger_janitor 覆盖）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (
    REPO / "22-执行引擎中心",
    REPO / "15-监控告警系统" / "scripts",
    REPO / "15-监控告警系统" / "exporter",
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from position_ledger import PositionLedger  # noqa: E402
from trade_execution_gateway import (  # noqa: E402
    FinalDecisionSignal,
    TradeExecutionGateway,
)

ETH = "ETH-USDT-SWAP"
BTC = "BTC-USDT-SWAP"


def _ledger(tmp_path, name: str = "p2.db") -> PositionLedger:
    return PositionLedger(tmp_path / name)


def _set_limits(led: PositionLedger, domain: str, limits: dict) -> None:
    with led._connect() as conn:
        conn.execute(
            "UPDATE domain_registry SET limits_json=? WHERE domain=?",
            (json.dumps(limits), domain),
        )


def _open_sig(inst: str, sz: float, px: float, source: str, did: str = "d1"):
    return FinalDecisionSignal.from_dict(
        {
            "symbol": inst,
            "pos_side": "long",
            "direction": "long",
            "action": "open",
            "sz": sz,
            "px": px,
            "source": source,
            "decision_id": did,
        }
    )


def test_p2_domain_quota_reject_then_consume(tmp_path):
    led = _ledger(tmp_path)
    _set_limits(led, "11", {"max_positions": 6, "max_notional": 2000})
    # 已有 11 域持仓 18×100=1800 名义
    led.record_fill(ETH, "long", "open", 18, 100.0, source="11-yijing")
    gw = TradeExecutionGateway(okx_client=object(), ledger=led, audit_path=tmp_path / "audit.jsonl")

    _rid, deny = gw._reserve_domain_quota(_open_sig(BTC, 1.0, 500.0, "11-yijing"), 1.0, 500.0)
    assert deny is not None and deny.reason_code == "DOMAIN_LIMIT_EXCEEDED"

    rid, deny2 = gw._reserve_domain_quota(_open_sig(BTC, 1.0, 100.0, "11-yijing"), 1.0, 100.0)
    assert deny2 is None and rid
    assert led.held_notional("11") == 100.0

    gw._settle_reservation(rid, consumed=True)
    assert led.held_notional("11") == 0.0
    assert led.list_reservations(domain="11", state="consumed")[0]["reservation_id"] == rid


def test_p2_close_and_unmanaged_domain_skip_reservation(tmp_path):
    led = _ledger(tmp_path)
    gw = TradeExecutionGateway(okx_client=object(), ledger=led, audit_path=tmp_path / "audit.jsonl")
    close_sig = FinalDecisionSignal.from_dict(
        {
            "symbol": ETH,
            "pos_side": "long",
            "direction": "long",
            "action": "close",
            "sz": 1.0,
            "px": 100.0,
            "source": "11-yijing",
            "decision_id": "c1",
        }
    )
    assert gw._reserve_domain_quota(close_sig, 1.0, 100.0) == (None, None)
    # 23 走 subpool 限额，不预占
    assert gw._reserve_domain_quota(_open_sig(ETH, 1.0, 100.0, "23-evolution"), 1.0, 100.0) == (
        None,
        None,
    )


def test_p2_eod_report_balanced_and_mismatch(tmp_path):
    from ledger_eod_recon import build_report

    led = _ledger(tmp_path, "eod.db")
    led.record_fill(ETH, "long", "open", 2.0, 100.0, source="23-evolution")

    ok = build_report(led, [{"inst_id": ETH, "pos_side": "long", "qty": 2.0, "avg_entry": 100.0}])
    assert ok["balanced"] is True
    assert ok["totals"]["positions_qty"] == 2.0
    assert ok["totals"]["domain_qty"] == 2.0
    assert ok["rows"][0]["balanced"] is True

    drift = build_report(
        led, [{"inst_id": ETH, "pos_side": "long", "qty": 3.0, "avg_entry": 100.0}]
    )
    assert drift["balanced"] is False
    assert drift["rows"][0]["exchange_vs_l1"] == 1.0


def test_p2_eod_markdown_renders(tmp_path):
    from ledger_eod_recon import build_report, render_markdown

    led = _ledger(tmp_path, "eod_md.db")
    led.record_fill(ETH, "long", "open", 1.0, 100.0, source="23-evolution")
    md = render_markdown(build_report(led, []))
    assert "账本日终对账" in md and "控制总数" in md


def test_p2_drop_copy_jsonl_import_and_replay(tmp_path):
    from executors.drop_copy_adapter import DropCopyAdapter

    led = _ledger(tmp_path, "dc.db")
    path = tmp_path / "x1_live_fills.jsonl"
    rec = {
        "ts": "2026-11-23T00:00:00Z",
        "decision_id": "d50",
        "source": "50-nn",
        "symbol": BTC,
        "direction": "long",
        "order_placed": True,
        "order_id": "ord-1",
        "fill_px": 60000.0,
        "request": {"sz": 1.5},
        "result": {"ok": True, "fill_sz": 1.5, "fee": 0.1},
    }
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    adapter = DropCopyAdapter(led)

    first = adapter.import_jsonl(path, domain="50")
    second = adapter.import_jsonl(path, domain="50")

    assert first["imported"] == 1 and second["duplicate"] == 1
    assert led.get_position(BTC, "long")["qty"] == 1.5
    assert led.list_domain_positions(domain="50")[0]["qty"] == 1.5


def test_p2_metrics_include_risk_fields(tmp_path):
    pytest.importorskip("yaml")
    import business_metrics_exporter as bme

    led = _ledger(tmp_path, "metrics.db")
    led.record_fill(ETH, "long", "open", 2.0, 100.0, source="23-evolution")
    led.set_status(ETH, "long", "stale")
    led.upsert_break("stale_position", ETH, "long", "23", {"miss": 3})
    led.heartbeat()

    collector = object.__new__(bme.Collector)
    collector.repo = REPO
    out = collector._ledger_metrics({"ledger_db": str(led.path)})
    text = "\n".join(out)

    assert "ledger_stale_positions 1" in text
    assert "ledger_breaks_open 1" in text
    assert "ledger_domain_qty_mismatch 0" in text
    assert "ledger_feed_state 0" in text
