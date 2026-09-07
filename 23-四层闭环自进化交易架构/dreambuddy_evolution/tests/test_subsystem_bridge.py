"""test_subsystem_bridge.py — SubSystemBridge 单元测试
覆盖: war_state读取+温度映射, BCRM direction, scale_class, shadow优先, trader=None FO
"""
from __future__ import annotations

import pytest

from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge


class MockFiveDomainState:
    """模拟五计庙算状态"""
    war_state = {"crypto_usdt": "ALLOW", "crypto_us_stock": "FREEZE"}


class MockTrader:
    """模拟 polling_trader 实例"""
    def __init__(self, war_state=None, bcrm_result=None, bdsm_snapshot=None):
        if war_state:
            self._five_domain_state_shadow = MockFiveDomainState()
            self._five_domain_state_shadow.war_state = war_state
        else:
            self._five_domain_state_shadow = None
            self._five_domain_state_cache = None
        self._last_bcrm2_result = bcrm_result
        self._last_bdsm_snapshot = bdsm_snapshot


class TestSubSystemBridge:

    def test_war_state_allow(self):
        """war_state=ALLOW → 温度 1.0"""
        trader = MockTrader(war_state={"crypto_usdt": "ALLOW"})
        bridge = SubSystemBridge(trader)
        assert bridge.get_war_state() == "ALLOW"
        assert bridge.get_ess_temperature() == 1.0

    def test_war_state_freeze(self):
        """war_state=FREEZE → 温度 0.1"""
        trader = MockTrader(war_state={"crypto_usdt": "FREEZE"})
        bridge = SubSystemBridge(trader)
        assert bridge.get_war_state() == "FREEZE"
        assert bridge.get_ess_temperature() == 0.1

    def test_war_state_cooldown(self):
        """war_state=COOLDOWN → 温度 0.5"""
        trader = MockTrader(war_state={"crypto_usdt": "COOLDOWN"})
        bridge = SubSystemBridge(trader)
        assert bridge.get_war_state() == "COOLDOWN"
        assert bridge.get_ess_temperature() == 0.5

    def test_bcrm_direction_up(self):
        """BCRM direction=UP → 'long'"""
        trader = MockTrader(bcrm_result={
            "next_state": {"direction": "UP", "confidence": 0.85}
        })
        bridge = SubSystemBridge(trader)
        assert bridge.get_bcrm_direction() == "long"
        assert bridge.get_bcrm_confidence() == 0.85

    def test_bcrm_direction_down(self):
        """BCRM direction=DOWN → 'short'"""
        trader = MockTrader(bcrm_result={
            "next_state": {"direction": "DOWN", "confidence": 0.7}
        })
        bridge = SubSystemBridge(trader)
        assert bridge.get_bcrm_direction() == "short"

    def test_bcrm_direction_flat(self):
        """BCRM direction=FLAT → ''"""
        trader = MockTrader(bcrm_result={
            "next_state": {"direction": "FLAT", "confidence": 0.3}
        })
        bridge = SubSystemBridge(trader)
        assert bridge.get_bcrm_direction() == ""

    def test_scale_class_btc(self):
        """BTC → Classical"""
        assert SubSystemBridge.get_scale_class("BTC") == "Classical"
        assert SubSystemBridge.get_scale_class("ETH") == "Classical"

    def test_scale_class_sol(self):
        """SOL → Meso"""
        assert SubSystemBridge.get_scale_class("SOL") == "Meso"
        assert SubSystemBridge.get_scale_class("XRP") == "Meso"

    def test_scale_class_unknown(self):
        """UNKNOWN → Quantum"""
        assert SubSystemBridge.get_scale_class("PEPE") == "Quantum"

    def test_trader_none_fo(self):
        """trader=None → 安全默认值"""
        bridge = SubSystemBridge(None)
        assert bridge.get_war_state() == "ALLOW"
        assert bridge.get_ess_temperature() == 1.0
        assert bridge.get_bcrm_direction() == ""
        assert bridge.get_bcrm_confidence() == 0.0
        assert bridge.get_bdsm_valuation() == 0.5

    def test_bcrm_result_none(self):
        """无 BCRM 结果 → 空方向"""
        trader = MockTrader(bcrm_result=None)
        bridge = SubSystemBridge(trader)
        assert bridge.get_bcrm_direction() == ""

    def test_bdsm_valuation(self):
        """BDSM 估值分位"""
        trader = MockTrader(bdsm_snapshot={"valuation_percentile": 0.72})
        bridge = SubSystemBridge(trader)
        assert bridge.get_bdsm_valuation() == 0.72

    def test_war_state_shadow_priority(self):
        """影子模式优先读 _five_domain_state_shadow"""
        class DualTrader:
            def __init__(self):
                self._five_domain_state_shadow = MockFiveDomainState()
                self._five_domain_state_shadow.war_state = {"crypto_usdt": "RESTRICT"}
                self._five_domain_state_cache = MockFiveDomainState()
                self._five_domain_state_cache.war_state = {"crypto_usdt": "ALLOW"}

        trader = DualTrader()
        bridge = SubSystemBridge(trader)
        # shadow 优先 → RESTRICT
        assert bridge.get_war_state() == "RESTRICT"
        assert bridge.get_ess_temperature() == 0.2
