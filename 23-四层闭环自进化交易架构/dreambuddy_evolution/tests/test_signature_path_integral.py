"""
Phase 2.5: 签名方法引擎 TDD 测试
SPEC-AGI升级蓝图.md §4.2.5

核心哲学: 万物皆数 — 任意价格路径 → 张量代数坐标（签名）
HC-AGI-11: 签名深度depth≤5
HC-AGI-12: 路径积分蒙特卡洛采样≥1000条路径
"""
from __future__ import annotations

import numpy as np
import pytest


class TestSignatureEngine:
    """路径签名计算: path → signature tensor"""

    def test_signature_returns_tensor(self):
        """签名计算返回数值张量"""
        from dreambuddy_evolution.core.signature_engine import SignatureEngine
        engine = SignatureEngine(depth=3)
        path = np.array([1.0, 1.1, 1.2, 1.15, 1.3])
        sig = engine.signature(path)
        assert isinstance(sig, np.ndarray)
        assert sig.ndim == 1
        assert len(sig) > 0

    def test_signature_constant_path_zero_increment(self):
        """常数路径的一阶签名（增量）应为0"""
        from dreambuddy_evolution.core.signature_engine import SignatureEngine
        engine = SignatureEngine(depth=3)
        path = np.array([5.0, 5.0, 5.0, 5.0])
        sig = engine.signature(path)
        # 常数路径增量=0，签名中价格增量项必须为 0
        assert np.any(np.abs(sig) < 1e-10), f"常数路径签名应含0增量项，got {sig}"

    def test_signature_monotonic_up_positive_increment(self):
        """单调上涨路径一阶签名为正"""
        from dreambuddy_evolution.core.signature_engine import SignatureEngine
        engine = SignatureEngine(depth=3)
        path = np.array([1.0, 2.0, 3.0, 4.0])
        sig = engine.signature(path)
        assert sig[0] > 0

    def test_signature_similar_paths_have_similar_signatures(self):
        """相似路径的签名距离应小于不相似路径"""
        from dreambuddy_evolution.core.signature_engine import SignatureEngine
        engine = SignatureEngine(depth=3)
        base = np.cumsum(np.random.randn(50)) * 0.01 + 100
        similar = base + np.random.randn(50) * 0.001  # 微小扰动
        different = np.cumsum(np.random.randn(50)) * 0.05 + 100  # 完全不同
        sig_base = engine.signature(base)
        sig_similar = engine.signature(similar)
        sig_different = engine.signature(different)
        dist_similar = np.linalg.norm(sig_base - sig_similar)
        dist_different = np.linalg.norm(sig_base - sig_different)
        assert dist_similar < dist_different

    def test_signature_depth_limit(self):
        """HC-AGI-11: depth不能超过5"""
        from dreambuddy_evolution.core.signature_engine import SignatureEngine
        with pytest.raises(ValueError):
            SignatureEngine(depth=6)

    def test_signature_depth_one(self):
        """depth=1时签名含路径增量项"""
        from dreambuddy_evolution.core.signature_engine import SignatureEngine
        engine = SignatureEngine(depth=1)
        path = np.array([1.0, 2.0, 3.0])
        sig = engine.signature(path)
        # 路径增量 = 3-1 = 2.0，签名中应包含此值（esig含常数项，numpy不含）
        delta = path[-1] - path[0]
        assert np.any(np.abs(sig - delta) < 1e-10), f"签名应含增量{delta}，got {sig}"

    def test_path_reconstruction_error_bounded(self):
        """签名重构路径的误差在合理范围内"""
        from dreambuddy_evolution.core.signature_engine import SignatureEngine
        engine = SignatureEngine(depth=3)
        path = np.cumsum(np.random.randn(100)) * 0.01 + 100
        error = engine.reconstruction_error(path)
        # 重构误差应为非负有限值
        assert error >= 0.0
        assert np.isfinite(error)


class TestPathIntegral:
    """路径积分: 蒙特卡洛采样 + 最小阻力路径"""

    def test_sample_paths_returns_correct_count(self):
        """HC-AGI-12: 蒙特卡洛采样≥1000条路径"""
        from dreambuddy_evolution.core.path_integral import PathIntegralEngine
        engine = PathIntegralEngine(n_paths=1000)
        paths = engine.sample_paths(
            start_price=100.0,
            horizon=20,
            volatility=0.02,
        )
        assert len(paths) >= 1000

    def test_all_paths_start_at_start_price(self):
        """所有采样路径从起始价格开始"""
        from dreambuddy_evolution.core.path_integral import PathIntegralEngine
        engine = PathIntegralEngine(n_paths=100)
        paths = engine.sample_paths(start_price=50.0, horizon=10, volatility=0.01)
        for p in paths:
            assert abs(p[0] - 50.0) < 1e-10

    def test_least_resistance_path_minimizes_action(self):
        """最小阻力路径的action应小于等于平均action"""
        from dreambuddy_evolution.core.path_integral import PathIntegralEngine
        engine = PathIntegralEngine(n_paths=500)
        paths = engine.sample_paths(start_price=100.0, horizon=20, volatility=0.02)
        best_idx, best_action = engine.find_least_resistance_path(paths)
        all_actions = [engine.compute_action(p) for p in paths]
        assert best_action <= np.mean(all_actions)
        assert 0 <= best_idx < len(paths)

    def test_action_is_non_negative(self):
        """路径action（阻力）应为非负"""
        from dreambuddy_evolution.core.path_integral import PathIntegralEngine
        engine = PathIntegralEngine(n_paths=10)
        path = np.array([100.0, 101.0, 100.5, 102.0])
        action = engine.compute_action(path)
        assert action >= 0.0

    def test_smoother_path_lower_action(self):
        """平滑路径的action应小于剧烈波动路径"""
        from dreambuddy_evolution.core.path_integral import PathIntegralEngine
        engine = PathIntegralEngine(n_paths=10)
        smooth = np.linspace(100, 110, 20)  # 平滑线性
        rough = np.array([100, 110, 95, 108, 92, 105, 88, 102, 90, 100,
                          105, 95, 108, 92, 104, 96, 101, 99, 103, 100])
        assert engine.compute_action(smooth) < engine.compute_action(rough)
