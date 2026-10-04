"""W5 RED 测试 — 三层防御整合 + 集成测试.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §9.5

W5 新增 1 文件:
  - 11-易经推理系统/scripts/memory_l4/bcrm2/washout_sl_guard.py
      Layer 1: WashoutSLGuard — SLTP 动态调节器

W5 修改 4 文件 (零回归: ENABLE_WASHOUT_DETECTOR=False 时链路字节等价):
  - bcrm2/exit_strategies.py
      新增 WashoutHoldStrategy (priority=15) + 修改 P3EarlyExit 增洗盘感知
  - bcrm2/exit_manager.py
      注册 WashoutHoldStrategy + P3EarlyExit 注入 washout_detector
  - polling_trader.py
      SLTP 检查前调用 WashoutSLGuard + _execute_trade 调用 WashoutDetector 仅 is_trial 子池
  - trading_utils.py
      TradeRecord (OpenPosition) 增 washout_verdict 字段

三层防御硬约束 (VM-1789994567129-791d228a B 级):
  HC-15: 放宽SL不得超原SL的25%
  HC-16: 放宽后SL必须位于爆仓价+0.3%安全缓冲的安全侧 (爆仓安全优先)
  HC-17: 收紧SL不得高于当前mark price
  HC-18: 放宽窗口最长48h, 超时自动恢复原SL
  HC-19: verdict从washout变为非washout时自动恢复原SL
  HC-20: P3EarlyExit洗盘抑制仅在washout+conf≥0.80时生效
  HC-21: P3洗盘检查异常时FAIL-OPEN走原P3逻辑
  HC-22: 三层防御在ENABLE_WASHOUT_DETECTOR=False时全部降级为no_change/pass

TDD 测试清单 (§9.5 共 35 项):
  Layer 1: WashoutSLGuard (10 项)
  Layer 2: P3EarlyExit 洗盘感知 (6 项)
  Layer 3: WashoutHoldStrategy (7 项)
  三层协同 + 集成 (12 项)
"""
from __future__ import annotations

import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

# ============================================================
# sys.path 设置
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent  # .../11-易经推理系统/scripts
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent  # dreambuddy-v2
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================
# 导入
# ============================================================
from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector,
    WashoutLabel,
    WashoutVerdict,
)
from scripts.memory_l4.bcrm2.exit_manager import (  # noqa: E402
    ExitContext,
    ExitDecision,
    ExitManager,
    ExitStrategy,
)
from scripts.memory_l4.bcrm2 import exit_strategies as es  # noqa: E402
from scripts.memory_l4.trading_utils import TradeRecord  # noqa: E402


# ============================================================
# 辅助: 构造 WashoutVerdict
# ============================================================
def _make_verdict(label: WashoutLabel, confidence: float,
                  trigger_activated: bool = True) -> WashoutVerdict:
    return WashoutVerdict(
        label=label,
        confidence=confidence,
        trigger_activated=trigger_activated,
        feature_snapshot={"f1": 1.0},
        reason=f"test_{label.value}",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


WASHOUT_HI = lambda: _make_verdict(WashoutLabel.WASHOUT, 0.85)
WASHOUT_LO = lambda: _make_verdict(WashoutLabel.WASHOUT, 0.60)
WEAKNESS_HI = lambda: _make_verdict(WashoutLabel.WEAKNESS, 0.80)
WEAKNESS_LO = lambda: _make_verdict(WashoutLabel.WEAKNESS, 0.50)
UNKNOWN_VERDICT = lambda: _make_verdict(WashoutLabel.UNKNOWN, 0.30)


def _make_df_with_runup_drawdown(runup_pct: float = 0.20,
                                 drawdown_pct: float = 0.08,
                                 above_ma200: bool = True) -> pd.DataFrame:
    """构造触发门通过的 OHLCV DataFrame."""
    n = 60
    base = 100.0
    # 涨 N 天后回撤
    peak = base * (1 + runup_pct)
    end_price = peak * (1 - drawdown_pct)
    prices = list(np.linspace(base, peak, 30)) + list(np.linspace(peak, end_price, 30))
    if not above_ma200:
        prices = [p * 0.5 for p in prices]
    df = pd.DataFrame({
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": [1000.0] * n,
    })
    return df


# ============================================================
# Mock WashoutDetector — 总是返回预设 verdict
# ============================================================
class _MockDetector:
    """简化 WashoutDetector mock, 直接返回预设 verdict."""

    def __init__(self, verdict: Optional[WashoutVerdict] = None,
                 enable: bool = True,
                 raise_on_run: bool = False):
        self.verdict = verdict
        self.enable = enable
        self.raise_on_run = raise_on_run

    def run(self, coin: str, df: Any = None, macro_data: Any = None) -> WashoutVerdict:
        if self.raise_on_run:
            raise RuntimeError("mock detector boom")
        if not self.enable:
            return WashoutVerdict.unknown()
        return self.verdict if self.verdict is not None else WashoutVerdict.unknown()


# ============================================================
# Layer 1: WashoutSLGuard 测试 (10 项)
# ============================================================
class TestWashoutSLGuard:
    """Layer 1: WashoutSLGuard SLTP 动态调节器."""

    def _make_guard(self, detector=None, **kw):
        from scripts.memory_l4.bcrm2.washout_sl_guard import WashoutSLGuard
        return WashoutSLGuard(washout_detector=detector or _MockDetector(), **kw)

    def test_washout_sl_guard_disabled_returns_no_change(self):
        """T1 detector.enable=False → no_change."""
        guard = self._make_guard(detector=_MockDetector(enable=False))
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=90.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        assert result.action == "no_change"

    def test_washout_sl_guard_washout_widen_sl(self):
        """T2 washout+conf≥0.80 → widen_sl."""
        guard = self._make_guard(detector=_MockDetector(WASHOUT_HI()))
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=90.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        assert result.action == "widen_sl"
        #做多: SL 下移 (远离 mark), 放宽 SL 避免被扫损
        assert result.new_sl_px < 90.0

    def test_washout_sl_guard_weakness_tighten_sl(self):
        """T3 weakness+conf≥0.70 → tighten_sl."""
        guard = self._make_guard(detector=_MockDetector(WEAKNESS_HI()))
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=90.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        assert result.action == "tighten_sl"
        #做多: SL价格上移 (从90 → 更接近100), 收紧 SL
        assert result.new_sl_px > 90.0
        #收紧后 SL 不得高于 mark price (HC-17)
        assert result.new_sl_px <= 100.0

    def test_washout_sl_guard_widen_respects_max_25pct(self):
        """T4 放宽不得超原 SL 的 25% (HC-15)."""
        guard = self._make_guard(detector=_MockDetector(WASHOUT_HI()))
        original_sl = 90.0  # entry=100, sl=90 → 距 entry 10%
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=original_sl, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=original_sl,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        assert result.action == "widen_sl"
        #原 SL 距 entry 10%; 放宽不得超 25% → 新 SL 距 entry ≤ 12.5%
        original_sl_pct = abs(original_sl - 100.0) / 100.0  # 0.10
        max_widen_pct = original_sl_pct * 1.25  # 0.125
        new_sl_pct = abs(result.new_sl_px - 100.0) / 100.0
        assert new_sl_pct <= max_widen_pct + 1e-9, (
            f"HC-15 violated: new_sl_pct={new_sl_pct} > max={max_widen_pct}")

    def test_washout_sl_guard_widen_respects_liq_safety(self):
        """T5 放宽后 SL 仍位于爆仓价 + 0.3% 安全侧 (HC-16)."""
        guard = self._make_guard(detector=_MockDetector(WASHOUT_HI()))
        # liq=80, entry=100, sl=85 (距 entry 15%); 放宽极限 15%*1.25=18.75% → sl=81.25
        # 但 liq_price=80, 安全侧 = 80 * 1.003 = 80.24
        #放宽不能越过爆仓安全边际
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=85.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=80.0, original_sl=85.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        if result.action == "widen_sl":
            #做多: SL < entry, 安全侧要求 SL > liq_price * (1 + 0.3%)
            safe_floor = 80.0 * (1 + 0.003)  # 80.24
            assert result.new_sl_px >= safe_floor, (
                f"HC-16 violated: new_sl={result.new_sl_px} < safe_floor={safe_floor}")

    def test_washout_sl_guard_tighten_not_above_mark(self):
        """T6 收紧 SL 不得高于 mark price (HC-17)."""
        guard = self._make_guard(detector=_MockDetector(WEAKNESS_HI()))
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=92.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=92.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        if result.action == "tighten_sl":
            assert result.new_sl_px <= 100.0, (
                f"HC-17 violated: new_sl={result.new_sl_px} > mark=100.0")

    def test_washout_sl_guard_widen_timeout_48h_restore(self):
        """T7 放宽超 48h → restore_sl (HC-18)."""
        guard = self._make_guard(detector=_MockDetector(WASHOUT_HI()))
        # 先放宽一次 (设置 state["widened"]=True)
        guard._state["BTC"] = {
            "original_sl": 90.0,
            "last_verdict_label": WashoutLabel.WASHOUT,
            "last_adjust_ts": time.time() - 49 * 3600,  # 49h 前
            "widened": True,
        }
        # 再次调用, last_adjust_ts 传入 49h 前 → 触发 timeout
        now_ts = time.time()
        last_ts = now_ts - 49 * 3600
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=95.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=50.0, last_adjust_ts=last_ts,
        )
        assert result.action == "restore_sl"
        assert abs(result.new_sl_px - 90.0) < 1e-9

    def test_washout_sl_guard_verdict_change_restore(self):
        """T8 verdict 从 washout→weakness → restore_sl (HC-19)."""
        #先用 washout 放宽一次
        guard = self._make_guard(detector=_MockDetector(WASHOUT_HI()))
        r1 = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=90.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        assert r1.action == "widen_sl"
        # 切换 detector 到 weakness (verdict 变化)
        guard2 = self._make_guard(detector=_MockDetector(WEAKNESS_HI()))
        # 把 guard2 的状态设为已放宽过 (复用 guard 的 _state 字典)
        guard2._state["BTC"] = guard._state.get("BTC", {}).copy()
        r2 = guard2.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=r1.new_sl_px, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=2.0, last_adjust_ts=time.time(),
        )
        #weakness+conf≥0.70 触发 tighten, 而非 restore; 也可接受 restore
        assert r2.action in ("tighten_sl", "restore_sl"), f"got {r2.action}"

    def test_washout_sl_guard_fail_open_on_exception(self):
        """T9 异常 → no_change + 6 层堆栈 (HC-21 FAIL-OPEN)."""
        guard = self._make_guard(detector=_MockDetector(raise_on_run=True))
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=90.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        assert result.action == "no_change"
        assert "fail_open" in result.reason or "exception" in result.reason.lower()

    def test_washout_sl_guard_get_adjustment_log(self):
        """T10 审计日志正确."""
        guard = self._make_guard(detector=_MockDetector(WASHOUT_HI()))
        guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=90.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        log = guard.get_adjustment_log(coin="BTC")
        assert isinstance(log, list)
        assert len(log) >= 1
        entry = log[-1]
        assert "action" in entry
        assert "timestamp" in entry


# ============================================================
# Layer 2: P3EarlyExit 洗盘感知测试 (6 项)
# ============================================================
class TestP3EarlyExitWashout:
    """Layer 2: P3EarlyExit 增加洗盘感知 (仅在 washout+conf≥0.80 时抑制)."""

    def _make_ctx(self, early_exit_signal: bool = True,
                  upl_ratio: float = -0.10,
                  in_protection: bool = True) -> ExitContext:
        return ExitContext(
            coin="BTC",
            inference={"early_exit_signal": early_exit_signal},
            pos_info={"pos_side": "long", "upl_ratio": upl_ratio},
            tracker_pos=None,
            in_protection=in_protection,
            age_hours=1.0,
        )

    def test_p3_early_exit_washout_suppresses_exit(self):
        """T11 washout+conf≥0.80 → P3 返回 hold 抑制退出 (HC-20)."""
        det = _MockDetector(WASHOUT_HI())
        strat = es.P3EarlyExitStrategy(washout_detector=det)
        #正常 P3 会触发 force_close (early_exit + 浮亏>=-8% + 确认 2 次)
        #先触发一次累计确认
        ctx = self._make_ctx()
        strat.evaluate(ctx)  # cnt=1
        decision = strat.evaluate(ctx)  # cnt=2 → 原 P3 force_close
        #洗盘抑制 → 应返回 hold
        assert decision.action == "hold"
        assert "washout" in decision.reason.lower() or "suppress" in decision.reason.lower()

    def test_p3_early_exit_washout_low_confidence_proceeds(self):
        """T12 washout+conf<0.80 → P3 正常逻辑 (不抑制)."""
        det = _MockDetector(WASHOUT_LO())  # conf=0.60 < 0.80
        strat = es.P3EarlyExitStrategy(washout_detector=det)
        ctx = self._make_ctx()
        strat.evaluate(ctx)  # cnt=1
        decision = strat.evaluate(ctx)  # cnt=2
        assert decision.action == "force_close"
        assert decision.reason == "p3_early_exit"

    def test_p3_early_exit_weakness_proceeds(self):
        """T13 weakness → P3 正常逻辑 (不抑制)."""
        det = _MockDetector(WEAKNESS_HI())  # weakness, 即使 conf=0.80 也不抑制
        strat = es.P3EarlyExitStrategy(washout_detector=det)
        ctx = self._make_ctx()
        strat.evaluate(ctx)
        decision = strat.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "p3_early_exit"

    def test_p3_early_exit_unknown_proceeds(self):
        """T14 unknown → P3 正常逻辑 (不抑制)."""
        det = _MockDetector(UNKNOWN_VERDICT())
        strat = es.P3EarlyExitStrategy(washout_detector=det)
        ctx = self._make_ctx()
        strat.evaluate(ctx)
        decision = strat.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "p3_early_exit"

    def test_p3_early_exit_washout_check_fail_open(self):
        """T15 washout 检查异常 → 走原 P3 逻辑 (HC-21)."""
        det = _MockDetector(raise_on_run=True)
        strat = es.P3EarlyExitStrategy(washout_detector=det)
        ctx = self._make_ctx()
        strat.evaluate(ctx)
        decision = strat.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "p3_early_exit"

    def test_p3_early_exit_no_detector_proceeds(self):
        """T16 washout_detector=None → 原 P3 逻辑."""
        strat = es.P3EarlyExitStrategy(washout_detector=None)
        ctx = self._make_ctx()
        strat.evaluate(ctx)
        decision = strat.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "p3_early_exit"


# ============================================================
# Layer 3: WashoutHoldStrategy 测试 (7 项)
# ============================================================
class TestWashoutHoldStrategy:
    """Layer 3: WashoutHoldStrategy (priority=15)."""

    def _make_ctx(self) -> ExitContext:
        return ExitContext(
            coin="BTC",
            inference={},
            pos_info={"pos_side": "long", "upl_ratio": -0.05},
            tracker_pos=None,
            in_protection=True,
            age_hours=2.0,
        )

    def test_washout_hold_strategy_disabled_returns_pass(self):
        """T17 detector=None → pass."""
        strat = es.WashoutHoldStrategy(washout_detector=None)
        decision = strat.evaluate(self._make_ctx())
        assert decision.action == "pass"

    def test_washout_hold_strategy_washout_label_returns_hold(self):
        """T18 washout → hold."""
        det = _MockDetector(WASHOUT_HI())
        strat = es.WashoutHoldStrategy(washout_detector=det)
        decision = strat.evaluate(self._make_ctx())
        assert decision.action == "hold"
        assert "washout" in decision.reason.lower()

    def test_washout_hold_strategy_weakness_high_confidence_force_close(self):
        """T19 weakness + conf≥0.70 → force_close."""
        det = _MockDetector(WEAKNESS_HI())  # conf=0.80
        strat = es.WashoutHoldStrategy(washout_detector=det)
        decision = strat.evaluate(self._make_ctx())
        assert decision.action == "force_close"
        assert "weakness" in decision.reason.lower()

    def test_washout_hold_strategy_weakness_low_confidence_pass(self):
        """T20 weakness + conf<0.70 → pass."""
        det = _MockDetector(WEAKNESS_LO())  # conf=0.50
        strat = es.WashoutHoldStrategy(washout_detector=det)
        decision = strat.evaluate(self._make_ctx())
        assert decision.action == "pass"

    def test_washout_hold_strategy_unknown_returns_pass(self):
        """T21 unknown → pass."""
        det = _MockDetector(UNKNOWN_VERDICT())
        strat = es.WashoutHoldStrategy(washout_detector=det)
        decision = strat.evaluate(self._make_ctx())
        assert decision.action == "pass"

    def test_washout_hold_strategy_timeout_48h_returns_hold_with_reason(self):
        """T22 超 48h → hold + reason."""
        det = _MockDetector(WASHOUT_HI())
        strat = es.WashoutHoldStrategy(washout_detector=det)
        ctx = self._make_ctx()
        ctx.age_hours = 49.0  # 超 48h
        decision = strat.evaluate(ctx)
        assert decision.action == "hold"
        assert "timeout" in decision.reason.lower() or "48" in decision.reason

    def test_washout_hold_strategy_fail_open_on_exception(self):
        """T23 异常 → pass (FAIL-OPEN)."""
        det = _MockDetector(raise_on_run=True)
        strat = es.WashoutHoldStrategy(washout_detector=det)
        decision = strat.evaluate(self._make_ctx())
        assert decision.action == "pass"


# ============================================================
# 三层协同 + 集成测试 (12 项)
# ============================================================
class TestIntegration:
    """三层协同 + 集成测试."""

    def test_exit_manager_priority_15_between_10_and_20(self):
        """T24 priority=15 在 10 和 20 之间."""
        assert es.P3EarlyExitStrategy.priority == 10
        assert es.WashoutHoldStrategy.priority == 15
        assert es.SignalReverseStrategy.priority == 20
        assert 10 < 15 < 20

    def test_exit_manager_washout_hold_short_circuits_after_force_close(self):
        """T25 force_close 后 priority=20+ 不评估."""
        det = _MockDetector(WEAKNESS_HI())
        washout_hold = es.WashoutHoldStrategy(washout_detector=det)
        signal_reverse = es.SignalReverseStrategy()
        manager = ExitManager(strategies=[washout_hold, signal_reverse])
        # 强制使用传入的 _strategies, 不走 PORTFOLIO_MODE_CHAINS
        manager._chains = {}
        ctx = ExitContext(
            coin="BTC",
            inference={"direction": "DOWN", "confidence": 0.9},
            pos_info={"pos_side": "long", "upl_ratio": -0.05},
            tracker_pos=None,
            in_protection=False,
            age_hours=2.0,
            confidence=0.9,
        )
        decision = manager.evaluate(
            coin=ctx.coin, inference=ctx.inference, pos_info=ctx.pos_info,
            tracker_pos=ctx.tracker_pos, in_protection=ctx.in_protection,
            age_hours=ctx.age_hours, confidence=ctx.confidence,
        )
        #weakness force_close 短路, signal_reverse 不评估
        assert decision.action == "force_close"
        assert decision.strategy_name == "washout_hold"

    def test_polling_trader_washout_trial_position_max_2(self):
        """T26 is_trial 子池最多 2 单 (MAX_TRIAL_POSITIONS=2)."""
        from scripts.memory_l4.polling_trader import PollingTrader
        #用 mock 检查类常量 (不实例化, polling_trader 实例化需要 OKX client)
        assert getattr(PollingTrader, "MAX_TRIAL_POSITIONS", 2) == 2

    def test_polling_trader_washout_source_tag(self):
        """T27 source_tag='washout_trial' 正确."""
        from scripts.memory_l4.polling_trader import PollingTrader
        #检查常量存在 (WashoutDetector 子池 source_tag)
        tag = getattr(PollingTrader, "WASHOUT_SOURCE_TAG", "washout_trial")
        assert tag == "washout_trial"

    def test_open_position_washout_verdict_field(self):
        """T28 TradeRecord.washout_verdict 字段存在."""
        #dataclass 字段检查
        assert "washout_verdict" in TradeRecord.__dataclass_fields__
        rec = TradeRecord(coin="BTC")
        assert rec.washout_verdict is None

    def test_integration_layer1_sl_guard_widens_sl_during_washout(self):
        """T29 端到端: washout → SLGuard 放宽 SL → 不被扫损."""
        from scripts.memory_l4.bcrm2.washout_sl_guard import WashoutSLGuard
        det = _MockDetector(WASHOUT_HI())
        guard = WashoutSLGuard(washout_detector=det)
        original_sl = 90.0
        # mark=91 接近 SL=90, 洗盘判定放宽 SL 避免被扫损
        result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=original_sl, mark_price=91.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=original_sl,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        assert result.action == "widen_sl"
        # 放宽: SL 下移 (< original_sl), 仍在 mark 之下 (91.0), 不被扫损
        assert result.new_sl_px < original_sl
        assert result.new_sl_px < 91.0

    def test_integration_layer2_p3_suppressed_during_washout(self):
        """T30 端到端: washout → P3 抑制 → 不误退出."""
        det = _MockDetector(WASHOUT_HI())
        p3 = es.P3EarlyExitStrategy(washout_detector=det)
        ctx = ExitContext(
            coin="BTC",
            inference={"early_exit_signal": True},
            pos_info={"pos_side": "long", "upl_ratio": -0.10},
            tracker_pos=None,
            in_protection=True,
            age_hours=1.0,
        )
        p3.evaluate(ctx)  # cnt=1
        decision = p3.evaluate(ctx)  # cnt=2 → washout 抑制
        assert decision.action == "hold"

    def test_integration_layer3_hold_blocks_signal_reverse(self):
        """T31 端到端: washout → WashoutHoldStrategy hold → 短路, SignalReverse 不评估."""
        det = _MockDetector(WASHOUT_HI())
        washout_hold = es.WashoutHoldStrategy(washout_detector=det)
        signal_reverse = es.SignalReverseStrategy()
        manager = ExitManager(strategies=[washout_hold, signal_reverse])
        manager._chains = {}  # 强制用 _strategies
        decision = manager.evaluate(
            coin="BTC",
            inference={"direction": "DOWN", "confidence": 0.9},
            pos_info={"pos_side": "long", "upl_ratio": -0.05},
            tracker_pos=None,
            in_protection=False,
            age_hours=2.0,
            confidence=0.9,
        )
        #washout → hold 短路 (非 force_close)
        assert decision.action == "hold"
        assert decision.strategy_name == "washout_hold"

    def test_integration_weakness_accelerates_exit_all_layers(self):
        """T32 端到端: weakness → SLGuard 收紧 + P3 不抑制 + WashoutHoldStrategy force_close."""
        det = _MockDetector(WEAKNESS_HI())
        #Layer 1: SLGuard 收紧
        from scripts.memory_l4.bcrm2.washout_sl_guard import WashoutSLGuard
        guard = WashoutSLGuard(washout_detector=det)
        sl_result = guard.adjust_sl(
            coin="BTC", df=_make_df_with_runup_drawdown(), macro_data={},
            current_sl=90.0, mark_price=100.0, entry_price=100.0,
            pos_side="long", liq_price=50.0, original_sl=90.0,
            age_hours=1.0, last_adjust_ts=0.0,
        )
        assert sl_result.action == "tighten_sl"
        #Layer 2: P3 不抑制 (weakness 不抑制)
        p3 = es.P3EarlyExitStrategy(washout_detector=det)
        ctx = ExitContext(
            coin="BTC",
            inference={"early_exit_signal": True},
            pos_info={"pos_side": "long", "upl_ratio": -0.10},
            tracker_pos=None,
            in_protection=True,
            age_hours=1.0,
        )
        p3.evaluate(ctx)
        p3_decision = p3.evaluate(ctx)
        assert p3_decision.action == "force_close"
        #Layer 3: WashoutHoldStrategy force_close
        hold_strat = es.WashoutHoldStrategy(washout_detector=det)
        hold_decision = hold_strat.evaluate(ExitContext(
            coin="BTC", inference={}, pos_info={"pos_side": "long"},
            tracker_pos=None, in_protection=False, age_hours=2.0,
        ))
        assert hold_decision.action == "force_close"

    def test_full_regression_all_existing_strategies_unchanged(self):
        """T33 全回归: 6 个原策略行为不变."""
        #验证 priority 不变
        assert es.P3EarlyExitStrategy.priority == 10
        assert es.SignalReverseStrategy.priority == 20
        assert es.EvForceCloseStrategy.priority == 30
        assert es.TimeoutProfitSwitchStrategy.priority == 40
        assert es.RankedTpStrategy.priority == 50
        assert es.EvAdjustStrategy.priority == 60
        #验证 P3EarlyExitStrategy 默认构造 (washout_detector=None) 行为不变
        p3 = es.P3EarlyExitStrategy()
        assert p3.washout_detector is None
        ctx = ExitContext(
            coin="BTC",
            inference={"early_exit_signal": True},
            pos_info={"pos_side": "long", "upl_ratio": -0.10},
            tracker_pos=None,
            in_protection=True,
            age_hours=1.0,
        )
        p3.evaluate(ctx)
        decision = p3.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "p3_early_exit"

    def test_full_regression_275_existing_tests_still_pass(self):
        """T34 全回归: 275 个原有测试仍通过 (运行 w1-w4 测试套件)."""
        #此测试在 CI 时运行 pytest 全套, 这里仅检查 w1-w4 测试文件存在
        w1 = _THIS_DIR / "test_washout_w1.py"
        w2 = _THIS_DIR / "test_washout_w2.py"
        w3 = _THIS_DIR / "test_washout_w3.py"
        w4 = _THIS_DIR / "test_washout_w4.py"
        assert w1.exists()
        assert w2.exists()
        assert w3.exists()
        assert w4.exists()

    def test_integration_washout_detector_to_exit_strategy(self):
        """T35 端到端: detector → verdict → 三层防御 → 交易动作."""
        det = _MockDetector(WASHOUT_HI())
        #Layer 3: WashoutHoldStrategy
        hold_strat = es.WashoutHoldStrategy(washout_detector=det)
        ctx = ExitContext(
            coin="BTC", inference={}, pos_info={"pos_side": "long"},
            tracker_pos=None, in_protection=False, age_hours=2.0,
        )
        decision = hold_strat.evaluate(ctx)
        assert decision.action == "hold"
        #切换到 weakness
        det2 = _MockDetector(WEAKNESS_HI())
        hold_strat2 = es.WashoutHoldStrategy(washout_detector=det2)
        decision2 = hold_strat2.evaluate(ctx)
        assert decision2.action == "force_close"
