# -*- coding: utf-8 -*-
"""L1X-02：22 网关对 `source=l1-chart` 的硬前置（SPEC-54 §4.6 / SPEC M1 同口径）。"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from trade_execution_gateway import TradeExecutionGateway  # noqa: E402


class _NoopOkx:
    """前置拒绝发生在任何下单调用之前；这里只需一个不会被真正调用的占位客户端。"""

    def __init__(self) -> None:
        self.calls = []

    def __getattr__(self, name):
        def _stub(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return {"ok": False, "error": "unexpected"}

        return _stub


def _l1(**overrides):
    base = {
        "signal_id": "l1-chart|dec-l1-BTC-2026-11-14-1-dr-1.0.0-bbbbbbbb",
        "source": "l1-chart",
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "confidence": 0.94,
        "expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15))
        .isoformat()
        .replace("+00:00", "Z"),
        "payload": {
            "decision_id": "dec-l1-BTC-2026-11-14-1-dr-1.0.0-bbbbbbbb",
            "action": "long",
            "position_tier": "trend",
            "position_mult": 0.94,
        },
    }
    base.update(overrides)
    return base


def _gateway(audit_path):
    return TradeExecutionGateway(okx_client=_NoopOkx(), audit_path=audit_path)


def test_l1_chart_missing_decision_id_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        gw = _gateway(Path(tmp) / "audit.jsonl")
        payload = _l1()
        payload["payload"] = {"action": "long"}
        result = gw.submit(payload)
        assert result.passed is False
        assert result.executed is False
        assert result.reason_code == "MISSING_DECISION_ID"
        assert "l1-chart" in result.reason


def test_l1_chart_expired_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        gw = _gateway(Path(tmp) / "audit.jsonl")
        expired = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        result = gw.submit(_l1(expires_at=expired.isoformat().replace("+00:00", "Z")))
        assert result.passed is False
        assert result.reason_code == "SIGNAL_EXPIRED"


def test_l1_chart_precheck_passes_then_hits_risk_gate():
    with tempfile.TemporaryDirectory() as tmp:
        gw = _gateway(Path(tmp) / "audit.jsonl")
        with patch("trade_execution_gateway._load_13_modules", return_value=None):
            result = gw.submit(_l1())
        assert result.reason_code != "MISSING_DECISION_ID"
        assert result.reason_code != "SIGNAL_EXPIRED"
        assert "OPEN_REJECTED" in result.reason_code


def test_evolution_source_still_gated():
    with tempfile.TemporaryDirectory() as tmp:
        gw = _gateway(Path(tmp) / "audit.jsonl")
        result = gw.submit(
            {"source": "23-evolution", "symbol": "BTC-USDT-SWAP", "direction": "long"}
        )
        assert result.reason_code == "MISSING_DECISION_ID"


def test_other_sources_not_gated():
    with tempfile.TemporaryDirectory() as tmp:
        gw = _gateway(Path(tmp) / "audit.jsonl")
        with patch("trade_execution_gateway._load_13_modules", return_value=None):
            result = gw.submit(
                {"source": "11-yijing", "symbol": "BTC-USDT-SWAP", "direction": "long"}
            )
        assert result.reason_code != "MISSING_DECISION_ID"


def test_audit_written_for_l1_rejection():
    with tempfile.TemporaryDirectory() as tmp:
        audit = Path(tmp) / "audit.jsonl"
        gw = _gateway(audit)
        payload = _l1()
        payload["payload"] = {"action": "long"}
        gw.submit(payload)
        records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
        assert records and records[0]["signal_id"] == payload["signal_id"]
        assert records[0]["reason_code"] == "MISSING_DECISION_ID"
