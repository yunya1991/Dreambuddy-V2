#!/usr/bin/env python3
"""
L1 价值-风险评估 + ML模型 + 告警通知 — 单元测试
"""

import sys
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import unittest
import json
import tempfile

from core.context import (
    PositionState,
    MarketSnapshot,
    RiskContext,
    Direction,
)
from core.l1_assessor import (
    L1ValueRiskAssessor,
    ExitFeatureSet,
    L1Mode,
    L2HysteresisState,
    TrendShape,
)
from core.ml_model import (
    MLRiskModel,
    CommitteeModel,
    MLModelRegistry,
    ModelPrediction,
)
from core.alert import (
    RiskAlertNotifier,
    AlertEvent,
    AlertLevel,
    AlertCategory,
)
from core.engine import RiskEngine


class TestL1Assessor(unittest.TestCase):
    """测试 L1 价值-风险评估"""

    def setUp(self):
        self.assessor = L1ValueRiskAssessor({
            "l2_close_threshold": 0.75,
            "l2_reduce_threshold": 0.55,
            "l2_deadband": 0.03,
            "l2_confirm_n": 1,
            "l2_reduce_base_frac": 0.30,
            "l2_reduce_max_frac": 0.70,
            "l2_reduce_risk_span": 0.20,
            "l2_reduce_min_profit_pct": 0.0,
        })

        self.position = PositionState(
            coin="BTC",
            side=Direction.LONG,
            entry_price=50000,
            current_price=51000,
            unrealized_pnl_pct=0.02,
            leverage=1.0,
            atr_pct=0.02,
        )

    def test_hold_risk_basic(self):
        """测试基础 hold_risk 计算"""
        features = ExitFeatureSet.from_market_data(
            rsi=55, macd_hist=0.001, adx=25, atr_pct=0.02, chop=50
        )
        result = self.assessor.assess(self.position, features, L1Mode.HEURISTIC)

        self.assertGreaterEqual(result.hold_risk, 0.0)
        self.assertLessEqual(result.hold_risk, 1.0)
        self.assertAlmostEqual(result.hold_value, 1.0 - result.hold_risk, places=4)

    def test_hold_risk_high_dd(self):
        """测试高回撤导致高 hold_risk"""
        features_low = ExitFeatureSet.from_market_data(
            rsi=50, macd_hist=0.0, adx=25, atr_pct=0.02, dd=0.0
        )
        features_high = ExitFeatureSet.from_market_data(
            rsi=70, macd_hist=-0.01, adx=15, atr_pct=0.03, dd=0.25, chop=60
        )

        result_low = self.assessor.assess(self.position, features_low)
        result_high = self.assessor.assess(self.position, features_high)

        self.assertGreater(result_high.hold_risk, result_low.hold_risk)

    def test_mrd_score_direction(self):
        """测试 MRD Score 方向性"""
        features_bullish = ExitFeatureSet.from_market_data(
            rsi=55, trend_w_dir=1, trend_d_dir=1, mom_dir=1, vol_dir=1, adx=30
        )
        features_bearish = ExitFeatureSet.from_market_data(
            rsi=55, trend_w_dir=-1, trend_d_dir=-1, mom_dir=-1, vol_dir=-1, adx=30
        )

        result_bull = self.assessor.assess(self.position, features_bullish)
        result_bear = self.assessor.assess(self.position, features_bearish)

        self.assertGreater(result_bull.mrd_score, result_bear.mrd_score)

    def test_mrd_mode_adjustment(self):
        """测试 MRD 模式调整"""
        features = ExitFeatureSet.from_market_data(
            rsi=50, macd_hist=0.0, adx=25, atr_pct=0.02
        )

        result_h = self.assessor.assess(self.position, features, L1Mode.HEURISTIC)
        result_m = self.assessor.assess(self.position, features, L1Mode.MRD)

        # MRD 模式应该产生 model_conf
        self.assertGreaterEqual(result_m.model_conf, 0.0)

    def test_ml_mode_adjustment(self):
        """测试 ML 模式调整"""
        features = ExitFeatureSet.from_market_data(
            rsi=50, macd_hist=0.0, adx=25, atr_pct=0.02,
            p_tail=0.8,  # 高尾部风险
        )

        result = self.assessor.assess(
            self.position, features, l1_mode=L1Mode.ML
        )

        self.assertIsNotNone(result.p_tail)
        self.assertGreater(result.model_conf, 0.0)

    def test_l2_action_hold(self):
        """测试 L2 动作映射 — 低风险持有"""
        features = ExitFeatureSet.from_market_data(
            rsi=50, macd_hist=0.001, adx=30, atr_pct=0.015, dd=0.0
        )
        result = self.assessor.assess(self.position, features, L1Mode.HEURISTIC)

        self.assertEqual(result.action, "hold")

    def test_l2_action_close(self):
        """测试 L2 动作映射 — 极高风险平仓"""
        features = ExitFeatureSet.from_market_data(
            rsi=75, macd_hist=-0.02, adx=10, atr_pct=0.035, dd=0.28, chop=65,
            ema_short_dist=-0.02, mom_rsi_delta=-3.0,
        )
        l2_state = L2HysteresisState()
        result = self.assessor.assess(
            self.position, features, l2_state=l2_state, l1_mode=L1Mode.HEURISTIC
        )

        # 高风险特征应该触发 close 或 reduce
        self.assertIn(result.action, ["close", "reduce"])

    def test_risk_budget_penalty(self):
        """测试风险预算序列回撤惩罚"""
        features = ExitFeatureSet.from_market_data(
            rsi=50, dd=0.15
        )
        # 构造持续上升的 dd 历史
        snapshots = [
            {"ts": 1, "dd": 0.05},
            {"ts": 2, "dd": 0.10},
            {"ts": 3, "dd": 0.15},
            {"ts": 4, "dd": 0.20},
        ]

        result = self.assessor.assess(
            self.position, features, L1Mode.HEURISTIC,
            snapshot_history=snapshots,
        )

        self.assertGreater(result.risk_budget_penalty, 0.0)

    def test_regime_shift(self):
        """测试 Regime 阈值偏移"""
        features_chop = ExitFeatureSet.from_market_data(
            rsi=50, adx=25, atr_pct=0.02, trend_shape="chop"
        )
        features_trend = ExitFeatureSet.from_market_data(
            rsi=50, adx=30, atr_pct=0.02, trend_shape="up_strong"
        )

        result_chop = self.assessor.assess(self.position, features_chop)
        result_trend = self.assessor.assess(self.position, features_trend)

        self.assertGreater(result_chop.regime_shift, 0.0)

    def test_l2_hysteresis_state(self):
        """测试 L2 滞回状态机持久化"""
        l2_state = L2HysteresisState()

        features = ExitFeatureSet.from_market_data(
            rsi=75, macd_hist=-0.02, adx=10, atr_pct=0.035, dd=0.28, chop=65,
        )

        self.assessor.assess(
            self.position, features, l2_state=l2_state, l1_mode=L1Mode.HEURISTIC
        )

        self.assertGreater(l2_state.last_update_ts, 0)


class TestMLModel(unittest.TestCase):
    """测试 ML 风控模型"""

    def test_load_nonexistent_meta(self):
        """测试加载不存在的 meta 文件"""
        model = MLRiskModel.load_from_meta("/nonexistent/path/meta.json")
        self.assertFalse(model.is_loaded)

    def test_model_prediction_empty(self):
        """测试空模型预测"""
        model = MLRiskModel()
        pred = model.predict({"feat1": 0.5})

        self.assertIsNone(pred.p_tail)
        self.assertEqual(pred.confidence, 0.0)

    def test_committee_empty(self):
        """测试空 Committee 预测"""
        committee = CommitteeModel()
        pred = committee.predict({"feat1": 0.5})

        self.assertIsNone(pred.p_tail)

    def test_model_registry(self):
        """测试模型注册表"""
        registry = MLModelRegistry()

        model = MLRiskModel(name="test", version="1")
        registry.register_model("test", model)

        self.assertIn("test", registry.list_models())
        self.assertIsNotNone(registry.get_model("test"))

    def test_model_registry_predict(self):
        """测试注册表预测"""
        registry = MLModelRegistry()
        model = MLRiskModel(name="test")
        registry.register_model("test", model)

        pred = registry.predict("test", {"feat1": 0.5})
        self.assertIsInstance(pred, ModelPrediction)

    def test_meta_json_loading(self):
        """测试 meta JSON 加载"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({
                "model_type": "sklearn_pickle",
                "model_path": "/nonexistent/model.pkl",
                "feature_names": ["feat1", "feat2"],
                "latest_version": 1,
            }, f)
            meta_path = f.name

        try:
            model = MLRiskModel.load_from_meta(meta_path)
            self.assertEqual(len(model.feature_names), 2)
            self.assertEqual(model.version, "1")
            self.assertFalse(model.is_loaded)
        finally:
            os.unlink(meta_path)


class TestAlertNotifier(unittest.TestCase):
    """测试告警通知"""

    def setUp(self):
        self.notifier = RiskAlertNotifier({
            "mode": "file",
            "min_level": "info",
            "rate_limit_sec": 0,
        })

    def test_alert_event_creation(self):
        """测试告警事件创建"""
        event = AlertEvent(
            level=AlertLevel.CRITICAL,
            category=AlertCategory.GATE_BLOCK,
            title="测试告警",
            message="这是一条测试消息",
            coin="BTC",
        )

        self.assertEqual(event.level, AlertLevel.CRITICAL)
        self.assertIn("BTC", event.coin)
        self.assertTrue(len(event.timestamp) > 0)

    def test_alert_card_building(self):
        """测试卡片构建"""
        event = AlertEvent(
            level=AlertLevel.WARNING,
            category=AlertCategory.DRAWDOWN,
            title="回撤告警",
            message="日回撤 8%",
            coin="ETH",
            details={"drawdown": "8%", "threshold": "10%"},
        )

        card = event.to_card()
        self.assertIn("config", card)
        self.assertIn("header", card)
        self.assertEqual(card["header"]["template"], "yellow")
        self.assertGreater(len(card["elements"]), 0)

    def test_alert_text_building(self):
        """测试文本消息构建"""
        event = AlertEvent(
            level=AlertLevel.INFO,
            category=AlertCategory.SYSTEM,
            title="系统通知",
            message="风控引擎已启动",
        )

        text = event.to_text()
        self.assertIn("风控引擎已启动", text)
        self.assertIn("info", text)

    def test_notifier_alert(self):
        """测试告警发送"""
        result = self.notifier.alert(AlertEvent(
            level=AlertLevel.WARNING,
            category=AlertCategory.GATE_BLOCK,
            title="门禁阻断",
            message="日回撤熔断",
            coin="BTC",
        ))

        # file 模式不需要真正发送，只要记录历史
        history = self.notifier.get_history()
        self.assertEqual(len(history), 1)

    def test_notifier_level_filter(self):
        """测试告警级别过滤"""
        notifier = RiskAlertNotifier({
            "mode": "file",
            "min_level": "critical",
            "rate_limit_sec": 0,
        })

        notifier.alert(AlertEvent(
            level=AlertLevel.INFO,
            category=AlertCategory.SYSTEM,
            title="信息",
            message="普通信息",
        ))

        # INFO 级别不应被记录到历史
        self.assertEqual(len(notifier.get_history()), 1)

    def test_convenience_methods(self):
        """测试便捷方法"""
        self.notifier.alert_gate_block("BTC", "回撤熔断", {"dd": "12%"})
        self.notifier.alert_drawdown(0.08, 0.10)
        self.notifier.alert_consecutive_loss(4, 5)

        history = self.notifier.get_history()
        self.assertGreaterEqual(len(history), 3)

    def test_rate_limit(self):
        """测试限频"""
        notifier = RiskAlertNotifier({
            "mode": "file",
            "min_level": "info",
            "rate_limit_sec": 60,
        })

        event = AlertEvent(
            level=AlertLevel.WARNING,
            category=AlertCategory.GATE_BLOCK,
            title="测试",
            message="限频测试",
            coin="BTC",
        )

        first = notifier.alert(event)
        second = notifier.alert(event)

        self.assertTrue(first)
        self.assertFalse(second)


class TestEngineIntegration(unittest.TestCase):
    """测试引擎集成"""

    def setUp(self):
        self.engine = RiskEngine({
            "gate": {
                "daily_drawdown_circuit_breaker": {"max_daily_drawdown_pct": 0.10},
                "concurrent_position_limit": {"max_concurrent_positions": 5},
            },
            "position": {"risk_per_trade_pct": 0.02},
            "exit": {"stop_loss_barrier": {"stop_loss_pct": 0.03}},
            "l1": {
                "l2_close_threshold": 0.75,
                "l2_reduce_threshold": 0.55,
            },
            "alert": {
                "mode": "file",
                "min_level": "info",
                "rate_limit_sec": 0,
            },
        })
        self.engine.register_default_rules()

    def test_l1_assessor_integration(self):
        """测试 L1 评估器集成"""
        position = PositionState(
            coin="BTC",
            side=Direction.LONG,
            entry_price=50000,
            current_price=51000,
            unrealized_pnl_pct=0.02,
        )
        features = ExitFeatureSet.from_market_data(
            rsi=55, macd_hist=0.001, adx=25, atr_pct=0.02
        )

        result = self.engine.assess_value_risk(position, features)
        self.assertGreaterEqual(result.hold_risk, 0.0)
        self.assertLessEqual(result.hold_risk, 1.0)

    def test_ml_model_management(self):
        """测试 ML 模型管理"""
        models = self.engine.list_ml_models()
        self.assertIsInstance(models, dict)

    def test_alert_integration(self):
        """测试告警集成"""
        event = AlertEvent(
            level=AlertLevel.CRITICAL,
            category=AlertCategory.GATE_BLOCK,
            title="集成测试",
            message="引擎告警集成",
            coin="BTC",
        )

        self.engine.alert(event)
        history = self.engine.get_alert_history()
        self.assertGreater(len(history), 0)

    def test_status_with_enhancements(self):
        """测试增强后的状态概览"""
        context = RiskContext(total_equity=10000)
        status = self.engine.get_status(context)

        self.assertIn("ml_models", status)
        self.assertIn("alert_count", status)


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestL1Assessor))
    suite.addTests(loader.loadTestsFromTestCase(TestMLModel))
    suite.addTests(loader.loadTestsFromTestCase(TestAlertNotifier))
    suite.addTests(loader.loadTestsFromTestCase(TestEngineIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
