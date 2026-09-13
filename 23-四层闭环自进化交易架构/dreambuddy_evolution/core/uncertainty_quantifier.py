"""
UncertaintyQuantifier — 不确定性量化器（Phase 5.1）

核心思想：不追求"准确预测"，而是量化"预测有多不可靠"，
为元认知门禁提供 uncertainty_score。

核心能力：
  1. conformal_interval   — Split Conformal Prediction，形式化覆盖保证
  2. deep_ensemble        — Deep Ensemble 集成不确定性（5个网络预测方差）
  3. quantify_uncertainty — 综合不确定性评分 [0, 1]

依赖降级：
  - torch 可用 → Deep Ensemble（MLP 集成）
  - torch 不可用 → 线性回归集成 + bootstrap 残差

硬约束：
  - HC-AGI-06: uncertainty > 0.4 → 强制降仓至 0.5×（由 MetaCognitionGate 执行）

FAIL-OPEN：任何步骤异常 → uncertainty=1.0（最保守），interval=None
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 torch（可选依赖）
try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TORCH_AVAILABLE = False
    logger.debug("[FO-AGI-02] torch 不可用，使用numpy不确定性降级")


class _SimpleMLP(nn.Module if _TORCH_AVAILABLE else object):
    """简单 MLP 回归器，用于 Deep Ensemble"""
    def __init__(self, input_dim: int, hidden_dim: int = 32):
        if _TORCH_AVAILABLE:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(input_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, 1),
            )

    def forward(self, x):
        return self.net(x).squeeze(-1)


class UncertaintyQuantifier:
    """不确定性量化器.

    提供形式化覆盖保证（Conformal Prediction）+ 集成不确定性（Deep Ensemble）.
    """

    # HC-AGI-06 阈值
    UNCERTAINTY_HIGH = 0.4    # 降仓阈值
    UNCERTAINTY_CRITICAL = 0.7  # 拒开仓阈值

    def __init__(
        self,
        confidence: float = 0.9,
        n_ensemble: int = 5,
        min_calibration_samples: int = 50,
    ) -> None:
        self.confidence = confidence
        self.n_ensemble = n_ensemble
        self.min_calibration_samples = min_calibration_samples
        # 校准状态
        self._calibrated = False
        self._conformal_quantile: Optional[float] = None
        self._ensemble_models: list = []

    # ------------------------------------------------------------------
    # 1. Split Conformal Prediction
    # ------------------------------------------------------------------
    def fit_conformal(
        self,
        X_calib: np.ndarray,
        y_calib: np.ndarray,
        base_predictor=None,
    ) -> dict:
        """Split Conformal Prediction 校准.

        步骤：
        1. 用 base_predictor 预测校准集
        2. 计算残差 |y - ŷ|
        3. 取 (1-α) 分位数作为 conformal quantile

        Args:
            X_calib: 校准特征 (n, d)
            y_calib: 校准标签 (n,)
            base_predictor: 基础预测器（需有 predict 方法）
        Returns:
            dict: {"conformal_quantile": float, "n_calib": int, "calibrated": bool}
        FAIL-OPEN: 样本不足 → 不校准，quantile=None
        """
        try:
            X_calib = np.asarray(X_calib, dtype=np.float64)
            y_calib = np.asarray(y_calib, dtype=np.float64)
            n = len(y_calib)

            if n < self.min_calibration_samples:
                logger.warning("[FO-AGI-02] 校准样本不足(< %d)，跳过校准", self.min_calibration_samples)
                return {"conformal_quantile": None, "n_calib": n, "calibrated": False}

            # 预测校准集
            if base_predictor is not None and hasattr(base_predictor, "predict"):
                preds = np.asarray(base_predictor.predict(X_calib)).ravel()
            else:
                # 降级：用均值预测
                preds = np.full(n, np.mean(y_calib))

            # 残差
            residuals = np.abs(y_calib - preds)

            # Conformal quantile = (1-α) 分位数
            alpha = 1.0 - self.confidence
            # 使用 ceil((n+1)*(1-α))/n 保证有限样本覆盖
            quantile_idx = int(np.ceil((n + 1) * (1 - alpha)))
            quantile_idx = min(quantile_idx, n)
            sorted_res = np.sort(residuals)
            self._conformal_quantile = float(sorted_res[quantile_idx - 1])
            self._calibrated = True

            return {
                "conformal_quantile": self._conformal_quantile,
                "n_calib": n,
                "calibrated": True,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] fit_conformal failed: %s", e)
            return {"conformal_quantile": None, "n_calib": 0, "calibrated": False}

    def conformal_interval(self, prediction: float) -> Tuple[Optional[float], Optional[float]]:
        """返回带覆盖保证的预测区间.

        Returns:
            (lower, upper): 预测区间；未校准时返回 (None, None)
        """
        if not self._calibrated or self._conformal_quantile is None:
            return None, None
        q = self._conformal_quantile
        return prediction - q, prediction + q

    # ------------------------------------------------------------------
    # 2. Deep Ensemble 集成不确定性
    # ------------------------------------------------------------------
    def fit_ensemble(
        self,
        X: np.ndarray,
        y: np.ndarray,
        epochs: int = 50,
        lr: float = 0.01,
    ) -> dict:
        """训练 Deep Ensemble（n_ensemble 个不同初始化的模型）.

        不确定性 = 集成预测的标准差.

        Returns:
            dict: {"n_models": int, "method": str, "trained": bool}
        FAIL-OPEN: torch不可用 → 用线性回归集成
        """
        try:
            X = np.asarray(X, dtype=np.float64)
            y = np.asarray(y, dtype=np.float64)
            n, d = X.shape

            if n < self.min_calibration_samples:
                return {"n_models": 0, "method": "insufficient_samples", "trained": False}

            self._ensemble_models = []

            if _TORCH_AVAILABLE:
                self._fit_torch_ensemble(X, y, epochs, lr)
            else:
                self._fit_linear_ensemble(X, y)

            return {
                "n_models": len(self._ensemble_models),
                "method": "torch_mlp" if _TORCH_AVAILABLE else "linear_regression",
                "trained": len(self._ensemble_models) > 0,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] fit_ensemble failed: %s", e)
            return {"n_models": 0, "method": "error", "trained": False}

    def _fit_torch_ensemble(self, X, y, epochs, lr):
        """torch MLP 集成训练"""
        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.float32)

        for i in range(self.n_ensemble):
            model = _SimpleMLP(input_dim=X.shape[1])
            optimizer = torch.optim.Adam(model.parameters(), lr=lr)
            loss_fn = nn.MSELoss()

            # 不同随机种子 → 不同初始化
            torch.manual_seed(i * 42)
            model.apply(lambda m: m.reset_parameters() if hasattr(m, "reset_parameters") else None)

            model.train()
            for _ in range(epochs):
                optimizer.zero_grad()
                pred = model(X_t)
                loss = loss_fn(pred, y_t)
                loss.backward()
                optimizer.step()

            model.eval()
            self._ensemble_models.append(model)

    def _fit_linear_ensemble(self, X, y):
        """线性回归集成（bootstrap 不同子集）"""
        from sklearn.linear_model import LinearRegression

        n = len(y)
        rng = np.random.RandomState(42)
        for i in range(self.n_ensemble):
            # bootstrap 采样
            idx = rng.choice(n, n, replace=True)
            reg = LinearRegression()
            reg.fit(X[idx], y[idx])
            self._ensemble_models.append(reg)

    def ensemble_predict(self, X: np.ndarray) -> dict:
        """集成预测，返回均值和不确定性.

        Returns:
            dict: {
                "mean": float,           # 集成均值
                "std": float,            # 集成标准差（不确定性）
                "n_models": int,
                "predictions": list,     # 各模型预测
            }
        FAIL-OPEN: 未训练 → mean=0, std=1.0
        """
        try:
            if not self._ensemble_models:
                return {"mean": 0.0, "std": 1.0, "n_models": 0, "predictions": []}

            X = np.asarray(X, dtype=np.float64)
            preds = []

            for model in self._ensemble_models:
                if _TORCH_AVAILABLE and isinstance(model, _SimpleMLP):
                    with torch.no_grad():
                        p = model(torch.tensor(X, dtype=torch.float32)).numpy().ravel()
                else:
                    p = model.predict(X).ravel()
                preds.append(p)

            preds_arr = np.array(preds)  # (n_models, n_samples)
            mean = float(np.mean(preds_arr, axis=0)[0]) if preds_arr.ndim > 1 else float(np.mean(preds_arr))
            std = float(np.std(preds_arr, axis=0)[0]) if preds_arr.ndim > 1 else float(np.std(preds_arr))

            return {
                "mean": mean,
                "std": std,
                "n_models": len(preds),
                "predictions": [float(p[0]) if hasattr(p, "__len__") else float(p) for p in preds],
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] ensemble_predict failed: %s", e)
            return {"mean": 0.0, "std": 1.0, "n_models": 0, "predictions": []}

    # ------------------------------------------------------------------
    # 3. 综合不确定性评分
    # ------------------------------------------------------------------
    def quantify_uncertainty(
        self,
        prediction: float,
        ensemble_std: Optional[float] = None,
        conformal_width: Optional[float] = None,
        feature_noise: Optional[float] = None,
    ) -> dict:
        """综合不确定性评分 [0, 1].

        融合多个不确定性来源：
        - 集成预测方差（Deep Ensemble）
        - Conformal 区间宽度
        - 特征噪声水平

        Args:
            prediction: 点预测值
            ensemble_std: 集成标准差（可选）
            conformal_width: conformal 区间宽度（可选）
            feature_noise: 特征噪声水平（可选）
        Returns:
            dict: {
                "uncertainty_score": float,  # [0, 1]
                "components": {
                    "ensemble": float,
                    "conformal": float,
                    "feature_noise": float,
                },
                "level": "low" | "medium" | "high" | "critical",
            }
        """
        try:
            # 防御：prediction 异常 → 最大不确定性
            if not isinstance(prediction, (int, float)) or np.isnan(prediction) or np.isinf(prediction):
                return {
                    "uncertainty_score": 1.0,
                    "components": {"ensemble": 1.0, "conformal": 1.0, "feature_noise": 1.0},
                    "level": "critical",
                }
            components = {}

            # 1. 集成不确定性：归一化到 [0,1]
            if ensemble_std is not None:
                # 用 tanh 压缩，std 越大越接近 1
                components["ensemble"] = float(min(1.0, ensemble_std / (abs(prediction) + 1e-10)))
            else:
                components["ensemble"] = 0.5  # 未知时给中等不确定性

            # 2. Conformal 区间宽度不确定性
            if conformal_width is not None:
                components["conformal"] = float(min(1.0, conformal_width / (abs(prediction) + 1e-10)))
            else:
                components["conformal"] = 0.5

            # 3. 特征噪声
            if feature_noise is not None:
                components["feature_noise"] = float(min(1.0, feature_noise))
            else:
                components["feature_noise"] = 0.3

            # 综合：加权平均
            weights = {"ensemble": 0.4, "conformal": 0.4, "feature_noise": 0.2}
            uncertainty = sum(components[k] * weights[k] for k in components)
            uncertainty = float(max(0.0, min(1.0, uncertainty)))

            # 分级
            if uncertainty >= self.UNCERTAINTY_CRITICAL:
                level = "critical"
            elif uncertainty >= self.UNCERTAINTY_HIGH:
                level = "high"
            elif uncertainty >= 0.2:
                level = "medium"
            else:
                level = "low"

            return {
                "uncertainty_score": uncertainty,
                "components": components,
                "level": level,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] quantify_uncertainty failed: %s", e)
            return {
                "uncertainty_score": 1.0,
                "components": {"ensemble": 1.0, "conformal": 1.0, "feature_noise": 1.0},
                "level": "critical",
            }

    # ------------------------------------------------------------------
    # 端到端：预测 + 不确定性量化
    # ------------------------------------------------------------------
    def predict_with_uncertainty(
        self,
        X: np.ndarray,
        y: Optional[np.ndarray] = None,
    ) -> dict:
        """端到端：训练集成 + conformal 校准 + 预测 + 不确定性量化.

        Args:
            X: 特征 (n, d)
            y: 标签 (n,)，用于训练和校准
        Returns:
            dict: {
                "prediction": float,
                "lower": Optional[float],
                "upper": Optional[float],
                "uncertainty_score": float,
                "level": str,
            }
        FAIL-OPEN: 异常 → 最保守结果
        """
        try:
            X = np.asarray(X, dtype=np.float64)
            if y is None or len(X) < self.min_calibration_samples:
                return {
                    "prediction": 0.0,
                    "lower": None,
                    "upper": None,
                    "uncertainty_score": 1.0,
                    "level": "critical",
                }

            y = np.asarray(y, dtype=np.float64)
            n = len(y)

            # Split: 70% 训练集成，30% 校准 conformal
            split = int(n * 0.7)
            X_train, X_calib = X[:split], X[split:]
            y_train, y_calib = y[:split], y[split:]

            # 训练集成
            self.fit_ensemble(X_train, y_train)

            # 用集成均值作为 base predictor 做 conformal 校准
            ens_pred = self.ensemble_predict(X_calib)
            base_mean = ens_pred["mean"]

            # 简化：用均值预测器校准 conformal
            class _MeanPredictor:
                def __init__(self, val): self.val = val
                def predict(self, X):
                    return np.full(len(X), self.val)

            self.fit_conformal(X_calib, y_calib, base_predictor=_MeanPredictor(base_mean))

            # 对最后一个样本预测
            last_X = X[-1:]
            ens_result = self.ensemble_predict(last_X)
            prediction = ens_result["mean"]
            ensemble_std = ens_result["std"]

            lower, upper = self.conformal_interval(prediction)
            conformal_width = (upper - lower) if (lower is not None and upper is not None) else None

            unc = self.quantify_uncertainty(
                prediction=prediction,
                ensemble_std=ensemble_std,
                conformal_width=conformal_width,
            )

            return {
                "prediction": prediction,
                "lower": lower,
                "upper": upper,
                "uncertainty_score": unc["uncertainty_score"],
                "level": unc["level"],
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] predict_with_uncertainty failed: %s", e)
            return {
                "prediction": 0.0,
                "lower": None,
                "upper": None,
                "uncertainty_score": 1.0,
                "level": "critical",
            }

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def backend_status(self) -> dict:
        return {
            "torch": _TORCH_AVAILABLE,
            "calibrated": self._calibrated,
            "conformal_quantile": self._conformal_quantile,
            "n_ensemble_models": len(self._ensemble_models),
            "confidence": self.confidence,
            "thresholds": {
                "high": self.UNCERTAINTY_HIGH,
                "critical": self.UNCERTAINTY_CRITICAL,
            },
        }
