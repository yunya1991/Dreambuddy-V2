"""WP-M1 测试：p3_resonance_matrix 计算逻辑（纯本地，不联网）。

验证 compute_resonance 和 granger_test 的数学正确性与 fail-open 行为。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_40_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _40_SCRIPTS not in sys.path:
    sys.path.insert(0, _40_SCRIPTS)

from p3_resonance_matrix import compute_resonance, granger_test  # noqa: E402


def _synth(base_noise=0.01, beta=1.5, n=200, seed=42):
    """构造 BTC（base）和 ETH（beta * base + 噪声）的收盘价序列。"""
    rng = np.random.default_rng(seed)
    base = np.cumsum(rng.standard_normal(n) * 0.02) + 100
    derived = base * beta + rng.standard_normal(n) * base_noise
    return base.tolist(), derived.tolist()


def test_compute_resonance_returns_required_fields():
    btc, eth = _synth()
    r = compute_resonance(btc, eth)
    for key in ("corr0", "lag_profile", "beta", "down_corr", "n_samples"):
        assert key in r


def test_compute_resonance_corr0_near_one_for_synchronized():
    """强同步（微噪声）→ corr0 接近 1.0"""
    btc, eth = _synth(base_noise=0.001)
    r = compute_resonance(btc, eth)
    assert r["corr0"] > 0.9


def test_compute_resonance_lag_profile_length():
    """lag_profile 应含 6 个值（lag 0-5）"""
    btc, eth = _synth()
    r = compute_resonance(btc, eth)
    assert len(r["lag_profile"]) == 6


def test_compute_resonance_fail_open_short_sample():
    """样本 < 60 → corr0=1.0, degraded=resonance_fallback"""
    btc, eth = _synth(n=10)
    r = compute_resonance(btc, eth)
    assert r["corr0"] == 1.0
    assert r.get("degraded") == "resonance_fallback"


def test_compute_resonance_beta_sign():
    """正相关 → beta > 0"""
    btc, eth = _synth(beta=2.0)
    r = compute_resonance(btc, eth)
    assert r["beta"] > 0


def test_granger_test_returns_none_for_short_sample():
    """样本不足 → (None, None)"""
    btc, eth = _synth(n=10)
    f, p = granger_test(btc, eth)
    assert f is None
    assert p is None


def test_granger_test_p_value_in_range():
    """p 值应在 [0, 1]"""
    btc, eth = _synth(n=200)
    _, p = granger_test(btc, eth)
    assert p is not None
    assert 0.0 <= p <= 1.0


def test_granger_test_significant_for_strong_causality():
    """强因果关系 → p < 0.05"""
    rng = np.random.default_rng(123)
    # 构造：eth[t] = 0.5 * btc[t-1] + noise（明确的上游→下游因果）
    n = 300
    btc_ret = rng.standard_normal(n) * 0.02
    eth_ret = 0.5 * np.roll(btc_ret, 1) + rng.standard_normal(n) * 0.005
    eth_ret[0] = 0
    btc = (100 + np.cumsum(btc_ret)).tolist()
    eth = (100 + np.cumsum(eth_ret)).tolist()
    _, p = granger_test(btc, eth, lags=3)
    assert p is not None
    assert p < 0.05
