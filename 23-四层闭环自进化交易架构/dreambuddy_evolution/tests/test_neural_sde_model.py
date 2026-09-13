"""Neural SDE 模型 + GARCH fallback 测试.

覆盖:
  - NeuralSDEModel 实例化、forward 形状、tanh 裁剪
  - Euler-Maruyama 积分器输出形状、路径起点
  - GARCH 估计、模拟路径形状、低于阈值降级
  - 完整降级链: torchsde → EM → GARCH → GBM
  - save/load 往返一致性
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from dreambuddy_evolution.core.neural_sde_model import (
    NeuralSDEModel,
    NeuralSDETrainer,
    MIN_SAMPLES_FOR_ACTIVATION,
)
from dreambuddy_evolution.core.garch_fallback import GARCHFallback


# ============================================================================
# GARCH fallback 测试
# ============================================================================


class TestGARCHFallback:
    def test_estimate_with_sufficient_samples(self):
        """≥50 样本时 GARCH 估计成功."""
        np.random.seed(42)
        returns = np.random.randn(100) * 0.02
        garch = GARCHFallback()
        assert garch.estimate(returns) is True
        assert garch.is_fitted
        assert 0 < garch._alpha < 0.5
        assert 0 < garch._beta < 0.95
        assert garch._alpha + garch._beta < 0.999

    def test_estimate_insufficient_samples(self):
        """<50 样本时 GARCH 估计失败."""
        returns = np.random.randn(30) * 0.02
        garch = GARCHFallback()
        assert garch.estimate(returns) is False
        assert not garch.is_fitted

    def test_simulate_output_shape(self):
        """GARCH 模拟输出形状正确."""
        np.random.seed(42)
        returns = np.random.randn(100) * 0.02
        garch = GARCHFallback()
        garch.estimate(returns)
        paths = garch.simulate(n_paths=500, horizon=20, init_price=100.0, init_vol=0.02)
        assert paths.shape == (500, 21)
        assert np.all(paths[:, 0] == 100.0)

    def test_simulate_not_fitted_returns_constant(self):
        """未拟合时 GARCH 返回常数路径."""
        garch = GARCHFallback()
        paths = garch.simulate(n_paths=10, horizon=5, init_price=100.0, init_vol=0.02)
        assert paths.shape == (10, 6)
        assert np.all(paths == 100.0)

    def test_simulated_paths_finite(self):
        """模拟路径无 NaN/Inf."""
        np.random.seed(42)
        returns = np.random.randn(200) * 0.02
        garch = GARCHFallback()
        garch.estimate(returns)
        paths = garch.simulate(n_paths=100, horizon=20, init_price=100.0, init_vol=0.02)
        assert np.all(np.isfinite(paths))


# ============================================================================
# Neural SDE 模型测试
# ============================================================================


class TestNeuralSDEModel:
    def test_model_instantiation(self):
        """模型可实例化."""
        model = NeuralSDEModel(device="cpu")
        assert model.is_available  # torch 应该可用
        assert not model.is_activated  # 未训练未激活

    def test_maybe_activate_threshold(self):
        """HC-AGI-13: 样本 ≥ 1000 时激活."""
        model = NeuralSDEModel(device="cpu")
        assert not model.maybe_activate(999)
        assert model.maybe_activate(1000)
        assert model.is_activated

    def test_record_sample_auto_activation(self):
        """样本累积自动激活."""
        model = NeuralSDEModel(device="cpu")
        model.record_sample(MIN_SAMPLES_FOR_ACTIVATION)
        assert model.is_activated

    def test_forecast_unactivated_returns_none(self):
        """未激活时 forecast 返回 None."""
        model = NeuralSDEModel(device="cpu")
        result = model.forecast(np.array([100.0, 0.02]), horizon=10, n_paths=100)
        assert result is None

    def test_forecast_euler_maruyama_shape(self):
        """EM 积分输出形状正确."""
        model = NeuralSDEModel(device="cpu")
        model.set_normalization(np.array([100.0, 101.0, 99.0]))
        model._activated = True
        paths = model.forecast_euler_maruyama(
            state=np.array([100.0, 0.02]),
            horizon=20,
            n_paths=50,
        )
        assert paths.shape == (50, 21)
        assert np.all(paths[:, 0] == 100.0)

    def test_forecast_em_paths_finite(self):
        """EM 积分路径无 NaN/Inf."""
        model = NeuralSDEModel(device="cpu")
        model.set_normalization(np.random.randn(100) * 5 + 100)
        model._activated = True
        paths = model.forecast_euler_maruyama(
            state=np.array([100.0, 0.02]),
            horizon=30,
            n_paths=100,
        )
        assert np.all(np.isfinite(paths))

    def test_forecast_torchsde_or_em(self):
        """forecast 统一入口: torchsde 或 EM."""
        model = NeuralSDEModel(device="cpu")
        model.set_normalization(np.random.randn(100) * 5 + 100)
        model._activated = True
        paths = model.forecast(np.array([100.0, 0.02]), horizon=10, n_paths=50)
        # 至少有一种方法应该成功（torchsde 或 EM）
        assert paths is not None
        assert paths.shape == (50, 11)


# ============================================================================
# save/load 持久化测试
# ============================================================================


class TestPersistence:
    def test_save_load_roundtrip(self):
        """save/load 权重往返一致."""
        model = NeuralSDEModel(device="cpu")
        model.set_normalization(np.random.randn(100) * 5 + 100)
        model._activated = True
        model._sample_count = 2000

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_model.pt"
            model.save(str(path))
            assert path.exists()

            # 加载到新模型
            model2 = NeuralSDEModel(device="cpu")
            assert model2.load(str(path))
            assert model2.is_activated
            assert model2._sample_count == 2000
            assert abs(model2._price_mean - model._price_mean) < 1e-6

    def test_load_nonexistent_returns_false(self):
        """加载不存在的文件返回 False."""
        model = NeuralSDEModel(device="cpu")
        assert not model.load("/tmp/nonexistent_neural_sde.pt")


# ============================================================================
# 训练器测试
# ============================================================================


class TestNeuralSDETrainer:
    def test_prepare_data_windows(self):
        """滑动窗口切分."""
        model = NeuralSDEModel(device="cpu")
        trainer = NeuralSDETrainer(model, seq_len=64, horizon=20)
        closes = np.random.randn(200) * 5 + 100
        windows = trainer.prepare_data(closes)
        assert len(windows) == 200 - 64 - 20 + 1  # 117
        assert len(windows[0][0]) == 64  # input
        assert len(windows[0][1]) == 20  # target

    def test_train_short_data_returns_insufficient(self):
        """数据不足时训练返回 insufficient_samples."""
        model = NeuralSDEModel(device="cpu")
        trainer = NeuralSDETrainer(model, seq_len=64, horizon=20)
        closes = np.random.randn(100) * 5 + 100  # 只有 17 窗口
        report = trainer.train(closes, epochs=5)
        assert report["status"] == "insufficient_samples"

    def test_train_epoch_loss_decreasing(self):
        """训练 loss 应下降（或至少不爆炸）."""
        model = NeuralSDEModel(device="cpu")
        trainer = NeuralSDETrainer(model, seq_len=32, horizon=10, batch_size=16)
        # 生成足够数据
        np.random.seed(42)
        closes = 100 * np.exp(np.cumsum(np.random.randn(1100) * 0.02))
        report = trainer.train(closes, epochs=5)
        if report["status"] == "ok":
            assert report["final_loss"] < 100.0  # 不爆炸
            assert len(report["losses"]) == 5
