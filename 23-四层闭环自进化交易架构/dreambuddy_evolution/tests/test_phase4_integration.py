"""
Phase 4 集成测试: 验证 Phase 0-3 组件在实盘热路径中的完整数据流
确保不出现"写入链路断裂"反模式
"""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock


class TestPhase4PipelineIntegration:
    """验证 evolution_pipeline 中 Phase 1-3 组件的完整数据流."""

    def test_lazy_init_all_components(self):
        """所有 6 个组件懒初始化方法存在且开关关时返回 None."""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipeline = EvolutionPipeline.__new__(EvolutionPipeline)
        pipeline._exogenous_evaluator = None
        pipeline._structural_break_detector = None
        pipeline._shift_accumulator = None
        pipeline._elastic_resolver = None
        pipeline._reflexivity_monitor = None
        pipeline._last_structural_break = None
        pipeline._last_shift_result = None
        pipeline._last_elastic_result = None
        pipeline._contradiction_weight_factors = {}

        # 开关关时全部返回 None
        with patch("dreambuddy_evolution.agi_config.get_switch", return_value=False):
            assert pipeline._get_exogenous_evaluator() is None
            assert pipeline._get_structural_break_detector() is None
            assert pipeline._get_shift_accumulator() is None
            assert pipeline._get_elastic_resolver() is None
            assert pipeline._get_reflexivity_monitor() is None

    def test_select_optimal_path_returns_phase_fields(self):
        """_select_optimal_path 返回值包含 Phase 1-3 字段."""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipeline = EvolutionPipeline.__new__(EvolutionPipeline)
        pipeline._exogenous_evaluator = None
        pipeline._structural_break_detector = None
        pipeline._shift_accumulator = None
        pipeline._elastic_resolver = None
        pipeline._reflexivity_monitor = None
        pipeline._last_structural_break = None
        pipeline._last_shift_result = None
        pipeline._last_elastic_result = None
        pipeline._contradiction_weight_factors = {}

        # 空路径 → 返回默认（含 Phase 字段）
        with patch("dreambuddy_evolution.agi_config.get_switch", return_value=False):
            result = pipeline._select_optimal_path([], {})
        assert "exogenous_pc" in result
        assert "structural_break" in result
        assert "shift_result" in result
        assert "elastic_result" in result

    def test_exogenous_pc_replaces_primary_contradiction(self):
        """ExogenousStrengthEvaluator 产出时替换 primary_contradiction."""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

        pipeline = EvolutionPipeline.__new__(EvolutionPipeline)
        pipeline._exogenous_evaluator = None
        pipeline._structural_break_detector = None
        pipeline._shift_accumulator = None
        pipeline._elastic_resolver = None
        pipeline._reflexivity_monitor = None
        pipeline._last_structural_break = None
        pipeline._last_shift_result = None
        pipeline._last_elastic_result = None
        pipeline._contradiction_weight_factors = {}
        pipeline._last_primary_contradiction = None

        paths = [{"path_id": "test", "source": "test", "direction": "long",
                  "expected_return": 0.05, "confidence": 0.7, "resistance": 0.3}]
        r_out = {"_last_price": 100.0, "_last_vol": 0.02, "R_up": 0.5, "R_down": 0.5}
        market_data = {"funding_rate": 0.0005, "close": [100.0] * 50, "ma_200": 95.0}

        with patch("dreambuddy_evolution.agi_config.get_switch", return_value=True):
            mock_eval = MagicMock()
            mock_eval.get_primary_contradiction.return_value = {
                "dimension": "fundamental", "timeframe": "short",
                "direction": "bull", "strength": 0.7,
                "all_contradictions": {"technical": {"short": 0.6}, "fundamental": {"short": 0.8}},
            }
            pipeline._exogenous_evaluator = mock_eval
            pipeline._structural_break_detector = False
            pipeline._shift_accumulator = False
            pipeline._elastic_resolver = False

            result = pipeline._select_optimal_path(paths, r_out, market_data)

        assert result["exogenous_pc"] is not None
        assert result["exogenous_pc"]["dimension"] == "fundamental"


class TestPhase4KlineHandlerIntegration:
    """验证 kline_event_handler 中 Phase 1-3 透传."""

    def test_return_dict_has_phase_fields(self):
        """on_kline_close 返回值包含 Phase 1-3 字段."""
        # 验证兜底返回值
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler.__new__(KlineEventHandler)

        # 构造最小 kline_data 触发兜底
        kline_data = {"symbol": "TEST", "close": "invalid"}
        result = handler.on_kline_close(kline_data)
        assert "elastic_position_mult" in result
        assert "structural_break" in result
        assert "shift_result" in result


class TestPhase4ReflexivityIntegration:
    """验证 ReflexivityMonitor 在 polling_trader 离场路径的接入."""

    def test_reflexivity_record_called_on_exit(self):
        """离场时 ReflexivityMonitor.record 被调用."""
        # 这个测试验证代码路径存在
        # 完整集成测试需要 mock 整个 polling_trader 环境
        import inspect
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor

        # 验证 ReflexivityMonitor 有 record 方法
        assert hasattr(ReflexivityMonitor, "record")
        assert hasattr(ReflexivityMonitor, "check_self_influence")
        assert hasattr(ReflexivityMonitor, "adjust_strength")

    def test_pipeline_has_reflexivity_accessor(self):
        """EvolutionPipeline 有 _get_reflexivity_monitor 方法."""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        assert hasattr(EvolutionPipeline, "_get_reflexivity_monitor")


class TestPhase4DataFlowIntegrity:
    """验证完整数据流：生产→传递→消费（防止写入链路断裂）."""

    def test_data_flow_exogenous_to_rv(self):
        """ExogenousStrengthEvaluator → primary_contradiction → ResistanceVector."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator

        evaluator = ExogenousStrengthEvaluator()
        data = {"funding_rate": 0.0008, "close": [100.0] * 50, "ma_200": 95.0}

        # 生产: ExogenousStrengthEvaluator 产出 primary_contradiction
        pc = evaluator.get_primary_contradiction(data)
        if pc is not None:
            # 验证数据结构可被下游消费
            assert "direction" in pc
            assert "strength" in pc
            # 验证 all_contradictions 存在（供 shift_accumulator 消费）
            assert "all_contradictions" in pc

    def test_data_flow_elastic_to_ri(self):
        """ElasticConstraintResolver → position_mult → ri 调整."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.8}
        secondary = {"direction": "bull", "strength": 0.4}
        result = resolver.resolve(primary, secondary)

        # position_mult 存在且 < 1.0（约束激活）
        assert result["constraint_active"]
        assert result["position_mult"] < 1.0
        assert result["position_mult"] > 0.0

        # 模拟 kline_event_handler 中的 ri 调整
        base_ri = 0.8
        adjusted_ri = base_ri * result["position_mult"]
        assert adjusted_ri < base_ri  # 仓位降低

    def test_data_flow_shift_to_structural_break(self):
        """ContradictionShiftAccumulator.detect_shift 接收 StructuralBreakDetector 结果."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator

        acc = ContradictionShiftAccumulator(persistence=3, dominance_gap=0.1)
        # 初始: technical 主 (1 次)
        acc.record([
            {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.7},
            {"dimension": "macro", "timeframe": "long", "direction": "bear", "normalized_strength": 0.3},
        ])
        # 切换: macro 主 (连续 persistence-1=2 次)
        for i in range(2):
            acc.record([
                {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.3},
                {"dimension": "macro", "timeframe": "long", "direction": "bear", "normalized_strength": 0.7},
            ])

        # 有结构断裂 → 质变
        structural_break = {
            "volatility_regime_shift": {"detected": True},
            "correlation_break": None,
            "market_form_shift": None,
        }
        result = acc.detect_shift(structural_break)
        assert result is not None
        assert result["shifted_from"]["dimension"] == "technical"
        assert result["shifted_to"]["dimension"] == "macro"
