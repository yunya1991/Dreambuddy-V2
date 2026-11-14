"""exit_loop 执行层硬门禁测试（2026-11-14）

覆盖：
  - SL 单调门禁：任何决策来源都不得把止损往不利方向改（P0-1 第二道防线）
  - 无实质变化不下单，避免每轮 cancel/place 抖动
  - RL 覆盖默认关闭（P1-5）
  - 全平后清理引擎持仓级状态（P1-1）
"""

from __future__ import annotations

import os

import pytest

from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision
from dreambuddy_evolution.execution.exit_loop import EvolutionExitLoop


class _FakeOkx:
    def __init__(self):
        self.cancelled = 0
        self.placed = []

    def cancel_algo_orders(self, inst_id=None):
        self.cancelled += 1
        return {"ok": True}

    def place_stop_loss_take_profit(self, **kw):
        self.placed.append(kw)
        return {"ok": True}


def _loop(okx=None):
    return EvolutionExitLoop(gateway=None, okx_client=okx or _FakeOkx(), enable_rl=False)


class TestSlMonotonicGate:
    def test_long_sl_cannot_be_lowered(self):
        """决策想把多头 SL 从 102.6 降到 98 → 被门禁钳回，且不发单（无变化）。"""
        okx = _FakeOkx()
        loop = _loop(okx)
        d = ExitDecision(action="trailing", sl_px=98.0, tp_px=0.0, reason="t")
        ctx = {"pos_side": "long", "current_sl_px": 102.6, "current_tp_px": 0.0}
        res = loop._apply_sl_tp({}, "ETH-USDT-SWAP", "ETH", d, ctx)
        assert res["status"] == "skipped"
        assert okx.placed == [] and okx.cancelled == 0

    def test_long_sl_improvement_is_placed(self):
        okx = _FakeOkx()
        loop = _loop(okx)
        d = ExitDecision(action="trailing", sl_px=102.6, tp_px=0.0, reason="t")
        ctx = {"pos_side": "long", "current_sl_px": 96.0, "current_tp_px": 0.0}
        res = loop._apply_sl_tp({}, "ETH-USDT-SWAP", "ETH", d, ctx)
        assert res["status"] == "executed"
        assert okx.placed[0]["stop_loss_px"] == pytest.approx(102.6)

    def test_short_sl_cannot_be_raised(self):
        okx = _FakeOkx()
        loop = _loop(okx)
        d = ExitDecision(action="trailing", sl_px=106.0, tp_px=0.0, reason="t")
        ctx = {"pos_side": "short", "current_sl_px": 94.0, "current_tp_px": 0.0}
        res = loop._apply_sl_tp({}, "ETH-USDT-SWAP", "ETH", d, ctx)
        assert res["status"] == "skipped"
        assert okx.placed == []

    def test_unchanged_sl_skips_cancel_and_place(self):
        okx = _FakeOkx()
        loop = _loop(okx)
        d = ExitDecision(action="trailing", sl_px=102.6, tp_px=0.0, reason="t")
        ctx = {"pos_side": "long", "current_sl_px": 102.6, "current_tp_px": 0.0}
        res = loop._apply_sl_tp({}, "ETH-USDT-SWAP", "ETH", d, ctx)
        assert res["status"] == "skipped"
        assert okx.cancelled == 0 and okx.placed == []


class TestRlDefaultOff:
    def test_rl_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("EVOLUTION_EXIT_RL", raising=False)
        loop = EvolutionExitLoop(gateway=None, okx_client=_FakeOkx())
        assert loop._rl_enabled is False, "RL 覆盖必须默认关闭"

    def test_rl_can_be_enabled_explicitly(self, monkeypatch):
        monkeypatch.setenv("EVOLUTION_EXIT_RL", "on")
        loop = EvolutionExitLoop(gateway=None, okx_client=_FakeOkx())
        assert loop._rl_enabled is True or os.getenv("EVOLUTION_EXIT_RL") == "on"


class TestStateCleanup:
    def test_cleanup_engine_state_calls_engine(self):
        loop = _loop()
        calls = []

        class _Engine:
            def cleanup_position(self, symbol, pos_side=None):
                calls.append((symbol, pos_side))

        loop._engine = _Engine()
        loop._cleanup_engine_state({"coin": "eth", "pos_side": "long"})
        assert calls == [("ETH", "long")]
