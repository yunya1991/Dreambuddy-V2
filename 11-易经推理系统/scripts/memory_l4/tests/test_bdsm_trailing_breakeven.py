# -*- coding: utf-8 -*-
"""BDSM 子池移动止盈(Trailing Stop) + 保本位(Break-Even) TDD 测试集.

修复项（对应 PUMP 事件：BDSM子池完全无trailing/保本位，盈利后零保护）:
  1. 保本位：upl_ratio >= 2% 时，SL 上移到 entry_price（保本）
  2. Trailing Stop：peak upl_ratio >= 5% 时，SL = current_price * (1 - retrace 5%)
  3. 方向感知：long/short 正确处理 SL 方向

每个新测试 **先失败** → 对应代码实现后 **再通过**。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


class TestBDSMTrailingAndBreakEven:
    """BDSM 子池 trailing + 保本位逻辑"""

    @pytest.fixture
    def trader(self):
        """构造 mock trader 实例（带 _bdsm_peak_upl dict 和 okx_client mock）"""
        from polling_trader import PollingTrader
        # 不真正初始化，用 __new__ 绕过 __init__
        t = PollingTrader.__new__(PollingTrader)
        t._bdsm_peak_upl = {}
        t.okx_client = MagicMock()
        t.okx_client.cancel_algo_orders = MagicMock()
        t.okx_client.place_stop_loss_take_profit = MagicMock()
        # mock _log
        t._log = MagicMock()
        return t

    def test_break_even_long_moves_sl_to_entry(self, trader):
        """多头 upl=3% >= 2% 保本位 → SL 上移到 entry_price"""
        pos_info = {
            "inst_id": "PUMP-USDT-SWAP",
            "coin": "PUMP",
            "pos_side": "long",
            "avg_px": 0.004384,
            "mark_px": 0.004516,  # +3%
            "upl_ratio": 0.03,
            "_trade_record": MagicMock(stop_loss_px=0.004200),  # 当前 SL 在 entry 下方
        }
        executed = trader._bdsm_apply_trailing_breakeven(pos_info)
        assert executed is True
        # 验证 SL 被更新到 entry_price
        call_kwargs = trader.okx_client.place_stop_loss_take_profit.call_args.kwargs
        assert call_kwargs["stop_loss_px"] == pytest.approx(0.004384, abs=1e-8)
        assert "break_even" in call_kwargs["reason"]

    def test_break_even_short_moves_sl_to_entry(self, trader):
        """空头 upl=3% >= 2% 保本位 → SL 下移到 entry_price"""
        pos_info = {
            "inst_id": "ETH-USDT-SWAP",
            "coin": "ETH",
            "pos_side": "short",
            "avg_px": 3000.0,
            "mark_px": 2910.0,  # +3%
            "upl_ratio": 0.03,
            "_trade_record": MagicMock(stop_loss_px=3100.0),  # 当前 SL 在 entry 上方
        }
        executed = trader._bdsm_apply_trailing_breakeven(pos_info)
        assert executed is True
        call_kwargs = trader.okx_client.place_stop_loss_take_profit.call_args.kwargs
        assert call_kwargs["stop_loss_px"] == pytest.approx(3000.0, abs=1e-8)
        assert "break_even" in call_kwargs["reason"]

    def test_trailing_long_armed(self, trader):
        """多头 peak=7% >= 5% arm，当前 upl=5% > 2% → SL = mark_px * (1 - 5%)"""
        pos_info = {
            "inst_id": "SOL-USDT-SWAP",
            "coin": "SOL",
            "pos_side": "long",
            "avg_px": 100.0,
            "mark_px": 105.0,  # 当前 +5%
            "upl_ratio": 0.05,
            "_trade_record": MagicMock(stop_loss_px=100.0),
        }
        # 先设置 peak=7%
        trader._bdsm_peak_upl["SOL"] = 0.07
        executed = trader._bdsm_apply_trailing_breakeven(pos_info)
        assert executed is True
        call_kwargs = trader.okx_client.place_stop_loss_take_profit.call_args.kwargs
        expected_sl = 105.0 * (1 - 0.05)  # 99.75
        assert call_kwargs["stop_loss_px"] == pytest.approx(expected_sl, abs=1e-8)
        assert "trailing" in call_kwargs["reason"]

    def test_trailing_short_armed(self, trader):
        """空头 peak=7% >= 5% arm，当前 upl=5% > 2% → SL = mark_px * (1 + 5%)"""
        pos_info = {
            "inst_id": "BTC-USDT-SWAP",
            "coin": "BTC",
            "pos_side": "short",
            "avg_px": 60000.0,
            "mark_px": 57000.0,  # 当前 +5%
            "upl_ratio": 0.05,
            "_trade_record": MagicMock(stop_loss_px=60000.0),
        }
        trader._bdsm_peak_upl["BTC"] = 0.07
        executed = trader._bdsm_apply_trailing_breakeven(pos_info)
        assert executed is True
        call_kwargs = trader.okx_client.place_stop_loss_take_profit.call_args.kwargs
        expected_sl = 57000.0 * (1 + 0.05)  # 59850
        assert call_kwargs["stop_loss_px"] == pytest.approx(expected_sl, abs=1e-8)
        assert "trailing" in call_kwargs["reason"]

    def test_no_action_below_breakeven(self, trader):
        """upl=1% < 2% 保本位 → 无动作"""
        pos_info = {
            "inst_id": "UNI-USDT-SWAP",
            "coin": "UNI",
            "pos_side": "long",
            "avg_px": 10.0,
            "mark_px": 10.10,  # +1%
            "upl_ratio": 0.01,
            "_trade_record": MagicMock(stop_loss_px=9.85),
        }
        executed = trader._bdsm_apply_trailing_breakeven(pos_info)
        assert executed is False
        trader.okx_client.place_stop_loss_take_profit.assert_not_called()

    def test_peak_updates_on_new_high(self, trader):
        """peak upl_ratio 持续更新到历史最高"""
        pos_info = {
            "inst_id": "AAVE-USDT-SWAP",
            "coin": "AAVE",
            "pos_side": "long",
            "avg_px": 100.0,
            "mark_px": 104.0,  # +4%
            "upl_ratio": 0.04,
            "_trade_record": MagicMock(stop_loss_px=100.0),
        }
        trader._bdsm_peak_upl["AAVE"] = 0.03  # 之前 peak=3%
        trader._bdsm_apply_trailing_breakeven(pos_info)
        # peak 应更新到 4%
        assert trader._bdsm_peak_upl["AAVE"] == pytest.approx(0.04)

    def test_break_even_not_triggered_when_sl_already_above_entry(self, trader):
        """多头 SL 已在 entry 上方（已保本）→ 不重复触发保本位（由 trailing 接管）"""
        pos_info = {
            "inst_id": "HYPE-USDT-SWAP",
            "coin": "HYPE",
            "pos_side": "long",
            "avg_px": 1.0,
            "mark_px": 1.03,  # +3%
            "upl_ratio": 0.03,
            "_trade_record": MagicMock(stop_loss_px=1.01),  # SL 已在 entry 上方
        }
        executed = trader._bdsm_apply_trailing_breakeven(pos_info)
        # 不触发 break_even（SL 已保本），但 peak 更新
        assert executed is False
