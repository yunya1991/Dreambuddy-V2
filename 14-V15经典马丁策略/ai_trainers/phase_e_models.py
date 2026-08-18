"""Phase E: PPO-LSTM Actor-Critic 网络定义 (v6: tanh-bounded actor)

路线图 §5.1: LSTM 共享 encoder + Actor (4 continuous Gaussian + 1 discrete Categorical)
+ Critic (value head)。

v6 关键修复：
- cont_mean 加 torch.tanh 激活，将均值限制在 [-1, 1]
- 通过 map_action_to_bounds 线性映射到 ACTION_BOUNDS [lo, hi]
- 修复 v4/v5 中 PPO 无界输出(±9~17)导致 clamp 零梯度、贴边二值策略的问题
- 梯度可流过 tanh，PPO 能学到边界内的连续策略

用于 phase_e_train_ppo.py 训练 + PhaseEGateway 推理。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Normal, Categorical


# v6: 默认动作边界（k_bound=0.80 时的有效边界，与 v15_gym_env.ACTION_BOUNDS + _apply_k_bound_to_bounds 一致）
DEFAULT_ACTION_BOUNDS: List[Tuple[float, float]] = [
    (0.75, 1.24),    # addon_pct_mult
    (0.50, 1.40),    # addon_size_mult
    (0.75, 1.24),    # tp_pct_mult
    (0.625, 1.16),   # base_position_mult
]


class PPOLSTMActorCritic(nn.Module):
    """PPO-LSTM Actor-Critic 网络 (v6: tanh-bounded actor)。

    输入: (B, T, 34) 状态序列
    输出:
      - Actor: 4 continuous actions (Gaussian mean+std, tanh-bounded) + 1 discrete (Categorical)
      - Critic: value estimate (B, 1)

    v6: cont_mean = tanh(linear) → [-1, 1]，再映射到 action_bounds [lo, hi]
    """

    def __init__(
        self,
        state_dim: int = 34,
        hidden_dim: int = 128,
        num_layers: int = 1,
        n_continuous: int = 4,
        n_discrete: int = 2,  # max_addons_delta ∈ {-1, 0} → 2 类
        action_bounds: Optional[List[Tuple[float, float]]] = None,
    ):
        super().__init__()
        self.state_dim = state_dim
        self.hidden_dim = hidden_dim
        self.n_continuous = n_continuous
        self.n_discrete = n_discrete

        # v6: 动作边界（register_buffer → 随 model state_dict 一起保存/加载）
        bounds = action_bounds if action_bounds is not None else DEFAULT_ACTION_BOUNDS
        self.register_buffer("action_lo", torch.tensor([b[0] for b in bounds], dtype=torch.float32))
        self.register_buffer("action_hi", torch.tensor([b[1] for b in bounds], dtype=torch.float32))

        # 共享 LSTM encoder
        self.lstm = nn.LSTM(
            input_size=state_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
        )

        # Actor heads
        self.actor_cont_mean = nn.Linear(hidden_dim, n_continuous)
        self.actor_cont_log_std = nn.Parameter(torch.zeros(n_continuous))  # 全局可学习 std
        self.actor_disc_logits = nn.Linear(hidden_dim, n_discrete)

        # Critic head
        self.critic = nn.Linear(hidden_dim, 1)

    def forward(
        self, x: torch.Tensor, h: Optional[Tuple[torch.Tensor, torch.Tensor]] = None
    ) -> Dict[str, torch.Tensor]:
        """前向传播。

        x: (B, T, state_dim) 或 (B, state_dim)
        h: (h_0, c_0) 可选初始隐状态
        返回 dict:
          cont_mean: (B, T, 4) 连续动作均值（tanh-bounded [-1, 1]）
          cont_std:  (4,) 连续动作标准差
          disc_logits: (B, T, 2) 离散动作 logits
          value: (B, T, 1) 价值估计
          h_n: (h_n, c_n) 最终隐状态
        """
        if x.ndim == 2:
            x = x.unsqueeze(1)  # (B, 1, state_dim)
        B, T, _ = x.shape

        if h is not None:
            lstm_out, h_n = self.lstm(x, h)
        else:
            lstm_out, h_n = self.lstm(x)

        # v6: tanh 限制均值到 [-1, 1]，梯度可流过
        cont_mean = torch.tanh(self.actor_cont_mean(lstm_out))  # (B, T, 4) in [-1, 1]
        cont_std = self.actor_cont_log_std.exp().expand(B, T, -1)  # (B, T, 4)
        disc_logits = self.actor_disc_logits(lstm_out)  # (B, T, 2)
        value = self.critic(lstm_out)  # (B, T, 1)

        return {
            "cont_mean": cont_mean,
            "cont_std": cont_std,
            "disc_logits": disc_logits,
            "value": value,
            "h_n": h_n,
        }

    def map_action_to_bounds(self, raw: torch.Tensor) -> torch.Tensor:
        """v6: 将 [-1, 1] 原始动作线性映射到 [lo, hi] 边界。

        raw < -1 → 映射到 lo（等价 clamp）
        raw > 1  → 映射到 hi
        raw ∈ [-1, 1] → 线性映射到 [lo, hi]

        用于:
        - PPO trainer: 将 sample_action 的原始输出映射后传给 env
        - get_action_dict: 推理时映射 mean
        """
        clamped = torch.clamp(raw, -1.0, 1.0)
        mapped = self.action_lo + (clamped + 1.0) / 2.0 * (self.action_hi - self.action_lo)
        return mapped

    def sample_action(
        self, x: torch.Tensor, h: Optional[Tuple[torch.Tensor, torch.Tensor]] = None
    ) -> Dict[str, torch.Tensor]:
        """采样动作（用于训练 rollout）。

        v6: cont_mean = tanh(linear) ∈ [-1, 1]
            action_cont 是 Normal(tanh_mean, std) 的原始采样（可超出 [-1, 1]）
            log_prob 针对原始采样计算（PPO 一致性）
            PPO trainer 调用 map_action_to_bounds 映射后传给 env

        返回:
          action_cont: (B, 4) 原始连续动作（未映射，用于 buffer/log_prob）
          action_disc: (B,) 离散动作 index
          log_prob: (B,) 总对数概率
          value: (B,) 价值
          entropy: (B,) 熵（用于 PPO ent_coef）
          h_n: 最终隐状态
        """
        out = self.forward(x, h)
        # 取最后一步
        cont_mean = out["cont_mean"][:, -1, :]  # (B, 4) tanh-bounded
        cont_std = out["cont_std"][:, -1, :]    # (B, 4)
        disc_logits = out["disc_logits"][:, -1, :]  # (B, 2)
        value = out["value"][:, -1, 0]  # (B,)

        # 采样连续动作（原始空间，用于 log_prob 一致性）
        dist_cont = Normal(cont_mean, cont_std)
        action_cont = dist_cont.rsample()  # (B, 4) — 可超出 [-1, 1]
        log_prob_cont = dist_cont.log_prob(action_cont).sum(dim=-1)  # (B,)

        # 采样离散动作
        dist_disc = Categorical(logits=disc_logits)
        action_disc = dist_disc.sample()  # (B,)
        log_prob_disc = dist_disc.log_prob(action_disc)  # (B,)

        # 合并
        log_prob = log_prob_cont + log_prob_disc
        entropy = dist_cont.entropy().sum(dim=-1) + dist_disc.entropy()

        return {
            "action_cont": action_cont,
            "action_disc": action_disc,
            "log_prob": log_prob,
            "value": value,
            "entropy": entropy,
            "h_n": out["h_n"],
        }

    def evaluate_actions(
        self,
        x: torch.Tensor,
        action_cont: torch.Tensor,
        action_disc: torch.Tensor,
        h: Optional[Tuple[torch.Tensor, torch.Tensor]] = None,
    ) -> Dict[str, torch.Tensor]:
        """评估给定动作的对数概率和价值（用于 PPO update）。

        v6: action_cont 是原始采样（buffer 存储），log_prob 针对原始采样计算。
        不需要 unmap——buffer 存的就是原始采样，evaluate 用同样的分布算 log_prob。
        """
        out = self.forward(x, h)
        cont_mean = out["cont_mean"][:, -1, :]
        cont_std = out["cont_std"][:, -1, :]
        disc_logits = out["disc_logits"][:, -1, :]
        value = out["value"][:, -1, 0]

        dist_cont = Normal(cont_mean, cont_std)
        log_prob_cont = dist_cont.log_prob(action_cont).sum(dim=-1)

        dist_disc = Categorical(logits=disc_logits)
        log_prob_disc = dist_disc.log_prob(action_disc)

        log_prob = log_prob_cont + log_prob_disc
        entropy = dist_cont.entropy().sum(dim=-1) + dist_disc.entropy()

        return {
            "log_prob": log_prob,
            "value": value,
            "entropy": entropy,
        }

    def get_action_dict(
        self, x: torch.Tensor, h: Optional[Tuple[torch.Tensor, torch.Tensor]] = None
    ) -> Dict[str, float]:
        """推理模式：返回确定性动作（mean + argmax），供 PhaseEGateway 使用。

        v6: cont_mean = tanh(linear) ∈ [-1, 1]，通过 map_action_to_bounds 映射到 [lo, hi]。
        """
        with torch.no_grad():
            out = self.forward(x, h)
            cont_mean = out["cont_mean"][:, -1, :]  # (B, 4) tanh-bounded [-1, 1]
            disc_logits = out["disc_logits"][:, -1, :]  # (B, 2)

            # v6: 映射到 action bounds [lo, hi]
            action_cont = self.map_action_to_bounds(cont_mean).squeeze(0)  # (4,)
            action_disc = disc_logits.argmax(dim=-1).squeeze(0)  # scalar

        # 映射到 action dict
        return {
            "addon_pct_mult": float(action_cont[0].item()),
            "addon_size_mult": float(action_cont[1].item()),
            "tp_pct_mult": float(action_cont[2].item()),
            "base_position_mult": float(action_cont[3].item()),
            "max_addons_delta": int(action_disc.item()) - 1,  # 0→-1, 1→0
        }
