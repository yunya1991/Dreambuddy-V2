"""Phase E: V15 马丁策略 Gym 环境 (v2 修复 PPO 不学习)

包装 v15_backtest.py 为 Gymnasium 风格环境，供 PPO 训练。
状态 34 维 / 动作 5 维 / 奖励事件驱动（TP=+5, addon=-3*level, bust=-20, shield=-3）。

v2 关键修复：
- _generate_synthetic_klines：加入 bull/bear 段与 1% 爆仓跳空，保证信号多样
- __init__：每 episode 用新随机 seed → 分布不僵死
- _get_obs：timing / regime / obs 全部改为基于当前 4H 窗口计算，不再硬编码 0.5
- step：position is None 时，按 v15 信号（MA 回撤 + 动量）概率开多单，触发 TP/bust/addon 奖励
- _reset_state：每 episode 重采样 seed 与 价格起点
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

# ── §5.1.3 奖励常量（v3-D: 重平衡 — 加仓不惩罚，TP奖励提升，资金占用微罚） ──
REWARD_TP_FULL = 10.0          # v3: 5→10，TP 是核心正反馈
REWARD_TP_PARTIAL_RATIO = 1.0
REWARD_CAPITAL_OCCUPANCY = -0.02  # v3: -0.10→-0.02，微罚资金占用（防久持不TP）
REWARD_ADDON_LEVEL = -0.5       # v3: -3.0→-0.5，加仓是策略核心而非惩罚
REWARD_BUST = -20.0
REWARD_SHIELD_VIOLATION = -3.0
REWARD_OPEN_TRADE = 0.0
REWARD_PNL_SCALE = 0.01         # v3: realized PnL 直接乘入 reward（使 PPO 感受到真实盈亏）
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


def _sma(xs: List[float], p: int) -> float:
    if len(xs) < p:
        p = len(xs)
    return sum(xs[-p:]) / max(1, p)


def _rsi_ema(closes: List[float], p: int = 14) -> float:
    if len(closes) < p + 1:
        return 50.0
    d = [closes[i] / max(1e-9, closes[i - 1]) - 1 for i in range(1, len(closes))]
    wins = [max(x, 0.0) for x in d[-p:]]
    losses = [max(-x, 0.0) for x in d[-p:]]
    ag = sum(wins) / p
    al = sum(losses) / p
    if al <= 1e-12:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


class V15MartingaleGymEnv:
    """Gym 风格环境，包装 v15_backtest 单次回测为一个 episode (v2)。

    每个 episode 使用不同的 seed 生成 K 线，避免分布重复。
    每 step 推进 1 根 1H K 线；在无持仓时按概率开多单，触发 TP/bust/addon 奖励。
    """

    def __init__(
        self,
        klines: List[Dict] = None,
        initial_capital: float = 10000.0,
        max_addons: int = 4,
        use_shield: bool = True,
        seed: int = 42,
    ):
        self._seed = seed
        self._rng = np.random.RandomState(seed)
        self.initial_capital = initial_capital
        self.max_addons = max_addons
        self.use_shield = use_shield
        self.observation_dim = 34
        self.action_dim = 5  # 4 continuous + 1 discrete
        # Episode state (在 reset 里填充 klines)
        self.klines: List[Dict] = klines if klines is not None else []
        self._reset_state()

    # ── 合成 K 线（v2: 趋势段 + bear 段加权 + 偶发爆仓跳空） ──
    @staticmethod
    def _generate_synthetic_klines(n: int = 600, seed: int = 42) -> List[Dict]:
        rng = np.random.RandomState(seed)
        klines: List[Dict] = []
        price = float(rng.uniform(10, 500))
        trend = 0.0
        for i in range(n):
            if i % 60 == 0:
                seg = rng.choice(["bull", "bear", "random", "bear", "bull", "random"])
                if seg == "bull":
                    trend = float(rng.uniform(0.0004, 0.0012))
                elif seg == "bear":
                    trend = float(rng.uniform(-0.0012, -0.0004))
                else:
                    trend = float(rng.uniform(-0.0002, 0.0002))
            drift = trend + 0.0002 * math.sin(i / 30.0)
            vol = 0.025 + 0.015 * math.sin(i / 50.0) + float(rng.uniform(0, 0.01))
            ret = float(rng.normal(drift, vol))
            if rng.random() < 0.01:
                ret -= float(rng.uniform(0.08, 0.18))
            o = price
            c = max(0.01, price * (1 + ret))
            h = max(o, c) * (1 + abs(float(rng.normal(0, 0.006))))
            l = min(o, c) * (1 - abs(float(rng.normal(0, 0.006))))
            v = float(rng.uniform(100, 1500))
            klines.append({"o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": v, "t": i})
            price = c
        return klines

    def _reset_state(self):
        # v2: 每 episode 换一个 seed 生成 K 线，避免过拟合同一份 K 线
        self._seed += 1
        self.klines = self._generate_synthetic_klines(n=600, seed=self._seed)
        self.current_step = 120  # 给前面 120 根做指标
        self.capital = self.initial_capital
        self.position: Optional[Dict[str, Any]] = None
        self.total_reward = 0.0
        self.shield_violations = 0
        self.trade_history: List[Dict] = []
        self._steps_since_closed = 0

    def reset(self) -> np.ndarray:
        self._reset_state()
        return self._get_obs()

    # ── 观测：不再硬编码 0.5 ──
    def _get_obs(self) -> np.ndarray:
        """基于当前 K 线窗口计算 34 维状态。"""
        i = self.current_step
        closes = [k["c"] for k in self.klines[: i + 1]]
        highs = [k["h"] for k in self.klines[: i + 1]]
        lows = [k["l"] for k in self.klines[: i + 1]]

        # ── Timing 4 维：用价格相对 MA20/MA60 的位置 + 回撤深度近似 ──
        ma20 = _sma(closes, 20)
        ma60 = _sma(closes, 60)
        last = closes[-1]
        timing_score = float(np.clip((last / max(1e-9, ma20) - 1.0) * 10 + 0.5, 0.0, 1.0))  # 超 MA 涨 → 高分
        max_20 = max(highs[-20:]) if len(highs) >= 20 else highs[-1]
        retrace_depth = 1.0 - last / max(1e-9, max_20)  # 回撤
        structure_score = float(np.clip(1.0 - retrace_depth * 2.5, 0.0, 1.0))
        retrace_score = float(np.clip(0.8 - retrace_depth * 2.0 + 0.2, 0.0, 1.0))
        window = lows[-40:] if len(lows) >= 40 else lows
        extension = (last / max(1e-9, min(window)) - 1.0) if window else 0.0
        extension_score = float(np.clip(1.0 - extension * 3.0, 0.0, 1.0))

        # ── DirectionGate 3hot + long/short enabled ──
        if ma20 > ma60 * 1.01:
            regime = "UP"
            zone = 3
        elif ma20 < ma60 * 0.99:
            regime = "DOWN"
            zone = 1
        else:
            regime = "ACCUM"
            zone = 2
        regime_3hot = _regime_to_3hot(regime)
        long_enabled = 1.0 if regime != "DOWN" else 0.4
        short_enabled = 1.0 if regime != "UP" else 0.4

        # ── Regime 5 维 ──
        regime_zone_5hot = _one_hot(zone, 5)

        # ── 持仓 9 维 ──
        if self.position:
            level = int(self.position.get("current_level", 0))
            level_5hot = _one_hot(level, 5)
            avg_entry = float(self.position.get("avg_entry", last))
            avg_entry_diff = (last - avg_entry) / max(1e-9, avg_entry)
            total_deployed = float(self.position.get("total_deployed", 1e-9))
            cost_basis = total_deployed
            if cost_basis > 0 and avg_entry > 0:
                # 浮盈比例 ≈ (last - avg_entry) * qty / cost
                qty = cost_basis / max(1e-9, avg_entry)
                unrealized = (last - avg_entry) * qty / max(1e-9, cost_basis)
            else:
                unrealized = 0.0
            max_loss_frac = 0.20  # 20% 爆仓线
            liq_price = avg_entry * (1 - max_loss_frac)
            if avg_entry != liq_price:
                dist_to_liq = (last - liq_price) / max(1e-9, avg_entry - liq_price)
            else:
                dist_to_liq = 1.0
            dist_to_liq = float(np.clip(dist_to_liq, 0.0, 1.0))
        else:
            level_5hot = _one_hot(0, 5)
            avg_entry_diff = 0.0
            unrealized = 0.0
            dist_to_liq = 1.0

        # ── 波动率 8 维 ──
        if len(closes) >= 30:
            rets = np.diff(closes[-30:]) / np.maximum(1e-9, closes[-30:-1])
            realized_vol = float(np.std(rets))
        else:
            realized_vol = 0.02
        if len(closes) >= 60:
            rets60 = np.diff(closes[-60:]) / np.maximum(1e-9, closes[-60:-1])
            v60 = float(np.std(rets60))
        else:
            v60 = realized_vol
        # ATR%: (H-L)/C 14 均值
        hl_pcts = [(h - l) / max(1e-9, c) for h, l, c in zip(highs[-14:], lows[-14:], closes[-14:])]
        atr_pct = float(np.mean(hl_pcts)) if hl_pcts else 0.02
        atr_z = 0.0  # 训练中暂用 0，真实接入由 v15_trader 提供
        vol_z = float(np.clip((realized_vol - 0.02) / max(1e-9, 0.015), -3.0, 3.0)) if realized_vol > 0 else 0.0
        btc_corr = 0.80  # 训练简化：视为高度相关
        btc_rsi = _rsi_ema(closes, 14) / 100.0
        swing_daily = 2.0
        swing_4h = 3.0

        # ── 历史表现 3 维 ──
        if len(self.trade_history) >= 10:
            recent = self.trade_history[-10:]
            wins = sum(1 for t in recent if t.get("pnl_pct", 0) > 0)
            win_rate = wins / 10.0
            avg_pnl = sum(t.get("pnl_pct", 0) for t in recent) / 10.0
        elif self.trade_history:
            wins = sum(1 for t in self.trade_history if t.get("pnl_pct", 0) > 0)
            win_rate = wins / max(1, len(self.trade_history))
            avg_pnl = sum(t.get("pnl_pct", 0) for t in self.trade_history) / max(1, len(self.trade_history))
        else:
            win_rate = 0.5
            avg_pnl = 0.0
        # mdd_30：近似用 closes[-60:] 的 drawdown
        if len(closes) >= 2:
            peak = closes[-1]
            mdd = 0.0
            for c in reversed(closes[-60:]):
                peak = max(peak, c)
                mdd = min(mdd, (c - peak) / max(1e-9, peak))
            mdd_30 = abs(mdd)
        else:
            mdd_30 = 0.0

        obs = np.array([
            timing_score, structure_score, retrace_score, extension_score,
            regime_3hot[0], regime_3hot[1], regime_3hot[2],
            long_enabled, short_enabled,
            *regime_zone_5hot,
            *level_5hot,
            avg_entry_diff, unrealized, dist_to_liq, 0.0,
            atr_pct, atr_z, realized_vol, vol_z,
            btc_corr, btc_rsi, swing_daily, swing_4h,
            win_rate, avg_pnl, mdd_30,
        ], dtype=np.float32)
        assert obs.shape == (34,), f"obs shape {obs.shape} != (34,)"
        return obs

    # ── Step: 引入真实开仓逻辑 ──
    def step(self, action: Dict[str, Any]) -> Tuple[np.ndarray, float, bool, Dict]:
        i = self.current_step
        reward = 0.0
        info: Dict[str, Any] = {"step": i, "shield_flags": []}
        k_curr = self.klines[i]
        closes = [x["c"] for x in self.klines[: i + 1]]
        last = closes[-1]
        ma20 = _sma(closes, 20)
        ma60 = _sma(closes, 60)

        # ── 开仓：position is None 时基于 MA20 + RSI 概率开 LONG ──
        if self.position is None:
            self._steps_since_closed += 1
            # v15-like 信号：price 在 [ma60, ma60*1.02] 区间（接近支撑/企稳）且 RSI<55 → 3% 概率开仓
            rsi = _rsi_ema(closes, 14)
            ma_zone = (ma60 * 0.98) <= last <= (ma60 * 1.04)
            cooldown = self._steps_since_closed >= 4
            # 提高基础开仓概率，使 episode 内至少有几单
            p_open = 0.06 if (ma_zone and rsi < 60 and cooldown) else 0.02
            # 应用 base_position_mult：> 1.2 → 更激进（提概率）；< 0.8 → 更保守（降概率）
            bp_mult = float(action.get("base_position_mult", 1.0))
            p_open = float(np.clip(p_open * bp_mult, 0.0, 0.25))
            if self._rng.random() < p_open:
                # 开多单
                budget = self.initial_capital * 0.0022 * bp_mult  # 约 22U
                budget = max(1.0, min(self.capital * 0.10, budget))  # shield：单次不超过 10% 资金
                base_addon_pct_default = 0.08 * float(action.get("addon_pct_mult", 1.0))
                base_tp_default = 0.04 * float(action.get("tp_pct_mult", 1.0))
                self.position = {
                    "direction": "LONG",
                    "current_level": 0,
                    "avg_entry": last,
                    "base_entry": last,
                    "total_qty": budget / max(1e-9, last),
                    "total_deployed": budget,
                    "tp_pct": max(0.005, base_tp_default * 100),  # 百分比形式
                    "addon_pct": max(0.01, base_addon_pct_default * 100),  # 百分比形式
                    "opened_at_step": i,
                }
                self._steps_since_closed = 0
                reward += REWARD_OPEN_TRADE

        # ── 推进一步 ──
        self.current_step += 1
        done = self.current_step >= len(self.klines) - 1
        if self.current_step < len(self.klines):
            k = self.klines[self.current_step]
        else:
            k = self.klines[-1]

        # ── 持仓生命周期事件（TP / addon / bust） ──
        if self.position:
            pos = self.position
            level = int(pos.get("current_level", 0))
            entry = float(pos.get("avg_entry", k["c"]))
            direction = str(pos.get("direction", "LONG"))

            # TP 判定（按高价触及）
            tp_pct = float(pos.get("tp_pct", 4.0)) / 100.0
            if direction == "LONG" and k["h"] >= entry * (1 + tp_pct):
                # TP：按均价 * tp_pct 计算 PnL
                pnl_pct = tp_pct
                deployed = float(pos.get("total_deployed", 0.0))
                pnl_usd = deployed * pnl_pct
                self.capital += pnl_usd
                self.trade_history.append({
                    "pnl_usd": pnl_usd, "pnl_pct": pnl_pct * 100,
                    "exit_reason": "take_profit", "level": level,
                })
                reward += REWARD_TP_FULL * (1 + 0.1 * level)  # 深度加仓后 TP 奖励更高
                reward += REWARD_PNL_SCALE * pnl_usd  # v3-D: PnL 直接乘入
                self.position = None
                self._steps_since_closed = 0
            elif direction == "SHORT" and k["l"] <= entry * (1 - tp_pct):
                deployed = float(pos.get("total_deployed", 0.0))
                pnl_pct = tp_pct
                pnl_usd = deployed * pnl_pct
                self.capital += pnl_usd
                self.trade_history.append({
                    "pnl_usd": pnl_usd, "pnl_pct": pnl_pct * 100,
                    "exit_reason": "take_profit", "level": level,
                })
                reward += REWARD_TP_FULL
                reward += REWARD_PNL_SCALE * pnl_usd  # v3-D: PnL 直接乘入
                self.position = None
                self._steps_since_closed = 0
            else:
                # 资金占用惩罚（按步）
                deployed = float(pos.get("total_deployed", 0.0))
                if deployed > 0 and self.capital > 0:
                    reward += REWARD_CAPITAL_OCCUPANCY * (deployed / max(1e-9, self.capital))

                # 加仓：按 addon_pct_mult 调整的档位向下触达
                eff_max = self.max_addons + int(action.get("max_addons_delta", 0))
                eff_max = max(0, min(self.max_addons + 2, eff_max))
                addon_pct_pct = float(pos.get("addon_pct", 8.0)) / 100.0
                # addon_size_mult：预算缩放
                asz_mult = float(action.get("addon_size_mult", 1.0))
                base_budgets = (5.0, 10.0, 20.0, 35.0, 60.0)
                while True:
                    next_level = level + 1
                    if next_level > eff_max or next_level >= self.max_addons + 2:
                        break
                    addon_price_down = entry * (1 - addon_pct_pct * next_level)
                    triggered = direction == "LONG" and k["l"] <= addon_price_down
                    if not triggered:
                        break
                    bud = base_budgets[min(next_level - 1, len(base_budgets) - 1)] * asz_mult
                    bud = min(self.capital * 0.15, bud)  # shield：单次加仓不超过 15%
                    if bud <= 0:
                        break
                    fill = addon_price_down
                    qty_add = bud / max(1e-9, fill)
                    prev_cost = float(pos.get("total_deployed", 0.0))
                    prev_qty = float(pos.get("total_qty", 0.0))
                    new_cost = prev_cost + bud
                    new_qty = prev_qty + qty_add
                    pos["avg_entry"] = (pos["avg_entry"] * prev_qty + fill * qty_add) / max(1e-9, new_qty)
                    pos["total_deployed"] = new_cost
                    pos["total_qty"] = new_qty
                    pos["current_level"] = next_level
                    # TP 随均价重算（马丁 TP 按均价）
                    pos["tp_pct"] = (0.04 * float(action.get("tp_pct_mult", 1.0))) * 100
                    level = next_level
                    reward += REWARD_ADDON_LEVEL * next_level

                # bust 判定：满档 max_addons 且回撤≥20% → bust
                if level >= self.max_addons:
                    liq_frac = 0.20
                    if direction == "LONG" and k["c"] <= entry * (1 - liq_frac):
                        deployed = float(pos.get("total_deployed", 0.0))
                        loss = deployed * liq_frac
                        self.capital = max(0.0, self.capital - loss)
                        self.trade_history.append({
                            "pnl_usd": -loss, "pnl_pct": -liq_frac * 100,
                            "exit_reason": "bust", "level": level,
                        })
                        reward += REWARD_BUST
                        reward += REWARD_PNL_SCALE * (-loss)  # v3-D: 负 PnL 乘入
                        self.position = None
                        self._steps_since_closed = 0
                    elif direction == "SHORT" and k["c"] >= entry * (1 + liq_frac):
                        deployed = float(pos.get("total_deployed", 0.0))
                        loss = deployed * liq_frac
                        self.capital = max(0.0, self.capital - loss)
                        self.trade_history.append({
                            "pnl_usd": -loss, "pnl_pct": -liq_frac * 100,
                            "exit_reason": "bust", "level": level,
                        })
                        reward += REWARD_BUST
                        reward += REWARD_PNL_SCALE * (-loss)  # v3-D: 负 PnL 乘入
                        self.position = None
                        self._steps_since_closed = 0

            # episode 结束且仍有持仓：按收盘价强平，无额外惩罚，记录 pnl
            if done and self.position:
                pos2 = self.position
                entry2 = float(pos2.get("avg_entry", k["c"]))
                deployed2 = float(pos2.get("total_deployed", 0.0))
                frac = (k["c"] - entry2) / max(1e-9, entry2)
                pnl_usd = deployed2 * frac
                self.capital = max(0.0, self.capital + pnl_usd)
                self.trade_history.append({
                    "pnl_usd": pnl_usd, "pnl_pct": frac * 100,
                    "exit_reason": "eod_close", "level": int(pos2.get("current_level", 0)),
                })
                reward += REWARD_PNL_SCALE * pnl_usd  # v3-D: EOD 强平也计入 PnL
                self.position = None

        # ── DS 盾（简化） ──
        if self.use_shield:
            for kk in ["addon_size_mult", "base_position_mult"]:
                if abs(float(action.get(kk, 1.0)) - 1.0) > 0.75:  # > 1.75 或 < 0.25
                    reward += REWARD_SHIELD_VIOLATION
                    self.shield_violations += 1
                    info["shield_flags"].append(kk)

        self.total_reward += reward
        info["capital"] = float(self.capital)
        info["total_reward"] = float(self.total_reward)
        info["n_trades"] = len(self.trade_history)

        obs = self._get_obs()
        return obs, float(reward), bool(done), info

    # ── 兼容：返回 dict 形式状态（供 PhaseEGateway 使用） ──
    def get_s_state_dict(self) -> Dict[str, Any]:
        obs = self._get_obs()
        return {
            "timing_score": float(obs[0]),
            "structure_match_score": float(obs[1]),
            "retrace_quality_score": float(obs[2]),
            "extension_chase_score": float(obs[3]),
            "regime": "ACCUM",
            "long_enabled": float(obs[7]) > 0.5,
            "short_enabled": float(obs[8]) > 0.5,
            "btc_windvane_strength": 0.5,
            "regime_zone": 2,
            "days_in_current_zone": 10,
            "position_level": int(self.position["current_level"]) if self.position else 0,
            "avg_entry_price_pct_diff": float(obs[20]),
            "unrealized_pnl_ratio": float(obs[21]),
            "distance_to_liq_ratio": float(obs[22]),
            "atr_14_pct": float(obs[24]),
            "atr_14_zscore_30": float(obs[25]),
            "realized_vol_30d": float(obs[26]),
            "vol_zscore_60": float(obs[27]),
            "btc_corr_30d": float(obs[28]),
            "btc_rsi_14": float(obs[29]) * 100.0,
            "swing_window_daily": float(obs[30]),
            "swing_window_4h": float(obs[31]),
            "recent_10_win_rate": float(obs[32]),
            "recent_10_avg_pnl_ratio": float(obs[33]),
            "max_drawdown_30d": 0.05,
            "account_margin_ratio": 0.10,
            "imr": 0.05,
            "coin_total_deployed": float(self.position["total_deployed"]) if self.position else 0.0,
        }
