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
from typing import Any

import numpy as np

from dreambuddy_evolution.core.signature_engine import SignatureEngine
from dreambuddy_evolution.core.path_integral import PathIntegralEngine

logger = logging.getLogger(__name__)

# 尝试导入深度学习依赖（FAIL-OPEN）
try:
    from timesfm import TimesFm  # type: ignore
    _TIMESFM_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TIMESFM_AVAILABLE = False
    logger.debug("[FO-AGI-03] timesfm 不可用，降级为统计预测")

try:
    import signatory  # type: ignore
    _SIGNATORY_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SIGNATORY_AVAILABLE = False

try:
    # Stable-Neural-SDEs 或 torch 可用
    import torch  # type: ignore
    # 修复: PyTorch OpenMP tanh_kernel 在 Apple Silicon 多线程下 SIGSEGV
    torch.set_num_threads(1)
    _TORCH_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TORCH_AVAILABLE = False


class DeepReasoningEngine:
    """深度学习推理引擎（万物皆数·最小阻力路径）.

    无LLM·纯数据驱动：
      签名抽象 → Neural SDE动态 → TimesFM预测 → 蒙特卡洛 → 最小阻力路径
    """

    def __init__(self, signature_depth: int = 3) -> None:
        self._signature_engine = SignatureEngine(depth=signature_depth)
        self._path_integral = PathIntegralEngine(n_paths=1000)
        self._timesfm_available = _TIMESFM_AVAILABLE
        self._signatory_available = _SIGNATORY_AVAILABLE
        self._torch_available = _TORCH_AVAILABLE
        # TimesFM 模型实例（懒加载）
        self._timesfm_model = None
        # Neural SDE 模型（懒加载）
        self._neural_sde_model = None
        self._neural_sde_loaded = False
        self._sde_backend_used: str = "unavailable"
        # GARCH fallback（懒加载）
        self._garch = None
        # FAIL-OPEN 告警计数器 (HC-AGI-03)
        self._fail_open_counter: dict[str, list[float]] = {}
        # Neural SDE 权重路径
        self._sde_model_path = str(
            Path(__file__).resolve().parents[1] / "data" / "neural_sde_v1.pt"
        )

    # ------------------------------------------------------------------
    # 后端状态
    # ------------------------------------------------------------------
    def backend_status(self) -> dict[str, Any]:
        """报告各深度学习后端的可用状态."""
        return {
            "timesfm": self._timesfm_available,
            "signatory": self._signatory_available,
            "neural_sde": self._torch_available,
            "neural_sde_trained": self._neural_sde_loaded,
            "neural_sde_backend": self._sde_backend_used,
        }

    # ------------------------------------------------------------------
    # 1. 路径抽象：签名方法
    # ------------------------------------------------------------------
    def path_to_signature(self, price_path: np.ndarray) -> np.ndarray:
        """价格路径 → 签名张量（万物皆数）.

        优先用 signatory，否则用 numpy 降级实现.
        """
        return self._signature_engine.signature(price_path)

    # ------------------------------------------------------------------
    # 2. Neural SDE 动态建模（4 级 FAIL-OPEN 降级链）
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

    def neural_sde_forecast(
        self,
        state: np.ndarray,
        horizon: int,
        n_paths: int = 1000,
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
                    paths = model.forecast(state, horizon, n_paths)
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
    # 3. TimesFM 时序预测
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
        """使用真实 TimesFM 模型预测."""
        try:
            if self._timesfm_model is None:
                self._timesfm_model = TimesFm(
                    context_len=min(len(history), 512),
                    horizon_len=horizon,
                    input_patch_len=32,
                    output_patch_len=128,
                    num_layers=20,
                    model_dims=1280,
                )
            # TimesFM 输入: shape (batch, seq_len)
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
    ) -> dict[str, Any]:
        """完整推理流程：签名→SDE→预测→采样→最优路径.

        FAIL-OPEN: 任一环节异常返回降级结果，不crash.
        """
        price_path = np.asarray(price_path, dtype=np.float64).ravel()

        # 1. 路径抽象
        try:
            signature = self.path_to_signature(price_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] 签名计算失败: %s", e)
            signature = np.array([])

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
            "forecast": forecast,
            "min_resistance_path": min_resistance_path,
            "min_resistance": float(min_resistance),
            "min_resistance_backend": mr.get("backend", "argmin") if isinstance(mr, dict) else "argmin",
            "min_resistance_converged": mr.get("converged", True) if isinstance(mr, dict) else True,
            "n_paths": len(paths),
            "backends": self.backend_status(),
            "sde_backend": self._sde_backend_used,
        }
