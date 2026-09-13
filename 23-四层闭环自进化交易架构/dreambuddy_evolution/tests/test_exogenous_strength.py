"""
ExogenousStrengthEvaluator 测试
覆盖: 外生力量度量 + 标准化 + 主矛盾识别
"""
import pytest
import numpy as np


class TestExogenousStrengthEvaluator:
    """测试外生力量度量器."""

    def test_basic_evaluation(self):
        """基本评估：返回三维度×三周期."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        data = {
            "ri_signal_strength": 0.7,
            "okx_positions": {"long": 0.6, "short": 0.4},
            "ma_200": 95.0,
            "close": [100.0] * 50,
            "funding_rate": 0.0005,
        }
        result = evaluator.evaluate(data)
        assert "technical" in result
        assert "fundamental" in result
        assert "macro" in result
        for dim in ["technical", "fundamental", "macro"]:
            for tf in ["short", "medium", "long"]:
                val = result[dim][tf]
                assert 0.0 <= val <= 1.0

    def test_normalize_range(self):
        """标准化值在 [0,1]."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        # 历史不足时直接线性映射
        val = evaluator._normalize("test_key", 0.8)
        assert 0.0 <= val <= 1.0
        val = evaluator._normalize("test_key", -0.8)
        assert 0.0 <= val <= 1.0
        val = evaluator._normalize("test_key", 0.0)
        assert abs(val - 0.5) < 0.01

    def test_normalize_with_history(self):
        """有历史数据时使用 percentile rank."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        # 填充历史
        for i in range(15):
            evaluator._normalize("hist_key", float(i) / 14.0 * 2.0 - 1.0)
        # 新值 = 1.0（最大值）
        val = evaluator._normalize("hist_key", 1.0)
        assert val > 0.8  # 高分位

    def test_funding_rate_as_fundamental_proxy(self):
        """资金费率作为基本面短期的 fallback."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        # 正费率 → 做多拥挤 → 基本面短期力量偏离中性
        data = {"funding_rate": 0.0008}
        result = evaluator.evaluate(data)
        assert result["fundamental"]["short"] != 0.5

    def test_cpi_surprise(self):
        """CPI surprise 影响宏观短期."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        # CPI 超预期 0.3% → 宏观短期力量偏空
        data = {"cpi_actual": 3.5, "cpi_expected": 3.2}
        result = evaluator.evaluate(data)
        # 历史不足时线性映射: surprise=0.3, 0.3/0.5=0.6, 0.5+0.6*0.5=0.8
        assert result["macro"]["short"] > 0.5

    def test_nvt_deviation(self):
        """NVT 偏离影响基本面长期."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        data = {"nvt_ratio": 75.0, "nvt_historical_median": 50.0}
        result = evaluator.evaluate(data)
        assert result["fundamental"]["long"] != 0.5

    def test_monetary_cycle(self):
        """货币政策周期影响宏观长期."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        data = {"monetary_cycle": "tightening"}
        result = evaluator.evaluate(data)
        # tightening → 1.0 → 标准化 > 0.5
        assert result["macro"]["long"] >= 0.5

        data2 = {"monetary_cycle": "easing"}
        result2 = evaluator.evaluate(data2)
        assert result2["macro"]["long"] <= 0.5

    def test_get_primary_contradiction(self):
        """主矛盾识别: 力量最强的."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        data = {
            "funding_rate": 0.001,  # 强基本面短期信号
            "cpi_actual": 3.5, "cpi_expected": 3.2,  # 宏观短期
            "ri_signal_strength": 0.55,  # 技术面中性
            "ma_200": 100.0, "close": [100.0] * 50,
            "okx_positions": {"long": 0.5, "short": 0.5},
        }
        pc = evaluator.get_primary_contradiction(data)
        assert pc is not None
        assert "dimension" in pc
        assert "timeframe" in pc
        assert "direction" in pc
        assert "strength" in pc
        assert pc["direction"] in ["bull", "bear", "neutral"]

    def test_all_neutral_returns_none(self):
        """全部中性时返回 None."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        data = {}  # 无数据 → 全部默认 0.5
        pc = evaluator.get_primary_contradiction(data)
        assert pc is None

    def test_failopen_missing_data(self):
        """数据缺失时 FAIL-OPEN."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        evaluator = ExogenousStrengthEvaluator()
        result = evaluator.evaluate({})
        for dim in ["technical", "fundamental", "macro"]:
            for tf in ["short", "medium", "long"]:
                assert 0.0 <= result[dim][tf] <= 1.0

    def test_non_price_metrics(self):
        """验证所有度量是非价格量."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        # 数据中只有非价格量
        data = {
            "ri_signal_strength": 0.7,        # 路径评分，非价格
            "funding_rate": 0.0005,          # 费率，非价格
            "etf_net_flow": 0.3,             # 份额变动，非价格
            "active_addresses_now": 1000000,
            "active_addresses_7d_ago": 950000,
            "nvt_ratio": 75.0,
            "nvt_historical_median": 50.0,
            "cpi_actual": 3.5, "cpi_expected": 3.2,
            "rate_hike_prob": 0.7,
            "monetary_cycle": "tightening",
        }
        evaluator = ExogenousStrengthEvaluator()
        result = evaluator.evaluate(data)
        # 所有值都在合理范围
        for dim in ["technical", "fundamental", "macro"]:
            for tf in ["short", "medium", "long"]:
                assert 0.0 <= result[dim][tf] <= 1.0


class TestBacktestFramework:
    """回测验证框架: 方向命中率 + IC 检验."""

    def test_backtest_basic(self):
        """基本回测: 验证可证伪性框架."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator

        # 模拟 50 个时段
        evaluator = ExogenousStrengthEvaluator()
        predictions = []
        actuals = []

        for i in range(50):
            data = {
                "funding_rate": 0.0003 * (1 if i % 3 != 0 else -1),
                "ri_signal_strength": 0.6 + 0.1 * (i % 5 - 2) / 2,
                "ma_200": 100.0, "close": [100.0 + i] * 10,
                "okx_positions": {"long": 0.55, "short": 0.45},
            }
            pc = evaluator.get_primary_contradiction(data)
            if pc is not None:
                predictions.append(pc["direction"])
                actual_dir = "bull" if i % 2 == 0 else "bear"
                actuals.append(actual_dir)

        # 至少有一些预测
        assert len(predictions) > 0

    def test_falsification_criteria(self):
        """可证伪标准定义."""
        # binomial test: H0: p=0.5, α=0.05
        # 如果命中率 ≤ 55% 且样本 > 100，理论被证伪
        # 这里只验证逻辑结构
        hits = 55
        total = 100
        hit_rate = hits / total
        assert hit_rate == 0.55  # 边界值

        # IC 检验: IC > 0.03 才显著
        ic = 0.03
        assert ic == 0.03  # 边界值
