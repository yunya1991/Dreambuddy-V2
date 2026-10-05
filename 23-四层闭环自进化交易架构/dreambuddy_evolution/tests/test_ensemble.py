"""RED 测试: P1.1 熵加权 SDE+GARCH Ensemble.

结合 P0.2 (regime_uncertainty) + P1.1 (ensemble):
  final_pred = w * SDE_pred + (1-w) * GARCH_pred
  w = f(entropy): 熵越高, SDE 权重越低 (过拟合风险高时降权)

TDD 覆盖:
  P1.1-T1.1 entropy_to_weight: 熵=0 → w=1 (全信 SDE)
  P1.1-T1.2 entropy_to_weight: 熵=max → w=0 (全信 GARCH)
  P1.1-T1.3 entropy_to_weight: 熵在中间 → w 在 (0,1)
  P1.1-T2.1 ensemble_forecast: 合并 SDE 和 GARCH 预测
  P1.1-T2.2 ensemble_forecast: SDE 不可用时回退 GARCH
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_entropy_to_weight_zero():
    """P1.1-T1.1: 熵=0 → w=1 (全信 SDE)."""
    from dreambuddy_evolution.core.ensemble import entropy_to_weight
    w = entropy_to_weight(entropy=0.0, n_regimes=3)
    assert w == 1.0


def test_entropy_to_weight_max():
    """P1.1-T1.2: 熵=max → w=0 (全信 GARCH)."""
    from dreambuddy_evolution.core.ensemble import entropy_to_weight
    import math
    max_entropy = math.log(3)
    w = entropy_to_weight(entropy=max_entropy, n_regimes=3)
    assert w == pytest.approx(0.0, abs=1e-6)


def test_entropy_to_weight_mid():
    """P1.1-T1.3: 熵在中间 → w 在 (0,1)."""
    from dreambuddy_evolution.core.ensemble import entropy_to_weight
    import math
    mid_entropy = math.log(3) / 2
    w = entropy_to_weight(entropy=mid_entropy, n_regimes=3)
    assert 0.0 < w < 1.0
    assert w == pytest.approx(0.5, abs=0.01)


def test_ensemble_forecast_combines():
    """P1.1-T2.1: ensemble_forecast 合并 SDE 和 GARCH 预测."""
    from dreambuddy_evolution.core.ensemble import ensemble_forecast

    sde_pred = np.array([100.0, 101.0, 102.0])
    garch_pred = np.array([99.0, 100.0, 101.0])
    # w=0.5 → 平均
    result = ensemble_forecast(sde_pred, garch_pred, sde_weight=0.5)
    expected = 0.5 * sde_pred + 0.5 * garch_pred
    np.testing.assert_allclose(result, expected)


def test_ensemble_forecast_sde_none_fallback():
    """P1.1-T2.2: SDE 不可用时回退 GARCH."""
    from dreambuddy_evolution.core.ensemble import ensemble_forecast

    garch_pred = np.array([99.0, 100.0, 101.0])
    result = ensemble_forecast(None, garch_pred, sde_weight=0.5)
    np.testing.assert_allclose(result, garch_pred)
