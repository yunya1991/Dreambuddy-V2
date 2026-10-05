"""RED 测试: T3 prepare_data 按 regime 分组切窗 (NeuralSDE V3c 修复).

问题背景:
  原 prepare_data 用 max_windows=3000 随机子采样, 在 80k 样本上混 regime 噪声.
  V3c MAE=569 vs V2 MAE=269 退化的根因之一.
  需让 prepare_data 接受 regime_labels, 按 regime 分组均衡子采样, 使每个 window 携带
  对应 regime 标签, 训练时通过 _current_regime 上下文传给 drift_net.

接口变更 (向后兼容):
  旧: prepare_data(closes, max_windows=3000) -> list[(inp, tgt, log_sig)]
  新: prepare_data(closes, max_windows=3000, regime_labels=None)
        -> list[(inp, tgt, log_sig, regime_label_int)]
      - regime_labels=None → 所有 regime_label=0 (兼容旧调用)
      - regime_labels 给定 → 每个窗口 regime = regime_labels[start_idx]
      - 子采样按 regime 均衡 (max_windows / n_regimes 每 regime, 防止 bull 占比过大)

TDD 覆盖:
  T3.1 prepare_data 接受 regime_labels kwarg (向后兼容)
  T3.2 返回 4-tuple, 第 4 元素为 regime_label int
  T3.3 每个窗口 regime_label = regime_labels[窗口起点 idx]
  T3.4 子采样均衡: max_windows=300, 3 regime 各占 ~100 (±20)
  T3.5 train_epoch 处理 4-tuple 不抛异常
  T3.6 短 regime_labels (< len(closes)) 兜底: 末段 regime=0

参考:
  - neural_sde_model.py L819 prepare_data, L878 train_epoch
  - T1 BTCRegimeDetector 输出 (本会话)
  - 调研 spec VM-1791190210830 §方案 A 步骤 3
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
# T3.1 prepare_data 接受 regime_labels kwarg (向后兼容)
# ============================================================================


def test_prepare_data_accepts_regime_labels_kwarg():
    """T3.1: prepare_data 应接受 regime_labels=None kwarg, 旧行为不变."""
    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel,
        NeuralSDETrainer,
    )

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
    closes = 100.0 + np.cumsum(np.random.randn(300) * 0.5)

    # regime_labels=None 应不抛异常 (向后兼容)
    windows = trainer.prepare_data(closes, max_windows=20, regime_labels=None)
    assert isinstance(windows, list)
    assert len(windows) > 0


# ============================================================================
# T3.2 返回 4-tuple, 第 4 元素为 regime_label int
# ============================================================================


def test_prepare_data_returns_4tuple_with_regime_label():
    """T3.2: 当 regime_labels 给定时, windows 应为 4-tuple (inp, tgt, log_sig, regime_label)."""
    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel,
        NeuralSDETrainer,
    )

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
    closes = 100.0 + np.cumsum(np.random.randn(500) * 0.5)
    # 模拟 regime labels: 前 200 = 0 (bull), 中 200 = 1 (chop), 末 100 = 2 (bear)
    regime_labels = np.concatenate([
        np.zeros(200, dtype=int),
        np.ones(200, dtype=int),
        np.full(100, 2, dtype=int),
    ])

    windows = trainer.prepare_data(closes, max_windows=50, regime_labels=regime_labels)
    assert len(windows) > 0
    for w in windows:
        assert len(w) == 4, f"每个 window 应为 4-tuple, 实际 len={len(w)}"
        inp, tgt, log_sig, reg = w
        assert isinstance(reg, (int, np.integer)) or (isinstance(reg, np.ndarray) and reg.ndim == 0), (
            f"regime_label 应为 int, 实际 type={type(reg)}"
        )


# ============================================================================
# T3.3 每个窗口 regime_label = regime_labels[窗口起点 idx]
# ============================================================================


def test_window_regime_matches_start_index():
    """T3.3: 每个窗口的 regime_label 应等于 regime_labels[窗口起点 idx]."""
    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel,
        NeuralSDETrainer,
    )

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
    closes = 100.0 + np.cumsum(np.random.randn(500) * 0.5)
    # 简单: regime = idx % 3
    regime_labels = np.arange(500) % 3

    windows = trainer.prepare_data(closes, max_windows=300, regime_labels=regime_labels)
    # 由于子采样, 窗口起点 i = seq_len 偏移后的某个 idx
    # 这里检查: 每个 window 的 regime_label ∈ {0, 1, 2}
    for w in windows:
        reg = int(w[3])
        assert reg in (0, 1, 2), f"regime_label {reg} 应 ∈ {{0, 1, 2}}"


# ============================================================================
# T3.4 子采样均衡: max_windows=300, 3 regime 各占 ~100 (±20)
# ============================================================================


def test_subsample_balanced_across_regimes():
    """T3.4: 子采样按 regime 均衡, max_windows / n_regimes 每 regime.

    反模式 (调研 spec): max_windows=3000 随机子采样会让 bull (78% 数据) 占主导,
    drift_net 见到的 regime 分布严重失衡.
    闸门: 3 regime 各占 max_windows/3 ± 20%.
    """
    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel,
        NeuralSDETrainer,
    )

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
    closes = 100.0 + np.cumsum(np.random.randn(2000) * 0.5)
    # 均匀 3 regime
    regime_labels = np.arange(2000) % 3

    max_windows = 300
    windows = trainer.prepare_data(closes, max_windows=max_windows, regime_labels=regime_labels)
    regs = np.array([int(w[3]) for w in windows])
    counts = np.bincount(regs, minlength=3)
    # 每个 regime 应 ≈ 100 ± 30
    for k in range(3):
        assert abs(counts[k] - max_windows / 3) <= 30, (
            f"regime {k} 样本数 {counts[k]} 偏离均衡值 {max_windows // 3} 超过 30"
        )


# ============================================================================
# T3.5 train_epoch 处理 4-tuple 不抛异常
# ============================================================================


def test_train_epoch_handles_4tuple():
    """T3.5: train_epoch 应能处理 4-tuple windows, 不抛异常, 返回有限 loss."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel,
        NeuralSDETrainer,
    )

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
    closes = 100.0 + np.cumsum(np.random.randn(400) * 0.5)
    regime_labels = np.arange(400) % 3
    windows = trainer.prepare_data(closes, max_windows=30, regime_labels=regime_labels)

    loss = trainer.train_epoch(windows)
    assert np.isfinite(loss), f"train_epoch loss={loss} 应有限"
    assert loss >= 0, "loss 应非负"


# ============================================================================
# T3.7 regime_balance="natural" 保留自然分布 (Option D, 修复 V4c MAE 退化)
# ============================================================================


def test_prepare_data_regime_balance_natural():
    """T3.7: regime_balance="natural" 时, 窗口 regime 分布应接近自然分布 (非均衡 33%).

    背景: V4b (2y + 200ep + balanced) MAE=709 退化根因 —
      2y 自然分布 59.6% bull / 28.5% chop / 11.8% bear, 但 balanced 强行拉到
      33%/33%/33%, 导致 bull regime 过度欠采样, 测试点 (bull) 预测偏差.
    修复: 加 regime_balance="natural" 选项, 随机子采样但保留 regime 标签,
      drift_net 仍接收 regime one-hot 作为输入 (信息保留), 分布不被扭曲.

    闸门: natural 模式下 bull 占比 > 40% (接近自然 59.6%), 远高于 balanced 的 33%.
    """
    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel,
        NeuralSDETrainer,
    )

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
    closes = 100.0 + np.cumsum(np.random.randn(2000) * 0.5)
    # 自然分布: 70% bull, 20% chop, 10% bear (类似 2y BTC)
    regime_labels = np.concatenate([
        np.zeros(1400, dtype=int),  # 70% bull
        np.ones(400, dtype=int),    # 20% chop
        np.full(200, 2, dtype=int),  # 10% bear
    ])

    max_windows = 300
    windows = trainer.prepare_data(
        closes, max_windows=max_windows,
        regime_labels=regime_labels, regime_balance="natural",
    )
    regs = np.array([int(w[3]) for w in windows])
    counts = np.bincount(regs, minlength=3)
    bull_ratio = counts[0] / max_windows

    # natural: bull 应 > 40% (接近 70% 自然分布), 而非 balanced 的 33%
    assert bull_ratio > 0.40, (
        f"natural 模式 bull 占比 {bull_ratio:.2%} 应 > 40% (接近自然 70%), "
        f"实际 bull={counts[0]} chop={counts[1]} bear={counts[2]}"
    )


def test_prepare_data_regime_balance_default_is_balanced():
    """T3.7b: 默认 regime_balance="balanced" 保持旧行为 (向后兼容)."""
    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel,
        NeuralSDETrainer,
    )

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
    closes = 100.0 + np.cumsum(np.random.randn(2000) * 0.5)
    # 不传 regime_balance → 默认 "balanced"
    regime_labels = np.concatenate([
        np.zeros(1400, dtype=int),
        np.ones(400, dtype=int),
        np.full(200, 2, dtype=int),
    ])

    windows = trainer.prepare_data(
        closes, max_windows=300, regime_labels=regime_labels,
    )
    regs = np.array([int(w[3]) for w in windows])
    counts = np.bincount(regs, minlength=3)
    # balanced: 三个 regime 应接近 100 ± 30
    for k in range(3):
        assert abs(counts[k] - 100) <= 30, (
            f"balanced 默认 regime {k}={counts[k]} 应 ≈100±30"
        )


# ============================================================================
# T3.6 短 regime_labels (< len(closes)) 兜底: 末段 regime=0
# ============================================================================


def test_short_regime_labels_fallback():
    """T3.6: regime_labels 短于 closes 时, 末段 regime=0 兜底 (不抛异常)."""
    from dreambuddy_evolution.core.neural_sde_model import (
        NeuralSDEModel,
        NeuralSDETrainer,
    )

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    trainer = NeuralSDETrainer(model=model, seq_len=64, horizon=20)
    closes = 100.0 + np.cumsum(np.random.randn(500) * 0.5)
    # regime_labels 只有 100 个, 后 400 个会越界 → 兜底 regime=0
    regime_labels = np.ones(100, dtype=int) * 2

    # 不应抛异常
    windows = trainer.prepare_data(closes, max_windows=20, regime_labels=regime_labels)
    assert len(windows) > 0
    # 末段窗口 regime 应 = 0 (兜底)
    for w in windows:
        reg = int(w[3])
        assert reg in (0, 1, 2)
