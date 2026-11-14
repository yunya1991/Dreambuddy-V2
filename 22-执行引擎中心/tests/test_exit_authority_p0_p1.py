"""P0/P1 执行权收口测试（2026-11-14）

P0: cancel_algo_orders 必须经 22 Gateway（不允许 __getattr__ 透传 raw），
    执行权威不可用时 fail-closed 拒绝。
P1: OKX algo 历史/成交查询落在 22，state 归一（effective→pending），
    供 23 规则 0 与幽灵仓落账消费。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from executors import domain_clients as dc  # noqa: E402
from executors.okx_client import OKXSimulatedClient  # noqa: E402
from trade_execution_gateway import (  # noqa: E402
    FailClosedOkxClient,
    RiskGatedOkxClient,
    TradeExecutionGateway,
)


class _FakeRaw:
    def __init__(self) -> None:
        self.cancels = []

    def cancel_algo_orders(self, inst_id=None):
        self.cancels.append(inst_id)
        return {"ok": True, "cancelled": 1, "total": 1}


# ── P0: 撤单收口 ─────────────────────────────────────────────────────


def test_risk_gated_cancel_goes_through_gateway_and_audits(tmp_path):
    raw = _FakeRaw()
    audit = tmp_path / "audit.jsonl"
    gw = TradeExecutionGateway(okx_client=raw, audit_path=audit)
    client = RiskGatedOkxClient(raw, gw)

    out = client.cancel_algo_orders("ETH-USDT-SWAP")

    assert out["ok"] is True
    assert raw.cancels == ["ETH-USDT-SWAP"]
    rec = json.loads(audit.read_text(encoding="utf-8").strip())
    assert rec["action"] == "cancel_algo"
    assert rec["source"] == "11-yijing"
    assert rec["executed"] is True


def test_fail_closed_rejects_cancel_algo_orders():
    raw = _FakeRaw()
    client = FailClosedOkxClient(raw)

    out = client.cancel_algo_orders("ETH-USDT-SWAP")

    assert out["ok"] is False
    assert out.get("rejected") is True
    assert raw.cancels == []


def test_shadow_gateway_cancel_never_touches_exchange(tmp_path):
    """23 域 dry-run（shadow_only）不得真的撤掉交易所保护单。"""
    raw = _FakeRaw()
    audit = tmp_path / "audit.jsonl"
    gw = TradeExecutionGateway(okx_client=raw, audit_path=audit, shadow_only=True)

    out = gw.cancel_algo_orders("ETH-USDT-SWAP", source="23-evolution")

    assert out["ok"] is True
    assert out.get("shadow") is True
    assert raw.cancels == []
    rec = json.loads(audit.read_text(encoding="utf-8").strip())
    assert rec["action"] == "cancel_algo"
    assert rec["source"] == "23-evolution"


def test_domain_tagged_cancel_uses_gateway_with_evo_source(tmp_path):
    raw = dc.DomainTaggedOkxClient(_FakeRaw(), None)
    audit = tmp_path / "audit.jsonl"
    gw = TradeExecutionGateway(okx_client=_FakeRaw(), audit_path=audit)
    tagged = dc.DomainTaggedOkxClient(_FakeRaw(), None, gateway=gw)

    # 无 gateway 时保留 raw 直连（回滚路径），有 gateway 时必须经 gateway
    assert raw.cancel_algo_orders("BTC-USDT-SWAP")["ok"] is True
    out = tagged.cancel_algo_orders("BTC-USDT-SWAP")
    assert out["ok"] is True
    rec = json.loads(audit.read_text(encoding="utf-8").strip())
    assert rec["source"] == "23-evolution"


def test_domain_routed_cancel_picks_evo_client():
    nn_raw, evo_raw = _FakeRaw(), _FakeRaw()
    evo = dc.DomainTaggedOkxClient(evo_raw, None)
    router = dc.DomainRoutedOkxClient(
        nn_client=dc.DomainTaggedOkxClient(nn_raw, None),
        evo_client=evo,
        is_evolution_position=lambda inst: inst == "BARD-USDT-SWAP",
    )

    router.cancel_algo_orders("BARD-USDT-SWAP")
    router.cancel_algo_orders("BTC-USDT-SWAP")

    assert evo_raw.cancels == ["BARD-USDT-SWAP"]
    assert nn_raw.cancels == ["BTC-USDT-SWAP"]


# ── P1: algo 历史 / 成交查询 ─────────────────────────────────────────


class _StubOkx(OKXSimulatedClient):
    def __init__(self, algo_rows=None, fill_rows=None):
        super().__init__(
            {
                "api_key": "k",
                "secret_key": "s",
                "passphrase": "p",
                "base_url": "http://127.0.0.1",
                "simulated": True,
                "dry_run": False,
                "default_inst_id": "ETH-USDT-SWAP",
            }
        )
        self._algo_rows = algo_rows or []
        self._fill_rows = fill_rows or []

    def _has_credentials(self):
        return True

    def _get(self, path, params=None, auth=True):
        if path == "/api/v5/trade/orders-algo-history":
            return {"code": "0", "data": self._algo_rows}
        if path == "/api/v5/trade/fills":
            return {"code": "0", "data": self._fill_rows}
        return {"code": "0", "data": []}


def test_algo_history_maps_effective_to_pending():
    """effective 表示仍在挂单，绝不能被当成已触达（否则规则 0 会强平）。"""
    c = _StubOkx(
        algo_rows=[
            {"algoId": "a1", "state": "effective", "triggerPx": "90", "uTime": "100"},
            {"algoId": "a2", "state": "filled", "actualPx": "95", "uTime": "200"},
        ]
    )
    out = c.get_algo_order_history("ETH-USDT-SWAP")

    assert out["ok"] is True
    by_id = {o["algo_id"]: o for o in out["orders"]}
    assert by_id["a1"]["state"] == "pending"
    assert by_id["a1"]["raw_state"] == "effective"
    assert by_id["a2"]["state"] == "filled"
    assert by_id["a2"]["actual_px"] == 95.0


def test_recent_fills_sorted_desc_and_fields():
    c = _StubOkx(
        fill_rows=[
            {"tradeId": "f1", "fillPx": "94", "fillSz": "1", "ts": "100"},
            {"tradeId": "f2", "fillPx": "99", "fillSz": "2", "ts": "200"},
        ]
    )
    out = c.get_recent_fills("ETH-USDT-SWAP")

    assert out["ok"] is True
    assert [f["trade_id"] for f in out["fills"]] == ["f2", "f1"]
    assert out["fills"][0]["fill_px"] == 99.0
