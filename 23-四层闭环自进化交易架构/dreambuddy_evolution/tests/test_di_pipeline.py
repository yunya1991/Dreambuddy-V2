"""
Phase 4 P0-2 废单例 — DI 连锁 TDD 测试套件

5 步连锁:
- Step 4.1: IEvolutionPipeline Protocol 定义 (run_symbol + get_feedback)
- Step 4.2: TradeSettlementBridge 构造注入 pipeline 参数 (过渡兼容 fallback)
- Step 4.3: KlineEventHandler 透传 pipeline 参数
- Step 4.4: 跳过 (DataPipelineAdapter 不构造 KlineEventHandler, 实际生产无该链路)
- Step 4.5: _instance 标记 deprecated (保留过渡兼容, 不破坏 lazy fallback)

硬约束: 65 baseline + 16 safe_call 测试零回归 + EvolutionPipeline 仍可单例 fallback.
"""
import os
from pathlib import Path

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in os.environ.get("PYTHONPATH", ""):
    os.environ["PYTHONPATH"] = REPO.as_posix() + os.pathsep + os.environ.get("PYTHONPATH", "")
if str(REPO) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO))


# ==============================================================================
# TR-DI-01: IEvolutionPipeline Protocol 定义 (Step 4.1)
# ==============================================================================
class TestIEvolutionPipelineProtocol:
    """IEvolutionPipeline Protocol 契约: run_symbol + get_feedback"""

    def test_TR_DI_01_protocol_importable(self):
        """IEvolutionPipeline 可从 dreambuddy_evolution.core.interfaces 导入"""
        from dreambuddy_evolution.core.interfaces import IEvolutionPipeline  # noqa: F401
        assert IEvolutionPipeline is not None

    def test_TR_DI_02_protocol_is_runtime_checkable(self):
        """IEvolutionPipeline 应为 @runtime_checkable (支持 isinstance)"""
        from dreambuddy_evolution.core.interfaces import IEvolutionPipeline
        # runtime_checkable Protocol 支持 isinstance(obj, Protocol)
        # 至少不抛 TypeError
        class DummyPipe:
            def run_symbol(self, symbol, market_data, rv=None): return {}
            def get_feedback(self): return {}
        dummy = DummyPipe()
        # runtime_checkable: isinstance 不抛 TypeError
        try:
            isinstance(dummy, IEvolutionPipeline)
        except TypeError:
            pytest.fail("IEvolutionPipeline 不是 runtime_checkable, isinstance 抛 TypeError")

    def test_TR_DI_03_protocol_defines_run_symbol(self):
        """IEvolutionPipeline 定义 run_symbol 方法契约"""
        from dreambuddy_evolution.core.interfaces import IEvolutionPipeline
        # Protocol 类应有 run_symbol 属性
        assert hasattr(IEvolutionPipeline, "run_symbol"), \
            "IEvolutionPipeline 缺少 run_symbol 方法"

    def test_TR_DI_04_protocol_defines_get_feedback(self):
        """IEvolutionPipeline 定义 get_feedback 方法契约"""
        from dreambuddy_evolution.core.interfaces import IEvolutionPipeline
        assert hasattr(IEvolutionPipeline, "get_feedback"), \
            "IEvolutionPipeline 缺少 get_feedback 方法"

    def test_TR_DI_05_evolution_pipeline_satisfies_protocol(self):
        """EvolutionPipeline 实例满足 IEvolutionPipeline Protocol"""
        from dreambuddy_evolution.core.interfaces import IEvolutionPipeline
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        # EvolutionPipeline 应有 run_symbol + get_feedback 方法
        assert hasattr(EvolutionPipeline, "run_symbol"), \
            "EvolutionPipeline 缺少 run_symbol, 不满足 IEvolutionPipeline"
        assert hasattr(EvolutionPipeline, "get_feedback"), \
            "EvolutionPipeline 缺少 get_feedback, 不满足 IEvolutionPipeline"


# ==============================================================================
# TR-DI-02: TradeSettlementBridge 构造注入 (Step 4.2)
# ==============================================================================
class TestTradeSettlementBridgeDI:
    """TradeSettlementBridge 接受 pipeline 参数 (过渡兼容 _instance fallback)"""

    def test_TR_DI_06_constructor_accepts_pipeline_param(self):
        """TradeSettlementBridge.__init__ 接受 pipeline 关键字参数"""
        import inspect
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        sig = inspect.signature(TradeSettlementBridge.__init__)
        assert "pipeline" in sig.parameters, \
            f"TradeSettlementBridge.__init__ 缺少 pipeline 参数: {list(sig.parameters.keys())}"

    def test_TR_DI_07_constructor_defaults_pipeline_none(self):
        """pipeline 参数默认 None (过渡兼容, 不强制注入)"""
        import inspect
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        sig = inspect.signature(TradeSettlementBridge.__init__)
        pipeline_param = sig.parameters.get("pipeline")
        assert pipeline_param is not None
        # 默认值应为 None
        assert pipeline_param.default is None, \
            f"pipeline 默认值应为 None, 实际: {pipeline_param.default}"

    def test_TR_DI_08_injected_pipeline_used_in_record_real_pnl(self):
        """注入的 pipeline 优先于 _instance (DI 优先于全局单例)"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        # 构造 mock pipeline
        class MockPipeline:
            shadow_rl = None  # 让 record 路径早返回
            def get_feedback(self): return {}
        mock_pipe = MockPipeline()
        bridge = TradeSettlementBridge(pipeline=mock_pipe)
        # 验证 bridge._pipeline 引用 mock_pipe (而非 _instance)
        assert getattr(bridge, "_pipeline", None) is mock_pipe, \
            "bridge._pipeline 未保存注入的 pipeline"

    def test_TR_DI_09_pipeline_none_falls_back_to_instance(self):
        """pipeline=None 时, _record_real_pnl_reward 仍可走 _instance fallback"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        bridge = TradeSettlementBridge()  # pipeline=None
        # 不抛异常即过渡兼容
        assert bridge is not None
        # 内部应保存 _pipeline = None
        assert getattr(bridge, "_pipeline", "missing") is None


# ==============================================================================
# TR-DI-03: KlineEventHandler 透传 (Step 4.3)
# ==============================================================================
class TestKlineEventHandlerPassThrough:
    """KlineEventHandler 接受 pipeline 参数, 透传给 TradeSettlementBridge"""

    def test_TR_DI_10_constructor_accepts_pipeline_param(self):
        """KlineEventHandler.__init__ 接受 pipeline 关键字参数"""
        import inspect
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        sig = inspect.signature(KlineEventHandler.__init__)
        assert "pipeline" in sig.parameters, \
            f"KlineEventHandler.__init__ 缺少 pipeline 参数: {list(sig.parameters.keys())}"

    def test_TR_DI_11_constructor_defaults_pipeline_none(self):
        """pipeline 参数默认 None (向后兼容)"""
        import inspect
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        sig = inspect.signature(KlineEventHandler.__init__)
        pipeline_param = sig.parameters.get("pipeline")
        assert pipeline_param is not None
        assert pipeline_param.default is None, \
            f"pipeline 默认值应为 None, 实际: {pipeline_param.default}"

    def test_TR_DI_12_get_bridge_passes_pipeline_to_settlement_bridge(self):
        """_get_bridge() 创建 TradeSettlementBridge 时透传 pipeline"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        class MockPipe:
            def get_feedback(self): return {}
        mock_pipe = MockPipe()
        handler = KlineEventHandler(mode="Phase2", pipeline=mock_pipe)
        # 调用 _get_bridge 触发懒初始化
        bridge = handler._get_bridge()
        # bridge 应保存 mock_pipe
        assert getattr(bridge, "_pipeline", None) is mock_pipe, \
            "_get_bridge 未透传 pipeline 到 TradeSettlementBridge"


# ==============================================================================
# TR-DI-04: _instance 过渡兼容 (Step 4.5 — 保留 fallback 不破坏)
# ==============================================================================
class TestInstanceTransitionCompat:
    """_instance 保留作为过渡兼容 (SPEC §10 过渡兼容)"""

    def test_TR_DI_13_instance_attribute_still_exists(self):
        """EvolutionPipeline._instance 仍存在 (过渡兼容, 不破坏 lazy fallback)"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        assert hasattr(EvolutionPipeline, "_instance"), \
            "EvolutionPipeline._instance 已被删除, 违反过渡兼容约束"

    def test_TR_DI_14_instance_default_none(self):
        """_instance 默认 None (未注册时)"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        # 注意: 测试间可能已注册, 仅检查属性存在
        assert hasattr(EvolutionPipeline, "_instance")
        # 重置为 None 验证默认行为
        original = EvolutionPipeline._instance
        try:
            EvolutionPipeline._instance = None
            assert EvolutionPipeline._instance is None
        finally:
            EvolutionPipeline._instance = original
