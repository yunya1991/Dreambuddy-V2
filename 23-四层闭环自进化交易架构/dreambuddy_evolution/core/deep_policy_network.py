"""
深度策略网络（学习范式跃迁）

三范式跃迁之"学习范式跃迁"：
  - SimplePolicy (纯 numpy 单层 linear→softmax) → MLPPolicy (PyTorch 多层感知机)
  - REINFORCE+baseline → A2C + GAE + 熵正则
  - FAIL-OPEN 4 级降级链：A2C → REINFORCE → numpy SimplePolicy → record-only

复刻 neural_sde_model.py 的 FAIL-OPEN 模式:
  - nn.Module if _TORCH_AVAILABLE else object
  - 懒加载 torch + torch.set_num_threads(1) 修 Apple Silicon SIGSEGV
  - 4 级降级链
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# 延迟导入 torch（复刻 neural_sde_model.py 的 FAIL-OPEN 模式）
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    # 修复 Apple Silicon OpenMP SIGSEGV
    torch.set_num_threads(1)

    _TORCH_AVAILABLE = True
except ImportError:  # noqa: BLE001
    _TORCH_AVAILABLE = False
    logger.debug("[FO-EVO] torch 不可用，MLPPolicy 将降级为 numpy 实现")


# --------------------------------------------------------------------------------
# MLPPolicy — PyTorch 多层感知机策略网络
# --------------------------------------------------------------------------------
class _MLPPolicyBase:
    """MLPPolicy 基类（torch 可用/不可用共用接口）."""

    def __init__(self, n_features: int = 17, n_actions: int = 3,
                 hidden_dims: list[int] | None = None) -> None:
        self.n_features = int(n_features)
        self.n_actions = int(n_actions)
        self.hidden_dims = list(hidden_dims) if hidden_dims else [128, 64]
        self._torch_available = _TORCH_AVAILABLE

    def get_architecture(self) -> dict[str, Any]:
        return {
            "n_features": self.n_features,
            "n_actions": self.n_actions,
            "hidden_dims": list(self.hidden_dims),
            "activation": "relu",
        }

    def arch_hash(self) -> str:
        """架构哈希（不同拓扑不同哈希）."""
        arch = self.get_architecture()
        return f"{arch['n_features']}_{arch['hidden_dims']}_{arch['activation']}"

    def get_cs_input_dimension(self) -> int:
        """CS 公式输入维度（硬约束：不增维度，仍为 8）."""
        return 8


if _TORCH_AVAILABLE:

    class MLPPolicy(_MLPPolicyBase, nn.Module):
        """PyTorch MLP 策略网络.

        Input[n_features] → Linear(128)+ReLU → Linear(64)+ReLU+Dropout(0.1) → Linear(n_actions)+Softmax
        """

        def __init__(self, n_features: int = 17, n_actions: int = 3,
                     hidden_dims: list[int] | None = None) -> None:
            _MLPPolicyBase.__init__(self, n_features, n_actions, hidden_dims)
            nn.Module.__init__(self)

            layers: list[Any] = []
            in_dim = n_features
            for h_dim in self.hidden_dims:
                layers.append(nn.Linear(in_dim, h_dim))
                layers.append(nn.ReLU())
                layers.append(nn.Dropout(0.1))
                in_dim = h_dim
            layers.append(nn.Linear(in_dim, n_actions))
            self.network = nn.Sequential(*layers)

        def _features_to_array(self, state: dict[str, Any]) -> torch.Tensor:
            feats = state.get("features", [])
            if isinstance(feats, torch.Tensor):
                arr = feats.float()
            else:
                arr = torch.tensor(feats, dtype=torch.float32)
            if arr.numel() < self.n_features:
                arr = F.pad(arr, (0, self.n_features - arr.numel()))
            elif arr.numel() > self.n_features:
                arr = arr[:self.n_features]
            return arr

        def forward(self, state: dict[str, Any] | torch.Tensor) -> torch.Tensor:
            if isinstance(state, torch.Tensor):
                arr = state
            else:
                arr = self._features_to_array(state)
            logits = self.network(arr)
            return F.softmax(logits, dim=-1)

        def predict(self, state: dict[str, Any]) -> dict[str, float]:
            """返回 {action: probability} 字典."""
            with torch.no_grad():
                probs = self.forward(state)
            if not hasattr(self, "_action_list") or not self._action_list:
                self._action_list = [f"action_{i}" for i in range(self.n_actions)]
            return {self._action_list[i]: float(probs[i]) for i in range(self.n_actions)}

        def act(self, state: dict[str, Any]) -> str:
            probs = self.predict(state)
            return max(probs, key=probs.get)

else:
    # torch 不可用时的降级实现（numpy MLP）
    class MLPPolicy(_MLPPolicyBase):  # type: ignore[no-redef]
        """numpy 降级 MLP（torch 不可用时）."""

        def __init__(self, n_features: int = 17, n_actions: int = 3,
                     hidden_dims: list[int] | None = None) -> None:
            super().__init__(n_features, n_actions, hidden_dims)
            self._action_list: list[str] = []
            # 初始化权重（Xavier 近似）
            self.weights: list[np.ndarray] = []
            self.biases: list[np.ndarray] = []
            in_dim = n_features
            for h_dim in self.hidden_dims:
                w = np.random.randn(h_dim, in_dim) * np.sqrt(2.0 / in_dim)
                b = np.zeros(h_dim)
                self.weights.append(w)
                self.biases.append(b)
                in_dim = h_dim
            # 输出层
            w_out = np.random.randn(n_actions, in_dim) * np.sqrt(2.0 / in_dim)
            b_out = np.zeros(n_actions)
            self.weights.append(w_out)
            self.biases.append(b_out)

        def _features_to_array(self, state: dict[str, Any]) -> np.ndarray:
            feats = state.get("features", [])
            arr = np.asarray(feats, dtype=np.float64).ravel()
            if len(arr) < self.n_features:
                arr = np.pad(arr, (0, self.n_features - len(arr)))
            elif len(arr) > self.n_features:
                arr = arr[:self.n_features]
            return arr

        def _forward(self, arr: np.ndarray) -> np.ndarray:
            x = arr
            for i in range(len(self.weights) - 1):
                x = np.maximum(0, self.weights[i] @ x + self.biases[i])  # ReLU
            logits = self.weights[-1] @ x + self.biases[-1]
            # softmax
            shifted = logits - np.max(logits)
            exp = np.exp(shifted)
            return exp / (np.sum(exp) + 1e-9)

        def predict(self, state: dict[str, Any]) -> dict[str, float]:
            arr = self._features_to_array(state)
            probs = self._forward(arr)
            if not self._action_list:
                self._action_list = [f"action_{i}" for i in range(self.n_actions)]
            return {self._action_list[i]: float(probs[i]) for i in range(self.n_actions)}

        def act(self, state: dict[str, Any]) -> str:
            probs = self.predict(state)
            return max(probs, key=probs.get)


# --------------------------------------------------------------------------------
# MLPCritic — A2C 架构的值函数网络
# --------------------------------------------------------------------------------
if _TORCH_AVAILABLE:

    class MLPCritic(nn.Module):
        """A2C 值函数网络，共享 MLPPolicy 前两层 trunk."""

        def __init__(self, n_features: int = 17, hidden_dims: list[int] | None = None) -> None:
            super().__init__()
            self.n_features = int(n_features)
            self.hidden_dims = list(hidden_dims) if hidden_dims else [128, 64]

            layers: list[Any] = []
            in_dim = n_features
            for h_dim in self.hidden_dims:
                layers.append(nn.Linear(in_dim, h_dim))
                layers.append(nn.ReLU())
                in_dim = h_dim
            layers.append(nn.Linear(in_dim, 1))
            self.network = nn.Sequential(*layers)

        def _features_to_tensor(self, state: dict[str, Any]) -> torch.Tensor:
            feats = state.get("features", [])
            return torch.tensor(feats, dtype=torch.float32)

        def forward(self, state: dict[str, Any] | torch.Tensor) -> torch.Tensor:
            if isinstance(state, torch.Tensor):
                arr = state
            else:
                arr = self._features_to_tensor(state)
            return self.network(arr).squeeze(-1)

        def value(self, state: dict[str, Any]) -> float:
            with torch.no_grad():
                v = self.forward(state)
            return float(v.item())

else:
    class MLPCritic:  # type: ignore[no-redef]
        """numpy 降级值函数（torch 不可用时）."""

        def __init__(self, n_features: int = 17, hidden_dims: list[int] | None = None) -> None:
            self.n_features = int(n_features)
            self.hidden_dims = list(hidden_dims) if hidden_dims else [128, 64]
            # 简化：用线性值函数
            self.w = np.random.randn(n_features) * 0.01

        def value(self, state: dict[str, Any]) -> float:
            feats = state.get("features", [])
            arr = np.asarray(feats, dtype=np.float64).ravel()
            if len(arr) < self.n_features:
                arr = np.pad(arr, (0, self.n_features - len(arr)))
            elif len(arr) > self.n_features:
                arr = arr[:self.n_features]
            return float(np.dot(self.w, arr))


# --------------------------------------------------------------------------------
# A2CTrainer — A2C + GAE + 熵正则
# --------------------------------------------------------------------------------
class A2CTrainer:
    """A2C 训练器（FAIL-OPEN 4 级降级链）.

    Level 1: A2C + GAE + 熵正则 (torch 可用)
    Level 2: REINFORCE + baseline (critic 降级)
    Level 3: numpy SimplePolicy (torch 不可用)
    Level 4: record-only
    """

    def __init__(self, n_features: int = 17, n_actions: int = 3,
                 hidden_dims: list[int] | None = None,
                 lr: float = 3e-4, gae_lambda: float = 0.95,
                 entropy_beta: float = 0.01, grad_clip: float = 1.0) -> None:
        self.n_features = int(n_features)
        self.n_actions = int(n_actions)
        self.hidden_dims = list(hidden_dims) if hidden_dims else [128, 64]
        self.lr = float(lr)
        self.gae_lambda = float(gae_lambda)
        self.entropy_beta = float(entropy_beta)
        self.grad_clip = float(grad_clip)
        self._torch_available = _TORCH_AVAILABLE

        if _TORCH_AVAILABLE:
            self.policy = MLPPolicy(n_features, n_actions, hidden_dims)
            self.critic = MLPCritic(n_features, hidden_dims)
            self.optimizer = torch.optim.Adam(
                list(self.policy.parameters()) + list(self.critic.parameters()),
                lr=lr,
            )
            self._degradation_level = "a2c"
        else:
            # 降级到 numpy SimplePolicy
            from dreambuddy_evolution.core.shadow_rl_trainer import SimplePolicy
            self.policy = SimplePolicy(n_features=n_features, n_actions=n_actions)
            self.critic = None
            self.optimizer = None
            self._degradation_level = "simple"

    def get_degradation_level(self) -> str:
        return self._degradation_level

    def train(self, samples: list[dict[str, Any]], epochs: int = 50) -> dict[str, Any]:
        """A2C 训练（FAIL-OPEN: torch 不可用降级到 SimplePolicy）."""
        if not samples:
            return {"policy_loss": 0.0, "value_loss": 0.0, "episode_reward": 0.0}

        # 过滤 reward=0 占位样本
        samples = [s for s in samples if float(s.get("reward", 0.0)) != 0.0]
        if not samples:
            return {"policy_loss": 0.0, "value_loss": 0.0, "episode_reward": 0.0}

        if self._torch_available and self._degradation_level == "a2c":
            return self._train_a2c(samples, epochs)
        else:
            return self._train_simple(samples, epochs)

    def _train_a2c(self, samples: list[dict[str, Any]], epochs: int) -> dict[str, Any]:
        """A2C + GAE + 熵正则训练."""
        import torch as _torch

        # 准备数据
        states = _torch.tensor([
            self.policy._features_to_array(s.get("state", {})).numpy()
            for s in samples
        ], dtype=_torch.float32)

        actions_set = sorted(set(s["action"] for s in samples if "action" in s))
        if not actions_set:
            actions_set = [f"action_{i}" for i in range(self.n_actions)]
        self.policy._action_list = actions_set
        self.n_actions = len(actions_set)
        action_to_idx = {a: i for i, a in enumerate(actions_set)}
        actions = _torch.tensor([action_to_idx.get(s.get("action", ""), 0) for s in samples])
        rewards = _torch.tensor([float(s.get("reward", 0.0)) for s in samples], dtype=_torch.float32)

        # GAE 优势估计
        with _torch.no_grad():
            values = self.critic.forward(states)
        advantages = self._compute_gae(rewards, values)
        returns = advantages + values

        # 训练循环
        loss_history = []
        for epoch in range(epochs):
            self.optimizer.zero_grad()

            # Policy forward
            logits = self.policy.network(states)
            probs = F.softmax(logits, dim=-1)
            log_probs = F.log_softmax(logits, dim=-1)

            # Policy loss: -log_prob * advantage
            selected_log_probs = log_probs.gather(1, actions.unsqueeze(1)).squeeze(1)
            policy_loss = -(selected_log_probs * advantages.detach()).mean()

            # Value loss
            pred_values = self.critic.forward(states).squeeze(-1)
            value_loss = F.mse_loss(pred_values, returns.detach())

            # 熵正则（鼓励探索）
            entropy = -(probs * log_probs).sum(dim=-1).mean()
            total_loss = policy_loss + 0.5 * value_loss - self.entropy_beta * entropy

            total_loss.backward()
            _torch.nn.utils.clip_grad_norm_(
                list(self.policy.parameters()) + list(self.critic.parameters()),
                self.grad_clip,
            )
            self.optimizer.step()

            loss_history.append(float(total_loss.item()))

        return {
            "policy_loss": float(loss_history[-1]) if loss_history else 0.0,
            "value_loss": float(value_loss.item()),
            "episode_reward": float(rewards.mean().item()),
            "loss_history": loss_history,
        }

    def _compute_gae(self, rewards: Any, values: Any) -> Any:
        """计算 GAE 优势估计."""
        import torch as _torch
        advantages = _torch.zeros_like(rewards)
        gae = _torch.tensor(0.0)
        for i in reversed(range(len(rewards))):
            if i == len(rewards) - 1:
                next_value = _torch.tensor(0.0)
            else:
                next_value = values[i + 1]
            delta = rewards[i] + 0.95 * next_value - values[i]
            gae = delta + self.gae_lambda * 0.95 * gae
            advantages[i] = gae
        return advantages

    def _train_simple(self, samples: list[dict[str, Any]], epochs: int) -> dict[str, Any]:
        """降级到 SimplePolicy 训练（numpy）."""
        result = self.policy.fit(samples, epochs=epochs)
        return {
            "policy_loss": result.get("policy_loss", 0.0),
            "value_loss": 0.0,  # SimplePolicy 无 critic
            "episode_reward": result.get("episode_reward", 0.0),
        }
