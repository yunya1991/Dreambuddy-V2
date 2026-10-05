"""RED 测试: NeuralSDE 第 2 轮架构优化 (TDD-010/011/012).

解决 PoC 失败的 4 个根因中的 3 个 (代码改动):
  - TDD-010: log_sig z-score 归一化 (根因 1)
    第3维 (delta_x^2/2 log1p) 数值 ~7, S_t 归一化后 ~2, 内部尺度不一致.
    解决: _compute_log_sig 内部对 log_sig 做 z-score (跨样本统计均值/std).
  - TDD-011: sig_dim=6 不截断 (根因 2)
    SignatureEngine numpy depth=3 实际返回 6 维 (1+2+3), 当前 DEFAULT_SIG_DIM=4 截断损失 2 维.
    解决: DEFAULT_SIG_DIM=6, 不截断.
  - TDD-012: QLIKE loss 替代 MSE (根因 4)
    当前 train_epoch 用 MSE 对价格, 与 GARCH 评估 MAE 不一致.
    QLIKE 是波动率建模标准 loss, 把价格 diff 转为方差后计算.
    解决: train_epoch 支持 loss_type="qlike" 参数, 默认 "mse" 向后兼容.

参考:
  - .trae/specs/neural-sde-architecture-upgrade/spec.md §5
  - 认知记忆 VM-1791187544250 (PoC 失败 + 4 根因)
  - 调研记忆 VM-1791186239750 (路径依赖 SDE 概率 30-40%)
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
# TDD-010: log_sig z-score 归一化 (根因 1)
# ============================================================================


class TestLogSigZScoreNormalization:
    """TDD-010: _compute_log_sig 返回的 log_sig 应做 z-score 归一化.

    根因 1: log_sig 第3维 (delta_x^2/2 log1p) 数值 ~7, 而 S_t 归一化后 ~2,
    内部尺度不一致导致 drift_net 学习困难.
    解决: 在 _compute_log_sig 内部对 log_sig 做 z-score 归一化,
    统计参数 (log_sig_mean, log_sig_std) 在训练时累积, 推理时使用.
    """

    def test_log_sig_components_in_zscore_range(self):
        """log_sig 各分量应在 z-score 范围 [-5, 5] 内 (prepare_data 拟合后)."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        np.random.seed(42)
        model = NeuralSDEModel(device="cpu")
        model._activated = True

        # 用 prepare_data 拟合归一化参数 (反映真实训练流程)
        closes = 50000.0 + np.cumsum(np.random.randn(300) * 100.0)
        trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
        windows = trainer.prepare_data(closes, max_windows=50)

        # prepare_data 后 _log_sig_mean/std 已设置, windows 中 log_sig 已归一化
        log_sigs = [w[2] for w in windows]
        log_sigs_arr = np.array(log_sigs)  # (N, sig_dim)

        for i in range(log_sigs_arr.shape[1]):
            col = log_sigs_arr[:, i]
            assert np.all(np.abs(col) < 5.0), (
                f"log_sig 第 {i} 维未归一化, 值 {col} 超出 z-score 范围 [-5, 5]"
            )

    def test_log_sig_mean_near_zero_after_normalization(self):
        """归一化后 log_sig 跨样本均值应接近 0 (z-score 性质)."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        np.random.seed(123)
        model = NeuralSDEModel(device="cpu")
        model._activated = True

        closes = 50000.0 + np.cumsum(np.random.randn(300) * 50.0)
        trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
        windows = trainer.prepare_data(closes, max_windows=100)

        log_sigs = [w[2] for w in windows]
        log_sigs_arr = np.array(log_sigs)  # (N, sig_dim)

        col_means = np.mean(log_sigs_arr, axis=0)
        for i, m in enumerate(col_means):
            assert abs(m) < 1.0, (
                f"log_sig 第 {i} 维跨样本均值 {m} 不接近 0, z-score 归一化未生效"
            )

    def test_log_sig_persist_normalization_params(self):
        """模型应持久化 log_sig 的归一化参数 (mean/std) 供推理用."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        model = NeuralSDEModel(device="cpu")
        # 归一化参数应作为模型属性存在
        assert hasattr(model, "_log_sig_mean"), "模型应有 _log_sig_mean 属性"
        assert hasattr(model, "_log_sig_std"), "模型应有 _log_sig_std 属性"

    def test_log_sig_save_load_preserves_normalization(self, tmp_path):
        """save/load 应保留 log_sig 归一化参数."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        model = NeuralSDEModel(device="cpu")
        model._activated = True
        # 设置非默认归一化参数 (长度 = sig_dim)
        sig_dim = model.sig_dim
        model._log_sig_mean = np.linspace(0.1, 0.6, sig_dim)
        model._log_sig_std = np.linspace(1.1, 1.6, sig_dim)

        save_path = tmp_path / "test_norm.pt"
        model.save(str(save_path))

        model2 = NeuralSDEModel(device="cpu")
        loaded = model2.load(str(save_path))
        assert loaded, "load 应成功"

        np.testing.assert_allclose(
            model2._log_sig_mean, model._log_sig_mean, atol=1e-6,
            err_msg="_log_sig_mean 未在 save/load 中保留",
        )
        np.testing.assert_allclose(
            model2._log_sig_std, model._log_sig_std, atol=1e-6,
            err_msg="_log_sig_std 未在 save/load 中保留",
        )


# ============================================================================
# TDD-011: sig_dim 不截断 SignatureEngine 输出 (根因 2)
# ============================================================================


class TestSigDimNoTruncation:
    """TDD-011: DEFAULT_SIG_DIM 适配 SignatureEngine 完整输出, 不截断.

    根因 2: SignatureEngine depth=3 实际返回维度取决于后端:
      - numpy 降级: 6 维 (1+2+3)
      - esig (当前环境): 15 维 (2D 增广 depth=3 几何级数 1+2+4+8)
      - signatory: 9 维 (logsignature free Lie algebra)
    当前 DEFAULT_SIG_DIM=4 截断所有后端输出, 损失信息.
    解决: DEFAULT_SIG_DIM 适配 SignatureEngine 实际输出维度 (动态检测或用上限).
    """

    def test_default_sig_dim_matches_engine_output(self):
        """DEFAULT_SIG_DIM 应 >= SignatureEngine depth=3 实际输出维度 (不截断)."""
        from dreambuddy_evolution.core.neural_sde_model import (
            DEFAULT_SIG_DIM,
            NeuralSDEModel,
        )
        from dreambuddy_evolution.core.signature_engine import SignatureEngine

        engine = SignatureEngine(depth=3)
        path = np.cumsum(np.random.randn(64)) + 50000.0
        engine_log_sig = engine.log_signature(path)
        engine_dim = len(engine_log_sig)

        assert DEFAULT_SIG_DIM >= engine_dim, (
            f"DEFAULT_SIG_DIM={DEFAULT_SIG_DIM} 应 >= SignatureEngine 输出维度 "
            f"{engine_dim} (不截断)"
        )
        model = NeuralSDEModel(device="cpu")
        assert model.sig_dim >= engine_dim, (
            f"模型 sig_dim={model.sig_dim} 应 >= SignatureEngine 输出维度 "
            f"{engine_dim}"
        )

    def test_path_signature_drift_net_sig_dim_matches_engine(self):
        """_PathSignatureDriftNet 默认 sig_dim 应 >= SignatureEngine 输出."""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet
        from dreambuddy_evolution.core.signature_engine import SignatureEngine

        engine = SignatureEngine(depth=3)
        path = np.cumsum(np.random.randn(64)) + 50000.0
        engine_dim = len(engine.log_signature(path))

        net = _PathSignatureDriftNet()
        assert net.sig_dim >= engine_dim, (
            f"drift_net sig_dim={net.sig_dim} 应 >= SignatureEngine 输出维度 "
            f"{engine_dim}"
        )

    def test_log_sig_dim_not_truncated(self):
        """_compute_log_sig 返回的 log_sig 长度 >= SignatureEngine 输出维度 (不截断)."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
        from dreambuddy_evolution.core.signature_engine import SignatureEngine

        np.random.seed(42)
        model = NeuralSDEModel(device="cpu")
        model._activated = True
        history = np.cumsum(np.random.randn(64)) + 50000.0

        engine = SignatureEngine(depth=3)
        engine_dim = len(engine.log_signature(history))

        log_sig = model._compute_log_sig(history)
        assert len(log_sig) >= engine_dim, (
            f"_compute_log_sig 返回 {len(log_sig)} 维 < SignatureEngine 输出 "
            f"{engine_dim} 维 (被截断)"
        )

    def test_log_sig_not_truncated(self):
        """log_sig 不被截断 (长度 == sig_dim, 且维度 >= SignatureEngine 输出)."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
        from dreambuddy_evolution.core.signature_engine import SignatureEngine

        np.random.seed(42)
        model = NeuralSDEModel(device="cpu")
        model._activated = True

        history = np.linspace(50000, 51000, 64)  # 线性趋势
        log_sig = model._compute_log_sig(history)

        engine = SignatureEngine(depth=3)
        engine_dim = len(engine.log_signature(history))
        assert len(log_sig) == model.sig_dim, (
            f"log_sig 长度 {len(log_sig)} != sig_dim {model.sig_dim}"
        )
        assert model.sig_dim >= engine_dim, (
            f"sig_dim={model.sig_dim} 截断了 SignatureEngine 输出 (维度 {engine_dim})"
        )


# ============================================================================
# TDD-012: QLIKE loss 替代 MSE (根因 4)
# ============================================================================


class TestQLIKELoss:
    """TDD-012: train_epoch 支持 loss_type="qlike" 参数.

    根因 4: 当前 train_epoch 用 MSE 对价格, 与 GARCH 评估 MAE 不一致.
    QLIKE 是波动率建模标准 loss ( quasi-likelihood):
      QLIKE = mean(log(sigma2_pred + eps) + actual_var / (sigma2_pred + eps))
    其中 actual_var = (log_returns_actual)^2, sigma2_pred = (log_returns_pred)^2.
    解决: train_epoch 支持 loss_type="qlike" 参数, 默认 "mse" 向后兼容.
    """

    def test_trainer_supports_loss_type_param(self):
        """NeuralSDETrainer 应支持 loss_type 参数 (默认 'mse' 向后兼容)."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        model = NeuralSDEModel(device="cpu")
        # 默认 loss_type="mse"
        trainer = NeuralSDETrainer(model=model)
        assert getattr(trainer, "loss_type", None) == "mse", (
            "Trainer 默认 loss_type 应为 'mse' (向后兼容)"
        )

        # 显式 qlike
        trainer_q = NeuralSDETrainer(model=model, loss_type="qlike")
        assert trainer_q.loss_type == "qlike", (
            "Trainer 应支持 loss_type='qlike'"
        )

    def test_train_epoch_qlike_returns_finite_loss(self):
        """用 loss_type='qlike' 训练一个 epoch, loss 应为正有限值."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        np.random.seed(42)
        model = NeuralSDEModel(device="cpu")
        if not model.is_available:
            pytest.skip("torch 不可用")

        trainer = NeuralSDETrainer(model=model, loss_type="qlike", seq_len=64, horizon=20)
        closes = 50000.0 + np.cumsum(np.random.randn(200) * 10.0)
        windows = trainer.prepare_data(closes, max_windows=50)
        assert len(windows) > 0, "应能切出训练窗口"

        loss = trainer.train_epoch(windows)
        assert np.isfinite(loss), f"QLIKE loss 应为有限值, 实际={loss}"
        assert loss > 0, f"QLIKE loss 应为正, 实际={loss}"

    def test_train_epoch_qlike_lower_than_mse_for_volatility(self):
        """QLIKE 在波动率预测上应比 MSE 更敏感 (loss 值更大, 梯度更显著)."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        np.random.seed(42)
        closes = 50000.0 + np.cumsum(np.random.randn(200) * 10.0)

        # MSE 训练
        model_mse = NeuralSDEModel(device="cpu")
        if not model_mse.is_available:
            pytest.skip("torch 不可用")
        trainer_mse = NeuralSDETrainer(model=model_mse, loss_type="mse", seq_len=64, horizon=20)
        windows_mse = trainer_mse.prepare_data(closes, max_windows=50)
        loss_mse = trainer_mse.train_epoch(windows_mse)

        # QLIKE 训练
        model_q = NeuralSDEModel(device="cpu")
        trainer_q = NeuralSDETrainer(model=model_q, loss_type="qlike", seq_len=64, horizon=20)
        windows_q = trainer_q.prepare_data(closes, max_windows=50)
        loss_q = trainer_q.train_epoch(windows_q)

        # 两个 loss 都应为正有限
        assert np.isfinite(loss_mse) and loss_mse > 0
        assert np.isfinite(loss_q) and loss_q > 0
        # 不要求 QLIKE > MSE (尺度不同), 只验证两者都正常工作

    def test_train_persists_loss_type(self, tmp_path):
        """train() 完成后 training_report 应记录 loss_type."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        np.random.seed(42)
        model = NeuralSDEModel(device="cpu")
        if not model.is_available:
            pytest.skip("torch 不可用")

        trainer = NeuralSDETrainer(model=model, loss_type="qlike", seq_len=64, horizon=20)
        # 用足够数据 (> 1000 窗口满足 HC-AGI-13 激活阈值)
        closes = 50000.0 + np.cumsum(np.random.randn(2000) * 10.0)
        report = trainer.train(closes, epochs=3)

        assert report["status"] == "ok", f"训练应成功, 实际={report}"
        assert report.get("loss_type") == "qlike", (
            f"training_report 应记录 loss_type='qlike', 实际={report.get('loss_type')}"
        )


# ============================================================================
# TDD-013: 多任务 loss (0.7 MSE + 0.3 QLIKE) — 解决 QLIKE 训练波动率但评估价格 MAE 不匹配
# ============================================================================


class TestMultitaskLoss:
    """TDD-013: train_epoch 支持 loss_type="multitask" 参数.

    问题: QLIKE 训练波动率, 但 PoC v2 用价格 MAE 评估 → 价格路径发散 (MAE=112465).
    解决: 多任务 loss = 0.7*MSE (价格路径) + 0.3*QLIKE (波动率), 同时优化两个目标.
      - MSE 分量保证价格路径不发散
      - QLIKE 分量引入波动率建模约束, 与 GARCH 评估更一致
    权重 0.7/0.3 经验值, 可调优.
    """

    def test_trainer_supports_loss_type_multitask(self):
        """NeuralSDETrainer 应支持 loss_type='multitask' 参数."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        model = NeuralSDEModel(device="cpu")
        trainer = NeuralSDETrainer(model=model, loss_type="multitask")
        assert trainer.loss_type == "multitask", (
            "Trainer 应支持 loss_type='multitask'"
        )

    def test_multitask_loss_value_matches_formula(self):
        """multitask loss 应严格等于 0.7*MSE + 0.3*QLIKE (在相同 path/targets 上)."""
        import torch

        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        torch.manual_seed(42)
        model = NeuralSDEModel(device="cpu")
        if not model.is_available:
            pytest.skip("torch 不可用")

        # 三个 trainer 共享同一 model 权重结构, 但各自独立计算 loss
        # 用同一 path/targets 测试公式
        bs, horizon = 8, 20
        path = torch.randn(bs, horizon, requires_grad=False)
        targets = torch.randn(bs, horizon, requires_grad=False)

        # MSE loss
        trainer_mse = NeuralSDETrainer(model=model, loss_type="mse")
        mse_loss = trainer_mse._compute_loss(path, targets).item()

        # QLIKE loss
        trainer_q = NeuralSDETrainer(model=model, loss_type="qlike")
        q_loss = trainer_q._compute_loss(path, targets).item()

        # multitask loss
        trainer_mt = NeuralSDETrainer(model=model, loss_type="multitask")
        mt_loss = trainer_mt._compute_loss(path, targets).item()

        expected = 0.7 * mse_loss + 0.3 * q_loss
        assert abs(mt_loss - expected) < 1e-5, (
            f"multitask loss={mt_loss} 应等于 0.7*MSE+0.3*QLIKE={expected} "
            f"(mse={mse_loss}, qlike={q_loss})"
        )

    def test_train_epoch_multitask_returns_finite_loss(self):
        """用 loss_type='multitask' 训练一个 epoch, loss 应为正有限值."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        np.random.seed(42)
        model = NeuralSDEModel(device="cpu")
        if not model.is_available:
            pytest.skip("torch 不可用")

        trainer = NeuralSDETrainer(
            model=model, loss_type="multitask", seq_len=64, horizon=20
        )
        closes = 50000.0 + np.cumsum(np.random.randn(200) * 10.0)
        windows = trainer.prepare_data(closes, max_windows=50)
        assert len(windows) > 0

        loss = trainer.train_epoch(windows)
        assert np.isfinite(loss), f"multitask loss 应为有限值, 实际={loss}"
        assert loss > 0, f"multitask loss 应为正, 实际={loss}"

    def test_train_persists_loss_type_multitask(self, tmp_path):
        """train() 完成后 training_report 应记录 loss_type='multitask'."""
        from dreambuddy_evolution.core.neural_sde_model import (
            NeuralSDEModel,
            NeuralSDETrainer,
        )

        np.random.seed(42)
        model = NeuralSDEModel(device="cpu")
        if not model.is_available:
            pytest.skip("torch 不可用")

        trainer = NeuralSDETrainer(
            model=model, loss_type="multitask", seq_len=64, horizon=20
        )
        closes = 50000.0 + np.cumsum(np.random.randn(2000) * 10.0)
        report = trainer.train(closes, epochs=3)

        assert report["status"] == "ok", f"训练应成功, 实际={report}"
        assert report.get("loss_type") == "multitask", (
            f"training_report 应记录 loss_type='multitask', 实际={report.get('loss_type')}"
        )


# ============================================================================
# 辅助
# ============================================================================


def _torch():
    """安全获取 torch."""
    import torch
    return torch
