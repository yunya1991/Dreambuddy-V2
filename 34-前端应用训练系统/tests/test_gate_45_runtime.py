# -*- coding: utf-8 -*-
"""GAP-14: settle 的 45 门禁生产注入点契约（默认关、FAIL-OPEN、payload 不伪造）。

依据: 56-L2 TECHNICAL_DESIGN GAP-14 / ADR-04（Mandate+预算+trace 三件套）
+ gate_45_adapter DD4（shadow → hard）+ H2（默认关时字节等价）。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from core import gate_45_runtime as rt  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_builder():
    rt.reset_payload_builder()
    yield
    rt.reset_payload_builder()


def test_default_off_returns_none():
    """未设置 DREAM_GATE_45_MODE → 无门禁（与接线前字节等价）。"""
    assert rt.resolve_settle_gate(environ={}) is None


def test_invalid_mode_returns_none():
    assert rt.resolve_settle_gate(environ={rt.MODE_ENV: "strict"}) is None


def test_enabled_without_payload_builder_returns_none():
    """开启但未注册业务 payload → 不伪造请求，退回无门禁。"""
    assert rt.resolve_settle_gate(environ={rt.MODE_ENV: "shadow"}) is None


def _patch_transport(monkeypatch, verdict="BLOCK"):
    monkeypatch.setattr(rt, "_http_submit", lambda base, timeout: (lambda ctx: "EV-T-1"))
    monkeypatch.setattr(
        rt,
        "_http_poll",
        lambda base, timeout: (lambda eid: {"verdict": verdict, "evidence_uri": "s3://ev/1"}),
    )


def test_shadow_allows_but_records_verdict(monkeypatch):
    _patch_transport(monkeypatch, verdict="BLOCK")
    rt.register_payload_builder(lambda ctx: {"category": "settle", "trace_id": ctx.get("trace_id")})
    gate = rt.resolve_settle_gate(environ={rt.MODE_ENV: "shadow"})
    assert gate is not None
    allowed, info = gate({"message": "m", "trace_id": "tr-1"})
    assert allowed is True
    assert info.get("verdict") == "BLOCK"


def test_hard_mode_obeys_hard_switch(monkeypatch):
    _patch_transport(monkeypatch, verdict="BLOCK")
    rt.register_payload_builder(lambda ctx: {"category": "settle"})
    env = {rt.MODE_ENV: "hard"}

    gate_off = rt.resolve_settle_gate(flags={}, environ=env)
    assert gate_off is not None
    assert gate_off({"message": "m"})[0] is True

    gate_on = rt.resolve_settle_gate(flags={"enable_gate_45_hard": True}, environ=env)
    assert gate_on is not None
    assert gate_on({"message": "m"})[0] is False
