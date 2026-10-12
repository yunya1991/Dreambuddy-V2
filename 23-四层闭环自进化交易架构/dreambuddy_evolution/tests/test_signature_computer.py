"""
P1-1 RED: SignatureComputer 组件契约测试
来源: SPEC v0.3 §2.B — 从 deep_reasoning_engine.py 拆出签名计算职责

拆分目标:
- path_to_signature(price_path)->np.ndarray — 路径抽象签名
- extract_features(state_features, price_path)->list[float] — 17维签名特征
- status()->dict — 后端可用性报告
"""
from __future__ import annotations

import numpy as np
import pytest


class TestSignatureComputerContract:
    """SignatureComputer 接口契约 — RED 阶段断言模块尚未创建"""

    def test_module_importable(self):
        """模块 dreambuddy_evolution.engines.signature_computer 可导入"""
        from dreambuddy_evolution.engines.signature_computer import SignatureComputer  # noqa: F401

    def test_class_instantiates_with_default_depth(self):
        """SignatureComputer(signature_depth=3) 可实例化"""
        from dreambuddy_evolution.engines.signature_computer import SignatureComputer
        computer = SignatureComputer()
        assert computer is not None

    def test_class_instantiates_with_custom_depth(self):
        """SignatureComputer(signature_depth=2) 接收自定义深度"""
        from dreambuddy_evolution.engines.signature_computer import SignatureComputer
        computer = SignatureComputer(signature_depth=2)
        assert computer is not None


class TestPathToSignature:
    """path_to_signature 返回签名向量"""

    def test_returns_numpy_array(self):
        from dreambuddy_evolution.engines.signature_computer import SignatureComputer
        computer = SignatureComputer()
        path = np.array([100.0, 101.0, 102.0, 101.5, 103.0])
        sig = computer.path_to_signature(path)
        assert isinstance(sig, np.ndarray)
        assert sig.ndim == 1
        assert len(sig) > 0

    def test_constant_path_has_zero_increment(self):
        from dreambuddy_evolution.engines.signature_computer import SignatureComputer
        computer = SignatureComputer()
        path = np.array([50.0, 50.0, 50.0])
        sig = computer.path_to_signature(path)
        zero_items = np.where(np.abs(sig) < 1e-10)[0]
        assert len(zero_items) > 0


class TestBackendStatus:
    """status() 返回 signatory 后端可用性"""

    def test_status_returns_dict_with_signatory_key(self):
        from dreambuddy_evolution.engines.signature_computer import SignatureComputer
        computer = SignatureComputer()
        status = computer.status()
        assert isinstance(status, dict)
        assert "signatory" in status
