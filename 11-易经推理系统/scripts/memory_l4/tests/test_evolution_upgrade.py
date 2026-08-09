#!/usr/bin/env python3
"""
test_evolution_upgrade.py — PROP-20260809 E1 验收测试

覆盖:
  T1 evolution_backtest: klines→bars→walk-forward 双引擎对比
  T2 _backtest_and_adopt: 白名单 AND 回测 + 影子参数标记 + 降级路径
  T3 evolution_optimize: 方向约束搜索空间 + 影子参数跳过 + 降级
  T5 regime 四象限: 静态回退 + regime 调整 + 归一化 + ±max_adjust 裁剪
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.evolution_backtest import (      # noqa: E402
    load_local_bars, bars_to_walk_forward_data,
    build_snapshot, walk_forward_validate, MIN_BARS_FOR_BACKTEST)
from scripts.memory_l4.evolution_optimize import (      # noqa: E402
    _resolve_search_space, optimize_proposal_value)
from scripts.memory_l4.self_evolution_engine import (   # noqa: E402
    SelfEvolutionEngine)


class TestEvolutionBacktest(unittest.TestCase):
    """PROP-001: walk-forward 真实回测基础设施"""

    def test_load_local_bars_btc(self):
        bars = load_local_bars("BTC", "1H", 200)
        self.assertGreaterEqual(len(bars), MIN_BARS_FOR_BACKTEST)
        b = bars[0]
        for key in ("close", "high", "low", "open", "volume", "ts"):
            self.assertIn(key, b)

    def test_snapshot_richness(self):
        """snapshot 必须包含 preprocessor 实际消费的字段"""
        bars = load_local_bars("BTC", "1H", 100)
        snap = build_snapshot(bars, 60)
        for key in ("price_change_pct", "ch4h", "rsi",
                    "ema20", "ema50", "volume_ratio"):
            self.assertIn(key, snap, f"缺失字段 {key}")
        self.assertIsInstance(snap["rsi"], float)

    def test_walk_forward_validate_consumable_param(self):
        """min_confidence_threshold 是引擎消费参数 → affected_engine=True"""
        result = walk_forward_validate(
            param_key="min_confidence_threshold", proposed_value=0.45,
            max_bars=120)
        self.assertEqual(result["method"], "walk_forward")
        self.assertFalse(result.get("degraded", False))
        self.assertTrue(result["affected_engine"])
        self.assertIn("baseline", result)
        self.assertIn("proposed", result)
        self.assertIn("direction_accuracy", result["baseline"])

    def test_walk_forward_validate_shadow_param(self):
        """velocity_threshold 无引擎消费点 → affected_engine=False, 恒通过"""
        result = walk_forward_validate(
            param_key="velocity_threshold", proposed_value=0.02)
        self.assertTrue(result["validated"])
        self.assertFalse(result["affected_engine"])

    def test_walk_forward_validate_insufficient_bars(self):
        """数据不足 → rule_check + degraded（不抛异常）"""
        result = walk_forward_validate(
            param_key="min_confidence_threshold", proposed_value=0.45,
            max_bars=5)
        self.assertEqual(result["method"], "rule_check")
        self.assertTrue(result["degraded"])
        self.assertTrue(result["validated"])

    def test_walk_forward_validate_invalid_value(self):
        """非法值（越界）→ validated=False（拒绝采纳）"""
        result = walk_forward_validate(
            param_key="min_confidence_threshold", proposed_value=-1.0)
        self.assertFalse(result["validated"])
        self.assertTrue(str(result["reason"]).startswith("invalid_value"))


class TestEvolutionOptimize(unittest.TestCase):
    """PROP-002: Optuna 数据驱动寻优"""

    def test_search_space_lower(self):
        lo, hi = _resolve_search_space("velocity_threshold", "lower", 0.015)
        self.assertLess(lo, 0.015)
        self.assertLessEqual(hi, 0.015)

    def test_search_space_raise_clipped(self):
        """min_confidence_threshold raise 不得超过绝对上限 0.90"""
        lo, hi = _resolve_search_space(
            "min_confidence_threshold", "raise", 0.80)
        self.assertLessEqual(hi, 0.90)

    def test_shadow_param_skipped(self):
        val, source = optimize_proposal_value(
            "velocity_threshold", "lower", 0.015)
        self.assertEqual(val, 0.015)
        self.assertEqual(source, "shadow_no_consumer")

    def test_optuna_consumable_param(self):
        """可消费参数 → optuna 寻优（或环境降级 fallback，不允许抛异常）"""
        val, source = optimize_proposal_value(
            "min_confidence_threshold", "raise", 0.25,
            n_trials=8, timeout_s=90)
        self.assertIn(source, ("optuna", "default_fallback"))
        self.assertIsInstance(val, float)
        self.assertGreater(val, 0)
        self.assertLessEqual(val, 0.90)
        if source == "optuna":
            # raise 方向: 结果应在搜索区间内（> 原值附近）
            self.assertGreater(val, 0.25 * 0.999)

    def test_non_numeric_fallback(self):
        val, source = optimize_proposal_value(
            "min_confidence_threshold", "lower", "abc")
        self.assertEqual(source, "default_fallback")


class TestRegimeQuadrant(unittest.TestCase):
    """PROP-003: regime 联动四象限"""

    def setUp(self):
        self.engine = SelfEvolutionEngine(llm_client=None)

    def test_static_fallback_no_ab_logs(self):
        """AB_LOG_DIR 无日志 → 静态基线，概率和=1.0"""
        os.environ["AB_LOG_DIR"] = "/nonexistent_dir_xyz"
        probs, meta = self.engine._regime_adjusted_quadrant_probs()
        self.assertEqual(meta["prob_source"], "static_fallback")
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=3)
        self.assertAlmostEqual(probs["optimistic"], 0.15, places=2)

    def test_regime_adjustment_bull(self):
        """注入 BULL regime 日志 → 概率按映射调整且归一化"""
        with tempfile.TemporaryDirectory() as td:
            log_file = Path(td) / "agent_a" / "test_log.json"
            log_file.parent.mkdir(parents=True)
            log_file.write_text(json.dumps({
                "market_regime": "BULL", "confidence": 0.7,
                "ts": "2026-08-09T00:00:00Z"}), encoding="utf-8")
            os.environ["AB_LOG_DIR"] = td

            probs, meta = self.engine._regime_adjusted_quadrant_probs()
            self.assertEqual(meta["prob_source"], "regime")
            self.assertEqual(meta["regime"], "BULL")
            # 牛市: optimistic 应高于基线 0.15
            self.assertGreater(probs["optimistic"], 0.15)
            # 归一化
            self.assertAlmostEqual(sum(probs.values()), 1.0, places=3)

    def test_regime_stale_fallback(self):
        """过期日志（>48h）→ 回退静态基线"""
        with tempfile.TemporaryDirectory() as td:
            log_file = Path(td) / "old.json"
            log_file.write_text(json.dumps(
                {"market_regime": "BEAR"}), encoding="utf-8")
            old_ts = os.path.getmtime(str(log_file)) - 60 * 3600
            os.utime(str(log_file), (old_ts, old_ts))
            os.environ["AB_LOG_DIR"] = td

            probs, meta = self.engine._regime_adjusted_quadrant_probs()
            self.assertEqual(meta["prob_source"], "static_fallback")
            self.assertEqual(meta.get("reason"), "no_regime_data")

    def test_adjustment_clipped_to_max(self):
        """调整幅度不得超过 ±max_adjust（0.10）"""
        cfg = self.engine._load_regime_map()
        max_adj = cfg.get("max_adjust", 0.10)
        base = cfg["base_probs"]
        for regime, adj in cfg["regime_adjustments"].items():
            for quad, delta in adj.items():
                self.assertLessEqual(abs(delta), max_adj + 1e-9,
                                     f"{regime}.{quad} 调整越界")
                self.assertGreaterEqual(base[quad] + delta, -1e-9,
                                        f"{regime}.{quad} 调整后为负")

    def test_unknown_regime_fallback(self):
        """映射表外的 regime → 静态基线"""
        with tempfile.TemporaryDirectory() as td:
            log_file = Path(td) / "x.json"
            log_file.write_text(json.dumps(
                {"market_regime": "WEIRD_NEW_REGIME"}), encoding="utf-8")
            os.environ["AB_LOG_DIR"] = td

            probs, meta = self.engine._regime_adjusted_quadrant_probs()
            self.assertEqual(meta["prob_source"], "static_fallback")
            self.assertEqual(meta.get("reason"), "regime_not_in_map")


class TestBacktestAndAdoptIntegration(unittest.TestCase):
    """T2: _backtest_and_adopt 集成（白名单 AND walk-forward）"""

    def setUp(self):
        self.engine = SelfEvolutionEngine(llm_client=None)
        # 满足 recent_decisions >= 5 的门槛
        self.decisions = [{"decision": "HOLD"} for _ in range(6)]

    def test_whitelist_param_goes_through_walk_forward(self):
        """白名单可消费参数 → 走真实 walk-forward，采纳与否由回测决定"""
        proposals = [{
            "title": "测试: 微调最小置信度门槛",
            "param_key": "min_confidence_threshold",
            "param_value": 0.26,  # 近基线值，delta 应在容忍带内
            "source": "a8",
        }]
        # 隔离副作用: 不写 config/constraints
        self.engine._apply_adopted_to_config = lambda adopted: None
        adopted = self.engine._backtest_and_adopt(proposals, self.decisions)
        # 机制断言: 无论采纳与否，backtest_result 必须是真实 walk_forward
        bt = proposals[0].get("backtest_result", {})
        self.assertEqual(bt.get("method"), "walk_forward")
        self.assertFalse(bt.get("degraded", False))
        if adopted:  # 若采纳，记录必须完整
            self.assertIn("baseline", adopted[0]["backtest_result"])

    def test_non_whitelist_param_rejected(self):
        proposals = [{
            "title": "测试: 危险参数",
            "param_key": "position_size_multiplier",
            "param_value": 3.0,
            "source": "online",
        }]
        self.engine._apply_adopted_to_config = lambda adopted: None
        adopted = self.engine._backtest_and_adopt(proposals, self.decisions)
        self.assertEqual(len(adopted), 0)

    def test_insufficient_decisions_a8_fallback(self):
        """recent_decisions < 5 → a8 来源降级采纳并诚实标注"""
        proposals = [{
            "title": "测试: 降级路径",
            "param_key": "min_confidence_threshold",
            "param_value": 0.45,
            "source": "a8",
        }]
        self.engine._apply_adopted_to_config = lambda adopted: None
        adopted = self.engine._backtest_and_adopt(proposals, [{"decision": "HOLD"}])
        self.assertEqual(len(adopted), 1)
        bt = adopted[0]["backtest_result"]
        self.assertTrue(bt.get("degraded", False))


class TestE2ReviewFixes(unittest.TestCase):
    """E2 独立审查修复的回归测试（S1/W1/W3/W4/W6）"""

    def setUp(self):
        self.engine = SelfEvolutionEngine(llm_client=None)
        self.decisions = [{"decision": "HOLD"} for _ in range(6)]

    def test_s1_coverage_gate_blocks_blank_answers(self):
        """S1: 极端提高门槛（0.95）→ fail_closed 暴涨 → 覆盖率门禁拒绝"""
        result = walk_forward_validate(
            param_key="min_confidence_threshold", proposed_value=0.95,
            max_bars=250)
        self.assertEqual(result["method"], "walk_forward")
        # fail_closed 暴涨超容忍带 → 拒绝（防"交白卷=准确率提升"）
        self.assertFalse(result["validated"],
                         "覆盖率门禁未拦截交白卷提案: "
                         f"gate={result.get('gate_detail')}")
        self.assertFalse(result["gate_detail"]["coverage_ok"])

    def test_w1_boundary_direction_not_flipped(self):
        """W1: 边界值退化区间方向不得翻转"""
        lo, hi = _resolve_search_space(
            "min_confidence_threshold", "lower", 0.05)
        if lo < hi:  # 区间有效时必须向下搜
            self.assertLessEqual(hi, 0.05)
        lo, hi = _resolve_search_space(
            "min_confidence_threshold", "raise", 0.90)
        if lo < hi:  # 区间有效时必须向上搜
            self.assertGreaterEqual(lo, 0.90)

    def test_w3_degraded_proposal_rejected(self):
        """W3: 回测劣化的提案必须被拒绝（拒绝分支覆盖）"""
        import scripts.memory_l4.evolution_backtest as ebt
        original = ebt.walk_forward_validate

        def fake_validate(**kwargs):
            return {"validated": False, "method": "walk_forward",
                    "affected_engine": True,
                    "reason": "injected_degradation",
                    "delta": {"direction_accuracy": -0.5}}
        ebt.walk_forward_validate = fake_validate
        try:
            proposals = [{
                "title": "测试: 注入劣化提案",
                "param_key": "min_confidence_threshold",
                "param_value": 0.45,
                "source": "a8",
            }]
            self.engine._apply_adopted_to_config = lambda adopted: None
            adopted = self.engine._backtest_and_adopt(
                proposals, self.decisions)
            self.assertEqual(len(adopted), 0, "劣化提案不应被采纳")
        finally:
            ebt.walk_forward_validate = original

    def test_w4_record_ts_staleness_overrides_fresh_mtime(self):
        """W4: 文件 mtime 新鲜但 regime 记录 ts 过期 → 静态回退"""
        from datetime import datetime, timedelta, timezone
        old_ts = (datetime.now(timezone.utc)
                  - timedelta(hours=100)).isoformat()
        with tempfile.TemporaryDirectory() as td:
            log_file = Path(td) / "fresh_file.json"
            log_file.write_text(json.dumps(
                {"market_regime": "BULL", "ts": old_ts}), encoding="utf-8")
            # 文件 mtime = 现在（新鲜），但记录 ts = 100h 前（过期）
            os.environ["AB_LOG_DIR"] = td
            probs, meta = self.engine._regime_adjusted_quadrant_probs()
            self.assertEqual(meta["prob_source"], "static_fallback",
                             "记录级过期未被识别")

    def test_w6_refine_direction_inference(self):
        """W6: _refine_proposal_values 方向推断（中文语序陷阱）"""
        import scripts.memory_l4.evolution_optimize as eopt
        original = eopt.optimize_proposal_value
        seen = {}

        def fake_optimize(param_key, direction, current_value, **kw):
            seen[param_key] = direction
            return current_value, "default_fallback"
        eopt.optimize_proposal_value = fake_optimize
        try:
            proposals = [
                {"title": "上调置信度门槛", "param_key": "min_confidence_threshold",
                 "param_value": 0.45,
                 "rationale": "实际胜率偏低，提高入场门槛减少错误"},
                {"title": "降低速度阈值", "param_key": "velocity_threshold",
                 "param_value": 0.015,
                 "rationale": "降低速度阈值提高灵敏度"},
            ]
            self.engine._refine_proposal_values(proposals)
            self.assertEqual(seen.get("min_confidence_threshold"), "raise",
                             "'提高入场门槛减少错误' 应推断为 raise")
            self.assertEqual(seen.get("velocity_threshold"), "lower")
        finally:
            eopt.optimize_proposal_value = original


if __name__ == "__main__":
    unittest.main(verbosity=2)