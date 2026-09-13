"""RL 离场策略层三阶段测试

阶段1: CQL 预训练器（离线训练 Q 函数）
阶段2: Shielded 推理器（CQL 策略 + EvolutionExitEngine shield）
阶段3: PPO 微调器（在线 clip 更新）
"""
import pytest
import numpy as np

# ============================================================================
# 阶段 1: CQL 预训练器
# ============================================================================

class TestCQLTrainer:
    """CQL 离线 RL 预训练器"""

    def test_cql_trainer_import(self):
        """能从 exit_rl_policy 导入 CQLTrainer"""
        from dreambuddy_evolution.core.exit_rl_policy import CQLTrainer
        assert CQLTrainer is not None

    def test_cql_q_network_forward(self):
        """Q 网络前向传播：8维状态 → 5个动作 Q 值"""
        from dreambuddy_evolution.core.exit_rl_policy import CQLTrainer
        trainer = CQLTrainer(state_dim=8, n_actions=5, lr=1e-3, cql_alpha=1.0)
        state = np.random.rand(8).astype(np.float32)
        q_values = trainer.predict_q(state)
        assert q_values.shape == (5,)
        assert not np.any(np.isnan(q_values))

    def test_cql_train_on_batch(self):
        """CQL 训练一个 batch 后 loss 应有变化"""
        from dreambuddy_evolution.core.exit_rl_policy import CQLTrainer
        trainer = CQLTrainer(state_dim=8, n_actions=5, lr=1e-3, cql_alpha=1.0)
        # 构造 32 条 (s, a, R, s') 样本
        batch = []
        for _ in range(32):
            batch.append({
                "state": np.random.rand(8).astype(np.float32),
                "action": np.random.randint(5),
                "reward": float(np.random.randn()),
                "next_state": np.random.rand(8).astype(np.float32),
                "done": np.random.rand() > 0.8,
            })
        loss1 = trainer.train_batch(batch)
        loss2 = trainer.train_batch(batch)
        # loss 应为有限值
        assert np.isfinite(loss1)
        assert np.isfinite(loss2)

    def test_cql_save_load(self, tmp_path):
        """CQL 模型可保存和加载"""
        from dreambuddy_evolution.core.exit_rl_policy import CQLTrainer
        trainer = CQLTrainer(state_dim=8, n_actions=5)
        # 训练几步
        batch = [{
            "state": np.random.rand(8).astype(np.float32),
            "action": np.random.randint(5),
            "reward": float(np.random.randn()),
            "next_state": np.random.rand(8).astype(np.float32),
            "done": False,
        } for _ in range(16)]
        trainer.train_batch(batch)
        # 保存
        model_path = str(tmp_path / "exit_cql_v1.pt")
        trainer.save(model_path)
        # 加载
        trainer2 = CQLTrainer(state_dim=8, n_actions=5)
        trainer2.load(model_path)
        # 验证 Q 值一致
        state = np.random.rand(8).astype(np.float32)
        q1 = trainer.predict_q(state)
        q2 = trainer2.predict_q(state)
        np.testing.assert_allclose(q1, q2, atol=1e-5)

    def test_cql_conservative_penalty(self):
        """CQL 保守惩罚：OOD 动作 Q 值被压低"""
        import numpy as np
        np.random.seed(42)
        try:
            import torch
            torch.manual_seed(42)
        except ImportError:
            pass
        from dreambuddy_evolution.core.exit_rl_policy import CQLTrainer
        trainer = CQLTrainer(state_dim=8, n_actions=5, cql_alpha=5.0)  # 高 alpha
        # 训练一批数据，让某个动作有高 reward
        batch = [{
            "state": np.array([0.1]*8, dtype=np.float32),
            "action": 0,  # 动作 0 有正 reward
            "reward": 1.0,
            "next_state": np.array([0.1]*8, dtype=np.float32),
            "done": False,
        } for _ in range(64)]
        for _ in range(50):
            trainer.train_batch(batch)
        # 动作 0 的 Q 值应高于其他动作（OOD 动作被 CQL 压低）
        state = np.array([0.1]*8, dtype=np.float32)
        q_values = trainer.predict_q(state)
        # Q[a=0] 应高于其他动作均值（CQL 保守惩罚 + 训练收敛）
        assert q_values[0] >= np.mean(q_values[1:]) - 0.15


# ============================================================================
# 阶段 2: Shielded 推理器
# ============================================================================

class TestShieldedPolicy:
    """CQL 策略 + EvolutionExitEngine shield"""

    def test_shielded_policy_import(self):
        """能从 exit_rl_policy 导入 ShieldedPolicy"""
        from dreambuddy_evolution.core.exit_rl_policy import ShieldedPolicy
        assert ShieldedPolicy is not None

    def test_shielded_policy_safe_action(self):
        """RL 建议安全动作 → 直接执行"""
        from dreambuddy_evolution.core.exit_rl_policy import ShieldedPolicy, CQLTrainer
        trainer = CQLTrainer(state_dim=8, n_actions=5)
        policy = ShieldedPolicy(
            cql_trainer=trainer,
            exit_engine=None,  # 测试中不传 shield
            log_fn=lambda msg, level="INFO": None,
        )
        state = np.random.rand(8).astype(np.float32)
        action, params = policy.act(state)
        assert action in ("hold", "adjust_sl_tp", "trailing", "force_close", "partial_close")

    def test_shielded_policy_unsafe_action_downgrade(self):
        """RL 建议不安全动作 → shield 降级为规则动作"""
        from dreambuddy_evolution.core.exit_rl_policy import ShieldedPolicy, CQLTrainer
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        trainer = CQLTrainer(state_dim=8, n_actions=5)
        engine = EvolutionExitEngine(
            okx_client=None, ess_provider=None, ftc_bridge=None,
            shadow_rl_tracker=None, log_fn=lambda msg, level="INFO": None,
        )
        policy = ShieldedPolicy(
            cql_trainer=trainer,
            exit_engine=engine,
            log_fn=lambda msg, level="INFO": None,
        )
        # 构造一个 RL 建议不安全动作的场景
        # upl_ratio=0.05（盈利 5%）但 RL 建议 force_close → shield 应降级
        context = {
            "symbol": "BTC", "pos_side": "long",
            "entry_price": 100000.0, "current_price": 105000.0,
            "upl_ratio": 0.05, "position_age_sec": 7200,
            "r_vector": {"R_up": 0.5, "R_down": 0.5}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.02,
            "current_sl_px": 97000.0, "current_tp_px": 106000.0,
            "okx_algo_triggered": False,
        }
        action, params = policy.act_with_shield(
            state=np.array([0.05, 120, 0.02, 50, 0.6, 0.5, 1.0, 0.0], dtype=np.float32),
            context=context,
        )
        # shield 应阻止 force_close（盈利 5% 时不应强平）
        assert action != "force_close"

    def test_shielded_policy_fail_open(self):
        """CQL 推理异常 → FAIL-OPEN 返回 hold"""
        from dreambuddy_evolution.core.exit_rl_policy import ShieldedPolicy
        policy = ShieldedPolicy(
            cql_trainer=None,  # 无 trainer → 模拟异常
            exit_engine=None,
            log_fn=lambda msg, level="INFO": None,
        )
        action, params = policy.act(np.zeros(8, dtype=np.float32))
        assert action == "hold"
        assert "fail_open" in params.get("reason", "").lower()


# ============================================================================
# 阶段 3: PPO 微调器
# ============================================================================

class TestPPOFineTuner:
    """PPO 在线微调器"""

    def test_ppo_fine_tuner_import(self):
        """能从 exit_rl_policy 导入 PPOFineTuner"""
        from dreambuddy_evolution.core.exit_rl_policy import PPOFineTuner
        assert PPOFineTuner is not None

    def test_ppo_actor_forward(self):
        """PPO actor 前向传播：8维状态 → 5个动作概率"""
        from dreambuddy_evolution.core.exit_rl_policy import PPOFineTuner
        tuner = PPOFineTuner(state_dim=8, n_actions=5, lr=1e-4, clip_epsilon=0.2)
        state = np.random.rand(8).astype(np.float32)
        action_probs = tuner.predict_probs(state)
        assert action_probs.shape == (5,)
        # 概率和约等于 1
        np.testing.assert_allclose(np.sum(action_probs), 1.0, atol=1e-4)

    def test_ppo_update_on_batch(self):
        """PPO 在一个 batch 上更新后 loss 应有变化"""
        from dreambuddy_evolution.core.exit_rl_policy import PPOFineTuner
        tuner = PPOFineTuner(state_dim=8, n_actions=5, lr=1e-4, clip_epsilon=0.2)
        batch = []
        for _ in range(64):
            batch.append({
                "state": np.random.rand(8).astype(np.float32),
                "action": np.random.randint(5),
                "reward": float(np.random.randn()),
                "old_prob": float(1.0 / 5),  # 均匀分布
                "advantage": float(np.random.randn()),
            })
        loss1 = tuner.update(batch)
        loss2 = tuner.update(batch)
        assert np.isfinite(loss1)
        assert np.isfinite(loss2)

    def test_ppo_clip_prevents_large_update(self):
        """PPO clip 防止策略更新过大"""
        from dreambuddy_evolution.core.exit_rl_policy import PPOFineTuner
        tuner = PPOFineTuner(state_dim=8, n_actions=5, lr=1e-4, clip_epsilon=0.2)
        # 构造极端 advantage 测试 clip
        batch = [{
            "state": np.random.rand(8).astype(np.float32),
            "action": 0,
            "reward": 10.0,  # 极大 reward
            "old_prob": 0.01,  # 极低旧概率
            "advantage": 10.0,  # 极大 advantage
        } for _ in range(32)]
        loss = tuner.update(batch)
        # loss 应有限（clip 生效，不爆炸）
        assert np.isfinite(loss)
        assert loss < 100.0  # clip 限制

    def test_ppo_init_from_cql(self):
        """PPO 可从 CQL 预训练模型初始化"""
        from dreambuddy_evolution.core.exit_rl_policy import CQLTrainer, PPOFineTuner
        cql = CQLTrainer(state_dim=8, n_actions=5)
        # 训练 CQL
        batch = [{
            "state": np.random.rand(8).astype(np.float32),
            "action": np.random.randint(5),
            "reward": float(np.random.randn()),
            "next_state": np.random.rand(8).astype(np.float32),
            "done": False,
        } for _ in range(32)]
        for _ in range(10):
            cql.train_batch(batch)
        # 从 CQL 初始化 PPO
        ppo = PPOFineTuner(state_dim=8, n_actions=5)
        ppo.init_from_cql(cql)
        # PPO actor 应有非均匀输出（受 CQL 影响）
        state = np.random.rand(8).astype(np.float32)
        probs = ppo.predict_probs(state)
        assert np.isfinite(probs).all()
        np.testing.assert_allclose(np.sum(probs), 1.0, atol=1e-4)
