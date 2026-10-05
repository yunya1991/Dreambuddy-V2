"""RED 测试: P0.1 NeuralSDEOnlineTrainer 在线学习.

解决 T7 OOS 根因 1: 数据分布漂移 (2024 与 2017-2023 分布不同).
策略: 在线 fine-tune (低 lr) + 定期 full retrain + EWC 防遗忘.

TDD 覆盖:
  P0.1-T1.1 NeuralSDEOnlineTrainer 初始化正确
  P0.1-T1.2 fine_tune() 接受新数据, 返回 report dict
  P0.1-T1.3 fine_tune() 后模型权重发生变化 (学习了新数据)
  P0.1-T2.1 rolling_window 截断过旧数据
  P0.1-T2.2 EWC loss 计算正确 (Fisher 信息 + 重要权重惩罚)
  P0.1-T3.1 should_retrain() 按间隔阈值判断
  P0.1-T3.2 full_retrain() 从头训练
  P0.1-T3.3 FAIL-OPEN: 在线训练失败回退上次权重
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_online_trainer_init():
    """P0.1-T1.1: NeuralSDEOnlineTrainer 初始化正确."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
    from dreambuddy_evolution.core.online_trainer import NeuralSDEOnlineTrainer

    model = NeuralSDEModel(device="cpu", n_regimes=3)
    trainer = NeuralSDEOnlineTrainer(
        base_model=model,
        fine_tune_lr=1e-5,
        rolling_window=24 * 365 * 2,
        ewc_lambda=1000.0,
    )
    assert trainer.fine_tune_lr == 1e-5
    assert trainer.rolling_window == 24 * 365 * 2
    assert trainer.ewc_lambda == 1000.0
    assert trainer.model is model


def test_fine_tune_returns_report():
    """P0.1-T1.2: fine_tune() 接受新数据, 返回 report dict."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
    from dreambuddy_evolution.core.online_trainer import NeuralSDEOnlineTrainer

    model = NeuralSDEModel(device="cpu", n_regimes=3)
    # 先激活模型 (模拟已训练)
    model._activated = True
    model._sample_count = 5000

    trainer = NeuralSDEOnlineTrainer(base_model=model, fine_tune_lr=1e-5)
    new_closes = np.cumsum(np.random.randn(5000)) + 50000.0
    regime_labels = np.zeros(5000, dtype=int)

    report = trainer.fine_tune(new_closes, regime_labels=regime_labels, epochs=5)
    assert isinstance(report, dict)
    assert "status" in report
    assert report["status"] == "ok"
    assert "n_windows" in report
    assert "final_loss" in report


def test_fine_tune_changes_weights():
    """P0.1-T1.3: fine_tune() 后模型权重发生变化."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
    from dreambuddy_evolution.core.online_trainer import NeuralSDEOnlineTrainer

    model = NeuralSDEModel(device="cpu", n_regimes=3)
    model._activated = True
    model._sample_count = 5000

    # 保存初始权重
    initial_weights = {
        name: p.clone() for name, p in model.drift_net.named_parameters()
    }

    trainer = NeuralSDEOnlineTrainer(base_model=model, fine_tune_lr=1e-4)
    np.random.seed(42)
    new_closes = np.cumsum(np.random.randn(2000)) + 50000.0
    regime_labels = np.random.randint(0, 3, 2000)

    trainer.fine_tune(new_closes, regime_labels=regime_labels, epochs=10)

    # 检查权重是否变化
    changed = False
    for name, p in model.drift_net.named_parameters():
        if not torch.equal(p, initial_weights[name]):
            changed = True
            break
    assert changed, "fine_tune 后权重应该变化"


def test_rolling_window_truncates_old_data():
    """P0.1-T2.1: rolling_window 截断过旧数据."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.online_trainer import NeuralSDEOnlineTrainer

    trainer = NeuralSDEOnlineTrainer.__new__(NeuralSDEOnlineTrainer)
    trainer.rolling_window = 100

    closes = np.arange(1000, dtype=float)
    truncated = trainer._apply_rolling_window(closes)
    assert len(truncated) == 100
    np.testing.assert_array_equal(truncated, closes[900:])


def test_should_retrain_by_interval():
    """P0.1-T3.1: should_retrain() 按间隔阈值判断."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from datetime import datetime, timedelta

    from dreambuddy_evolution.core.online_trainer import NeuralSDEOnlineTrainer

    trainer = NeuralSDEOnlineTrainer.__new__(NeuralSDEOnlineTrainer)
    trainer.retrain_interval_days = 90  # 每季度

    last = datetime(2024, 1, 1)
    now_89d = last + timedelta(days=89)
    now_91d = last + timedelta(days=91)

    assert trainer.should_retrain(now_89d, last) is False
    assert trainer.should_retrain(now_91d, last) is True


def test_ewc_loss_computation():
    """P0.1-T2.2: EWC loss 计算正确 (Fisher 信息 + 重要权重惩罚)."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
    from dreambuddy_evolution.core.online_trainer import NeuralSDEOnlineTrainer

    model = NeuralSDEModel(device="cpu", n_regimes=3)
    trainer = NeuralSDEOnlineTrainer(base_model=model, ewc_lambda=1000.0)

    # 模拟计算 Fisher 信息
    fisher = {
        name: torch.ones_like(p) * 0.5
        for name, p in model.drift_net.named_parameters()
    }
    optimal_params = {
        name: p.clone()
        for name, p in model.drift_net.named_parameters()
    }

    # 保存当前参数作为 optimal
    ewc_loss = trainer._ewc_loss(fisher, optimal_params)
    # 当参数 == optimal 时, EWC loss = 0
    assert float(ewc_loss) == 0.0

    # 修改参数后, EWC loss > 0
    with torch.no_grad():
        for p in model.drift_net.parameters():
            p.add_(1.0)
    ewc_loss_changed = trainer._ewc_loss(fisher, optimal_params)
    assert float(ewc_loss_changed) > 0.0
