"""
TransferLearner — 跨资产迁移学习（Phase 3.2）

核心思想：BTC 上学到的 pattern，能否迁移到 SOL/ETH？
用 Prototypical Network 衡量 pattern 相似度，
用 MAML 做跨资产元学习，
迁移前必须经反事实评估（HC-AGI-05）。

核心能力：
  1. compute_prototype     — 计算某资产 pattern 的原型向量
  2. pattern_similarity    — Prototypical Network 余弦相似度
  3. maml_adapt            — MAML 元学习：用源资产梯度更新参数，在目标资产上验证
  4. transfer_pattern      — 端到端迁移（含 HC-AGI-05 反事实验证）

硬约束：
  - HC-AGI-05: 迁移 pattern 必须经反事实评估（CounterfactualEvaluator.validate_migration）

依赖降级：
  - torch 可用 → MAML（简单 MAML 实现）
  - torch 不可用 → 统计原型相似度（cosine）

FAIL-OPEN：迁移失败 → 返回 valid=False
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from dreambuddy_evolution.core.counterfactual_evaluator import CounterfactualEvaluator

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TORCH_AVAILABLE = False


class TransferLearner:
    """跨资产迁移学习.

    Prototypical Network + MAML + 反事实验证（HC-AGI-05）.
    """

    # 迁移有效性阈值
    SIMILARITY_THRESHOLD = 0.6   # 余弦相似度 > 0.6 才考虑迁移
    ALPHA_THRESHOLD = 0.0        # 反事实 alpha > 0 才认可

    def __init__(
        self,
        counterfactual_evaluator: Optional[CounterfactualEvaluator] = None,
        similarity_threshold: float = 0.6,
    ) -> None:
        self.cf_evaluator = counterfactual_evaluator or CounterfactualEvaluator()
        self.similarity_threshold = similarity_threshold
        self._prototypes: dict = {}  # {asset: prototype_vector}

    # ------------------------------------------------------------------
    # 1. Prototypical Network: 计算原型
    # ------------------------------------------------------------------
    def compute_prototype(
        self,
        feature_matrix: np.ndarray,
        labels: Optional[np.ndarray] = None,
    ) -> dict:
        """计算原型向量（Prototypical Network）.

        对每类（label）计算特征均值作为原型.
        如果无 labels，则整体均值作为单一原型.

        Args:
            feature_matrix: 特征矩阵 (n_samples, n_features)
            labels: 类别标签 (n_samples,)，可选
        Returns:
            dict: {"prototypes": {label: np.ndarray}, "n_classes": int}
        """
        try:
            X = np.asarray(feature_matrix, dtype=np.float64)
            if X.ndim == 1:
                X = X.reshape(-1, 1)

            if labels is None:
                # 单一原型：整体均值
                proto = np.mean(X, axis=0)
                return {"prototypes": {0: proto}, "n_classes": 1}

            labels = np.asarray(labels)
            prototypes = {}
            for cls in np.unique(labels):
                mask = labels == cls
                prototypes[int(cls)] = np.mean(X[mask], axis=0)

            return {"prototypes": prototypes, "n_classes": len(prototypes)}
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] compute_prototype failed: %s", e)
            return {"prototypes": {}, "n_classes": 0}

    def store_prototype(self, asset: str, feature_matrix: np.ndarray, labels=None) -> None:
        """存储某资产的原型"""
        result = self.compute_prototype(feature_matrix, labels)
        self._prototypes[asset] = result["prototypes"]

    # ------------------------------------------------------------------
    # 2. Pattern 相似度
    # ------------------------------------------------------------------
    def pattern_similarity(
        self,
        source_features: np.ndarray,
        target_features: np.ndarray,
    ) -> float:
        """计算两个 pattern 的余弦相似度（Prototypical Network）.

        Returns:
            similarity: [0, 1]，1 表示完全相同
        """
        try:
            src = np.asarray(source_features, dtype=np.float64).ravel()
            tgt = np.asarray(target_features, dtype=np.float64).ravel()

            if len(src) == 0 or len(tgt) == 0:
                return 0.0

            # 对齐长度
            min_len = min(len(src), len(tgt))
            src = src[:min_len]
            tgt = tgt[:min_len]

            # 余弦相似度
            norm_src = np.linalg.norm(src)
            norm_tgt = np.linalg.norm(tgt)
            if norm_src < 1e-10 or norm_tgt < 1e-10:
                return 0.0

            cosine = float(np.dot(src, tgt) / (norm_src * norm_tgt))
            # 映射到 [0, 1]
            return float(max(0.0, min(1.0, (cosine + 1.0) / 2.0)))
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] pattern_similarity failed: %s", e)
            return 0.0

    def asset_similarity(self, source_asset: str, target_asset: str) -> float:
        """计算两个资产已存储原型的相似度"""
        if source_asset not in self._prototypes or target_asset not in self._prototypes:
            return 0.0
        src_proto = self._prototypes[source_asset].get(0, np.array([]))
        tgt_proto = self._prototypes[target_asset].get(0, np.array([]))
        return self.pattern_similarity(src_proto, tgt_proto)

    # ------------------------------------------------------------------
    # 3. MAML 元学习
    # ------------------------------------------------------------------
    def maml_adapt(
        self,
        source_X: np.ndarray,
        source_y: np.ndarray,
        target_X: np.ndarray,
        target_y: np.ndarray,
        inner_lr: float = 0.01,
        outer_lr: float = 0.001,
        inner_steps: int = 5,
    ) -> dict:
        """MAML 元学习适配.

        简化版 MAML：
        1. 用源资产数据训练基础模型
        2. 用目标资产数据做 inner-loop 梯度更新
        3. 在目标资产上评估 meta-loss

        Returns:
            dict: {
                "meta_loss": float,          # 目标资产上的损失
                "adapted_loss": float,       # 适配后损失
                "source_loss": float,        # 源资产损失
                "improvement": float,        # source - adapted（正=迁移有效）
            }
        FAIL-OPEN: torch不可用 → 用线性回归统计适配
        """
        try:
            if _TORCH_AVAILABLE:
                return self._maml_torch(source_X, source_y, target_X, target_y, inner_lr, inner_steps)
            else:
                return self._maml_linear(source_X, source_y, target_X, target_y)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] maml_adapt failed: %s", e)
            return {"meta_loss": float("inf"), "adapted_loss": float("inf"),
                    "source_loss": float("inf"), "improvement": 0.0}

    def _maml_torch(self, src_X, src_y, tgt_X, tgt_y, inner_lr, inner_steps):
        """torch MAML 实现"""
        src_X = torch.tensor(src_X, dtype=torch.float32)
        src_y = torch.tensor(src_y, dtype=torch.float32)
        tgt_X = torch.tensor(tgt_X, dtype=torch.float32)
        tgt_y = torch.tensor(tgt_y, dtype=torch.float32)

        # 基础模型
        d = src_X.shape[1] if src_X.ndim > 1 else 1
        if src_X.ndim == 1:
            src_X = src_X.unsqueeze(1)
            tgt_X = tgt_X.unsqueeze(1)

        model = nn.Sequential(
            nn.Linear(d, 16), nn.ReLU(),
            nn.Linear(16, 1),
        )

        # 源资产训练
        opt = torch.optim.Adam(model.parameters(), lr=0.01)
        for _ in range(100):
            opt.zero_grad()
            loss = ((model(src_X).squeeze() - src_y) ** 2).mean()
            loss.backward()
            opt.step()

        source_loss = float(loss.item())

        # MAML inner loop: 用目标资产梯度更新（不保存优化器状态）
        model.train()
        for _ in range(inner_steps):
            pred = model(tgt_X).squeeze()
            loss = ((pred - tgt_y) ** 2).mean()
            grads = torch.autograd.grad(loss, model.parameters(), create_graph=True)
            with torch.no_grad():
                for p, g in zip(model.parameters(), grads):
                    p.copy_(p - inner_lr * g)

        # 评估目标资产损失
        model.eval()
        with torch.no_grad():
            meta_pred = model(tgt_X).squeeze()
            meta_loss = float(((meta_pred - tgt_y) ** 2).mean().item())

        return {
            "meta_loss": meta_loss,
            "adapted_loss": meta_loss,
            "source_loss": source_loss,
            "improvement": source_loss - meta_loss,
        }

    def _maml_linear(self, src_X, src_y, tgt_X, tgt_y):
        """线性回归 MAML 降级"""
        from sklearn.linear_model import LinearRegression

        src_X = np.asarray(src_X, dtype=np.float64)
        tgt_X = np.asarray(tgt_X, dtype=np.float64)
        src_y = np.asarray(src_y, dtype=np.float64)
        tgt_y = np.asarray(tgt_y, dtype=np.float64)

        if src_X.ndim == 1:
            src_X = src_X.reshape(-1, 1)
            tgt_X = tgt_X.reshape(-1, 1)

        # 源资产训练
        src_model = LinearRegression()
        src_model.fit(src_X, src_y)
        src_pred = src_model.predict(src_X)
        source_loss = float(np.mean((src_pred - src_y) ** 2))

        # 目标资产直接训练（MAML 简化）
        tgt_model = LinearRegression()
        tgt_model.fit(tgt_X, tgt_y)
        tgt_pred = tgt_model.predict(tgt_X)
        meta_loss = float(np.mean((tgt_pred - tgt_y) ** 2))

        return {
            "meta_loss": meta_loss,
            "adapted_loss": meta_loss,
            "source_loss": source_loss,
            "improvement": source_loss - meta_loss,
        }

    # ------------------------------------------------------------------
    # 4. 端到端迁移（HC-AGI-05 反事实验证）
    # ------------------------------------------------------------------
    def transfer_pattern(
        self,
        source_asset: str,
        target_asset: str,
        source_returns: np.ndarray,
        target_returns: np.ndarray,
        control_returns: np.ndarray,
        source_features: Optional[np.ndarray] = None,
        target_features: Optional[np.ndarray] = None,
    ) -> dict:
        """端到端 pattern 迁移（含 HC-AGI-05 反事实验证）.

        流程：
        1. Prototypical Network 计算相似度
        2. 相似度 < 阈值 → 拒绝迁移
        3. MAML 适配验证
        4. 反事实验证（HC-AGI-05）
        5. 全部通过 → valid=True

        Returns:
            dict: {
                "valid": bool,
                "similarity": float,
                "maml_improvement": float,
                "counterfactual_alpha": float,
                "rejected_by": Optional[str],   # 被哪一步拒绝
                "reason": str,
            }
        """
        try:
            source_returns = np.asarray(source_returns, dtype=np.float64).ravel()
            target_returns = np.asarray(target_returns, dtype=np.float64).ravel()
            control_returns = np.asarray(control_returns, dtype=np.float64)

            # Step 1: 相似度
            if source_features is not None and target_features is not None:
                similarity = self.pattern_similarity(source_features, target_features)
            else:
                similarity = self.pattern_similarity(source_returns, target_returns)

            if similarity < self.similarity_threshold:
                return {
                    "valid": False,
                    "similarity": similarity,
                    "maml_improvement": 0.0,
                    "counterfactual_alpha": 0.0,
                    "rejected_by": "similarity",
                    "reason": f"相似度 {similarity:.3f} < 阈值 {self.similarity_threshold}",
                }

            # Step 2: MAML 适配
            maml_result = self.maml_adapt(
                source_X=source_returns.reshape(-1, 1),
                source_y=source_returns,
                target_X=target_returns.reshape(-1, 1),
                target_y=target_returns,
            )
            improvement = maml_result["improvement"]

            # Step 3: 反事实验证（HC-AGI-05）
            cf_result = self.cf_evaluator.validate_migration(
                pattern_source_returns=source_returns,
                pattern_target_returns=target_returns,
                control_returns=control_returns,
                source_pnl=float(np.sum(source_returns)),
            )

            alpha = cf_result["alpha"]

            if not cf_result["valid"]:
                return {
                    "valid": False,
                    "similarity": similarity,
                    "maml_improvement": improvement,
                    "counterfactual_alpha": alpha,
                    "rejected_by": "counterfactual",
                    "reason": f"反事实验证未通过: {cf_result['reason']}",
                }

            # 全部通过
            return {
                "valid": True,
                "similarity": similarity,
                "maml_improvement": improvement,
                "counterfactual_alpha": alpha,
                "rejected_by": None,
                "reason": f"迁移通过: similarity={similarity:.3f}, alpha={alpha:.4f}",
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] transfer_pattern failed: %s", e)
            return {
                "valid": False,
                "similarity": 0.0,
                "maml_improvement": 0.0,
                "counterfactual_alpha": 0.0,
                "rejected_by": "error",
                "reason": f"error: {e}",
            }

    # ------------------------------------------------------------------
    # SPEC 兼容接口：extract_pattern / transfer_to
    # ------------------------------------------------------------------
    def extract_pattern(
        self,
        source_symbol: str,
        returns: np.ndarray,
        features: Optional[np.ndarray] = None,
        labels: Optional[np.ndarray] = None,
    ) -> dict:
        """SPEC 接口：提取可迁移 pattern.

        提取源资产的原型向量 + 收益特征，供 transfer_to 使用.

        Args:
            source_symbol: 源资产标识（如 "BTC"）
            returns: 源资产收益序列
            features: 特征矩阵（可选，用于 Prototypical Network）
            labels: 类别标签（可选）
        Returns:
            dict: {
                "symbol": str,
                "returns": np.ndarray,
                "features": Optional[np.ndarray],
                "prototype": dict,  # 原型向量
                "n_samples": int,
            }
        """
        try:
            returns = np.asarray(returns, dtype=np.float64).ravel()
            proto_result = self.compute_prototype(features if features is not None else returns.reshape(-1, 1), labels)

            pattern = {
                "symbol": source_symbol,
                "returns": returns,
                "features": features,
                "prototype": proto_result["prototypes"],
                "n_samples": len(returns),
            }
            # 缓存原型
            self._prototypes[source_symbol] = proto_result["prototypes"]
            return pattern
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] extract_pattern failed: %s", e)
            return {"symbol": source_symbol, "returns": np.array([]), "features": None,
                    "prototype": {}, "n_samples": 0}

    def transfer_to(
        self,
        pattern: dict,
        target_symbol: str,
        target_returns: np.ndarray,
        control_returns: np.ndarray,
        target_features: Optional[np.ndarray] = None,
    ) -> float:
        """SPEC 接口：迁移 pattern 到目标资产，返回适应度评分.

        内部调用 transfer_pattern，返回 alpha 作为适应度评分.

        Args:
            pattern: extract_pattern 返回的 pattern dict
            target_symbol: 目标资产标识
            target_returns: 目标资产收益序列
            control_returns: 控制组收益矩阵
            target_features: 目标资产特征（可选）
        Returns:
            float: 适应度评分（counterfactual alpha），无效迁移返回 0.0
        """
        try:
            result = self.transfer_pattern(
                source_asset=pattern.get("symbol", "unknown"),
                target_asset=target_symbol,
                source_returns=pattern.get("returns", np.array([])),
                target_returns=target_returns,
                control_returns=control_returns,
                source_features=pattern.get("features"),
                target_features=target_features,
            )
            return float(result["counterfactual_alpha"]) if result["valid"] else 0.0
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] transfer_to failed: %s", e)
            return 0.0

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def backend_status(self) -> dict:
        return {
            "torch": _TORCH_AVAILABLE,
            "similarity_threshold": self.similarity_threshold,
            "n_stored_prototypes": len(self._prototypes),
            "counterfactual_evaluator": self.cf_evaluator.backend_status(),
        }
