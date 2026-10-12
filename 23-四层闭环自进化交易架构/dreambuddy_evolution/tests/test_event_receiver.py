"""
P1-2 RED: EventReceiver 组件契约测试
来源: SPEC v0.3 §2.B — 从 kline_event_handler.py 拆出 K线事件接收+L1 R向量+AGI-A签名职责

拆分目标:
- receive_kline(kline_data, rv, router=None)->dict (含 symbol / r_vector / agi_signature)
- write_event_driven_state(kline_data, result)->None
"""
from __future__ import annotations

import numpy as np
import pytest


class TestEventReceiverContract:
    """EventReceiver 接口契约 — RED 阶段断言模块尚未创建"""

    def test_module_importable(self):
        from dreambuddy_evolution.engines.event_receiver import EventReceiver  # noqa: F401

    def test_class_instantiates_with_mode(self):
        from dreambuddy_evolution.engines.event_receiver import EventReceiver
        receiver = EventReceiver(mode="Phase2")
        assert receiver is not None


class TestReceiveKline:
    """receive_kline 返回 L1 R 向量 + AGI 签名"""

    def test_returns_dict_with_symbol(self):
        from dreambuddy_evolution.engines.event_receiver import EventReceiver
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        receiver = EventReceiver(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0, 101.0, 102.0, 103.0, 104.0] * 4,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "vol_5": 2000.0,
            "vol_20": 1000.0,
            "bid_ask_spread_bps": 2.0,
        }
        result = receiver.receive_kline(kline_data, rv=ResistanceVector())
        assert isinstance(result, dict)
        assert "symbol" in result
        assert result["symbol"] == "BTC-USDT-SWAP"

    def test_returns_dict_with_r_vector(self):
        from dreambuddy_evolution.engines.event_receiver import EventReceiver
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        receiver = EventReceiver(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
        }
        result = receiver.receive_kline(kline_data, rv=ResistanceVector())
        assert "r_vector" in result
        assert "R_up" in result["r_vector"]
