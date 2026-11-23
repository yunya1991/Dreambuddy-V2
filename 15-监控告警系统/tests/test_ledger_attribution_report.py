"""15 持仓标签日巡检报告测试。"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for p in (_HERE.parent / "scripts", _REPO / "22-执行引擎中心"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from ledger_attribution_report import build_report, render_markdown  # noqa: E402
from position_ledger import PositionLedger  # noqa: E402


def _ledger(tmp_path) -> PositionLedger:
    return PositionLedger(tmp_path / "ledger.db")


def test_labeled_positions_report_ok(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("AVAX-USDT-SWAP", "long", "open", 2.0, 30.0, domain="23", source="23-evolution")
    led.record_fill("BNB-USDT-SWAP", "short", "open", 5.0, 600.0, domain="50", source="50-nn")

    rep = build_report(led)
    assert rep["ok"] is True and rep["alerts"] == []
    assert set(rep["domains"]) == {"22", "23", "50"}  # 三个受监控域始终展示
    assert rep["domains"]["23"]["positions"] == 1
    assert rep["domains"]["22"]["positions"] == 0
    assert rep["fills_by_domain"] == {"22": 0, "23": 1, "50": 1}
    assert rep["unlabeled_fills"] == 0


def test_unlabeled_position_triggers_alert(tmp_path):
    led = _ledger(tmp_path)
    # 直接落一行无域归属的 L1 持仓 + 无标签成交（模拟网关外开仓/历史回填）
    with led._lock, led._connect() as conn:
        conn.execute(
            "INSERT INTO positions (inst_id, pos_side, qty, avg_entry, entry_known,"
            " realized_pnl, source, opened_at, updated_at, closed_at, status)"
            " VALUES ('ETH-USDT-SWAP','long',1.5,3000,1,0,'legacy-open',"
            " datetime('now'), datetime('now'), NULL, 'open')"
        )
        conn.execute(
            "INSERT INTO fills (ts, inst_id, pos_side, action, qty, px, fee, source)"
            " VALUES (datetime('now'),'ETH-USDT-SWAP','long','open',1.5,3000,0,'legacy-open')"
        )

    rep = build_report(led)
    assert rep["ok"] is False
    assert rep["unlabeled_positions"] == ["ETH-USDT-SWAP:long"]
    assert any("未打域标签" in a for a in rep["alerts"])
    assert rep["unlabeled_fills"] >= 1


def test_l1_l2_drift_detected(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("BNB-USDT-SWAP", "short", "open", 5.0, 600.0, domain="50", source="50-nn")
    # 模拟账本漂移：L1 数量被对账改成 7，L2 仍 5
    with led._lock, led._connect() as conn:
        conn.execute("UPDATE positions SET qty=7 WHERE inst_id='BNB-USDT-SWAP'")

    rep = build_report(led)
    assert rep["ok"] is False
    assert rep["drift"][0]["key"] == "BNB-USDT-SWAP:short"
    assert any("漂移" in a for a in rep["alerts"])


def test_markdown_contains_sections(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("AVAX-USDT-SWAP", "long", "open", 2.0, 30.0, domain="23", source="23-evolution")
    md = render_markdown(build_report(led))
    assert "各域活跃持仓" in md and "近周期成交标签" in md and "## 告警" in md
    assert "| 23 | 1 |" in md
