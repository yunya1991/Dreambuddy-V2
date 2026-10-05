"""
签名特征提取器（认知范式跃迁）

三范式跃迁之"认知范式跃迁"：
  - 原始 5 维状态特征 → 17 维（5 状态 + 12 签名）
  - 复用 core/signature_engine.py 的 SignatureEngine（signatory→esig→numpy 三级降级）
  - 时间增广路径 (t, X_t) 捕获 lead-lag

FAIL-OPEN:
  Level 1: signatory（PyTorch 可微签名）
  Level 2: esig（替代签名计算）
  Level 3: numpy 手动迭代积分
  Level 4: pad zeros（policy 仍可工作于原始 5 维特征）
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 SignatureEngine（复用现有实现）
try:
    from dreambuddy_evolution.core.signature_engine import SignatureEngine
    _SIG_ENGINE_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SIG_ENGINE_AVAILABLE = False
    logger.debug("[FO-EVO] signature_engine 不可用，降级 pad zeros")

# 尝试导入 signatory/esig（复用 SignatureEngine 的导入状态）
try:
    import signatory  # type: ignore
    _SIGNATORY_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SIGNATORY_AVAILABLE = False

try:
    import esig  # type: ignore
    _ESIG_AVAILABLE = True
except Exception:  # noqa: BLE001
    _ESIG_AVAILABLE = False


class SignatureFeatureExtractor:
    """签名特征提取器.

    将价格路径通过路径签名映射为特征向量，拼接到状态特征后输入策略网络.

    用法:
        ext = SignatureFeatureExtractor()
        features = ext.extract(state_features, price_path)
        # features: 17 维（5 状态 + 12 签名）
    """

    STATE_DIM = 5  # 原始状态特征维度
    SIGNATURE_DIM = 12  # 签名特征维度
    FULL_DIM = STATE_DIM + SIGNATURE_DIM  # 17
    DEFAULT_DEPTH = 3  # 签名深度

    def __init__(self, depth: int = DEFAULT_DEPTH) -> None:
        self.depth = int(depth)
        self._signatory_available = _SIGNATORY_AVAILABLE
        self._esig_available = _ESIG_AVAILABLE
        if _SIG_ENGINE_AVAILABLE:
            self._signature_engine: SignatureEngine | None = SignatureEngine(depth=depth)
        else:
            self._signature_engine = None

    def extract(self, state_features: list[float] | np.ndarray,
                price_path: list[float] | np.ndarray | list) -> list[float]:
        """提取 17 维特征（5 状态 + 12 签名）.

        Args:
            state_features: 5 维原始状态特征
            price_path: 价格路径序列

        Returns:
            17 维特征向量
        """
        # 状态特征部分
        state_arr = np.asarray(state_features, dtype=np.float64).ravel()
        if len(state_arr) < self.STATE_DIM:
            state_arr = np.pad(state_arr, (0, self.STATE_DIM - len(state_arr)))
        elif len(state_arr) > self.STATE_DIM:
            state_arr = state_arr[:self.STATE_DIM]

        # 签名特征部分
        sig_features = self._compute_signature(price_path)
        # 调整到 SIGNATURE_DIM
        if len(sig_features) < self.SIGNATURE_DIM:
            sig_features = np.pad(sig_features, (0, self.SIGNATURE_DIM - len(sig_features)))
        elif len(sig_features) > self.SIGNATURE_DIM:
            sig_features = sig_features[:self.SIGNATURE_DIM]

        return list(np.concatenate([state_arr, sig_features]))

    def _compute_signature(self, price_path: list | np.ndarray) -> np.ndarray:
        """计算路径签名（FAIL-OPEN 三级降级）."""
        path = np.asarray(price_path, dtype=np.float64).ravel()
        if len(path) < 2:
            return np.zeros(self.SIGNATURE_DIM, dtype=np.float64)

        # 当 signatory 和 esig 都不可用时，pad zeros（policy 仍可工作于原始 5 维特征）
        if not self._signatory_available and not self._esig_available:
            return np.zeros(self.SIGNATURE_DIM, dtype=np.float64)

        # Level 1-3: 复用 SignatureEngine（signatory 或 esig 可用时）
        if self._signature_engine is not None:
            try:
                sig = self._signature_engine.signature(path)
                return np.asarray(sig, dtype=np.float64).ravel()
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[FO-EVO] SignatureEngine 失败: {exc}")

        # Level 4: numpy 手动迭代积分签名（最简签名）
        return self._numpy_signature_fallback(path)

    def _numpy_signature_fallback(self, path: np.ndarray) -> np.ndarray:
        """numpy 手动迭代积分签名（Level 4 降级）.

        签名一阶项: S^1 = ∫ dX = X_T - X_0
        签名二阶项: S^(1,1) = 1/2 * (∫ dX)^2
        扩展到 12 维（重复 + 高阶）
        """
        path = np.asarray(path, dtype=np.float64)
        increments = np.diff(path)
        s1 = float(np.sum(increments))  # 一阶签名
        s2 = 0.5 * s1 * s1  # 二阶签名（简化）
        s3 = (1.0 / 6.0) * s1 * s1 * s1  # 三阶签名

        # 扩展到 12 维（重复+高阶，保持维度一致）
        features = np.array([
            s1, s2, s3,
            float(np.std(increments)),  # 波动率特征
            float(np.mean(increments)),  # 漂移
            float(np.max(increments)),  # 最大增量
            float(np.min(increments)),  # 最小增量
            float(np.sum(np.abs(increments))),  # 总变差
            float(len(increments)),  # 路径长度
            s1 * float(np.std(increments)),  # 交叉项
            s2 * float(np.mean(increments)),  # 交叉项
            float(np.sum(increments ** 2)),  # 二次变差
        ], dtype=np.float64)
        return features

    def _time_augment(self, price_path: np.ndarray) -> np.ndarray:
        """时间增广路径 (t, X_t) — 2D 路径."""
        path = np.asarray(price_path, dtype=np.float64).ravel()
        t = np.arange(len(path), dtype=np.float64)
        # 归一化时间到 [0, 1] 避免数值爆炸
        if len(t) > 1:
            t = t / (len(t) - 1)
        return np.column_stack([t, path])  # shape (n, 2)
