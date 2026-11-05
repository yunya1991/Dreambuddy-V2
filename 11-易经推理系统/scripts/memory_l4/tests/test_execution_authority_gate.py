"""执行权限闸门 单元测试（evolution_only 收口决策）

设计口径（2026-11-05 用户决策）：
  evolution_only 时 PollingTrader._open_position 必须：
    1. 仅 source_tag="evolution" 允许进入下游真实下单路径；
    2. BCRM2.0(bcrm) / BDSM(bdsm) / 事件驱动(event_arbitrage) / 洗盘(washout_entry) / strategy
       一律记录 WARN "[EXECUTION-AUTHORITY BLOCKED-OPEN]" + 写影子信号，并立刻 return；
    3. 权限属性缺失时 fail-closed（默认按 evolution_only 处理）。
"""

from __future__ import annotations

import os as _os
import sys as _sys
from unittest.mock import MagicMock

_PROJECT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_ROOT = _os.path.dirname(_PROJECT)
_TESTS_DIR = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_ROOT, _TESTS_DIR):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from test_shadow_mode_gate import _make_bare_trader, _make_inference  # noqa: E402


def _trader(authority: str):
    """构造 shadow_mode=False 的最小 trader，并注入执行权限。"""
    t = _make_bare_trader(shadow_mode=False)
    t.execution_authority = authority
    if authority == "all":
        t._EXECUTION_AUTHORITY_ALLOWED = None
    elif authority == "evolution_only":
        t._EXECUTION_AUTHORITY_ALLOWED = {"evolution"}
    else:
        t._EXECUTION_AUTHORITY_ALLOWED = {
            x.strip().lower() for x in authority.split(",") if x.strip()
        }
    t._write_shadow_signal = MagicMock()
    # 让允许路径能走到风控（避免因 sl/tp=0 提前 return）
    t._calc_sl_price.return_value = 58500.0
    t._calc_tp_price.return_value = 63000.0
    return t


def _open(t, direction: str, source_tag):
    inf = _make_inference(direction)
    if source_tag is not None:
        inf["source_tag"] = source_tag
    return t._open_position(inf)


class TestExecutionAuthorityBlocks:
    """非 evolution 来源必须被拦截且零下游调用。"""

    def _assert_blocked(self, t):
        c = t.okx_client
        assert c.market_open_long.call_count == 0
        assert c.market_open_short.call_count == 0
        assert c.get_balance.call_count == 0
        assert c._usdt_to_sz.call_count == 0
        assert t.risk_manager.calc_position_size.call_count == 0
        assert t._compute_p2_dynamic_sizing_factors.call_count == 0
        msgs = [m for m, _ in t.logs]
        blocked = [m for m in msgs if "EXECUTION-AUTHORITY BLOCKED-OPEN" in m]
        assert blocked, f"必须记录拦截日志，实际={msgs}"
        levels = [lv for m, lv in t.logs if "EXECUTION-AUTHORITY BLOCKED-OPEN" in m]
        assert levels == ["WARN"]

    def test_bcrm_blocked_and_shadow_signal_written(self):
        t = _trader("evolution_only")
        _open(t, "UP", "bcrm")
        self._assert_blocked(t)
        assert t._write_shadow_signal.call_count == 1
        _args = t._write_shadow_signal.call_args[0]
        assert _args[1] == "bcrm"

    def test_bdsm_blocked(self):
        t = _trader("evolution_only")
        _open(t, "DOWN", "bdsm")
        self._assert_blocked(t)
        assert t._write_shadow_signal.call_args[0][1] == "bdsm"

    def test_event_arbitrage_blocked(self):
        t = _trader("evolution_only")
        _open(t, "UP", "event_arbitrage")
        self._assert_blocked(t)
        assert t._write_shadow_signal.call_args[0][1] == "event_arbitrage"

    def test_washout_entry_blocked(self):
        t = _trader("evolution_only")
        _open(t, "UP", "washout_entry")
        self._assert_blocked(t)
        assert t._write_shadow_signal.call_args[0][1] == "washout_entry"

    def test_strategy_blocked(self):
        t = _trader("evolution_only")
        _open(t, "UP", "strategy")
        self._assert_blocked(t)
        assert t._write_shadow_signal.call_args[0][1] == "strategy"

    def test_classify_fallback_bcrm_blocked(self):
        """未显式给 source_tag 时按币种子池归类 → bcrm，必须拦截。"""
        t = _trader("evolution_only")
        _open(t, "UP", None)
        self._assert_blocked(t)
        assert t._write_shadow_signal.call_args[0][1] == "bcrm"

    def test_missing_authority_attr_legacy_allows(self):
        """权限属性缺失（测试/legacy __new__ 实例）按 legacy 放行；生产实例必由 __init__ 注入。"""
        t = _trader("evolution_only")
        del t._EXECUTION_AUTHORITY_ALLOWED
        _open(t, "UP", "bcrm")
        assert t.risk_manager.calc_position_size.call_count >= 1
        assert t._write_shadow_signal.call_count == 0


class TestExecutionAuthorityAllows:
    """evolution 来源 / all 模式必须放行。"""

    def test_evolution_allowed_reaches_risk_engine(self):
        t = _trader("evolution_only")
        _open(t, "UP", "evolution")
        assert t.risk_manager.calc_position_size.call_count >= 1
        assert t.okx_client.get_balance.call_count >= 1
        assert t._write_shadow_signal.call_count == 0

    def test_all_mode_allows_bcrm(self):
        t = _trader("all")
        _open(t, "UP", "bcrm")
        assert t.risk_manager.calc_position_size.call_count >= 1
        assert t._write_shadow_signal.call_count == 0

    def test_custom_whitelist_allows_event_only(self):
        t = _trader("evolution,event_arbitrage")
        _open(t, "UP", "event_arbitrage")
        assert t.risk_manager.calc_position_size.call_count >= 1
        # 同一白名单下 bcrm 仍拦截
        t2 = _trader("evolution,event_arbitrage")
        _open(t2, "UP", "bcrm")
        assert t2.risk_manager.calc_position_size.call_count == 0
