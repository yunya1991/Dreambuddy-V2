"""22 x1_live_executor 风控与幂等测试（不触发真实下单）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_22_DIR = Path(__file__).resolve().parents[1]
if str(_22_DIR) not in sys.path:
    sys.path.insert(0, str(_22_DIR))

import x1_live_executor as ex  # noqa: E402


def _live_decision(**overrides):
    base = {
        "decision_id": "50-nn|BTC-USDT-SWAP|1",
        "signal_id": "50-nn|BTC-USDT-SWAP|1",
        "source": "50-nn",
        "mode": "live",
        "shadow": False,
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "mandate_id": "mandate-20261113-50-live-btc",
        "execution": {"outcome": "live:50-bypass", "allowed": True},
    }
    base.update(overrides)
    return base


def test_check_rejects_shadow_decision():
    assert ex._check(_live_decision(mode="shadow", shadow=True)) == "not_live_decision"


def test_check_rejects_denied_rights():
    decision = _live_decision(execution={"outcome": "paper", "allowed": True})
    assert ex._check(decision) == "execution_rights_denied"


def test_check_rejects_over_limit_notional():
    assert ex._check(_live_decision(notional_usdt=200)) == "notional_limit"


def test_dry_run_records_without_bridge(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=True, limit=10)
    assert result["executed"] == 1
    row = json.loads((tmp_path / "fills.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["result"]["dry_run"] is True

    again = ex.run(outbox, dry_run=True, limit=10)
    assert again["executed"] == 1  # dry-run 不写 processed，真实执行仍会触发
    assert again["skipped"] == 0
