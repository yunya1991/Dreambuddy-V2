#!/usr/bin/env python3
"""P0 回归测试：_handle_close_position 必须接受 inference 关键字参数。

Bug 复盘：2026-09-05 实盘日志显示 BMNR/GOOGL 平仓时抛出
  PollingTrader._handle_close_position() got an unexpected keyword argument 'inference'
导致平仓后记账全流程中断（无 trade_rec、无绩效、无 case、无增量学习）。
根因：调用方传入 inference=，但函数签名未声明该参数。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.polling_trader import PollingTrader


def _make_trader():
    """构造一个仅 mock 掉 _handle_close_position 依赖的 PollingTrader 实例。"""
    trader = PollingTrader.__new__(PollingTrader)
    trader.yijing_exit_system = MagicMock()
    trader.okx_client = MagicMock()
    trader.position_tracker = MagicMock()
    # close_position 返回 None → 跳过 trade_rec 后续链路，仅验证签名不炸
    trader.position_tracker.close_position.return_value = None
    trader.perf_tracker = MagicMock()
    trader.risk_manager = MagicMock()
    trader._gate_threshold_state = {"recent_pnl": [], "n_max": 150}
    trader.incremental_learner = MagicMock()
    trader.learning_scheduler = MagicMock()
    trader.ranging_enhancer = None
    trader._log = MagicMock()
    return trader


def test_handle_close_position_accepts_inference_kwarg():
    """调用方传入 inference 时不得抛出 TypeError（记账链路不能断）。"""
    trader = _make_trader()
    # 不应抛 TypeError: got an unexpected keyword argument 'inference'
    trader._handle_close_position(
        inst_id="BTC-USDT-SWAP",
        coin="BTC",
        pos_side="long",
        exit_price=50000.0,
        exit_reason="trial_trend_reverse",
        pnl=-1.0,
        pnl_pct=-0.05,
        inference={"direction": "LONG", "confidence": 0.7},
    )


def test_handle_close_position_without_inference_still_works():
    """不传 inference 时（当前调用方）也必须正常工作，保证向后兼容。"""
    trader = _make_trader()
    trader._handle_close_position(
        inst_id="ETH-USDT-SWAP",
        coin="ETH",
        pos_side="long",
        exit_price=3000.0,
        exit_reason="sl_hit",
        pnl=-0.5,
        pnl_pct=-0.02,
    )


if __name__ == "__main__":
    test_handle_close_position_accepts_inference_kwarg()
    test_handle_close_position_without_inference_still_works()
    print("✅ _handle_close_position inference 参数兼容测试通过")
