#!/usr/bin/env python3
"""BDSM 做空试错单信号分级测试（RED→GREEN）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.polling_trader import PollingTrader


def _make_entry(**kw):
    entry = {
        "bds_score": 0.0,
        "exit_action": "NONE",
        "trend_stop": {"action": "none"},
        "value_exit": {"action": "none"},
    }
    entry.update(kw)
    return entry


def _make_snapshot(coin, entry):
    return {"coins": {coin: entry}}


class TestClassifyBdsmShortSignal:
    """_classify_bdsm_short_signal 信号分级测试"""

    # === L1 强做空信号 ===

    def test_bds_below_zero_is_l1(self):
        """bds_score < 0 → L1 强做空"""
        snap = _make_snapshot("SOL", _make_entry(bds_score=-0.126))
        assert PollingTrader._classify_bdsm_short_signal(snap, "SOL") == "L1"

    def test_exit_action_close_all_is_l1(self):
        """exit_action=CLOSE_ALL → L1 强做空"""
        snap = _make_snapshot("ETH", _make_entry(exit_action="CLOSE_ALL"))
        assert PollingTrader._classify_bdsm_short_signal(snap, "ETH") == "L1"

    def test_trend_stop_full_exit_is_l1(self):
        """trend_stop.action=full_exit → L1 强做空"""
        snap = _make_snapshot("BTC", _make_entry(trend_stop={"action": "full_exit"}))
        assert PollingTrader._classify_bdsm_short_signal(snap, "BTC") == "L1"

    # === L2 中做空信号 ===

    def test_exit_action_reduce_80_is_l2(self):
        """exit_action=REDUCE_80 → L2 中做空"""
        snap = _make_snapshot("UNI", _make_entry(exit_action="REDUCE_80"))
        assert PollingTrader._classify_bdsm_short_signal(snap, "UNI") == "L2"

    def test_trend_stop_reduce50_is_l2(self):
        """trend_stop.action=reduce50 → L2 中做空"""
        snap = _make_snapshot("AAVE", _make_entry(trend_stop={"action": "reduce50"}))
        assert PollingTrader._classify_bdsm_short_signal(snap, "AAVE") == "L2"

    # === 不做空信号 ===

    def test_value_exit_full_exit_with_positive_bds_is_none(self):
        """value_exit=full_exit 但 bds≥0 → 不做空（高估止盈，非恶化）"""
        snap = _make_snapshot("UNI", _make_entry(
            bds_score=0.498,
            value_exit={"action": "full_exit"},
        ))
        assert PollingTrader._classify_bdsm_short_signal(snap, "UNI") is None

    def test_reduce_50_is_none(self):
        """exit_action=REDUCE_50 → 不做空（减仓信号）"""
        snap = _make_snapshot("ZEC", _make_entry(exit_action="REDUCE_50"))
        assert PollingTrader._classify_bdsm_short_signal(snap, "ZEC") is None

    def test_trend_stop_reduce30_is_none(self):
        """trend_stop.action=reduce30 → 不做空（轻度减仓）"""
        snap = _make_snapshot("PUMP", _make_entry(trend_stop={"action": "reduce30"}))
        assert PollingTrader._classify_bdsm_short_signal(snap, "PUMP") is None

    def test_no_signal_is_none(self):
        """无任何恶化信号 → 不做空"""
        snap = _make_snapshot("HYPE", _make_entry())
        assert PollingTrader._classify_bdsm_short_signal(snap, "HYPE") is None

    # === FAIL-OPEN ===

    def test_missing_coin_returns_none(self):
        """币种不在快照中 → None"""
        snap = {"coins": {}}
        assert PollingTrader._classify_bdsm_short_signal(snap, "XXX") is None

    def test_missing_snapshot_returns_none(self):
        """快照为空 → None"""
        assert PollingTrader._classify_bdsm_short_signal(None, "SOL") is None
        assert PollingTrader._classify_bdsm_short_signal({}, "SOL") is None

    def test_missing_fields_default_to_none(self):
        """字段缺失 → 默认值，不触发做空"""
        snap = _make_snapshot("ARB", {})  # 无 bds_score/exit_action/trend_stop
        assert PollingTrader._classify_bdsm_short_signal(snap, "ARB") is None


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
