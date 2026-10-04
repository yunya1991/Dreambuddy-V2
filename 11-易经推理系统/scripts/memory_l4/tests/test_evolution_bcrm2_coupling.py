# -*- coding: utf-8 -*-
"""BCRM2.0 样本不足拦截 evolution 开仓 TDD 测试.

Spec: .trae/documents/pons_river_evolution_fix_spec.md 缺陷D (P1)

问题背景:
  BCRM2.0 样本不足时（bcrm2_min_samples=100）"跳过"BCRM2.0 推理，
  不是"拦截开仓"。evolution 信号仍能开仓，缺少耦合约束。

修复目标:
  1. BCRM2.0 跳过时（bcrm2_failed_coins 标记）拦截 evolution 开仓
  2. bcrm2_retry_interval_sec（24h）后自动解封
  3. FAIL-OPEN：检查异常不阻断

TDD 红: _evolution_build_position 入口无 BCRM2.0 耦合检查 → 测试期望拦截但实际继续执行
TDD 绿: 入口增加耦合检查，bcrm2_failed_coins 命中时 return 拦截
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


class TestEvolutionBCRM2Coupling:
    """BCRM2.0 样本不足拦截 evolution 开仓测试（缺陷D P1）."""

    @pytest.fixture
    def trader(self):
        """轻量 PollingTrader 实例（参考 test_p2_s4b_sl_floor.py 模式）."""
        from polling_trader import PollingTrader
        t = PollingTrader.__new__(PollingTrader)
        t.okx_client = MagicMock()
        t._log = MagicMock()
        t._current_fuse_action = None  # 不熔断
        t.bcrm2_failed_coins = {}  # BCRM2.0 失败记录
        t.bcrm2_retry_interval_sec = 86400  # 24h
        t.position_tracker = MagicMock()
        t.position_tracker.has_open_position.return_value = False
        return t

    def test_bcrm2_insufficient_blocks_evolution_open(self, trader):
        """bcrm2_failed_coins 命中且在 24h 内 → _evolution_build_position 应拦截 return.

        场景: BCRM2.0 样本不足跳过 → evolution 试图开仓 → 应被耦合检查拦截
        """
        symbol = "PONS"
        trader.bcrm2_failed_coins[symbol] = time.time()  # 刚失败，24h 内

        # 调用 _evolution_build_position
        result = trader._evolution_build_position(
            symbol=symbol, action="long", u_open=0.8,
            d_star=0.5, confidence=0.55, tier="probe",
        )
        # 应被拦截 return None
        assert result is None, "BCRM2.0 样本不足时应拦截 evolution 开仓"
        # 验证日志被调用，包含拦截关键词
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert any("BCRM2.0" in c and "拦截" in c for c in log_calls), \
            f"应记录 BCRM2.0 拦截日志, 实际: {log_calls}"

    def test_bcrm2_expired_not_block(self, trader):
        """bcrm2_failed_coins 有记录但超过 24h → 不拦截（继续执行后续逻辑）.

        场景: BCRM2.0 24h+1s 前失败 → 已解封 → evolution 可以开仓
        """
        symbol = "PONS"
        trader.bcrm2_failed_coins[symbol] = time.time() - 86401  # 24h+1s 前

        # 调用 _evolution_build_position
        # 不会被 BCRM2.0 耦合检查拦截（会继续执行后续逻辑，可能在其他地方 return）
        result = trader._evolution_build_position(
            symbol=symbol, action="long", u_open=0.8,
            d_star=0.5, confidence=0.55, tier="probe",
        )
        # 不应被 BCRM2.0 耦合检查拦截（日志中无 BCRM2.0 拦截）
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert not any("BCRM2.0" in c and "拦截" in c for c in log_calls), \
            "24h 后不应再拦截 evolution 开仓"

    def test_bcrm2_no_record_not_block(self, trader):
        """bcrm2_failed_coins 无记录 → 不拦截（正常开仓流程）."""
        symbol = "PONS"
        # bcrm2_failed_coins 为空（无失败记录）
        result = trader._evolution_build_position(
            symbol=symbol, action="long", u_open=0.8,
            d_star=0.5, confidence=0.55, tier="probe",
        )
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert not any("BCRM2.0" in c and "拦截" in c for c in log_calls), \
            "无 BCRM2.0 失败记录时不应拦截"

    def test_bcrm2_blocks_different_symbol_independent(self, trader):
        """BCRM2.0 拦截按 symbol 独立：PONS 被拦截，RIVER 不受影响.

        场景: PONS BCRM2.0 样本不足 → PONS evolution 被拦截
              RIVER 无 BCRM2.0 失败 → RIVER evolution 不被拦截
        """
        trader.bcrm2_failed_coins["PONS"] = time.time()
        # PONS 应被拦截
        result_pons = trader._evolution_build_position(
            symbol="PONS", action="long", u_open=0.8,
            d_star=0.5, confidence=0.55, tier="probe",
        )
        assert result_pons is None
        # RIVER 不应被拦截（bcrm2_failed_coins 中无 RIVER）
        trader._log.reset_mock()
        result_river = trader._evolution_build_position(
            symbol="RIVER", action="long", u_open=0.8,
            d_star=0.5, confidence=0.55, tier="probe",
        )
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert not any("BCRM2.0" in c and "拦截" in c for c in log_calls), \
            "RIVER 不应被 PONS 的 BCRM2.0 失败记录影响"

    def test_bcrm2_coupling_fail_open_on_exception(self, trader):
        """耦合检查异常时不阻断（FAIL-OPEN）.

        场景: bcrm2_failed_coins 被篡改为非法值 → 检查异常 → 不阻断开仓流程
        """
        symbol = "PONS"
        # 设置非法值触发异常
        trader.bcrm2_failed_coins = None  # None 没有 .get 方法

        # 调用 _evolution_build_position
        # FAIL-OPEN：异常不阻断，继续执行后续逻辑
        result = trader._evolution_build_position(
            symbol=symbol, action="long", u_open=0.8,
            d_star=0.5, confidence=0.55, tier="probe",
        )
        # 不应因异常崩溃（FAIL-OPEN），日志应记录异常告警
        log_calls = [str(call) for call in trader._log.call_args_list]
        # 应有 fail-open 相关日志
        assert any("fail-open" in c.lower() or "异常" in c for c in log_calls), \
            f"异常时应记录 FAIL-OPEN 告警, 实际: {log_calls}"
