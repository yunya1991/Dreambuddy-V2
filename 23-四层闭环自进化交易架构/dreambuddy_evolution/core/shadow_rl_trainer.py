"""
Phase 1: Shadow RL Phase3 训练器
SPEC-AGI升级蓝图.md §4.1.1

核心能力：
  - 样本≥2000自动激活（HC-AGI-01，非PR评审）
  - gmax变异：策略基因权重±0.01~0.05随机扰动
  - Thompson sampling：Beta(α=success+1, β=fail+1) 采样策略选择
  - V(s)回流：Bellman V值影响L1状态空间权重
  - 内置 Policy Gradient 训练（REINFORCE + baseline，纯 numpy）
  - FAIL-OPEN：finrl未安装时降级为内置简化训练，不crash

蓝本: FinRL (16.3k★) 三层解耦 + ElegantRL (4.4k★) 并行训练
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 finrl（可选依赖，FAIL-OPEN）
try:
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv  # type: ignore
    _FINRL_AVAILABLE = True
except Exception:  # noqa: BLE001
    _FINRL_AVAILABLE = False
    logger.debug("[FO-AGI-01] finrl 不可用，ShadowRLTrainer 降级为 record-only")


class SimplePolicy:
    """简化版 softmax 策略（REINFORCE policy gradient）.

    state features → linear → softmax → action probabilities.
    纯 numpy 实现，不依赖 PyTorch/TensorFlow.
    """

    def __init__(self, n_features: int = 5, n_actions: int = 3, lr: float = 0.01):
        self.n_features = n_features
        self.n_actions = n_actions
        self.lr = lr
        # 权重矩阵: [n_actions, n_features]
        self.W = np.random.randn(n_actions, n_features) * 0.01
        self.b = np.zeros(n_actions)
        self._action_list: list[str] = []
        self._fitted = False

    def _features_to_array(self, state: dict[str, Any]) -> np.ndarray:
        feats = state.get("features", [])
        if isinstance(feats, list):
            arr = np.array(feats, dtype=np.float64)
        else:
            arr = np.array(feats, dtype=np.float64).flatten()
        if len(arr) < self.n_features:
            arr = np.pad(arr, (0, self.n_features - len(arr)))
        elif len(arr) > self.n_features:
            arr = arr[:self.n_features]
        return arr

    def _logits(self, state_arr: np.ndarray) -> np.ndarray:
        return self.W @ state_arr + self.b

    def _softmax(self, logits: np.ndarray) -> np.ndarray:
        shifted = logits - np.max(logits)
        exp = np.exp(shifted)
        return exp / (np.sum(exp) + 1e-9)

    def predict(self, state: dict[str, Any]) -> dict[str, float]:
        """返回 {action: probability} 字典."""
        arr = self._features_to_array(state)
        probs = self._softmax(self._logits(arr))
        if not self._action_list:
            self._action_list = [f"action_{i}" for i in range(self.n_actions)]
        return {self._action_list[i]: float(probs[i]) for i in range(self.n_actions)}

    def act(self, state: dict[str, Any]) -> str:
        """返回概率最大的动作."""
        probs = self.predict(state)
        return max(probs, key=probs.get)

    def fit(self, samples: list[dict[str, Any]], epochs: int = 50) -> dict[str, Any]:
        """REINFORCE + baseline 策略梯度训练.

        Returns: {"policy_loss": final_loss, "episode_reward": avg_reward,
                  "loss_history": [loss_per_epoch]}
        """
        if not samples:
            return {"policy_loss": 0.0, "episode_reward": 0.0, "loss_history": []}

        # C方案双保险: 过滤 reward=0 占位样本，防 baseline 被污染导致 advantage 信号衰减
        samples = [s for s in samples if float(s.get("reward", 0.0)) != 0.0]
        if not samples:
            return {"policy_loss": 0.0, "episode_reward": 0.0, "loss_history": []}

        # 自动发现 action 空间
        actions_set = sorted(set(s["action"] for s in samples if "action" in s))
        self._action_list = actions_set if actions_set else [f"action_{i}" for i in range(self.n_actions)]
        self.n_actions = len(self._action_list)
        action_to_idx = {a: i for i, a in enumerate(self._action_list)}

        # 调整权重矩阵维度
        n_feat = self.n_features
        self.W = np.random.randn(self.n_actions, n_feat) * 0.01
        self.b = np.zeros(self.n_actions)

        # 准备训练数据
        states_arr = np.array([self._features_to_array(s.get("state", {})) for s in samples])
        actions_idx = np.array([action_to_idx.get(s.get("action", ""), 0) for s in samples])
        rewards = np.array([float(s.get("reward", 0.0)) for s in samples])

        # Baseline: 滑动平均回报
        baseline = np.mean(rewards)

        loss_history = []
        for epoch in range(epochs):
            total_loss = 0.0
            for i in range(len(samples)):
                arr = states_arr[i]
                logits = self._logits(arr)
                probs = self._softmax(logits)
                action_idx = actions_idx[i]
                prob = max(probs[action_idx], 1e-8)
                # Policy gradient: -log(pi(a|s)) * (R - baseline)
                advantage = rewards[i] - baseline
                grad_log = -advantage / prob
                # Softmax Jacobian: dsoftmax/dlogits
                grad_logits = -probs.copy()
                grad_logits[action_idx] += 1.0
                grad_logits *= grad_log
                # 参数梯度
                grad_W = np.outer(grad_logits, arr)
                grad_b = grad_logits
                # 参数更新
                self.W -= self.lr * grad_W
                self.b -= self.lr * grad_b
                # Loss = -log_prob * advantage
                total_loss += -np.log(prob) * advantage
            avg_loss = total_loss / max(len(samples), 1)
            loss_history.append(float(avg_loss))

        self._fitted = True
        return {
            "policy_loss": float(loss_history[-1]) if loss_history else 0.0,
            "episode_reward": float(np.mean(rewards)),
            "loss_history": loss_history,
        }


class ShadowRLTrainer:
    """Shadow RL Phase3 训练器.

    Phase 3: 样本≥2000自动激活，启动 gmax 变异 + Thompson sampling.
    """

    MIN_SAMPLES = 2000  # HC-AGI-01: 自动激活阈值
    GMAX_MUTATION_LOW = 0.01
    GMAX_MUTATION_HIGH = 0.05
    # 内置训练默认参数
    DEFAULT_EPOCHS = 50
    DEFAULT_LR = 0.01
    DEFAULT_N_FEATURES = 5

    def __init__(self) -> None:
        self._activated: bool = False
        self._finrl_available: bool = _FINRL_AVAILABLE
        # Beta分布参数: gene_id -> {"alpha": int, "beta": int}
        # α = successes + 1, β = failures + 1 (pseudocount=1 防零)
        self._beta_params: dict[str, dict[str, int]] = {}
        # 训练后的策略缓存: gene_id -> SimplePolicy
        self._trained_policies: dict[str, SimplePolicy] = {}

    # ------------------------------------------------------------------
    # 激活
    # ------------------------------------------------------------------
    def maybe_activate(self, sample_count: int) -> bool:
        """样本≥MIN_SAMPLES时自动激活（非PR评审）."""
        if sample_count >= self.MIN_SAMPLES:
            self._activated = True
            return True
        return False

    def is_activated(self) -> bool:
        return self._activated

    # ------------------------------------------------------------------
    # gmax 变异 (Schluter 风格)
    # ------------------------------------------------------------------
    def mutate_gmax(self, current_gmax: float) -> float:
        """策略基因权重±0.01~0.05随机扰动，结果clamp到[0,1].

        变异幅度 = uniform(0.01, 0.05)，方向 = random sign.
        """
        magnitude = float(np.random.uniform(self.GMAX_MUTATION_LOW, self.GMAX_MUTATION_HIGH))
        direction = 1.0 if np.random.rand() >= 0.5 else -1.0
        mutated = float(current_gmax) + direction * magnitude
        return max(0.0, min(1.0, mutated))

    # ------------------------------------------------------------------
    # Thompson Sampling
    # ------------------------------------------------------------------
    def thompson_sample(self, gene_id: str, successes: int, failures: int) -> float:
        """从 Beta(α=successes+1, β=failures+1) 采样.

        返回 [0,1] 浮点数，表示该基因的估计成功率.
        """
        alpha = max(1, int(successes) + 1)
        beta = max(1, int(failures) + 1)
        # numpy 提供 beta 采样，无需 scipy
        sample = float(np.random.beta(alpha, beta))
        return max(0.0, min(1.0, sample))

    def select_best_gene(self, genes: dict[str, tuple[int, int]]) -> str:
        """对每个基因做Thompson采样，返回采样值最大的gene_id.

        genes: {gene_id: (successes, failures)}
        """
        if not genes:
            raise ValueError("genes 不能为空")
        best_id = None
        best_score = -1.0
        for gid, (succ, fail) in genes.items():
            score = self.thompson_sample(gid, succ, fail)
            if score > best_score:
                best_score = score
                best_id = gid
        return str(best_id)

    # ------------------------------------------------------------------
    # Beta 参数在线更新
    # ------------------------------------------------------------------
    def update_beta(self, gene_id: str, success: bool) -> None:
        """根据交易结果更新基因的Beta分布参数."""
        stats = self._beta_params.setdefault(gene_id, {"alpha": 1, "beta": 1})
        if success:
            stats["alpha"] += 1
        else:
            stats["beta"] += 1

    def get_beta_stats(self, gene_id: str) -> dict[str, int]:
        """返回基因当前的Beta参数（未知基因返回默认 α=1, β=1）."""
        stats = self._beta_params.get(gene_id)
        if stats is None:
            return {"alpha": 1, "beta": 1}
        return {"alpha": int(stats["alpha"]), "beta": int(stats["beta"])}

    # ------------------------------------------------------------------
    # 策略训练 (内置 Policy Gradient + FinRL 可选扩展)
    # ------------------------------------------------------------------
    def train_policy(
        self,
        samples: list[dict[str, Any]],
        epochs: int | None = None,
        gene_id: str = "default",
    ) -> dict[str, Any]:
        """基于样本训练 RL 策略.

        内置 REINFORCE policy gradient（纯 numpy，不依赖 finrl）.
        FAIL-OPEN: 任何异常→降级返回，不抛异常.

        Args:
            samples: [{symbol, state, action, reward, next_state}, ...]
            epochs: 训练轮数（默认 DEFAULT_EPOCHS=50）
            gene_id: 基因ID，用于缓存策略和更新Beta参数

        Returns: {status, trained_policy, policy_loss, episode_reward,
                  loss_history, samples_seen}
        """
        if epochs is None:
            epochs = self.DEFAULT_EPOCHS

        # 空样本降级
        if not samples:
            return {
                "status": "degraded",
                "reason": "no samples; record-only mode",
                "samples_seen": 0,
            }

        try:
            # 内置 SimplePolicy 训练（REINFORCE + baseline）
            policy = SimplePolicy(
                n_features=self.DEFAULT_N_FEATURES,
                n_actions=3,  # 初始默认，fit 时自动调整
                lr=self.DEFAULT_LR,
            )
            train_result = policy.fit(samples, epochs=epochs)

            # 缓存训练后的策略
            self._trained_policies[gene_id] = policy

            # 更新 Beta 参数：reward > 0 → success, reward <= 0 → failure
            for s in samples:
                reward = float(s.get("reward", 0.0))
                self.update_beta(gene_id, success=reward > 0)

            return {
                "status": "trained",
                "trained_policy": policy,
                "policy_loss": train_result["policy_loss"],
                "episode_reward": train_result["episode_reward"],
                "loss_history": train_result["loss_history"],
                "samples_seen": len(samples),
                "gene_id": gene_id,
                "finrl_used": False,  # 内置训练，未用 finrl
            }
        except Exception as e:
            # FAIL-OPEN: 训练异常→降级返回
            logger.warning(f"[FO-AGI-01] train_policy 异常: {e}")
            return {
                "status": "degraded",
                "reason": f"training error: {e}",
                "samples_seen": len(samples),
            }

    def get_trained_policy(self, gene_id: str = "default") -> SimplePolicy | None:
        """获取已训练的策略（未训练返回 None）."""
        return self._trained_policies.get(gene_id)
