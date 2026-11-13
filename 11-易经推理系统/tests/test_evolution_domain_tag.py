"""23 自进化域下单路由测试。

约束：13→16→22→11 链路只属于神经网络系统；23 域经 11 下单需走 raw client
并带 evo23 标签 + [23域] reason，与神经网络订单可区分对照。
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.memory_l4 import polling_trader as pt  # noqa: E402


class _FakeClient:
    def __init__(self, name: str):
        self.name = name
        self.calls = []

    def market_open_long(self, inst_id=None, usdt_amount=None, reason="", tag=""):
        self.calls.append(("open_long", inst_id, usdt_amount, reason, tag))
        return {"ok": True, "client": self.name}

    def market_close_long(self, inst_id=None, reason="", tag=""):
        self.calls.append(("close_long", inst_id, reason, tag))
        return {"ok": True, "client": self.name}

    def place_order(self, **kwargs):
        self.calls.append(("place_order", kwargs))
        return {"ok": True, "client": self.name}


class _FakeShadowGw:
    def __init__(self):
        self.decisions = []

    def submit(self, decision):
        self.decisions.append(decision)
        return type("R", (), {"passed": False, "executed": False})()


class _Pos:
    def __init__(self, source_tag: str):
        self.source_tag = source_tag


class _Tracker:
    def __init__(self, mapping):
        self.open_positions = mapping


def _make_router(nn, evo, tracker):
    return pt._DomainRoutedOkxClient(
        nn_client=nn,
        evo_client=evo,
        is_evolution_position=lambda inst: str(
            getattr(tracker.open_positions.get(inst), "source_tag", "") or ""
        ).lower()
        == "evolution",
    )


def test_domain_23_routes_to_evo_and_tags():
    nn, raw_evo = _FakeClient("nn"), _FakeClient("evo")
    evo = pt._DomainTaggedOkxClient(raw_evo, None)
    router = _make_router(nn, evo, _Tracker({}))
    out = router.market_open_long("BARD-USDT-SWAP", 300, reason="evolution_auto_long", domain="23")
    assert out["client"] == "evo"
    assert nn.calls == []
    kind, inst, _amt, reason, tag = raw_evo.calls[0]
    assert kind == "open_long"
    assert tag == pt.EVOLUTION_OKX_TAG == "evo23"
    assert reason.startswith("[23域]")


def test_neural_order_still_routed_to_gateway_client():
    nn, evo = _FakeClient("nn"), _FakeClient("evo")
    router = _make_router(nn, evo, _Tracker({}))
    out = router.market_open_long("BTC-USDT-SWAP", 100, reason="bcrm_open")
    assert out["client"] == "nn"
    assert evo.calls == []
    assert nn.calls[0][3] == "bcrm_open"  # 神经网络域不加 23 域前缀


def test_evolution_position_routes_without_explicit_domain():
    nn, evo = _FakeClient("nn"), _FakeClient("evo")
    tracker = _Tracker({"BARD-USDT-SWAP": _Pos("evolution")})
    router = _make_router(nn, evo, tracker)
    out = router.market_close_long("BARD-USDT-SWAP", reason="evolution_exit")
    assert out["client"] == "evo"
    assert nn.calls == []


def test_evo_client_runs_shadow_check_but_always_orders():
    raw = _FakeClient("raw")
    shadow = _FakeShadowGw()
    evo = pt._DomainTaggedOkxClient(raw, shadow)
    out = evo.market_open_long("BARD-USDT-SWAP", 300, reason="evolution_auto_long")
    assert out["ok"] is True
    assert raw.calls and raw.calls[0][4] == "evo23"
    assert shadow.decisions, "13 只读影子校验必须被调用"
    assert shadow.decisions[0]["source"] == "23-evolution"
    assert shadow.decisions[0]["reason"].startswith("[23域]")


def test_tag_reason_is_idempotent():
    once = pt._tag_reason("evolution_auto_long")
    assert once == "[23域]evolution_auto_long"
    assert pt._tag_reason(once) == once
