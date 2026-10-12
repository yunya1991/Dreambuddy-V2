"""P1-1 拆分组件: SignatureComputer

从 deep_reasoning_engine.py 拆出的签名计算职责（内聚组件）。
承担 signatory + SignatureEngine + SignatureFeatureExtractor 三类签名相关能力。

来源: SPEC v0.3 §2.B — deep_reasoning_engine 多算法缝合体拆分
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from dreambuddy_evolution.core.signature_engine import SignatureEngine

logger = logging.getLogger(__name__)

# 模块级可选依赖 signatory/esig（FAIL-OPEN 降级到 numpy 实现）
try:
    import signatory  # type: ignore
    _SIGNATORY_AVAILABLE = True
except Exception:  # noqa: BLE001
    # signatory 与新版 torch(>2.0) 不兼容时，检查 esig 降级是否可用
    try:
        import esig  # type: ignore  # noqa: F401
        _SIGNATORY_AVAILABLE = True  # esig 可用，签名计算不降级
    except Exception:  # noqa: BLE001
        _SIGNATORY_AVAILABLE = False


class SignatureComputer:
    """路径签名计算器 — 从 DeepReasoningEngine 拆出的内聚组件.

    职责：
    - path_to_signature: 价格路径 → 签名张量（万物皆数）
    - extract_features: 17维签名特征（5状态+12签名，Phase 2 接入）
    - status: signatory 后端可用性报告
    """

    def __init__(self, signature_depth: int = 3) -> None:
        self._signature_engine = SignatureEngine(depth=signature_depth)
        self._signatory_available = _SIGNATORY_AVAILABLE
        self._signature_feature_extractor: Any = None  # 懒加载

    def path_to_signature(self, price_path: np.ndarray) -> np.ndarray:
        """价格路径 → 签名张量.

        优先用 signatory，否则 SignatureEngine 内部 numpy 降级实现。
        """
        return self._signature_engine.signature(price_path)

    def extract_features(
        self, state_features: list[float], price_path: np.ndarray
    ) -> list[float]:
        """17维签名特征提取（5状态 + 12签名，Phase 2 接入）.

        Args:
            state_features: 5个状态特征（mean/std/last/max/min of returns）
            price_path: 原始价格路径
        """
        sig_ext = self._get_signature_feature_extractor()
        if sig_ext is None:
            return []
        return sig_ext.extract(state_features, price_path)

    def _get_signature_feature_extractor(self):
        """懒加载 SignatureFeatureExtractor（Phase 2 签名特征接入）."""
        if self._signature_feature_extractor is None:
            try:
                from dreambuddy_evolution.core.signature_feature_extractor import (
                    SignatureFeatureExtractor,
                )
                self._signature_feature_extractor = SignatureFeatureExtractor()
            except Exception as e:  # noqa: BLE001
                logger.debug("[FO-AGI-03] SignatureFeatureExtractor 不可用: %s", e)
                self._signature_feature_extractor = None
        return self._signature_feature_extractor

    def status(self) -> dict[str, Any]:
        """signatory 后端可用性"""
        return {
            "signatory": self._signatory_available,
        }
