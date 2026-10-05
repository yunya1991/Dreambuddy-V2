"""RED 测试: P3 损失函数扩展 + 正则化.

损失函数:
  - "huber": Huber loss (抗异常值, delta=1.0)
  - "return_mse": 基于收益率 (diff) 的 MSE, 而非绝对价格

正则化:
  - dropout: drift_net 隐藏层间加 nn.Dropout
  - weight_decay: AdamW 优化器的 L2 正则
  - early_stopping: 基于验证集 loss 的提前停止

TDD 覆盖:
  P3-T1.1 _compute_loss huber: 小误差 = MSE, 大误差 = 线性
  P3-T1.2 _compute_loss return_mse: 在 diff 域计算 MSE
  P3-T1.3 _compute_loss return_mse: 常量路径 → 0 loss
  P3-T2.1 drift_net dropout>0: forward 训练模式有随机性
  P3-T2.2 trainer weight_decay>0: 使用 AdamW
  P3-T2.3 trainer early_stopping: patience 触发提前停止
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_loss_huber_small_equals_mse():
    """P3-T1.1: Huber loss 小误差 (=MSE 行为)."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer

    trainer = NeuralSDETrainer.__new__(NeuralSDETrainer)
    trainer._torch = torch
    trainer.loss_type = "huber"

    path = torch.tensor([[0.1, 0.2, 0.3]])
    targets = torch.tensor([[0.1, 0.2, 0.3]])
    loss = trainer._compute_loss(path, targets)
    assert float(loss) == pytest.approx(0.0, abs=1e-6)


def test_loss_return_mse_on_diff_domain():
    """P3-T1.2: return_mse 在 diff (收益率) 域计算 MSE."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer

    trainer = NeuralSDETrainer.__new__(NeuralSDETrainer)
    trainer._torch = torch
    trainer.loss_type = "return_mse"

    # path 和 targets 的 diff 不同
    path = torch.tensor([[0.0, 0.1, 0.3]])  # diffs: [0.1, 0.2]
    targets = torch.tensor([[0.0, 0.2, 0.5]])  # diffs: [0.2, 0.3]
    loss = trainer._compute_loss(path, targets)
    expected = float(torch.mean((torch.tensor([0.1, 0.2]) - torch.tensor([0.2, 0.3])) ** 2))
    assert float(loss) == pytest.approx(expected, abs=1e-6)


def test_loss_return_mse_constant_path_zero():
    """P3-T1.3: return_mse 常量路径 (diff=0) 且 targets diff=0 → 0 loss."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer

    trainer = NeuralSDETrainer.__new__(NeuralSDETrainer)
    trainer._torch = torch
    trainer.loss_type = "return_mse"

    path = torch.tensor([[1.0, 1.0, 1.0]])  # diffs: [0, 0]
    targets = torch.tensor([[2.0, 2.0, 2.0]])  # diffs: [0, 0]
    loss = trainer._compute_loss(path, targets)
    assert float(loss) == pytest.approx(0.0, abs=1e-6)


def test_drift_net_dropout_training_mode():
    """P3-T2.1: dropout>0 时训练模式 forward 有随机性."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel, _PathSignatureDriftNet,
    )

    net = _PathSignatureDriftNet(hidden_dim=16, sig_dim=15, n_regimes=3, dropout=0.5)
    net.train()  # 训练模式

    y = torch.randn(4, 1)
    log_sig = torch.randn(4, 15)
    regime = torch.zeros(4, 3)

    # 训练模式下两次 forward 结果应不同 (dropout 随机性)
    out1 = net.forward(t=0.5, y=y, log_sig=log_sig, regime=regime)
    out2 = net.forward(t=0.5, y=y, log_sig=log_sig, regime=regime)
    assert not torch.equal(out1, out2), "训练模式下 dropout 应导致结果不同"


def test_drift_net_dropout_eval_mode_deterministic():
    """P3-T2.1b: dropout>0 时 eval 模式 forward 确定性."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    net = _PathSignatureDriftNet(hidden_dim=16, sig_dim=15, n_regimes=3, dropout=0.5)
    net.eval()

    y = torch.randn(4, 1)
    log_sig = torch.randn(4, 15)
    regime = torch.zeros(4, 3)

    out1 = net.forward(t=0.5, y=y, log_sig=log_sig, regime=regime)
    out2 = net.forward(t=0.5, y=y, log_sig=log_sig, regime=regime)
    assert torch.equal(out1, out2), "eval 模式下应确定性"


def test_trainer_weight_decay_uses_adamw():
    """P3-T2.2: weight_decay>0 时使用 AdamW."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer

    model = NeuralSDEModel(device="cpu", n_regimes=3)
    trainer = NeuralSDETrainer(
        model=model, lr=1e-4, weight_decay=1e-4,
    )
    assert isinstance(trainer._optimizer, torch.optim.AdamW)


def test_trainer_weight_decay_zero_uses_adam():
    """P3-T2.2b: weight_decay=0 (默认) 时用 Adam (向后兼容)."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer

    model = NeuralSDEModel(device="cpu", n_regimes=3)
    trainer = NeuralSDETrainer(model=model, lr=1e-4, weight_decay=0.0)
    assert isinstance(trainer._optimizer, torch.optim.Adam)


def test_early_stopping_triggers():
    """P3-T2.3: patience 触发提前停止."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer

    model = NeuralSDEModel(device="cpu", n_regimes=3)
    model._activated = True
    model._sample_count = 5000

    trainer = NeuralSDETrainer(
        model=model, lr=1e-4, patience=2, val_split=0.1,
    )
    np.random.seed(42)
    closes = np.cumsum(np.random.randn(10000)) + 50000.0
    regime_labels = np.random.randint(0, 3, 10000)

    report = trainer.train(
        closes, epochs=50, regime_labels=regime_labels, regime_balance="natural",
    )
    # patience=2 应在 50 epochs 内提前停止
    assert report.get("status") == "ok"
    assert report.get("early_stopped") is True
    assert report.get("epochs_run", 50) < 50
