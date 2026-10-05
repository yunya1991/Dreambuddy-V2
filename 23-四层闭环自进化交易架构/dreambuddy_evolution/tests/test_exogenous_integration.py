"""RED 测试: P1 外生力量接入 NeuralSDE drift_net (E1-E5).

方案文档: 23-四层闭环自进化交易架构/PLAN-exogenous-integration.md §三

集成核心:
  - prepare_data 新增 exogenous_series: Optional[np.ndarray] (shape=(N,9)) 参数
  - 每窗口取末尾点 9 维向量拼到 drift_net 输入
  - drift_net.forward 新增 exogenous 输入 +9 维
  - train() / forecast() 透传
  - FAIL-OPEN: exogenous_series=None → 零向量, 行为等价当前

TDD 覆盖:
  E1   build_exogenous_series() 辅助函数
  E2   prepare_data(exogenous_series=...) 接受参数 + 窗口元组扩展
  E3   _PathSignatureDriftNet.forward + _MoEDriftNet.forward 接受 exogenous
  E4   train(exogenous_series=...) 透传
  E5   forecast(exogenous_snapshot=...) 透传
  FO   FAIL-OPEN: exogenous_series=None 行为等价当前 (零回归)

参考:
  - neural_sde_model.py L1167-1304 (prepare_data)
  - neural_sde_model.py L164-248 (_PathSignatureDriftNet.forward)
  - neural_sde_model.py L371-407 (_MoEDriftNet.forward)
  - exogenous_data_bridge.py (ExogenousDataBridge)
  - exogenous_strength_evaluator.py (9 维输出)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ============================================================================
# E1: build_exogenous_series 辅助函数
# ============================================================================


class TestBuildExogenousSeries:
    """E1: exogenous_data_bridge.build_exogenous_series()."""

    def test_build_exogenous_series_exists(self):
        """E1.1: build_exogenous_series 函数存在."""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_exogenous_series,
        )
        assert callable(build_exogenous_series)

    def test_build_exogenous_series_shape(self):
        """E1.2: 返回 shape=(len(closes), 9) 的 [0,1] 标准化数组."""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_exogenous_series,
        )
        closes = np.linspace(100.0, 200.0, 200)
        series = build_exogenous_series(closes)
        assert series is not None
        assert isinstance(series, np.ndarray)
        assert series.shape == (200, 9), f"shape={series.shape}, 期望 (200, 9)"
        # 值域 [0, 1] (允许微小数值误差)
        assert np.all(series >= -1e-6), f"最小值 {series.min()} < 0"
        assert np.all(series <= 1.0 + 1e-6), f"最大值 {series.max()} > 1"

    def test_build_exogeneous_with_bridge_none(self):
        """E1.3: bridge=None 时仍能从 closes 衍生技术面子集, 其余维度中性值 0.5."""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_exogenous_series,
        )
        closes = np.linspace(100.0, 200.0, 250)
        series = build_exogenous_series(closes, bridge=None)
        assert series.shape == (250, 9)
        # 至少有非零维度 (技术面 long = ma_200 偏离度)
        non_zero_count = int(np.sum(np.any(series != 0.5, axis=1)))
        assert non_zero_count > 0, "bridge=None 时应有非中性值维度"

    def test_build_exogenous_short_closes(self):
        """E1.4: closes 过短时仍返回正确 shape, 不抛异常 (FAIL-OPEN)."""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_exogenous_series,
        )
        closes = np.array([100.0, 101.0, 102.0])
        series = build_exogenous_series(closes)
        assert series.shape == (3, 9)


# ============================================================================
# E2: prepare_data 接受 exogenous_series 参数
# ============================================================================


class TestPrepareDataExogenous:
    """E2: NeuralSDETrainer.prepare_data(exogenous_series=...)."""

    def _make_model(self):
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
        # 显式 opt-in 9 维外生力量 (P1 设计: 默认 exogenous_dim=0 = 向后兼容)
        return NeuralSDEModel(
            n_regimes=3, use_transition=False, dropout=0.0,
            use_exogenous=True, exogenous_dim=9,
        )

    def test_prepare_data_accepts_exogenous_kwarg(self):
        """E2.1: prepare_data 接受 exogenous_series 关键字参数."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer
        model = self._make_model()
        trainer = NeuralSDETrainer(model, seq_len=32, horizon=8)
        closes = np.linspace(100.0, 200.0, 200)
        exo = np.full((200, 9), 0.5)
        # 不应抛 TypeError
        windows = trainer.prepare_data(closes, exogenous_series=exo)
        assert len(windows) > 0

    def test_prepare_data_window_tuple_has_5_elements(self):
        """E2.2: 窗口元组扩展为 5 元素 (含 exo 向量)."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer
        model = self._make_model()
        trainer = NeuralSDETrainer(model, seq_len=32, horizon=8)
        closes = np.linspace(100.0, 200.0, 200)
        exo = np.full((200, 9), 0.5)
        windows = trainer.prepare_data(closes, exogenous_series=exo)
        # 第一个窗口应为 5-tuple
        win = windows[0]
        assert len(win) == 5, f"窗口元组长度 {len(win)}, 期望 5"
        # 第 5 个元素应是 (9,) 数组
        exo_vec = win[4]
        assert isinstance(exo_vec, np.ndarray)
        assert exo_vec.shape == (9,), f"exo_vec shape={exo_vec.shape}"

    def test_prepare_data_exogenous_alignment(self):
        """E2.3: 第 i 个窗口的 exo = exogenous_series[start + seq_len - 1]
        (对齐 regime 的取法)."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer
        model = self._make_model()
        trainer = NeuralSDETrainer(model, seq_len=32, horizon=8)
        closes = np.linspace(100.0, 200.0, 200)
        # 构造唯一值 exo, 便于验证对齐
        exo = np.tile(np.arange(200).reshape(-1, 1), (1, 9)) / 200.0
        windows = trainer.prepare_data(
            closes, exogenous_series=exo, max_windows=9999,
        )
        # windows[0] 的起点 i=0, 末尾 idx = 0 + seq_len - 1 = 31
        win0 = windows[0]
        exo_vec0 = win0[4]
        expected0 = exo[31]  # = 31/200 = 0.155
        np.testing.assert_allclose(exo_vec0, expected0, atol=1e-6)

    def test_prepare_data_exogenous_none_fallback(self):
        """E2.4: exogenous_series=None → 窗口 exo = 零向量 (FAIL-OPEN)."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer
        model = self._make_model()
        trainer = NeuralSDETrainer(model, seq_len=32, horizon=8)
        closes = np.linspace(100.0, 200.0, 200)
        windows = trainer.prepare_data(closes, exogenous_series=None)
        # 窗口元组仍为 5-tuple, 第 5 项 = 零向量
        win = windows[0]
        assert len(win) == 5
        exo_vec = win[4]
        assert isinstance(exo_vec, np.ndarray)
        np.testing.assert_allclose(exo_vec, np.zeros(9), atol=1e-6)

    def test_prepare_data_exogenous_short_series(self):
        """E2.5: exogenous_series 长度 < closes → 截断/补零 (FAIL-OPEN)."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer
        model = self._make_model()
        trainer = NeuralSDETrainer(model, seq_len=32, horizon=8)
        closes = np.linspace(100.0, 200.0, 200)
        exo_short = np.full((50, 9), 0.7)  # 比 closes 短
        # 不应抛异常
        windows = trainer.prepare_data(closes, exogenous_series=exo_short)
        assert len(windows) > 0
        # 越界点 (i+seq_len-1 >= 50) 应回退到零向量
        win_last = windows[-1]
        exo_vec = win_last[4]
        assert exo_vec.shape == (9,)


# ============================================================================
# E3: drift_net forward 接受 exogenous 输入
# ============================================================================


class TestDriftNetExogenousForward:
    """E3: _PathSignatureDriftNet + _MoEDriftNet forward 接受 exogenous."""

    def test_path_sig_drift_net_forward_accepts_exogenous(self):
        """E3.1: _PathSignatureDriftNet.forward(t, y, log_sig, regime, transition, exogenous)
        接受 exogenous 参数."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet
        # exogenous_dim=9 显式开启 (默认 0 = 关闭, 向后兼容)
        net = _PathSignatureDriftNet(
            hidden_dim=32, sig_dim=4, n_regimes=3, exogenous_dim=9,
        )
        y = torch.zeros(4, 1)
        log_sig = torch.zeros(4, 4)
        regime = torch.tensor([[1.0, 0.0, 0.0]] * 4)
        exo = torch.full((4, 9), 0.5)
        # 不应抛 TypeError
        out = net(
            torch.tensor(0.5), y, log_sig=log_sig,
            regime=regime, exogenous=exo,
        )
        assert out.shape == (4, 1)
        assert torch.isfinite(out).all()

    def test_path_sig_drift_net_in_dim_includes_exogenous(self):
        """E3.2: exogenous_dim=9 时, 第一层 in_features 应包含 +9 维."""
        from dreambuddy_evolution.core.neural_sde_model import (
            _PathSignatureDriftNet,
            DEFAULT_SIG_DIM,
        )
        net = _PathSignatureDriftNet(n_regimes=3, exogenous_dim=9)
        expected = 3 + DEFAULT_SIG_DIM + 3 + 9
        first_linear = net.net[0]
        assert first_linear.in_features == expected, (
            f"in_features={first_linear.in_features}, 期望 {expected} "
            f"(3 + sig_dim={DEFAULT_SIG_DIM} + n_regimes=3 + exo=9)"
        )

    def test_path_sig_drift_net_exogenous_dim_zero_backward_compat(self):
        """E3.2b: exogenous_dim=0 (默认) → in_dim 不含 exo (向后兼容旧 ckpt)."""
        from dreambuddy_evolution.core.neural_sde_model import (
            _PathSignatureDriftNet,
            DEFAULT_SIG_DIM,
        )
        net = _PathSignatureDriftNet(n_regimes=3)  # 默认 exogenous_dim=0
        expected = 3 + DEFAULT_SIG_DIM + 3  # 不含 exo
        first_linear = net.net[0]
        assert first_linear.in_features == expected, (
            f"默认 exogenous_dim=0 时 in_features={first_linear.in_features}, "
            f"期望 {expected} (向后兼容)"
        )

    def test_path_sig_drift_net_exogenous_none_fallback(self):
        """E3.3: exogenous=None → pad zeros (FAIL-OPEN, 行为等价 exo=None)."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet
        net = _PathSignatureDriftNet(
            hidden_dim=32, sig_dim=4, n_regimes=3, exogenous_dim=9,
        )
        y = torch.zeros(4, 1)
        # exogenous=None 不应抛
        out_none = net(torch.tensor(0.5), y, exogenous=None)
        assert out_none.shape == (4, 1)
        assert torch.isfinite(out_none).all()

    def test_moe_drift_net_forward_accepts_exogenous(self):
        """E3.4: _MoEDriftNet.forward 接受 exogenous 参数."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet
        net = _MoEDriftNet(
            n_experts=3, hidden_dim=32, sig_dim=4,
            n_transition=0, routing="hard", exogenous_dim=9,
        )
        y = torch.zeros(4, 1)
        log_sig = torch.zeros(4, 4)
        regime = torch.tensor([[1.0, 0.0, 0.0]] * 4)
        exo = torch.full((4, 9), 0.5)
        out = net(
            torch.tensor(0.5), y,
            log_sig=log_sig, regime=regime, exogenous=exo,
        )
        assert out.shape == (4, 1)
        assert torch.isfinite(out).all()

    def test_moe_drift_net_exogenous_none_fallback(self):
        """E3.5: _MoEDriftNet exogenous=None → pad zeros (FAIL-OPEN)."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet
        net = _MoEDriftNet(
            n_experts=3, hidden_dim=32, sig_dim=4, exogenous_dim=9,
        )
        y = torch.zeros(4, 1)
        out = net(torch.tensor(0.5), y, exogenous=None)
        assert out.shape == (4, 1)


# ============================================================================
# E4: train 透传 exogenous_series
# ============================================================================


class TestTrainExogenousPassthrough:
    """E4: NeuralSDETrainer.train(exogenous_series=...)."""

    def test_train_accepts_exogenous_kwarg(self):
        """E4.1: train 接受 exogenous_series 关键字参数, 不抛 TypeError."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel, NeuralSDETrainer,
        )
        # use_exogenous=True 显式开启, drift_net 输入 +9 维 exo
        model = NeuralSDEModel(
            n_regimes=3, use_moe=True, moe_routing="hard",
            use_exogenous=True,
        )
        trainer = NeuralSDETrainer(
            model, seq_len=32, horizon=8, batch_size=16,
            loss_type="return_mse", weight_decay=1e-4,
        )
        # 构造合成数据: 1000+ 窗口需要 ~1000+32+8 closes
        closes = np.cumsum(np.random.randn(1100) * 0.5 + 0.01) + 100.0
        exo = np.random.uniform(0.0, 1.0, size=(1100, 9))
        report = trainer.train(
            closes, epochs=2, exogenous_series=exo,
        )
        assert "status" in report
        # 应该 ok 或 insufficient_samples (不应是 TypeError)
        assert report["status"] in ("ok", "insufficient_samples"), (
            f"train 返回 status={report.get('status')}"
        )

    def test_train_exogenous_none_no_regression(self):
        """E4.2: train(exogenous_series=None) 行为等价当前 (FAIL-OPEN)."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel, NeuralSDETrainer,
        )
        # use_exogenous=False (默认), 行为等价当前最佳配置
        model = NeuralSDEModel(n_regimes=3, use_moe=True, moe_routing="hard")
        trainer = NeuralSDETrainer(
            model, seq_len=32, horizon=8, batch_size=16,
            loss_type="return_mse", weight_decay=1e-4,
        )
        closes = np.cumsum(np.random.randn(1100) * 0.5 + 0.01) + 100.0
        report = trainer.train(closes, epochs=2, exogenous_series=None)
        assert report["status"] in ("ok", "insufficient_samples")


# ============================================================================
# E5: forecast 接受 exogenous_snapshot
# ============================================================================


class TestForecastExogenousSnapshot:
    """E5: NeuralSDEModel.forecast(exogenous_snapshot=...)."""

    def _train_mini(self, model, trainer, closes, exo=None):
        """mini 训练以激活模型 (满足 MIN_SAMPLES_FOR_ACTIVATION)."""
        trainer.train(closes, epochs=1, exogenous_series=exo)
        model._activated = True  # 强制激活以便 forecast 可用

    def test_forecast_accepts_exogenous_snapshot(self):
        """E5.1: forecast 接受 exogenous_snapshot 关键字参数."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel, NeuralSDETrainer,
        )
        model = NeuralSDEModel(
            n_regimes=3, use_moe=True, moe_routing="hard",
            use_exogenous=True,
        )
        trainer = NeuralSDETrainer(
            model, seq_len=32, horizon=8, batch_size=16,
        )
        closes = np.cumsum(np.random.randn(1100) * 0.5 + 0.01) + 100.0
        exo = np.full((1100, 9), 0.5)
        self._train_mini(model, trainer, closes, exo=exo)
        history = closes[-64:]
        exo_snap = np.full(9, 0.5)
        # 不应抛 TypeError
        paths = model.forecast(
            history, horizon=4, n_paths=8,
            exogenous_snapshot=exo_snap,
        )
        # forecast 可能返回 None (torchsde 失败) 或 array
        if paths is not None:
            assert paths.ndim == 2
            assert paths.shape[1] == 5  # horizon+1

    def test_forecast_exogenous_none(self):
        """E5.2: forecast(exogenous_snapshot=None) 不抛 (FAIL-OPEN)."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel, NeuralSDETrainer,
        )
        # use_exogenous=False (默认), exogenous_snapshot=None 应等价当前
        model = NeuralSDEModel(n_regimes=3, use_moe=True, moe_routing="hard")
        trainer = NeuralSDETrainer(model, seq_len=32, horizon=8, batch_size=16)
        closes = np.cumsum(np.random.randn(1100) * 0.5 + 0.01) + 100.0
        self._train_mini(model, trainer, closes)
        history = closes[-64:]
        paths = model.forecast(
            history, horizon=4, n_paths=8, exogenous_snapshot=None,
        )
        if paths is not None:
            assert paths.ndim == 2


# ============================================================================
# FO: FAIL-OPEN 综合验证 (零回归)
# ============================================================================


class TestFailOpenExogenous:
    """FAIL-OPEN: exogenous_series=None 行为等价当前最佳配置."""

    def test_no_exogenous_signature_in_ckpt(self):
        """FO.1: use_exogenous=False 的 ckpt 可加载 (向后兼容旧模型)."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        import tempfile
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel, NeuralSDETrainer,
        )
        # 旧模型 (use_exogenous=False)
        model = NeuralSDEModel(n_regimes=3, use_moe=True, moe_routing="hard")
        trainer = NeuralSDETrainer(model, seq_len=32, horizon=8, batch_size=16)
        closes = np.cumsum(np.random.randn(1100) * 0.5 + 0.01) + 100.0
        trainer.train(closes, epochs=1, exogenous_series=None)
        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as f:
            path = f.name
        try:
            model.save(path)
            # 加载到同样配置的模型
            model2 = NeuralSDEModel(
                n_regimes=3, use_moe=True, moe_routing="hard",
            )
            ok = model2.load(path)
            assert ok, "load 应成功"
            # 加载到 use_exogenous=True 的模型应触发 rebuild
            model3 = NeuralSDEModel(
                n_regimes=3, use_moe=True, moe_routing="hard",
                use_exogenous=True,
            )
            ok3 = model3.load(path)
            assert ok3, "load 应成功 (rebuild)"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_drift_net_exogenous_zero_eq_none(self):
        """FO.2: exogenous=zeros 与 exogenous=None drift 输出等价 (FAIL-OPEN)."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not available")

        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet
        net = _PathSignatureDriftNet(
            hidden_dim=32, sig_dim=4, n_regimes=3, exogenous_dim=9,
        )
        y = torch.zeros(4, 1)
        out_none = net(torch.tensor(0.5), y, exogenous=None)
        out_zero = net(
            torch.tensor(0.5), y,
            exogenous=torch.zeros(4, 9),
        )
        torch.testing.assert_allclose(out_none, out_zero)
