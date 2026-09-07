"""test_sync_tp_sl_guard.py — _sync_tp_sl_orders SL秒触发防护测试.

Bug背景: MU持仓在亏损-2.3%时，_update_tp_sl_dynamic每轮同步OCO止损单。
日K线更新导致MA200止损价从$896跳到$961.74，但当前价$955 < SL $961.74 →
OKX OCO挂上去SL秒触发 → MU被强制平仓亏损-2.4%。

根因: _sync_tp_sl_orders只校验 sl_price < entry_price，
未校验 sl_price < current_price。当 current < SL < entry 时SL秒触发。

修复: 新增 current_price 参数，LONG时 sl_price >= current_price → 只挂TP不挂SL。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HERE = Path(__file__).resolve().parent
_V15_ROOT = _HERE.parent
if str(_V15_ROOT) not in sys.path:
    sys.path.insert(0, str(_V15_ROOT))
if str(_V15_ROOT / "core") not in sys.path:
    sys.path.insert(0, str(_V15_ROOT / "core"))
if str(_V15_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(_V15_ROOT / "lib"))


class TestSyncTpSlGuard:
    """SL在当前价上方时不应挂OCO止损单，只挂TP。"""

    def test_long_sl_above_current_skips_sl(self):
        """LONG: SL=$961.74 > current=$955 → 只挂TP，不挂SL（防止秒触发）。"""
        from v15_trader import _sync_tp_sl_orders

        client = MagicMock()
        client.cancel_algo_orders = MagicMock()
        client.place_stop_loss_take_profit = MagicMock(
            return_value={"ok": True, "data": {"algoId": "tp_only"}}
        )

        pos = {
            "inst_id": "MU-USDT-SWAP",
            "sz": "0.15",
            "direction": "LONG",
        }

        # SL=$961.74 在 current=$955 上方 → 应只挂TP
        _sync_tp_sl_orders(
            client, "MU", pos,
            entry_price=984.41,
            tp_pct=0.27,        # TP=$1250.83
            sl_price=961.7389,  # SL在当前价上方！
            current_price=955.0,
        )

        # 应调用 place_stop_loss_take_profit 但不带 stop_loss_px
        call_args = client.place_stop_loss_take_profit.call_args
        assert call_args is not None, "应调用place_stop_loss_take_profit"
        # 不应包含 stop_loss_px 参数（或为None）
        assert "stop_loss_px" not in call_args.kwargs or call_args.kwargs["stop_loss_px"] is None, (
            f"SL在当前价上方时不应传stop_loss_px，实际传了: {call_args.kwargs}"
        )

    def test_long_sl_below_current_places_oco(self):
        """LONG: SL=$896 < current=$955 → 正常挂OCO（TP+SL）。"""
        from v15_trader import _sync_tp_sl_orders

        client = MagicMock()
        client.cancel_algo_orders = MagicMock()
        client.place_stop_loss_take_profit = MagicMock(
            return_value={"ok": True, "data": {"algoId": "oco_ok"}}
        )

        pos = {
            "inst_id": "MU-USDT-SWAP",
            "sz": "0.15",
            "direction": "LONG",
        }

        # SL=$896 在 current=$955 下方 → 正常挂OCO
        _sync_tp_sl_orders(
            client, "MU", pos,
            entry_price=984.41,
            tp_pct=0.27,
            sl_price=896.87,
            current_price=955.0,
        )

        call_args = client.place_stop_loss_take_profit.call_args
        assert call_args is not None
        assert call_args.kwargs.get("stop_loss_px") == 896.87, (
            f"SL在当前价下方时应传stop_loss_px=896.87，实际: {call_args.kwargs}"
        )

    def test_current_price_none_skips_check_backward_compat(self):
        """current_price=None 时不做SL vs current校验（向后兼容）。"""
        from v15_trader import _sync_tp_sl_orders

        client = MagicMock()
        client.cancel_algo_orders = MagicMock()
        client.place_stop_loss_take_profit = MagicMock(
            return_value={"ok": True}
        )

        pos = {"inst_id": "MU-USDT-SWAP", "sz": "0.15", "direction": "LONG"}

        # current_price不传 → 不做额外校验，按原逻辑(sl < entry)走OCO
        _sync_tp_sl_orders(
            client, "MU", pos,
            entry_price=984.41,
            tp_pct=0.27,
            sl_price=961.7389,  # SL < entry → 原逻辑valid
            # current_price 不传
        )

        call_args = client.place_stop_loss_take_profit.call_args
        assert call_args is not None
        # 向后兼容：SL < entry → 挂OCO
        assert call_args.kwargs.get("stop_loss_px") == 961.7389

    def test_short_sl_below_current_skips_sl(self):
        """SHORT: SL=$1050 < current=$1100 → SL在当前价下方 → 只挂TP。"""
        from v15_trader import _sync_tp_sl_orders

        client = MagicMock()
        client.cancel_algo_orders = MagicMock()
        client.place_stop_loss_take_profit = MagicMock(
            return_value={"ok": True}
        )

        pos = {"inst_id": "BTC-USDT-SWAP", "sz": "0.01", "direction": "SHORT"}

        # SHORT: SL=$1050 < current=$1100 → SL在当前价下方 → 秒触发 → 只挂TP
        _sync_tp_sl_orders(
            client, "BTC", pos,
            entry_price=1000.0,
            tp_pct=0.04,
            sl_price=1050.0,    # SHORT SL应在当前价上方才安全
            current_price=1100.0,
        )

        call_args = client.place_stop_loss_take_profit.call_args
        assert call_args is not None
        assert "stop_loss_px" not in call_args.kwargs or call_args.kwargs["stop_loss_px"] is None, (
            f"SHORT时SL在当前价下方不应传stop_loss_px"
        )
