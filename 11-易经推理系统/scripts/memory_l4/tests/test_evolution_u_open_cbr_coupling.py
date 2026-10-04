# -*- coding: utf-8 -*-
"""_evolution_build_position u_open/cbr_sim 耦合约束 TDD 测试.

Spec: .trae/documents/pons_river_evolution_fix_spec.md 缺陷E+F (P2)

问题背景:
  RIVER u_open=1.0（高开仓意愿）vs cbr_sim=0.3738（低相似度）矛盾。
  高 u_open + 低 cbr_sim 表示"基因组强烈想开但历史相似度不足"，
  缺少耦合约束导致低质量开仓。

修复目标:
  1. _evolution_build_position 入口增加 u_open/cbr_sim 耦合检查：
     u_open >= 1.0 且 cbr_sim < 0.4 → 拒绝开仓 return
  2. FAIL-OPEN：检查异常不阻断

TDD 红: 当前签名无 cbr_sim 参数 + 无耦合检查 → TypeError
TDD 绿: 签名增加 cbr_sim 参数 + 耦合检查落地
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


class TestEvolutionBuildPositionUOpenCbr:
    """_evolution_build_position 入口 u_open/cbr_sim 耦合检查测试."""

    @pytest.fixture
    def trader(self):
        """轻量 PollingTrader 实例（参考 test_evolution_bcrm2_coupling.py 模式）."""
        from polling_trader import PollingTrader
        t = PollingTrader.__new__(PollingTrader)
        t.okx_client = MagicMock()
        t._log = MagicMock()
        t._current_fuse_action = None  # 不熔断
        t.bcrm2_failed_coins = {}  # BCRM2.0 无失败记录
        t.bcrm2_retry_interval_sec = 86400
        t.position_tracker = MagicMock()
        t.position_tracker.has_open_position.return_value = False
        return t

    def test_high_u_open_low_cbr_blocks_evolution_open(self, trader):
        """u_open>=1.0 且 cbr_sim<0.4 → _evolution_build_position 应拦截 return None.

        场景（RIVER 案例）: u_open=1.0 + cbr_sim=0.3738 → 拒绝开仓
        """
        symbol = "RIVER"
        result = trader._evolution_build_position(
            symbol=symbol, action="long", u_open=1.0,
            d_star=0.5, confidence=0.55, tier="trend",
            cbr_sim=0.3738,
        )
        # 应被耦合检查拦截 return None
        assert result is None, "u_open=1.0 + cbr_sim=0.3738 时应拒绝 evolution 开仓"
        # 验证日志包含耦合拦截关键词
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert any("u_open" in c and ("cbr_sim" in c or "cbr" in c) for c in log_calls), \
            f"应记录 u_open/cbr_sim 耦合拦截日志, 实际: {log_calls}"

    def test_high_u_open_high_cbr_not_block(self, trader):
        """u_open>=1.0 且 cbr_sim>=0.4 → 不被耦合检查拦截（继续执行后续逻辑）.

        场景: u_open=1.0 + cbr_sim=0.6 → 相似度足够，允许开仓
        """
        symbol = "RIVER"
        # 调用 _evolution_build_position
        # 不会被 u_open/cbr_sim 耦合检查拦截（会继续执行后续逻辑）
        try:
            trader._evolution_build_position(
                symbol=symbol, action="long", u_open=1.0,
                d_star=0.5, confidence=0.55, tier="trend",
                cbr_sim=0.6,
            )
        except Exception:
            # 后续逻辑可能因 mock 不完整崩溃，但关键是没被耦合检查拦截
            pass
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert not any("u_open" in c and ("cbr_sim" in c or "cbr" in c) and "拦截" in c
                       for c in log_calls), \
            "cbr_sim=0.6 足够时不应拦截"

    def test_low_u_open_low_cbr_not_block(self, trader):
        """u_open<1.0 且 cbr_sim<0.4 → 不被耦合检查拦截（轻仓允许探索）.

        场景: u_open=0.4 (probe) + cbr_sim=0.37 → 轻仓试探允许
        """
        symbol = "PONS"
        try:
            trader._evolution_build_position(
                symbol=symbol, action="long", u_open=0.4,
                d_star=0.5, confidence=0.55, tier="probe",
                cbr_sim=0.37,
            )
        except Exception:
            pass
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert not any("u_open" in c and ("cbr_sim" in c or "cbr" in c) and "拦截" in c
                       for c in log_calls), \
            "u_open=0.4 轻仓时不应被耦合检查拦截"

    def test_coupling_fail_open_on_exception(self, trader):
        """耦合检查异常时不阻断（FAIL-OPEN）.

        场景: cbr_sim 传入非法值 → 检查异常 → 不阻断开仓流程
        """
        symbol = "RIVER"
        # cbr_sim 传入非法值（字符串），触发比较异常
        try:
            trader._evolution_build_position(
                symbol=symbol, action="long", u_open=1.0,
                d_star=0.5, confidence=0.55, tier="trend",
                cbr_sim="invalid",
            )
        except Exception:
            pass
        # 不应崩溃，日志应记录 fail-open 告警
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert any("fail-open" in c.lower() or "异常" in c for c in log_calls), \
            f"异常时应记录 FAIL-OPEN 告警, 实际: {log_calls}"

    def test_default_cbr_sim_byte_equivalent(self, trader):
        """cbr_sim 默认值 0.5（字节等价）：不传 cbr_sim 时不触发拦截.

        场景: 旧调用方式（不传 cbr_sim）→ cbr_sim=0.5 默认 → 不拦截
        确保开关关断时字节等价。
        """
        symbol = "RIVER"
        try:
            trader._evolution_build_position(
                symbol=symbol, action="long", u_open=1.0,
                d_star=0.5, confidence=0.55, tier="trend",
                # 不传 cbr_sim，使用默认值
            )
        except Exception:
            pass
        log_calls = [str(call) for call in trader._log.call_args_list]
        assert not any("u_open" in c and ("cbr_sim" in c or "cbr" in c) and "拦截" in c
                       for c in log_calls), \
            "cbr_sim 默认 0.5 时不应拦截（字节等价）"
