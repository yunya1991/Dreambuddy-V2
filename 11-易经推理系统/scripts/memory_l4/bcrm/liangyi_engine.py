"""
两仪引擎 — 宏观（美林时钟）× 微观（生命周期）。

太极是本体（小大之辩），两仪是双时间维度周期：
- 宏观：美林时钟循环圆盘（复苏/过热/滞胀/衰退）— 天时
- 微观：自身生命周期（萌芽/生长/成熟/衰落）— 作物之于春夏秋冬

两仪生四象：两仪状态影响时空表里参数偏置。
两仪共振/对冲：宏观微观同季共振放大，反季对冲减弱。

本质是计算，易经只是符号推理。
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List

from ._constants import (
    # 宏观美林时钟
    MACRO_RECOVERY, MACRO_OVERHEAT, MACRO_STAGFLATION, MACRO_RECESSION,
    MACRO_PHASES_CN, MACRO_SEASON,
    # 微观生命周期
    MICRO_SPROUT, MICRO_GROWTH, MICRO_MATURE, MICRO_DECLINE,
    MICRO_PHASES_CN, MICRO_SEASON,
    # 季节偏置
    LIANGYI_SEASON_BIAS, LIANGYI_SEASON_MECH_BIAS,
    LIANGYI_RESONANCE_BONUS, LIANGYI_CONFLICT_PENALTY, LIANGYI_NEUTRAL,
    SEASON_OPPOSITE,
)
from .scale_engine import ScaleParams


@dataclass
class LiangyiState:
    """
    两仪状态 — 宏观周期 × 微观生命周期。

    两仪不直接决定方向，而是通过调整四象参数影响力场。
    """
    macro_phase: str = MACRO_RECOVERY      # 宏观美林时钟阶段
    macro_season: str = "春"                # 宏观季节
    micro_phase: str = MICRO_SPROUT        # 微观生命周期阶段
    micro_season: str = "春"                # 微观季节

    # 共振状态
    is_resonance: bool = False              # 同季共振
    is_conflict: bool = False               # 反季对冲
    resonance_factor: float = 1.0           # 共振系数（用于置信度调整）

    # 宏观指标快照（用于追溯）
    gdp_growth: Optional[float] = None
    cpi: Optional[float] = None
    interest_rate: Optional[float] = None

    # 微观指标快照
    price_position: float = 0.5
    trend_strength: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "macro_phase": self.macro_phase,
            "macro_phase_cn": MACRO_PHASES_CN.get(self.macro_phase, ""),
            "macro_season": self.macro_season,
            "micro_phase": self.micro_phase,
            "micro_phase_cn": MICRO_PHASES_CN.get(self.micro_phase, ""),
            "micro_season": self.micro_season,
            "is_resonance": self.is_resonance,
            "is_conflict": self.is_conflict,
            "resonance_factor": round(self.resonance_factor, 4),
            "gdp_growth": self.gdp_growth,
            "cpi": self.cpi,
            "interest_rate": self.interest_rate,
            "price_position": round(self.price_position, 4),
            "trend_strength": round(self.trend_strength, 4),
        }


class LiangyiEngine:
    """
    两仪引擎 — 宏观×微观双时间维度周期。

    串行集成：ScaleEngine（体量）→ LiangyiEngine（两仪）→ ForceEngine（力学）

    工作流程：
    1. 从宏观指标（gdp/cpi/利率）推断美林时钟阶段
    2. 从 price_position + trend_strength 推断生命周期阶段
    3. 计算两仪共振/对冲系数
    4. 根据两仪季节对 ScaleParams 做偏置调整
    """

    def __init__(self,
                 gdp_growth_threshold: float = 0.0,
                 cpi_threshold: float = 0.02,
                 interest_rate_threshold: float = 0.02,
                 resonance_bonus: float = None,
                 conflict_penalty: float = None,
                 resonance_conf_relax: float = None,
                 conflict_conf_tighten: float = None,
                 season_bias_scale: float = 2.0,
                 season_mech_scale: float = 1.0,
                 macro_weight: float = 0.4):
        """
        Args:
            gdp_growth_threshold: GDP 增长率中性阈值（正负分界，默认0）
            cpi_threshold: CPI 中性阈值（默认2%）
            interest_rate_threshold: 利率中性阈值（默认2%）
            resonance_bonus: 共振系数（默认从常量读取，调优后1.05）
            conflict_penalty: 对冲系数（默认从常量读取，调优后0.85）
            resonance_conf_relax: 共振时置信度阈值放宽量（调优后0.02）
            conflict_conf_tighten: 对冲时置信度阈值收紧量（调优后0.0）
            season_bias_scale: 季节四象权重偏置缩放因子（调优后2.0）
            season_mech_scale: 季节力学参数偏置缩放因子（1.0=原始）
            macro_weight: 宏观权重（调优后0.4，微观权重0.6）
        """
        self.gdp_thresh = gdp_growth_threshold
        self.cpi_thresh = cpi_threshold
        self.rate_thresh = interest_rate_threshold
        self.resonance_bonus = (resonance_bonus if resonance_bonus is not None
                                 else LIANGYI_RESONANCE_BONUS)
        self.conflict_penalty = (conflict_penalty if conflict_penalty is not None
                                  else LIANGYI_CONFLICT_PENALTY)
        self.resonance_conf_relax = (resonance_conf_relax if resonance_conf_relax is not None
                                       else 0.02)
        self.conflict_conf_tighten = (conflict_conf_tighten if conflict_conf_tighten is not None
                                       else 0.0)
        self.season_bias_scale = season_bias_scale
        self.season_mech_scale = season_mech_scale
        self.macro_weight = macro_weight
        self._state_cache: Dict[str, LiangyiState] = {}
        self._learned_stats: Dict[Tuple[str, str], Dict] = {}
        self._learned_season_stats: Dict[Tuple[str, str], Dict] = {}

    # ============================================================
    # 宏观美林时钟推断
    # ============================================================
    def infer_macro_phase(self,
                          gdp_growth: float,
                          cpi: float,
                          interest_rate: float) -> str:
        """
        从宏观指标推断美林时钟4阶段。

        美林时钟规则：
        - 复苏（春）：GDP↑ + CPI↓ + 利率↓
        - 过热（夏）：GDP↑ + CPI↑ + 利率↑
        - 滞胀（秋）：GDP↓ + CPI↑ + 利率↑
        - 衰退（冬）：GDP↓ + CPI↓ + 利率↓

        Args:
            gdp_growth: GDP 增长率（如 0.065 表示 6.5%）
            cpi: CPI 同比（如 0.025 表示 2.5%）
            interest_rate: 基准利率（如 0.03 表示 3%）

        Returns:
            宏观阶段字符串
        """
        gdp_up = gdp_growth > self.gdp_thresh
        cpi_up = cpi > self.cpi_thresh
        rate_up = interest_rate > self.rate_thresh

        if gdp_up and not cpi_up and not rate_up:
            return MACRO_RECOVERY     # 复苏
        elif gdp_up and cpi_up and rate_up:
            return MACRO_OVERHEAT     # 过热
        elif not gdp_up and cpi_up and rate_up:
            return MACRO_STAGFLATION  # 滞胀
        elif not gdp_up and not cpi_up and not rate_up:
            return MACRO_RECESSION    # 衰退
        else:
            # 混合状态，用主导指标判定
            if gdp_up:
                return MACRO_OVERHEAT if cpi_up else MACRO_RECOVERY
            else:
                return MACRO_STAGFLATION if cpi_up else MACRO_RECESSION

    # ============================================================
    # 微观生命周期推断
    # ============================================================
    def infer_micro_phase(self,
                          price_position: float,
                          trend_strength: float) -> str:
        """
        从价格位置 + 趋势强度推断生命周期4阶段。

        作物之于春夏秋冬：
        - 萌芽（春）：price_position<0.25，趋势刚启动
        - 生长（夏）：0.25-0.6，趋势强
        - 成熟（秋）：0.6-0.85，趋势减弱
        - 衰落（冬）：>0.85 或趋势消失

        Args:
            price_position: 价格位置（0-1，0=底部，1=顶部）
            trend_strength: 趋势强度（0-1）

        Returns:
            微观阶段字符串
        """
        # 趋势消失优先判定为衰落
        if trend_strength < 0.15:
            return MICRO_DECLINE

        if price_position < 0.25:
            return MICRO_SPROUT
        elif price_position < 0.6:
            return MICRO_GROWTH
        elif price_position < 0.85:
            return MICRO_MATURE
        else:
            return MICRO_DECLINE

    # ============================================================
    # 两仪状态计算
    # ============================================================
    def infer(self,
              market_snapshot: Dict[str, Any],
              scale_params: ScaleParams = None) -> LiangyiState:
        """
        从市场快照推断两仪状态。

        Args:
            market_snapshot: 市场快照，需包含宏观指标和微观指标
            scale_params: 体量参数（可选，用于追溯）

        Returns:
            LiangyiState
        """
        # --- 宏观指标 ---
        gdp_growth = market_snapshot.get("gdp_growth", 0.05)  # 默认温和增长
        cpi = market_snapshot.get("cpi", 0.02)                # 默认2%
        interest_rate = market_snapshot.get("interest_rate", 0.025)  # 默认2.5%

        macro_phase = self.infer_macro_phase(gdp_growth, cpi, interest_rate)
        macro_season = MACRO_SEASON.get(macro_phase, "春")

        # --- 微观指标 ---
        price_position = market_snapshot.get("price_position", 0.5)
        trend_strength = market_snapshot.get("trend_strength", 0.5)

        micro_phase = self.infer_micro_phase(price_position, trend_strength)
        micro_season = MICRO_SEASON.get(micro_phase, "春")

        # --- 共振/对冲（维度4：自适应共振系数）---
        is_resonance = macro_season == micro_season
        is_conflict = SEASON_OPPOSITE.get(macro_season) == micro_season

        # 维度4：如果有学习数据，用自适应共振系数
        if self._learned_season_stats:
            resonance_factor = self.get_adaptive_resonance_factor(
                macro_season, micro_season)
        elif is_resonance:
            resonance_factor = self.resonance_bonus
        elif is_conflict:
            resonance_factor = self.conflict_penalty
        else:
            resonance_factor = LIANGYI_NEUTRAL

        return LiangyiState(
            macro_phase=macro_phase,
            macro_season=macro_season,
            micro_phase=micro_phase,
            micro_season=micro_season,
            is_resonance=is_resonance,
            is_conflict=is_conflict,
            resonance_factor=resonance_factor,
            gdp_growth=gdp_growth,
            cpi=cpi,
            interest_rate=interest_rate,
            price_position=price_position,
            trend_strength=trend_strength,
        )

    # ============================================================
    # 参数偏置调整（两仪→四象）
    # ============================================================
    def adjust_params(self,
                      base_params: ScaleParams,
                      state: LiangyiState) -> ScaleParams:
        """
        根据两仪状态对 ScaleParams 做偏置调整。

        两仪生四象：两仪季节影响时空表里权重 + 力学参数。
        共振放大置信度，对冲减弱置信度。

        Args:
            base_params: 体量基础参数
            state: 两仪状态

        Returns:
            调整后的 ScaleParams（新对象）
        """
        # 宏观季节偏置
        macro_bias = LIANGYI_SEASON_BIAS.get(state.macro_season,
                                              {"time": 0, "space": 0,
                                               "surface": 0, "core": 0})
        macro_mech = LIANGYI_SEASON_MECH_BIAS.get(state.macro_season,
                                                   {"mass": 0, "decay": 0,
                                                    "conf": 0, "reversal": 0})

        # 微观季节偏置
        micro_bias = LIANGYI_SEASON_BIAS.get(state.micro_season,
                                              {"time": 0, "space": 0,
                                               "surface": 0, "core": 0})
        micro_mech = LIANGYI_SEASON_MECH_BIAS.get(state.micro_season,
                                                   {"mass": 0, "decay": 0,
                                                    "conf": 0, "reversal": 0})

        # 宏观×微观 偏置叠加（宏观权重可配置，默认0.6）
        # 宏观是天时，影响更广；微观是自身，影响更聚焦
        macro_w = self.macro_weight
        micro_w = 1.0 - macro_w

        # 应用偏置缩放因子
        sbs = self.season_bias_scale
        sms = self.season_mech_scale

        w_time_bias = (macro_bias["time"] * macro_w + micro_bias["time"] * micro_w) * sbs
        w_space_bias = (macro_bias["space"] * macro_w + micro_bias["space"] * micro_w) * sbs
        w_surface_bias = (macro_bias["surface"] * macro_w + micro_bias["surface"] * micro_w) * sbs
        w_core_bias = (macro_bias["core"] * macro_w + micro_bias["core"] * micro_w) * sbs

        mass_bias = (macro_mech["mass"] * macro_w + micro_mech["mass"] * micro_w) * sms
        decay_bias = (macro_mech["decay"] * macro_w + micro_mech["decay"] * micro_w) * sms
        conf_bias = (macro_mech["conf"] * macro_w + micro_mech["conf"] * micro_w) * sms
        reversal_bias = (macro_mech["reversal"] * macro_w + micro_mech["reversal"] * micro_w) * sms

        # 应用偏置
        new_w_time = base_params.weight_time + w_time_bias
        new_w_space = base_params.weight_space + w_space_bias
        new_w_surface = base_params.weight_surface + w_surface_bias
        new_w_core = base_params.weight_core + w_core_bias

        # 归一化（确保权重和为1）
        total = new_w_time + new_w_space + new_w_surface + new_w_core
        if total > 0:
            new_w_time /= total
            new_w_space /= total
            new_w_surface /= total
            new_w_core /= total

        # 力学参数偏置（共振系数影响置信度阈值）
        new_mass = max(0.1, base_params.market_mass_base + mass_bias)
        new_decay = max(0.5, min(0.98, base_params.velocity_decay + decay_bias))
        # 共振降低阈值（更易通过），对冲提高阈值（更保守）
        new_conf = max(0.2, min(0.6,
            base_params.confidence_threshold + conf_bias))
        new_reversal = max(0.05, min(0.4,
            base_params.reversal_threshold + reversal_bias))

        # 共振系数影响置信度阈值（可配置放宽/收紧量）
        if state.is_resonance:
            new_conf = max(0.2, new_conf - self.resonance_conf_relax)
        elif state.is_conflict:
            new_conf = min(0.6, new_conf + self.conflict_conf_tighten)

        return ScaleParams(
            scale=base_params.scale,
            weight_time=new_w_time,
            weight_space=new_w_space,
            weight_surface=new_w_surface,
            weight_core=new_w_core,
            market_mass_base=new_mass,
            velocity_decay=new_decay,
            confidence_threshold=new_conf,
            reversal_threshold=new_reversal,
            time_horizon_base=base_params.time_horizon_base,
            space_sensitivity=base_params.space_sensitivity,
            volatility_adjustment=base_params.volatility_adjustment,
            scale_gua=base_params.scale_gua,
        )

    # ============================================================
    # 综合接口
    # ============================================================
    def adapt(self,
              market_snapshot: Dict[str, Any],
              base_params: ScaleParams) -> Tuple[ScaleParams, LiangyiState]:
        """
        综合接口：从快照推断两仪状态，并调整参数。

        Args:
            market_snapshot: 市场快照
            base_params: 体量基础参数

        Returns:
            (调整后的 ScaleParams, LiangyiState)
        """
        state = self.infer(market_snapshot, base_params)
        adjusted = self.adjust_params(base_params, state)

        # L4 学习：用历史胜率微调置信度阈值
        if self._learned_stats:
            adjusted = self._apply_learned_adjustment(adjusted, state)

        return adjusted, state

    # ============================================================
    # L4 记忆学习：多维度学习
    # ============================================================
    # 学习维度：
    # 1. 胜率维度：统计每种两仪组合的胜率 → 调整 confidence_threshold
    # 2. 权重偏置维度：学习正确案例的四象权重分布 → 调整 weight_time/space/surface/core
    # 3. 力学参数维度：学习正确案例的 mass/decay 分布 → 调整 market_mass_base/velocity_decay
    # 4. 共振系数维度：学习每种季节组合的共振/对冲系数 → 调整 resonance_bonus/conflict_penalty
    # ============================================================

    # 最小样本数（低于此数不学习）
    MIN_LEARN_SAMPLES = 5
    # 学习率（向正确案例均值靠拢的速度）
    LEARN_RATE = 0.3
    # 权重学习率（保守，避免权重突变）
    WEIGHT_LEARN_RATE = 0.2

    def learn_from_cases(self, cases: List[Dict[str, Any]]) -> None:
        """
        从历史案例多维度学习。

        学习维度：
        1. 胜率：每种 (macro, micro) 组合的 win_rate
        2. 权重偏置：正确案例的四象权重加权均值
        3. 力学参数：正确案例的 mass/decay 加权均值
        4. 共振系数：每种 (macro_season, micro_season) 组合的胜率反馈

        案例需包含:
        - liangyi_state: {macro_phase, micro_phase, macro_season, micro_season,
                          is_resonance, is_conflict}
        - bcrm_output.scale_params: {weight_time, weight_space, weight_surface, weight_core,
                                       market_mass_base, velocity_decay, ...}
        - actual_outcome: {is_correct: bool}

        Args:
            cases: 历史案例列表
        """
        # 维度1+2+3：按 (macro_phase, micro_phase) 分组
        # 从已有统计继承，支持增量学习
        combo_stats: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for k, v in self._learned_stats.items():
            combo_stats[k] = dict(v)

        # 维度4：按 (macro_season, micro_season) 分组
        season_stats: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for k, v in self._learned_season_stats.items():
            season_stats[k] = dict(v)

        for case in cases:
            bcrm_output = case.get("bcrm_output", {})
            ly = case.get("liangyi_state") or bcrm_output.get("liangyi_state", {})
            if not ly:
                continue

            macro = ly.get("macro_phase")
            micro = ly.get("micro_phase")
            macro_season = ly.get("macro_season")
            micro_season = ly.get("micro_season")
            if not macro or not micro:
                continue

            outcome = case.get("actual_outcome") or case.get("decision_outcome") or {}
            is_correct = outcome.get("is_correct")
            if is_correct is None:
                continue

            # 提取该案例使用的参数
            sp = case.get("scale_params") or bcrm_output.get("scale_params", {})

            # --- 维度1+2+3：组合级统计 ---
            combo_key = (macro, micro)
            if combo_key not in combo_stats:
                combo_stats[combo_key] = {
                    "total": 0, "correct": 0, "wrong": 0,
                    # 所有案例的参数累加
                    "w_time_sum": 0.0, "w_space_sum": 0.0,
                    "w_surface_sum": 0.0, "w_core_sum": 0.0,
                    "mass_sum": 0.0, "decay_sum": 0.0,
                    # 正确案例的参数累加
                    "w_time_correct_sum": 0.0, "w_space_correct_sum": 0.0,
                    "w_surface_correct_sum": 0.0, "w_core_correct_sum": 0.0,
                    "mass_correct_sum": 0.0, "decay_correct_sum": 0.0,
                    # 错误案例的参数累加
                    "w_time_wrong_sum": 0.0, "w_space_wrong_sum": 0.0,
                    "w_surface_wrong_sum": 0.0, "w_core_wrong_sum": 0.0,
                    "mass_wrong_sum": 0.0, "decay_wrong_sum": 0.0,
                }

            cs = combo_stats[combo_key]
            cs["total"] += 1
            if is_correct:
                cs["correct"] += 1
            else:
                cs["wrong"] += 1

            # 提取参数
            w_t = sp.get("weight_time", 0.2)
            w_s = sp.get("weight_space", 0.15)
            w_sf = sp.get("weight_surface", 0.3)
            w_c = sp.get("weight_core", 0.35)
            mass = sp.get("market_mass_base", 1.0)
            decay = sp.get("velocity_decay", 0.85)

            # 累加所有案例
            cs["w_time_sum"] += w_t
            cs["w_space_sum"] += w_s
            cs["w_surface_sum"] += w_sf
            cs["w_core_sum"] += w_c
            cs["mass_sum"] += mass
            cs["decay_sum"] += decay

            # 分别累加正确/错误案例
            if is_correct:
                cs["w_time_correct_sum"] += w_t
                cs["w_space_correct_sum"] += w_s
                cs["w_surface_correct_sum"] += w_sf
                cs["w_core_correct_sum"] += w_c
                cs["mass_correct_sum"] += mass
                cs["decay_correct_sum"] += decay
            else:
                cs["w_time_wrong_sum"] += w_t
                cs["w_space_wrong_sum"] += w_s
                cs["w_surface_wrong_sum"] += w_sf
                cs["w_core_wrong_sum"] += w_c
                cs["mass_wrong_sum"] += mass
                cs["decay_wrong_sum"] += decay

            # --- 维度4：季节级统计 ---
            if macro_season and micro_season:
                season_key = (macro_season, micro_season)
                if season_key not in season_stats:
                    season_stats[season_key] = {
                        "total": 0, "correct": 0,
                        "is_resonance": ly.get("is_resonance", False),
                        "is_conflict": ly.get("is_conflict", False),
                    }
                season_stats[season_key]["total"] += 1
                if is_correct:
                    season_stats[season_key]["correct"] += 1

        # 计算学习结果：用 正确案例均值 - 错误案例均值 作为学习方向
        for key, s in combo_stats.items():
            n = s["total"]
            n_correct = s["correct"]
            n_wrong = s["wrong"]

            s["win_rate"] = n_correct / n if n > 0 else 0.5

            # 全体均值
            s["w_time_mean"] = s["w_time_sum"] / n if n > 0 else 0.2
            s["w_space_mean"] = s["w_space_sum"] / n if n > 0 else 0.15
            s["w_surface_mean"] = s["w_surface_sum"] / n if n > 0 else 0.3
            s["w_core_mean"] = s["w_core_sum"] / n if n > 0 else 0.35
            s["mass_mean"] = s["mass_sum"] / n if n > 0 else 1.0
            s["decay_mean"] = s["decay_sum"] / n if n > 0 else 0.85

            # 正确案例均值
            s["w_time_correct_mean"] = (s["w_time_correct_sum"] / n_correct
                                          if n_correct > 0 else s["w_time_mean"])
            s["w_space_correct_mean"] = (s["w_space_correct_sum"] / n_correct
                                           if n_correct > 0 else s["w_space_mean"])
            s["w_surface_correct_mean"] = (s["w_surface_correct_sum"] / n_correct
                                             if n_correct > 0 else s["w_surface_mean"])
            s["w_core_correct_mean"] = (s["w_core_correct_sum"] / n_correct
                                          if n_correct > 0 else s["w_core_mean"])
            s["mass_correct_mean"] = (s["mass_correct_sum"] / n_correct
                                        if n_correct > 0 else s["mass_mean"])
            s["decay_correct_mean"] = (s["decay_correct_sum"] / n_correct
                                         if n_correct > 0 else s["decay_mean"])

            # 错误案例均值
            s["w_time_wrong_mean"] = (s["w_time_wrong_sum"] / n_wrong
                                        if n_wrong > 0 else s["w_time_mean"])
            s["w_space_wrong_mean"] = (s["w_space_wrong_sum"] / n_wrong
                                         if n_wrong > 0 else s["w_space_mean"])
            s["w_surface_wrong_mean"] = (s["w_surface_wrong_sum"] / n_wrong
                                           if n_wrong > 0 else s["w_surface_mean"])
            s["w_core_wrong_mean"] = (s["w_core_wrong_sum"] / n_wrong
                                        if n_wrong > 0 else s["w_core_mean"])
            s["mass_wrong_mean"] = (s["mass_wrong_sum"] / n_wrong
                                      if n_wrong > 0 else s["mass_mean"])
            s["decay_wrong_mean"] = (s["decay_wrong_sum"] / n_wrong
                                       if n_wrong > 0 else s["decay_mean"])

            # 学习方向：correct_mean - wrong_mean（正确案例比错误案例偏多的方向）
            # 这是更有效的学习信号，因为参数相同时该值为0
            s["w_time_direction"] = s["w_time_correct_mean"] - s["w_time_wrong_mean"]
            s["w_space_direction"] = s["w_space_correct_mean"] - s["w_space_wrong_mean"]
            s["w_surface_direction"] = s["w_surface_correct_mean"] - s["w_surface_wrong_mean"]
            s["w_core_direction"] = s["w_core_correct_mean"] - s["w_core_wrong_mean"]
            s["mass_direction"] = s["mass_correct_mean"] - s["mass_wrong_mean"]
            s["decay_direction"] = s["decay_correct_mean"] - s["decay_wrong_mean"]

        for key, s in season_stats.items():
            s["win_rate"] = s["correct"] / s["total"] if s["total"] > 0 else 0.5

        self._learned_stats = combo_stats
        self._learned_season_stats = season_stats

        # Bug Y5 修复: 原函数无返回值（隐式 None）
        return {
            "ok": True,
            "learned_combos": len(combo_stats),
            "learned_seasons": len(season_stats),
            "total_cases": len(cases),
        }

    def _apply_learned_adjustment(self,
                                    params: ScaleParams,
                                    state: LiangyiState) -> ScaleParams:
        """
        应用多维度学习结果到 ScaleParams。

        维度1：胜率 → confidence_threshold
        维度2：权重偏置 → weight_time/space/surface/core（用正确-错误方向）
        维度3：力学参数 → market_mass_base/velocity_decay（用正确-错误方向）
        维度4：共振系数 → 不直接修改 ScaleParams（在 infer 中通过 resonance_factor 间接影响）

        核心算法：方向性学习
        - 学习方向 = correct_mean - wrong_mean
        - 当正确案例和错误案例的参数分布相同时，方向=0，不调整
        - 当正确案例的某参数偏高时，向该方向微调
        - 学习率随胜率偏离0.5的程度放大（胜率越极端，越信任学习结果）

        Args:
            params: 规则调整后的参数
            state: 两仪状态

        Returns:
            多维学习调整后的 ScaleParams
        """
        key = (state.macro_phase, state.micro_phase)
        s = self._learned_stats.get(key)

        if not s or s["total"] < self.MIN_LEARN_SAMPLES:
            return params  # 样本不足，不调整

        win_rate = s["win_rate"]
        deviation = win_rate - 0.5  # [-0.5, 0.5]

        # === 维度1：胜率 → confidence_threshold ===
        # 胜率高 → 放宽（降低阈值）；胜率低 → 收紧（提高阈值）
        conf_adjust = -deviation * 0.1
        new_conf = max(0.2, min(0.6, params.confidence_threshold + conf_adjust))

        # 学习率：胜率越极端，越信任学习结果
        confidence_factor = min(1.0, abs(deviation) * 2 + 0.3)
        w_lr = self.WEIGHT_LEARN_RATE * confidence_factor
        mech_lr = self.LEARN_RATE * confidence_factor

        # === 维度2：权重偏置 → 四象权重 ===
        # 用方向性学习：向正确案例偏多的方向调整
        new_w_time = params.weight_time + s["w_time_direction"] * w_lr
        new_w_space = params.weight_space + s["w_space_direction"] * w_lr
        new_w_surface = params.weight_surface + s["w_surface_direction"] * w_lr
        new_w_core = params.weight_core + s["w_core_direction"] * w_lr

        # 归一化
        total_w = new_w_time + new_w_space + new_w_surface + new_w_core
        if total_w > 0:
            new_w_time /= total_w
            new_w_space /= total_w
            new_w_surface /= total_w
            new_w_core /= total_w

        # === 维度3：力学参数 → mass/decay ===
        new_mass = params.market_mass_base + s["mass_direction"] * mech_lr
        new_decay = params.velocity_decay + s["decay_direction"] * mech_lr

        # clamp
        new_mass = max(0.1, min(5.0, new_mass))
        new_decay = max(0.5, min(0.98, new_decay))

        return ScaleParams(
            scale=params.scale,
            weight_time=new_w_time,
            weight_space=new_w_space,
            weight_surface=new_w_surface,
            weight_core=new_w_core,
            market_mass_base=new_mass,
            velocity_decay=new_decay,
            confidence_threshold=new_conf,
            reversal_threshold=params.reversal_threshold,
            time_horizon_base=params.time_horizon_base,
            space_sensitivity=params.space_sensitivity,
            volatility_adjustment=params.volatility_adjustment,
            scale_gua=params.scale_gua,
        )

    def get_learned_stats(self) -> Dict[Tuple[str, str], Dict]:
        """获取组合级学习统计（维度1+2+3）。"""
        return dict(self._learned_stats)

    def get_learned_season_stats(self) -> Dict[Tuple[str, str], Dict]:
        """获取季节级学习统计（维度4，共振系数反馈）。"""
        return dict(self._learned_season_stats)

    def get_adaptive_resonance_factor(self,
                                        macro_season: str,
                                        micro_season: str) -> float:
        """
        维度4：自适应共振系数。

        根据季节组合的历史胜率动态调整共振/对冲系数：
        - 同季共振且历史胜率高 → 增强共振
        - 同季共振且历史胜率低 → 减弱共振
        - 反季对冲且历史胜率高 → 减弱对冲（信号依然有效）
        - 反季对冲且历史胜率低 → 增强对冲（保守）

        Args:
            macro_season: 宏观季节（春/夏/秋/冬）
            micro_season: 微观季节

        Returns:
            调整后的共振系数
        """
        key = (macro_season, micro_season)
        s = self._learned_season_stats.get(key)

        if not s or s["total"] < self.MIN_LEARN_SAMPLES:
            # 样本不足，用默认
            is_resonance = macro_season == micro_season
            is_conflict = SEASON_OPPOSITE.get(macro_season) == micro_season
            if is_resonance:
                return self.resonance_bonus
            elif is_conflict:
                return self.conflict_penalty
            else:
                return LIANGYI_NEUTRAL

        win_rate = s["win_rate"]
        deviation = win_rate - 0.5

        if s.get("is_resonance"):
            # 共振组合：胜率高→增强共振（系数↑），胜率低→减弱共振
            return self.resonance_bonus + deviation * 0.2
        elif s.get("is_conflict"):
            # 对冲组合：胜率高→减弱对冲（系数向1.0靠拢=增大），胜率低→增强对冲（系数减小）
            return self.conflict_penalty + deviation * 0.2
        else:
            # 中性组合：胜率高→略放大，胜率低→略缩小
            return LIANGYI_NEUTRAL + deviation * 0.1

    # ============================================================
    # 持久化
    # ============================================================
    def save_state(self, path: str) -> bool:
        """
        保存学习状态到 JSON 文件。

        保存内容：
        - _learned_stats: 组合级学习统计
        - _learned_season_stats: 季节级学习统计
        - 可调超参数（便于版本追溯）

        Returns:
            True 表示成功
        """
        import json
        from pathlib import Path

        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "version": "v0.1",
                "learned_stats": {
                    f"{k[0]}|{k[1]}": v
                    for k, v in self._learned_stats.items()
                },
                "learned_season_stats": {
                    f"{k[0]}|{k[1]}": v
                    for k, v in self._learned_season_stats.items()
                },
                "hyperparams": {
                    "resonance_bonus": self.resonance_bonus,
                    "conflict_penalty": self.conflict_penalty,
                    "resonance_conf_relax": self.resonance_conf_relax,
                    "conflict_conf_tighten": self.conflict_conf_tighten,
                    "season_bias_scale": self.season_bias_scale,
                    "season_mech_scale": self.season_mech_scale,
                    "macro_weight": self.macro_weight,
                    "MIN_LEARN_SAMPLES": self.MIN_LEARN_SAMPLES,
                    "LEARN_RATE": self.LEARN_RATE,
                    "WEIGHT_LEARN_RATE": self.WEIGHT_LEARN_RATE,
                },
            }
            with p.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def load_state(self, path: str) -> bool:
        """
        从 JSON 文件加载学习状态。

        Returns:
            True 表示成功加载，False 表示文件不存在或格式错误
        """
        import json
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return False

        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)

            combo_stats: Dict[Tuple[str, str], Dict] = {}
            for k_str, v in data.get("learned_stats", {}).items():
                parts = k_str.split("|", 1)
                if len(parts) == 2:
                    combo_stats[(parts[0], parts[1])] = v
            self._learned_stats = combo_stats

            season_stats: Dict[Tuple[str, str], Dict] = {}
            for k_str, v in data.get("learned_season_stats", {}).items():
                parts = k_str.split("|", 1)
                if len(parts) == 2:
                    season_stats[(parts[0], parts[1])] = v
            self._learned_season_stats = season_stats

            hp = data.get("hyperparams", {})
            if hp:
                self.resonance_bonus = hp.get("resonance_bonus", self.resonance_bonus)
                self.conflict_penalty = hp.get("conflict_penalty", self.conflict_penalty)
                self.season_bias_scale = hp.get("season_bias_scale", self.season_bias_scale)
                self.season_mech_scale = hp.get("season_mech_scale", self.season_mech_scale)
                self.macro_weight = hp.get("macro_weight", self.macro_weight)

            return True
        except Exception:
            return False
