"""P1-1 拆分组件: SDESolver

从 deep_reasoning_engine.py 拆出的 SDE + TimesFM + GARCH 时序动态建模职责。
整合三个预测算法（NeuralSDE / TimesFM / GARCH fallback / GBM 兜底），同属"动态建模"算法域。

来源: SPEC v0.3 §2.B — deep_reasoning_engine 多算法缝合体拆分
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入深度学习依赖（FAIL-OPEN）
# TimesFM v3+ 使用 TimesFM3Forecaster；旧版用 TimesFm。兼容两种 API。
_TIMESFM_CLS = None
_TIMESFM_API = "none"
try:
    from timesfm import TimesFM3Forecaster  # type: ignore  # v3.0+
    _TIMESFM_CLS = TimesFM3Forecaster
    _TIMESFM_API = "v3"
    _TIMESFM_AVAILABLE = True
except Exception:  # noqa: BLE001
    try:
        from timesfm import TimesFm  # type: ignore  # v1/v2 旧版
        _TIMESFM_CLS = TimesFm
        _TIMESFM_API = "legacy"
        _TIMESFM_AVAILABLE = True
    except Exception:  # noqa: BLE001
        _TIMESFM_AVAILABLE = False
        logger.debug("[FO-AGI-03] timesfm 不可用，降级为统计预测")

try:
    # Stable-Neural-SDEs 或 torch 可用
    import torch  # type: ignore
    # 修复: PyTorch OpenMP tanh_kernel 在 Apple Silicon 多线程下 SIGSEGV
    torch.set_num_threads(1)
    _TORCH_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TORCH_AVAILABLE = False


class SDESolver:
    """时序动态建模器 — 从 DeepReasoningEngine 拆出的内聚组件.

    整合三个预测算法域（NeuralSDE + TimesFM + GARCH/GBM 兜底）。
    4 级降级链: torchsde → Euler-Maruyama → GARCH(1,1) → GBM
    """

    def __init__(self) -> None:
        self._timesfm_available = _TIMESFM_AVAILABLE
        self._timesfm_api = _TIMESFM_API
        self._torch_available = _TORCH_AVAILABLE
        # TimesFM 模型实例（懒加载）
        self._timesfm_model: Any = None
        # Neural SDE 模型（懒加载）
        self._neural_sde_model: Any = None
        self._neural_sde_loaded = False
        self._sde_backend_used: str = "unavailable"
        # GARCH fallback（懒加载）
        self._garch: Any = None
        # FAIL-OPEN 告警计数器 (HC-AGI-03)
        self._fail_open_counter: dict[str, list[float]] = {}
        # Neural SDE 权重路径
        self._sde_model_path = str(
            Path(__file__).resolve().parents[1] / "data" / "neural_sde_v1.pt"
        )

    # ------------------------------------------------------------------
    # Neural SDE 模型懒加载
    # ------------------------------------------------------------------
    def _get_neural_sde_model(self):
        """懒加载 Neural SDE 模型（参考 CQLTrainer 模式）."""
        if self._neural_sde_model is not None:
            return self._neural_sde_model if self._neural_sde_loaded else None
        if not self._torch_available:
            return None
        try:
            from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
            model = NeuralSDEModel(device="cpu")
            loaded = model.load(self._sde_model_path)
            self._neural_sde_model = model
            self._neural_sde_loaded = loaded
            if loaded:
                logger.info("[NeuralSDE] 模型权重加载成功: %s", self._sde_model_path)
            else:
                logger.debug("[NeuralSDE] 权重未找到，SDE 降级到 GARCH/GBM")
            return model if loaded else None
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] NeuralSDEModel 初始化失败: %s", e)
            self._neural_sde_model = False
            return None

    def _log_fail_open(self, module: str, exc: Exception) -> None:
        """HC-AGI-03: 记录 6 层堆栈 + 5分钟3次告警."""
        import time
        stack = traceback.format_exc()
        logger.warning("[FO-AGI-03] %s 降级: %s\n%s", module, exc, stack)
        now = time.time()
        self._fail_open_counter.setdefault(module, [])
        self._fail_open_counter[module].append(now)
        # 清理 5 分钟前的记录
        self._fail_open_counter[module] = [
            t for t in self._fail_open_counter[module] if now - t < 300
        ]
        if len(self._fail_open_counter[module]) >= 3:
            logger.critical(
                "[FO-AGI-03] %s 5分钟内 %d 次降级，触发 Lark 告警",
                module, len(self._fail_open_counter[module]),
            )

    # ------------------------------------------------------------------
    # Neural SDE 路径生成（4 级降级链）
    # ------------------------------------------------------------------
    def neural_sde_forecast(
        self,
        state: np.ndarray,
        horizon: int,
        n_paths: int = 1000,
        exogenous_factors: Optional[np.ndarray] = None,
        head_multipliers: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Neural SDE 模拟市场连续时间动态（4 级降级链）.

        dS = fθ(S,t)dt + gφ(S,t)dW

        Level 1: torchsde.sdeint() — torchsde 可用 + 模型已训练
        Level 2: 手写 Euler-Maruyama — torch 可用 + 模型已训练
        Level 3: GARCH(1,1) — HC-AGI-13，样本 < 1000 或模型未训练
        Level 4: GBM — 最后兜底

        Args:
            state: [price, volatility]
            horizon: 预测步数
            n_paths: 模拟路径数
            exogenous_factors: (N, factor_dim) 外生因子张量 (P1+ Cross-Attention),
                               None → zero context (FAIL-OPEN)
            head_multipliers: (n_heads,) Phase 5 每 head 衰减系数,
                              来自 CrossValidationGate.head_adjustment_to_array()
                              None → 不衰减 (FAIL-OPEN)

        Returns:
            shape (n_paths, horizon+1) 的价格路径数组
        """
        state = np.asarray(state, dtype=np.float64).ravel()
        if len(state) < 2:
            raise ValueError("state 必须至少含 [price, volatility]")
        init_price = float(state[0])
        vol = float(state[1])

        # 开关守卫：关闭时跳过 Neural SDE，降级到 GARCH (HC-AGI-07)
        from dreambuddy_evolution.agi_config import is_enabled
        if is_enabled("enable_neural_sde"):
            # Level 1+2: 真实 Neural SDE（torchsde 或 EM 积分）
            model = self._get_neural_sde_model()
            if model is not None and model.is_activated:
                try:
                    # P1+: 传入 cross-attention 外生因子 (模型不支持时自动 FAIL-OPEN)
                    forecast_kwargs = {}
                    if exogenous_factors is not None and getattr(model, "use_cross_attention", False):
                        forecast_kwargs["exogenous_factors"] = exogenous_factors
                    if head_multipliers is not None and getattr(model, "use_cross_attention", False):
                        forecast_kwargs["head_multipliers"] = head_multipliers
                    paths = model.forecast(state, horizon, n_paths, **forecast_kwargs)
                    if paths is not None:
                        self._sde_backend_used = (
                            "torchsde" if model.torchsde_available else "euler_maruyama"
                        )
                        return paths
                except Exception as e:  # noqa: BLE001
                    self._log_fail_open("neural_sde", e)

        # Level 3: GARCH(1,1) (HC-AGI-13)
        try:
            if self._garch is None:
                from dreambuddy_evolution.core.garch_fallback import GARCHFallback
                self._garch = GARCHFallback()
            # 用 volatility 估算 returns 长度（需要足够样本）
            # 如果 GARCH 未拟合，用 vol 做简单初始化
            if not self._garch.is_fitted:
                # 用 vol 生成伪 returns 估计 GARCH 参数
                pseudo_returns = np.random.randn(100) * vol
                self._garch.estimate(pseudo_returns)
            if self._garch.is_fitted:
                paths = self._garch.simulate(n_paths, horizon, init_price, vol)
                self._sde_backend_used = "garch"
                return paths
        except Exception as e:  # noqa: BLE001
            self._log_fail_open("garch", e)

        # Level 4: GBM 最后兜底
        self._sde_backend_used = "gbm"
        dt = 1.0
        drift = 0.0
        Z = np.random.standard_normal((n_paths, horizon))
        log_returns = (drift - 0.5 * vol ** 2) * dt + vol * np.sqrt(dt) * Z
        paths = np.zeros((n_paths, horizon + 1))
        paths[:, 0] = init_price
        paths[:, 1:] = init_price * np.exp(np.cumsum(log_returns, axis=1))
        return paths

    # ------------------------------------------------------------------
    # TimesFM 时序预测
    # ------------------------------------------------------------------
    def timesfm_predict(self, history: np.ndarray, horizon: int) -> np.ndarray:
        """TimesFM 预训练模型预测价格序列.

        FAIL-OPEN: timesfm 不可用时降级为线性趋势+波动率外推.
        """
        history = np.asarray(history, dtype=np.float64).ravel()
        if len(history) < 2:
            return np.full(horizon, float(history[-1]) if len(history) else 0.0)

        # 开关守卫：关闭时降级为统计预测 (HC-AGI-07)
        from dreambuddy_evolution.agi_config import is_enabled
        if is_enabled("enable_timesfm_forecast") and self._timesfm_available:
            return self._timesfm_predict_real(history, horizon)
        return self._statistical_forecast(history, horizon)

    def _timesfm_predict_real(self, history: np.ndarray, horizon: int) -> np.ndarray:
        """使用真实 TimesFM 模型预测（兼容 v3 和 legacy API）."""
        try:
            if self._timesfm_model is None:
                if _TIMESFM_API == "v3":
                    # TimesFM v3: 从预训练权重加载
                    self._timesfm_model = _TIMESFM_CLS.from_pretrained()
                else:
                    # TimesFM legacy (v1/v2): 直接构造
                    self._timesfm_model = _TIMESFM_CLS(
                        context_len=min(len(history), 512),
                        horizon_len=horizon,
                        input_patch_len=32,
                        output_patch_len=128,
                        num_layers=20,
                        model_dims=1280,
                    )
            if _TIMESFM_API == "v3":
                # v3 API: predict(context, horizon) -> ForecastOutput
                forecast_out = self._timesfm_model.predict(history, horizon)
                forecast = forecast_out.forecast if hasattr(forecast_out, "forecast") else forecast_out
                arr = np.asarray(forecast, dtype=np.float64)
                # 兼容 (batch, horizon) 或 (horizon,) 输出
                return arr[0] if arr.ndim == 2 else arr
            # legacy API: forecast(batch)
            batch = history[np.newaxis, :]
            forecast = self._timesfm_model.forecast(batch)
            return np.asarray(forecast[0], dtype=np.float64)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] TimesFM预测失败，降级统计预测: %s", e)
            return self._statistical_forecast(history, horizon)

    def _statistical_forecast(self, history: np.ndarray, horizon: int) -> np.ndarray:
        """统计降级预测：线性趋势 + 历史波动率扰动.

        简单但稳健的预测基线:
          - 用最近 N 个点拟合线性趋势
          - 外推 horizon 步
          - 叠加历史波动率的衰减扰动
        """
        n = len(history)
        t = np.arange(n, dtype=np.float64)
        # 线性回归拟合趋势
        coeffs = np.polyfit(t, history, 1)
        slope, intercept = coeffs
        # 预测未来点
        future_t = np.arange(n, n + horizon, dtype=np.float64)
        forecast = intercept + slope * future_t
        # 叠加历史波动率（衰减）
        if n > 5:
            returns = np.diff(history) / np.maximum(np.abs(history[:-1]), 1e-12)
            vol = float(np.std(returns))
            # 波动率随时间衰减（越远不确定性越大，但用历史vol的衰减形式）
            decay = np.exp(-0.05 * np.arange(horizon))
            noise = np.random.randn(horizon) * vol * history[-1] * decay * 0.5
            forecast = forecast + noise
        return forecast

    # ------------------------------------------------------------------
    # 后端状态
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """neural_sde + timesfm 后端可用性"""
        return {
            "neural_sde": self._torch_available,
            "timesfm": self._timesfm_available,
            "timesfm_api": self._timesfm_api,
            "neural_sde_trained": self._neural_sde_loaded,
            "neural_sde_backend": self._sde_backend_used,
        }
