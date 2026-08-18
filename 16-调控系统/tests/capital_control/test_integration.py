"""
集成测试：RuleRegistry CAPITAL 注册链、CapitalControlComponent 主流程、降级链。

运行方式::

    cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
    python -m pytest 16-调控系统/tests/capital_control/test_integration.py -v
"""

import sys
import os
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

_PROJECT = Path(__file__).resolve().parents[3]
_CORE = _PROJECT / "16-调控系统" / "core"
_RISK = _PROJECT / "13-通用风控模块"
_RISK_CORE = _RISK / "core"
for _p in (_CORE, _RISK, _RISK_CORE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest

try:
    from core.registry import RuleRegistry, RuleCategory, DEFAULT_RULES
except ImportError:
    from registry import RuleRegistry, RuleCategory, DEFAULT_RULES
from capital_control.types import (
    AccountType,
    CapitalMode,
    CapitalResult,
    CapitalSnapshot,
    HealthLevel,
)


# =========================================================================
# RuleRegistry CAPITAL 类别测试
# =========================================================================


class TestRuleRegistryCapital:
    def test_capital_category_exists(self):
        assert RuleCategory.CAPITAL.value == "capital"

    def test_load_defaults_loads_capital_rules(self):
        """import 4 条规则后 load_defaults 应载入 capital 类"""
        # import 触发 @register_capital
        from capital_control.capital_rules import (
            okx_live_rule,
            okx_simulated_rule,
            hyperliquid_rule,
            aster_rule,
        )
        registry = RuleRegistry()
        loaded = registry.load_defaults()
        assert loaded >= 4
        capital_rules = registry.get_enabled_rules(RuleCategory.CAPITAL)
        assert len(capital_rules) >= 4

    def test_priority_ordering(self):
        from capital_control.capital_rules import (
            okx_live_rule,
            okx_simulated_rule,
            hyperliquid_rule,
            aster_rule,
        )
        registry = RuleRegistry()
        registry.load_defaults()
        rules = registry.get_rules(RuleCategory.CAPITAL)
        priorities = [r.priority for r in rules]
        assert priorities == sorted(priorities)
        assert priorities[0] == 10  # okx_live
        assert priorities[-1] == 40  # aster

    def test_enable_disable(self):
        from capital_control.capital_rules import okx_live_rule
        registry = RuleRegistry()
        registry.load_defaults()
        # disable
        assert registry.disable("capital.okx_live") is True
        assert registry.get_rule("capital.okx_live").enabled is False
        # enable
        assert registry.enable("capital.okx_live") is True
        assert registry.get_rule("capital.okx_live").enabled is True

    def test_list_all_includes_capital(self):
        from capital_control.capital_rules import okx_live_rule
        registry = RuleRegistry()
        registry.load_defaults()
        all_cats = registry.list_all()
        assert "capital" in all_cats


# =========================================================================
# CapitalControlComponent 测试
# =========================================================================


def _mock_fetch_all_positions(equity_map=None):
    """构造 mock fetch_all_positions 返回值"""
    equity_map = equity_map or {}
    systems = {}
    for sys_name, eq in equity_map.items():
        systems[sys_name] = {
            "equity": eq,
            "extra": {
                "avail_balance": eq,
                "used_margin": 0.0,
                "account_type": _account_type_for_system(sys_name),
            },
        }
    return {"version": "1.1", "total_equity": sum(equity_map.values()), "systems": systems}


def _account_type_for_system(sys_name):
    mapping = {
        "v15_martin": "okx_live",
        "yijing_bcrm": "okx_simulated",
        "agent_a": "hyperliquid",
        "agent_b": "hyperliquid",
        "agent_c_memory": "hyperliquid",
        "three_screen": "aster",
    }
    return mapping.get(sys_name, "unknown")


class TestCapitalControlComponent:
    def test_import_and_init(self):
        """组件可导入和实例化"""
        from capital_control import CapitalControlComponent, CapitalMode
        c = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
        assert c is not None

    def test_evaluate_with_mock(self):
        """evaluate 使用 mock 数据返回 CapitalSnapshot"""
        from capital_control import CapitalControlComponent, CapitalMode

        mock_data = _mock_fetch_all_positions({
            "v15_martin": 260.0,
            "yijing_bcrm": 150.0,
            "agent_a": 60.0,
            "agent_b": 60.0,
            "agent_c_memory": 60.0,
            "three_screen": 200.0,
        })
        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            c = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            snap = c.evaluate()
        assert isinstance(snap, CapitalSnapshot)
        assert snap.health == HealthLevel.HEALTHY
        assert len(snap.by_system) == 6
        assert snap.total_equity == pytest.approx(790.0, abs=0.1)

    def test_fixed_mode_uses_static_budget(self):
        """FIXED 模式使用静态值"""
        from capital_control import CapitalControlComponent, CapitalMode

        c = CapitalControlComponent(mode=CapitalMode.FIXED)
        snap = c.evaluate(systems=["v15_martin"])
        assert snap.by_system["v15_martin"].total_eq == 260.0
        assert snap.by_system["v15_martin"].mode == CapitalMode.FIXED
        assert snap.by_system["v15_martin"].fallback_used is True

    def test_single_system_failure_doesnt_break_overall(self):
        """单系统失败不影响整体"""
        from capital_control import CapitalControlComponent, CapitalMode

        mock_data = _mock_fetch_all_positions({
            "v15_martin": 260.0,
            "yijing_bcrm": 150.0,
            "agent_a": 60.0,
            "agent_b": 60.0,
            "agent_c_memory": 60.0,
            "three_screen": 0.0,  # 降级
        })
        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            c = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            snap = c.evaluate()
        assert snap.health in (HealthLevel.WARNING, HealthLevel.CRITICAL)
        assert snap.by_system["three_screen"].fallback_used is True
        assert snap.by_system["v15_martin"].fallback_used is False

    def test_cache_hit(self):
        """60s 缓存命中"""
        from capital_control import CapitalControlComponent, CapitalMode

        call_count = [0]
        mock_data = _mock_fetch_all_positions({"v15_martin": 260.0})

        def _mock_fetch():
            call_count[0] += 1
            return mock_data

        with patch("unified_position_query.fetch_all_positions", side_effect=_mock_fetch):
            c = CapitalControlComponent(mode=CapitalMode.DYNAMIC, cache_ttl=60)
            snap1 = c.evaluate()
            snap2 = c.evaluate()
        # 第二次应命中缓存，不再调 fetch_all_positions
        assert snap1 is snap2 or snap1.timestamp == snap2.timestamp
        assert call_count[0] == 1

    def test_get_capital_advice(self):
        """get_capital_advice 返回正确结构"""
        from capital_control import CapitalControlComponent, CapitalMode

        mock_data = _mock_fetch_all_positions({"v15_martin": 260.0})
        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            c = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            c.evaluate()
        adv = c.get_capital_advice("v15_martin", action="HOLD")
        assert "allowed" in adv
        assert "margin_pressure" in adv
        assert "max_position_usdt" in adv
        assert adv["allowed"] is True

    def test_get_capital_advice_unknown_system(self):
        """未知系统返回 allowed=True"""
        from capital_control import CapitalControlComponent, CapitalMode

        mock_data = _mock_fetch_all_positions({"v15_martin": 260.0})
        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            c = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            c.evaluate()
        adv = c.get_capital_advice("nonexistent_system", action="HOLD")
        assert adv["allowed"] is True
        assert "not_in_capital_registry" in adv["reason"]

    def test_health_check(self):
        """health_check 返回组件状态"""
        from capital_control import CapitalControlComponent, CapitalMode

        mock_data = _mock_fetch_all_positions({"v15_martin": 260.0})
        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            c = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            c.evaluate()
        hc = c.health_check()
        assert hc["ok"] is True
        assert "health" in hc
        assert hc["registry_rules_loaded"] >= 4

    def test_get_snapshot(self):
        """get_snapshot 返回最近一次 evaluate 缓存"""
        from capital_control import CapitalControlComponent, CapitalMode

        mock_data = _mock_fetch_all_positions({"v15_martin": 260.0})
        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            c = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            snap = c.evaluate()
        assert c.get_snapshot() is snap

    def test_phase2_advice_blocks_raise_tp(self):
        """phase2 启用时 HIGH 压力阻断 RAISE_TP"""
        from capital_control import CapitalControlComponent, CapitalMode

        # 构造高压力数据（used_pct=90%）
        mock_data = {
            "systems": {
                "v15_martin": {
                    "equity": 100.0,
                    "extra": {"avail_balance": 10.0, "used_margin": 90.0, "account_type": "okx_live"},
                },
            }
        }
        config_path = _CORE.parent / "config" / "capital_control.json"
        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            c = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            # 手动开启 phase2
            c._config["phase2"]["enabled"] = True
            c.evaluate()
        adv = c.get_capital_advice("v15_martin", action="RAISE_TP")
        assert adv["allowed"] is False
        assert adv["margin_pressure"] == "HIGH"
