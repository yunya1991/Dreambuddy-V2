# -*- coding: utf-8 -*-
"""TDD: REGIME_FACTORS 映射修复测试。

根因：polling_trader.py 传入的 market_regime 值（TREND_BULL/STRONG_TREND_BEAR/TREND_BEAR/
      MEAN_REVERTING/RANGING/UNKNOWN）与 strategy_algo_layer.py REGIME_FACTORS 表键
      （Bull/Bear/Sideways 等）不匹配，导致 regime_factor 全部退化到默认 1.00，
      弹簧力场精细形态分类在策略层校准公式中失效。

修复：REGIME_FACTORS 补齐三套命名体系的键（旧版4y大周期 + 弹簧力场5类 + 八卦8类），
      确保无论上游传入哪套命名，都能命中正确的 regime_factor。
"""
import pytest
import numpy as np
from scripts.memory_l4.strategy_algo_layer import StrategyAlgorithmLayer, DEFAULT_NEUTRAL_SCORES


class TestRegimeFactorMapping:
    """验证三套 regime 命名体系都能命中 REGIME_FACTORS。"""

    def setup_method(self):
        self.layer = StrategyAlgorithmLayer()
        self.scores = {"dao": 70, "tian": 70, "di": 70, "jiang": 70, "fa": 70}

    # ===== 弹簧力场分类器（polling_trader.py L11219-L11245 产出）=====

    def test_trend_bull_factor(self):
        """TREND_BULL → factor=1.08（进攻型，对应旧版 Bull）。"""
        f = self.layer.REGIME_FACTORS.get("TREND_BULL", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(1.08), f"TREND_BULL 应映射到 1.08，实际={f}"

    def test_strong_trend_bear_factor(self):
        """STRONG_TREND_BEAR → factor=0.82（最强防御，对应旧版 Bear）。"""
        f = self.layer.REGIME_FACTORS.get("STRONG_TREND_BEAR", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(0.82), f"STRONG_TREND_BEAR 应映射到 0.82，实际={f}"

    def test_trend_bear_factor(self):
        """TREND_BEAR → factor=0.90（弱空头，对应旧版 EarlyBear）。"""
        f = self.layer.REGIME_FACTORS.get("TREND_BEAR", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(0.90), f"TREND_BEAR 应映射到 0.90，实际={f}"

    def test_mean_reverting_factor(self):
        """MEAN_REVERTING → factor=1.02（均值回归有机会，对应旧版 Rebound）。"""
        f = self.layer.REGIME_FACTORS.get("MEAN_REVERTING", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(1.02), f"MEAN_REVERTING 应映射到 1.02，实际={f}"

    def test_ranging_factor(self):
        """RANGING → factor=1.00（震荡中性，对应旧版 Sideways）。"""
        f = self.layer.REGIME_FACTORS.get("RANGING", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(1.00), f"RANGING 应映射到 1.00，实际={f}"

    def test_unknown_factor(self):
        """UNKNOWN → factor=1.00（FAIL-OPEN 中性默认）。"""
        f = self.layer.REGIME_FACTORS.get("UNKNOWN", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(1.00), f"UNKNOWN 应映射到 1.00，实际={f}"

    # ===== 八卦形态分类（bcrm2/market_regime.py GUA_REGIME_MAP）=====

    def test_trend_up_strong_factor(self):
        """TREND_UP_STRONG（乾）→ factor=1.08（强趋势上涨，进攻型）。"""
        f = self.layer.REGIME_FACTORS.get("TREND_UP_STRONG", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(1.08), f"TREND_UP_STRONG 应映射到 1.08，实际={f}"

    def test_trend_up_mild_factor(self):
        """TREND_UP_MILD（巽）→ factor=1.04（温和上涨）。"""
        f = self.layer.REGIME_FACTORS.get("TREND_UP_MILD", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(1.04), f"TREND_UP_MILD 应映射到 1.04，实际={f}"

    def test_volatile_drop_factor(self):
        """VOLATILE_DROP → factor=0.85（波动下跌，防御型）。"""
        f = self.layer.REGIME_FACTORS.get("VOLATILE_DROP", self.layer.DEFAULT_REGIME_FACTOR)
        assert f < 1.0, f"VOLATILE_DROP 应 <1.0（防御），实际={f}"

    def test_breakout_factor(self):
        """BREAKOUT → factor>1.0（突破，进攻型）。"""
        f = self.layer.REGIME_FACTORS.get("BREAKOUT", self.layer.DEFAULT_REGIME_FACTOR)
        assert f > 1.0, f"BREAKOUT 应 >1.0（进攻），实际={f}"

    # ===== 旧版4y大周期命名（backward compat，测试套件使用）=====

    def test_legacy_bull_factor(self):
        """旧版 Bull → factor=1.08（向后兼容）。"""
        f = self.layer.REGIME_FACTORS.get("Bull", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(1.08)

    def test_legacy_bear_factor(self):
        """旧版 Bear → factor=0.82（向后兼容）。"""
        f = self.layer.REGIME_FACTORS.get("Bear", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(0.82)

    def test_legacy_sideways_factor(self):
        """旧版 Sideways → factor=1.00（向后兼容）。"""
        f = self.layer.REGIME_FACTORS.get("Sideways", self.layer.DEFAULT_REGIME_FACTOR)
        assert f == pytest.approx(1.00)


class TestRegimeFactorInSelect:
    """验证 select() 端到端：不同 regime 产出不同 calibration_bias。"""

    def setup_method(self):
        from scripts.memory_l4.strategy_algo_layer import StrategyAlgoConfig
        self.layer = StrategyAlgorithmLayer(StrategyAlgoConfig(enable_strategy_layer=True))
        self.scores = {"dao": 75, "tian": 70, "di": 70, "jiang": 70, "fa": 70}

    def test_trend_bull_vs_bear_diff(self):
        """TREND_BULL 的 calibration_bias 应 > RANGING（进攻型放大）。"""
        sel_bull = self.layer.select("crypto_usdt", self.scores,
                                     regime_summary={"phase": "TREND_BULL"}, liquidity_tier="G2")
        sel_range = self.layer.select("crypto_usdt", self.scores,
                                     regime_summary={"phase": "RANGING"}, liquidity_tier="G2")
        # TREND_BULL 的 sl_tighten_factor 应与 RANGING 不同（regime_factor 生效）
        cb_bull = sel_bull.calibration_biases
        cb_range = sel_range.calibration_biases
        # 至少有一个参数不同（regime_factor 1.08 vs 1.00）
        diffs = [k for k in cb_bull if abs(cb_bull[k] - cb_range[k]) > 1e-9]
        assert len(diffs) > 0, "TREND_BULL vs RANGING 应有不同 calibration_bias（regime_factor 生效）"

    def test_strong_bear_vs_bull_diff(self):
        """STRONG_TREND_BEAR 的 calibration_bias 应 < TREND_BULL（防御型收缩）。"""
        sel_bull = self.layer.select("crypto_usdt", self.scores,
                                     regime_summary={"phase": "TREND_BULL"}, liquidity_tier="G2")
        sel_bear = self.layer.select("crypto_usdt", self.scores,
                                     regime_summary={"phase": "STRONG_TREND_BEAR"}, liquidity_tier="G2")
        # 防御型 sl_tighten_factor 更小（更紧止损）
        assert sel_bear.calibration_biases["sl_tighten_factor"] <= \
               sel_bull.calibration_biases["sl_tighten_factor"] + 1e-9, \
               "STRONG_TREND_BEAR 的 sl_tighten_factor 应 ≤ TREND_BULL（防御收缩）"
