"""Phase E: PPO-LSTM 强化学习闸门 + 确定性风控盾

路线图 §5 Phase E 核心模块。封装 PPO policy 推理 → 5 维动作 → §3.3 边界 clamp →
§5.2 DS1-DS6 确定性风控盾 → 最终生效动作。

设计原则（与 PhaseDGateway 一致）：
- enabled=False 时所有方法返回基线原值（铁律 1 字节级等价）
- MVP 桥接模式：_mock_action 支持测试注入，真实 PPO 权重加载后替换
- K_bound 初始 0.80（§5.3 Phase E 从收紧起跑）
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# ── §3.3 动作空间默认边界（LOWER / UPPER 相对倍率） ──
ACTION_BOUNDS = {
    "addon_pct_mult":      {"lo": 0.80, "hi": 1.30, "abs_lo": 0.375, "abs_hi": 3.125},   # 绝对: addon_pct∈[3%,25%] / base 8%
    "addon_size_mult":     {"lo": 0.60, "hi": 1.50, "abs_lo": 0.60, "abs_hi": 1.50},
    "tp_pct_mult":         {"lo": 0.80, "hi": 1.30, "abs_lo": 0.375, "abs_hi": 3.00},      # 绝对: tp∈[1.5%,12%] / base 4%
    "base_position_mult":  {"lo": 0.70, "hi": 1.20, "abs_lo": 0.50, "abs_hi": 2.00},       # 绝对: pct∈[5%,40%] / base 22%
    "max_addons_delta":    {"lo": -1,   "hi": 0,    "abs_lo": -1,   "abs_hi": 0},          # 只可缩档
}

# §3.3 铁壳：总加仓预算不超过原 ×1.10
TOTAL_BUDGET_CEIL_MULT = 1.10

# §5.3 Phase E K_bound 起始
PHASE_E_DEFAULT_K_BOUND = 0.80


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _apply_k_bound_to_bounds(lo: float, hi: float, k_bound: float) -> Tuple[float, float]:
    """§3.4 K_bound 缩放边界。
    K_bound > 1 → LOWER 更靠近 1（更宽），UPPER 更远离 1（更宽）
    K_bound < 1 → LOWER 更远离 1（更紧），UPPER 更靠近 1（更紧）
    """
    if k_bound <= 0:
        k_bound = 0.50
    # LOWER: 1 - (1 - lo) / k_bound  （k_bound > 1 时 lo_eff 更靠近 1）
    if lo < 1.0:
        lo_eff = 1.0 - (1.0 - lo) / k_bound
    else:
        lo_eff = lo
    # UPPER: 1 + (hi - 1) * k_bound
    if hi > 1.0:
        hi_eff = 1.0 + (hi - 1.0) * k_bound
    else:
        hi_eff = hi
    return lo_eff, hi_eff


@dataclass
class PhaseEGateway:
    """PPO-LSTM 策略推理 + 确定性风控盾。

    核心方法:
        get_action(s_state) → 5 维动作 dict（已 clamp 边界，未过盾）
        shield_check(action, s_state, alloc, params) → 盾后动作 dict + shield_flags
        apply_size_multipliers(alloc, s_state) → 最终 allocation dict
        apply_param_multipliers(coin, params, s_state) → 最终 params dict
        write_decision_jsonl(record) → 决策归档（PhaseE_decisions.jsonl）
    """

    enabled: bool = False
    ppo_model_path: Optional[str] = None
    k_bound: float = PHASE_E_DEFAULT_K_BOUND
    # §5.2 DS 盾开关（生产不可关，测试可关）
    shield_enabled: bool = True
    # 归档 JSONL 路径：None 时使用默认路径 <project>/data/ai_logs/phase_e_decisions.jsonl
    jsonl_log_path: Optional[str] = None

    # TDD 诊断
    last_shield_flags: list = field(default_factory=list, repr=False)
    _mock_action: Optional[Dict[str, Any]] = field(default=None, repr=False)
    _ppo_model: Any = field(default=None, repr=False)
    _jsonl_fh: Any = field(default=None, repr=False)

    def __post_init__(self):
        # 归档文件：若显式传路径用显式；否则用 PROJECT/data/ai_logs（懒打开，write_decision_jsonl 里开）
        if self.jsonl_log_path is None:
            default_dir = Path(__file__).resolve().parent.parent / "data" / "ai_logs"
            self.jsonl_log_path = str(default_dir / "phase_e_decisions.jsonl")

        if self.enabled and self.ppo_model_path and os.path.isfile(self.ppo_model_path):
            try:
                self._load_ppo_model()
            except Exception:
                pass  # 加载失败 → 降级为中性动作

    def _ensure_jsonl_open(self):
        """懒打开 JSONL 文件句柄（append，line-buffered）。失败则 self._jsonl_fh=None 继续。"""
        if self._jsonl_fh is not None:
            return
        try:
            p = Path(self.jsonl_log_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._jsonl_fh = open(p, "a", encoding="utf-8", buffering=1)
        except Exception:
            self._jsonl_fh = None

    def write_decision_jsonl(self, record: Dict[str, Any]) -> None:
        """Point4c: PhaseEGateway 推理决策归档写入 JSONL（可复现 & 事后回溯）。

        record 推荐包含：
            ts_iso, coin, s_state, inference_action, shield_action,
            final_addon_pct, final_tp_pct, k_bound, ppo_model_path
        """
        if not self.enabled:
            return
        self._ensure_jsonl_open()
        if self._jsonl_fh is None:
            return
        try:
            from datetime import datetime, timezone

            data = dict(record)
            data.setdefault("ts_iso", datetime.now(timezone.utc).isoformat())
            data.setdefault("k_bound", self.k_bound)
            data.setdefault("ppo_model_path", self.ppo_model_path)
            line = json.dumps(data, ensure_ascii=False, default=str)
            self._jsonl_fh.write(line + "\n")
        except Exception:
            # 归档失败绝不影响主交易：吞掉异常（可能是磁盘满/权限等）
            pass

    def close(self) -> None:
        """显式关闭 JSONL 文件句柄。"""
        try:
            if self._jsonl_fh is not None:
                self._jsonl_fh.close()
        except Exception:
            pass
        finally:
            self._jsonl_fh = None

    def _load_ppo_model(self):
        """加载 PPO-LSTM 权重，构造 PPOLSTMActorCritic 模型。

        v6: 从 checkpoint 读取 action_bounds 传给模型，保证推理时
        map_action_to_bounds 用训练时一致的边界。
        旧版 checkpoint 无 action_bounds → 用模型默认 DEFAULT_ACTION_BOUNDS。
        """
        import torch

        ai_trainers_path = str(Path(__file__).resolve().parent.parent / "ai_trainers")
        if ai_trainers_path not in sys.path:
            sys.path.insert(0, ai_trainers_path)
        from phase_e_models import PPOLSTMActorCritic

        payload = torch.load(self.ppo_model_path, map_location="cpu", weights_only=False)
        config = payload.get("config", {})
        action_bounds = payload.get("action_bounds")  # v6: None 时模型用默认边界
        model = PPOLSTMActorCritic(
            state_dim=34,
            hidden_dim=config.get("hidden_dim", 128),
            num_layers=config.get("num_layers", 1),
            action_bounds=action_bounds,
        )
        model.load_state_dict(payload["model_state_dict"])
        model.eval()
        self._ppo_model = model

    @staticmethod
    def _build_state_vector(s_state: Dict[str, Any]) -> "Any":
        """将 s_state dict 转为 34 维 numpy float32 向量（对齐 v15_gym_env.STATE_KEYS）。

        训练环境 _get_obs() 的 34 维定义：
          TimingGate(4) + DirectionGate(5: regime_3hot + long/short) +
          RegimeManager(5: zone_5hot) + 持仓(9: level_5hot + 4标量) +
          波动(8) + 历史表现(3)
        """
        import numpy as np

        # TimingGate (4)
        timing_score = float(s_state.get("timing_score", 0.5))
        structure = float(s_state.get("structure_match_score", 0.5))
        retrace = float(s_state.get("retrace_quality_score", 0.5))
        extension = float(s_state.get("extension_chase_score", 0.5))

        # DirectionGate (5): regime 3hot + long_enabled + short_enabled
        regime = str(s_state.get("regime", "ACCUM")).upper()
        if regime == "ACCUM":
            r3 = [1.0, 0.0, 0.0]
        elif regime == "UP":
            r3 = [0.0, 1.0, 0.0]
        elif regime == "DOWN":
            r3 = [0.0, 0.0, 1.0]
        else:
            r3 = [0.0, 0.0, 0.0]
        long_en = 1.0 if s_state.get("long_enabled", True) else 0.0
        short_en = 1.0 if s_state.get("short_enabled", False) else 0.0

        # RegimeManager (5): zone 5hot
        zone = int(s_state.get("regime_zone", 2))
        z5 = [0.0] * 5
        if 0 <= zone < 5:
            z5[zone] = 1.0

        # 持仓 (9): level 5hot + 4 标量
        level = int(s_state.get("position_level", 0))
        l5 = [0.0] * 5
        if 0 <= level < 5:
            l5[level] = 1.0
        avg_entry_diff = float(s_state.get("avg_entry_price_pct_diff", 0.0))
        unrealized = float(s_state.get("unrealized_pnl_ratio", 0.0))
        dist_liq = float(s_state.get("distance_to_liq_ratio", 0.80))
        unused_9 = 0.0

        # 波动 (8)
        atr_pct = float(s_state.get("atr_14_pct", 0.03))
        atr_z = float(s_state.get("atr_14_zscore_30", 0.0))
        realized_vol = float(s_state.get("realized_vol_30d", 0.04))
        vol_z = float(s_state.get("vol_zscore_60", 0.0))
        btc_corr = float(s_state.get("btc_corr_30d", 0.8))
        btc_rsi = float(s_state.get("btc_rsi_14", 50.0)) / 100.0
        swing_d = float(s_state.get("swing_window_daily", 2))
        swing_4h = float(s_state.get("swing_window_4h", 3))

        # 历史表现 (3)
        win_rate = float(s_state.get("recent_10_win_rate", 0.5))
        avg_pnl = float(s_state.get("recent_10_avg_pnl_ratio", 0.0))
        mdd = float(s_state.get("max_drawdown_30d", 0.05))

        obs = np.array([
            timing_score, structure, retrace, extension,
            r3[0], r3[1], r3[2], long_en, short_en,
            z5[0], z5[1], z5[2], z5[3], z5[4],
            l5[0], l5[1], l5[2], l5[3], l5[4],
            avg_entry_diff, unrealized, dist_liq, unused_9,
            atr_pct, atr_z, realized_vol, vol_z,
            btc_corr, btc_rsi, swing_d, swing_4h,
            win_rate, avg_pnl, mdd,
        ], dtype=np.float32)
        return obs

    # ── 核心：PPO 推理 → 5 维动作 ──

    def _infer_action(self, s_state: Dict[str, Any]) -> Dict[str, Any]:
        """PPO policy 推理，返回原始 5 维动作。"""
        if self._mock_action is not None:
            return dict(self._mock_action)
        # 真实模型推理
        if self._ppo_model is not None:
            try:
                import torch
                obs = self._build_state_vector(s_state)  # (34,)
                x = torch.from_numpy(obs).unsqueeze(0).unsqueeze(0)  # (1, 1, 34)
                return self._ppo_model.get_action_dict(x)
            except Exception:
                pass  # 推理失败 → 降级中性
        # 无模型时返回中性动作（=基线）
        return {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.0,
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }

    def _clamp_action(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """§3.3 + §3.4 双层 clamp：先 K_bound 相对边界，再宽安全网。
        绝对值铁壳（addon_pct∈[3%,25%] 等）由 DS3/DS4 盾在 shield_check 中检查。"""
        clamped = {}
        for key, bounds in ACTION_BOUNDS.items():
            val = raw.get(key, 1.0 if key != "max_addons_delta" else 0)
            if key == "max_addons_delta":
                clamped[key] = int(max(bounds["abs_lo"], min(bounds["abs_hi"], int(val))))
                continue

            lo_eff, hi_eff = _apply_k_bound_to_bounds(bounds["lo"], bounds["hi"], self.k_bound)
            # 相对边界 clamp
            val = _clamp(float(val), lo_eff, hi_eff)
            # 宽安全网（防止极端值，但不干涉 DS 盾的绝对值检查）
            val = _clamp(val, 0.01, 100.0)
            clamped[key] = val
        return clamped

    def get_action(self, s_state: Dict[str, Any]) -> Dict[str, Any]:
        """返回已 clamp 边界的 5 维动作（未过盾）。"""
        if not self.enabled:
            return {
                "addon_pct_mult": 1.0,
                "addon_size_mult": 1.0,
                "tp_pct_mult": 1.0,
                "base_position_mult": 1.0,
                "max_addons_delta": 0,
            }
        raw = self._infer_action(s_state)
        return self._clamp_action(raw)

    # ── §5.2 确定性风控盾 ──

    def shield_check(
        self,
        action: Dict[str, Any],
        s_state: Dict[str, Any],
        allocation: Dict[str, Any],
        base_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """DS1-DS6 六盾检查，返回盾后动作 + shield_flags 列表。"""
        if not self.enabled or not self.shield_enabled:
            action = dict(action)
            action["shield_flags"] = []
            return action

        shielded = dict(action)
        flags = []

        # ── DS1: 总保证金率安全 ──
        margin_ratio = float(s_state.get("account_margin_ratio", 0.0))
        imr = float(s_state.get("imr", 0.05))
        margin_ceil = (imr + 0.02) * 1.50
        if margin_ratio > margin_ceil:
            if shielded["addon_size_mult"] > 1.0:
                shielded["addon_size_mult"] = 1.0
                flags.append("DS1")
            shielded["max_addons_delta"] = min(shielded["max_addons_delta"], -1)
            if "DS1" not in flags:
                flags.append("DS1")

        # ── DS2: 单币种投入上限 ──
        coin_deployed = float(s_state.get("coin_total_deployed", 0.0))
        per_coin_budget = float(allocation.get("per_coin_budget", 0.0))
        if per_coin_budget > 0 and coin_deployed > per_coin_budget * TOTAL_BUDGET_CEIL_MULT:
            if shielded["addon_size_mult"] > 1.0:
                shielded["addon_size_mult"] = 1.0
            if shielded["base_position_mult"] > 1.0:
                shielded["base_position_mult"] = 1.0
            flags.append("DS2")

        # ── DS3: TP 绝对值 ──
        base_tp = float(base_params.get("tp_pct", 4.0))
        eff_tp = base_tp * shielded["tp_pct_mult"]
        if eff_tp < 1.5:
            shielded["tp_pct_mult"] = 1.5 / base_tp if base_tp > 0 else 1.0
            flags.append("DS3")
        elif eff_tp > 12.0:
            shielded["tp_pct_mult"] = 12.0 / base_tp if base_tp > 0 else 1.0
            flags.append("DS3")

        # ── DS4: addon_pct 绝对值 ──
        base_addon = float(base_params.get("addon_pct", 8.0))
        eff_addon = base_addon * shielded["addon_pct_mult"]
        if eff_addon < 3.0:
            shielded["addon_pct_mult"] = 3.0 / base_addon if base_addon > 0 else 1.0
            flags.append("DS4")
        elif eff_addon > 25.0:
            shielded["addon_pct_mult"] = 25.0 / base_addon if base_addon > 0 else 1.0
            flags.append("DS4")

        # ── DS5: 极端行情禁放大 ──
        vol_z = float(s_state.get("vol_zscore_60", 0.0))
        if vol_z > 2.5:
            for k in ["addon_pct_mult", "addon_size_mult", "tp_pct_mult", "base_position_mult"]:
                if shielded[k] > 1.0:
                    shielded[k] = 1.0
            flags.append("DS5")

        # ── DS6: 连亏熔断 ──
        win_rate = float(s_state.get("recent_10_win_rate", 0.5))
        trade_count = int(s_state.get("recent_10_count", 0))
        if win_rate < 0.20 and trade_count >= 10:
            if shielded["max_addons_delta"] != -1:
                shielded["max_addons_delta"] = -1
                flags.append("DS6")

        shielded["shield_flags"] = flags
        self.last_shield_flags = flags
        return shielded

    # ── 整合 API ──

    def apply_size_multipliers(
        self,
        allocation: Dict[str, Any],
        s_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """应用动作到 allocation dict（含盾 + 总预算 clamp）。"""
        if not self.enabled:
            return dict(allocation)

        action = self.get_action(s_state)
        action = self.shield_check(action, s_state, allocation, {"tp_pct": 4.0, "addon_pct": 8.0})

        result = dict(allocation)
        base_mult = action["base_position_mult"]
        size_mult = action["addon_size_mult"]
        max_addons_delta = action["max_addons_delta"]

        # 应用倍率
        result["base_usd"] = round(allocation.get("base_usd", 0) * base_mult, 2)
        for k in [1, 2, 3, 4]:
            key = f"addon{k}_usd"
            result[key] = round(allocation.get(key, 0) * size_mult, 2)

        # max_addons_delta=-1 → 最深档清零
        if max_addons_delta == -1:
            result["addon4_usd"] = 0.0

        # §3.3 铁壳：总预算 ≤ 原 × 1.10
        original_total = float(allocation.get("total_usd", 0))
        if original_total > 0:
            current_total = (
                result["base_usd"]
                + result["addon1_usd"]
                + result["addon2_usd"]
                + result["addon3_usd"]
                + result["addon4_usd"]
            )
            ceil = original_total * TOTAL_BUDGET_CEIL_MULT
            if current_total > ceil:
                # 按比例缩减
                ratio = ceil / current_total
                result["base_usd"] = round(result["base_usd"] * ratio, 2)
                for k in [1, 2, 3, 4]:
                    key = f"addon{k}_usd"
                    result[key] = round(result[key] * ratio, 2)

        result["total_usd"] = round(
            result["base_usd"]
            + result["addon1_usd"]
            + result["addon2_usd"]
            + result["addon3_usd"]
            + result["addon4_usd"],
            2,
        )
        result["ai_action"] = action
        return result

    def apply_param_multipliers(
        self,
        coin: str,
        base_params: Dict[str, Any],
        s_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """应用动作到 strategy params（addon_pct / tp_pct）。

        v2 Point4c: 每次调用都尝试 write_decision_jsonl 归档（可复现 & 事后回溯）。
        """
        if not self.enabled:
            return dict(base_params)

        action_raw = self.get_action(s_state)
        # 盾检查需要 allocation（用空 dict 占位，DS1/DS2 不依赖 params）
        action = self.shield_check(action_raw, s_state, {"per_coin_budget": 0}, base_params)

        result = dict(base_params)
        base_addon = float(base_params.get("addon_pct", 8.0))
        base_tp = float(base_params.get("tp_pct", 4.0))

        eff_addon = round(base_addon * action["addon_pct_mult"], 2)
        eff_tp = round(base_tp * action["tp_pct_mult"], 2)
        result["addon_pct"] = eff_addon
        result["tp_pct"] = eff_tp
        result["ai_action"] = action

        # Point4c: 决策归档
        try:
            self.write_decision_jsonl({
                "coin": coin,
                "s_state": s_state,
                "inference_action": action_raw,
                "shield_action": action,
                "base_addon_pct": base_addon,
                "base_tp_pct": base_tp,
                "final_addon_pct": eff_addon,
                "final_tp_pct": eff_tp,
                "shield_flags": action.get("shield_flags", []),
            })
        except Exception:
            pass
        return result
