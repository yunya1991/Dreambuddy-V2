"""ParameterMapper · 方案 A：Level-Trend 纯连续函数映射

Spec 映射关系：
  【Layer 0 全局 BTC 形态】
    (L∈[-4,4], T∈[-4,4], C∈[0,1])  →  6 个全局范围参数（中心 + 带宽随 C 收窄）
      • global_position_mult   — 全局仓位乘数
      • ls_ratio_cap           — 多空持仓比上限
      • long_bias              — 多头偏置（加性）
      • short_bias             — 空头偏置（加性）
      • long_threshold_mult    — 多头开仓阈值乘数
      • short_threshold_mult   — 空头开仓阈值乘数

  【Layer 1 板块龙头形态】
    (L, T, C) + 5 板块 (β, α, corr)  →  5 板块资金权重 Σ=1
      • DeFi / AI / RWA / MEME / L2

  【核心不变量 · 三层兼容】
    L=0, T=0, C=0 时：
      • 6 参数中心 ≡ 直通默认值（mult=1.0，ls_cap=0.5，bias=0，threshold_mult=1.0）
      • 5 板块权重 ≡ 均匀 0.20 / 板块
    → 前置层「无偏/无共识」等价于 identity，不干扰 BCRM + 弹簧力场原链路。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


# ============================================================
# Phase C: α blend 超参（前瞻参数上线）
# 默认全关，ALPHA_BLEND_ENABLED=False 且 DEFAULT_ALPHA_BLEND=0.0 时字节等价 Phase 0
# ============================================================
ALPHA_BLEND_ENABLED: bool = True         # Phase C 总开关（已开启，alpha=0.0 仍字节等价）
DEFAULT_ALPHA_BLEND: float = 0.0         # 默认 α 值（0=纯反应式）
ALPHA_BLEND_MAX: float = 0.5             # α 上限（project_memory 硬约束）
ALPHA_BLEND_STEP: float = 0.1            # 渐进步长


# ============================================================
# 6 参数的「base + w_L + w_T + clip 边界」
# 系数来源：Spec §方案 A Level-Trend 纯连续函数 + project_memory
# ============================================================
@dataclass(frozen=True)
class _RangeSpec:
    base: float          # L=0, T=0 时的中心
    w_L: float           # × L_norm（L/4 ∈ [-1, 1]）
    w_T: float           # × T_norm（T/4 ∈ [-1, 1]）
    clip_lo: float       # 中心最低
    clip_hi: float       # 中心最高
    base_width: float    # C=0 时的带宽（lo↔hi 全宽）
    width_at_C1: float   # C=1 时的带宽（共识最高 → 最窄）


_PARAM_SPECS: Dict[str, _RangeSpec] = {
    #            base    w_L     w_T     clip    base_w   w@C1
    "global_position_mult":  _RangeSpec(1.0,  0.40,  0.20,  0.30, 1.60, 0.80, 0.20),
    "ls_ratio_cap":          _RangeSpec(0.5,  0.25,  0.15,  0.20, 1.00, 0.40, 0.10),
    "long_bias":             _RangeSpec(0.0,  0.15,  0.10, -0.30, 0.30, 0.30, 0.08),
    "short_bias":            _RangeSpec(0.0, -0.15, -0.10, -0.30, 0.30, 0.30, 0.08),
    # 牛市(L高T高) → long_threshold_mult 中心下降 → 降低做多门槛 ✅T12(4)
    "long_threshold_mult":   _RangeSpec(1.0, -0.10, -0.15,  0.70, 1.50, 0.40, 0.10),
    # 熊市(L低T低) → short_threshold_mult 中心下降 → 降低做空门槛 ✅T12(4)
    #   注意：与 long_threshold_mult 相反，short 的 w_L/w_T 为正，
    #   当 L_norm/T_norm < 0 时中心 < 1.0（放宽做空），> 0 时中心 > 1.0（牛市抑制做空）
    "short_threshold_mult":  _RangeSpec(1.0,  0.10,  0.15,  0.70, 1.50, 0.40, 0.10),
}

SECTOR_NAMES = ("defi", "ai", "rwa", "meme", "l2")
_N_SECTORS = len(SECTOR_NAMES)
_UNIFORM_WEIGHT = 1.0 / _N_SECTORS

# ============================================================
# REGIME_BASE_PARAMS: 6 全局参数的基线（identity / 中性值）
# 来源：_PARAM_SPECS[*].base（L=0, T=0 时的中心值）
# 用途：polling_trader 融合层和 ShadowLogger 的 regime_baselines 兜底
# ============================================================
REGIME_BASE_PARAMS: Dict[str, float] = {
    name: spec.base for name, spec in _PARAM_SPECS.items()
}


# ============================================================
# Utility：clip 连续值
# ============================================================
def _clip(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


class ParameterMapper:
    """方案 A 纯连续函数映射 —— 不依赖查表，完全可微、连续。

    用法：
        pm = ParameterMapper()
        rng = pm.map_global_parameters(L, T, C, stats_row=...)   # Dict[str, (lo,hi)]
        w   = pm.map_sector_weights(L, T, C, sector_betas=...)   # Dict[str, float∈(0,1)]
    """

    # 类级暴露 REGIME_BASE_PARAMS（供 polling_trader getattr 兜底）
    REGIME_BASE_PARAMS = REGIME_BASE_PARAMS

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _center(spec: _RangeSpec, L_norm: float, T_norm: float) -> float:
        c = spec.base + spec.w_L * L_norm + spec.w_T * T_norm
        return _clip(c, spec.clip_lo, spec.clip_hi)

    @staticmethod
    def _bandwidth(spec: _RangeSpec, C: float) -> float:
        """共识越高 → 带宽越窄（线性插值）。"""
        c = float(np.clip(C, 0.0, 1.0))
        return spec.width_at_C1 + (spec.base_width - spec.width_at_C1) * (1.0 - c)

    # ------------------------------------------------------------------ 全局 6 参数
    def map_global_parameters(
        self,
        L: float,
        T: float,
        C: float,
        stats_row: Dict[str, float] | None = None,
        forecast_L: float | None = None,
        forecast_T: float | None = None,
        alpha_blend: float = 0.0,
    ) -> Dict[str, Tuple[float, float]]:
        """输出 6 个全局参数的范围 [lo, hi] 元组。

        参数:
            L — Level Score ∈ [-4, 4]
            T — Trend Score ∈ [-4, 4]
            C — 共识度 ∈ [0, 1]，越高带宽越窄
            stats_row — （保留接口，当前未使用；未来滚动分位归一化锚点）
            forecast_L — Phase C 前瞻 L（来自 MorphCyclePredictor），None 时不 blend
            forecast_T — Phase C 前瞻 T，None 时不 blend
            alpha_blend — Phase C 混合权重 [0,1]，0=纯反应式（默认，字节等价）
        """
        del stats_row  # 预留，当前不用
        # Phase C: α blend（无偏不变量：alpha=0 或 forecast=None 时不改变 L/T）
        if alpha_blend != 0.0:
            alpha_blend = _clip(alpha_blend, 0.0, 1.0)
            if forecast_L is not None:
                L = (1.0 - alpha_blend) * L + alpha_blend * forecast_L
            if forecast_T is not None:
                T = (1.0 - alpha_blend) * T + alpha_blend * forecast_T
        L_norm = _clip(L / 4.0, -1.0, 1.0)
        T_norm = _clip(T / 4.0, -1.0, 1.0)

        out: Dict[str, Tuple[float, float]] = {}
        for name, spec in _PARAM_SPECS.items():
            center = self._center(spec, L_norm, T_norm)
            half = 0.5 * self._bandwidth(spec, C)
            lo = center - half
            hi = center + half
            # 防止数值舍入越界
            lo = max(spec.clip_lo - 1e-9, lo)
            hi = min(spec.clip_hi + 1e-9, hi)
            out[name] = (lo, hi)
        return out

    # ------------------------------------------------------------------ 5 板块权重：softmax((1-C)*uniform + C*score)
    def map_sector_weights(
        self,
        L: float,
        T: float,
        C: float,
        sector_betas: Dict[str, Tuple[float, float, float]],
        forecast_L: float | None = None,
        forecast_T: float | None = None,
        alpha_blend: float = 0.0,
    ) -> Dict[str, float]:
        """输出 5 板块权重 Σ=1，开区间 (0,1)。

        sector_betas 格式：
            {"defi": (beta_252d, alpha_60d_daily, corr_60d_with_btc), ...}

        核心：
            logit_i = (1 - C) * 0  +  C * (
                  w_β * (β_i - β_avg)
                + w_α * sign * (α_i * 252)     # α 年化后再加权，量级 ~ [±0.5]
                + w_corr * corr_i
            )
            weight_i = softmax(logit_i)

        Identity 不变量：
            C=0 → 所有 logit_i == 0 → softmax = 均匀 0.20 ✅

        Phase C: 支持 α blend（forecast_L/T 与 reactive L/T 混合）
        """
        # Phase C: α blend（无偏不变量：alpha=0 或 forecast=None 时不改变 L/T）
        if alpha_blend != 0.0:
            alpha_blend = _clip(alpha_blend, 0.0, 1.0)
            if forecast_L is not None:
                L = (1.0 - alpha_blend) * L + alpha_blend * forecast_L
            if forecast_T is not None:
                T = (1.0 - alpha_blend) * T + alpha_blend * forecast_T
        # 输入完整性校验
        if set(sector_betas.keys()) != set(SECTOR_NAMES):
            raise ValueError(
                f"sector_betas 必须恰好包含 {SECTOR_NAMES}，"
                f"实际={sorted(sector_betas.keys())}"
            )

        C_clamped = float(np.clip(C, 0.0, 1.0))
        # L 方向性：L>0 时正 α 加分，L<0 时负 α（空头贡献正收益）加分；|L|<0.5 视为中性 → 不看 α
        L_norm = _clip(L / 4.0, -1.0, 1.0)
        L_sign = 0.0
        if L_norm > 0.125:   # ~ L > 0.5
            L_sign = +1.0
        elif L_norm < -0.125:
            L_sign = -1.0

        # ---- 按统一顺序构造向量 ----
        betas_arr = np.zeros(_N_SECTORS, dtype=float)
        alphas_arr = np.zeros(_N_SECTORS, dtype=float)
        corrs_arr = np.zeros(_N_SECTORS, dtype=float)
        for i, name in enumerate(SECTOR_NAMES):
            b, a, c = sector_betas[name]
            betas_arr[i] = float(b)
            alphas_arr[i] = float(a)
            corrs_arr[i] = float(c)

        # ---- 权重系数 ----
        # 注意：量级刻意控制，避免 softmax 坍缩到 0/1（要保持 (0,1) 开区间）
        #   W_BETA  × β_rel   量级 ~ [±0.8]
        #   W_ALPHA × α×252   量级 ~ [±0.3×12.6] ≈ [±3.8]（α×252 年化约 ±12.6）
        #   W_CORR  × corr    量级 ~ [±0.3]
        # 合计单板块 score 量级 ~ [±4.4]，× C=0.8 → logits 差 ~ 6~7，
        #   softmax 后权重仍在 (0.001, 0.9) 开区间内，仍能满足 1.15 比率门槛。
        W_BETA: float = 0.5
        W_ALPHA: float = 0.3
        W_CORR: float = 0.3

        # β 相对均值的偏离（让高β和低β有自然对比）
        beta_center = betas_arr.mean()
        beta_rel = betas_arr - beta_center

        # α 年化（日α × 252），再乘方向性 L_sign
        alpha_annual = alphas_arr * 252.0 * L_sign

        score = (
            W_BETA * beta_rel
            + W_ALPHA * alpha_annual
            + W_CORR * corrs_arr
        )

        # Identity 不变量核心：(1 - C) * 均匀logit + C * score
        # 当 C=0 → logits = 全 0 → softmax 均匀 0.20 ✅
        logits = C_clamped * score

        # 数值稳定 softmax
        logits_shifted = logits - logits.max()
        exp_l = np.exp(logits_shifted)
        w_vec = exp_l / exp_l.sum()

        # 保证 Σ=1 的精确浮点修正
        w_vec = w_vec / w_vec.sum()

        weights = {name: float(w_vec[i]) for i, name in enumerate(SECTOR_NAMES)}

        # ========== T3 扩展：板块级 TP/SL 乘数 ==========
        # 按 L, T, C 推断「板块级形态」→ 映射到 8 态 → 查表得 TP/SL 乘数
        # 规则（与币种级 REGIME_MULTIPLIERS 单调一致）：
        #   TREND_UP / BREAKOUT → tp 高(≥1.15)，sl 保守(≤1.0)
        #   RANGE_BOUND → tp 低(≤0.9), sl 放大(≥1.15)
        #   BEAR / VOLATILE_DROP → tp 低 sl 高
        #   L=0,T=0 → identity 1.0
        regime_lvl = _clip(L / 4.0, -1.0, 1.0)  # [-1, 1]
        regime_trend = _clip(T / 4.0, -1.0, 1.0)
        # 综合得分 = (1-C)*identity + C*(0.6*lvl + 0.4*trend)
        composite = (1 - C_clamped) * 0.0 + C_clamped * (0.6 * regime_lvl + 0.4 * regime_trend)

        sector_tp_mult: dict[str, float] = {}
        sector_sl_mult: dict[str, float] = {}
        for i, name in enumerate(SECTOR_NAMES):
            # 板块差异叠加：每个板块按 β_rel 轻微调整（高β更激进）
            beta_bonus = _clip(beta_rel[i] * 0.1, -0.1, 0.1)

            # tp_mult：composite 高 → tp 高（看涨，止盈可以更远）
            # base: composite=-1 → 0.85, composite=0 → 1.0, composite=1 → 1.20
            tp_base = 1.0 + composite * 0.20
            sector_tp_mult[name] = round(float(np.clip(tp_base + beta_bonus, 0.70, 1.50)), 4)

            # sl_mult：composite 低 → sl 高（看跌，止损更宽）
            # base: composite=-1 → 1.30, composite=0 → 1.0, composite=1 → 0.85
            sl_base = 1.0 - composite * 0.22
            sector_sl_mult[name] = round(float(np.clip(sl_base - beta_bonus, 0.70, 1.60)), 4)

        # Identity 双重校验：L=0 且 T=0 且 C=0 → 所有板块 TP=1.0 SL=1.0
        if abs(L) < 1e-9 and abs(T) < 1e-9 and abs(C) < 1e-9:
            sector_tp_mult = {n: 1.0 for n in SECTOR_NAMES}
            sector_sl_mult = {n: 1.0 for n in SECTOR_NAMES}

        return {
            "weights": weights,
            "sector_tp_mult": sector_tp_mult,
            "sector_sl_mult": sector_sl_mult,
        }

    # ============================================================
    # 范围→单值插值：为核心层(polling_trader)提供可直接使用的单值
    # ============================================================
    def resolve_point_estimate(
        self,
        ranges: dict,
        stats_row: dict,
        forecast_L: float | None,
        forecast_T: float | None,
        alpha_blend: float,
        regime_baselines: dict[str, float],
    ) -> dict[str, float]:
        """将 map_global_parameters() 的 [lo, hi] 范围转换为单值。

        插值规则：
          (1) forecast_L 为空 or alpha=0 → 直接返回 regime_baselines（字节等价兜底）
          (2) norm_L = clip((forecast_L - level_lo)/(level_hi - level_lo), 0, 1)
          (3) value_raw = lo + (hi - lo) * norm_L  （形态锚定插值）
          (4) value_effective = (1-α)·baseline + α·value_raw

        参数:
            ranges: map_global_parameters() 返回的 {param: (lo, hi)} 字典
            stats_row: stats 锚点（需包含 L_p10_60d/L_p90_60d）
            forecast_L: MorphCyclePredictor 预测的 level 值（5 天后），None=缺失
            forecast_T: 预测的 trend 值，None=缺失（当前仅用 L，预留接口）
            alpha_blend: 前瞻混合权重 [0,1]
            regime_baselines: REGIME_MULTIPLIERS 查表得到的默认值（字节等价的锚）

        返回:
            {param: float}，与 ranges 的 key 一致。
        """
        # (1) 兜底：forecast 缺失 或 alpha=0 → 纯 regime baseline
        if forecast_L is None or alpha_blend == 0.0:
            return {k: float(regime_baselines[k]) for k in regime_baselines}

        alpha = _clip(float(alpha_blend), 0.0, 1.0)
        # (2) 将 forecast_L 映射到历史 [L_p10, L_p90] 范围内的归一化位置
        L_lo = float(stats_row.get("L_p10_60d", stats_row.get("L_p10_252d", -3.0)))
        L_hi = float(stats_row.get("L_p90_60d", stats_row.get("L_p90_252d", +3.0)))
        denom = max(L_hi - L_lo, 1e-9)
        norm_L = _clip((float(forecast_L) - L_lo) / denom, 0.0, 1.0)

        result: dict[str, float] = {}
        for k, baseline in regime_baselines.items():
            rng = ranges.get(k)
            if rng is None:
                result[k] = float(baseline)
                continue
            lo, hi = float(rng[0]), float(rng[1])
            # (3) 形态锚定插值：lo → hi 线性插值
            value_raw = lo + (hi - lo) * norm_L
            # (4) alpha 混合
            result[k] = (1.0 - alpha) * float(baseline) + alpha * value_raw
        return result

    # ============================================================
    # T4 融合层：为 polling_trader._execute_trade() 提供最终有效参数
    # ============================================================
    _VALID_SECTORS = {"defi", "ai", "rwa", "meme", "l2"}

    def _resolve_effective_params(
        self,
        ranges: dict,
        stats_row: dict,
        forecast_L: float | None,
        forecast_T: float | None,
        alpha_blend: float,
        regime_baselines: dict[str, float],
        sector_weights_result: dict,
        symbol_sector: str | None,
        regime_multipliers: dict[str, float],
        enable_inject: bool,
        base_long_threshold: float,
        base_short_threshold: float,
    ) -> dict[str, float]:
        """为 polling_trader 决策路径提供最终使用的有效参数。

        核心规则：
          enable_inject=False → 完全字节等价于 REGIME_MULTIPLIERS 查表（开关关闭，设计 A.5）
          enable_inject=True  → ① resolve_point_estimate 注入 6 参数
                                ② 板块级 sector_tp/sl_mult 与 regime.tp/sl 聚合
                                ③ long/short bias 修正阈值
                                ④ 直接返回 ls_ratio_cap

        返回字段（所有输出均可直接用于核心层下单决策）：
            position_mult_final
            tp_mult_final
            sl_mult_final
            threshold_mult_final
            long_conf_threshold   # 修正后的实际做多阈值
            short_conf_threshold  # 修正后的实际做空阈值
            ls_ratio_cap
            global_position_mult_raw
            sector_weight_raw
            sector_tp_mult_raw
            sector_sl_mult_raw
        """
        # ========== 开关关闭：字节等价（完全不注入，仅返回查表值）==========
        if not enable_inject:
            thr_mult = float(regime_multipliers.get("threshold_mult", 1.0))
            return {
                "position_mult_final": float(regime_multipliers.get("position_mult", 1.0)),
                "tp_mult_final": float(regime_multipliers.get("tp_mult", 1.0)),
                "sl_mult_final": float(regime_multipliers.get("sl_mult", 1.0)),
                "threshold_mult_final": thr_mult,
                "long_conf_threshold": float(base_long_threshold) * thr_mult,
                "short_conf_threshold": float(base_short_threshold) * thr_mult,
                "ls_ratio_cap": float(regime_baselines.get("ls_ratio_cap", 0.5)),
                "global_position_mult_raw": float(regime_baselines.get("global_position_mult", 1.0)),
                "sector_weight_raw": 0.20,
                "sector_tp_mult_raw": 1.0,
                "sector_sl_mult_raw": 1.0,
            }

        # ========== 开关打开：注入 + 融合 ==========
        # (1) 6 参数 resolve
        pm_params = self.resolve_point_estimate(
            ranges=ranges, stats_row=stats_row,
            forecast_L=forecast_L, forecast_T=forecast_T,
            alpha_blend=alpha_blend, regime_baselines=regime_baselines,
        )
        pos_from_pm = pm_params["global_position_mult"]
        ls_cap = pm_params["ls_ratio_cap"]
        long_thr_pm = pm_params["long_threshold_mult"]
        short_thr_pm = pm_params["short_threshold_mult"]

        # (1b) 加法偏置 → 乘法偏置转换
        # resolve 的 long/short_bias 是加法值（∈ [-0.3, 0.3]，0=不变）
        # 语义：add<0 表示该方向更谨慎 → 乘数>1（抬高高门槛）
        #       add>0 表示该方向更激进 → 乘数<1（降低门槛）
        _lb_add = float(pm_params.get("long_bias", 0.0))
        _sb_add = float(pm_params.get("short_bias", 0.0))
        long_bias = float(np.clip(1.0 - _lb_add, 0.70, 1.30))
        short_bias = float(np.clip(1.0 - _sb_add, 0.70, 1.30))

        # (2) position 融合：pos_final = regime.pos_mult × pos_from_pm
        # （regime 查表 × PM 全局调节，乘法合成）
        pos_base = float(regime_multipliers.get("position_mult", 1.0))
        position_mult_final = float(np.clip(pos_base * pos_from_pm, 0.10, 5.0))

        # (3) sector_tp/sl_mult × regime.tp/sl 合成
        tp_base = float(regime_multipliers.get("tp_mult", 1.0))
        sl_base = float(regime_multipliers.get("sl_mult", 1.0))
        sw_res = sector_weights_result or {}
        sect_tp_dict = sw_res.get("sector_tp_mult", {}) if isinstance(sw_res, dict) else {}
        sect_sl_dict = sw_res.get("sector_sl_mult", {}) if isinstance(sw_res, dict) else {}
        weights_dict = sw_res.get("weights", {}) if isinstance(sw_res, dict) else {}

        sect_tp = 1.0
        sect_sl = 1.0
        sect_w = 0.20
        if symbol_sector and symbol_sector in self._VALID_SECTORS:
            sect_tp = float(sect_tp_dict.get(symbol_sector, 1.0))
            sect_sl = float(sect_sl_dict.get(symbol_sector, 1.0))
            sect_w = float(weights_dict.get(symbol_sector, 0.20))

        tp_mult_final = float(np.clip(tp_base * sect_tp, 0.50, 3.0))
        sl_mult_final = float(np.clip(sl_base * sect_sl, 0.50, 5.0))

        # (4) threshold_mult_final：综合门槛修正，取 long/short 的均值做展示性返回
        #     实际 long/short 阈值独立计算：
        #        long 用 regime.threshold_mult × long_thr_pm × long_bias_mult
        #        short 用 regime.threshold_mult × short_thr_pm × short_bias_mult
        #     这样 long/short 各自方向的 PM 参数都生效，避免二选一互相抵消
        regime_thr = float(regime_multipliers.get("threshold_mult", 1.0))
        long_thr_component = regime_thr * float(long_thr_pm)
        short_thr_component = regime_thr * float(short_thr_pm)
        threshold_mult_final = float(np.clip(
            (long_thr_component + short_thr_component) * 0.5, 0.30, 3.0
        ))

        # (5) 多空偏置 × 各自阈值组件：
        #     long/short 独立计算，bias>1 → 更谨慎 → 门槛更高；bias<1 → 更激进 → 门槛更低
        long_thr_bias = float(np.clip(long_bias, 0.50, 2.0))
        short_thr_bias = float(np.clip(short_bias, 0.50, 2.0))
        long_conf_threshold = float(
            np.clip(base_long_threshold, 0.0, 10.0)
            * np.clip(long_thr_component, 0.30, 3.0)
            * long_thr_bias
        )
        short_conf_threshold = float(
            np.clip(base_short_threshold, 0.0, 10.0)
            * np.clip(short_thr_component, 0.30, 3.0)
            * short_thr_bias
        )

        return {
            "position_mult_final": position_mult_final,
            "tp_mult_final": tp_mult_final,
            "sl_mult_final": sl_mult_final,
            "threshold_mult_final": threshold_mult_final,
            "long_conf_threshold": long_conf_threshold,
            "short_conf_threshold": short_conf_threshold,
            "ls_ratio_cap": float(ls_cap),
            "global_position_mult_raw": float(pos_from_pm),
            "sector_weight_raw": float(sect_w),
            "sector_tp_mult_raw": float(sect_tp),
            "sector_sl_mult_raw": float(sect_sl),
        }


# ============================================================
# 模块别名同步
# ============================================================
def _sync_module_aliases():
    import sys as _sys
    this_mod = _sys.modules.get(__name__)
    if this_mod is None:
        return
    candidates = [
        "bcrm2.parameter_mapper",
        "scripts.memory_l4.bcrm2.parameter_mapper",
    ]
    for alias in candidates:
        existing = _sys.modules.get(alias)
        if existing is None:
            _sys.modules[alias] = this_mod


_sync_module_aliases()
del _sync_module_aliases
