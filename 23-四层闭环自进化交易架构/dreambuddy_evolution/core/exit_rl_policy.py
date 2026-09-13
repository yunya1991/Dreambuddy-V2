"""RL 离场策略层 — CQL 预训练 + Shielded 推理 + PPO 微调

三阶段渐进式引入 RL：
  阶段1: CQLTrainer — 离线训练 Q 函数（从 ShadowRL (s,a,R,s') 样本）
  阶段2: ShieldedPolicy — CQL 推理 + EvolutionExitEngine shield
  阶段3: PPOFineTuner — 在线 clip 更新（从 CQL 初始化）

MDP 建模：
  State (8维): [upl_ratio, position_age_min, atr_pct, RSI, ESS, CS, vol_ratio, tier_index]
  Action (5个): {0:hold, 1:adjust_sl_tp, 2:trailing, 3:force_close, 4:partial_close}
  Reward: ExitRewardCalculator.calculate() 的 R_total
  Transition: 下一轮巡检时的状态

FAIL-OPEN: 任何异常 → 返回 hold，不阻塞主链路。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# 动作枚举
ACTION_NAMES = ["hold", "adjust_sl_tp", "trailing", "force_close", "partial_close"]
ACTION_TO_IDX = {name: i for i, name in enumerate(ACTION_NAMES)}


# ----------------------------------------------------------------------------
# 状态归一化（训练和推理共用，确保 Q 网络输入尺度一致）
# ----------------------------------------------------------------------------
# State (8维): [upl_ratio, position_age_min, atr_pct, RSI, ESS, CS, vol_ratio, tier_index]
# 归一化策略：每维 clip 到合理范围后线性映射到 [0, 1] 或 [-1, 1]
STATE_CLIP_RANGES = [
    (-0.10, 0.40),    # 0: upl_ratio  [-10%, +40%]
    (0.0, 3000.0),    # 1: position_age_min  [0, 3000min=50h]
    (0.0, 0.05),      # 2: atr_pct  [0, 5%]
    (0.0, 100.0),     # 3: RSI  [0, 100]
    (0.0, 1.0),       # 4: ESS  [0, 1]
    (-1.0, 1.0),      # 5: CS  [-1, 1]
    (0.0, 3.0),       # 6: vol_ratio  [0, 3]
    (0.0, 2.0),       # 7: tier_index  [0, 2]
]


def normalize_state(state: np.ndarray) -> np.ndarray:
    """将原始状态向量归一化到 [0, 1] 范围

    训练和推理必须使用相同的归一化，确保 Q 网络输入尺度一致。
    """
    state = np.asarray(state, dtype=np.float32)
    norm = np.empty_like(state)
    for i, (lo, hi) in enumerate(STATE_CLIP_RANGES):
        val = float(state[i]) if i < len(state) else 0.0
        # clip 到 [lo, hi] 然后线性映射到 [0, 1]
        val = max(lo, min(hi, val))
        norm[i] = (val - lo) / (hi - lo) if hi > lo else 0.0
    return norm


# ============================================================================
# 阶段 1: CQL 预训练器
# ============================================================================


class CQLTrainer:
    """Conservative Q-Learning 离线预训练器

    CQL 在标准 Q-learning 基础上对 OOD 动作施加保守惩罚：
      L_CQL = L_TD + α × (logsumexp(Q(s,a')) - Q(s,a))
    特别适合低数据 regime（16→2000 笔交易）。
    """

    def __init__(
        self,
        state_dim: int = 8,
        n_actions: int = 5,
        lr: float = 1e-4,
        cql_alpha: float = 0.1,
        gamma: float = 0.99,
        hidden_dim: int = 64,
        device: str = "cpu",
        grad_clip: float = 1.0,
    ):
        self.state_dim = state_dim
        self.n_actions = n_actions
        self.cql_alpha = cql_alpha
        self.gamma = gamma
        self.device = device
        self.grad_clip = grad_clip

        # 延迟导入 torch（允许无 torch 时模块仍可加载）
        try:
            import torch
            import torch.nn as nn
            import torch.optim as optim
            self._torch = torch
            self._nn = nn
            self._optim = optim

            # Q 网络: state_dim → hidden → hidden → n_actions
            self.q_net = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, n_actions),
            ).to(device)
            # 双网络架构：target Q 用于稳定训练
            self.target_q_net = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, n_actions),
            ).to(device)
            self.target_q_net.load_state_dict(self.q_net.state_dict())
            self.target_q_net.eval()
            self._target_update_freq = 10
            self._train_steps = 0

            self.optimizer = optim.Adam(self.q_net.parameters(), lr=lr)
            self._available = True
        except ImportError:
            self._torch = None
            self._nn = None
            self._available = False
            logger.warning("torch not available, CQLTrainer will use numpy fallback")

    def predict_q(self, state: np.ndarray) -> np.ndarray:
        """Q 网络前向传播：state → Q[5]

        自动归一化原始状态向量。
        """
        if not self._available:
            # numpy 兜底：返回均匀 Q 值
            return np.zeros(self.n_actions, dtype=np.float32)

        # 归一化状态
        norm_state = normalize_state(state)
        t = self._torch
        with t.no_grad():
            state_t = t.FloatTensor(norm_state).to(self.device)
            if state_t.dim() == 1:
                state_t = state_t.unsqueeze(0)
            q = self.q_net(state_t).squeeze(0)
        return q.cpu().numpy()

    def train_batch(self, batch: List[Dict[str, Any]]) -> float:
        """CQL 训练一个 batch

        Args:
            batch: [{state, action, reward, next_state, done}, ...]
                  state/next_state 为原始尺度，内部自动归一化

        Returns:
            loss 值
        """
        if not self._available or len(batch) == 0:
            return 0.0

        t = self._torch
        nn = self._nn

        # 归一化状态 + clip 奖励到 [-1, 1]
        states = t.FloatTensor(
            np.array([normalize_state(b["state"]) for b in batch])
        ).to(self.device)
        actions = t.LongTensor([b["action"] for b in batch]).to(self.device)
        rewards = t.FloatTensor(
            [max(-1.0, min(1.0, float(b["reward"]))) for b in batch]
        ).to(self.device)
        next_states = t.FloatTensor(
            np.array([normalize_state(b["next_state"]) for b in batch])
        ).to(self.device)
        dones = t.FloatTensor([float(b.get("done", False)) for b in batch]).to(self.device)

        # 当前 Q(s,a)
        q_values = self.q_net(states)  # (B, n_actions)
        q_a = q_values.gather(1, actions.unsqueeze(1)).squeeze(1)  # (B,)

        # 目标 Q（使用 target network 稳定训练）
        with t.no_grad():
            next_q = self.target_q_net(next_states)  # (B, n_actions)
            next_q_max = next_q.max(dim=1)[0]  # (B,)
            target = rewards + self.gamma * (1 - dones) * next_q_max

        # TD loss
        td_loss = nn.functional.mse_loss(q_a, target)

        # CQL 保守惩罚: α × (logsumexp(Q(s,a')) - Q(s,a))
        logsumexp_q = t.logsumexp(q_values, dim=1)  # (B,)
        cql_penalty = self.cql_alpha * (logsumexp_q - q_a).mean()

        # 总损失
        loss = td_loss + cql_penalty

        self.optimizer.zero_grad()
        loss.backward()
        # 梯度裁剪防止爆炸
        nn.utils.clip_grad_norm_(self.q_net.parameters(), self.grad_clip)
        self.optimizer.step()

        # 定期更新 target network
        self._train_steps += 1
        if self._train_steps % self._target_update_freq == 0:
            self.target_q_net.load_state_dict(self.q_net.state_dict())

        return float(loss.item())

    def save(self, path: str) -> None:
        """保存 Q 网络参数"""
        if not self._available:
            return
        self._torch.save({
            "q_net_state_dict": self.q_net.state_dict(),
            "target_q_net_state_dict": self.target_q_net.state_dict(),
            "state_dim": self.state_dim,
            "n_actions": self.n_actions,
            "cql_alpha": self.cql_alpha,
            "grad_clip": self.grad_clip,
        }, path)

    def load(self, path: str) -> None:
        """加载 Q 网络参数"""
        if not self._available:
            return
        ckpt = self._torch.load(path, map_location=self.device, weights_only=False)
        self.q_net.load_state_dict(ckpt["q_net_state_dict"])
        # 兼容旧格式（无 target_q_net）
        if "target_q_net_state_dict" in ckpt:
            self.target_q_net.load_state_dict(ckpt["target_q_net_state_dict"])
        else:
            self.target_q_net.load_state_dict(self.q_net.state_dict())
        self.q_net.eval()


# ============================================================================
# 阶段 2: Shielded 推理器
# ============================================================================


class ShieldedPolicy:
    """CQL 策略 + EvolutionExitEngine shield

    CQL policy 建议动作 → shield 检查安全性 → 安全则执行，不安全则降级
    """

    # shield 安全边界规则
    SHIELD_RULES = {
        # RL 建议 force_close 但盈利 >5% → 降级为 trailing
        "force_close_profit_block": 0.05,
        # RL 建议 hold 但亏损超时 → 升级为 force_close
        "hold_loss_timeout_sec": 29 * 3600,
        "hold_loss_upl_threshold": -0.02,
    }

    def __init__(
        self,
        cql_trainer: Optional[CQLTrainer],
        exit_engine: Any = None,  # EvolutionExitEngine 实例
        log_fn: Optional[Callable[[str, str], None]] = None,
        min_confidence: float = 0.3,
    ):
        """
        Args:
            cql_trainer: CQL 预训练器（None 时 FAIL-OPEN）
            exit_engine: EvolutionExitEngine 实例（shield 层）
            log_fn: 日志回调
            min_confidence: RL 动作置信度低于此值时退化为规则
        """
        self.cql_trainer = cql_trainer
        self.exit_engine = exit_engine
        self._log_fn = log_fn or (lambda msg, level="INFO": None)
        self.min_confidence = min_confidence

    def _log(self, msg: str, level: str = "INFO") -> None:
        try:
            self._log_fn(msg, level)
        except Exception:
            pass

    def act(self, state: np.ndarray) -> Tuple[str, Dict[str, Any]]:
        """无 shield 的纯 RL 推理（FAIL-OPEN）"""
        try:
            if self.cql_trainer is None:
                return "hold", {"reason": "evolution_rl:hold:fail_open:no_trainer"}

            q_values = self.cql_trainer.predict_q(state)
            action_idx = int(np.argmax(q_values))

            # ★ FIX: confidence 用 softmax(Q/T) 归一化为 [0,1] 概率
            #   原始 Q 值范围不固定（如 24~29），直接作阈值毫无意义。
            #   softmax 将 Q 值转为动作概率分布，max(prob) ∈ (0,1]，
            #   min_confidence=0.3 阈值才有意义。
            #   T=1.0 为温度参数，值越大分布越平滑。
            q_arr = np.asarray(q_values, dtype=np.float64)
            q_max = float(np.max(q_arr))
            exp_q = np.exp(q_arr - q_max)  # 减最大值防数值溢出
            probs = exp_q / float(np.sum(exp_q))
            confidence = float(probs[action_idx])

            if confidence < self.min_confidence:
                return "hold", {
                    "reason": f"evolution_rl:hold:low_confidence_{confidence:.3f}",
                    "q_values": q_values.tolist(),
                    "confidence": confidence,
                }

            action = ACTION_NAMES[action_idx]
            return action, {
                "q_values": q_values.tolist(),
                "confidence": confidence,
                "reason": f"evolution_rl:{action}:rl_policy",
            }
        except Exception as exc:
            self._log(f"[ShieldedPolicy] act crash (FAIL-OPEN): {exc}", "WARN")
            return "hold", {"reason": f"evolution_rl:hold:fail_open:{type(exc).__name__}"}

    def act_with_shield(
        self, state: np.ndarray, context: Dict[str, Any]
    ) -> Tuple[str, Dict[str, Any]]:
        """带 shield 的 RL 推理

        Args:
            state: 8 维状态向量
            context: 离场决策上下文（symbol/pos_side/upl_ratio 等）

        Returns:
            (action, params)
        """
        try:
            # Step 1: RL 建议动作
            rl_action, rl_params = self.act(state)

            # Step 2: shield 检查
            shielded_action = self._apply_shield(rl_action, context)

            if shielded_action != rl_action:
                self._log(
                    f"[ShieldedPolicy] shield 降级: {rl_action} → {shielded_action} "
                    f"(upl={context.get('upl_ratio', 0):.2%})",
                    "INFO",
                )
                return shielded_action, {
                    **rl_params,
                    "original_action": rl_action,
                    "shielded": True,
                    "reason": f"evolution_rl:{shielded_action}:shielded_from_{rl_action}",
                }

            return rl_action, {**rl_params, "shielded": False}

        except Exception as exc:
            self._log(f"[ShieldedPolicy] act_with_shield crash (FAIL-OPEN): {exc}", "WARN")
            return "hold", {"reason": f"evolution_rl:hold:fail_open:{type(exc).__name__}"}

    def _apply_shield(self, rl_action: str, ctx: Dict[str, Any]) -> str:
        """shield 规则检查

        规则：
        1. RL 建议 force_close 但盈利 >5% → 降级为 trailing
        2. RL 建议 hold 但亏损超时（>29h 且 upl<-2%）→ 升级为 force_close
        3. 任何 RL 动作但 entry_price<=0 → 强制 hold
        """
        upl_ratio = float(ctx.get("upl_ratio", 0.0) or 0.0)
        position_age_sec = float(ctx.get("position_age_sec", 0.0) or 0.0)
        entry_price = float(ctx.get("entry_price", 0.0) or 0.0)

        # 规则 3: entry_price 无效 → hold
        if entry_price <= 0:
            return "hold"

        # 规则 1: force_close 在盈利时 → trailing
        if rl_action == "force_close" and upl_ratio > self.SHIELD_RULES["force_close_profit_block"]:
            return "trailing"

        # 规则 2: hold 在亏损超时时 → force_close
        if rl_action == "hold":
            timeout_sec = self.SHIELD_RULES["hold_loss_timeout_sec"]
            loss_threshold = self.SHIELD_RULES["hold_loss_upl_threshold"]
            if position_age_sec > timeout_sec and upl_ratio < loss_threshold:
                return "force_close"

        # 安全动作
        return rl_action


# ============================================================================
# 阶段 3: PPO 微调器
# ============================================================================


class PPOFineTuner:
    """PPO 在线微调器

    从 CQL 预训练初始化，用 PPO clip 目标在线更新。
    """

    def __init__(
        self,
        state_dim: int = 8,
        n_actions: int = 5,
        lr: float = 1e-4,
        clip_epsilon: float = 0.2,
        gamma: float = 0.99,
        hidden_dim: int = 64,
        device: str = "cpu",
    ):
        self.state_dim = state_dim
        self.n_actions = n_actions
        self.clip_epsilon = clip_epsilon
        self.gamma = gamma
        self.device = device

        try:
            import torch
            import torch.nn as nn
            import torch.optim as optim
            self._torch = torch
            self._nn = nn
            self._optim = optim

            # Actor 网络: state → action probs (softmax)
            self.actor = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, n_actions),
            ).to(device)

            # Critic 网络: state → V(s)
            self.critic = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, 1),
            ).to(device)

            self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=lr)
            self.critic_optimizer = optim.Adam(self.critic.parameters(), lr=lr)
            self._available = True
        except ImportError:
            self._torch = None
            self._nn = None
            self._available = False
            logger.warning("torch not available, PPOFineTuner will use numpy fallback")

    def predict_probs(self, state: np.ndarray) -> np.ndarray:
        """Actor 前向传播：state → action probs (softmax)"""
        if not self._available:
            return np.ones(self.n_actions, dtype=np.float32) / self.n_actions

        t = self._torch
        with t.no_grad():
            state_t = t.FloatTensor(state).to(self.device)
            if state_t.dim() == 1:
                state_t = state_t.unsqueeze(0)
            logits = self.actor(state_t).squeeze(0)
            probs = t.softmax(logits, dim=0)
        return probs.cpu().numpy()

    def update(self, batch: List[Dict[str, Any]]) -> float:
        """PPO 在一个 batch 上更新

        Args:
            batch: [{state, action, reward, old_prob, advantage}, ...]

        Returns:
            total loss
        """
        if not self._available or len(batch) == 0:
            return 0.0

        t = self._torch
        nn = self._nn

        states = t.FloatTensor(np.array([b["state"] for b in batch])).to(self.device)
        actions = t.LongTensor([b["action"] for b in batch]).to(self.device)
        rewards = t.FloatTensor([b["reward"] for b in batch]).to(self.device)
        old_probs = t.FloatTensor([b["old_prob"] for b in batch]).to(self.device)
        advantages = t.FloatTensor([b["advantage"] for b in batch]).to(self.device)

        # Actor loss (PPO clip)
        logits = self.actor(states)
        new_probs = nn.functional.softmax(logits, dim=1)
        new_prob_a = new_probs.gather(1, actions.unsqueeze(1)).squeeze(1)

        ratio = new_prob_a / (old_probs + 1e-8)
        clipped_ratio = t.clamp(ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon)
        actor_loss = -t.min(ratio * advantages, clipped_ratio * advantages).mean()

        # Critic loss
        values = self.critic(states).squeeze(1)
        critic_loss = nn.functional.mse_loss(values, rewards)

        # 总损失
        loss = actor_loss + 0.5 * critic_loss

        self.actor_optimizer.zero_grad()
        self.critic_optimizer.zero_grad()
        loss.backward()
        # 梯度裁剪
        nn.utils.clip_grad_norm_(self.actor.parameters(), 0.5)
        nn.utils.clip_grad_norm_(self.critic.parameters(), 0.5)
        self.actor_optimizer.step()
        self.critic_optimizer.step()

        return float(loss.item())

    def init_from_cql(self, cql_trainer: CQLTrainer) -> None:
        """从 CQL 预训练模型初始化 PPO actor

        将 CQL Q 值转换为动作概率（softmax(Q/T)），初始化 actor 最后一层。
        """
        if not self._available or not cql_trainer._available:
            return

        t = self._torch
        nn = self._nn

        with t.no_grad():
            # 用 CQL Q 网络的最后一层初始化 actor 的最后一层
            # Q 值 → logits → softmax → 概率
            cql_last_layer = cql_trainer.q_net[-1]  # Linear(hidden_dim, n_actions)
            actor_last_layer = self.actor[-1]  # Linear(hidden_dim, n_actions)

            if cql_last_layer.weight.shape == actor_last_layer.weight.shape:
                actor_last_layer.weight.copy_(cql_last_layer.weight)
                actor_last_layer.bias.copy_(cql_last_layer.bias)

    def save(self, path: str) -> None:
        """保存 PPO 模型"""
        if not self._available:
            return
        self._torch.save({
            "actor_state_dict": self.actor.state_dict(),
            "critic_state_dict": self.critic.state_dict(),
            "state_dim": self.state_dim,
            "n_actions": self.n_actions,
            "clip_epsilon": self.clip_epsilon,
        }, path)

    def load(self, path: str) -> None:
        """加载 PPO 模型"""
        if not self._available:
            return
        ckpt = self._torch.load(path, map_location=self.device, weights_only=False)
        self.actor.load_state_dict(ckpt["actor_state_dict"])
        self.critic.load_state_dict(ckpt["critic_state_dict"])
        self.actor.eval()
        self.critic.eval()
