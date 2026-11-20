"""23 域 → 22 网关决策契约：执行层决策必须满足 v1.2。

背景：执行适配层复用 `shadow_decision()` 构造 stop_loss/take_profit/open 决策，
此前缺少 v1.2 顶层 ts/horizon/risk_exposure_hint/mode 与 payload 12 字段，
导致 22 网关每个止损巡检周期都记录 `GatewayContractViolation`(P1)；
同时限价 px 被写在根节点，与 `additionalProperties=false` 冲突。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_GW_DIR = Path(__file__).resolve().parents[1]
if str(_GW_DIR) not in sys.path:
    sys.path.insert(0, str(_GW_DIR))

from executors.domain_clients import DomainTaggedOkxClient, shadow_decision  # noqa: E402

_SCHEMA_PATH = _GW_DIR.parent / "49-交易框架协议" / "contracts" / "final_decision_signal.v1.2.json"
_REQUIRED_PAYLOAD = (
    "action",
    "position_tier",
    "position_mult",
    "d_star",
    "ri",
    "l4_v",
    "regime",
    "primary_contradiction",
    "contradiction_shift",
    "elastic_result",
    "cross_validation",
    "path",
)


class _FakeResult:
    executed = True
    passed = True
    order_result = {"ok": True}
    sltp_result = None


class _FakeGateway:
    def __init__(self) -> None:
        self.decisions: list[dict] = []

    def submit(self, decision: dict) -> _FakeResult:
        self.decisions.append(decision)
        return _FakeResult()


def _client() -> tuple[_FakeGateway, DomainTaggedOkxClient]:
    gw = _FakeGateway()
    return gw, DomainTaggedOkxClient(raw=object(), gateway=gw)


def test_stop_loss_decision_omits_null_px() -> None:
    gw, client = _client()

    client._submit_via_gateway("stop_loss", "XAG-USDT-SWAP", "long", "sl", 1.0)
    client._submit_via_gateway("take_profit", "XAG-USDT-SWAP", "long", "tp", 1.0)

    assert gw.decisions, "决策应提交到网关"
    assert all("px" not in d for d in gw.decisions), "px=None 不应写入决策根节点"


def test_open_decision_keeps_limit_px_in_payload() -> None:
    gw, client = _client()

    client._submit_via_gateway("open", "BTC-USDT-SWAP", "long", "entry", 1.0, px=100.0)

    assert "px" not in gw.decisions[0], "契约根节点禁止 px"
    assert gw.decisions[0]["payload"]["px"] == 100.0


def test_execution_decisions_satisfy_v12_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    gw, client = _client()

    client._submit_via_gateway("stop_loss", "XAG-USDT-SWAP", "long", "sl", 1.0, sl_px=30.0)
    client._submit_via_gateway("take_profit", "BTC-USDT-SWAP", "short", "tp", 1.0, tp_px=90000.0)
    client._submit_via_gateway("open", "ETH-USDT-SWAP", "long", "entry", 1.0, px=3000.0)

    assert len(gw.decisions) == 3
    for decision in gw.decisions:
        jsonschema.validate(instance=decision, schema=schema)
        assert "px" not in decision
        for field in _REQUIRED_PAYLOAD:
            assert field in decision["payload"], f"payload 缺少 {field}"


def test_missing_inst_id_fails_closed_without_submit() -> None:
    gw, client = _client()

    out = client._submit_via_gateway("open", None, "long", "entry", 1.0)

    assert out == {"ok": False, "error": "inst_id_required"}
    assert gw.decisions == [], "无标的时不得提交 MULTI 占位决策"


def test_shadow_check_skips_missing_inst_id() -> None:
    class _ShadowGateway:
        def __init__(self) -> None:
            self.decisions: list[dict] = []

        def submit(self, decision: dict) -> None:
            self.decisions.append(decision)

    shadow = _ShadowGateway()
    client = DomainTaggedOkxClient(raw=object(), shadow_gateway=shadow)

    client._shadow_check("cancel_algo", None, "", "cancel all")

    assert shadow.decisions == []


def test_shadow_decision_rejects_empty_inst_id() -> None:
    with pytest.raises(ValueError, match="inst_id"):
        shadow_decision("open", "", "long", "entry")


def test_cancel_all_still_routes_to_gateway_without_inst_id() -> None:
    class _Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def cancel_algo_orders(self, inst_id=None, source=None) -> dict:
            self.calls.append((inst_id, source))
            return {"ok": True}

    gw = _Gateway()
    client = DomainTaggedOkxClient(raw=object(), gateway=gw)

    assert client.cancel_algo_orders(None) == {"ok": True}
    assert gw.calls == [(None, "23-evolution")]
