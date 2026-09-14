# -*- coding: utf-8 -*-
"""OKX algo SL/TP 单可靠性校验 TDD 测试集.

修复项(P2-2): PUMP案例中 SL 单未生效导致强平。开仓后立即校验 algo 单是否存在，
缺失时重试并告警。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


class TestVerifyAlgoOrders:
    """开仓后 algo 单校验"""

    @pytest.fixture
    def trader(self):
        from polling_trader import PollingTrader
        t = PollingTrader.__new__(PollingTrader)
        t.okx_client = MagicMock()
        t._log = MagicMock()
        return t

    def test_verify_passes_when_sl_tp_exist(self, trader):
        """SL/TP algo 单都存在 → 返回 True，不重试"""
        trader.okx_client.get_algo_orders = MagicMock(return_value={
            "ok": True,
            "orders": [{"sl_trigger_px": 96.0, "tp_trigger_px": 112.0}],
        })
        result = trader._verify_algo_sltp("ETH-USDT-SWAP", "long", 100.0, 100.0)
        assert result is True
        # 不应重下
        trader.okx_client.place_stop_loss_take_profit.assert_not_called()

    def test_verify_retries_when_sl_missing(self, trader):
        """SL algo 单缺失 → 重试下 SL/TP"""
        trader.okx_client.get_algo_orders = MagicMock(side_effect=[
            {"ok": True, "orders": [{"tp_trigger_px": 112.0}]},  # 首次：只有 TP
            {"ok": True, "orders": [{"sl_trigger_px": 96.0, "tp_trigger_px": 112.0}]},  # 重试后：都有
        ])
        result = trader._verify_algo_sltp("ETH-USDT-SWAP", "long", 96.0, 112.0)
        assert result is True
        # 应重试下 SL/TP
        trader.okx_client.place_stop_loss_take_profit.assert_called_once()

    def test_verify_fails_when_still_missing_after_retry(self, trader):
        """重试后 SL 仍缺失 → 返回 False，告警"""
        trader.okx_client.get_algo_orders = MagicMock(return_value={
            "ok": True, "orders": [],  # 始终无 algo 单
        })
        result = trader._verify_algo_sltp("ETH-USDT-SWAP", "long", 96.0, 112.0)
        assert result is False
        # 应尝试重下
        assert trader.okx_client.place_stop_loss_take_profit.call_count >= 1

    def test_verify_skips_when_no_okx_client(self, trader):
        """无 okx_client → 返回 True（不阻塞）"""
        trader.okx_client = None
        result = trader._verify_algo_sltp("ETH-USDT-SWAP", "long", 96.0, 112.0)
        assert result is True
