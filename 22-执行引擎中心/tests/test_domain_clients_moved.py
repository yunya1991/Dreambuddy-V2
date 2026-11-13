"""T-G3a：域路由执行器迁入 22 后的独立性与等价性验收。

验收三件事：
1. 22 可独立 import `executors.domain_clients`（不依赖 11 的任何模块）；
2. 行为与 11 原实现等价（路由 / evo23 标签 / [23域] reason / 13 只读影子）；
3. 11 侧保留同名符号，且指向 22 的同一类对象（别名等价，不是副本）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent  # 22-执行引擎中心/tests
MODULE_ROOT = HERE.parent  # 22-执行引擎中心
REPO = MODULE_ROOT.parent

from executors import domain_clients as dc  # noqa: E402


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


# ── 1. 独立性 ────────────────────────────────────────────────────────


def test_import_without_11_in_fresh_process():
    """全新进程仅凭 22 目录即可 import，且不加载 11 的任何模块。"""
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path.cwd()))\n"
        "from executors import domain_clients as dc\n"
        "assert dc.tag_reason('x') == '[23域]x'\n"
        "bad = [m for m in sys.modules if m.startswith(('scripts', 'okx_'))]\n"
        "assert not bad, bad\n"
        "print('INDEPENDENT_OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(MODULE_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "INDEPENDENT_OK" in proc.stdout


def test_executors_package_has_no_11_reference():
    """22/executors 源码不得出现 11 域路径或 11 私有模块。"""
    forbidden = ("11-易经推理", "scripts.memory_l4", "okx_simulated")
    for py in sorted((MODULE_ROOT / "executors").glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{py.name} 引用了 {token}"


# ── 2. 行为等价 ──────────────────────────────────────────────────────


def test_domain_23_routes_to_evo_and_tags():
    nn, raw_evo = _FakeClient("nn"), _FakeClient("evo")
    evo = dc.DomainTaggedOkxClient(raw_evo, None)
    router = dc.DomainRoutedOkxClient(
        nn_client=nn, evo_client=evo, is_evolution_position=lambda _i: False
    )
    out = router.market_open_long("BARD-USDT-SWAP", 300, reason="evolution_auto_long", domain="23")
    assert out["client"] == "evo"
    assert nn.calls == []
    kind, _inst, _amt, reason, tag = raw_evo.calls[0]
    assert kind == "open_long"
    assert tag == dc.EVOLUTION_OKX_TAG == "evo23"
    assert reason.startswith("[23域]")


def test_neural_order_routed_to_nn_without_domain_prefix():
    nn, evo = _FakeClient("nn"), _FakeClient("evo")
    router = dc.DomainRoutedOkxClient(
        nn_client=nn, evo_client=evo, is_evolution_position=lambda _i: False
    )
    out = router.market_open_long("BTC-USDT-SWAP", 100, reason="bcrm_open")
    assert out["client"] == "nn"
    assert evo.calls == []
    assert nn.calls[0][3] == "bcrm_open"


def test_evolution_position_routes_without_explicit_domain():
    nn, evo = _FakeClient("nn"), _FakeClient("evo")
    router = dc.DomainRoutedOkxClient(
        nn_client=nn,
        evo_client=evo,
        is_evolution_position=lambda inst: inst == "BARD-USDT-SWAP",
    )
    out = router.market_close_long("BARD-USDT-SWAP", reason="evolution_exit")
    assert out["client"] == "evo"
    assert nn.calls == []


def test_evo_client_runs_shadow_check_but_always_orders():
    raw = _FakeClient("raw")
    shadow = _FakeShadowGw()
    evo = dc.DomainTaggedOkxClient(raw, shadow)
    out = evo.market_open_long("BARD-USDT-SWAP", 300, reason="evolution_auto_long")
    assert out["ok"] is True
    assert raw.calls and raw.calls[0][4] == "evo23"
    assert shadow.decisions, "13 只读影子校验必须被调用"
    assert shadow.decisions[0]["source"] == "23-evolution"
    assert shadow.decisions[0]["reason"].startswith("[23域]")


def test_tag_reason_is_idempotent():
    once = dc.tag_reason("evolution_auto_long")
    assert once == "[23域]evolution_auto_long"
    assert dc.tag_reason(once) == once


def test_shadow_gateway_failure_does_not_block_order():
    """影子校验抛异常时必须吞掉，真实下单照常。"""

    class _BoomGw:
        def submit(self, _decision):
            raise RuntimeError("shadow down")

    raw = _FakeClient("raw")
    evo = dc.DomainTaggedOkxClient(raw, _BoomGw())
    out = evo.market_open_long("BARD-USDT-SWAP", 300, reason="evolution_auto_long")
    assert out["ok"] is True and raw.calls


# ── 3. 11 侧别名等价 ─────────────────────────────────────────────────


def test_11_exports_are_same_objects_as_22():
    """11 保留同名符号，且必须是 22 的同一对象（is 而非 ==）。"""
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "repo = Path.cwd()\n"
        "sys.path.insert(0, str(repo / '22-执行引擎中心'))\n"
        "from executors import domain_clients as dc\n"
        "sys.path.insert(0, str(repo / '11-易经推理系统'))\n"
        "from scripts.memory_l4 import polling_trader as pt\n"
        "assert pt._DomainTaggedOkxClient is dc.DomainTaggedOkxClient\n"
        "assert pt._DomainRoutedOkxClient is dc.DomainRoutedOkxClient\n"
        "assert pt._tag_reason is dc.tag_reason\n"
        "assert pt._shadow_decision is dc.shadow_decision\n"
        "assert pt.EVOLUTION_DOMAIN_TAG == dc.EVOLUTION_DOMAIN_TAG\n"
        "assert pt.EVOLUTION_OKX_TAG == dc.EVOLUTION_OKX_TAG\n"
        "assert pt.NN_OKX_TAG == dc.NN_OKX_TAG\n"
        "print('ALIAS_OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ALIAS_OK" in proc.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
