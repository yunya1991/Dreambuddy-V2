"""
Phase 2.3: Neural SDE 模型 — 连续时间动态建模
SPEC-AGI升级蓝图.md §4.2.3 / HC-AGI-13

核心: dS = fθ(S,t)dt + gφ(S,t)dW
  - drift_net fθ: 学习价格漂移趋势
  - diffusion_net gφ: 学习波动率（正值约束）

蓝本: Stable-Neural-SDEs (ICLR 2024)
  - Ito SDE, diagonal noise
  - tanh 裁剪防 drift 爆炸
  - sin/cos 时间特征

FAIL-OPEN:
  Level 1: torchsde.sdeint()（若 torchsde 可用）
  Level 2: 手写 Euler-Maruyama 积分（纯 torch）
  Level 3: GARCH(1,1)（HC-AGI-13，样本 < 1000）
  Level 4: GBM（最后兜底，在 deep_reasoning_engine 中）

参考模式: exit_rl_policy.py CQLTrainer 的延迟导入 / _available 标志 / save-load
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# 延迟导入 torch（允许无 torch 时模块仍可加载）
try:
    import torch
    import torch.nn as nn

    # 修复: PyTorch OpenMP tanh_kernel 在 Apple Silicon 多线程下 SIGSEGV (Sleef_tanhf4_u10)
    # 设置单线程避免 OpenMP 并行冲突，不影响 Neural SDE 性能（路径采样本身已向量化）
    torch.set_num_threads(1)

    _TORCH_AVAILABLE = True
except ImportError:  # noqa: BLE001
    _TORCH_AVAILABLE = False
    logger.debug("[FO-AGI-03] torch 不可用, NeuralSDEModel 将降级")

# 尝试导入 torchsde（可选加速）
try:
    import torchsde  # type: ignore

    _TORCHSDE_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TORCHSDE_AVAILABLE = False
    logger.debug("[FO-AGI-03] torchsde 不可用, 使用手写 Euler-Maruyama 积分")

# HC-AGI-13: 训练样本阈值
MIN_SAMPLES_FOR_ACTIVATION = 1000

# 模型超参默认值
DEFAULT_HIDDEN_DIM = 64
DEFAULT_DIFFUSION_HIDDEN = 32
DEFAULT_DRIFT_CLIP = 2.0
DEFAULT_DIFFUSION_FLOOR = 0.001


class _DriftNet(nn.Module if _TORCH_AVAILABLE else object):
    """Drift 网络 fθ(S_t, t) → 标量漂移."""

    def __init__(self, hidden_dim: int = DEFAULT_HIDDEN_DIM, clip: float = DEFAULT_DRIFT_CLIP):
        if not _TORCH_AVAILABLE:
            return
        super().__init__()
        # 输入: [S_t, sin(2πt/T), cos(2πt/T)] = 3维
        self.net = nn.Sequential(
            nn.Linear(3, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )
        self.clip = clip

    def forward(self, t: "torch.Tensor", y: "torch.Tensor") -> "torch.Tensor":
        if not _TORCH_AVAILABLE:
            return torch.zeros(y.size(0), 1)
        # 时间特征
        t_batch = torch.full((y.size(0), 1), float(t), device=y.device)
        time_features = torch.cat([torch.sin(2 * math.pi * t_batch), torch.cos(2 * math.pi * t_batch)], dim=-1)
        x = torch.cat([y, time_features], dim=-1)
        out = self.net(x)
        return torch.tanh(out) * self.clip  # tanh 裁剪防爆炸


class _DiffusionNet(nn.Module if _TORCH_AVAILABLE else object):
    """Diffusion 网络 gφ(S_t, t) → 正标量波动率."""

    def __init__(
        self,
        hidden_dim: int = DEFAULT_DIFFUSION_HIDDEN,
        floor: float = DEFAULT_DIFFUSION_FLOOR,
    ):
        if not _TORCH_AVAILABLE:
            return
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(3, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )
        self.floor = floor

    def forward(self, t: "torch.Tensor", y: "torch.Tensor") -> "torch.Tensor":
        if not _TORCH_AVAILABLE:
            return torch.ones(y.size(0), 1) * self.floor
        t_batch = torch.full((y.size(0), 1), float(t), device=y.device)
        time_features = torch.cat([torch.sin(2 * math.pi * t_batch), torch.cos(2 * math.pi * t_batch)], dim=-1)
        x = torch.cat([y, time_features], dim=-1)
        out = self.net(x)
        return torch.nn.functional.softplus(out) + self.floor  # 确保正值


class NeuralSDEModel:
    """Neural SDE 模型: drift + diffusion + 积分 + 持久化.

    遵循 CQLTrainer 模式:
      - 延迟导入 torch, _available 标志
      - save()/load() 权重持久化
      - maybe_activate() 样本阈值门禁 (HC-AGI-13)
    """

    def __init__(
        self,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        diffusion_hidden: int = DEFAULT_DIFFUSION_HIDDEN,
        drift_clip: float = DEFAULT_DRIFT_CLIP,
        diffusion_floor: float = DEFAULT_DIFFUSION_FLOOR,
        device: str = "cpu",
    ):
        self._available = _TORCH_AVAILABLE
        self._torchsde_available = _TORCHSDE_AVAILABLE
        self.device = device
        self.hidden_dim = hidden_dim
        self.diffusion_hidden = diffusion_hidden
        self.drift_clip = drift_clip
        self.diffusion_floor = diffusion_floor

        # 归一化参数
        self._price_mean = 0.0
        self._price_std = 1.0

        # 激活状态
        self._activated = False
        self._sample_count = 0

        if self._available:
            self._torch = torch
            self._nn = nn
            self.drift_net = _DriftNet(hidden_dim, drift_clip).to(device)
            self.diffusion_net = _DiffusionNet(diffusion_hidden, diffusion_floor).to(device)
        else:
            self._torch = None
            self.drift_net = None
            self.diffusion_net = None

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def is_activated(self) -> bool:
        return self._activated and self._available

    @property
    def torchsde_available(self) -> bool:
        return self._torchsde_available

    def record_sample(self, count: int = 1) -> None:
        """记录训练样本数."""
        self._sample_count += count
        if not self._activated and self._sample_count >= MIN_SAMPLES_FOR_ACTIVATION:
            self._activated = True
            logger.info(
                "[NeuralSDE] 自动激活: 样本 %d >= %d (HC-AGI-01)",
                self._sample_count, MIN_SAMPLES_FOR_ACTIVATION,
            )

    def maybe_activate(self, sample_count: int) -> bool:
        """HC-AGI-13: 样本 ≥ 1000 时自动激活."""
        if sample_count >= MIN_SAMPLES_FOR_ACTIVATION:
            self._activated = True
            self._sample_count = sample_count
            return True
        return False

    # ------------------------------------------------------------------
    # SDE 接口（兼容 torchsde.sdeint）
    # ------------------------------------------------------------------
    @property
    def sde_type(self) -> str:
        return "ito"

    @property
    def noise_type(self) -> str:
        return "diagonal"

    def f(self, t: "torch.Tensor", y: "torch.Tensor") -> "torch.Tensor":
        """Drift 函数 fθ(S_t, t)."""
        return self.drift_net(t, y)

    def g(self, t: "torch.Tensor", y: "torch.Tensor") -> "torch.Tensor":
        """Diffusion 函数 gφ(S_t, t)."""
        return self.diffusion_net(t, y)

    # ------------------------------------------------------------------
    # Level 1: torchsde 积分
    # ------------------------------------------------------------------
    def forecast_torchsde(
        self,
        state: np.ndarray,
        horizon: int,
        n_paths: int,
    ) -> np.ndarray:
        """Level 1: 使用 torchsde.sdeint() 生成路径.

        Returns:
            shape (n_paths, horizon+1) numpy 数组
        """
        if not self._available or not self._torchsde_available:
            raise RuntimeError("torchsde not available")

        with self._torch.no_grad():
            init_price = float(state[0])
            # 归一化初始状态
            s0 = (init_price - self._price_mean) / max(self._price_std, 1e-8)
            y0 = self._torch.full((n_paths, 1), float(s0), device=self.device)
            ts = self._torch.linspace(0, horizon, horizon + 1, device=self.device)

            # torchsde 积分
            z_t = torchsde.sdeint(
                sde=self,
                y0=y0,
                ts=ts,
                method="euler",
                dt=1.0,
            )
            # z_t: (horizon+1, n_paths, 1) → (n_paths, horizon+1)
            z_t = z_t.squeeze(-1).transpose(0, 1).cpu().numpy()

            # 反归一化
            paths = z_t * self._price_std + self._price_mean
            paths[:, 0] = init_price  # 保证起点

        return paths.astype(np.float64)

    # ------------------------------------------------------------------
    # Level 2: 手写 Euler-Maruyama 积分
    # ------------------------------------------------------------------
    def forecast_euler_maruyama(
        self,
        state: np.ndarray,
        horizon: int,
        n_paths: int,
    ) -> np.ndarray:
        """Level 2: 手写 EM 离散积分（torchsde 不可用时）.

        Euler-Maruyama:
          S_{t+1} = S_t + fθ(S_t, t)·dt + gφ(S_t, t)·√dt · Z

        Returns:
            shape (n_paths, horizon+1) numpy 数组
        """
        if not self._available:
            raise RuntimeError("torch not available")

        with self._torch.no_grad():
            init_price = float(state[0])
            s0 = (init_price - self._price_mean) / max(self._price_std, 1e-8)
            y = self._torch.full((n_paths, 1), float(s0), device=self.device)
            dt = 1.0
            paths = np.zeros((n_paths, horizon + 1), dtype=np.float64)
            paths[:, 0] = init_price

            for t_step in range(horizon):
                t_val = float(t_step)
                drift = self.f(t_val, y)
                diff = self.g(t_val, y)
                z = self._torch.randn_like(y)
                y = y + drift * dt + diff * math.sqrt(dt) * z
                # 反归一化
                price = y.squeeze(-1).cpu().numpy() * self._price_std + self._price_mean
                paths[:, t_step + 1] = price

        # NaN 检测
        if np.any(np.isnan(paths)) or np.any(np.isinf(paths)):
            raise RuntimeError("Euler-Maruyama 产生 NaN/Inf")

        return paths

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------
    def forecast(
        self,
        state: np.ndarray,
        horizon: int,
        n_paths: int = 1000,
    ) -> Optional[np.ndarray]:
        """统一预测入口: 优先 torchsde, 降级 EM.

        Returns:
            shape (n_paths, horizon+1) numpy 数组, 或 None 表示不可用
        """
        if not self.is_activated:
            return None

        try:
            if self._torchsde_available:
                return self.forecast_torchsde(state, horizon, n_paths)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] torchsde 积分失败, 降级 EM: %s", e)

        try:
            return self.forecast_euler_maruyama(state, horizon, n_paths)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] EM 积分失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save(self, path: str) -> None:
        """保存模型权重 (参考 CQLTrainer.save)."""
        if not self._available:
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._torch.save({
            "drift_net_state_dict": self.drift_net.state_dict(),
            "diffusion_net_state_dict": self.diffusion_net.state_dict(),
            "price_mean": self._price_mean,
            "price_std": self._price_std,
            "hidden_dim": self.hidden_dim,
            "diffusion_hidden": self.diffusion_hidden,
            "drift_clip": self.drift_clip,
            "diffusion_floor": self.diffusion_floor,
            "sample_count": self._sample_count,
            "activated": self._activated,
        }, str(path))
        logger.info("[NeuralSDE] 模型保存到 %s", path)

    def load(self, path: str) -> bool:
        """加载模型权重 (参考 CQLTrainer.load).

        Returns:
            True if load succeeded.
        """
        if not self._available:
            return False
        path = Path(path)
        if not path.exists():
            logger.debug("[NeuralSDE] 权重文件不存在: %s", path)
            return False
        try:
            ckpt = self._torch.load(str(path), map_location=self.device, weights_only=False)
            self.drift_net.load_state_dict(ckpt["drift_net_state_dict"])
            self.diffusion_net.load_state_dict(ckpt["diffusion_net_state_dict"])
            self._price_mean = float(ckpt.get("price_mean", 0.0))
            self._price_std = float(ckpt.get("price_std", 1.0))
            self._sample_count = int(ckpt.get("sample_count", 0))
            self._activated = bool(ckpt.get("activated", False))
            self.drift_net.eval()
            self.diffusion_net.eval()
            logger.info(
                "[NeuralSDE] 模型加载成功: %s (activated=%s, samples=%d)",
                path, self._activated, self._sample_count,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] 模型加载失败: %s", e)
            return False

    def set_normalization(self, prices: np.ndarray) -> None:
        """从历史价格序列计算归一化参数."""
        prices = np.asarray(prices, dtype=np.float64).ravel()
        if len(prices) > 0:
            self._price_mean = float(np.mean(prices))
            self._price_std = float(np.std(prices)) if float(np.std(prices)) > 0 else 1.0


class NeuralSDETrainer:
    """Neural SDE 训练器.

    训练策略:
      1. 从历史 close 序列计算对数收益率
      2. 滑动窗口切分 (seq_len=64, horizon=20)
      3. 用 SDE 积分生成路径, MSE loss 对齐真实未来窗口
      4. Adam 优化器 (lr=1e-4)
    """

    def __init__(
        self,
        model: NeuralSDEModel,
        lr: float = 1e-4,
        seq_len: int = 64,
        horizon: int = 20,
        batch_size: int = 64,
    ):
        self.model = model
        self.lr = lr
        self.seq_len = seq_len
        self.horizon = horizon
        self.batch_size = batch_size

        self._torch = torch if self.model.is_available else None

        if self.model.is_available:
            self._optimizer = torch.optim.Adam(
                list(self.model.drift_net.parameters()) +
                list(self.model.diffusion_net.parameters()),
                lr=lr,
            )

    def prepare_data(self, closes: np.ndarray, max_windows: int = 3000) -> list[tuple[np.ndarray, np.ndarray]]:
        """滑动窗口切分.

        Args:
            closes: 历史 close 序列
            max_windows: 最大窗口数（子采样以控制训练时间）

        Returns:
            list of (input_window, target_window)
        """
        closes = np.asarray(closes, dtype=np.float64).ravel()
        if len(closes) < self.seq_len + self.horizon:
            return []

        # 归一化
        self.model.set_normalization(closes)
        normed = (closes - self.model._price_mean) / max(self.model._price_std, 1e-8)

        windows = []
        for i in range(len(normed) - self.seq_len - self.horizon + 1):
            inp = normed[i:i + self.seq_len]
            tgt = normed[i + self.seq_len:i + self.seq_len + self.horizon]
            windows.append((inp, tgt))

        # 子采样控制训练时间
        if len(windows) > max_windows:
            indices = np.random.choice(len(windows), max_windows, replace=False)
            indices.sort()
            windows = [windows[i] for i in indices]

        return windows

    def train_epoch(self, windows: list[tuple[np.ndarray, np.ndarray]]) -> float:
        """训练一个 epoch, 返回平均 loss.

        向量化: 整个 batch 同时积分, 而非逐窗口循环.
        """
        if not self.model.is_available:
            return 0.0

        self.model.drift_net.train()
        self.model.diffusion_net.train()
        np.random.shuffle(windows)
        total_loss = 0.0
        n_batches = 0
        dt = 1.0
        sqrt_dt = math.sqrt(dt)

        for i in range(0, len(windows), self.batch_size):
            batch = windows[i:i + self.batch_size]
            if not batch:
                continue
            bs = len(batch)

            # 批量构建初始状态和目标
            s0_arr = np.array([[inp[-1]] for inp, _ in batch], dtype=np.float32)
            tgt_arr = np.array([tgt for _, tgt in batch], dtype=np.float32)  # (bs, horizon)

            y = self._torch.tensor(s0_arr, device=self.model.device)  # (bs, 1)
            targets = self._torch.tensor(tgt_arr, device=self.model.device)  # (bs, horizon)

            self._optimizer.zero_grad()

            # 向量化 SDE 积分: 整个 batch 同时推进 horizon 步
            path = torch.zeros(bs, self.horizon, device=self.model.device)
            for t_step in range(self.horizon):
                t_val = float(t_step)
                drift = self.model.f(t_val, y)       # (bs, 1)
                diff = self.model.g(t_val, y)         # (bs, 1)
                z = self._torch.randn_like(y)         # (bs, 1)
                y = y + drift * dt + diff * sqrt_dt * z
                path[:, t_step] = y.squeeze(-1)

            # MSE loss: (bs, horizon) vs (bs, horizon)
            batch_loss = self._torch.nn.functional.mse_loss(path, targets)
            batch_loss.backward()
            self._optimizer.step()
            total_loss += float(batch_loss.item())
            n_batches += 1

        return total_loss / max(n_batches, 1)

    def train(
        self,
        closes: np.ndarray,
        epochs: int = 200,
    ) -> dict[str, Any]:
        """完整训练流程.

        Returns:
            training report dict
        """
        if not self.model.is_available:
            return {"status": "skipped", "reason": "torch not available"}

        windows = self.prepare_data(closes)
        if len(windows) < MIN_SAMPLES_FOR_ACTIVATION:
            logger.warning(
                "[NeuralSDE] 训练样本 %d < %d, 无法激活 (HC-AGI-13)",
                len(windows), MIN_SAMPLES_FOR_ACTIVATION,
            )
            return {"status": "insufficient_samples", "n_windows": len(windows)}

        losses = []
        for epoch in range(epochs):
            avg_loss = self.train_epoch(windows)
            losses.append(avg_loss)
            if (epoch + 1) % 10 == 0:
                logger.info("[NeuralSDE] epoch %d/%d loss=%.6f", epoch + 1, epochs, avg_loss)

        # 激活模型
        self.model._sample_count = len(windows)
        self.model._activated = True

        return {
            "status": "ok",
            "epochs": epochs,
            "n_windows": len(windows),
            "final_loss": losses[-1] if losses else 0.0,
            "losses": losses,
        }
