"""23 域 → 22 网关决策契约：px=None 时不得写入根节点。

背景：v1.2 schema 根节点无 `px`，止损/止盈单每个巡检周期都会产生一条
`Additional properties are not allowed ('px' was unexpected)` 契约违规。
"""

from __future__ import annotations

import sys
from pathlib import Path

_GW_DIR = Path(__file__).resolve().parents[1]
if str(_GW_DIR) not in sys.path:
    sys.path.insert(0, str(_GW_DIR))

from executors.domain_clients import DomainTaggedOkxClient  # noqa: E402


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


def test_stop_loss_decision_omits_null_px() -> None:
    gw = _FakeGateway()
    client = DomainTaggedOkxClient(raw=object(), gateway=gw)

    client._submit_via_gateway("stop_loss", "XAG-USDT-SWAP", "long", "sl", 1.0)
    client._submit_via_gateway("take_profit", "XAG-USDT-SWAP", "long", "tp", 1.0)

    assert gw.decisions, "决策应提交到网关"
    assert all("px" not in d for d in gw.decisions), "px=None 不应写入决策根节点"


def test_open_decision_keeps_limit_px() -> None:
    gw = _FakeGateway()
    client = DomainTaggedOkxClient(raw=object(), gateway=gw)

    client._submit_via_gateway("open", "BTC-USDT-SWAP", "long", "entry", 1.0, px=100.0)

    assert gw.decisions[0]["px"] == 100.0
