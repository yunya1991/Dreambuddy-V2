#!/usr/bin/env python3
"""Phase E: PPO-LSTM 训练脚本

路线图 §5.5: 离线训练 → Walk-Forward 早停 → checkpoint 保存。

用法:
    python3 phase_e_train_ppo.py --episodes 500 --out ./data/phase_e_models_v1/ppo_lstm.pt
    python3 phase_e_train_ppo.py --quick-smoke  # 快速冒烟测试
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

# 确保项目根目录在 sys.path
_BASE_DIR = Path(__file__).resolve().parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

from ai_trainers.phase_e_models import PPOLSTMActorCritic
from ai_trainers.v15_gym_env import V15MartingaleGymEnv, GAMMA


# ── PPO 超参数（v2 提 entropy / 短 rollout，避免 identity 收敛） ──
PPO_CONFIG = {
    "lr": 2e-4,
    "gamma": GAMMA,           # 0.995
    "clip_eps": 0.2,
    "ent_coef": 0.03,         # v2: 0.01 → 0.03，防 identity 过早收敛
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "n_steps": 512,           # v2: 2048 → 512，每 episode 一次更频繁更新
    "batch_size": 64,
    "n_epochs": 4,
    "hidden_dim": 128,
    "num_layers": 1,
    "reward_window": 20,      # v2: 每 20 ep 计算 moving best，防偶发 0 值卡住
}


class RolloutBuffer:
    """PPO rollout 缓冲区。"""

    def __init__(self):
        self.states: List[np.ndarray] = []
        self.actions_cont: List[np.ndarray] = []
        self.actions_disc: List[int] = []
        self.log_probs: List[float] = []
        self.rewards: List[float] = []
        self.values: List[float] = []
        self.dones: List[bool] = []

    def add(self, state, action_cont, action_disc, log_prob, reward, value, done):
        self.states.append(state)
        self.actions_cont.append(action_cont)
        self.actions_disc.append(action_disc)
        self.log_probs.append(log_prob)
        self.rewards.append(reward)
        self.values.append(value)
        self.dones.append(done)

    def __len__(self):
        return len(self.states)

    def compute_returns(self, gamma: float, last_value: float) -> Dict[str, torch.Tensor]:
        n = len(self.rewards)
        returns = np.zeros(n, dtype=np.float32)
        advantages = np.zeros(n, dtype=np.float32)
        gae = 0.0
        for t in reversed(range(n)):
            next_val = last_value if t == n - 1 else self.values[t + 1]
            next_non_terminal = 1.0 - float(self.dones[t])
            delta = self.rewards[t] + gamma * next_val * next_non_terminal - self.values[t]
            gae = delta + gamma * 0.95 * gae * next_non_terminal  # GAE λ=0.95
            advantages[t] = gae
            returns[t] = advantages[t] + self.values[t]

        return {
            "states": torch.FloatTensor(np.array(self.states)),
            "actions_cont": torch.FloatTensor(np.array(self.actions_cont)),
            "actions_disc": torch.LongTensor(np.array(self.actions_disc)),
            "old_log_probs": torch.FloatTensor(np.array(self.log_probs)),
            "returns": torch.FloatTensor(returns),
            "advantages": torch.FloatTensor(advantages),
        }


def train_ppo(
    episodes: int = 500,
    config: Dict = None,
    out_path: str = "./data/phase_e_models_v1/ppo_lstm.pt",
    log_interval: int = 10,
    quick_smoke: bool = False,
):
    """PPO 训练主循环。"""
    cfg = {**PPO_CONFIG, **(config or {})}
    if quick_smoke:
        cfg["n_steps"] = 128
        cfg["batch_size"] = 32
        episodes = 5
        log_interval = 1

    device = torch.device("cpu")
    # v2: 每 episode 一个新 env 实例，K 线分布不同（PPO 的多样性至关重要）
    env_fn = lambda s: V15MartingaleGymEnv(seed=s)
    env = env_fn(1000)
    model = PPOLSTMActorCritic(
        state_dim=env.observation_dim,
        hidden_dim=cfg["hidden_dim"],
        num_layers=cfg["num_layers"],
    ).to(device)
    optimizer = optim.Adam(model.parameters(), lr=cfg["lr"])

    best_reward = -float("inf")
    all_rewards: List[float] = []
    reward_window_size = int(cfg.get("reward_window", 20))
    rolling_best_moving = -float("inf")

    for ep in range(1, episodes + 1):
        # v2: 换 seed，避免 PPO 记住一份 K 线
        env = env_fn(1000 + ep)
        # ── Rollout ──
        buf = RolloutBuffer()
        obs = env.reset()
        h = None
        ep_reward = 0.0
        steps = 0
        n_tp_ep = 0
        n_bust_ep = 0

        for _ in range(cfg["n_steps"]):
            x = torch.FloatTensor(obs).unsqueeze(0).unsqueeze(0).to(device)  # (1, 1, 34)
            with torch.no_grad():
                out = model.sample_action(x, h)
                h = out["h_n"]

            action_cont = out["action_cont"].squeeze(0).cpu().numpy()
            action_disc = int(out["action_disc"].item())
            log_prob = float(out["log_prob"].item())
            value = float(out["value"].item())

            # 映射到 action dict
            action_dict = {
                "addon_pct_mult": float(action_cont[0]),
                "addon_size_mult": float(action_cont[1]),
                "tp_pct_mult": float(action_cont[2]),
                "base_position_mult": float(action_cont[3]),
                "max_addons_delta": action_disc - 1,  # 0→-1, 1→0
            }

            next_obs, reward, done, info = env.step(action_dict)
            buf.add(obs, action_cont, action_disc, log_prob, reward, value, done)
            obs = next_obs
            ep_reward += reward
            steps += 1
            if info.get("n_trades"):
                last_tr = env.trade_history[-1] if env.trade_history else None
                if last_tr:
                    if last_tr.get("exit_reason") == "take_profit":
                        n_tp_ep += 1
                    elif last_tr.get("exit_reason") == "bust":
                        n_bust_ep += 1

            if done:
                obs = env.reset()
                h = None

        all_rewards.append(ep_reward)

        # ── PPO Update ──
        with torch.no_grad():
            x_last = torch.FloatTensor(obs).unsqueeze(0).unsqueeze(0).to(device)
            last_value = float(model(x_last)["value"][:, -1, 0].item())

        batch = buf.compute_returns(cfg["gamma"], last_value)
        advantages = batch["advantages"]
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        n = len(batch["states"])
        idx = np.arange(n)
        for _ in range(cfg["n_epochs"]):
            np.random.shuffle(idx)
            for start in range(0, n, cfg["batch_size"]):
                end = min(start + cfg["batch_size"], n)
                bidx = idx[start:end]

                states = batch["states"][bidx]  # (B, 34)
                actions_cont = batch["actions_cont"][bidx]
                actions_disc = batch["actions_disc"][bidx]
                old_log_probs = batch["old_log_probs"][bidx]
                returns = batch["returns"][bidx]
                adv = advantages[bidx]

                # 前向
                out = model.evaluate_actions(states, actions_cont, actions_disc)
                new_log_probs = out["log_prob"]
                values = out["value"]
                entropy = out["entropy"].mean()

                # PPO loss
                ratio = (new_log_probs - old_log_probs).exp()
                surr1 = ratio * adv
                surr2 = torch.clamp(ratio, 1 - cfg["clip_eps"], 1 + cfg["clip_eps"]) * adv
                policy_loss = -torch.min(surr1, surr2).mean()
                value_loss = F_mse_loss(values, returns)
                loss = policy_loss + cfg["vf_coef"] * value_loss - cfg["ent_coef"] * entropy

                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), cfg["max_grad_norm"])
                optimizer.step()

        # ── 日志 & 保存（v2: rolling window best 防偶发 0 值卡 best_reward=0） ──
        if ep % log_interval == 0 or ep == 1:
            avg_r = float(np.mean(all_rewards[-log_interval:]))
            win_r = float(np.mean(all_rewards[-reward_window_size:])) if len(all_rewards) >= reward_window_size else float("nan")
            print(
                f"  ep {ep:4d}/{episodes}  avg_r={avg_r:+.2f}  win_r={win_r:+.2f}  "
                f"best={best_reward:+.2f}  steps={steps}  TP≈{n_tp_ep}  bust≈{n_bust_ep}  "
                f"capital={info.get('capital',0):.0f}"
            )
            # v2: 如果 rolling window 创了新高，同样视为 best（避免 ep_reward==0 的边缘 episode 永远不保存）
            if len(all_rewards) >= reward_window_size and win_r > rolling_best_moving:
                rolling_best_moving = win_r
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                torch.save({
                    "model_state_dict": model.state_dict(),
                    "config": cfg,
                    "episode": ep,
                    "best_reward": rolling_best_moving,
                    "best_kind": "rolling_window",
                    "window_size": reward_window_size,
                }, out_path)

        # 保存单集 best
        if ep_reward > best_reward:
            best_reward = ep_reward
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "model_state_dict": model.state_dict(),
                "config": cfg,
                "episode": ep,
                "best_reward": best_reward,
                "best_kind": "single_episode",
            }, out_path)

    print(f"\n✅ PPO 训练完成: {episodes} episodes, best_reward={best_reward:.2f}")
    print(f"   权重已保存: {out_path}")
    return {"best_reward": best_reward, "episodes": episodes, "all_rewards": all_rewards}


def F_mse_loss(pred, target):
    return torch.nn.functional.mse_loss(pred, target)


def main():
    parser = argparse.ArgumentParser(description="Phase E: PPO-LSTM 训练")
    parser.add_argument("--episodes", type=int, default=500, help="训练 episode 数")
    parser.add_argument("--out", type=str, default="./data/phase_e_models_v1/ppo_lstm.pt")
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--quick-smoke", action="store_true", help="快速冒烟测试（5 episodes）")
    parser.add_argument("--log-interval", type=int, default=10)
    args = parser.parse_args()

    config = {"lr": args.lr}
    train_ppo(
        episodes=args.episodes,
        config=config,
        out_path=args.out,
        log_interval=args.log_interval,
        quick_smoke=args.quick_smoke,
    )


if __name__ == "__main__":
    main()
