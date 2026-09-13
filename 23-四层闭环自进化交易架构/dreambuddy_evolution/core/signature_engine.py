"""
Phase 2.5: 签名方法引擎
SPEC-AGI升级蓝图.md §4.2.5

核心哲学: 万物皆数 — 任意价格路径 → 张量代数坐标（签名）
蓝本: signatory (PyTorch可微签名, ICLR 2021)

签名定义: 路径 X(t) 的签名 S(X) 是张量代数中的元素，
  S^i1 = ∫ dX^i1
  S^(i1,i2) = ∫∫ dX^i1 dX^i2
  ...
签名是路径的"万能表示"：两条路径签名相同 ⟺ 路径等价（树状等价）.

HC-AGI-11: 签名深度depth≤5
FAIL-OPEN: signatory不可用时用numpy手动计算迭代积分.
"""
from __future__ import annotations

import logging
import math

import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 signatory（可选依赖，FAIL-OPEN）
try:
    import signatory  # type: ignore
    import torch
    _SIGNATORY_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SIGNATORY_AVAILABLE = False
    logger.debug("[FO-AGI-02] signatory 不可用，尝试esig降级")

# 尝试导入 esig（signatory 替代，签名计算）
try:
    import esig  # type: ignore
    _ESIG_AVAILABLE = True
except Exception:  # noqa: BLE001
    _ESIG_AVAILABLE = False
    logger.debug("[FO-AGI-02] esig 不可用，使用numpy签名降级实现")


class SignatureEngine:
    """路径签名计算器.

    将价格路径映射为签名张量（万物皆数）.
    使用时间增广路径 (t, X_t) 以捕获路径形状（lead-lag关系）.
    """

    MAX_DEPTH = 5  # HC-AGI-11

    def __init__(self, depth: int = 3) -> None:
        if depth > self.MAX_DEPTH:
            raise ValueError(f"depth={depth} 超过 HC-AGI-11 上限 {self.MAX_DEPTH}")
        if depth < 1:
            raise ValueError("depth 必须 ≥ 1")
        self.depth = int(depth)
        self._signatory_available = _SIGNATORY_AVAILABLE

    def signature(self, path: np.ndarray) -> np.ndarray:
        """计算路径的签名张量.

        Args:
            path: 1D 价格序列 [p_0, p_1, ..., p_n]

        Returns:
            1D numpy 数组，签名特征.
        """
        path = np.asarray(path, dtype=np.float64).ravel()
        if len(path) < 2:
            return np.zeros(self.depth, dtype=np.float64)

        if self._signatory_available:
            return self._signatory_signature(path)
        if _ESIG_AVAILABLE:
            return self._esig_signature(path)
        return self._numpy_signature(path)

    def compute_signature(self, path: np.ndarray) -> np.ndarray:
        """SPEC 别名：计算路径的签名张量（同 signature）."""
        return self.signature(path)

    def log_signature(self, path: np.ndarray) -> np.ndarray:
        """计算路径的对数签名（log signature）.

        log signature 是签名在张量代数中的对数映射，
        提供路径的"李代数"表示，维度更低、去冗余。

        数学背景：
          log S(X) = Σ (-1)^(k+1) (S(X)-1)^k / k
          对于 1D 增广路径，log signature 近似捕获路径的"几何特征"
          （增量、二次变分、roughness 等），消除代数冗余。

        降级实现：对 signature 做 log1p 变换，保留符号。
        signatory 可用时使用其 logsignature 函数。

        Returns:
            1D numpy 数组，对数签名特征.
        """
        path = np.asarray(path, dtype=np.float64).ravel()
        if len(path) < 2:
            return np.zeros(self.depth, dtype=np.float64)

        # 优先使用 signatory 的 logsignature
        if self._signatory_available:
            try:
                n = len(path)
                t = np.linspace(0.0, 1.0, n)
                aug = np.stack([t, path], axis=-1)[np.newaxis, :, :]
                aug_t = torch.tensor(aug, dtype=torch.float64)
                logsig = signatory.logsignature(aug_t, self.depth)
                return logsig.numpy().ravel()
            except Exception as e:  # noqa: BLE001
                logger.warning("[FO-AGI-02] signatory logsignature 失败，降级: %s", e)

        # 降级：对 signature 做符号保留的 log1p 变换
        sig = self.signature(path)
        if len(sig) == 0:
            return sig
        # 对数签名：对每个分量取符号保留的对数变换
        # log_sig_i = sign(sig_i) * log(1 + |sig_i|)
        signs = np.sign(sig)
        logsig = signs * np.log1p(np.abs(sig))
        return logsig

    def _numpy_signature(self, path: np.ndarray) -> np.ndarray:
        """numpy降级实现：时间增广路径的迭代积分签名.

        使用 (t, X_t) 增广，返回价格相关的签名项：
          Level 1: Δx (价格增量)
          Level 2: [Δx^2/2, ∫t dx] (价格二次变分 + 时价交叉)
          Level 3: [Δx^3/6, ∫t dx * Δx, ∫∫t dx dx]
          ...
        """
        n = len(path)
        t = np.linspace(0.0, 1.0, n)  # 归一化时间 [0, 1]
        dx = np.diff(path)
        dt = np.diff(t)
        delta_x = path[-1] - path[0]

        features: list[float] = []

        # Level 1: 价格增量
        features.append(float(delta_x))

        if self.depth >= 2:
            # Level 2: 价格二次变分 Δx^2/2
            features.append(float(delta_x ** 2 / 2.0))
            # Level 2: 时价交叉项 ∫ t dx （捕获lead-lag）
            cross = float(np.sum(t[:-1] * dx))
            features.append(cross)

        if self.depth >= 3:
            # Level 3: 价格三次变分 Δx^3/6
            features.append(float(delta_x ** 3 / 6.0))
            # Level 3: 二次交叉 ∫ t dx * Δx
            cross_l3 = float(cross * delta_x) if self.depth >= 2 else float(np.sum(t[:-1] * dx) * delta_x)
            features.append(cross_l3)
            # Level 3: 路径总波动（roughness）
            roughness = float(np.sum(dx ** 2))
            features.append(roughness)

        if self.depth >= 4:
            features.append(float(delta_x ** 4 / 24.0))
            features.append(float(np.sum(dx ** 3)))

        if self.depth >= 5:
            features.append(float(delta_x ** 5 / 120.0))
            features.append(float(np.sum(np.abs(dx))))

        return np.array(features, dtype=np.float64)

    def _signatory_signature(self, path: np.ndarray) -> np.ndarray:
        """使用 signatory 计算签名（若可用）."""
        try:
            n = len(path)
            t = np.linspace(0.0, 1.0, n)
            # 增广路径: shape (1, n, 2) — (batch, length, channels)
            aug = np.stack([t, path], axis=-1)[np.newaxis, :, :]
            aug_t = torch.tensor(aug, dtype=torch.float64)
            sig = signatory.signature(aug_t, self.depth)
            return sig.numpy().ravel()
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] signatory计算失败，降级numpy: %s", e)
            return self._numpy_signature(path)

    def _esig_signature(self, path: np.ndarray) -> np.ndarray:
        """使用 esig 计算签名（signatory 替代方案）.

        esig.stream2sig 接收 (n_steps, n_dims) 路径，返回签名特征向量.
        注意: roughpy 在 n=50 时存在已知 bug，故路径≥50步时降采样到49步.
        """
        try:
            n = len(path)
            t = np.linspace(0.0, 1.0, n)
            # esig/roughpy 在 n>=50 时有已知 bug，降采样到 49 步
            if n >= 50:
                idx = np.linspace(0, n - 1, 49, dtype=int)
                path = path[idx]
                t = t[idx]
            # 增广路径: shape (n, 2) — (time, price)
            aug = np.stack([t, path], axis=-1)
            sig = esig.stream2sig(aug, self.depth)
            return np.asarray(sig, dtype=np.float64).ravel()
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] esig计算失败，降级numpy: %s", e)
            return self._numpy_signature(path)

    def signature_distance(self, path1: np.ndarray, path2: np.ndarray) -> float:
        """两条路径的签名距离（L2范数）."""
        s1 = self.signature(path1)
        s2 = self.signature(path2)
        # 对齐长度
        min_len = min(len(s1), len(s2))
        return float(np.linalg.norm(s1[:min_len] - s2[:min_len]))

    def reconstruction_error(self, path: np.ndarray) -> float:
        """签名重构误差（用直线近似路径的RMSE）.

        1D路径的签名只含端点信息，重构为从起点到终点的直线.
        误差 = 实际路径与直线的RMSE.
        """
        path = np.asarray(path, dtype=np.float64).ravel()
        n = len(path)
        if n < 2:
            return 0.0
        # 直线重构: 从 path[0] 到 path[-1] 的线性插值
        reconstructed = np.linspace(path[0], path[-1], n)
        rmse = float(np.sqrt(np.mean((path - reconstructed) ** 2)))
        return rmse
