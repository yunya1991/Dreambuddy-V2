"""
Phase 2.3: 深度学习推理引擎
SPEC-AGI升级蓝图.md §4.2.3

核心思想: 不用大语言模型做推理，用深度学习做数据驱动的模式发现。
推理流程（无LLM·纯数据驱动）：
  1. 路径抽象：价格路径 → Signature张量（签名方法）
  2. 动态建模：Neural SDE学习市场连续时间动态
  3. 时序预测：TimesFM预训练模型预测价格分布
  4. 多路径采样：蒙特卡洛生成N条可能路径
  5. 最优路径：计算每条路径阻力→选最小阻力路径

蓝本: signatory + TimesFM (32.2k★) + Stable-Neural-SDEs (ICLR 2024)
FAIL-OPEN: 任一模块异常→降级为统计方法，不crash
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Optional

import numpy as np

from dreambuddy_evolution.core.signature_engine import SignatureEngine
from dreambuddy_evolution.core.path_integral import PathIntegralEngine
from dreambuddy_evolution.engines.signature_computer import (
    SignatureComputer,
    _SIGNATORY_AVAILABLE,
)
from dreambuddy_evolution.engines.sde_solver import (
    SDESolver,
    _TIMESFM_API,
    _TIMESFM_AVAILABLE,
    _TORCH_AVAILABLE,
)

logger = logging.getLogger(__name__)


class DeepReasoningEngine:
    """深度学习推理引擎（万物皆数·最小阻力路径）.

    无LLM·纯数据驱动：
      签名抽象 → Neural SDE动态 → TimesFM预测 → 蒙特卡洛 → 最小阻力路径
    """

    def __init__(self, signature_depth: int = 3) -> None:
        # P1-1 拆分: 签名职责委托给 SignatureComputer
        self._signature = SignatureComputer(signature_depth=signature_depth)
        # P1-1 拆分: SDE+TimesFM 动态建模委托给 SDESolver
        self._sde = SDESolver()
        # 保留实例变量向后兼容（backend_status / 旧测试引用）
        self._signature_engine = SignatureEngine(depth=signature_depth)
        self._path_integral = PathIntegralEngine(n_paths=1000)
        # Phase 2: 签名特征提取器（懒加载，前置签名特征接入）— 委托给 SignatureComputer
        self._timesfm_available = _TIMESFM_AVAILABLE
        self._timesfm_api = _TIMESFM_API
        self._signatory_available = _SIGNATORY_AVAILABLE
        self._torch_available = _TORCH_AVAILABLE
        # 以下状态迁移到 SDESolver 内部，这里保留为向后兼容引用（指向 self._sde.*）
        self._timesfm_model = None  # type: ignore[assignment]
        self._neural_sde_model = None  # type: ignore[assignment]
        self._neural_sde_loaded = False
        self._sde_backend_used: str = "unavailable"
        self._garch = None  # type: ignore[assignment]
        self._fail_open_counter: dict[str, list[float]] = {}
        self._sde_model_path = str(
            Path(__file__).resolve().parents[1] / "data" / "neural_sde_v1.pt"
        )

    def _get_signature_feature_extractor(self):
        """懒加载 SignatureFeatureExtractor — P1-1 拆分后委托给 SignatureComputer."""
        return self._signature._get_signature_feature_extractor()

    # ------------------------------------------------------------------
    # 后端状态
    # ------------------------------------------------------------------
    def backend_status(self) -> dict[str, Any]:
        """报告各深度学习后端的可用状态."""
        return {
            "timesfm": self._timesfm_available,
            "timesfm_api": self._timesfm_api,
            "signatory": self._signatory_available,
            "neural_sde": self._torch_available,
            "neural_sde_trained": self._neural_sde_loaded,
            "neural_sde_backend": self._sde_backend_used,
        }

    # ------------------------------------------------------------------
    # 1. 路径抽象：签名方法 — P1-1 拆分后委托给 SignatureComputer
    # ------------------------------------------------------------------
    def path_to_signature(self, price_path: np.ndarray) -> np.ndarray:
        """价格路径 → 签名张量（万物皆数）.

        优先用 signatory，否则用 numpy 降级实现.
        """
        return self._signature.path_to_signature(price_path)

    # ------------------------------------------------------------------
    # 2. Neural SDE 动态建模 — P1-1 拆分后委托给 SDESolver
    # ------------------------------------------------------------------
    def _get_neural_sde_model(self):
        """懒加载 Neural SDE 模型 — P1-1 拆分后委托给 SDESolver."""
        return self._sde._get_neural_sde_model()

    def _log_fail_open(self, module: str, exc: Exception) -> None:
        """HC-AGI-03 告警 — P1-1 拆分后委托给 SDESolver."""
        self._sde._log_fail_open(module, exc)

    def neural_sde_forecast(
        self,
        state: np.ndarray,
        horizon: int,
        n_paths: int = 1000,
        exogenous_factors: Optional[np.ndarray] = None,
        head_multipliers: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Neural SDE 4 级降级链 — 委托给 SDESolver.

        Level 1: torchsde.sdeint()
        Level 2: Euler-Maruyama
        Level 3: GARCH(1,1)
        Level 4: GBM
        """
        return self._sde.neural_sde_forecast(
            state,
            horizon,
            n_paths=n_paths,
            exogenous_factors=exogenous_factors,
            head_multipliers=head_multipliers,
        )

    # ------------------------------------------------------------------
    # 3. TimesFM 时序预测 — P1-1 拆分后委托给 SDESolver
    # ------------------------------------------------------------------
    def timesfm_predict(self, history: np.ndarray, horizon: int) -> np.ndarray:
        """TimesFM 预测 — 委托给 SDESolver. FAIL-OPEN 降级为统计预测."""
        return self._sde.timesfm_predict(history, horizon)

    def _timesfm_predict_real(self, history: np.ndarray, horizon: int) -> np.ndarray:
        """真实 TimesFM 预测 — 委托给 SDESolver."""
        return self._sde._timesfm_predict_real(history, horizon)

    def _statistical_forecast(self, history: np.ndarray, horizon: int) -> np.ndarray:
        """统计降级预测 — 委托给 SDESolver."""
        return self._sde._statistical_forecast(history, horizon)

    # ------------------------------------------------------------------
    # 4. 蒙特卡洛多路径采样
    # ------------------------------------------------------------------
    def monte_carlo_paths(
        self,
        start_price: float,
        horizon: int,
        n_paths: int = 1000,
        volatility: float | None = None,
    ) -> list[np.ndarray]:
        """蒙特卡洛采样 N 条可能路径（复用 PathIntegralEngine）."""
        pi = self._path_integral
        pi.n_paths = n_paths
        vol = volatility if volatility is not None else 0.02
        return pi.sample_paths(start_price=start_price, horizon=horizon, volatility=vol)

    # ------------------------------------------------------------------
    # 5. 路径阻力 & 最小阻力路径
    # ------------------------------------------------------------------
    def compute_path_resistance(self, path: np.ndarray) -> float:
        """计算路径阻力（交易成本 + 风险 + 不确定性）."""
        return self._path_integral.compute_action(path)

    def find_min_resistance_path(self, paths: list[np.ndarray]) -> dict[str, Any]:
        """搜索最小阻力路径（最小作用量 = 最优交易路径）.

        HC-AGI-17 降级链: HJB → 变分法 → argmin
        """
        # 1. 优先 HJB/变分法（开关控制 + FAIL-OPEN）
        try:
            from dreambuddy_evolution.agi_config import get_switch
            if get_switch("enable_hjb_solver", True) or get_switch("enable_variational_opt", True):
                from dreambuddy_evolution.core.hjb_solver import solve_optimal_path

                start_price = float(paths[0][0]) if paths and len(paths[0]) > 0 else 100.0
                horizon = max(len(p) for p in paths) - 1 if paths else 10
                # 从 paths 估算 vol
                all_returns = np.concatenate([
                    np.diff(p) / np.maximum(p[:-1], 1e-9) for p in paths
                ]) if paths else np.array([0.02])
                vol = float(np.std(all_returns)) if len(all_returns) > 1 else 0.02

                hjb_result = solve_optimal_path(
                    start_price=start_price,
                    horizon=horizon,
                    volatility=vol,
                    monte_carlo_paths=paths,
                )
                return {
                    "best_index": -1,
                    "best_resistance": hjb_result["total_cost"],
                    "best_path": hjb_result["optimal_path"],
                    "backend": hjb_result["backend"],
                    "converged": hjb_result["converged"],
                    "fallback_chain": hjb_result["fallback_chain"],
                }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] HJB/变分法降级到 argmin: %s", e)

        # 2. 兜底: argmin
        best_idx, best_resistance = self._path_integral.find_least_resistance_path(paths)
        return {
            "best_index": best_idx,
            "best_resistance": float(best_resistance),
            "best_path": paths[best_idx],
            "backend": "argmin",
            "converged": True,
            "fallback_chain": ["argmin"],
        }

    # ------------------------------------------------------------------
    # 完整推理流水线
    # ------------------------------------------------------------------
    def reason(
        self,
        price_path: np.ndarray,
        horizon: int = 20,
        n_paths: int = 1000,
        exogenous_factors: Optional[np.ndarray] = None,
        head_multipliers: Optional[np.ndarray] = None,
    ) -> dict[str, Any]:
        """完整推理流程：签名→SDE→预测→采样→最优路径.

        FAIL-OPEN: 任一环节异常返回降级结果，不crash.

        Args:
            head_multipliers: (n_heads,) Phase 5 每 head 衰减系数, 来自 CrossValidationGate.
        """
        price_path = np.asarray(price_path, dtype=np.float64).ravel()

        # 1. 路径抽象
        try:
            signature = self.path_to_signature(price_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] 签名计算失败: %s", e)
            signature = np.array([])

        # 1.5 Phase 2 前置签名特征提取（17 维：5 状态 + 12 签名）
        signature_features: list[float] = []
        try:
            from dreambuddy_evolution.agi_config import is_enabled
            sig_ext = self._get_signature_feature_extractor() if is_enabled("enable_signature_features") else None
            if sig_ext is not None:
                # 从价格路径提取状态特征（简化：用收益率统计量）
                returns = np.diff(price_path) / np.maximum(np.abs(price_path[:-1]), 1e-12) if len(price_path) > 1 else [0.0]
                state_features = [
                    float(np.mean(returns[-20:])) if len(returns) >= 20 else float(np.mean(returns)) if len(returns) > 0 else 0.0,
                    float(np.std(returns[-20:])) if len(returns) >= 20 else float(np.std(returns)) if len(returns) > 0 else 0.01,
                    float(price_path[-1]) if len(price_path) > 0 else 0.0,
                    float(np.max(returns[-20:])) if len(returns) >= 20 else 0.0,
                    float(np.min(returns[-20:])) if len(returns) >= 20 else 0.0,
                ]
                signature_features = sig_ext.extract(state_features, price_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] 签名特征提取失败: %s", e)
            signature_features = []

        # 2. 时序预测
        try:
            forecast = self.timesfm_predict(price_path, horizon=horizon)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] 预测失败: %s", e)
            forecast = np.full(horizon, float(np.asarray(price_path[-1]).item()) if len(price_path) else 0.0)

        # 2.5 Neural SDE 路径生成（4 级降级链：torchsde → EM → GARCH → GBM）
        sde_paths = None
        try:
            start_price = float(np.asarray(price_path[-1]).item()) if len(price_path) else 100.0
            vol = float(np.std(np.diff(price_path) / np.maximum(np.abs(price_path[:-1]), 1e-12))) if len(price_path) > 5 else 0.02
            sde_paths = self.neural_sde_forecast(
                np.array([start_price, max(vol, 0.001)]),
                horizon=horizon,
                n_paths=n_paths,
                exogenous_factors=exogenous_factors,
                head_multipliers=head_multipliers,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] SDE 路径生成失败: %s", e)

        # 3. 路径选择：优先 SDE 路径，否则降级蒙特卡洛 GBM 采样
        if sde_paths is not None:
            paths = [sde_paths[i] for i in range(sde_paths.shape[0])]
        else:
            try:
                paths = self.monte_carlo_paths(
                    start_price=start_price, horizon=horizon,
                    n_paths=n_paths, volatility=max(vol, 0.001),
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("[FO-AGI-03] 蒙特卡洛采样失败: %s", e)
                paths = [np.full(horizon + 1, start_price)]

        # 4. 最小阻力路径
        mr: dict[str, Any] = {"backend": "argmin", "converged": True}
        try:
            mr = self.find_min_resistance_path(paths)
            min_resistance = mr["best_resistance"]
            min_resistance_path = mr["best_path"]
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] 最小阻力搜索失败: %s", e)
            min_resistance = 0.0
            min_resistance_path = paths[0] if paths else np.array([])

        return {
            "signature": signature,
            "signature_features": signature_features,
            "forecast": forecast,
            "min_resistance_path": min_resistance_path,
            "min_resistance": float(min_resistance),
            "min_resistance_backend": mr.get("backend", "argmin") if isinstance(mr, dict) else "argmin",
            "min_resistance_converged": mr.get("converged", True) if isinstance(mr, dict) else True,
            "n_paths": len(paths),
            "backends": self.backend_status(),
            "sde_backend": self._sde_backend_used,
        }
