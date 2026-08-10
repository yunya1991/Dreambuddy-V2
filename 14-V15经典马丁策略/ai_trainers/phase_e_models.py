"""Phase E: PPO-LSTM Actor-Critic 网络定义

路线图 §5.1: LSTM 共享 encoder + Actor (4 continuous Gaussian + 1 discrete Categorical)
+ Critic (value head)。

用于 phase_e_train_ppo.py 训练 + PhaseEGateway 推理。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Normal, Categorical


class PPOLSTMActorCritic(nn.Module):
    """PPO-LSTM Actor-Critic 网络。

    输入: (B, T, 34) 状态序列
    输出:
      - Actor: 4 continuous actions (Gaussian mean+std) + 1 discrete (Categorical logits)
      - Critic: value estimate (B, 1)
    """

    def __init__(
        self,
        state_dim: int = 34,
        hidden_dim: int = 128,
        num_layers: int = 1,
        n_continuous: int = 4,
        n_discrete: int = 2,  # max_addons_delta ∈ {-1, 0} → 2 类
    ):
        super().__init__()
        self.state_dim = state_dim
        self.hidden_dim = hidden_dim
        self.n_continuous = n_continuous
        self.n_discrete = n_discrete

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
          cont_mean: (B, T, 4) 连续动作均值
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

        cont_mean = self.actor_cont_mean(lstm_out)  # (B, T, 4)
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

    def sample_action(
        self, x: torch.Tensor, h: Optional[Tuple[torch.Tensor, torch.Tensor]] = None
    ) -> Dict[str, torch.Tensor]:
        """采样动作（用于训练 rollout）。

        返回:
          action_cont: (B, 4) 连续动作
          action_disc: (B,) 离散动作 index
          log_prob: (B,) 总对数概率
          value: (B,) 价值
          entropy: (B,) 熵（用于 PPO ent_coef）
        """
        out = self.forward(x, h)
        # 取最后一步
        cont_mean = out["cont_mean"][:, -1, :]  # (B, 4)
        cont_std = out["cont_std"][:, -1, :]    # (B, 4)
        disc_logits = out["disc_logits"][:, -1, :]  # (B, 2)
        value = out["value"][:, -1, 0]  # (B,)

        # 采样连续动作
        dist_cont = Normal(cont_mean, cont_std)
        action_cont = dist_cont.rsample()  # (B, 4)
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

        返回:
          log_prob: (B,)
          value: (B,)
          entropy: (B,)
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
        """推理模式：返回确定性动作（mean + argmax），供 PhaseEGateway 使用。"""
        with torch.no_grad():
            out = self.forward(x, h)
            cont_mean = out["cont_mean"][:, -1, :]  # (B, 4)
            disc_logits = out["disc_logits"][:, -1, :]  # (B, 2)

            action_cont = cont_mean.squeeze(0)  # (4,)
            action_disc = disc_logits.argmax(dim=-1).squeeze(0)  # scalar

        # 映射到 action dict
        return {
            "addon_pct_mult": float(action_cont[0].item()),
            "addon_size_mult": float(action_cont[1].item()),
            "tp_pct_mult": float(action_cont[2].item()),
            "base_position_mult": float(action_cont[3].item()),
            "max_addons_delta": int(action_disc.item()) - 1,  # 0→-1, 1→0
        }
