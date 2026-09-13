# -*- coding: utf-8 -*-
"""TDD: 战略层+策略层独立开仓测试。

测试三层信号组合 → 独立买卖信号 → 建仓。
模式对标 test_evolution_direction_gate.py 的 mock trader 方式。
"""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple


@dataclass
class MockFiveDomainState:
    """轻量 mock FiveDomainState。"""
    war_state: Dict[str, str] = field(default_factory=lambda: {
        "crypto_usdt": "ALLOW", "us_stock": "ALLOW", "precious_metal": "ALLOW",
    })
    direction_state: Dict[str, str] = field(default_factory=lambda: {
        "crypto_usdt": "NEUTRAL", "us_stock": "NEUTRAL", "precious_metal": "NEUTRAL",
    })
    aggregate_position_cap_pct: Dict[str, float] = field(default_factory=lambda: {
        "crypto_usdt": 1.0, "us_stock": 1.0, "precious_metal": 1.0,
    })
    position_mult: Dict[str, float] = field(default_factory=lambda: {
        "crypto_usdt": 1.0, "us_stock": 1.0, "precious_metal": 1.0,
    })
    allowed_style_mask: Dict[str, Dict[str, bool]] = field(default_factory=lambda: {
        "crypto_usdt": {"trend_follow": True, "breakout": True, "mean_revert": True,
                         "momentum": True, "volatility": True, "emergency": True},
    })
    five_scores: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        "crypto_usdt": {"dao": 70, "tian": 70, "di": 70, "jiang": 70, "fa": 70},
    })


@dataclass
class MockStrategySelection:
    """轻量 mock StrategySelection。"""
    strategy_type: str = "trend_follow"
    style_exposures: Dict[str, float] = field(default_factory=lambda: {
        "trend_follow": 0.8, "breakout": 0.3, "mean_revert": 0.2,
        "momentum": 0.4, "volatility": 0.1, "emergency": 0.5,
    })
    calibration_biases: Dict[str, Any] = field(default_factory=lambda: {"sl_tighten_factor": 1.0})


class TestComputeStrategyOpenSignal:
    """测试 _compute_strategy_open_signal 三层信号组合。"""

    def _make_trader(self, war_state="ALLOW", direction_state="NEUTRAL",
                     strategy_type="trend_follow", d_star="long", ri=0.65,
                     coin="BTC", cls="crypto_usdt"):
        from scripts.memory_l4.polling_trader import PollingTrader
        bot = PollingTrader.__new__(PollingTrader)

        # 战略层 cache
        fds = MockFiveDomainState()
        fds.war_state[cls] = war_state
        fds.direction_state[cls] = direction_state
        bot._five_domain_state_cache = fds

        # 策略层 mock
        bot._strategy_algo_layer = MagicMock()
        bot._strategy_algo_layer.cfg = MagicMock(enable_strategy_layer=True)
        selection = MockStrategySelection(strategy_type=strategy_type)
        bot._strategy_algo_layer.select = MagicMock(return_value=selection)

        # kline 结果缓存
        bot._last_kline_result_by_coin = {coin: {"d_star": d_star, "ri": ri}}

        # 基础方法
        bot._log = MagicMock()
        bot._coin_asset_class = MagicMock(return_value=cls)
        bot._last_regime = "TREND_BULL"

        return bot

    # ===== 层1：方向控制（direction_state 才控制是否开仓）=====

    def test_direction_state_freeze_blocks(self):
        """direction_state=FREEZE → None（市场不明确，禁止开仓）。"""
        bot = self._make_trader(direction_state="FREEZE")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None

    def test_war_state_freeze_does_not_block(self):
        """war_state=FREEZE 不拦截开仓（只影响仓位 cap_pct）。"""
        bot = self._make_trader(war_state="FREEZE", direction_state="NEUTRAL")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is not None  # war_state=FREEZE 不拦截，direction_state=NEUTRAL 放行

    def test_war_state_restrict_does_not_block(self):
        """war_state=RESTRICT 不拦截开仓（只影响仓位 cap_pct）。"""
        bot = self._make_trader(war_state="RESTRICT", direction_state="NEUTRAL")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is not None

    def test_direction_state_short_only_blocks_long(self):
        """direction_state=SHORT_ONLY + d_star=long → None。"""
        bot = self._make_trader(direction_state="SHORT_ONLY", d_star="long")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None

    def test_direction_state_long_only_blocks_short(self):
        """direction_state=LONG_ONLY + d_star=short → None。"""
        bot = self._make_trader(direction_state="LONG_ONLY", d_star="short")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None

    # ===== 层2：策略层检查 =====

    def test_heuristic_equilibrium_blocks(self):
        """strategy_type=heuristic_equilibrium → None（中性策略不开仓）。"""
        bot = self._make_trader(strategy_type="heuristic_equilibrium")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None

    def test_strategy_layer_disabled_blocks(self):
        """enable_strategy_layer=False → None。"""
        bot = self._make_trader()
        bot._strategy_algo_layer.cfg.enable_strategy_layer = False
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None

    # ===== 层3：技术信号检查 =====

    def test_d_star_wait_blocks(self):
        """d_star=WAIT → None。"""
        bot = self._make_trader(d_star="WAIT")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None

    def test_low_ri_blocks(self):
        """ri < 0.55 → None。"""
        bot = self._make_trader(ri=0.40)
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None

    def test_missing_kline_result_blocks(self):
        """kline 结果缓存缺失 → None。"""
        bot = self._make_trader()
        bot._last_kline_result_by_coin = {}
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None

    # ===== 三层全通过 =====

    def test_all_pass_long(self):
        """三层全通过 → (direction=UP, confidence, strategy_type)。"""
        bot = self._make_trader(d_star="long", ri=0.70, strategy_type="trend_follow")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is not None
        direction, confidence, stype = result
        assert direction == "UP"
        assert stype == "trend_follow"
        assert 0.40 <= confidence <= 0.95

    def test_all_pass_short(self):
        """三层全通过 → (direction=DOWN, confidence, strategy_type)。"""
        bot = self._make_trader(d_star="short", ri=0.70, strategy_type="breakout")
        result = bot._compute_strategy_open_signal("BTC")
        assert result is not None
        direction, confidence, stype = result
        assert direction == "DOWN"
        assert stype == "breakout"

    def test_short_only_allows_short(self):
        """direction_state=SHORT_ONLY + d_star=short → 允许做空。"""
        bot = self._make_trader(direction_state="SHORT_ONLY", d_star="short", ri=0.65)
        result = bot._compute_strategy_open_signal("BTC")
        assert result is not None
        assert result[0] == "DOWN"

    def test_long_only_allows_long(self):
        """direction_state=LONG_ONLY + d_star=long → 允许做多。"""
        bot = self._make_trader(direction_state="LONG_ONLY", d_star="long", ri=0.65)
        result = bot._compute_strategy_open_signal("BTC")
        assert result is not None
        assert result[0] == "UP"

    # ===== FAIL-OPEN =====

    def test_failopen_on_exception(self):
        """异常 → None（FAIL-OPEN）。"""
        bot = self._make_trader()
        bot._five_domain_state_cache = None  # 触发异常路径
        result = bot._compute_strategy_open_signal("BTC")
        assert result is None


class TestStrategyIndependentOpen:
    """测试 _strategy_independent_open 主开仓入口。"""

    def _make_trader_full(self, enable=True, war_state="ALLOW",
                          direction_state="NEUTRAL", has_position=False,
                          in_cooldown=False, fuse_block=False):
        from scripts.memory_l4.polling_trader import PollingTrader
        bot = PollingTrader.__new__(PollingTrader)

        # 开关
        bot.enable_strategy_independent_open = enable
        bot.STRATEGY_INDEPENDENT_COINS = frozenset({"BTC", "ETH", "SOL"})
        bot.STRATEGY_BASE_BUDGET_USDT = 200.0
        bot.MAX_STRATEGY_POSITIONS = 3
        bot.SUBPOOL_MAX_POSITIONS = {"bdsm": 3, "bcrm": 5, "evolution": 10, "strategy": 3}
        bot.COOLDOWN_SEC = 28800
        bot.SHORT_ONLY_BLACKLIST = set()

        # 战略层 cache
        fds = MockFiveDomainState()
        fds.war_state["crypto_usdt"] = war_state
        fds.direction_state["crypto_usdt"] = direction_state
        bot._five_domain_state_cache = fds

        # 策略层 mock
        bot._strategy_algo_layer = MagicMock()
        bot._strategy_algo_layer.cfg = MagicMock(enable_strategy_layer=True)
        selection = MockStrategySelection(strategy_type="trend_follow")
        bot._strategy_algo_layer.select = MagicMock(return_value=selection)

        # kline 结果缓存
        bot._last_kline_result_by_coin = {
            "BTC": {"d_star": "long", "ri": 0.65},
            "ETH": {"d_star": "short", "ri": 0.60},
            "SOL": {"d_star": "WAIT", "ri": 0.30},
        }

        # position_tracker mock
        bot.position_tracker = MagicMock()
        bot.position_tracker.has_open_position = MagicMock(return_value=has_position)
        bot.position_tracker.is_in_cooldown = MagicMock(return_value=(in_cooldown, ""))
        bot.position_tracker.all_open_positions = MagicMock(return_value=[])

        # okx_client mock
        bot.okx_client = MagicMock()
        bot.okx_client.get_ticker = MagicMock(return_value={"ok": True, "last": "50000.0"})

        # 组合熔断
        bot._current_fuse_action = MagicMock() if fuse_block else None
        if fuse_block:
            bot._current_fuse_action.block_new_open = True

        # 基础方法
        bot._log = MagicMock()
        bot._coin_asset_class = MagicMock(return_value="crypto_usdt")
        bot._last_regime = "TREND_BULL"
        bot._count_subpool_positions = MagicMock(return_value=0)

        # _open_position mock（不真正下单）
        bot._open_position = MagicMock(return_value=("ok", "test_order", 50000.0))

        return bot

    def test_switch_off(self):
        """开关关闭 → 不开仓。"""
        bot = self._make_trader_full(enable=False)
        bot._strategy_independent_open()
        bot._open_position.assert_not_called()

    def test_switch_on_triggers_open(self):
        """开关开启 + 三层信号通过 → 调用 _open_position。"""
        bot = self._make_trader_full(enable=True)
        bot._strategy_independent_open()
        bot._open_position.assert_called()
        # 验证 inference 包含 source_tag="strategy"
        call_args = bot._open_position.call_args
        inference = call_args[0][0]
        assert inference.get("source_tag") == "strategy"

    def test_fuse_blocks(self):
        """组合熔断 → 不开仓。"""
        bot = self._make_trader_full(fuse_block=True)
        bot._strategy_independent_open()
        bot._open_position.assert_not_called()

    def test_has_position_blocks(self):
        """已有持仓 → 跳过该币种。"""
        bot = self._make_trader_full(has_position=True)
        bot._strategy_independent_open()
        bot._open_position.assert_not_called()

    def test_cooldown_blocks(self):
        """冷却期内 → 跳过。"""
        bot = self._make_trader_full(in_cooldown=True)
        bot._strategy_independent_open()
        bot._open_position.assert_not_called()

    def test_subpool_full_blocks(self):
        """子池已满 → 不开仓。"""
        bot = self._make_trader_full()
        bot._count_subpool_positions = MagicMock(return_value=3)
        bot._strategy_independent_open()
        bot._open_position.assert_not_called()

    def test_position_calculation(self):
        """仓位 = cap_pct × position_mult × base_budget。"""
        bot = self._make_trader_full()
        # cap=0.5, mult=0.8, base=200 → 80
        bot._five_domain_state_cache.aggregate_position_cap_pct["crypto_usdt"] = 0.5
        bot._five_domain_state_cache.position_mult["crypto_usdt"] = 0.8
        bot._strategy_independent_open()
        call_args = bot._open_position.call_args
        inference = call_args[0][0]
        # 验证 reason 中包含 cap 和 mult 信息
        assert "cap=0.50" in inference.get("reason", "") or "cap=0.5" in inference.get("reason", "")

    def test_failopen_top_level(self):
        """顶层异常 → FAIL-OPEN 不崩溃。"""
        bot = self._make_trader_full()
        bot._count_subpool_positions = MagicMock(side_effect=Exception("test"))
        # 不应抛异常
        bot._strategy_independent_open()
