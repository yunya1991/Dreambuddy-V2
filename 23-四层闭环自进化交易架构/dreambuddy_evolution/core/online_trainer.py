"""P0.1 NeuralSDEOnlineTrainer: 在线学习 / 滚动重训.

解决 T7 OOS 根因 1: 数据分布漂移 (2024 与 2017-2023 分布不同).

策略: 在线 fine-tune (低 lr) + 定期 full retrain + EWC 防遗忘.

EWC (Elastic Weight Consolidation):
  - 在 fine-tune 前, 用旧数据计算 Fisher 信息矩阵 F 和最优参数 θ*
  - fine-tune 时, 总 loss = task_loss + (ewc_lambda/2) * Σ F_i * (θ_i - θ*_i)^2
  - 防止灾难性遗忘: 对旧任务重要的权重 (高 F) 受到更强保护
"""
from __future__ import annotations

import copy
import logging
import math
from datetime import datetime
from typing import Any, Optional

import numpy as np

from .neural_sde_model import NeuralSDEModel, NeuralSDETrainer

logger = logging.getLogger(__name__)


class NeuralSDEOnlineTrainer:
    """Neural SDE 在线学习器.

    混合策略: 在线 fine-tune (低 lr) + 定期 full retrain (每季度) + EWC 防遗忘.

    Args:
        base_model: 已训练的 NeuralSDEModel
        fine_tune_lr: fine-tune 学习率 (默认 1e-5, 比训练 lr 小 10x)
        rolling_window: 滑动训练窗口大小 (默认 2y = 24*365*2 points)
        ewc_lambda: EWC 正则化强度 (默认 1000.0)
        retrain_interval_days: full retrain 间隔天数 (默认 90 = 每季度)
    """

    def __init__(
        self,
        base_model: NeuralSDEModel,
        fine_tune_lr: float = 1e-5,
        rolling_window: int = 24 * 365 * 2,
        ewc_lambda: float = 1000.0,
        retrain_interval_days: int = 90,
    ):
        self.model = base_model
        self.fine_tune_lr = float(fine_tune_lr)
        self.rolling_window = int(rolling_window)
        self.ewc_lambda = float(ewc_lambda)
        self.retrain_interval_days = int(retrain_interval_days)

        # EWC 状态: Fisher 信息和最优参数 (full retrain 后更新)
        self._fisher: dict[str, Any] = {}
        self._optimal_params: dict[str, Any] = {}
        # 上次 full retrain 的权重备份 (FAIL-OPEN 回退)
        self._last_full_retrain_state: Optional[dict] = None

        self._torch = __import__("torch") if self.model.is_available else None

    # ------------------------------------------------------------------
    # 滑动窗口
    # ------------------------------------------------------------------
    def _apply_rolling_window(self, closes: np.ndarray) -> np.ndarray:
        """截断过旧数据, 只保留最近 rolling_window 个点.

        防止分布漂移: 过旧数据与当前分布差异大, 会干扰 fine-tune.
        """
        closes = np.asarray(closes, dtype=np.float64).ravel()
        if len(closes) > self.rolling_window:
            return closes[-self.rolling_window:]
        return closes

    # ------------------------------------------------------------------
    # EWC (Elastic Weight Consolidation)
    # ------------------------------------------------------------------
    def _compute_fisher(
        self, closes: np.ndarray, regime_labels: Optional[np.ndarray] = None,
        n_samples: int = 200,
    ) -> dict[str, Any]:
        """计算 Fisher 信息矩阵 (对角线近似).

        F_i = E[(∂log p(y|x)/∂θ_i)^2]

        简化: 用 MSE loss 的梯度平方近似 (回归任务).
        采样 n_samples 个窗口计算梯度平方的期望.

        Returns:
            dict: param_name → Fisher diagonal tensor
        """
        if not self.model.is_available:
            return {}

        torch = self._torch
        model = self.model

        fisher = {
            name: torch.zeros_like(p)
            for name, p in model.drift_net.named_parameters()
        }

        closes = self._apply_rolling_window(closes)
        if len(closes) < 100:
            return fisher

        # 随机采样 n_samples 个窗口
        seq_len = 64
        horizon = 20
        n_valid = len(closes) - seq_len - horizon
        if n_valid <= 0:
            return fisher

        indices = np.random.choice(n_valid, min(n_samples, n_valid), replace=False)

        model.drift_net.eval()
        for idx in indices:
            inp = closes[idx:idx + seq_len]
            tgt = closes[idx + seq_len:idx + seq_len + horizon]
            # 归一化
            price_mean = float(np.mean(inp))
            price_std = float(np.std(inp)) if np.std(inp) > 0 else 1.0
            inp_norm = (inp - price_mean) / price_std
            tgt_norm = (tgt - price_mean) / price_std

            y = torch.tensor([[inp_norm[-1]]], dtype=torch.float32)
            targets = torch.tensor([tgt_norm], dtype=torch.float32)

            # 前向
            log_sig_t = None
            regime_onehot = None
            model._current_log_sig = log_sig_t
            model._current_regime = regime_onehot
            model._current_transition = None

            path = torch.zeros(1, horizon)
            for t_step in range(horizon):
                drift = model.f(float(t_step), y)
                y = y + drift
                path[:, t_step] = y.squeeze(-1)

            model._current_log_sig = None
            model._current_regime = None
            model._current_transition = None

            # MSE loss
            loss = torch.nn.functional.mse_loss(path, targets)
            model.drift_net.zero_grad()
            loss.backward()

            # 累积梯度平方
            for name, p in model.drift_net.named_parameters():
                if p.grad is not None:
                    fisher[name] += p.grad.detach() ** 2

        # 平均
        for name in fisher:
            fisher[name] /= len(indices)

        return fisher

    def _ewc_loss(self, fisher: dict[str, Any], optimal_params: dict[str, Any]) -> Any:
        """计算 EWC 正则化 loss.

        EWC_loss = (λ/2) * Σ F_i * (θ_i - θ*_i)^2

        Args:
            fisher: param_name → Fisher diagonal tensor
            optimal_params: param_name → 最优参数 tensor (full retrain 后保存)

        Returns:
            scalar tensor (EWC loss)
        """
        if not fisher or not optimal_params:
            return self._torch.tensor(0.0)

        torch = self._torch
        loss = torch.tensor(0.0)
        for name, p in self.model.drift_net.named_parameters():
            if name in fisher and name in optimal_params:
                f = fisher[name]
                theta_star = optimal_params[name]
                loss = loss + (f * (p - theta_star) ** 2).sum()
        return loss * 0.5 * self.ewc_lambda

    def _save_optimal_params(self) -> None:
        """保存当前权重作为 EWC 的最优参数 θ* (full retrain 后调用)."""
        if not self.model.is_available:
            return
        self._optimal_params = {
            name: p.detach().clone()
            for name, p in self.model.drift_net.named_parameters()
        }

    def _backup_full_retrain_state(self) -> None:
        """备份当前权重 (FAIL-OPEN: 在线训练失败时回退)."""
        if not self.model.is_available:
            return
        self._last_full_retrain_state = {
            name: p.detach().clone()
            for name, p in self.model.drift_net.named_parameters()
        }

    def _restore_full_retrain_state(self) -> None:
        """回退到上次 full retrain 的权重 (FAIL-OPEN)."""
        if not self.model.is_available or self._last_full_retrain_state is None:
            return
        with self._torch.no_grad():
            for name, p in self.model.drift_net.named_parameters():
                if name in self._last_full_retrain_state:
                    p.copy_(self._last_full_retrain_state[name])
        logger.warning("[NeuralSDE-Online] FAIL-OPEN: 回退到上次 full retrain 权重")

    # ------------------------------------------------------------------
    # 在线 fine-tune
    # ------------------------------------------------------------------
    def fine_tune(
        self,
        new_closes: np.ndarray,
        regime_labels: Optional[np.ndarray] = None,
        epochs: int = 10,
    ) -> dict[str, Any]:
        """增量 fine-tune 现有权重 (低 lr, 少 epochs + EWC 防遗忘).

        Args:
            new_closes: 新数据窗口 close 序列
            regime_labels: 可选 regime 标签 (与 new_closes 等长)
            epochs: fine-tune 轮数 (默认 10, 远少于 full retrain)

        Returns:
            report dict (status, n_windows, final_loss)
        """
        if not self.model.is_available:
            return {"status": "skipped", "reason": "torch not available"}

        torch = self._torch
        closes = self._apply_rolling_window(new_closes)

        if len(closes) < 100:
            return {"status": "skipped", "reason": "insufficient data"}

        # 如果还没有 Fisher 信息, 先用当前数据计算 (首次 fine-tune)
        if not self._fisher:
            logger.info("[NeuralSDE-Online] 首次 fine-tune, 计算 Fisher 信息...")
            self._fisher = self._compute_fisher(closes, regime_labels)
            self._save_optimal_params()
            self._backup_full_retrain_state()

        # 构建训练器 (低 lr)
        trainer = NeuralSDETrainer(
            model=self.model, lr=self.fine_tune_lr,
            seq_len=64, horizon=20, batch_size=64, loss_type="mse",
        )

        # 准备数据
        from .neural_sde_model import MIN_SAMPLES_FOR_ACTIVATION
        windows = trainer.prepare_data(
            closes, regime_labels=regime_labels, regime_balance="natural",
        )
        if len(windows) < MIN_SAMPLES_FOR_ACTIVATION:
            return {"status": "insufficient_samples", "n_windows": len(windows)}

        # EWC fine-tune 循环
        optimizer = torch.optim.Adam(
            list(self.model.drift_net.parameters()) +
            list(self.model.diffusion_net.parameters()),
            lr=self.fine_tune_lr,
        )

        np.random.shuffle(windows)
        total_loss = 0.0
        n_batches = 0
        bs = trainer.batch_size
        dt = 1.0
        sqrt_dt = math.sqrt(dt)

        for epoch in range(epochs):
            for i in range(0, len(windows), bs):
                batch = windows[i:i + bs]
                if not batch:
                    continue
                batch_size = len(batch)

                s0_arr = np.array([[inp[-1]] for inp, _, _, _ in batch], dtype=np.float32)
                tgt_arr = np.array([tgt for _, tgt, _, _ in batch], dtype=np.float32)
                log_sig_arr = np.array([ls for _, _, ls, _ in batch], dtype=np.float32)
                regime_arr = np.array([reg for _, _, _, reg in batch], dtype=np.int64)

                y = torch.tensor(s0_arr)
                targets = torch.tensor(tgt_arr)
                log_sig_t = torch.tensor(log_sig_arr)

                n_regimes = getattr(self.model, "n_regimes", 3)
                if n_regimes > 0:
                    regime_clamped = np.clip(regime_arr, 0, n_regimes - 1)
                    regime_onehot = torch.zeros(batch_size, n_regimes)
                    regime_onehot.scatter_(1, torch.tensor(regime_clamped).unsqueeze(1), 1.0)
                else:
                    regime_onehot = None

                self.model._current_log_sig = log_sig_t
                self.model._current_regime = regime_onehot
                self.model._current_transition = None

                path = torch.zeros(batch_size, trainer.horizon)
                for t_step in range(trainer.horizon):
                    drift = self.model.f(float(t_step), y)
                    diff = self.model.g(float(t_step), y)
                    z = torch.randn_like(y)
                    y = y + drift * dt + diff * sqrt_dt * z
                    path[:, t_step] = y.squeeze(-1)

                self.model._current_log_sig = None
                self.model._current_regime = None
                self.model._current_transition = None

                # task loss + EWC loss
                task_loss = torch.nn.functional.mse_loss(path, targets)
                ewc_loss = self._ewc_loss(self._fisher, self._optimal_params)
                loss = task_loss + ewc_loss

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                total_loss += float(loss.item())
                n_batches += 1

        avg_loss = total_loss / max(n_batches, 1)
        return {
            "status": "ok",
            "n_windows": len(windows),
            "final_loss": avg_loss,
            "epochs": epochs,
            "ewc_lambda": self.ewc_lambda,
        }

    # ------------------------------------------------------------------
    # Full retrain (每季度)
    # ------------------------------------------------------------------
    def full_retrain(
        self,
        closes: np.ndarray,
        regime_labels: Optional[np.ndarray] = None,
        epochs: int = 200,
    ) -> dict[str, Any]:
        """从头完整训练 (每季度调用).

        用滑动窗口内的全部数据从头训练, 然后更新 Fisher/最优参数.

        Args:
            closes: 训练数据 close 序列
            regime_labels: 可选 regime 标签
            epochs: 训练轮数 (默认 200)

        Returns:
            report dict
        """
        if not self.model.is_available:
            return {"status": "skipped", "reason": "torch not available"}

        closes = self._apply_rolling_window(closes)

        # 重置模型 (从头训练)
        torch = self._torch
        for p in self.model.drift_net.parameters():
            if p.dim() > 1:
                torch.nn.init.xavier_uniform_(p)
            else:
                torch.nn.init.zeros_(p)

        trainer = NeuralSDETrainer(
            model=self.model, lr=1e-4, seq_len=64, horizon=20,
            batch_size=64, loss_type="mse",
        )

        report = trainer.train(
            closes, epochs=epochs,
            regime_labels=regime_labels, regime_balance="natural",
        )

        if report.get("status") == "ok":
            # 更新 EWC 状态
            self._fisher = self._compute_fisher(closes, regime_labels)
            self._save_optimal_params()
            self._backup_full_retrain_state()
            logger.info("[NeuralSDE-Online] Full retrain 完成, Fisher/最优参数已更新")

        return report

    # ------------------------------------------------------------------
    # retrain 调度
    # ------------------------------------------------------------------
    def should_retrain(
        self, current_time: datetime, last_retrain_time: datetime,
    ) -> bool:
        """判断是否需要 full retrain (间隔阈值).

        Args:
            current_time: 当前时间
            last_retrain_time: 上次 full retrain 时间

        Returns:
            True 如果距离上次 retrain 超过 retrain_interval_days
        """
        delta_days = (current_time - last_retrain_time).total_seconds() / 86400.0
        return delta_days >= self.retrain_interval_days
