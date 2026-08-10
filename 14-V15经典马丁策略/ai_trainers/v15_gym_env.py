"""Phase E: V15 马丁策略 Gym 环境

包装 v15_backtest.py 为 Gymnasium 风格环境，供 PPO 训练。
状态 34 维 / 动作 5 维 / 奖励事件驱动（TP=+5, addon=-3*level, bust=-20, shield=-3）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ── §5.1.1 状态空间 34 维定义 ──
STATE_KEYS = [
    # TimingGate (4)
    "timing_score", "structure_match_score", "retrace_quality_score", "extension_chase_score",
    # DirectionGate (5)
    "regime_accum", "regime_up", "regime_down", "long_enabled", "short_enabled",
    # RegimeManager (5)
    "regime_zone_0", "regime_zone_1", "regime_zone_2", "regime_zone_3", "regime_zone_4",
    # 持仓 (9)
    "pos_level_0", "pos_level_1", "pos_level_2", "pos_level_3", "pos_level_4",
    "avg_entry_pct_diff", "unrealized_pnl_ratio", "distance_to_liq_ratio", "unused_9",
    # 波动 (8)
    "atr_14_pct", "atr_14_zscore", "realized_vol_30d", "vol_zscore_60",
    "btc_corr_30d", "btc_rsi_14_norm", "swing_window_daily", "swing_window_4h",
    # 历史表现 (3)
    "recent_10_win_rate", "recent_10_avg_pnl", "max_drawdown_30d",
]
assert len(STATE_KEYS) == 34

# ── §5.1.3 奖励常量 ──
REWARD_TP_FULL = 5.0
REWARD_TP_PARTIAL_RATIO = 1.0
REWARD_CAPITAL_OCCUPANCY = -1.0
REWARD_ADDON_LEVEL = -3.0
REWARD_BUST = -20.0
REWARD_SHIELD_VIOLATION = -3.0
GAMMA = 0.995


def _one_hot(idx: int, n: int) -> List[float]:
    v = [0.0] * n
    if 0 <= idx < n:
        v[idx] = 1.0
    return v


def _regime_to_3hot(regime: str) -> List[float]:
    r = regime.upper()
    if r == "ACCUM":
        return [1.0, 0.0, 0.0]
    elif r == "UP":
        return [0.0, 1.0, 0.0]
    elif r == "DOWN":
        return [0.0, 0.0, 1.0]
    return [0.0, 0.0, 0.0]


class V15MartingaleGymEnv:
    """Gym 风格环境，包装 v15_backtest 单次回测为一个 episode。

    MVP 实现：用合成 K 线驱动，不依赖真实 OKX 数据。
    训练时每个 episode = 一次完整回测（200~500 根 K 线）。
    """

    def __init__(
        self,
        klines: List[Dict] = None,
        initial_capital: float = 10000.0,
        max_addons: int = 4,
        use_shield: bool = True,
    ):
        self.klines = klines or self._generate_synthetic_klines(300)
        self.initial_capital = initial_capital
        self.max_addons = max_addons
        self.use_shield = use_shield

        self.observation_dim = 34
        self.action_dim = 5  # 4 continuous + 1 discrete

        # Episode state
        self._reset_state()

    @staticmethod
    def _generate_synthetic_klines(n: int = 300, seed: int = 42) -> List[Dict]:
        """生成合成 K 线用于训练（GBM + 周期性波动）。"""
        rng = np.random.RandomState(seed)
        klines = []
        price = 100.0
        for i in range(n):
            drift = 0.0002 * math.sin(i / 30)
            vol = 0.02 + 0.01 * math.sin(i / 50)
            ret = rng.normal(drift, vol)
            o = price
            c = price * (1 + ret)
            h = max(o, c) * (1 + abs(rng.normal(0, 0.005)))
            l = min(o, c) * (1 - abs(rng.normal(0, 0.005)))
            v = rng.uniform(100, 1000)
            klines.append({"o": o, "h": h, "l": l, "c": c, "v": v, "t": i})
            price = c
        return klines

    def _reset_state(self):
        self.current_step = 200  # 从第 200 根开始（有足够历史窗口）
        self.capital = self.initial_capital
        self.position = None
        self.total_reward = 0.0
        self.shield_violations = 0
        self.trade_history: List[Dict] = []

    def reset(self) -> np.ndarray:
        self._reset_state()
        return self._get_obs()

    def _get_obs(self) -> np.ndarray:
        """构建 34 维状态向量。"""
        i = self.current_step
        klines = self.klines
        closes = [k["c"] for k in klines[:i+1]]

        # TimingGate 简化（训练用合成值）
        timing_score = 0.5
        structure_score = 0.5
        retrace_score = 0.5
        extension_score = 0.5

        # DirectionGate 简化
        regime = "ACCUM"
        regime_3hot = _regime_to_3hot(regime)

        # RegimeManager 简化
        regime_zone_5hot = _one_hot(2, 5)

        # 持仓状态
        if self.position:
            level = self.position.get("current_level", 0)
            level_5hot = _one_hot(level, 5)
            avg_entry_diff = (closes[-1] - self.position.get("avg_entry", closes[-1])) / max(1e-9, self.position.get("avg_entry", closes[-1]))
            unrealized = self.position.get("unrealized_pnl_ratio", 0.0)
            dist_to_liq = 0.80
        else:
            level_5hot = _one_hot(0, 5)
            avg_entry_diff = 0.0
            unrealized = 0.0
            dist_to_liq = 0.80

        # 波动率
        if len(closes) >= 30:
            rets = np.diff(closes[-30:]) / closes[-30:-1]
            realized_vol = float(np.std(rets))
            atr_pct = realized_vol  # 简化
            atr_z = 0.0
            vol_z = 0.0
        else:
            realized_vol = 0.04
            atr_pct = 0.03
            atr_z = 0.0
            vol_z = 0.0

        btc_corr = 0.8
        btc_rsi = 50.0 / 100.0

        # 历史表现
        if len(self.trade_history) >= 10:
            recent = self.trade_history[-10:]
            wins = sum(1 for t in recent if t.get("pnl_usd", 0) > 0)
            win_rate = wins / 10
            avg_pnl = sum(t.get("pnl_pct", 0) for t in recent) / 10
        else:
            win_rate = 0.5
            avg_pnl = 0.0

        mdd = 0.05

        obs = np.array([
            timing_score, structure_score, retrace_score, extension_score,
            regime_3hot[0], regime_3hot[1], regime_3hot[2],
            1.0, 0.0,  # long_enabled, short_enabled
            *regime_zone_5hot,
            *level_5hot,
            avg_entry_diff, unrealized, dist_to_liq, 0.0,
            atr_pct, atr_z, realized_vol, vol_z,
            btc_corr, btc_rsi, 2.0, 3.0,
            win_rate, avg_pnl, mdd,
        ], dtype=np.float32)

        assert obs.shape == (34,), f"obs shape {obs.shape} != (34,)"
        return obs

    def step(self, action: Dict[str, Any]) -> Tuple[np.ndarray, float, bool, Dict]:
        """执行一步：应用动作 → 推进 K 线 → 计算奖励。

        action: {"addon_pct_mult", "addon_size_mult", "tp_pct_mult",
                 "base_position_mult", "max_addons_delta"}
        """
        i = self.current_step
        reward = 0.0
        info = {"step": i, "shield_flags": []}

        # ── 应用动作到持仓参数 ──
        if self.position is None and i < len(self.klines) - 1:
            # 尝试开仓（简化：每步有小概率开仓）
            # 实际训练中，开仓决策由 v15 信号驱动，这里仅做简化
            pass

        # ── 推进一步 ──
        self.current_step += 1
        if self.current_step >= len(self.klines) - 1:
            done = True
        else:
            done = False

        # ── 检查持仓事件 ──
        if self.position:
            level = self.position.get("current_level", 0)
            k = self.klines[self.current_step]
            entry = self.position.get("avg_entry", k["c"])

            # 检查 TP
            tp_pct = self.position.get("tp_pct", 4.0) / 100.0
            direction = self.position.get("direction", "LONG")
            if direction == "LONG" and k["c"] >= entry * (1 + tp_pct):
                reward += REWARD_TP_FULL
                self.trade_history.append({
                    "pnl_usd": self.capital * tp_pct,
                    "pnl_pct": tp_pct * 100,
                    "exit_reason": "take_profit",
                })
                self.capital *= (1 + tp_pct)
                self.position = None
            elif direction == "SHORT" and k["c"] <= entry * (1 - tp_pct):
                reward += REWARD_TP_FULL
                self.trade_history.append({
                    "pnl_usd": self.capital * tp_pct,
                    "pnl_pct": tp_pct * 100,
                    "exit_reason": "take_profit",
                })
                self.capital *= (1 + tp_pct)
                self.position = None
            else:
                # 资金占用惩罚
                deployed = self.position.get("total_deployed", 0)
                if deployed > 0 and self.capital > 0:
                    reward += REWARD_CAPITAL_OCCUPANCY * (deployed / self.capital)

                # 加仓检查
                next_level = level + 1
                eff_max = self.max_addons + action.get("max_addons_delta", 0)
                if next_level <= eff_max and next_level <= self.max_addons:
                    addon_pct = self.position.get("addon_pct", 8.0) / 100.0 * action.get("addon_pct_mult", 1.0)
                    if direction == "LONG" and k["c"] <= entry * (1 - addon_pct * next_level):
                        self.position["current_level"] = next_level
                        reward += REWARD_ADDON_LEVEL * next_level
                    elif direction == "SHORT" and k["c"] >= entry * (1 + addon_pct * next_level):
                        self.position["current_level"] = next_level
                        reward += REWARD_ADDON_LEVEL * next_level

                # 爆仓检查（满档且大幅亏损）
                if level >= self.max_addons:
                    liq_pct = 0.15  # 简化：15% 爆仓线
                    if direction == "LONG" and k["c"] <= entry * (1 - liq_pct):
                        reward += REWARD_BUST
                        self.trade_history.append({
                            "pnl_usd": -self.capital * liq_pct,
                            "pnl_pct": -liq_pct * 100,
                            "exit_reason": "bust",
                        })
                        self.capital *= (1 - liq_pct)
                        self.position = None
                    elif direction == "SHORT" and k["c"] >= entry * (1 + liq_pct):
                        reward += REWARD_BUST
                        self.trade_history.append({
                            "pnl_usd": -self.capital * liq_pct,
                            "pnl_pct": -liq_pct * 100,
                            "exit_reason": "bust",
                        })
                        self.capital *= (1 - liq_pct)
                        self.position = None

        # ── DS 盾检查（简化：只记录违规） ──
        if self.use_shield:
            for k in ["addon_size_mult", "base_position_mult"]:
                if action.get(k, 1.0) > 1.5:
                    reward += REWARD_SHIELD_VIOLATION
                    self.shield_violations += 1
                    info["shield_flags"].append("DS_CLAMP")

        self.total_reward += reward
        info["capital"] = self.capital
        info["total_reward"] = self.total_reward

        obs = self._get_obs()
        return obs, reward, done, info

    def get_s_state_dict(self) -> Dict[str, Any]:
        """返回 dict 形式状态（供 PhaseEGateway 使用）。"""
        obs = self._get_obs()
        return {
            "timing_score": obs[0],
            "structure_match_score": obs[1],
            "retrace_quality_score": obs[2],
            "extension_chase_score": obs[3],
            "regime": "ACCUM",
            "long_enabled": True,
            "short_enabled": False,
            "btc_windvane_strength": 0.5,
            "regime_zone": 2,
            "days_in_current_zone": 10,
            "position_level": self.position.get("current_level", 0) if self.position else 0,
            "avg_entry_price_pct_diff": obs[20],
            "unrealized_pnl_ratio": obs[21],
            "distance_to_liq_ratio": obs[22],
            "atr_14_pct": obs[24],
            "atr_14_zscore_30": obs[25],
            "realized_vol_30d": obs[26],
            "vol_zscore_60": obs[27],
            "btc_corr_30d": obs[28],
            "btc_rsi_14": obs[29] * 100,
            "swing_window_daily": obs[30],
            "swing_window_4h": obs[31],
            "recent_10_win_rate": obs[32],
            "recent_10_avg_pnl_ratio": obs[33],
            "max_drawdown_30d": 0.05,
            "account_margin_ratio": 0.10,
            "imr": 0.05,
            "coin_total_deployed": 0.0,
        }
