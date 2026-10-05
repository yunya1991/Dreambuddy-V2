"""RED 测试: P2.1 MoE-SDE 架构 (每 regime 独立 expert + router).

MoE-SDE 设计:
  - n_experts (= n_regimes) 个独立 expert drift net
  - router 接收 regime one-hot + transition vector → softmax 权重
  - soft routing: 加权求和; hard routing: argmax + straight-through
  - FAIL-OPEN: router 异常或 regime=None → 均匀权重

TDD 覆盖:
  P2.1-T1.1 _MoEDriftNet 实例化: n_experts 个 expert + router
  P2.1-T1.2 soft routing: regime 已知 → 对应 expert 权重最大
  P2.1-T1.3 hard routing: argmax → 单一 expert
  P2.1-T1.4 FAIL-OPEN: regime=None → 均匀权重 (所有 expert 等权)
  P2.1-T1.5 各 expert 参数独立: 一个 expert 梯度不影响其他 expert
  P2.1-T1.6 output shape: (B, 1) drift, tanh 裁剪
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _torch_available():
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def test_moe_driftnet_instantiation():
    """P2.1-T1.1: _MoEDriftNet 有 n_experts 个 expert + router."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet

    moe = _MoEDriftNet(n_experts=3, hidden_dim=32, sig_dim=5)
    assert len(moe.experts) == 3
    assert moe.n_experts == 3
    # router 输出维度 = n_experts
    t = torch.tensor(0.0)
    y = torch.randn(4, 1)
    regime = torch.zeros(4, 3)
    regime[:, 0] = 1.0
    weights = moe._compute_weights(regime)
    assert weights.shape == (4, 3)
    # softmax 归一化
    assert torch.allclose(weights.sum(dim=-1), torch.ones(4), atol=1e-5)


def test_moe_soft_routing_regime_specific():
    """P2.1-T1.2: soft routing 下, 不同 regime 产生不同 drift."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet

    torch.manual_seed(42)
    moe = _MoEDriftNet(n_experts=3, hidden_dim=32, sig_dim=5)
    moe.eval()

    t = torch.tensor(0.0)
    y = torch.randn(2, 1)

    # regime 0 (bull)
    r0 = torch.zeros(2, 3); r0[:, 0] = 1.0
    d0 = moe(t, y, regime=r0)

    # regime 2 (bear)
    r2 = torch.zeros(2, 3); r2[:, 2] = 1.0
    d2 = moe(t, y, regime=r2)

    # 不同 regime 应该产生不同 drift (因为 expert 独立)
    assert not torch.allclose(d0, d2, atol=1e-4)


def test_moe_hard_routing():
    """P2.1-T1.3: hard routing → 单一 expert (权重 one-hot)."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet

    torch.manual_seed(42)
    moe = _MoEDriftNet(n_experts=3, hidden_dim=32, sig_dim=5, routing="hard")

    regime = torch.zeros(4, 3)
    regime[:, 1] = 1.0  # all regime=1
    weights = moe._compute_weights(regime)
    # hard routing: 每行只有一个 1
    assert weights.shape == (4, 3)
    row_sums = weights.sum(dim=-1)
    assert torch.allclose(row_sums, torch.ones(4), atol=1e-5)
    # 每行最大值为 1 (one-hot)
    assert torch.allclose(weights.max(dim=-1).values, torch.ones(4), atol=1e-5)


def test_moe_failopen_uniform_weights():
    """P2.1-T1.4: FAIL-OPEN — regime=None → 均匀权重."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet

    moe = _MoEDriftNet(n_experts=3, hidden_dim=32, sig_dim=5)
    weights = moe._compute_weights(None)
    # 均匀分布: 1/3 each
    expected = torch.ones(1, 3) / 3.0
    assert torch.allclose(weights, expected, atol=1e-5)


def test_moe_expert_independence():
    """P2.1-T1.5: 各 expert 参数独立 — 一个 expert 梯度不影响其他 expert."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet

    torch.manual_seed(42)
    moe = _MoEDriftNet(n_experts=3, hidden_dim=16, sig_dim=5)

    # 强制只有 expert 0 激活
    t = torch.tensor(0.0)
    y = torch.randn(4, 1)
    log_sig = torch.zeros(4, 5)

    # 手动构造: 只用 expert 0 的输出
    expert0_out = moe.experts[0](t, y, log_sig)
    loss = expert0_out.sum()
    loss.backward()

    # expert 0 有梯度, expert 1/2 无梯度
    for p in moe.experts[0].parameters():
        assert p.grad is not None and p.grad.abs().sum() > 0
    for p in moe.experts[1].parameters():
        assert p.grad is None or p.grad.abs().sum() == 0
    for p in moe.experts[2].parameters():
        assert p.grad is None or p.grad.abs().sum() == 0


def test_moe_output_shape_and_clip():
    """P2.1-T1.6: 输出 shape (B, 1), 经 tanh 裁剪."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet

    moe = _MoEDriftNet(n_experts=3, hidden_dim=32, sig_dim=5, clip=5.0)
    moe.eval()

    t = torch.tensor(0.0)
    y = torch.randn(8, 1)
    regime = torch.zeros(8, 3); regime[:, 0] = 1.0
    drift = moe(t, y, regime=regime)

    assert drift.shape == (8, 1)
    # tanh 裁剪: |drift| <= clip
    assert (drift.abs() <= 5.0 + 1e-5).all()


# ---------------------------------------------------------------------------
# P2.1-T2: MoE training loop
# ---------------------------------------------------------------------------

def _make_synthetic_data(n=1500, n_regimes=3):
    """生成 regime-conditional 合成数据: 不同 regime 不同漂移."""
    rng = np.random.RandomState(42)
    closes = [100.0]
    regimes = []
    for i in range(n):
        r = i % n_regimes  # 周期 regime
        regimes.append(r)
        # regime 0: 正漂移, regime 1: 零漂移, regime 2: 负漂移
        drift = {0: 0.5, 1: 0.0, 2: -0.5}[r]
        noise = rng.normal(0, 1.0)
        closes.append(closes[-1] + drift + noise)
    return np.array(closes), np.array(regimes, dtype=np.int64)


def test_moe_trainer_loss_decreases():
    """P2.1-T2.1: MoE 模型训练时 loss 下降."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer

    torch.manual_seed(42)
    closes, regimes = _make_synthetic_data()

    model = NeuralSDEModel(device="cpu", n_regimes=3, use_moe=True,
                           sig_dim=3, hidden_dim=16)
    if not model.is_available:
        pytest.skip("torch not available")

    trainer = NeuralSDETrainer(
        model=model, lr=1e-3, seq_len=16, horizon=5,
        batch_size=32, loss_type="mse",
    )
    report = trainer.train(closes, epochs=20, regime_labels=regimes,
                           regime_balance="natural")

    assert report["status"] == "ok"
    # loss 应下降
    losses = report.get("loss_history", [])
    if len(losses) >= 2:
        assert losses[-1] < losses[0]


def test_moe_router_weights_learned():
    """P2.1-T2.2: 训练后 router 权重非均匀 (学到了 regime→expert 映射)."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer

    torch.manual_seed(42)
    closes, regimes = _make_synthetic_data()

    model = NeuralSDEModel(device="cpu", n_regimes=3, use_moe=True,
                           sig_dim=3, hidden_dim=16)
    if not model.is_available:
        pytest.skip("torch not available")

    trainer = NeuralSDETrainer(
        model=model, lr=5e-3, seq_len=16, horizon=5,
        batch_size=64, loss_type="mse",
    )
    trainer.train(closes, epochs=50, regime_labels=regimes,
                  regime_balance="natural")

    # 检查 router 权重非均匀 (从均匀分布 1/3 偏离 → 学到了东西)
    drift_net = model.drift_net
    r0 = torch.zeros(1, 3); r0[0, 0] = 1.0
    w0 = drift_net._compute_weights(r0)
    uniform = torch.ones_like(w0) / 3.0
    # 权重标准差应 > 0.01 (非均匀)
    assert float(w0.detach().std()) > 0.01


def test_moe_hard_routing_train():
    """P2.1-T2.3: hard routing 模式下训练正常 (不崩溃)."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer

    torch.manual_seed(42)
    closes, regimes = _make_synthetic_data()

    model = NeuralSDEModel(device="cpu", n_regimes=3, use_moe=True,
                           moe_routing="hard", sig_dim=3, hidden_dim=16)
    if not model.is_available:
        pytest.skip("torch not available")

    trainer = NeuralSDETrainer(
        model=model, lr=1e-3, seq_len=16, horizon=5,
        batch_size=32, loss_type="mse",
    )
    report = trainer.train(closes, epochs=10, regime_labels=regimes,
                           regime_balance="natural")
    assert report["status"] == "ok"


def test_moe_forecast_regime_specific():
    """P2.1-T2.4: MoE 模型 forecast 时不同 regime 产生不同路径."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer

    torch.manual_seed(42)
    closes, regimes = _make_synthetic_data()

    model = NeuralSDEModel(device="cpu", n_regimes=3, use_moe=True,
                           sig_dim=3, hidden_dim=16)
    if not model.is_available:
        pytest.skip("torch not available")

    trainer = NeuralSDETrainer(
        model=model, lr=1e-3, seq_len=16, horizon=5,
        batch_size=32, loss_type="mse",
    )
    trainer.train(closes, epochs=20, regime_labels=regimes,
                  regime_balance="natural")

    history = closes[-50:]
    paths_bull = model.forecast(history, horizon=10, n_paths=50, regime=0)
    paths_bear = model.forecast(history, horizon=10, n_paths=50, regime=2)

    assert paths_bull is not None
    assert paths_bear is not None
    # bull 和 bear regime 的均值路径应不同
    bull_mean = paths_bull[:, 1:].mean(axis=0)
    bear_mean = paths_bear[:, 1:].mean(axis=0)
    assert not np.allclose(bull_mean, bear_mean, atol=0.5)


# ---------------------------------------------------------------------------
# P2.1-T3: FAIL-OPEN 回退
# ---------------------------------------------------------------------------

def test_moe_failopen_n_regimes_zero():
    """P2.1-T3.1: use_moe=True 但 n_regimes=0 → 回退到共享 drift_net."""
    if not _torch_available():
        pytest.skip("torch not available")
    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel, _PathSignatureDriftNet, _MoEDriftNet,
    )

    model = NeuralSDEModel(device="cpu", n_regimes=0, use_moe=True,
                           sig_dim=3, hidden_dim=16)
    if not model.is_available:
        pytest.skip("torch not available")
    # n_regimes=0 时不使用 MoE, 回退到共享 drift_net
    assert not isinstance(model.drift_net, _MoEDriftNet)
    assert isinstance(model.drift_net, _PathSignatureDriftNet)


def test_moe_failopen_regime_none_forecast():
    """P2.1-T3.2: MoE 模型 forecast 时 regime=None → 均匀权重, 输出有效."""
    if not _torch_available():
        pytest.skip("torch not available")
    import torch
    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer

    torch.manual_seed(42)
    closes, regimes = _make_synthetic_data()

    model = NeuralSDEModel(device="cpu", n_regimes=3, use_moe=True,
                           sig_dim=3, hidden_dim=16)
    if not model.is_available:
        pytest.skip("torch not available")

    trainer = NeuralSDETrainer(
        model=model, lr=1e-3, seq_len=16, horizon=5,
        batch_size=64, loss_type="mse",
    )
    trainer.train(closes, epochs=10, regime_labels=regimes,
                  regime_balance="natural")

    # regime=None → FAIL-OPEN 均匀权重, forecast 仍应返回有效路径
    history = closes[-50:]
    paths = model.forecast(history, horizon=10, n_paths=50, regime=None)
    assert paths is not None
    assert paths.shape == (50, 11)  # (n_paths, horizon+1)
    # 无 NaN
    assert not np.isnan(paths).any()
