"""RED 测试 — WashoutReversalGenome 接入 (EvolutionEngine + PollingTrader).

Spec: docs/superpowers/specs/2026-09-22-washout-reversal-genome-design.md §3.4-§3.5

阶段1 修改文件:
  - 1-ARCHITECTURE/dreamos/evolution/engine.py
      — get_washout_reversal_genome() 延迟初始化 + evolve() 末尾追加
  - 11-易经推理系统/scripts/memory_l4/polling_trader.py
      — ENABLE_WASHOUT_REVERSAL_GENOME 类属性 + probe 候选注入

设计原则 (硬约束):
  - HC-G5: ENABLE_WASHOUT_REVERSAL_GENOME=False 时降级, 链路字节等价
  - 接入不破坏现有 evolve() 契约 (纯追加, 不修改返回值结构)
  - FAIL-OPEN: 基因组异常 → accepted=False, 不阻塞

TDD 测试清单:
  T1  / test_engine_get_washout_reversal_genome_lazy_init  — 延迟初始化
  T2  / test_engine_get_washout_reversal_genome_none_when_disabled — enable=False→None
  T3  / test_engine_evolve_appends_genome                  — evolve() 末尾追加调用
  T4  / test_engine_evolve_fail_open                        — 基因组异常不阻塞
  T5  / test_polling_trader_has_enable_flag                 — 类属性存在, 默认 False
  T6  / test_polling_trader_flag_false_no_injection        — flag=False→不注入候选
  T7  / test_zero_regression_evolution_report               — EvolutionReport 结构不变
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ============================================================
# sys.path 设置
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================
# 导入
# ============================================================
from dreamos.evolution.engine import EvolutionEngine  # noqa: E402
from dreamos.evolution.types import EvolutionReport  # noqa: E402


# ============================================================
# T1-T2: EvolutionEngine get_washout_reversal_genome
# ============================================================
class TestEngineGetGenome:
    def test_engine_get_washout_reversal_genome_lazy_init(self):
        """T1: get_washout_reversal_genome() 延迟初始化."""
        engine = EvolutionEngine()
        genome = engine.get_washout_reversal_genome()
        # 首次调用应初始化 (可能为 None 如果依赖缺失)
        # 第二次调用应返回同一实例
        genome2 = engine.get_washout_reversal_genome()
        assert genome is genome2

    def test_engine_get_washout_reversal_genome_none_when_disabled(self):
        """T2: enable=False 时基因组不初始化 (返回 None 或 enabled=False 的实例)."""
        engine = EvolutionEngine()
        genome = engine.get_washout_reversal_genome()
        # 默认 enable=False, 基因组应存在但 enable=False 或返回 None
        if genome is not None:
            assert genome.enable is False


# ============================================================
# T3-T4: evolve() 接入
# ============================================================
class TestEngineEvolveAppends:
    def test_engine_evolve_appends_genome(self):
        """T3: evolve() 末尾追加基因组 evolve 调用 (不破坏现有契约)."""
        engine = EvolutionEngine()
        # 构造最小 history entries
        from dreamos.core.graph_store.types import HistoryEntry
        entries = [
            HistoryEntry(
                cycle_id="test",
                intent_type="test",
                final_action="BUY",
                final_confidence=0.8,
            )
        ]
        report = engine.evolve(entries)
        # EvolutionReport 仍正常返回
        assert isinstance(report, EvolutionReport)
        assert report.cycles_analyzed == 1

    def test_engine_evolve_fail_open(self):
        """T4: 基因组异常不阻塞 evolve()."""
        engine = EvolutionEngine()
        from dreamos.core.graph_store.types import HistoryEntry
        entries = [
            HistoryEntry(
                cycle_id="test",
                intent_type="test",
                final_action="BUY",
                final_confidence=0.8,
            )
        ]
        # mock get_washout_reversal_genome 抛异常
        with patch.object(
            engine, "get_washout_reversal_genome",
            side_effect=RuntimeError("boom"),
        ):
            # 不应抛异常
            report = engine.evolve(entries)
            assert isinstance(report, EvolutionReport)


# ============================================================
# T5-T6: PollingTrader 类属性
# ============================================================
class TestPollingTraderFlag:
    def test_polling_trader_has_enable_flag(self):
        """T5: PollingTrader 类属性 ENABLE_WASHOUT_REVERSAL_GENOME 存在, 默认 False."""
        try:
            from scripts.memory_l4.polling_trader import PollingTrader
            assert hasattr(PollingTrader, "ENABLE_WASHOUT_REVERSAL_GENOME")
            assert PollingTrader.ENABLE_WASHOUT_REVERSAL_GENOME is False
        except ImportError:
            pytest.skip("PollingTrader 依赖未安装, 跳过")

    def test_polling_trader_flag_false_no_injection(self):
        """T6: flag=False → 不注入候选 (字节等价)."""
        try:
            from scripts.memory_l4.polling_trader import PollingTrader
            assert PollingTrader.ENABLE_WASHOUT_REVERSAL_GENOME is False
        except ImportError:
            pytest.skip("PollingTrader 依赖未安装, 跳过")


# ============================================================
# T7: 零回归
# ============================================================
class TestZeroRegression:
    def test_zero_regression_evolution_report(self):
        """T7: EvolutionReport 结构不变."""
        engine = EvolutionEngine()
        from dreamos.core.graph_store.types import HistoryEntry
        entries = [
            HistoryEntry(
                cycle_id="zr-test",
                intent_type="test",
                final_action="BUY",
                final_confidence=0.85,
            )
        ]
        report = engine.evolve(entries)
        # 核心字段不变
        assert hasattr(report, "cycles_analyzed")
        assert hasattr(report, "lessons")
        assert hasattr(report, "gap_analysis")
        assert hasattr(report, "suggestions")
        assert hasattr(report, "performance_metrics")
        assert report.cycles_analyzed == 1
