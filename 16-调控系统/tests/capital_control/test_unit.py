"""
单元测试：资金调控核心数据结构、健康判定、4 条资金规则 handler。

运行方式::

    cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
    python -m pytest 16-调控系统/tests/capital_control/test_unit.py -v
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 设置 sys.path
_PROJECT = Path(__file__).resolve().parents[3]  # dreambuddy-v2
_CORE = _PROJECT / "16-调控系统" / "core"
_RISK = _PROJECT / "13-通用风控模块"
_RISK_CORE = _RISK / "core"
for _p in (_CORE, _RISK, _RISK_CORE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest

from capital_control.types import (
    AccountType,
    CapitalMode,
    CapitalResult,
    CapitalSnapshot,
    HealthLevel,
    assess_health,
    calc_margin_pressure,
    now_iso,
)


# =========================================================================
# 数据结构测试
# =========================================================================


class TestCapitalMode:
    def test_values(self):
        assert CapitalMode.FIXED.value == "fixed"
        assert CapitalMode.DYNAMIC.value == "dynamic"

    def test_from_string(self):
        assert CapitalMode("fixed") == CapitalMode.FIXED
        assert CapitalMode("dynamic") == CapitalMode.DYNAMIC


class TestAccountType:
    def test_all_types(self):
        assert AccountType.OKX_LIVE.value == "okx_live"
        assert AccountType.OKX_SIMULATED.value == "okx_simulated"
        assert AccountType.HYPERLIQUID.value == "hyperliquid"
        assert AccountType.ASTER.value == "aster"
        assert AccountType.UNKNOWN.value == "unknown"


class TestCapitalResult:
    def test_creation(self):
        r = CapitalResult(
            system="v15_martin",
            account_type=AccountType.OKX_LIVE,
            mode=CapitalMode.DYNAMIC,
            total_eq=260.5,
            avail_balance=180.3,
            used_margin=80.2,
            used_pct=30.79,
        )
        assert r.system == "v15_martin"
        assert r.total_eq == 260.5
        assert r.fallback_used is False

    def test_to_dict(self):
        r = CapitalResult(
            system="test",
            account_type=AccountType.HYPERLIQUID,
            mode=CapitalMode.FIXED,
            total_eq=60.0,
            avail_balance=60.0,
            used_margin=0.0,
            used_pct=0.0,
        )
        d = r.to_dict()
        assert d["account_type"] == "hyperliquid"
        assert d["mode"] == "fixed"
        assert d["total_eq"] == 60.0


class TestCapitalSnapshot:
    def test_creation_and_to_dict(self):
        r = CapitalResult(
            system="v15_martin",
            account_type=AccountType.OKX_LIVE,
            mode=CapitalMode.DYNAMIC,
            total_eq=260.0,
            avail_balance=260.0,
            used_margin=0.0,
            used_pct=0.0,
        )
        snap = CapitalSnapshot(
            timestamp=now_iso(),
            mode=CapitalMode.DYNAMIC,
            by_system={"v15_martin": r},
            total_equity=260.0,
            total_avail=260.0,
            total_used=0.0,
            overall_used_pct=0.0,
            health=HealthLevel.HEALTHY,
        )
        d = snap.to_dict()
        assert d["health"] == "HEALTHY"
        assert d["totals"]["total_equity"] == 260.0
        assert "v15_martin" in d["by_system"]


# =========================================================================
# 健康判定测试
# =========================================================================


class TestAssessHealth:
    def test_healthy(self):
        assert assess_health(30.0, False, False) == HealthLevel.HEALTHY

    def test_warning_on_pct(self):
        assert assess_health(60.0, False, False) == HealthLevel.WARNING

    def test_critical_on_pct(self):
        assert assess_health(80.0, False, False) == HealthLevel.CRITICAL

    def test_warning_on_fallback(self):
        assert assess_health(30.0, True, False) == HealthLevel.WARNING

    def test_critical_on_unavailable(self):
        assert assess_health(30.0, False, True) == HealthLevel.CRITICAL

    def test_custom_thresholds(self):
        thresholds = {"healthy_used_pct_max": 20.0, "warning_used_pct_max": 40.0}
        assert assess_health(25.0, False, False, thresholds) == HealthLevel.WARNING
        assert assess_health(45.0, False, False, thresholds) == HealthLevel.CRITICAL


class TestCalcMarginPressure:
    def test_low(self):
        assert calc_margin_pressure(10.0) == "LOW"

    def test_medium(self):
        assert calc_margin_pressure(50.0) == "MEDIUM"

    def test_high(self):
        assert calc_margin_pressure(80.0) == "HIGH"

    def test_boundary(self):
        assert calc_margin_pressure(49.99) == "LOW"
        assert calc_margin_pressure(79.99) == "MEDIUM"


# =========================================================================
# 资金规则 handler 测试
# =========================================================================


def _mock_positions_result(system, equity=0.0, avail=0.0, used=0.0, account_type="unknown", fallback_reason=""):
    """构造一个 mock fetch_all_positions 结果"""
    return {
        "systems": {
            system: {
                "equity": equity,
                "extra": {
                    "avail_balance": avail,
                    "used_margin": used,
                    "account_type": account_type,
                    "fallback_reason": fallback_reason,
                },
            }
        }
    }


class TestOkxLiveRule:
    def test_dynamic_success(self):
        """动态模式成功查询"""
        from capital_control.capital_rules.okx_live_rule import okx_live_capital_handler

        mock_pos = _mock_positions_result("v15_martin", equity=260.5, avail=180.3, used=80.2, account_type="okx_live")
        ctx = {"mode": CapitalMode.DYNAMIC, "positions_result": mock_pos}
        r = okx_live_capital_handler(context=ctx, config={"fallback_static_budget": {"v15_martin": 260.0}})
        assert r.total_eq == 260.5
        assert r.fallback_used is False
        assert r.account_type == AccountType.OKX_LIVE

    def test_fixed_mode(self):
        """FIXED 模式使用静态值"""
        from capital_control.capital_rules.okx_live_rule import okx_live_capital_handler

        r = okx_live_capital_handler(
            context={"mode": CapitalMode.FIXED},
            config={"fallback_static_budget": {"v15_martin": 260.0}},
        )
        assert r.total_eq == 260.0
        assert r.fallback_used is True
        assert r.mode == CapitalMode.FIXED

    def test_fallback_on_equity_zero(self):
        """equity=0 时降级到静态值"""
        from capital_control.capital_rules.okx_live_rule import okx_live_capital_handler

        mock_pos = _mock_positions_result("v15_martin", equity=0.0, account_type="okx_live")
        ctx = {"mode": CapitalMode.DYNAMIC, "positions_result": mock_pos}
        r = okx_live_capital_handler(context=ctx, config={"fallback_static_budget": {"v15_martin": 260.0}})
        assert r.total_eq == 260.0
        assert r.fallback_used is True

    def test_fallback_on_missing_system(self):
        """系统数据缺失时降级"""
        from capital_control.capital_rules.okx_live_rule import okx_live_capital_handler

        ctx = {"mode": CapitalMode.DYNAMIC, "positions_result": {"systems": {}}}
        r = okx_live_capital_handler(context=ctx, config={"fallback_static_budget": {"v15_martin": 260.0}})
        assert r.total_eq == 260.0
        assert r.fallback_used is True
        assert "system_data_missing" in r.fallback_reason


class TestOkxSimulatedRule:
    def test_dynamic_success(self):
        from capital_control.capital_rules.okx_simulated_rule import okx_simulated_capital_handler

        mock_pos = _mock_positions_result("yijing_bcrm", equity=150.0, avail=100.0, used=50.0, account_type="okx_simulated")
        ctx = {"mode": CapitalMode.DYNAMIC, "positions_result": mock_pos}
        r = okx_simulated_capital_handler(context=ctx, config={})
        assert r.total_eq == 150.0
        assert r.fallback_used is False
        assert r.account_type == AccountType.OKX_SIMULATED


class TestHyperliquidRule:
    def test_returns_multi_system_dict(self):
        from capital_control.capital_rules.hyperliquid_rule import hyperliquid_capital_handler

        mock_pos = {
            "systems": {
                "agent_a": {"equity": 60.0, "extra": {"account_type": "hyperliquid", "avail_balance": 60.0}},
                "agent_b": {"equity": 80.0, "extra": {"account_type": "hyperliquid", "avail_balance": 80.0}},
                "agent_c_memory": {"equity": 80.0, "extra": {"account_type": "hyperliquid", "avail_balance": 80.0}},
            }
        }
        ctx = {"mode": CapitalMode.DYNAMIC, "positions_result": mock_pos}
        results = hyperliquid_capital_handler(context=ctx, config={})
        assert isinstance(results, dict)
        assert len(results) == 3
        assert "agent_a" in results
        assert results["agent_a"].total_eq == 60.0
        assert results["agent_b"].total_eq == 80.0

    def test_single_target_system(self):
        from capital_control.capital_rules.hyperliquid_rule import hyperliquid_capital_handler

        mock_pos = _mock_positions_result("agent_a", equity=60.0, avail=60.0, account_type="hyperliquid")
        ctx = {"mode": CapitalMode.DYNAMIC, "positions_result": mock_pos, "target_system": "agent_a"}
        results = hyperliquid_capital_handler(context=ctx, config={})
        assert "agent_a" in results
        assert len(results) == 1


class TestAsterRule:
    def test_fallback_on_zero_equity(self):
        """三屏 equity=0（ml_trade_service 未运行）时降级到静态 200"""
        from capital_control.capital_rules.aster_rule import aster_capital_handler

        mock_pos = _mock_positions_result("three_screen", equity=0.0, account_type="aster")
        ctx = {"mode": CapitalMode.DYNAMIC, "positions_result": mock_pos}
        r = aster_capital_handler(context=ctx, config={"fallback_static_budget": {"three_screen": 200.0}})
        assert r.total_eq == 200.0
        assert r.fallback_used is True
        assert r.account_type == AccountType.ASTER


class TestSharedHelper:
    def test_build_result_fixed_mode(self):
        from capital_control.capital_rules._shared import build_result_from_system

        r = build_result_from_system(
            system="v15_martin",
            account_type_default=AccountType.OKX_LIVE,
            mode=CapitalMode.FIXED,
            static_budget=260.0,
        )
        assert r.total_eq == 260.0
        assert r.fallback_used is True
        assert r.mode == CapitalMode.FIXED

    def test_build_result_dynamic_with_equity(self):
        from capital_control.capital_rules._shared import build_result_from_system

        mock_pos = _mock_positions_result("v15_martin", equity=300.0, avail=200.0, used=100.0, account_type="okx_live")
        r = build_result_from_system(
            system="v15_martin",
            account_type_default=AccountType.OKX_LIVE,
            mode=CapitalMode.DYNAMIC,
            static_budget=260.0,
            context={"positions_result": mock_pos},
        )
        assert r.total_eq == 300.0
        assert r.avail_balance == 200.0
        assert r.used_margin == 100.0
        assert r.used_pct == pytest.approx(33.33, abs=0.1)

    def test_build_result_dynamic_zero_equity(self):
        from capital_control.capital_rules._shared import build_result_from_system

        mock_pos = _mock_positions_result("test", equity=0.0, account_type="aster")
        r = build_result_from_system(
            system="test",
            account_type_default=AccountType.ASTER,
            mode=CapitalMode.DYNAMIC,
            static_budget=200.0,
            context={"positions_result": mock_pos},
        )
        assert r.total_eq == 200.0
        assert r.fallback_used is True
