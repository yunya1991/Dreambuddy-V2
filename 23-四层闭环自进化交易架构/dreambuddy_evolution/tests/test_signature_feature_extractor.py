"""
RED 测试集 — signature_feature_extractor (路径签名特征)

三范式跃迁之"认知范式跃迁"：
  - 原始 5 维状态特征 → 17 维（5 状态 + 12 签名）
  - signatory → esig → numpy 三级降级
  - 时间增广路径 (t, X_t) 捕获 lead-lag
"""
from __future__ import annotations

import pytest


# --------------------------------------------------------------------------------
# RED: 模块尚未创建
# --------------------------------------------------------------------------------
def test_module_importable():
    from dreambuddy_evolution.core.signature_feature_extractor import (  # noqa: F401
        SignatureFeatureExtractor,
    )


# --------------------------------------------------------------------------------
# 特征提取
# --------------------------------------------------------------------------------
class TestFeatureExtraction:
    def test_extract_returns_17_dim_features(self):
        """提取应返回 17 维特征（5 状态 + 12 签名）."""
        from dreambuddy_evolution.core.signature_feature_extractor import SignatureFeatureExtractor
        ext = SignatureFeatureExtractor()
        import numpy as np
        price_path = np.cumsum(np.random.randn(20)) + 100
        state_features = list(np.random.rand(5))
        features = ext.extract(state_features, price_path)
        assert len(features) == 17, f"特征维度应为 17，实际 {len(features)}"

    def test_extract_includes_state_features(self):
        """提取的特征前 5 维应为原始 state_features."""
        from dreambuddy_evolution.core.signature_feature_extractor import SignatureFeatureExtractor
        ext = SignatureFeatureExtractor()
        import numpy as np
        price_path = np.cumsum(np.random.randn(20)) + 100
        state_features = [0.1, 0.2, 0.3, 0.4, 0.5]
        features = ext.extract(state_features, price_path)
        for i in range(5):
            assert abs(features[i] - state_features[i]) < 1e-6

    def test_extract_signature_part_nonzero(self):
        """签名部分（后 12 维）应非全零（路径有信息）."""
        from dreambuddy_evolution.core.signature_feature_extractor import SignatureFeatureExtractor
        ext = SignatureFeatureExtractor()
        import numpy as np
        price_path = np.cumsum(np.random.randn(20)) + 100
        state_features = list(np.zeros(5))
        features = ext.extract(state_features, price_path)
        sig_part = features[5:]
        assert any(abs(v) > 1e-6 for v in sig_part), "签名部分全零，路径信息未捕获"


# --------------------------------------------------------------------------------
# 时间增广路径
# --------------------------------------------------------------------------------
class TestTimeAugmentedPath:
    def test_time_augmented_path_adds_time_dimension(self):
        """时间增广路径 (t, X_t) 应增加时间维度."""
        from dreambuddy_evolution.core.signature_feature_extractor import SignatureFeatureExtractor
        ext = SignatureFeatureExtractor()
        import numpy as np
        price_path = np.array([100, 101, 102, 103, 104], dtype=float)
        augmented = ext._time_augment(price_path)
        # 时间增广后应是 2D 路径 (t, X_t)
        assert augmented.ndim == 2
        assert augmented.shape[1] == 2  # (t, X_t)
        assert augmented.shape[0] == len(price_path)


# --------------------------------------------------------------------------------
# FAIL-OPEN 降级
# --------------------------------------------------------------------------------
class TestFailOpenDegradation:
    def test_signatory_unavailable_degrades_to_esig_or_numpy(self):
        """signatory 不可用时应降级到 esig 或 numpy 不 crash."""
        from dreambuddy_evolution.core.signature_feature_extractor import SignatureFeatureExtractor
        ext = SignatureFeatureExtractor()
        # 强制降级
        ext._signatory_available = False
        import numpy as np
        price_path = np.cumsum(np.random.randn(20)) + 100
        features = ext.extract([0.1, 0.2, 0.3, 0.4, 0.5], price_path)
        assert len(features) == 17  # 仍返回 17 维（可能 pad zeros）

    def test_all_unavailable_pads_zeros(self):
        """所有签名库不可用时应 pad zeros 保持 17 维."""
        from dreambuddy_evolution.core.signature_feature_extractor import SignatureFeatureExtractor
        ext = SignatureFeatureExtractor()
        ext._signatory_available = False
        ext._esig_available = False
        import numpy as np
        price_path = np.cumsum(np.random.randn(20)) + 100
        features = ext.extract([0.1, 0.2, 0.3, 0.4, 0.5], price_path)
        assert len(features) == 17
        # 签名部分应全零
        assert all(abs(v) < 1e-6 for v in features[5:])

    def test_empty_price_path_returns_state_only(self):
        """空价格路径应返回 5 维状态 + 12 维零."""
        from dreambuddy_evolution.core.signature_feature_extractor import SignatureFeatureExtractor
        ext = SignatureFeatureExtractor()
        features = ext.extract([0.1, 0.2, 0.3, 0.4, 0.5], [])
        assert len(features) == 17
        assert all(abs(v) < 1e-6 for v in features[5:])


# --------------------------------------------------------------------------------
# 复用 SignatureEngine
# --------------------------------------------------------------------------------
class TestReuseSignatureEngine:
    def test_reuses_existing_signature_engine(self):
        """应复用 core/signature_engine.py 的 SignatureEngine."""
        from dreambuddy_evolution.core.signature_feature_extractor import SignatureFeatureExtractor
        ext = SignatureFeatureExtractor()
        # 应持有 _signature_engine 属性
        assert hasattr(ext, "_signature_engine") or hasattr(ext, "_sig_engine")
