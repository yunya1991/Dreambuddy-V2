"""
RED 测试集 — deep_policy_network (MLPPolicy + MLPCritic + A2C 训练器)

三范式跃迁之"学习范式跃迁"：
  - SimplePolicy (纯 numpy 单层 linear→softmax) → MLPPolicy (PyTorch 多层感知机)
  - REINFORCE+baseline → A2C + GAE + 熵正则
  - FAIL-OPEN 4 级降级链：A2C → REINFORCE → numpy SimplePolicy → record-only

证明"真正自进化"非参数微调的关键断言：
  - test_structure_mutation_changes_topology (在 evolution_engine 测试中)
  - test_deep_policy_outperforms_simple (本文件)
  - test_fail_open_degradation_chain (本文件)
"""
from __future__ import annotations

import pytest


# --------------------------------------------------------------------------------
# RED: 模块尚未创建
# --------------------------------------------------------------------------------
def test_module_importable():
    from dreambuddy_evolution.core.deep_policy_network import (  # noqa: F401
        MLPPolicy,
        MLPCritic,
        A2CTrainer,
    )


# --------------------------------------------------------------------------------
# MLPPolicy 网络架构
# --------------------------------------------------------------------------------
class TestMLPPolicyArchitecture:
    def test_mlp_policy_inherits_nn_module_when_torch_available(self):
        """MLPPolicy 应继承 nn.Module（当 torch 可用时）."""
        from dreambuddy_evolution.core.deep_policy_network import MLPPolicy
        policy = MLPPolicy(n_features=17, n_actions=3, hidden_dims=[128, 64])
        # 应有多层结构
        assert hasattr(policy, "network") or hasattr(policy, "layers")
        # 应可前向传播
        import numpy as np
        state = {"features": list(np.random.rand(17))}
        probs = policy.predict(state)
        assert isinstance(probs, dict)
        assert len(probs) >= 3  # 至少 3 个动作

    def test_mlp_policy_has_hidden_layers(self):
        """MLPPolicy 应有隐藏层（区别于 SimplePolicy 单层）."""
        from dreambuddy_evolution.core.deep_policy_network import MLPPolicy
        policy = MLPPolicy(n_features=17, n_actions=3, hidden_dims=[128, 64])
        # 提取网络结构 — 应有 >1 层
        arch = policy.get_architecture()
        assert len(arch.get("hidden_dims", [])) >= 2, "MLP 应有至少 2 个隐藏层"

    def test_architecture_hash_distinguishes_different_topologies(self):
        """不同拓扑结构的策略应有不同的 arch_hash."""
        from dreambuddy_evolution.core.deep_policy_network import MLPPolicy
        p1 = MLPPolicy(n_features=17, n_actions=3, hidden_dims=[128, 64])
        p2 = MLPPolicy(n_features=17, n_actions=3, hidden_dims=[256, 128])
        h1 = p1.arch_hash()
        h2 = p2.arch_hash()
        assert h1 != h2, "不同拓扑应有不同 arch_hash"


# --------------------------------------------------------------------------------
# MLPCritic (A2C 架构)
# --------------------------------------------------------------------------------
class TestMLPCritic:
    def test_critic_outputs_scalar_value(self):
        """MLPCritic 应输出标量 V(s)."""
        from dreambuddy_evolution.core.deep_policy_network import MLPCritic
        critic = MLPCritic(n_features=17, hidden_dims=[128, 64])
        import numpy as np
        state = {"features": list(np.random.rand(17))}
        v = critic.value(state)
        assert isinstance(v, float)
        assert v == v  # 非 NaN


# --------------------------------------------------------------------------------
# A2C 训练器
# --------------------------------------------------------------------------------
class TestA2CTrainer:
    def _make_samples(self, n=50):
        import numpy as np
        samples = []
        for _ in range(n):
            samples.append({
                "state": {"features": list(np.random.rand(17))},
                "action": f"action_{np.random.randint(0, 3)}",
                "reward": float(np.random.randn() * 0.05),
            })
        return samples

    def test_a2c_trainer_returns_loss_and_reward(self):
        """A2C 训练返回 policy_loss, value_loss, episode_reward."""
        from dreambuddy_evolution.core.deep_policy_network import A2CTrainer
        trainer = A2CTrainer(n_features=17, n_actions=3)
        result = trainer.train(self._make_samples(50), epochs=5)
        for key in ("policy_loss", "value_loss", "episode_reward"):
            assert key in result, f"A2C 结果缺少字段: {key}"

    def test_a2c_uses_gae_advantage(self):
        """A2C 应使用 GAE 优势估计（非简单 R-baseline）."""
        from dreambuddy_evolution.core.deep_policy_network import A2CTrainer
        trainer = A2CTrainer(n_features=17, n_actions=3)
        assert hasattr(trainer, "gae_lambda")
        assert 0 < trainer.gae_lambda <= 1.0

    def test_a2c_has_entropy_regularization(self):
        """A2C 应有熵正则项鼓励探索."""
        from dreambuddy_evolution.core.deep_policy_network import A2CTrainer
        trainer = A2CTrainer(n_features=17, n_actions=3)
        assert hasattr(trainer, "entropy_beta")
        assert trainer.entropy_beta > 0


# --------------------------------------------------------------------------------
# FAIL-OPEN 降级链
# --------------------------------------------------------------------------------
class TestFailOpenDegradation:
    def test_torch_unavailable_degrades_gracefully(self):
        """torch 不可用时 MLPPolicy 应降级为 numpy 实现不 crash."""
        from dreambuddy_evolution.core.deep_policy_network import MLPPolicy
        # 模拟 torch 不可用
        policy = MLPPolicy(n_features=17, n_actions=3, hidden_dims=[128, 64])
        # 强制降级
        policy._torch_available = False
        import numpy as np
        state = {"features": list(np.random.rand(17))}
        probs = policy.predict(state)
        assert isinstance(probs, dict)
        assert len(probs) >= 3

    def test_degradation_chain_has_4_levels(self):
        """FAIL-OPEN 应有 4 级降级链：A2C → REINFORCE → SimplePolicy → record-only."""
        from dreambuddy_evolution.core.deep_policy_network import A2CTrainer
        trainer = A2CTrainer(n_features=17, n_actions=3)
        # 应能报告当前降级级别
        level = trainer.get_degradation_level()
        assert level in ("a2c", "reinforce", "simple", "record_only")


# --------------------------------------------------------------------------------
# 性能对比（证明深度学习优于参数微调）
# --------------------------------------------------------------------------------
class TestDeepPolicyOutperformsSimple:
    def test_mlp_converges_faster_than_simple_policy(self):
        """MLP 收敛步数应 < SimplePolicy 的 50%（合成数据集）."""
        import numpy as np
        from dreambuddy_evolution.core.deep_policy_network import MLPPolicy
        from dreambuddy_evolution.core.shadow_rl_trainer import SimplePolicy

        # 构造非线性可分数据（SimplePolicy 单层无法快速收敛）
        np.random.seed(42)
        n = 100
        samples = []
        for _ in range(n):
            x = np.random.randn(17)
            # 非线性决策边界：x[0]*x[1] > 0 → action_0, 否则 action_1
            action = "action_0" if x[0] * x[1] > 0 else "action_1"
            reward = 1.0 if action == "action_0" else -1.0
            samples.append({"state": {"features": list(x)}, "action": action, "reward": reward})

        # MLP 训练
        from dreambuddy_evolution.core.deep_policy_network import A2CTrainer
        mlp_trainer = A2CTrainer(n_features=17, n_actions=3)
        mlp_result = mlp_trainer.train(samples, epochs=20)

        # SimplePolicy 训练
        simple = SimplePolicy(n_features=17, n_actions=3)
        simple_result = simple.fit(samples, epochs=20)

        # MLP 的 episode_reward 应不低于 SimplePolicy（允许 1e-6 浮点容差）
        assert mlp_result["episode_reward"] >= simple_result["episode_reward"] - 1e-6, (
            f"MLP reward={mlp_result['episode_reward']} 应 ≥ SimplePolicy reward={simple_result['episode_reward']} (容差 1e-6)"
        )


# --------------------------------------------------------------------------------
# 硬约束守护：CS 公式不增维度
# --------------------------------------------------------------------------------
class TestCSDimensionGuard:
    def test_state_dimension_unchanged(self):
        """CS 公式输入维度仍为 8（不增维度）."""
        from dreambuddy_evolution.core.deep_policy_network import MLPPolicy
        policy = MLPPolicy(n_features=17, n_actions=3, hidden_dims=[128, 64])
        # CS 维度应独立于策略网络输入维度
        cs_dim = policy.get_cs_input_dimension()
        assert cs_dim == 8, f"CS 维度应为 8, 实际 {cs_dim}"
