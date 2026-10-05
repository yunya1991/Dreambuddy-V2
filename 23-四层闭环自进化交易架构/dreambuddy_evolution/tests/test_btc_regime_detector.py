"""RED 测试: T1 BTCRegimeDetector — k=3 HMM + drawdown 观测 (NeuralSDE V3c MAE 退化修复).

问题背景:
  V3c (80k 1h 10y) MAE=569 vs V2 (17k 1h 2y) MAE=269, 退化根因:
  BTC 2017-2025 多 regime (牛/熊/DeFi夏/2022崩溃), 单一 SDE 难同时拟合.
  max_windows=3000 子采样混 regime 噪声.

解决方案 (调研 spec VM-1791190210830):
  新建 BTCRegimeDetector:
    - HMM K=3 (bull/chop/bear) — SOTA for BTC (Koki 2020, Bielejec 2026)
    - observation = drawdown from rolling max (非 log-return, Bielejec 2026 证明优)
    - 输出 regime labels per timestep, 供 NeuralSDE drift_net / prepare_data 分 regime 使用

TDD 覆盖:
  T1.1 BTCRegimeDetector 模块可导入
  T1.2 detect() 返回 ndarray, 长度 = 输入 closes 长度
  T1.3 regimes 取值 ∈ {0, 1, 2} (k=3)
  T1.4 observation 用 drawdown (非 log-return)
  T1.5 FAIL-OPEN: 短数据 / 异常输入返回 zeros (不抛异常)
  T1.6 regime 标签排序: bull=均值收益最大, bear=均值收益最小
  T1.7 历史 BTC 10y 数据 regime 与已知周期对齐 (2017 牛/2018 熊/2020 DeFi 夏/2022 熊)
  T1.8 持久化: save/load regime labels 供训练数据准备复用

参考:
  - 调研 spec 记忆 VM-1791190210830 (A 级)
  - structural_break_detector.py detect_volatility_regime (k=2 HMM 复用模式)
  - CLAUDE.md 硬约束: recall → 编码 → record → verify
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
# T1.1 BTCRegimeDetector 模块可导入
# ============================================================================


def test_btc_regime_detector_importable():
    """T1.1: BTCRegimeDetector 类可从 dreambuddy_evolution.core.btc_regime_detector 导入."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector
    assert BTCRegimeDetector is not None


# ============================================================================
# T1.2 detect() 返回 ndarray, 长度 = 输入 closes 长度
# ============================================================================


def test_detect_returns_ndarray_with_correct_length():
    """T1.2: detect(closes) 返回 ndarray, 长度 = len(closes)."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    np.random.seed(42)
    closes = 100.0 * np.exp(np.cumsum(np.random.randn(500) * 0.01))
    detector = BTCRegimeDetector()
    regimes = detector.detect(closes)
    assert isinstance(regimes, np.ndarray), "detect 应返回 np.ndarray"
    assert regimes.shape[0] == len(closes), (
        f"regimes 长度 {regimes.shape[0]} 应等于 closes 长度 {len(closes)}"
    )


# ============================================================================
# T1.3 regimes 取值 ∈ {0, 1, 2} (k=3)
# ============================================================================


def test_regimes_value_set_is_three():
    """T1.3: regime 标签取值集合 ⊆ {0, 1, 2}, 至少出现 2 种."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    np.random.seed(42)
    # 构造含牛 + 熊两段的数据
    bull = 100.0 * np.exp(np.cumsum(np.random.randn(300) * 0.005 + 0.001))
    bear = bull[-1] * np.exp(np.cumsum(np.random.randn(300) * 0.005 - 0.001))
    closes = np.concatenate([bull, bear])
    detector = BTCRegimeDetector()
    regimes = detector.detect(closes)
    unique = set(regimes.tolist())
    assert unique.issubset({0, 1, 2}), (
        f"regime 取值 {unique} 应 ⊆ {{0, 1, 2}}"
    )
    assert len(unique) >= 2, (
        f"至少应出现 2 种 regime, 实际 {len(unique)}"
    )


# ============================================================================
# T1.4 observation 用 drawdown (非 log-return)
# ============================================================================


def test_observation_is_drawdown_not_log_return():
    """T1.4: 内部 observation 应为 drawdown from rolling max.

    反模式 (调研 spec): log-return 作 HMM observation 会被 Bielejec 2026 否定,
    drawdown 更能区分 regime (牛市 dd≈0, 熊市 dd 大).
    """
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    # 类应有 _compute_drawdown 方法或 _observation_kind 属性标识
    assert hasattr(detector, "_compute_drawdown") or hasattr(detector, "observation_kind"), (
        "BTCRegimeDetector 应暴露 _compute_drawdown 或 observation_kind 以证明用 drawdown"
    )

    # 验证 _compute_drawdown 输出特征: 单调非正,牛市接近 0,回撤期大幅负
    if hasattr(detector, "_compute_drawdown"):
        # 构造: 100→150→80 (回撤 46.7%)
        closes = np.array([100.0, 120.0, 150.0, 100.0, 80.0, 90.0])
        dd = detector._compute_drawdown(closes)
        assert dd[-1] <= 0, "drawdown 应 ≤ 0"
        # 中段 (创新高时) drawdown = 0
        assert dd[2] >= -1e-9, f"创新高位置 drawdown 应=0, 实际 {dd[2]}"
        # 末段 (回撤期) drawdown 显著负
        assert dd[4] < -0.3, f"回撤 46.7% 时 drawdown 应 < -0.3, 实际 {dd[4]}"


# ============================================================================
# T1.5 FAIL-OPEN: 短数据 / 异常输入返回 zeros (不抛异常)
# ============================================================================


def test_fail_open_short_data_returns_zeros():
    """T1.5a: 数据 < min_samples 时返回全 0 (FAIL-OPEN, 不抛异常)."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector(min_samples=100)
    short_closes = np.array([100.0, 101.0, 99.0, 100.5])
    regimes = detector.detect(short_closes)
    assert regimes is not None, "短数据应返回 zeros 兜底, 不应 None"
    assert regimes.shape[0] == len(short_closes)
    assert np.all(regimes == 0), f"短数据兜底应全 0 (regime=未知), 实际 {regimes}"


def test_fail_open_nan_input_no_raise():
    """T1.5b: 含 NaN 输入不应抛异常, NaN 段填 0."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    closes = np.array([100.0, np.nan, 102.0, 103.0, np.nan] + [100.0] * 200)
    regimes = detector.detect(closes)  # 不应 raise
    assert regimes.shape[0] == len(closes)


# ============================================================================
# T1.6 regime 标签排序: bull=均值收益最大, bear=均值收益最小
# ============================================================================


def test_regime_label_ordering_bull_bear():
    """T1.6: regime 标签 0/1/2 应按均值收益排序:
    regime 0 = bull (均值收益最大), regime 2 = bear (均值收益最小).
    """
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    np.random.seed(42)
    bull = 100.0 * np.exp(np.cumsum(np.random.randn(400) * 0.005 + 0.002))
    chop = bull[-1] * np.exp(np.cumsum(np.random.randn(400) * 0.004))
    bear = chop[-1] * np.exp(np.cumsum(np.random.randn(400) * 0.005 - 0.002))
    closes = np.concatenate([bull, chop, bear])
    detector = BTCRegimeDetector()
    regimes = detector.detect(closes)
    returns = np.diff(np.log(closes))

    # 三 regime 各段平均收益
    seg_len = 400
    r_bull = np.mean(returns[:seg_len - 1])
    r_chop = np.mean(returns[seg_len:seg_len * 2 - 1])
    r_bear = np.mean(returns[seg_len * 2:])
    r_by_regime = {0: r_bull, 1: r_chop, 2: r_bear}

    # 取每 regime 标签在对应段的众数
    label_bull = int(np.bincount(regimes[:seg_len]).argmax())
    label_chop = int(np.bincount(regimes[seg_len:seg_len * 2]).argmax())
    label_bear = int(np.bincount(regimes[seg_len * 2:]).argmax())

    # bull 段标签应对应最大均值收益, bear 段对应最小
    assert r_by_regime[label_bull] >= r_by_regime[label_chop], (
        f"bull 段标签 {label_bull} 收益 {r_by_regime[label_bull]} "
        f"应 >= chop 段标签 {label_chop} 收益 {r_by_regime[label_chop]}"
    )
    assert r_by_regime[label_bear] <= r_by_regime[label_chop], (
        f"bear 段标签 {label_bear} 收益 {r_by_regime[label_bear]} "
        f"应 <= chop 段标签 {label_chop} 收益 {r_by_regime[label_chop]}"
    )


# ============================================================================
# T1.7 历史 BTC 10y 数据 regime 与已知周期对齐
# ============================================================================


def test_btc_10y_regime_alignment_known_cycles():
    """T1.7: 历史 BTC 10y 数据 regime 标签与已知周期对齐.

    BTC 2017-2025 关键周期 (数据起点 ~2017-09, $4308):
      - 2017-09 ~ 2017-12: 牛市冲顶 ($4308→$19000)
      - 2018-01 ~ 2018-12: 熊市 ($19000→$3200)
      - 2020-03 ~ 2021-11: DeFi 夏 + 牛市 ($5000→$69000)
      - 2022-01 ~ 2022-12: 熊市 ($69000→$16000)
      - 2024-01 ~ 2025: 复苏 ($16000→$86000)

    闸门 (合理阈值, HMM regime 平滑后允许过渡期):
      - 2017-09 ~ 2017-12 牛市段 (前 ~2200 点): bull (label=0) 占比 >= 40%
      - 2018 熊市段 (idx 2200~6500): bear (label=2) 占比 >= 40%
    """
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    if not data_path.exists():
        pytest.skip(f"BTC 10y 数据不存在: {data_path}")
    with open(data_path) as f:
        import json
        closes = np.array(json.load(f))

    # 1h 数据, 79941 点, 起点 ~2017-09
    # 估算各段索引 (1h = 8760 点/年):
    #   2017-09~2017-12 牛: 0 ~ 2200 (3 个月)
    #   2018 熊: 2200 ~ 8760 (10 个月)
    #   2022 熊: ~44000 ~ 53000
    detector = BTCRegimeDetector()
    regimes = detector.detect(closes)

    # 2017-09~2017-12 牛市段 bull (label=0) 占比 >= 40%
    bull_seg = regimes[:2200]
    bull_ratio = np.mean(bull_seg == 0)
    # 2018 熊市段 bear (label=2) 占比 >= 40%
    bear_seg = regimes[2200:6500]
    bear_ratio = np.mean(bear_seg == 2)

    assert bull_ratio >= 0.40, (
        f"2017-09~12 牛市段 bull 占比 {bull_ratio:.2%} 应 >= 40%"
    )
    assert bear_ratio >= 0.40, (
        f"2018 熊市段 bear 占比 {bear_ratio:.2%} 应 >= 40%"
    )


# ============================================================================
# T1.8 持久化: save/load regime labels 供训练数据准备复用
# ============================================================================


def test_persist_regime_labels(tmp_path):
    """T1.8: BTCRegimeDetector 应支持 save/load regime labels.

    NeuralSDE prepare_data 按 regime 分组切窗时需复用已计算的 regime labels.
    """
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    np.random.seed(42)
    closes = 100.0 * np.exp(np.cumsum(np.random.randn(500) * 0.01))
    detector = BTCRegimeDetector()
    regimes = detector.detect(closes)

    save_path = tmp_path / "regime_labels.npy"
    detector.save_labels(str(save_path), regimes)
    assert save_path.exists(), "save_labels 应写入文件"

    loaded = BTCRegimeDetector.load_labels(str(save_path))
    np.testing.assert_array_equal(loaded, regimes, "load_labels 应等于原 regime labels")
