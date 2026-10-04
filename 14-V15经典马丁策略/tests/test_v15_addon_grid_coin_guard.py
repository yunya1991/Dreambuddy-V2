"""test_v15_addon_grid_coin_guard.py — _place_addon_grid_orders 币种守卫测试.

Bug背景: V15 与 11-易经 BCRM2.0 共用 screen_trade 实盘账户（无账户隔离）。
9-27 20:20:08 11-易经 BCRM2.0（tag=yijingsim）误用实盘账户开 MU 多仓 →
1 秒后 V15 capital_manager 轮询发现 MU 持仓，误识别为自有持仓，
调用 _place_addon_grid_orders 挂 v15addongrid 限价买单
（0.02@805.14 + 0.04@709.02，已撤销）。

根因: _place_addon_grid_orders 入口仅校验 AUTO_EXECUTE，
未校验 coin 是否属于 V15 币种池（_RAW_COINS）。
任何外部策略在同账户开的仓都会被 V15 误识别为自有持仓并挂加仓网格单。

修复: 函数入口在 `if not AUTO_EXECUTE: return` 之后，
新增 `if coin.upper() not in [c.upper() for c in _RAW_COINS]: return` 守卫，
阻断非 V15 币种的历史/外部持仓误触发。
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


class TestPlaceAddonGridCoinGuard:
    """币种守卫：coin 不在 V15_COINS 时跳过加仓网格挂单。"""

    def _make_pos(self, coin: str = "MU", direction: str = "LONG") -> dict:
        """构造一个能走到 place_order 调用的最小 pos。"""
        return {
            "inst_id": f"{coin}-USDT-SWAP",
            "direction": direction,
            "open_price": 1000.0,
            "addon_pct": 0.08,
            "addon1_usd": 100.0,
            "addon2_usd": 100.0,
            "addon3_usd": 100.0,
            "addon4_usd": 100.0,
            "vol_mult": 1.0,
            "timing_mult": 1.0,
            "ai_effective_max_addons": 4,
        }

    def test_mu_not_in_v15_coins_skips_addon_grid(self):
        """MU 不在 V15_COINS（外部策略误开仓） → 不应调用 place_order。"""
        from v15_trader import _place_addon_grid_orders

        client = MagicMock()
        client.place_order = MagicMock(return_value={"ok": True, "ord_id": "fake"})

        pos = self._make_pos("MU", "LONG")

        with patch("v15_trader.AUTO_EXECUTE", True), \
             patch("v15_trader._RAW_COINS", ["BTC", "ETH", "SOL", "UNI", "LINK", "ZEC"]), \
             patch("v15_trader._cancel_addon_grid_orders"), \
             patch("v15_trader.get_contract_info", return_value=(0.01, 0.01)), \
             patch("v15_trader.calc_lot_sz", return_value=0.05), \
             patch("v15_trader.LEVERAGE", 5), \
             patch("v15_trader.MAX_ADDONS", 4), \
             patch("v15_trader.ADDON_PCT", 0.08):
            _place_addon_grid_orders(client, "MU", pos)

        # 守卫应阻断：place_order 不应被调用
        assert client.place_order.call_count == 0, (
            f"MU 不在 V15_COINS 时不应挂加仓网格单，但 place_order 被调用了 "
            f"{client.place_order.call_count} 次"
        )

    def test_btc_in_v15_coins_places_addon_grid(self):
        """BTC 在 V15_COINS（正常 V15 持仓） → 应正常调用 place_order 挂加仓网格。"""
        from v15_trader import _place_addon_grid_orders

        client = MagicMock()
        client.place_order = MagicMock(return_value={"ok": True, "ord_id": "fake"})

        pos = self._make_pos("BTC", "LONG")

        with patch("v15_trader.AUTO_EXECUTE", True), \
             patch("v15_trader._RAW_COINS", ["BTC", "ETH", "SOL", "UNI", "LINK", "ZEC"]), \
             patch("v15_trader._cancel_addon_grid_orders"), \
             patch("v15_trader.get_contract_info", return_value=(0.01, 0.01)), \
             patch("v15_trader.calc_lot_sz", return_value=0.05), \
             patch("v15_trader.LEVERAGE", 5), \
             patch("v15_trader.MAX_ADDONS", 4), \
             patch("v15_trader.ADDON_PCT", 0.08):
            _place_addon_grid_orders(client, "BTC", pos)

        # 正常 V15 币种：place_order 应被调用（4 档加仓）
        assert client.place_order.call_count > 0, (
            "BTC 在 V15_COINS 时应正常挂加仓网格单，但 place_order 未被调用"
        )
        # 确认 tag 是 v15addongrid
        first_call = client.place_order.call_args
        assert first_call.kwargs.get("tag") == "v15addongrid", (
            f"加仓网格 tag 应为 v15addongrid，实际: {first_call.kwargs.get('tag')}"
        )

    def test_case_insensitive_coin_guard(self):
        """币种大小写不敏感：'mu' 小写也应被守卫阻断。"""
        from v15_trader import _place_addon_grid_orders

        client = MagicMock()
        client.place_order = MagicMock(return_value={"ok": True, "ord_id": "fake"})

        pos = self._make_pos("mu", "LONG")

        with patch("v15_trader.AUTO_EXECUTE", True), \
             patch("v15_trader._RAW_COINS", ["BTC", "ETH", "SOL"]), \
             patch("v15_trader._cancel_addon_grid_orders"), \
             patch("v15_trader.get_contract_info", return_value=(0.01, 0.01)), \
             patch("v15_trader.calc_lot_sz", return_value=0.05), \
             patch("v15_trader.LEVERAGE", 5), \
             patch("v15_trader.MAX_ADDONS", 4), \
             patch("v15_trader.ADDON_PCT", 0.08):
            _place_addon_grid_orders(client, "mu", pos)

        assert client.place_order.call_count == 0, (
            "小写 'mu' 不在 V15_COINS 时也应被守卫阻断"
        )

    def test_auto_execute_false_skips_regardless_of_coin(self):
        """AUTO_EXECUTE=False 时无论币种都应直接返回（向后兼容）。"""
        from v15_trader import _place_addon_grid_orders

        client = MagicMock()
        client.place_order = MagicMock(return_value={"ok": True})

        pos = self._make_pos("BTC", "LONG")

        with patch("v15_trader.AUTO_EXECUTE", False), \
             patch("v15_trader._RAW_COINS", ["BTC", "ETH"]):
            _place_addon_grid_orders(client, "BTC", pos)

        # AUTO_EXECUTE=False → 直接 return，place_order 不应被调用
        assert client.place_order.call_count == 0
