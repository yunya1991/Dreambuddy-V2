# -*- coding: utf-8 -*-
"""TDD: evolution 路径 direction_state 闸门缺失修复测试。

根因：_evolution_build_position 由 KlineEventHandler 直接调用，
      完全绕过 _execute_trade 中的 direction_state 闸门。
      导致：
      - direction_state=FREEZE 时 evolution 仍可开仓（市场不明确应冻结）
      - direction_state=SHORT_ONLY 时 evolution 仍可做多（市场明确看跌应禁止做多）
      - direction_state=LONG_ONLY 时 evolution 仍可做空（市场明确看多应禁止做空）

修复：在 _evolution_build_position 早期（冷却期检查后、仓位计数前）添加
      direction_state 闸门，逻辑与 BCRM2.0 路径（L13982-L14012）对齐。
      FAIL-OPEN：异常时放行（不阻塞交易热路径）。
"""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MockFiveDomainState:
    """轻量 mock FiveDomainState，仅包含 direction_state 字段。"""
    direction_state: Dict[str, str] = field(default_factory=lambda: {
        "crypto_usdt": "NEUTRAL",
        "us_stock": "NEUTRAL",
        "precious_metal": "NEUTRAL",
    })
    war_state: Dict[str, str] = field(default_factory=lambda: {
        "crypto_usdt": "ALLOW",
        "us_stock": "ALLOW",
        "precious_metal": "ALLOW",
    })
    aggregate_position_cap_pct: Dict[str, float] = field(default_factory=lambda: {
        "crypto_usdt": 1.0,
        "us_stock": 1.0,
        "precious_metal": 1.0,
    })


class TestEvolutionDirectionGate:
    """验证 _evolution_build_position 中 direction_state 闸门生效。"""

    def _make_trader_with_dstate(self, dstate: str, cls: str = "crypto_usdt"):
        """创建带 direction_state 的 mock trader。"""
        from scripts.memory_l4.polling_trader import PollingTrader
        bot = PollingTrader.__new__(PollingTrader)

        # 设置 _five_domain_state_cache
        fds = MockFiveDomainState()
        fds.direction_state[cls] = dstate
        bot._five_domain_state_cache = fds

        # mock 基础方法
        bot._log = MagicMock()
        bot._coin_asset_class = MagicMock(return_value=cls)

        # mock position_tracker（无持仓、无冷却期）
        bot.position_tracker = MagicMock()
        bot.position_tracker.has_open_position = MagicMock(return_value=False)
        bot.position_tracker.is_in_cooldown = MagicMock(return_value=(False, ""))
        bot.position_tracker.all_open_positions = MagicMock(return_value=[])

        # mock 组合熔断
        bot._current_fuse_action = None

        # mock perf_tracker
        bot.perf_tracker = MagicMock()
        bot.perf_tracker.current_equity = 1000.0

        # mock SHORT_ONLY_BLACKLIST
        bot.SHORT_ONLY_BLACKLIST = set()

        # mock SUBPOOL_MAX_POSITIONS
        bot.SUBPOOL_MAX_POSITIONS = {"evolution": 5}
        bot.MAX_EVOLUTION_PROBE_POSITIONS = 4

        # mock COOLDOWN_SEC
        bot.COOLDOWN_SEC = 28800

        return bot

    # ===== FREEZE: 禁止开仓（市场不明确）=====

    def test_freeze_blocks_long(self):
        """direction_state=FREEZE 时禁止做多。"""
        bot = self._make_trader_with_dstate("FREEZE")
        result = bot._evolution_build_position("BTCUSDT", "long", 0.8, 0.02, 0.55, "standard")
        assert result is None, "FREEZE 状态不应开多仓"
        # 验证日志包含 FREEZE 拦截
        log_calls = [str(c) for c in bot._log.call_args_list]
        assert any("FREEZE" in c for c in log_calls), f"日志应包含 FREEZE 拦截: {log_calls}"

    def test_freeze_blocks_short(self):
        """direction_state=FREEZE 时禁止做空。"""
        bot = self._make_trader_with_dstate("FREEZE")
        result = bot._evolution_build_position("BTCUSDT", "short", 0.8, 0.02, 0.55, "standard")
        assert result is None, "FREEZE 状态不应开空仓"
        log_calls = [str(c) for c in bot._log.call_args_list]
        assert any("FREEZE" in c for c in log_calls), f"日志应包含 FREEZE 拦截: {log_calls}"

    # ===== SHORT_ONLY: 禁止做多，允许做空 =====

    def test_short_only_blocks_long(self):
        """direction_state=SHORT_ONLY 时禁止做多。"""
        bot = self._make_trader_with_dstate("SHORT_ONLY")
        result = bot._evolution_build_position("BTCUSDT", "long", 0.8, 0.02, 0.55, "standard")
        assert result is None, "SHORT_ONLY 状态不应开多仓"
        log_calls = [str(c) for c in bot._log.call_args_list]
        assert any("SHORT_ONLY" in c for c in log_calls), f"日志应包含 SHORT_ONLY 拦截: {log_calls}"

    def test_short_only_allows_short(self):
        """direction_state=SHORT_ONLY 时允许做空（不被 direction_state 拦截）。"""
        bot = self._make_trader_with_dstate("SHORT_ONLY")
        # 调用后应通过 direction_state 闸门（可能在后续步骤因其他原因 return，
        # 但不应在 direction_state 闸门处被拦截）
        bot._evolution_build_position("BTCUSDT", "short", 0.8, 0.02, 0.55, "standard")
        log_calls = [str(c) for c in bot._log.call_args_list]
        # 不应有 SHORT_ONLY 拦截日志（做空被放行）
        assert not any("SHORT_ONLY" in c and "禁止" in c for c in log_calls), \
            f"SHORT_ONLY 做空不应被拦截: {log_calls}"

    # ===== LONG_ONLY: 禁止做空，允许做多 =====

    def test_long_only_blocks_short(self):
        """direction_state=LONG_ONLY 时禁止做空。"""
        bot = self._make_trader_with_dstate("LONG_ONLY")
        result = bot._evolution_build_position("BTCUSDT", "short", 0.8, 0.02, 0.55, "standard")
        assert result is None, "LONG_ONLY 状态不应开空仓"
        log_calls = [str(c) for c in bot._log.call_args_list]
        assert any("LONG_ONLY" in c for c in log_calls), f"日志应包含 LONG_ONLY 拦截: {log_calls}"

    def test_long_only_allows_long(self):
        """direction_state=LONG_ONLY 时允许做多（不被 direction_state 拦截）。"""
        bot = self._make_trader_with_dstate("LONG_ONLY")
        bot._evolution_build_position("BTCUSDT", "long", 0.8, 0.02, 0.55, "standard")
        log_calls = [str(c) for c in bot._log.call_args_list]
        assert not any("LONG_ONLY" in c and "禁止" in c for c in log_calls), \
            f"LONG_ONLY 做多不应被拦截: {log_calls}"

    # ===== NEUTRAL: 多空均可 =====

    def test_neutral_allows_both(self):
        """direction_state=NEUTRAL 时多空均不被 direction_state 拦截。"""
        bot = self._make_trader_with_dstate("NEUTRAL")
        bot._evolution_build_position("BTCUSDT", "long", 0.8, 0.02, 0.55, "standard")
        log_calls_long = [str(c) for c in bot._log.call_args_list]
        assert not any("direction_state" in c and "禁止" in c for c in log_calls_long), \
            f"NEUTRAL 做多不应被拦截: {log_calls_long}"

        bot2 = self._make_trader_with_dstate("NEUTRAL")
        bot2._evolution_build_position("BTCUSDT", "short", 0.8, 0.02, 0.55, "standard")
        log_calls_short = [str(c) for c in bot2._log.call_args_list]
        assert not any("direction_state" in c and "禁止" in c for c in log_calls_short), \
            f"NEUTRAL 做空不应被拦截: {log_calls_short}"

    # ===== FAIL-OPEN: 异常时放行 =====

    def test_failopen_on_exception(self):
        """direction_state 读取异常时 FAIL-OPEN 放行（不阻塞交易）。"""
        bot = self._make_trader_with_dstate("NEUTRAL")
        # 模拟 direction_state 属性访问异常
        bot._five_domain_state_cache = MagicMock()
        bot._five_domain_state_cache.direction_state = MagicMock(
            side_effect=Exception("test exception")
        )
        # 不应在 direction_state 闸门处 return（FAIL-OPEN 放行）
        bot._evolution_build_position("BTCUSDT", "long", 0.8, 0.02, 0.55, "standard")
        log_calls = [str(c) for c in bot._log.call_args_list]
        # 应有 fail-open 日志
        assert any("fail" in c.lower() or "方向状态" in c for c in log_calls), \
            f"异常时应有 fail-open 日志: {log_calls}"
