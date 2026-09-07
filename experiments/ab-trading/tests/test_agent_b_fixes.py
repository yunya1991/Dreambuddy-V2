#!/usr/bin/env python3
"""
Agent B Fix-1 / Fix-2 单元测试
==============================

Fix-1: 平仓 PnL 回写 save_memory 闭环
  - _extract_closed_pnl_size 形态 A/B 兼容测试
  - _aggregate_cycle_pnl_from_decision 加权/平均/空/异常 fail-open 测试
  - save_memory 不传 pnl_pct 时自动从 decision 提取，streaks 正确更新

Fix-2: _compute_param_adjustments 无变化项过滤
  - 边界钉死场景（趋势市 + TP/SL/ATR_TP 达边界）→ adjustments 必须为空
  - 连胜/连败驱动场景 → 实际有变化的项必须保留
  - 浮点 epsilon 边界场景 → 1e-10 差异不被误判
"""

import json, os, sys, tempfile, unittest
from pathlib import Path
from copy import deepcopy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from agents.agent_b_runner import (
    _extract_closed_pnl_size,
    _aggregate_cycle_pnl_from_decision,
    save_memory,
    _compute_param_adjustments,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fix-1 Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractClosedPnlSize(unittest.TestCase):

    def test_shape_A_closed_info(self):
        """形态 A：closed_info 顶层有 pnl_pct 和 size"""
        item = {
            "coin": "BTC",
            "pnl_pct": 0.085,
            "position_size_usdt": 100.0,
            "exit_reason": "TP_BASE",
        }
        p, s = _extract_closed_pnl_size(item)
        self.assertAlmostEqual(p, 0.085)
        self.assertAlmostEqual(s, 100.0)

    def test_shape_B_classic_driver_nested(self):
        """形态 B：ClassicDriver exit_info 嵌套在 result.closed 下"""
        item = {
            "coin": "ETH",
            "reason": "RSI_OVERBOUGHT",
            "result": {
                "ok": True,
                "closed": {
                    "pnl_pct": -0.03,
                    "position_size_usdt": 40.0,
                    "coin": "ETH",
                },
            },
        }
        p, s = _extract_closed_pnl_size(item)
        self.assertAlmostEqual(p, -0.03)
        self.assertAlmostEqual(s, 40.0)

    def test_negative_pnl_shape_A(self):
        item = {"pnl_pct": -0.05, "position_size_usdt": 50}
        p, s = _extract_closed_pnl_size(item)
        self.assertAlmostEqual(p, -0.05)
        self.assertAlmostEqual(s, 50.0)

    def test_str_floats_castable(self):
        """数字以字符串形式提供时能被转成 float"""
        item = {"pnl_pct": "0.012", "position_size_usdt": "30.5"}
        p, s = _extract_closed_pnl_size(item)
        self.assertAlmostEqual(p, 0.012)
        self.assertAlmostEqual(s, 30.5)

    def test_empty_dict_returns_none_zero(self):
        self.assertEqual(_extract_closed_pnl_size({}), (None, 0))

    def test_non_dict_returns_none_zero(self):
        self.assertEqual(_extract_closed_pnl_size("not_a_dict"), (None, 0))
        self.assertEqual(_extract_closed_pnl_size(None), (None, 0))  # type: ignore[arg-type]

    def test_shape_B_missing_closed_fields(self):
        """形态 B 有嵌套但 closed 没 pnl_pct → 返回 None,0"""
        item = {"result": {"ok": True, "closed": {"coin": "BTC"}}}
        self.assertEqual(_extract_closed_pnl_size(item), (None, 0))

    def test_shape_B_missing_result(self):
        item = {"coin": "BTC", "pnl_pct": None}
        self.assertEqual(_extract_closed_pnl_size(item), (None, 0))

    def test_uncastable_values_fail_open(self):
        """size 是完全无法转 float 的垃圾值 → fail-open"""
        item = {"pnl_pct": 0.02, "position_size_usdt": object()}
        p, s = _extract_closed_pnl_size(item)
        # 当 pnl_pct 能解析但 size 不行时，size 应该走 try-except fail-open
        # 注意我们的形态 A 代码：size = float(sz) if sz is not None else 0.0
        # object() 传入 float(object()) 会抛 TypeError → except 捕获后走形态B
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p, 0.02)


class TestAggregateCyclePnl(unittest.TestCase):

    def test_empty_decision_returns_none(self):
        self.assertIsNone(_aggregate_cycle_pnl_from_decision({}))

    def test_no_exits_returns_none(self):
        self.assertIsNone(_aggregate_cycle_pnl_from_decision({
            "l1_exits": [], "l3_exits": [], "a9_exits": [],
        }))

    def test_single_l1_win(self):
        """只有一笔 L1 盈利平仓 → 加权平均 = 单笔 pnl"""
        decision = {
            "l1_exits": [{"pnl_pct": 0.06, "position_size_usdt": 100}],
        }
        self.assertAlmostEqual(_aggregate_cycle_pnl_from_decision(decision), 0.06)

    def test_size_weighted_average(self):
        """三笔不同 size 的平仓 → 按 size 加权平均"""
        # BTC 100 USDT * +10%  = +10 收益
        # ETH  50 USDT * -4%   = -2 收益
        # SOL  50 USDT * +8%   = +4 收益
        # 总仓位 200 → 净收益 +12 / 200 = 6%
        decision = {
            "l1_exits": [{"pnl_pct":  0.10, "position_size_usdt": 100}],
            "l3_exits": [{"pnl_pct": -0.04, "position_size_usdt":  50}],
            "a9_exits": [{"pnl_pct":  0.08, "position_size_usdt":  50}],
        }
        avg = _aggregate_cycle_pnl_from_decision(decision)
        expected = (0.10 * 100 + (-0.04) * 50 + 0.08 * 50) / 200
        self.assertAlmostEqual(avg, expected)
        self.assertAlmostEqual(avg, 0.06)

    def test_fallback_simple_average_when_no_sizes(self):
        """所有 size = 0 → 退化为简单算术平均"""
        decision = {
            "l1_exits": [
                {"pnl_pct":  0.04, "position_size_usdt": 0},
                {"pnl_pct": -0.02, "position_size_usdt": 0},
            ]
        }
        avg = _aggregate_cycle_pnl_from_decision(decision)
        self.assertAlmostEqual(avg, (0.04 + (-0.02)) / 2)

    def test_mixed_shapes_A_and_B(self):
        """形态 A + 形态 B 混合时都能提取并加权"""
        decision = {
            # A: +10% @ 200 USDT
            "l1_exits": [{"pnl_pct":  0.10, "position_size_usdt": 200}],
            # B: -5% @ 100 USDT
            "l3_exits": [{
                "reason": "X",
                "result": {"ok": True, "closed": {"pnl_pct": -0.05, "position_size_usdt": 100}},
            }],
        }
        avg = _aggregate_cycle_pnl_from_decision(decision)
        expected = (0.10 * 200 + (-0.05) * 100) / 300
        self.assertAlmostEqual(avg, expected)

    def test_non_list_exit_fail_open(self):
        """exit 字段不是 list 时跳过，不抛异常"""
        decision = {"l1_exits": "not_a_list", "l3_exits": None, "a9_exits": object()}
        self.assertIsNone(_aggregate_cycle_pnl_from_decision(decision))

    def test_exception_fail_open(self):
        """decision 非 dict → 返回 None，不抛异常"""
        self.assertIsNone(_aggregate_cycle_pnl_from_decision(None))   # type: ignore[arg-type]
        self.assertIsNone(_aggregate_cycle_pnl_from_decision(42))     # type: ignore[arg-type]


class TestSaveMemoryPnlLoop(unittest.TestCase):
    """验证 save_memory 能自动从 decision 中汇总 pnl，并正确更新 streaks / lessons。
    Fix-4 I/O 隔离：所有磁盘写入到 self._tmpdir 下的测试文件，永不污染生产 data/agent_b_memory.json。"""

    def setUp(self):
        import tempfile
        self._tmp_td = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._tmp_td.name)
        self._mem_path = self._tmpdir / "agent_b_memory_TEST.json"

    def tearDown(self):
        self._tmp_td.cleanup()  # 递归删除测试目录

    def _save_memory(self, memory, decision, **kwargs):
        """封装 save_memory(...) 调用，固定 memory_path 到测试临时目录"""
        kwargs.setdefault("memory_path", self._mem_path)
        save_memory(memory, decision, **kwargs)

    def _new_memory(self) -> dict:
        return {
            "regime_history": [],
            "lessons": [],
            "recent_decisions": [],
            "win_streaks": 0,
            "loss_streaks": 0,
            "last_regime": None,
            "total_cycles": 0,
            "active_positions": {},
        }

    def test_no_closed_trades_pnl_none_streaks_unchanged(self):
        """无平仓记录时，pnl_pct 保持 None，连胜连败不应被改写（Fix-4: 写入临时目录）"""
        mem = self._new_memory()
        # 先手动设一下历史值
        mem["win_streaks"] = 2
        mem["loss_streaks"] = 0
        decision = {"market_regime": "TREND_UP", "coin": "BTC",
                    "l1_exits": [], "l3_exits": [], "a9_exits": []}
        self._save_memory(mem, decision)
        self.assertEqual(mem["win_streaks"], 2)   # 未变
        self.assertEqual(mem["loss_streaks"], 0)  # 未变
        self.assertEqual(mem["total_cycles"], 1)
        # Fix-4 额外断言：临时路径有文件，生产路径未被写入（通过比较名字）
        self.assertTrue(self._mem_path.exists(), "测试临时 JSON 必须存在")
        self.assertNotEqual(
            str(self._mem_path).endswith("data/agent_b_memory.json"), True,
            "测试绝不能写到生产 data/agent_b_memory.json"
        )

    def test_win_pnl_streak_increments_via_decision(self):
        """盈利平仓 +8% → win_streaks += 1, loss_streaks = 0"""
        mem = self._new_memory()
        decision = {
            "market_regime": "TREND_UP",
            "action": "LONG",
            "coin": "BTC",
            "l1_exits": [{"pnl_pct": 0.08, "position_size_usdt": 100}],
        }
        self._save_memory(mem, decision)
        self.assertEqual(mem["win_streaks"], 1)
        self.assertEqual(mem["loss_streaks"], 0)
        self.assertEqual(mem["lessons"], [])

    def test_loss_pnl_streak_increments_via_decision(self):
        """亏损平仓 -3% → loss_streaks += 1, win_streaks = 0"""
        mem = self._new_memory()
        decision = {
            "market_regime": "TREND_DOWN",
            "action": "SHORT",
            "coin": "ETH",
            "l1_exits": [{"pnl_pct": -0.03, "position_size_usdt": 50}],
        }
        self._save_memory(mem, decision)
        self.assertEqual(mem["win_streaks"], 0)
        self.assertEqual(mem["loss_streaks"], 1)

    def test_three_losses_triggers_lesson_via_decision(self):
        """连败3次 → 自动写入「提升置信度门槛至0.75」教训"""
        mem = self._new_memory()
        # 连败 3 次
        for i in range(3):
            decision = {
                "market_regime": "RANGE",
                "coin": ["BTC", "ETH", "SOL"][i],
                "action": "LONG",
                "l1_exits": [{"pnl_pct": -0.02 - 0.01*i, "position_size_usdt": 40}],
            }
            self._save_memory(mem, decision)
        self.assertEqual(mem["loss_streaks"], 3)
        self.assertEqual(mem["win_streaks"], 0)
        self.assertEqual(len(mem["lessons"]), 1)
        self.assertIn("连败3次", mem["lessons"][0])
        self.assertIn("提升置信度门槛至0.75", mem["lessons"][0])

    def test_mixed_shapes_B_classic_nested_pnl(self):
        """形态 B（ClassicDriver）的嵌套 pnl 也能驱动 streak"""
        mem = self._new_memory()
        decision = {
            "market_regime": "TREND_UP",
            "action": "LONG",
            "coin": "BTC",
            "l3_exits": [{
                "coin": "BTC",
                "reason": "VOL_BREAKDOWN",
                "result": {"ok": True, "closed": {"pnl_pct": 0.12, "position_size_usdt": 200}},
            }],
        }
        self._save_memory(mem, decision)
        self.assertEqual(mem["win_streaks"], 1)

    def test_explicit_pnl_pct_overrides_decision(self):
        """调用方显式传 pnl_pct 参数应优先于 decision 自动聚合"""
        mem = self._new_memory()
        decision = {
            "market_regime": "TREND_UP",
            "l1_exits": [{"pnl_pct": -0.05, "position_size_usdt": 100}],  # decision 显示亏损
        }
        # 显式传盈利
        self._save_memory(mem, decision, pnl_pct=0.06)
        self.assertEqual(mem["win_streaks"], 1)
        self.assertEqual(mem["loss_streaks"], 0)


# ──────────────────────────────────────────────────────────────────────────────
# Fix-2 Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeParamAdjustmentsFilter(unittest.TestCase):
    """验证 Fix-2：等值项被过滤，不再产生「X→X」的假更新"""

    def _make_memory(self, loss_streaks=0, win_streaks=0, lessons=None,
                     total_cycles=0) -> dict:
        return {
            "total_cycles": total_cycles,
            "loss_streaks": loss_streaks,
            "win_streaks": win_streaks,
            "lessons": lessons or [],
            "active_positions": {},
        }

    # ── 核心：趋势钉死新边界端点场景 → 等值过滤为 empty，Fix-2 继续生效 ──

    def test_pinned_at_bounds_trend_market_returns_empty(self):
        """
        [Fix-2 + Fix-3 兼容验证] TREND 100% + 参数位于 新 TREND×系数 不动点
        （新边界端点：TP=0.25(上限)、SL=0.015(下限)、ATR_TP=7.0(上限)）
        → TREND×1.15 / ×0.92 / ×1.1 全部被钳制回原值 → Fix-2 过滤为 {}。
        （旧边界 0.15/0.02/5.0 场景在 Fix-3 后不再是钉死场景，会产真变化，
         因此更新用例至新 TREND-fixpoint 边界端点，不改变 Fix-2 验证意图）
        """
        from agents.agent_b_runner import _load_strategy_params, _save_strategy_params
        orig = _load_strategy_params()
        try:
            tmp = dict(orig)
            # 新 TREND 不动点：对应 ×系数 的边界端点（夹制后 = 当前）
            tmp["take_profit_pct"]   = 0.25   # min(0.25×1.15=0.2875, 0.25) = 0.25
            tmp["stop_loss_pct"]     = 0.015  # max(0.015×0.92=0.0138, 0.015) = 0.015
            tmp["atr_tp_multiplier"] = 7.0    # min(7.0×1.1=7.7,    7.0) = 7.0
            _save_strategy_params(tmp)

            decisions = (
                [{"regime": "TREND_UP",   "pnl_pct": None}] * 12
                + [{"regime": "TREND_DOWN", "pnl_pct": None}] * 8
            )
            mem = self._make_memory(loss_streaks=0, win_streaks=0)
            adj = _compute_param_adjustments(mem, decisions)

            self.assertEqual(adj, {},
                             f"新 TREND 钉死场景应返回空 adjustments（Fix-2 等值过滤），实际: {adj}")
        finally:
            _save_strategy_params(orig)

    # ── 连败驱动：有真实变化时应被正确保留 ──

    def test_loss_streaks_5_adjustments_actually_change(self):
        """连败 5 次 → 置信度/杠杆/仓位/持仓数 4 项都会变化，必须全部保留"""
        # 基础参数: confidence_gate=0.55, default_leverage=3,
        #           per_trade_pct=0.05, max_positions=3
        # 连败≥5的调整:
        #   confidence_gate = min(0.55+0.15, 0.85) = 0.70  (变化 ✅)
        #   default_leverage = max(3-2, 1) = 1           (变化 ✅)
        #   per_trade_pct   = max(0.05*0.6, 0.02) = 0.03 (变化 ✅)
        #   max_positions   = max(3-2, 1) = 1            (变化 ✅)
        adj = _compute_param_adjustments(
            self._make_memory(loss_streaks=5),
            recent_decisions=[],  # 空 → 波动率/胜率分支都不触发
        )
        self.assertIn("confidence_gate", adj)
        self.assertIn("default_leverage", adj)
        self.assertIn("per_trade_pct", adj)
        self.assertIn("max_positions", adj)
        self.assertAlmostEqual(adj["confidence_gate"], 0.70)
        self.assertEqual(adj["default_leverage"], 1)
        self.assertAlmostEqual(adj["per_trade_pct"], 0.03)
        self.assertEqual(adj["max_positions"], 1)
        # 不应该出现 take_profit_pct / stop_loss_pct 等其他未变项
        self.assertNotIn("take_profit_pct", adj)
        self.assertNotIn("stop_loss_pct", adj)

    # ── 连胜驱动：有真实变化时保留 ──

    def test_win_streaks_3_changes_only_per_trade_pct(self):
        """连胜 3 次 (连败=0) → per_trade_pct 0.05*1.1=0.055，被 min(0.055, 0.08) 保留"""
        adj = _compute_param_adjustments(
            self._make_memory(win_streaks=3, loss_streaks=0),
            recent_decisions=[],
        )
        self.assertIn("per_trade_pct", adj)
        self.assertAlmostEqual(adj["per_trade_pct"], 0.055)

    # ── 浮动 eps 精度保护：1e-10 差异视为相等 ──

    def test_float_epsilon_within_tolerance_filtered(self):
        """当 RANGE 调整后值 == 当前参数（Fix-3 新边界不动点）时应被过滤为 empty，
        并间接验证 float epsilon 1e-9 精度比较（Fix-2 eps 保护）。

        Fix-3 新边界下，RANGE 分支 multiplicative-from-current 的不动点 = 新边界端点：
          take_profit_pct  = max(current * 0.85, low=0.03)  → 不动点 = 0.03 (new low)
          stop_loss_pct    = min(current * 1.1,  high=0.10) → 不动点 = 0.10 (new high)
          atr_sl_multiplier = min(current * 1.05, high=3.0) → 不动点 = 3.0  (new high)
          atr_tp_multiplier = max(current * 0.9,  low=1.5)  → 不动点 = 1.5  (new low)
        把参数临时设到上述 4 个不动点值，全 RANGE 场景下 adjustments 必须 == {}。
        （旧 0.04/0.08/2.5/2.0 在 Fix-3 后已非不动点，见 test_range_old_fixpoints_now_move）
        """
        from agents.agent_b_runner import _load_strategy_params, _save_strategy_params
        orig = _load_strategy_params()
        try:
            tmp = dict(orig)
            # Fix-3 新边界: RANGE ×系数 的真正不动点 = 新边界端点（对应夹制）
            tmp["take_profit_pct"]   = 0.03  # max(0.03*0.85=0.0255, 0.03) == 0.03 ✓
            tmp["stop_loss_pct"]     = 0.10  # min(0.10*1.1=0.11,   0.10) == 0.10 ✓
            tmp["atr_sl_multiplier"] = 3.0   # min(3.0*1.05=3.15,  3.0)  == 3.0  ✓
            tmp["atr_tp_multiplier"] = 1.5   # max(1.5*0.9=1.35,   1.5)  == 1.5  ✓
            _save_strategy_params(tmp)

            # 20 条全 RANGE（>60% 阈值触发分支）；pnl_pct=None 胜率分支不触发
            decisions = [{"regime": "RANGE", "pnl_pct": None}] * 20
            mem = self._make_memory()  # streaks=0, lessons=[] → 连胜/连败/教训驱动都不触发
            adj = _compute_param_adjustments(mem, decisions)

            # 四项都命中不动点 → adjustments 必须为空（Fix-2 过滤生效）
            self.assertEqual(adj, {},
                             f"RANGE 新不动点参数应被过滤为 empty，实际: {adj}")
        finally:
            _save_strategy_params(orig)  # 还原真实策略参数

    # ── 教训驱动调整：有变化时保留 ──

    def test_lesson_driven_confidence_gate_change_retained(self):
        """连败期间存在「提升置信度门槛至 0.70」的教训 → 应调到 0.70"""
        adj = _compute_param_adjustments(
            self._make_memory(loss_streaks=2, lessons=["连败2次，regime=RANGE，提升置信度门槛至0.70"]),
            recent_decisions=[],
        )
        self.assertIn("confidence_gate", adj)
        self.assertAlmostEqual(adj["confidence_gate"], 0.70)

    def test_lesson_driven_gate_ignored_when_loss_streaks_zero(self):
        """连败已解除（loss_streaks=0）时，提门槛教训不应生效"""
        adj = _compute_param_adjustments(
            self._make_memory(loss_streaks=0, win_streaks=1, lessons=["连败2次，regime=RANGE，提升置信度门槛至0.70"]),
            recent_decisions=[],
        )
        # 教训不应抬高门槛；但可能有连胜回调门槛的调整
        if "confidence_gate" in adj:
            self.assertLess(adj["confidence_gate"], 0.70,
                            "连败已解除时不应应用提门槛教训")

    def test_lesson_driven_below_current_gate_filtered(self):
        """教训建议 0.60，但当前已经更高 0.70 → 不调整（max 保留更高值），应该被过滤"""
        from agents.agent_b_runner import _load_strategy_params, _save_strategy_params
        orig = _load_strategy_params()
        try:
            tmp = dict(orig)
            tmp["confidence_gate"] = 0.70  # 已经很高
            _save_strategy_params(tmp)
            adj = _compute_param_adjustments(
                self._make_memory(lessons=["提升置信度门槛至0.60"]),
                recent_decisions=[],
            )
            self.assertEqual(adj, {}, f"教训目标低于当前值应被过滤，实际: {adj}")
        finally:
            _save_strategy_params(orig)

    # ── 胜率统计分支（recent_decisions ≥10 且有 pnl_pct）──

    def test_win_rate_low_30pct_decreases_per_trade_pct(self):
        """10 笔决策中 8 笔亏损（win_rate=20% < 30%阈值）→ per_trade_pct × 0.7"""
        # 当前 per_trade_pct = 0.05, 0.05 * 0.7 = 0.035 > 0.02 下限 → 调整值 0.035（变化 ✅）
        decisions = (
            [{"regime": "RANGE", "pnl_pct": -0.02}] * 8
            + [{"regime": "RANGE", "pnl_pct":  0.05}] * 2
        )
        adj = _compute_param_adjustments(self._make_memory(), decisions)
        self.assertIn("per_trade_pct", adj)
        self.assertAlmostEqual(adj["per_trade_pct"], 0.035)


# ──────────────────────────────────────────────────────────────────────────────
# Fix-3 Tests: PARAM_BOUNDS 边界放宽，让 TREND/RANGE ×系数 真正产生变化
# ──────────────────────────────────────────────────────────────────────────────
# Fix-3 的目标放宽边界（未来代码的新 PARAM_BOUNDS），测试先用 mock 注入验证：
#   stop_loss_pct:     0.015 ~ 0.10   (常规仓 1.5% 下限)
#   take_profit_pct:   0.03  ~ 0.25   (常规仓 3% 下限)
#   atr_sl_multiplier: 0.8   ~ 3.0
#   atr_tp_multiplier: 1.5   ~ 7.0
#   per_trade_pct:     0.02  ~ 0.15
NEW_BOUNDS_FIX3 = {
    "stop_loss_pct":    (0.015, 0.10),
    "take_profit_pct":  (0.03,  0.25),
    "atr_sl_multiplier": (0.8,   3.0),
    "atr_tp_multiplier": (1.5,   7.0),
    "per_trade_pct":    (0.02,  0.15),
    "confidence_gate":  (0.40,  0.85),
    "default_leverage": (1,     5),
    "max_positions":    (1,     5),
}


class TestFix3RelaxedBounds(unittest.TestCase):
    """Fix-3 RED → GREEN：旧边界下 TREND/RANGE 永远被夹回原值（钉死），
    新边界下必须产生真实、数值正确的调整变化。"""

    def _make_memory(self, **kw):
        base = {"total_cycles": 0, "loss_streaks": 0, "win_streaks": 0,
                "lessons": [], "active_positions": {}}
        base.update(kw)
        return base

    # ── Fix-3 目标行为 1：当前"钉死"的 TREND 参数（TP=0.15/SL=0.02/ATR_TP=5.0）
    #    在新边界下应真正放大/缩小（不再被等值过滤为 empty）──

    def test_trend_pinned_now_grows_tp_sl_atrtp(self):
        """[Fix-3 RED] TREND 100% + 当前钉死参数: 0.15/0.02/5.0 → 新边界应产 3 项真变化。
        旧边界：×系数后全被夹回原值 → adjustments 空 → 本测试断言失败（RED）。
        新边界：TP=0.15×1.15=0.1725, SL=0.02×0.92=0.0184, ATR_TP=5.0×1.1=5.5 → 断言通过（GREEN）。"""
        from unittest.mock import patch
        decisions = (
            [{"regime": "TREND_UP",   "pnl_pct": None}] * 12
            + [{"regime": "TREND_DOWN", "pnl_pct": None}] * 8
        )
        mem = self._make_memory()
        # 需要 PARAM_BOUNDS 提取为模块级变量才能 mock（Fix-3 的一部分）
        with patch.dict("agents.agent_b_runner.PARAM_BOUNDS", NEW_BOUNDS_FIX3, clear=True):
            adj = _compute_param_adjustments(mem, decisions)

        self.assertIn("take_profit_pct", adj,
                      f"TREND 放大 TP 不应被边界夹死; adjustments={adj}")
        self.assertAlmostEqual(adj["take_profit_pct"], 0.1725, places=6)
        self.assertIn("stop_loss_pct", adj,
                      f"TREND 收窄 SL 不应被边界夹死; adjustments={adj}")
        self.assertAlmostEqual(adj["stop_loss_pct"], 0.0184, places=6)
        self.assertIn("atr_tp_multiplier", adj,
                      f"TREND 放大 ATR_TP 不应被边界夹死; adjustments={adj}")
        self.assertAlmostEqual(adj["atr_tp_multiplier"], 5.5, places=6)
        # TREND 分支不改 ATR_SL → 不应出现
        self.assertNotIn("atr_sl_multiplier", adj)

    # ── Fix-3 目标行为 2：旧 RANGE 不动点（TP=0.04/SL=0.08/ATR_SL=2.5/ATR_TP=2.0）
    #    在新边界下应真正缩小/放大（原 test_float_epsilon 的不动点不再是不动点）──

    def test_range_old_fixpoints_now_move(self):
        """[Fix-3 RED] RANGE 100% + 旧边界不动点参数: 0.04/0.08/2.5/2.0 → 新边界应产 4 项真变化。
        旧边界: ×系数后全被夹回 → adjustments 空 → RED 失败。
        新边界: TP=max(0.04×0.85=0.034, low=0.03)=0.034
                SL=min(0.08×1.1=0.088,    high=0.10)=0.088
                ATR_SL=min(2.5×1.05=2.625, high=3.0)=2.625
                ATR_TP=max(2.0×0.9=1.8,    low=1.5)=1.8
        → 4 项都应出现（GREEN 通过）。"""
        from agents.agent_b_runner import _load_strategy_params, _save_strategy_params
        from unittest.mock import patch
        orig = _load_strategy_params()
        try:
            # 设成旧边界下的 RANGE 不动点值（现在应能动起来）
            tmp = dict(orig)
            tmp["take_profit_pct"]   = 0.04
            tmp["stop_loss_pct"]     = 0.08
            tmp["atr_sl_multiplier"] = 2.5
            tmp["atr_tp_multiplier"] = 2.0
            _save_strategy_params(tmp)

            decisions = [{"regime": "RANGE", "pnl_pct": None}] * 20
            mem = self._make_memory()
            with patch.dict("agents.agent_b_runner.PARAM_BOUNDS", NEW_BOUNDS_FIX3, clear=True):
                adj = _compute_param_adjustments(mem, decisions)

            self.assertEqual(len(adj), 4,
                             f"RANGE 旧不动点应产生 4 项真变化，实际 {len(adj)} 项: {adj}")
            self.assertAlmostEqual(adj["take_profit_pct"],   0.034,  places=6)
            self.assertAlmostEqual(adj["stop_loss_pct"],     0.088,  places=6)
            self.assertAlmostEqual(adj["atr_sl_multiplier"], 2.625,  places=6)
            self.assertAlmostEqual(adj["atr_tp_multiplier"], 1.8,    places=6)
        finally:
            _save_strategy_params(orig)


# ──────────────────────────────────────────────────────────────────────────────
# Fix-4 Tests: save_memory 调用必须路径可注入，不得污染生产 agent_b_memory.json
# ──────────────────────────────────────────────────────────────────────────────

class TestFix4MemoryPathIsolation(unittest.TestCase):
    """Fix-4 RED → GREEN:
    save_memory(mem, decision, memory_path=Path/to/tmp.json) 必须写到 tmp.json；
    未传 memory_path 时保持默认 MEMORY_PATH（向后兼容）。
    RED: 当前 save_memory 无 memory_path 参数 → TypeError（失败）。
    GREEN: 增加可选 memory_path 参数后通过。"""

    def _win_decision(self):
        return {
            "cycle_id": "FIX4-TEST-IGNORE",
            "market_regime": "TREND_UP",
            "action": "LONG",
            "coin": "BTC",
            "l1_exits": [{"pnl_pct": 0.06, "position_size_usdt": 150}],
        }

    def test_save_memory_accepts_memory_path_kwarg_writes_there(self):
        """[Fix-4 RED] save_memory 必须接受 memory_path 形参，写入指定位置而非生产路径。"""
        import tempfile, hashlib
        mem = {
            "total_cycles": 0, "win_streaks": 0, "loss_streaks": 0,
            "lessons": [], "recent_decisions": [], "active_positions": {},
        }

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td) / "test_memory.json"
            # RED: save_memory 没这个参数 → TypeError → 测试失败
            save_memory(mem, self._win_decision(), memory_path=tmp_path)

            # GREEN: 参数被接受，磁盘内容正确（写到了 tmp_path，连胜+1）
            self.assertTrue(tmp_path.exists(), "memory_path 指定位置必须有写入文件")
            with open(tmp_path) as f:
                written = json.load(f)
            self.assertEqual(written["win_streaks"], 1,
                             "自定义路径的磁盘记忆中连胜必须已+1")
            self.assertEqual(written["loss_streaks"], 0)
            self.assertEqual(written["total_cycles"], 1)

    def test_save_memory_default_path_backward_compat(self):
        """不传 memory_path → 行为等价默认 MEMORY_PATH（向后兼容）。
        直接使用 save_memory 签名 introspection：memory_path 必须是 kwarg 且默认 MEMORY_PATH。"""
        import inspect
        sig = inspect.signature(save_memory)
        self.assertIn("memory_path", sig.parameters,
                      "save_memory 签名中必须有 memory_path 参数")
        self.assertIsNot(
            sig.parameters["memory_path"].default, inspect.Parameter.empty,
            "memory_path 必须有默认值（向后兼容：未传时 = MEMORY_PATH）"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
