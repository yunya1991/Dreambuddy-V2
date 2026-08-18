"""Phase E: Gym 环境 + PPO 模型测试"""
import pytest
import numpy as np
import torch


class TestV15GymEnv:
    """V15MartingaleGymEnv 测试。"""

    def test_reset_returns_34dim_obs(self):
        from ai_trainers.v15_gym_env import V15MartingaleGymEnv
        env = V15MartingaleGymEnv()
        obs = env.reset()
        assert obs.shape == (34,)
        assert obs.dtype == np.float32

    def test_step_returns_tuple(self):
        from ai_trainers.v15_gym_env import V15MartingaleGymEnv
        env = V15MartingaleGymEnv()
        env.reset()
        action = {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.0,
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }
        obs, reward, done, info = env.step(action)
        assert obs.shape == (34,)
        assert isinstance(reward, float)
        assert isinstance(done, bool)
        assert isinstance(info, dict)

    def test_episode_terminates(self):
        from ai_trainers.v15_gym_env import V15MartingaleGymEnv
        env = V15MartingaleGymEnv(klines=V15MartingaleGymEnv._generate_synthetic_klines(250))
        env.reset()
        action = {
            "addon_pct_mult": 1.0, "addon_size_mult": 1.0,
            "tp_pct_mult": 1.0, "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }
        done = False
        steps = 0
        while not done and steps < 100:
            _, _, done, _ = env.step(action)
            steps += 1
        assert done or steps == 100

    def test_s_state_dict_has_required_keys(self):
        from ai_trainers.v15_gym_env import V15MartingaleGymEnv
        env = V15MartingaleGymEnv()
        env.reset()
        s = env.get_s_state_dict()
        required = ["timing_score", "regime", "position_level", "vol_zscore_60",
                     "recent_10_win_rate", "account_margin_ratio", "imr"]
        for k in required:
            assert k in s, f"missing key: {k}"


class TestPPOLSTMActorCritic:
    """PPO-LSTM Actor-Critic 网络测试。"""

    def test_forward_shapes(self):
        from ai_trainers.phase_e_models import PPOLSTMActorCritic
        model = PPOLSTMActorCritic(state_dim=34, hidden_dim=64)
        x = torch.randn(4, 10, 34)  # B=4, T=10
        out = model(x)
        assert out["cont_mean"].shape == (4, 10, 4)
        assert out["cont_std"].shape == (4, 10, 4)
        assert out["disc_logits"].shape == (4, 10, 2)
        assert out["value"].shape == (4, 10, 1)

    def test_sample_action_shapes(self):
        from ai_trainers.phase_e_models import PPOLSTMActorCritic
        model = PPOLSTMActorCritic(state_dim=34, hidden_dim=64)
        x = torch.randn(4, 10, 34)
        out = model.sample_action(x)
        assert out["action_cont"].shape == (4, 4)
        assert out["action_disc"].shape == (4,)
        assert out["log_prob"].shape == (4,)
        assert out["value"].shape == (4,)
        assert out["entropy"].shape == (4,)

    def test_evaluate_actions(self):
        from ai_trainers.phase_e_models import PPOLSTMActorCritic
        model = PPOLSTMActorCritic(state_dim=34, hidden_dim=64)
        x = torch.randn(4, 10, 34)
        action_cont = torch.randn(4, 4)
        action_disc = torch.randint(0, 2, (4,))
        out = model.evaluate_actions(x, action_cont, action_disc)
        assert out["log_prob"].shape == (4,)
        assert out["value"].shape == (4,)
        assert out["entropy"].shape == (4,)

    def test_get_action_dict(self):
        from ai_trainers.phase_e_models import PPOLSTMActorCritic
        model = PPOLSTMActorCritic(state_dim=34, hidden_dim=64)
        x = torch.randn(1, 10, 34)
        action = model.get_action_dict(x)
        assert "addon_pct_mult" in action
        assert "addon_size_mult" in action
        assert "tp_pct_mult" in action
        assert "base_position_mult" in action
        assert "max_addons_delta" in action
        assert action["max_addons_delta"] in [-1, 0]

    def test_single_step_input(self):
        """单步输入 (B, state_dim) 也能正常工作。"""
        from ai_trainers.phase_e_models import PPOLSTMActorCritic
        model = PPOLSTMActorCritic(state_dim=34, hidden_dim=64)
        x = torch.randn(1, 34)
        out = model(x)
        assert out["cont_mean"].shape == (1, 1, 4)

    def test_lstm_hidden_state_propagation(self):
        """LSTM 隐状态跨步传播。"""
        from ai_trainers.phase_e_models import PPOLSTMActorCritic
        model = PPOLSTMActorCritic(state_dim=34, hidden_dim=64)
        x1 = torch.randn(1, 1, 34)
        out1 = model(x1)
        h = out1["h_n"]
        x2 = torch.randn(1, 1, 34)
        out2 = model(x2, h)
        assert out2["cont_mean"].shape == (1, 1, 4)
