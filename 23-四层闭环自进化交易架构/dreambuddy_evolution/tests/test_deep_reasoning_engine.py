"""
Phase 2.3: 深度学习推理引擎 TDD 测试
SPEC-AGI升级蓝图.md §4.2.3

推理流程（无LLM·纯数据驱动）：
  1. 路径抽象：价格路径 → Signature张量
  2. 动态建模：Neural SDE
  3. 时序预测：TimesFM（不可用时降级统计预测）
  4. 多路径采样：蒙特卡洛
  5. 最优路径：最小阻力
"""
from __future__ import annotations

import numpy as np
import pytest


class TestDeepReasoningEngineInit:
    def test_engine_instantiates(self):
        """引擎可正常实例化"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        assert engine is not None

    def test_engine_reports_backend_status(self):
        """引擎报告各深度学习后端的可用状态"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        status = engine.backend_status()
        assert "timesfm" in status
        assert "signatory" in status
        assert "neural_sde" in status
        assert isinstance(status["timesfm"], bool)


class TestPathToSignature:
    def test_returns_signature_vector(self):
        """路径抽象返回签名向量"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        path = np.array([100.0, 101.0, 102.0, 101.5, 103.0])
        sig = engine.path_to_signature(path)
        assert isinstance(sig, np.ndarray)
        assert sig.ndim == 1
        assert len(sig) > 0

    def test_constant_path_zero_increment(self):
        """常数路径签名价格增量项≈0"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        path = np.array([50.0, 50.0, 50.0])
        sig = engine.path_to_signature(path)
        # 增广路径 (t, X) 签名：sig[0]=时间增量(=1)，sig[1]=价格增量(=0 for常数路径)
        # 找到价格增量分量（值接近0的项）
        zero_items = np.where(np.abs(sig) < 1e-10)[0]
        assert len(zero_items) > 0, f"常数路径签名应含0增量项，got {sig}"


class TestTimesFMPredict:
    def test_returns_forecast_array(self):
        """TimesFM预测返回预测数组（含降级）"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        history = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
        forecast = engine.timesfm_predict(history, horizon=5)
        assert isinstance(forecast, np.ndarray)
        assert len(forecast) == 5

    def test_forecast_finite_values(self):
        """预测值为有限数"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        history = np.cumsum(np.random.randn(50)) * 0.01 + 100
        forecast = engine.timesfm_predict(history, horizon=10)
        assert np.all(np.isfinite(forecast))

    def test_uptrend_forecast_positive_slope(self):
        """上涨趋势的预测均值应高于历史均值"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        history = np.linspace(100, 120, 50)  # 明确上涨
        forecast = engine.timesfm_predict(history, horizon=20)
        assert np.mean(forecast) > np.mean(history)


class TestNeuralSDEForecast:
    def test_returns_simulated_paths(self):
        """Neural SDE返回多条模拟路径"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        state = np.array([100.0, 0.02])  # [price, vol]
        paths = engine.neural_sde_forecast(state, horizon=20, n_paths=100)
        assert isinstance(paths, np.ndarray)
        assert paths.shape == (100, 21)  # n_paths x (horizon+1)

    def test_all_paths_start_at_initial_price(self):
        """所有模拟路径从初始价格开始"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        init_price = 150.0
        state = np.array([init_price, 0.01])
        paths = engine.neural_sde_forecast(state, horizon=10, n_paths=50)
        assert np.allclose(paths[:, 0], init_price)


class TestMonteCarloAndResistance:
    def test_monte_carlo_returns_n_paths(self):
        """蒙特卡洛采样返回N条路径"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        paths = engine.monte_carlo_paths(start_price=100.0, horizon=20, n_paths=500)
        assert len(paths) == 500
        assert all(len(p) == 21 for p in paths)

    def test_path_resistance_non_negative(self):
        """路径阻力非负"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        path = np.array([100.0, 101.0, 100.5, 102.0])
        r = engine.compute_path_resistance(path)
        assert r >= 0.0

    def test_smoother_path_lower_resistance(self):
        """平滑路径阻力小于剧烈波动路径"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        smooth = np.linspace(100, 110, 20)
        rough = np.array([100, 110, 95, 108, 92, 105, 88, 102, 90, 100,
                          105, 95, 108, 92, 104, 96, 101, 99, 103, 100])
        assert engine.compute_path_resistance(smooth) < engine.compute_path_resistance(rough)

    def test_find_min_resistance_path(self):
        """最小阻力路径搜索返回有效结果"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        paths = [
            np.linspace(100, 110, 15),
            np.array([100, 120, 90, 115, 85, 110, 95, 108, 92, 105, 98, 103, 100, 106, 102]),
            np.linspace(100, 108, 15),
        ]
        result = engine.find_min_resistance_path(paths)
        assert "best_index" in result
        assert "best_resistance" in result
        # HJB/变分法后端返回 best_index=-1（计算路径），argmin 后端返回有效索引
        if result.get("backend") == "argmin":
            assert 0 <= result["best_index"] < len(paths)
        else:
            assert result["best_index"] == -1  # HJB/变分法计算路径
            assert result["backend"] in ("hjb", "variational")
        assert result["best_resistance"] >= 0.0


class TestFullReasoningPipeline:
    def test_end_to_end_reasoning(self):
        """完整推理流程：签名→SDE→预测→采样→最优路径"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        price_path = np.cumsum(np.random.randn(60)) * 0.01 + 100.0

        result = engine.reason(price_path, horizon=20, n_paths=200)
        assert "signature" in result
        assert "forecast" in result
        assert "min_resistance_path" in result
        assert "min_resistance" in result
        assert result["min_resistance"] >= 0.0

    def test_fail_open_never_crash_on_empty(self):
        """空输入不崩溃（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        result = engine.reason(np.array([]), horizon=5)
        assert result is not None
        assert "min_resistance" in result

    def test_reason_uses_sde_paths(self):
        """reason() 现在调用 neural_sde_forecast（非死代码）"""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        price_path = np.cumsum(np.random.randn(60)) * 0.01 + 100.0
        result = engine.reason(price_path, horizon=10, n_paths=50)
        # SDE backend 字段存在
        assert "sde_backend" in result
        assert result["sde_backend"] in ("torchsde", "euler_maruyama", "garch", "gbm", "unavailable")
        # 路径数量正确
        assert result["n_paths"] == 50


class TestNeuralSDEFailOpen:
    """Neural SDE 4 级降级链测试."""

    def test_forecast_always_returns_array(self):
        """neural_sde_forecast 始终返回 numpy 数组（不 crash）."""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        state = np.array([100.0, 0.02])
        paths = engine.neural_sde_forecast(state, horizon=10, n_paths=50)
        assert isinstance(paths, np.ndarray)
        assert paths.shape == (50, 11)

    def test_forecast_backend_status_tracked(self):
        """forecast 后 backend_status 追踪了实际使用的后端."""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        state = np.array([100.0, 0.02])
        engine.neural_sde_forecast(state, horizon=5, n_paths=10)
        status = engine.backend_status()
        assert "neural_sde_backend" in status
        assert status["neural_sde_backend"] in ("torchsde", "euler_maruyama", "garch", "gbm", "unavailable")

    def test_paths_finite_no_nan(self):
        """生成的路径无 NaN/Inf."""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        state = np.array([100.0, 0.02])
        paths = engine.neural_sde_forecast(state, horizon=20, n_paths=100)
        assert np.all(np.isfinite(paths))

    def test_paths_start_at_init_price(self):
        """所有路径起点 = 初始价格."""
        from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
        engine = DeepReasoningEngine()
        init_price = 250.0
        state = np.array([init_price, 0.03])
        paths = engine.neural_sde_forecast(state, horizon=15, n_paths=30)
        assert np.allclose(paths[:, 0], init_price)
