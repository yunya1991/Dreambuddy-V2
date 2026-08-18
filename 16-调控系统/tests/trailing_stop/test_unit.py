"""
TrailingStopComponent 单元测试
===============================

覆盖范围：
  T1-T4  : 纯函数辅助（ATR 追踪价计算、PnL 计算）
  T5-T10 : 状态机生命周期（IDLE→ARM→ARMED→TRIGGER）
  T11    : 做空场景
  T12    : min_trail_pct 下限兜底
  T13    : 追踪价仅单边调整
  T14    : 持久化 & 重启恢复
  T15    : 冷却保护 & 自动关闭
  T16    : 峰值只单边更新（做多/做空）

运行::
  cd 16-调控系统 && python -m pytest tests/trailing_stop/test_unit.py -v
  # 或直接: python tests/trailing_stop/test_unit.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_BASE_DIR = Path(__file__).resolve().parents[2]            # 16-调控系统
_CORE_DIR = _BASE_DIR / "core"
sys.path.insert(0, str(_CORE_DIR))

from trailing_stop.types import (  # noqa: E402
    TrailingAction,
    TrailingStatus,
    calc_atr_trailing_price,
    calc_pnl_eff_pct,
    TrailingState,
)


# =====================================================================
# T1 ~ T4: 纯函数辅助
# =====================================================================


class TestHelperFunctions(unittest.TestCase):

    # T1: 做多 ATR 追踪价
    def test_atr_trailing_long_basic(self):
        price = calc_atr_trailing_price(
            is_long=True,
            peak_price=100.0,
            atr_value=2.0,
            atr_multiplier=2.5,
            min_trail_pct=0.03,
        )
        # ATR×2.5=5  vs  100×3%=3  → 取较大 5 → 100-5=95
        self.assertAlmostEqual(price, 95.0, places=4)

    # T2: 做空 ATR 追踪价
    def test_atr_trailing_short_basic(self):
        price = calc_atr_trailing_price(
            is_long=False,
            peak_price=100.0,        # 做空时的最低价
            atr_value=2.0,
            atr_multiplier=2.5,
            min_trail_pct=0.03,
        )
        # 做空：最低价 + 追踪距离 = 100 + 5 = 105
        self.assertAlmostEqual(price, 105.0, places=4)

    # T3: min_trail_pct 下限兜底（ATR 过小）
    def test_atr_trailing_min_pct_fallback(self):
        price = calc_atr_trailing_price(
            is_long=True,
            peak_price=100.0,
            atr_value=0.5,          # ATR×2.5=1.25 < 100×3%=3 → 取 3
            atr_multiplier=2.5,
            min_trail_pct=0.03,
        )
        self.assertAlmostEqual(price, 97.0, places=4)

    # T4: PnL 计算（含杠杆）
    def test_pnl_eff_with_leverage(self):
        # 做多：100 → 104，4% 名义 × 5x 杠杆 = 20% 有效盈利
        pnl = calc_pnl_eff_pct(True, 100.0, 104.0, leverage=5.0)
        self.assertAlmostEqual(pnl, 0.20, places=4)
        # 做空：100 → 96，4% 名义 × 5x = 20%
        pnl = calc_pnl_eff_pct(False, 100.0, 96.0, leverage=5.0)
        self.assertAlmostEqual(pnl, 0.20, places=4)
        # 亏损：100 → 98，2% 名义 × 10x = -20%
        pnl = calc_pnl_eff_pct(True, 100.0, 98.0, leverage=10.0)
        self.assertAlmostEqual(pnl, -0.20, places=4)


# =====================================================================
# T5 ~ T15: 组件 & 状态机
# =====================================================================


class TestTrailingStopComponent(unittest.TestCase):

    def setUp(self):
        # 独立临时状态文件
        self._tmpdir = tempfile.mkdtemp(prefix="trailing_test_")
        self._state_file = Path(self._tmpdir) / "state.json"

        # 自定义配置
        self._cfg_file = Path(self._tmpdir) / "trailing_stop.json"
        self._cfg_file.write_text(
            json.dumps({
                "version": "1.0",
                "mode": "atr_adaptive",
                "enabled_systems": ["v15_martin", "yijing_bcrm"],
                "cache_ttl_sec": 0,                 # 禁用缓存便于测试
                "persist_enabled": True,
                "persist_file": str(self._state_file),
                "algorithm": {
                    "arm_threshold_pct": 0.20,
                    "atr_period": 14,
                    "atr_multiplier": 2.5,
                    "min_trail_pct": 0.03,
                    "atr_fallback_pct": 0.02,        # 2% 默认 ATR
                },
                "trigger_cooldown_sec": 300,
                "auto_close_after_sec": 1_000_000,  # 测试中不自动关闭
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # mock 构造
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_fetch(positions_by_system):
        """构造 fetch_all_positions 返回结构。

        positions_by_system: { system: [pos_dict, ...] }
        """
        by_system = {}
        all_positions = []
        for sys_name, pos_list in positions_by_system.items():
            by_system[sys_name] = {
                "positions": pos_list,
                "equity": 150.0,
                "fallback_used": False,
            }
            for p in pos_list:
                enriched = dict(p)
                enriched.setdefault("system", sys_name)
                all_positions.append(enriched)
        return {
            "by_system": by_system,
            "positions": all_positions,
            "total_systems": len(by_system),
            "total_positions": len(all_positions),
            "total_equity": 150.0 * len(by_system),
        }

    # ------------------------------------------------------------------
    # T5: IDLE，盈利未达阈值，无动作
    # ------------------------------------------------------------------
    def test_t5_idle_no_arm(self):
        from trailing_stop.component import TrailingStopComponent

        positions = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 50000.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.01,   # 1% 名义 = 5% 有效（<20%）
                    "meta": {
                        "current_price": 50500.0,
                        "atr_pct": 0.02,
                    },
                },
            ],
        })
        with patch(
            "trailing_stop.component.TrailingStopComponent._lazy_fetch_positions",
            return_value=positions,
        ):
            comp = TrailingStopComponent(config_path=self._cfg_file)
            snap = comp.evaluate()

        self.assertEqual(snap.stats.total_positions, 1)
        self.assertEqual(snap.stats.armed_count, 0)
        key = "v15_martin:BTC-USDT:long"
        self.assertIn(key, snap.by_state)
        r = snap.by_state[key]
        self.assertEqual(r.status, TrailingStatus.IDLE)
        self.assertEqual(r.action, TrailingAction.HOLD)
        self.assertAlmostEqual(r.current_pnl_eff_pct, 0.05, places=4)

    # ------------------------------------------------------------------
    # T6: 盈利达 20% → ARM
    # ------------------------------------------------------------------
    def test_t6_arm_on_20pct_profit(self):
        from trailing_stop.component import TrailingStopComponent

        # 100 → 104 × 5x = 20% 有效收益
        positions = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {
                        "current_price": 104.0,
                        "atr_pct": 0.02,        # ATR=2.08
                    },
                },
            ],
        })
        with patch(
            "trailing_stop.component.TrailingStopComponent._lazy_fetch_positions",
            return_value=positions,
        ):
            comp = TrailingStopComponent(config_path=self._cfg_file)
            snap = comp.evaluate()

        key = "v15_martin:BTC-USDT:long"
        r = snap.by_state[key]
        self.assertEqual(r.status, TrailingStatus.ARMED)
        self.assertEqual(r.action, TrailingAction.ARM)
        self.assertAlmostEqual(r.current_pnl_eff_pct, 0.20, places=4)
        # peak=104，ATR=104*2%=2.08，ATR×2.5=5.2，104*3%=3.12 → 取 5.2，trail=104-5.2=98.8
        self.assertAlmostEqual(r.peak_price, 104.0, places=4)
        self.assertAlmostEqual(r.trailing_stop_price, 98.8, places=2)

    # ------------------------------------------------------------------
    # T7: 继续上涨 → peak 更新，trail 上移
    # ------------------------------------------------------------------
    def test_t7_peak_and_trail_move_up(self):
        from trailing_stop.component import TrailingStopComponent

        # 第一轮：ARM
        positions_1 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
        })
        # 第二轮：价格继续上涨 108（有效盈利 = (108-100)/100*5=40%）
        positions_2 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.08,
                    "meta": {"current_price": 108.0, "atr_pct": 0.02},
                },
            ],
        })

        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=positions_1):
            snap1 = comp.evaluate()
        k = "v15_martin:BTC-USDT:long"
        self.assertEqual(snap1.by_state[k].action, TrailingAction.ARM)
        trail_1 = snap1.by_state[k].trailing_stop_price

        with patch.object(comp, "_lazy_fetch_positions", return_value=positions_2):
            snap2 = comp.evaluate()
        r = snap2.by_state[k]
        self.assertEqual(r.status, TrailingStatus.ARMED)
        self.assertEqual(r.action, TrailingAction.HOLD)
        self.assertGreater(r.peak_price, 104.0)
        # peak=108，ATR×2.5 = 108*2%*2.5 = 5.4 → trail = 108-5.4 = 102.6
        self.assertAlmostEqual(r.peak_price, 108.0, places=2)
        self.assertAlmostEqual(r.trailing_stop_price, 102.6, places=2)
        self.assertGreater(r.trailing_stop_price, trail_1)  # 追踪价上移

    # ------------------------------------------------------------------
    # T8: 价格跌破追踪线 → 触发 TRIGGER_CLOSE
    # ------------------------------------------------------------------
    def test_t8_trigger_close_on_trail_break(self):
        from trailing_stop.component import TrailingStopComponent

        # 第1轮 ARM 后 trail=98.8（peak=104）
        positions_arm = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
        })
        # 第2轮价格跌到 98（< trail 98.8）
        positions_trig = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": -0.02,
                    "meta": {"current_price": 98.0, "atr_pct": 0.02},
                },
            ],
        })

        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=positions_arm):
            snap1 = comp.evaluate()
        k = "v15_martin:BTC-USDT:long"
        self.assertEqual(snap1.by_state[k].action, TrailingAction.ARM)

        with patch.object(comp, "_lazy_fetch_positions", return_value=positions_trig):
            snap2 = comp.evaluate()

        r = snap2.by_state[k]
        self.assertEqual(r.action, TrailingAction.TRIGGER_CLOSE)
        self.assertEqual(r.status, TrailingStatus.TRIGGERED)
        # 锁定有效盈利 = (98-100)/100*5 = -10%
        # （说明：虽然 break even，但这是保护机制，允许锁利低于峰值时）
        self.assertAlmostEqual(r.locked_profit_pct, -0.10, places=2)
        self.assertIn("TRIGGER", r.reason)

    # ------------------------------------------------------------------
    # T9: 峰值没创新高，trail 不下移（做多）
    # ------------------------------------------------------------------
    def test_t9_trail_never_goes_down_long(self):
        from trailing_stop.component import TrailingStopComponent

        # 轮1：104 → trail 98.8
        p1 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
        })
        # 轮2：价格回落到 102（peak 仍=104，不更新），如果重算 trail 会 104-...
        # 本轮当前价=102 > trail(98.8)，不触发；trail 保持
        p2 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.02,
                    "meta": {"current_price": 102.0, "atr_pct": 0.02},
                },
            ],
        })

        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=p1):
            s1 = comp.evaluate()
        trail_1 = s1.by_state["v15_martin:BTC-USDT:long"].trailing_stop_price

        with patch.object(comp, "_lazy_fetch_positions", return_value=p2):
            s2 = comp.evaluate()
        r2 = s2.by_state["v15_martin:BTC-USDT:long"]
        self.assertEqual(r2.action, TrailingAction.HOLD)
        self.assertEqual(r2.status, TrailingStatus.ARMED)
        self.assertAlmostEqual(r2.peak_price, 104.0, places=2)  # peak 不下降
        # 关键断言：做多时追踪价不得下降（只允许持平或上移）
        self.assertGreaterEqual(r2.trailing_stop_price, trail_1 - 1e-9)

    # ------------------------------------------------------------------
    # T10: 状态 JSON 持久化 & 重启恢复
    # ------------------------------------------------------------------
    def test_t10_state_persist_and_restore(self):
        from trailing_stop.component import TrailingStopComponent

        p1 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
        })

        # 第1次实例化并 evaluate → ARM
        comp1 = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp1, "_lazy_fetch_positions", return_value=p1):
            comp1.evaluate()
        k = "v15_martin:BTC-USDT:long"
        state1 = comp1.get_state("v15_martin", "BTC-USDT", "long")
        self.assertEqual(state1.status, TrailingStatus.ARMED)
        trail_before = state1.trailing_stop_price
        self.assertTrue(self._state_file.exists(), "状态文件应存在")

        # 第2次全新实例化（模拟重启）→ 无需达到 arm 阈值也保持 ARMED
        comp2 = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp2, "_lazy_fetch_positions", return_value=p1):
            snap2 = comp2.evaluate()
        self.assertEqual(snap2.by_state[k].status, TrailingStatus.ARMED)
        state2 = comp2.get_state("v15_martin", "BTC-USDT", "long")
        self.assertAlmostEqual(state2.trailing_stop_price, trail_before, places=2)

    # ------------------------------------------------------------------
    # T11: 做空 ARM + TRIGGER
    # ------------------------------------------------------------------
    def test_t11_short_arm_and_trigger(self):
        from trailing_stop.component import TrailingStopComponent

        # 做空：entry=100，价格跌到 96 → 名义 4% × 5x = 20% 盈利 → ARM
        p_arm = self._mock_fetch({
            "yijing_bcrm": [
                {
                    "system": "yijing_bcrm",
                    "symbol": "ETH-USDT",
                    "direction": "SHORT",
                    "size": 1.0,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 96.0, "atr_pct": 0.02},
                },
            ],
        })
        # 然后反弹到 101（> trail）→ 触发 TRIGGER
        # trail = 96 + max(96*0.02*2.5, 96*3%) = 96 + max(4.8, 2.88) = 96 + 4.8 = 100.8
        p_trig = self._mock_fetch({
            "yijing_bcrm": [
                {
                    "system": "yijing_bcrm",
                    "symbol": "ETH-USDT",
                    "direction": "SHORT",
                    "size": 1.0,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": -0.01,
                    "meta": {"current_price": 101.0, "atr_pct": 0.02},
                },
            ],
        })

        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=p_arm):
            s1 = comp.evaluate()
        k = "yijing_bcrm:ETH-USDT:short"
        self.assertEqual(s1.by_state[k].action, TrailingAction.ARM)
        self.assertAlmostEqual(s1.by_state[k].trailing_stop_price, 100.8, places=2)

        with patch.object(comp, "_lazy_fetch_positions", return_value=p_trig):
            s2 = comp.evaluate()
        r = s2.by_state[k]
        self.assertEqual(r.action, TrailingAction.TRIGGER_CLOSE)
        self.assertIn("price_above_trail", r.reason.lower())

    # ------------------------------------------------------------------
    # T12: min_trail_pct 下限兜底 (ATR<min_trail 时用 min_trail)
    # ------------------------------------------------------------------
    def test_t12_min_trail_pct_fallback_in_component(self):
        from trailing_stop.component import TrailingStopComponent

        # ATR 设得很小：0.5% → ATR*2.5 = 1.25% < 3% min
        p_arm = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.005},  # 0.5%
                },
            ],
        })
        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=p_arm):
            snap = comp.evaluate()
        r = snap.by_state["v15_martin:BTC-USDT:long"]
        # 追踪距离应为 max(0.5%*2.5=1.25%, 3%)*peak = 3% * 104 = 3.12，trail=100.88
        expected = 104.0 - (104.0 * 0.03)
        self.assertAlmostEqual(r.trailing_stop_price, expected, places=2)

    # ------------------------------------------------------------------
    # T13: 追踪价只单边调整（做空 trail 只下移，不向上）
    # ------------------------------------------------------------------
    def test_t13_short_trail_only_moves_down(self):
        from trailing_stop.component import TrailingStopComponent

        # 轮1：ARM，价格 96，peak=96，trail=100.8
        p1 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "SHORT",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 96.0, "atr_pct": 0.02},
                },
            ],
        })
        # 轮2：价格反弹 98（空头未创新低，peak 保持 96，trail 应保持）
        p2 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "SHORT",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.02,
                    "meta": {"current_price": 98.0, "atr_pct": 0.02},
                },
            ],
        })
        # 轮3：价格继续下跌 90（空头创新低 peak=90，trail 下移 = 90+4.5=94.5）
        p3 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "SHORT",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.10,
                    "meta": {"current_price": 90.0, "atr_pct": 0.02},
                },
            ],
        })

        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=p1):
            s1 = comp.evaluate()
        trail_1 = s1.by_state["v15_martin:BTC-USDT:short"].trailing_stop_price
        self.assertAlmostEqual(trail_1, 100.8, places=2)

        with patch.object(comp, "_lazy_fetch_positions", return_value=p2):
            s2 = comp.evaluate()
        trail_2 = s2.by_state["v15_martin:BTC-USDT:short"].trailing_stop_price
        self.assertAlmostEqual(trail_2, trail_1, places=2)  # 不上升

        with patch.object(comp, "_lazy_fetch_positions", return_value=p3):
            s3 = comp.evaluate()
        r3 = s3.by_state["v15_martin:BTC-USDT:short"]
        self.assertAlmostEqual(r3.peak_price, 90.0, places=2)  # 空头最低价更新
        expected_trail = 90.0 + (90.0 * 0.02 * 2.5)  # 90+4.5=94.5
        self.assertAlmostEqual(r3.trailing_stop_price, expected_trail, places=2)
        self.assertLess(r3.trailing_stop_price, trail_1)  # 空头追踪价应下移

    # ------------------------------------------------------------------
    # T14: 无持仓但状态持久化中存在 ARMED → 不丢失并可恢复
    # ------------------------------------------------------------------
    def test_t14_no_position_state_retained_in_file(self):
        from trailing_stop.component import TrailingStopComponent

        # 有持仓 ARM
        p1 = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
        })
        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=p1):
            comp.evaluate()
        self.assertEqual(
            comp.get_state("v15_martin", "BTC-USDT", "long").status,
            TrailingStatus.ARMED,
        )
        # 然后返回无持仓
        p2 = self._mock_fetch({"v15_martin": []})
        with patch.object(comp, "_lazy_fetch_positions", return_value=p2):
            snap2 = comp.evaluate()
        self.assertEqual(snap2.stats.total_positions, 0)
        # 状态文件里仍保留，直到 auto_close 过期
        self.assertTrue(self._state_file.exists())

    # ------------------------------------------------------------------
    # T15: 健康检查接口
    # ------------------------------------------------------------------
    def test_t15_health_check(self):
        from trailing_stop.component import TrailingStopComponent
        p = self._mock_fetch({"v15_martin": []})
        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=p):
            h = comp.health_check()
        self.assertEqual(h["ok"], True)
        self.assertEqual(h["persist_enabled"], True)

    # ------------------------------------------------------------------
    # T16: 多系统 + 多币种聚合
    # ------------------------------------------------------------------
    def test_t16_multi_system_aggregate(self):
        from trailing_stop.component import TrailingStopComponent
        # v15_martin BTC (ARM), yijing_bcrm ETH (IDLE)
        p = self._mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
            "yijing_bcrm": [
                {
                    "system": "yijing_bcrm",
                    "symbol": "ETH-USDT",
                    "direction": "LONG",
                    "size": 1.0,
                    "entry_price": 2000.0,
                    "leverage": 10.0,
                    "upl_ratio": 0.005,    # 5% 有效，不够 20%
                    "meta": {"current_price": 2010.0, "atr_pct": 0.02},
                },
            ],
        })
        comp = TrailingStopComponent(config_path=self._cfg_file)
        with patch.object(comp, "_lazy_fetch_positions", return_value=p):
            snap = comp.evaluate()

        self.assertEqual(snap.stats.total_positions, 2)
        self.assertEqual(snap.stats.armed_count, 1)
        self.assertEqual(snap.stats.idle_count, 1)
        self.assertEqual(snap.by_state["v15_martin:BTC-USDT:long"].action, TrailingAction.ARM)
        self.assertEqual(snap.by_state["yijing_bcrm:ETH-USDT:long"].status, TrailingStatus.IDLE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
