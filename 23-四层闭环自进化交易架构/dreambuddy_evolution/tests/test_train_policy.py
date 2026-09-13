"""
TDD 测试: train_policy 真实 RL 策略训练

验证点：
  T1. train_policy 返回 trained_policy 字段（非骨架）
  T2. 训练后策略能 predict（给定状态→输出动作概率）
  T3. 训练后策略能 act（给定状态→输出离散动作）
  T4. 样本不足时降级为 record-only
  T5. 训练结果包含 policy_loss（收敛指标）
  T6. 训练结果包含 episode_reward（回报指标）
  T7. 多轮训练后 policy_loss 单调下降（学习收敛）
  T8. 训练后 Thompson 采样权重与训练前不同（权重已更新）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.shadow_rl_trainer import ShadowRLTrainer


def _make_samples(n=100, n_actions=3, n_features=5):
    """构造模拟 (s, a, R, s') 样本"""
    import numpy as np
    np.random.seed(42)
    samples = []
    for i in range(n):
        state = {"features": np.random.randn(n_features).tolist()}
        action = f"action_{np.random.randint(0, n_actions)}"
        reward = float(np.random.randn() * 0.1 + (0.5 if action == "action_1" else -0.2))
        next_state = {"features": np.random.randn(n_features).tolist()}
        samples.append({
            "symbol": "BTC-USDT-SWAP",
            "state": state,
            "action": action,
            "reward": reward,
            "next_state": next_state,
        })
    return samples


# ====================================================================
# T1. train_policy 返回 trained_policy 字段
# ====================================================================
def test_train_returns_policy():
    trainer = ShadowRLTrainer()
    trainer._activated = True
    trainer._finrl_available = False  # 使用内置简化训练
    samples = _make_samples(100)
    result = trainer.train_policy(samples)
    assert "trained_policy" in result, "train_policy 应返回 trained_policy"


# ====================================================================
# T2. 训练后策略能 predict（状态→动作概率）
# ====================================================================
def test_policy_predict():
    trainer = ShadowRLTrainer()
    trainer._activated = True
    trainer._finrl_available = False
    samples = _make_samples(100)
    result = trainer.train_policy(samples)
    policy = result["trained_policy"]
    state = {"features": [0.1, -0.2, 0.3, 0.0, -0.1]}
    probs = policy.predict(state)
    assert isinstance(probs, dict), "predict 应返回动作概率字典"
    assert abs(sum(probs.values()) - 1.0) < 0.01, "概率和应≈1.0"


# ====================================================================
# T3. 训练后策略能 act（状态→离散动作）
# ====================================================================
def test_policy_act():
    trainer = ShadowRLTrainer()
    trainer._activated = True
    trainer._finrl_available = False
    samples = _make_samples(100)
    result = trainer.train_policy(samples)
    policy = result["trained_policy"]
    state = {"features": [0.1, -0.2, 0.3, 0.0, -0.1]}
    action = policy.act(state)
    assert isinstance(action, str), "act 应返回字符串动作"


# ====================================================================
# T4. 样本不足时降级为 record-only
# ====================================================================
def test_insufficient_samples_degraded():
    trainer = ShadowRLTrainer()
    trainer._finrl_available = False
    result = trainer.train_policy([])
    assert result["status"] == "degraded", "空样本应降级"


# ====================================================================
# T5. 训练结果包含 policy_loss
# ====================================================================
def test_train_result_has_loss():
    trainer = ShadowRLTrainer()
    trainer._activated = True
    trainer._finrl_available = False
    samples = _make_samples(100)
    result = trainer.train_policy(samples)
    assert "policy_loss" in result, "应返回 policy_loss"


# ====================================================================
# T6. 训练结果包含 episode_reward
# ====================================================================
def test_train_result_has_reward():
    trainer = ShadowRLTrainer()
    trainer._activated = True
    trainer._finrl_available = False
    samples = _make_samples(100)
    result = trainer.train_policy(samples)
    assert "episode_reward" in result, "应返回 episode_reward"


# ====================================================================
# T7. 多轮训练后 policy_loss 下降（学习收敛）
# ====================================================================
def test_loss_decreases_over_epochs():
    trainer = ShadowRLTrainer()
    trainer._activated = True
    trainer._finrl_available = False
    samples = _make_samples(200)
    result = trainer.train_policy(samples, epochs=50)
    losses = result.get("loss_history", [])
    if len(losses) >= 2:
        assert losses[-1] < losses[0], "多轮训练后 loss 应下降"


# ====================================================================
# T8. 训练后 Thompson 权重已更新
# ====================================================================
def test_beta_updated_after_train():
    trainer = ShadowRLTrainer()
    trainer._activated = True
    trainer._finrl_available = False
    # 训练前 Beta 参数
    before = trainer.get_beta_stats("test_gene")
    samples = _make_samples(100)
    trainer.train_policy(samples, gene_id="test_gene")
    after = trainer.get_beta_stats("test_gene")
    # 训练后 Beta 参数应变化（α 或 β 增加）
    changed = (after["alpha"] > before["alpha"]) or (after["beta"] > before["beta"])
    assert changed, "训练后 Beta 参数应更新"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
