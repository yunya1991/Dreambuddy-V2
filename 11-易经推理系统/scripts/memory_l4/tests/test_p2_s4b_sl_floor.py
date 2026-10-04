# -*- coding: utf-8 -*-
"""P2-S4b SL/TP 门禁 TDD 测试.

Spec: .trae/documents/pons_river_evolution_fix_spec.md 缺陷C (P0)

修复目标:
  1. P2-S4b 路径 SL 下限从 4% 上调到 8%（对齐 MIN_SL_PCT_TRIAL=0.080）
  2. 接入 _enforce_sl_price_floor 双约束钳制（与其他开仓路径 L4359/L4780/L9957 对齐）
  3. probe tier 同标准（SL≥8%），不再有 "probe 仓 SL≥4%" 的特殊下限
  4. event_arbitrage 路径 SL 从 2% 上调到 5%（对齐 ABS_HARD_SL_PCT=0.050）

TDD 红: _p2_s4b_compute_sltp 方法不存在 → AttributeError → RED
TDD 绿: 实现方法，SL≥8%，_enforce_sl_price_floor 被调用 → GREEN
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


class TestP2S4bSLFloorEnforced:
    """P2-S4b SL 门禁测试（缺陷C P0）."""

    @pytest.fixture
    def trader(self):
        """轻量 PollingTrader 实例（参考 test_verify_algo_sltp.py 模式）."""
        from polling_trader import PollingTrader
        t = PollingTrader.__new__(PollingTrader)
        t.okx_client = MagicMock()
        t._log = MagicMock()
        t._get_leverage = MagicMock(return_value=5)
        return t

    def test_probe_tier_sl_floor_8pct(self, trader):
        """probe tier SL 下限 ≥ 8%（不是 4%）.

        场景: ATR=0.5%, probe mult=4.0 → 2% < 8% 兜底 → SL 应为 8%
        """
        _last_kd = {"atr_pct": 0.005, "regime": "trend_up"}
        sl_px, tp_px, sl_pct, tp_pct = trader._p2_s4b_compute_sltp(
            tier="probe", action="long", entry_px=100.0,
            source_tag="evolution", _last_kd=_last_kd
        )
        # SL 下限 8%（不是 4%）
        assert sl_pct >= 0.08, f"probe SL 下限应 ≥8%, 实际 {sl_pct}"

    def test_standard_tier_sl_floor_8pct(self, trader):
        """standard tier SL 下限 ≥ 8%."""
        _last_kd = {"atr_pct": 0.005, "regime": "trend_up"}
        sl_px, tp_px, sl_pct, tp_pct = trader._p2_s4b_compute_sltp(
            tier="standard", action="long", entry_px=100.0,
            source_tag="evolution", _last_kd=_last_kd
        )
        assert sl_pct >= 0.08, f"standard SL 下限应 ≥8%, 实际 {sl_pct}"

    def test_trend_tier_sl_floor_8pct(self, trader):
        """trend tier SL 下限 ≥ 8%."""
        _last_kd = {"atr_pct": 0.005, "regime": "trend_up"}
        sl_px, tp_px, sl_pct, tp_pct = trader._p2_s4b_compute_sltp(
            tier="trend", action="long", entry_px=100.0,
            source_tag="evolution", _last_kd=_last_kd
        )
        assert sl_pct >= 0.08, f"trend SL 下限应 ≥8%, 实际 {sl_pct}"

    def test_low_atr_still_meets_8pct_floor(self, trader):
        """ATR 很低时 SL 仍 ≥ 8%（兜底 0.08 而非 0.04）.

        场景: ATR=0.1%, probe mult=4.0 → 0.4% << 8% 兜底
        """
        _last_kd = {"atr_pct": 0.001, "regime": "trend_up"}
        sl_px, tp_px, sl_pct, tp_pct = trader._p2_s4b_compute_sltp(
            tier="probe", action="long", entry_px=100.0,
            source_tag="evolution", _last_kd=_last_kd
        )
        assert sl_pct >= 0.08, f"低 ATR 时 SL 应兜底到 8%, 实际 {sl_pct}"

    def test_enforce_sl_price_floor_called(self, trader):
        """_enforce_sl_price_floor 必须被调用（与 L4359/L4780/L9957 对齐）."""
        trader._enforce_sl_price_floor = MagicMock(
            return_value=(92.0, True, 0.04, {"liq_conflict": False, "spacing_clamped": True, "warn_leverage": False})
        )
        trader._enforce_tp_price_floor = MagicMock(
            return_value=(106.0, False, 0.06, {"liq_conflict": False, "spacing_clamped": False, "warn_leverage": False})
        )
        _last_kd = {"atr_pct": 0.02, "regime": "trend_up"}
        trader._p2_s4b_compute_sltp(
            tier="probe", action="long", entry_px=100.0,
            source_tag="evolution", _last_kd=_last_kd
        )
        assert trader._enforce_sl_price_floor.called, "_enforce_sl_price_floor 必须被调用"

    def test_enforce_tp_price_floor_called(self, trader):
        """_enforce_tp_price_floor 必须被调用."""
        trader._enforce_sl_price_floor = MagicMock(
            return_value=(92.0, True, 0.04, {"liq_conflict": False, "spacing_clamped": True, "warn_leverage": False})
        )
        trader._enforce_tp_price_floor = MagicMock(
            return_value=(106.0, False, 0.06, {"liq_conflict": False, "spacing_clamped": False, "warn_leverage": False})
        )
        _last_kd = {"atr_pct": 0.02, "regime": "trend_up"}
        trader._p2_s4b_compute_sltp(
            tier="probe", action="long", entry_px=100.0,
            source_tag="evolution", _last_kd=_last_kd
        )
        assert trader._enforce_tp_price_floor.called, "_enforce_tp_price_floor 必须被调用"

    def test_event_arbitrage_sl_floor_5pct(self, trader):
        """event_arbitrage 路径 SL ≥ 5%（对齐 ABS_HARD_SL_PCT=0.050）.

        Spec L86: event_arbitrage SL=0.02 违反 ABS_HARD_SL_PCT=0.05，上调到 0.05
        """
        _last_kd = {"atr_pct": 0.005, "regime": "trend_up"}
        sl_px, tp_px, sl_pct, tp_pct = trader._p2_s4b_compute_sltp(
            tier="probe", action="long", entry_px=100.0,
            source_tag="event_arbitrage", _last_kd=_last_kd
        )
        assert sl_pct >= 0.05, f"event_arbitrage SL 应 ≥5%（ABS_HARD_SL_PCT）, 实际 {sl_pct}"

    def test_short_side_sl_clamped(self, trader):
        """SHORT 方向 SL 门禁也生效."""
        _last_kd = {"atr_pct": 0.005, "regime": "trend_up"}
        sl_px, tp_px, sl_pct, tp_pct = trader._p2_s4b_compute_sltp(
            tier="probe", action="short", entry_px=100.0,
            source_tag="evolution", _last_kd=_last_kd
        )
        assert sl_pct >= 0.08, f"SHORT SL 下限应 ≥8%, 实际 {sl_pct}"
        # SHORT: SL 价格 > entry（止损在上方）
        assert sl_px > 100.0, f"SHORT SL 价格应 > entry, 实际 {sl_px}"

    def test_returns_4_tuple(self, trader):
        """返回值必须是 (sl_px, tp_px, sl_pct, tp_pct) 四元组."""
        _last_kd = {"atr_pct": 0.02, "regime": "trend_up"}
        result = trader._p2_s4b_compute_sltp(
            tier="probe", action="long", entry_px=100.0,
            source_tag="evolution", _last_kd=_last_kd
        )
        assert isinstance(result, tuple) and len(result) == 4, \
            f"返回值应为 4-tuple, 实际 {type(result)}"
