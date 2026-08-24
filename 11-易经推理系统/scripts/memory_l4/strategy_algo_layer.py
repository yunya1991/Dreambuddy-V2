#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略算法层（v1.4.1 纯参数校准算法层，阶段1最小影子模式）。

严格纯函数：无任何 I/O、无全局状态、无系统调用。
- 输入：five_scores[cls] / regime_summary / liquidity_tier 纯数值
- 输出：StrategySelection dataclass（strategy_type + calibration_biases + front_layer_band）
- fail-open：任何开关关断 / 异常 → 返回默认 StrategySelection（calibration_biases 全1.0）

参考 spec：docs/superpowers/specs/2026-08-21-strategy-layer-v1p4p1-stage1-implementation-spec.md §二/§三
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# =====================================================================
# 全局唯一归一化函数（§2.1：禁止多口径换算漂移）
# =====================================================================
def _normalize_0_100(raw_proxy: float, scale: float = 100.0) -> int:
    """§2.1 全局唯一归一化函数：所有五维评分必须通过此函数输出 0-100 整数。

    单调性保证：raw_proxy 大 → final 一定大（不可逆）；
    边界保证：任何 NaN/±inf/极端值 clip 到 0-100；
    类型保证：返回 int（避免 shadow 日志中出现 float 精度噪声）。
    """
    # ── 防御：非数值 / NaN / ±inf → 中性 50 ──
    try:
        if not isinstance(raw_proxy, (int, float, np.integer, np.floating)):
            return 50
        raw = float(raw_proxy)
        if math.isnan(raw) or math.isinf(raw):
            return 50
    except Exception:  # noqa: BLE001 防御性兜底
        return 50
    value = raw * float(scale)
    # ── 四舍五入 + clip 0-100 ──
    return int(np.clip(round(value), 0, 100))


# =====================================================================
# §一.3：3 个核心 dataclass（StrategySelection / DecisionAuditRecord）
# =====================================================================
STYLE_ORDER = ("emergency", "trend_follow", "breakout", "mean_revert", "momentum", "volatility")
ASSET_CLASSES = ("crypto_usdt", "us_stock", "precious_metal")
DEFAULT_NEUTRAL_SCORES = {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70}


@dataclass
class DecisionAuditRecord:
    """阶段1预留：结构化记录决策审计字段（阶段2在线学习Beta-Bandit/CUSUM直接消费）。

    默认值全中性/None，保证fail-open字节等价。
    """
    heuristic_arm_id: Optional[int] = None              # 阶段1: §15.5.2查表映射臂号0-7
    ol_arm_id: Optional[int] = None                     # 阶段2: Beta-Bandit采样臂号
    arm_reward_parts: Dict[str, float] = field(default_factory=dict)  # 阶段1预记录5项reward拆分
    arm_timestamp: float = 0.0                           # unix秒时间戳（便于离线训练对齐）


@dataclass
class StrategySelection:
    """策略算法层唯一对外输出结构（v1.4.1，按类独立）。

    默认值 = 完全 fail-open 中性值：
    - calibration_biases 全 1.0 → ExitStrategy 阈值 = BASE × 1.0（字节等价改造前）
    - front_layer_band None → 前置层 clip 0 行执行
    - style_exposures = 1/6 均匀 → 无风格偏好
    - strategy_type="heuristic_equilibrium" → 中性启发式均衡策略
    """
    strategy_type: str = "heuristic_equilibrium"
    strategy_version: str = "salv1.4.1"
    style_exposures: Dict[str, float] = field(
        default_factory=lambda: {s: 1.0 / len(STYLE_ORDER) for s in STYLE_ORDER}
    )
    calibration_biases: Dict[str, Any] = field(
        default_factory=lambda: {
            "signal_reverse_threshold_factor": 1.0,
            "p3_early_exit_profit_threshold_factor": 1.0,
            "ev_force_close_threshold_factor": 1.0,
            "timeout_profit_switch_hours_factor": 1.0,
            "ranked_tp_rank_factor": 1.0,
            "ev_adjust_sensitivity_factor": 1.0,
            "min_holding_hours_factor": 1.0,
            "sl_tighten_factor": 1.0,
            "hard_relax_gate": False,  # §R5红线：默认=False（>1.0的放宽方向被强制写回1.0）
        }
    )
    front_layer_band: Optional[Dict[str, float]] = None
    asset_class: str = ""
    five_scores_snapshot: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_NEUTRAL_SCORES))
    audit: Optional[DecisionAuditRecord] = None

    def to_enhance_info(self) -> Dict[str, Any]:
        """绑定TradeRecord.enhance_info时序列化：Dict字段天然兼容白名单，缺键不崩（R1红线）。"""
        d = asdict(self)
        # numpy类型转原生JSON可序列化类型
        def _clean(o):
            if isinstance(o, (np.integer,)): return int(o)
            if isinstance(o, (np.floating,)): return float(o)
            if isinstance(o, np.ndarray): return o.tolist()
            if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)): return [_clean(x) for x in o]
            return o
        return _clean(d)

    @classmethod
    def from_enhance_info(cls, data: Dict) -> "StrategySelection":
        """从TradeRecord.enhance_info反序列化：缺字段自动填默认值（R1兼容性保证）。"""
        full = asdict(cls())
        full.update({k: v for k, v in (data or {}).items() if k in full})
        return cls(**full)


# =====================================================================
# StrategyAlgoConfig：2总+7子开关配置
# =====================================================================
@dataclass
class StrategyAlgoConfig:
    """策略算法层开关配置（默认全部False=fail-open关闭）。

    命名与polling_trader.__init__的enable_*属性保持1:1映射（§三.3.1开关表）。
    """
    # ===== 2总开关 =====
    enable_strategy_layer: bool = False
    enable_five_domain: bool = False
    # ===== 7子开关 =====
    enable_five_domain_war_state: bool = False
    enable_five_domain_style_mask: bool = False
    enable_five_domain_position_cap: bool = False
    enable_five_domain_cross_asset: bool = False
    enable_five_domain_dimensio: bool = False
    enable_five_domain_front_layer_band: bool = False
    enable_five_domain_ol: bool = False  # §十六阶段2才启用
    # ===== 3模式开关（影子AB） =====
    enable_five_domain_shadow_mode: bool = False
    enable_shadow_ab_static_baseline_v15: bool = False
    enable_shadow_ab_dynamic_baseline: bool = False
    # ===== R5红线：放宽阈值允许开关（默认False=不允许放宽，>1.0写回1.0）=====
    enable_strategy_layer_relax_allowed: bool = False


# =====================================================================
# StrategyAlgorithmLayer：纯函数校准算法层（v1.4.1核心）
# =====================================================================
class StrategyAlgorithmLayer:
    """v1.4.1 纯参数校准算法层（无 I/O、无状态，便于 100% 分支单测）。

    输入：
        asset_class∈ASSET_CLASSES: 资产类别（crypto/us_stock/precious_metal，按类独立）
        five_scores = {"dao":0-100, "tian":..., "di":..., "jiang":..., "fa":...}
        regime_summary = {"phase": 4y_phase_str, "regime":..., "liquidity_tier": "G1~G4"}
        liquidity_tier ∈ {"G1","G2","G3","G4"} （G4高波动×0.5 §R6红线）
        five_domain_state: Optional[FiveDomainState] = None（带war_state/mask/band/veto_flags）
    输出：StrategySelection
    """

    # -----------------------------------------------------------------
    # G6 对照表：Seed 初始偏置表（§十 v1.4.1：庙算总分线性缩放 × regime平滑偏移 × liquidity收紧因子）
    #   KEY = (strategy_type, calibration_param) → seed bias base；统一二次校准公式最终相乘
    #   数值范围：[0.30, 2.00] 物理 clip 区间（§R5只是默认硬门限，这里是seed基）
    # -----------------------------------------------------------------
    G6_SEED_TABLE: Dict[Tuple[str, str], float] = {
        # ── 趋势跟踪：放宽出场阈值，拉长持仓 ──
        ("trend_follow",    "signal_reverse_threshold_factor"): 1.30,
        ("trend_follow",    "min_holding_hours_factor"):         1.40,
        ("trend_follow",    "ev_adjust_sensitivity_factor"):     0.80,
        ("trend_follow",    "sl_tighten_factor"):                0.90,
        # ── 突破：Chandelier Exit风格，SL/TP严格 ──
        ("breakout",        "signal_reverse_threshold_factor"):  0.85,
        ("breakout",        "p3_early_exit_profit_threshold_factor"): 0.75,
        ("breakout",        "ranked_tp_rank_factor"):            1.30,
        ("breakout",        "sl_tighten_factor"):                0.80,
        # ── 均值回归：回归达标检测严格，最低持仓时间短 ──
        ("mean_revert",     "signal_reverse_threshold_factor"):  0.70,
        ("mean_revert",     "p3_early_exit_profit_threshold_factor"): 0.65,
        ("mean_revert",     "min_holding_hours_factor"):         0.70,
        ("mean_revert",     "timeout_profit_switch_hours_factor"): 0.80,
        # ── 动量轮动：趋势延续略宽松，强止盈 ──
        ("momentum",        "signal_reverse_threshold_factor"):  1.10,
        ("momentum",        "ranked_tp_rank_factor"):            1.20,
        ("momentum",        "sl_tighten_factor"):                0.85,
        # ── 波动率策略：最小持仓严格，EV强平阈值收紧 ──
        ("volatility",      "ev_force_close_threshold_factor"):  0.80,
        ("volatility",      "min_holding_hours_factor"):         0.60,
        ("volatility",      "sl_tighten_factor"):                0.70,
        # ── 应急策略：所有阈值最保守，只求活下来 ──
        ("emergency",       "ev_force_close_threshold_factor"):  0.50,
        ("emergency",       "sl_tighten_factor"):                0.60,
        ("emergency",       "min_holding_hours_factor"):         0.50,
        ("emergency",       "p3_early_exit_profit_threshold_factor"): 0.50,
        # ── 中性启发式均衡：全1.0默认 ──
        ("heuristic_equilibrium", "signal_reverse_threshold_factor"): 1.0,
        ("heuristic_equilibrium", "p3_early_exit_profit_threshold_factor"): 1.0,
        ("heuristic_equilibrium", "ev_force_close_threshold_factor"): 1.0,
        ("heuristic_equilibrium", "timeout_profit_switch_hours_factor"): 1.0,
        ("heuristic_equilibrium", "ranked_tp_rank_factor"): 1.0,
        ("heuristic_equilibrium", "ev_adjust_sensitivity_factor"): 1.0,
        ("heuristic_equilibrium", "min_holding_hours_factor"): 1.0,
        ("heuristic_equilibrium", "sl_tighten_factor"): 1.0,
    }

    # -----------------------------------------------------------------
    # regime 平滑偏移量（§十 v1.4.1 统一二次校准公式的第二项 regime_factor）
    #   4y大周期 → 乘数；Bull > 1.0（进攻）；Bear < 1.0（防御）
    # -----------------------------------------------------------------
    REGIME_FACTORS: Dict[str, float] = {
        "Bull":       1.08,
        "Recovery":   1.04,
        "Rebound":    1.02,
        "Sideways":   1.00,
        "LateBear":   0.95,
        "EarlyBear":  0.90,
        "Bear":       0.82,
    }
    DEFAULT_REGIME_FACTOR = 1.00

    # -----------------------------------------------------------------
    # liquidity_tier 收紧因子（§R6红线：G4高波动×0.50，严格收紧方向）
    # -----------------------------------------------------------------
    LIQUIDITY_FACTORS: Dict[str, float] = {
        "G1": 1.00,
        "G2": 0.92,
        "G3": 0.80,
        "G4": 0.50,  # §R6红线：G4高波动 所有仓位×0.5
    }
    DEFAULT_LIQUIDITY_FACTOR = 1.00

    # -----------------------------------------------------------------
    # 前置层带宽映射规则 FRONT_BAND_RULES（§15.5.3）：
    #   Tuple(match_fn) → (L_min, L_max), (T_min, T_max), (sector_min, sector_max)
    #   按类cls的五计分匹配，返回band；无匹配返回None=不clip
    # -----------------------------------------------------------------
    FRONT_BAND_RULES: List = [
        # ★ v1.4 大周期弹性闸门原则：仅在【极端场景】给带宽约束，正常区间留None=前置层完全自洽
        #   （三击/强势/极度劣势 → 3条规则；中间 40≤总分<75 → 不落规则=返回None=不clip）
        # 规则1：三击（道≥80 & 地≥75）→ 进攻型最宽带宽（允许前置层高L/T上限放大进攻）
        (lambda s: (s.get("dao", 0) >= 80 and s.get("di", 0) >= 75),
            (0.55, 0.98), (0.55, 0.98), (0.90, 1.20)),
        # 规则2：强势（庙算总分≥75）→ 常规较宽带宽（比三击略保守）
        (lambda s: sum([s.get(k,50)*w for k,w in zip(("dao","tian","di","jiang","fa"),(0.30,0.15,0.25,0.15,0.15))]) >= 75,
            (0.50, 0.92), (0.50, 0.92), (0.85, 1.15)),
        # 规则3：极度劣势（dao<40 维度否决 或 庙算总分<40）→ 最小带宽（收缩，抑制前置层高波动参数）
        (lambda s: (s.get("dao", 0) < 40) or (sum([s.get(k,50)*w for k,w in zip(("dao","tian","di","jiang","fa"),(0.30,0.15,0.25,0.15,0.15))]) < 40),
            (0.35, 0.65), (0.35, 0.65), (0.80, 1.00)),
        # ★ 中间区间 40≤总分<75：无规则匹配 → 返回None（带宽全开，前置层参数自洽）
        #   符合§15.4方案B：战略层不精确修改前置层公式，仅做极端边界闸门
    ]

    def __init__(self, cfg: Optional[StrategyAlgoConfig] = None):
        self.cfg = cfg or StrategyAlgoConfig()
        # EMA 平滑 style_exposures 权重避免频繁切换（GitHub G1）
        self._style_ema_alpha = 0.20
        self._last_style_exposures: Optional[Dict[str, float]] = None

    # =================================================================
    # 对外 1：select() —— v1.4.1 新增 asset_class + five_domain_state 参数
    # =================================================================
    def select(
        self,
        asset_class: str,
        five_scores: Dict[str, int],
        regime_summary: Dict[str, Any],
        liquidity_tier: str,
        five_domain_state: Optional[Any] = None,  # 实际类型 FiveDomainState（避免循环import用Any）
    ) -> StrategySelection:
        """按类cls选择策略 + 校准离场参数 + 前置层带宽。

        fail-open：cfg.enable_strategy_layer=False → 直接返回默认字节等价。
        """
        # ── F1：总开关关断 → 立即返回纯默认字节等价（§15.4.1：严禁填asset/five_scores） ──
        if not self.cfg.enable_strategy_layer:
            return StrategySelection()

        try:
            scores = five_scores or DEFAULT_NEUTRAL_SCORES
            # BUGFIX(Step B1发现): 按asset_class差异化取权重，而非硬编码crypto权重
            # 与 five_domain_scorer.WEIGHTS_BY_CLASS 保持一致（TDD #约束：权重和=1.00）
            try:
                from scripts.memory_l4.five_domain_scorer import FiveDomainHeuristicScorer as _FDHS
                weights = dict(_FDHS.WEIGHTS_BY_CLASS.get(
                    asset_class, _FDHS.WEIGHTS_BY_CLASS["crypto_usdt"]
                ))
            except Exception:
                # 兜底：导入失败时保持crypto权重（fail-safe字节等价前）
                weights = {"dao":0.30, "tian":0.15, "di":0.25, "jiang":0.15, "fa":0.15}
            total = int(round(sum(scores.get(k,50)*w for k,w in weights.items())))

            # =============================================================
            # 步骤1：决定strategy_type（基于allowed_style_mask + 风格暴露）
            # =============================================================
            allowed_mask = {"emergency": True, "trend_follow": True, "breakout": True,
                            "mean_revert": True, "momentum": True, "volatility": True}
            if self.cfg.enable_five_domain_style_mask and five_domain_state is not None:
                cls_mask = getattr(five_domain_state, "allowed_style_mask", {}).get(asset_class, {})
                for s in STYLE_ORDER:
                    if s in cls_mask and not cls_mask[s]:
                        allowed_mask[s] = False
            # GitHub G1 EMA 平滑 style_exposures（避免1轮一切）
            raw_exposures = self._raw_style_exposures_from_scores(total, scores, allowed_mask)
            exposures = self._ema_style(raw_exposures)

            # 策略类型 = max style
            strategy_type = max(STYLE_ORDER, key=lambda s: (exposures[s], allowed_mask[s]))
            # 禁止选择被mask掉的非紧急策略 → 优先 emergency fallback
            if not allowed_mask[strategy_type] and strategy_type != "emergency":
                strategy_type = "emergency"

            # =============================================================
            # 步骤2：统一二次校准公式（§十 v1.4.1）
            #   calibration_bias_raw = clip( G6_seed × regime_factor × liquidity_factor, 0.30, 2.00 )
            #   calibration_bias_final = raw if (relax_allowed or raw <= 1.0) else 1.0
            # =============================================================
            regime_factor = self.REGIME_FACTORS.get(str(regime_summary.get("phase", "")).strip() or "_", self.DEFAULT_REGIME_FACTOR)
            liquidity_factor = self.LIQUIDITY_FACTORS.get(str(liquidity_tier).strip().upper() or "G2", self.DEFAULT_LIQUIDITY_FACTOR)
            default = StrategySelection()
            cb = dict(default.calibration_biases)  # 先默认全1.0
            for param in list(cb.keys()):
                if param == "hard_relax_gate":
                    continue
                seed = self.G6_SEED_TABLE.get((strategy_type, param), 1.0)
                raw = float(np.clip(seed * regime_factor * liquidity_factor, 0.30, 2.00))
                # §R5红线：relax_allowed 默认=False → >1.0的"放宽"方向强制写回1.0
                if raw > 1.0 and not self.cfg.enable_strategy_layer_relax_allowed:
                    cb[param] = 1.0
                else:
                    cb[param] = raw
            cb["hard_relax_gate"] = bool(self.cfg.enable_strategy_layer_relax_allowed)

            # =============================================================
            # 步骤3：前置层带宽 front_layer_band（FRONT_BAND_RULES 查表）
            #   band子开关关断 → 返回None（0行clip）
            # =============================================================
            band: Optional[Dict[str,float]] = None
            if self.cfg.enable_five_domain_front_layer_band:
                # 优先从战略层five_domain_state取独立带宽；否则用这里的规则表
                if five_domain_state is not None:
                    try:
                        external = getattr(five_domain_state, "front_layer_band", {}).get(asset_class)
                        if external: band = dict(external)
                    except Exception:  # noqa: BLE001 fail-open
                        band = None
                if band is None:
                    band = self._compute_front_layer_band(scores, total)
            # 决策审计预留
            audit = DecisionAuditRecord(
                heuristic_arm_id=self._heuristic_arm_id(total, scores),
                arm_timestamp=0.0,
            )
            sel = StrategySelection(
                strategy_type=strategy_type,
                strategy_version="salv1.4.1",
                style_exposures=exposures,
                calibration_biases=cb,
                front_layer_band=band,
                asset_class=asset_class,
                five_scores_snapshot=dict(scores),
                audit=audit,
            )
            return sel
        except Exception:  # noqa: BLE001 — F1异常降级：返回默认字节等价
            return StrategySelection()

    # =================================================================
    # 对外 2：apply_front_band_clip — 纯静态 clip 辅助函数（不依赖cfg开关）
    # =================================================================
    @staticmethod
    def apply_front_band_clip(
        L_raw: np.ndarray,
        T_raw: np.ndarray,
        sector_weights_raw: np.ndarray,
        band: Optional[Dict[str, float]],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """§15.4方案B：仅np.clip限制带宽范围，绝不修改前置层内部L/T计算公式。

        band=None → 完全no-op（返回raw的copy，保持字节等价）。
        """
        # 防御：统一numpy数组类型
        L = np.asarray(L_raw, dtype=float)
        T = np.asarray(T_raw, dtype=float)
        S = np.asarray(sector_weights_raw, dtype=float)
        if band is None:
            # 方案B承诺：band=None 必须严格0行clip → 返回与raw完全相等（TDD #6检查）
            return L, T, S

        L_min = float(band.get("L_min", -np.inf))
        L_max = float(band.get("L_max",  np.inf))
        T_min = float(band.get("T_min", -np.inf))
        T_max = float(band.get("T_max",  np.inf))
        S_min = float(band.get("sector_weights_min", -np.inf))
        S_max = float(band.get("sector_weights_max",  np.inf))
        L_out = np.clip(L, L_min, L_max)
        T_out = np.clip(T, T_min, T_max)
        S_out = np.clip(S, S_min, S_max)
        return L_out, T_out, S_out

    # =================================================================
    # 对外 3：apply_band_with_switch — 版本2：尊重cfg.enable_five_domain_front_layer_band开关
    # =================================================================
    def apply_band_with_switch(
        self,
        L_raw: np.ndarray,
        T_raw: np.ndarray,
        sector_weights_raw: np.ndarray,
        band: Optional[Dict[str, float]],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """带cfg开关的版本。子开关关断时：即便有band，也严格0行clip（TDD #15检查）。"""
        if not self.cfg.enable_five_domain_front_layer_band:
            return np.asarray(L_raw, float), np.asarray(T_raw, float), np.asarray(sector_weights_raw, float)
        return StrategyAlgorithmLayer.apply_front_band_clip(L_raw, T_raw, sector_weights_raw, band)

    # =================================================================
    # 内部工具
    # =================================================================
    @classmethod
    def _compute_front_layer_band(cls, five_scores: Dict[str,int], total: Optional[int] = None) -> Optional[Dict[str,float]]:
        """§15.5.3 FRONT_BAND_RULES：按五计分查带宽；无匹配→None=默认全带宽不clip。"""
        if total is None:
            w = {"dao":0.30, "tian":0.15, "di":0.25, "jiang":0.15, "fa":0.15}
            total = int(round(sum(five_scores.get(k,50)*ww for k,ww in w.items())))
        for rule, L_lims, T_lims, S_lims in cls.FRONT_BAND_RULES:
            try:
                if bool(rule(five_scores)):
                    return {
                        "L_min": float(L_lims[0]), "L_max": float(L_lims[1]),
                        "T_min": float(T_lims[0]), "T_max": float(T_lims[1]),
                        "sector_weights_min": float(S_lims[0]), "sector_weights_max": float(S_lims[1]),
                    }
            except Exception:  # noqa: BLE001 规则函数抛错 → 进入下一条
                continue
        return None  # 无匹配 → 默认全带宽

    @staticmethod
    def _heuristic_arm_id(total: int, five_scores: Dict[str,int]) -> int:
        """阶段1预留：§15.5.2规则→臂号0-7（阶段2 Beta-Bandit离线训练的arm基准标签）。"""
        dao, veto = five_scores.get("dao", 50), five_scores.get("di", 50) < 40 and five_scores.get("tian", 50) < 40
        if five_scores.get("fa", 70) < 40: return 3
        if total < 60 or dao < 40: return 3
        if total < 65: return 2
        if veto: return 7
        if total >= 85 and dao >= 80 and five_scores.get("di", 50) >= 75: return 0
        if total >= 75: return 1
        if five_scores.get("di", 50) >= 60: return 5
        return 6

    def _raw_style_exposures_from_scores(
        self, total: int, scores: Dict[str,int], mask: Dict[str,bool]
    ) -> Dict[str, float]:
        """从五计分庙算+阈值映射 → 6策略原始得分 → 归一化权重。"""
        s = {
            "emergency":    1.0 if (total < 60) else 0.15,
            "trend_follow": (min(total, 100) / 100.0) if mask["trend_follow"] else 0.0,
            "breakout":     (scores.get("di", 50) / 100.0) if mask["breakout"] and total >= 65 else 0.0,
            "mean_revert":  (1.0 - abs(scores.get("di", 50) - 50) / 50.0) if mask["mean_revert"] else 0.0,
            "momentum":     (scores.get("dao", 50) / 100.0) if mask["momentum"] else 0.0,
            "volatility":   1.0 if (mask["volatility"] and scores.get("di",50)<40 and scores.get("tian",50)<40) else 0.0,
        }
        total_v = sum(max(v, 0.0) for v in s.values()) or 1.0
        return {k: max(v,0.0)/total_v for k,v in s.items()}

    def _ema_style(self, new: Dict[str,float]) -> Dict[str,float]:
        """GitHub G1：EMA平滑避免风格权重每轮跳变（span≈5轮=25分钟/5min轮询）。"""
        if self._last_style_exposures is None:
            out = dict(new)
        else:
            last = self._last_style_exposures
            out = {s: (self._style_ema_alpha * new[s] + (1-self._style_ema_alpha) * last.get(s, new[s])) for s in STYLE_ORDER}
        # 重归一化到sum=1.0
        ssum = sum(out.values()) or 1.0
        out = {k: v/ssum for k,v in out.items()}
        self._last_style_exposures = dict(out)
        return out


# =====================================================================
# 路径 B 核心函数（§三组合级完整改造，纯函数/配置表，无I/O）
# =====================================================================
# ---- ExitStrategy 轻量子类（仅用于PORTFOLIO_MODE_CHAINS占位，真实evaluate由ExitManager已有子类完成）----
try:
    from .bcrm2.exit_manager import ExitStrategy, ExitDecision  # noqa: E402
except Exception:  # noqa: BLE001 防御：独立脚本import时允许降级
    try:
        from bcrm2.exit_manager import ExitStrategy, ExitDecision  # type: ignore
    except Exception:  # noqa: BLE001
        # 终极兜底：用ABC类本地定义（保证import不崩，TDD RED阶段最小化耦合）
        from abc import ABC, abstractmethod  # noqa: E402

        class ExitDecision:  # type: ignore
            def __init__(self, action="pass", reason="", strategy_name="", params=None):
                self.action = action
                self.reason = reason
                self.strategy_name = strategy_name
                self.params = params

            @staticmethod
            def pass_():
                return ExitDecision(action="pass")

        class ExitStrategy(ABC):  # type: ignore
            name: str = ""
            priority: int = 0
            enabled: bool = True

            @abstractmethod
            def evaluate(self, context):
                return ExitDecision.pass_()


class _PortfolioChainPlaceholder(ExitStrategy):
    """路径B组合模式链占位策略：不承担真实离场判断，仅用于结构性排序/模式路由。
    真实evaluate由ExitManager注入的实盘子类（P3EarlyExit/SignalReverse/EvFC等）执行。"""

    def __init__(self, name: str, priority: int, enabled: bool = True):
        self.name = name
        self.priority = priority
        self.enabled = enabled

    def evaluate(self, context) -> ExitDecision:  # pragma: no cover - 纯占位不调用
        return ExitDecision.pass_()


# ---------------------------------------------------------------------
# 4 档组合模式预设链（§4.2 路径B组合模式配置表）
#   default: 实盘5策略中性链（priority 10/20/30/40/60，与polling_trader实盘注册一致）
#   cta_risk_on: 趋势风险偏好（让利润跑 → RankedTp关，紧SL放宽）
#   mean_revert_mode: 震荡优先（开启RankedTp换仓，短持仓）
#   risk_off_emergency: 应急风控（P3更早触发，Timeout缩短，EvFC阈值收紧）
# ---------------------------------------------------------------------
PORTFOLIO_MODE_CHAINS: Dict[str, List[ExitStrategy]] = {
    "default": [
        _PortfolioChainPlaceholder("Portfolio_P3EarlyExit",    priority=10),
        _PortfolioChainPlaceholder("Portfolio_SignalReverse",   priority=20),
        _PortfolioChainPlaceholder("Portfolio_EvForceClose",    priority=30),
        _PortfolioChainPlaceholder("Portfolio_TimeoutProfit",   priority=40),
        _PortfolioChainPlaceholder("Portfolio_EvAdjust",        priority=60),
    ],
    "cta_risk_on": [
        # 趋势行情：P3更晚触发（让利润飘）priority=15（比default更晚），保留EvFC/Timeout
        _PortfolioChainPlaceholder("CTA_P3EarlyExit",          priority=15),
        _PortfolioChainPlaceholder("CTA_SignalReverse",        priority=20),
        _PortfolioChainPlaceholder("CTA_EvForceClose",         priority=30),
        _PortfolioChainPlaceholder("CTA_TimeoutProfitLong",    priority=50),  # 拉长持仓时间
        _PortfolioChainPlaceholder("CTA_EvAdjust",             priority=65),
    ],
    "mean_revert_mode": [
        # 震荡：P3更早出场（priority=8=最前线），Timeout短 → 快速止盈换仓
        _PortfolioChainPlaceholder("MR_P3EarlyExit",           priority=8),
        _PortfolioChainPlaceholder("MR_SignalReverse",         priority=20),
        _PortfolioChainPlaceholder("MR_EvForceClose",          priority=30),
        _PortfolioChainPlaceholder("MR_TimeoutProfitShort",    priority=35),  # 缩短换仓
        _PortfolioChainPlaceholder("MR_EvAdjust",              priority=60),
    ],
    "risk_off_emergency": [
        # 应急：P3最紧(priority=5) → EvFC收紧阈值 → Timeout 6h上限
        _PortfolioChainPlaceholder("EMG_P3EarlyExit_Tight",    priority=5),
        _PortfolioChainPlaceholder("EMG_SignalReverse",        priority=18),
        _PortfolioChainPlaceholder("EMG_EvForceClose_Squeeze", priority=28),  # ≤-0.20（对应factor≤0.80）
        _PortfolioChainPlaceholder("EMG_Timeout_6hCap",        priority=38),  # ≤6h（对应factor≤0.50）
        _PortfolioChainPlaceholder("EMG_EvAdjust_Defensive",   priority=60),
    ],
}


# ---------------------------------------------------------------------
# 组合级 RankedTp 开关路由（§4.12.3 路径B：组合级 override 单笔 RankedTp 开关）
#   default=True: 中性；cta_risk_on=False: 趋势让利润跑，不换仓；
#   mean_revert_mode=True: 震荡模式快速换仓；未知fail-open=True
# ---------------------------------------------------------------------
_RANKTP_ALLOW_TABLE: Dict[str, bool] = {
    "default": True,
    "cta_risk_on": False,
    "mean_revert_mode": True,
    "risk_off_emergency": True,  # 应急模式可以True也可以False（但组合级G10不开新仓）
}


def get_ranktp_allow_for_mode(mode: str) -> bool:
    """§G8组合级RankedTp开关路由：未知模式fail-open=True（安全默认）。"""
    try:
        key = str(mode or "").strip() or "default"
        return bool(_RANKTP_ALLOW_TABLE.get(key, True))
    except Exception:  # noqa: BLE001 fail-open
        return True


# ---------------------------------------------------------------------
# G9 聚类约束纯函数（§3.3：同方向同风格总仓位 ≤ 权益×cap_pct，默认50%）
#
# 算法：
#   1. 将已有持仓按 (direction, dominant_style) 分桶
#      dominant_style = style_exposures 中权重最大的非 emergency 风格
#   2. 计算 "新开桶" = (new_direction, new_dominant_style)
#   3. 累加 "新开桶" 内已有 size_usdt + new_size_usdt
#   4. 若 > total_equity × cap_pct → False（拒绝）；否则 True（允许）
#   5. size_usdt = abs(amount × entry_price × leverage) （多空通用）
# ---------------------------------------------------------------------
def _dominant_style_from_exposures(exposures: Dict[str, float]) -> str:
    """从style_exposures取dominant风格（排除emergency，除非只有它）。"""
    if not exposures:
        return "heuristic_equilibrium"
    candidates = [(s, w) for s, w in exposures.items() if s != "emergency"]
    if not candidates:
        return "emergency"
    return max(candidates, key=lambda t: t[1])[0]


def _pos_size_usdt(pos: Any) -> float:
    """从持仓对象近似名义仓位：amount × entry × leverage（防御性兜底0）。"""
    try:
        amount = float(getattr(pos, "amount", 0.0) or 0.0)
        entry = float(getattr(pos, "entry_price", 0.0) or 0.0)
        lev = float(getattr(pos, "leverage", 1.0) or 1.0)
        if entry <= 0 or amount <= 0:
            return 0.0
        return abs(amount * entry * lev)
    except Exception:  # noqa: BLE001
        return 0.0


def enforce_cluster_cap(
    positions_dict: Dict[str, Any],
    new_direction: str,
    new_style_exposures: Dict[str, float],
    new_size_usdt: float,
    total_equity: float,
    cap_pct: float = 0.50,
) -> bool:
    """§G9 聚类约束：同方向×同风格桶 合并仓位 超过 equity×cap_pct → False（拒绝开仓）。

    纯函数、无I/O；异常时fail-open=True（不阻塞交易）。
    """
    try:
        # --- 防御：参数合理性 ---
        if total_equity <= 0 or new_size_usdt <= 0:
            return True  # 权益0或无新开仓 → 无需约束（fail-open安全）
        cap_pct_f = float(cap_pct) if cap_pct else 0.50
        cap_usdt = float(total_equity) * max(0.0, min(1.0, cap_pct_f))

        # --- 确定新开仓的桶 key ---
        new_dir_norm = "long" if str(new_direction or "").lower().startswith("l") else "short"
        new_style = _dominant_style_from_exposures(new_style_exposures or {})
        target_bucket = (new_dir_norm, new_style)

        # --- 遍历已有持仓，累加同桶 size ---
        bucket_sum = 0.0
        for _coin, pos in (positions_dict or {}).items():
            try:
                p_dir = getattr(pos, "direction", "")
                p_dir_norm = "long" if str(p_dir or "").lower().startswith("l") else "short"
                enh = getattr(pos, "enhance_info", {}) or {}
                p_exp = enh.get("style_exposures", {}) or {}
                p_style = _dominant_style_from_exposures(p_exp)
                if (p_dir_norm, p_style) == target_bucket:
                    bucket_sum += _pos_size_usdt(pos)
            except Exception:  # noqa: BLE001
                continue

        # --- 加新开仓尺寸 → 判断是否超限 ---
        total = bucket_sum + float(new_size_usdt)
        if total > cap_usdt + 1e-9:  # 浮点容忍
            return False
        return True
    except Exception:  # noqa: BLE001 — fail-open：不阻塞交易
        return True


# ---------------------------------------------------------------------
# 内部分支触发器（§3.2 路径B：单笔持仓按 ctx.strategy_type 触发差异化分支）
#   分支名："breakout_fail"（假突破失败检测）
#           "mean_revert_target"（均值回归达标检测）
#   返回 bool：True=分支条件满足（可被ExitStrategy消费）
# ---------------------------------------------------------------------
def internal_branch_triggered(branch_name: str, ctx: Any) -> bool:
    """按 strategy_type × 分支名 的规则表，判断内部分支是否触发。

    纯函数：读取ctx的属性（不写入）；未知分支/异常 → False。
    """
    try:
        bn = str(branch_name or "").strip()
        stype = str(getattr(ctx, "strategy_type", "") or "").strip()

        if bn == "breakout_fail":
            # 假突破：strategy=breakout 且 紧震荡RANGE_TIGHT 且 age<1h（保护期内）且 浮亏≥1.5%
            if stype != "breakout":
                return False
            regime = str(getattr(ctx, "regime_label", "") or "").strip().upper()
            age = float(getattr(ctx, "age_hours", 0.0) or 0.0)
            upnl = float(getattr(ctx, "unrealized_pnl_pct", 0.0) or 0.0)
            if regime == "RANGE_TIGHT" and age < 1.0 and upnl < -0.015:
                return True
            return False

        if bn == "mean_revert_target":
            # 均值回归达标：strategy=mean_revert 且 浮盈≥2% 且 距离MA≤0.5%（回中）
            if stype != "mean_revert":
                return False
            upnl = float(getattr(ctx, "unrealized_pnl_pct", 0.0) or 0.0)
            dist = float(getattr(ctx, "distance_from_ma_pct", 0.0) or 0.0)
            if upnl >= 0.02 and dist <= 0.005:
                return True
            return False

        # 未知分支 → False（不意外触发）
        return False
    except Exception:  # noqa: BLE001
        return False


# =====================================================================
# __all__ 出口（路径B新增6个符号 + 原有8个）
# =====================================================================
__all__ = [
    "_normalize_0_100",
    "DecisionAuditRecord",
    "StrategySelection",
    "StrategyAlgoConfig",
    "StrategyAlgorithmLayer",
    "ASSET_CLASSES", "DEFAULT_NEUTRAL_SCORES", "STYLE_ORDER",
    # 路径 B 新增：
    "PORTFOLIO_MODE_CHAINS",
    "get_ranktp_allow_for_mode",
    "enforce_cluster_cap",
    "internal_branch_triggered",
    "_dominant_style_from_exposures",  # 导出便于单测/调试
    "_pos_size_usdt",
]
