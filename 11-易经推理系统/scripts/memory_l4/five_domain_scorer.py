#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五计庙算启发式评分 + 六决策不等式映射（阶段1最小影子模式）。

核心职责：
- 输入：按类cls的五维原始评分（five_scores[cls]）
- 输出：FiveDomainState（9字段按类Dict：war_state / allowed_style_mask / aggregate_position_cap_pct /
        cross_asset_multiplier / position_mult / forced_close_flags / front_layer_band /
        dimension_veto_flags / five_scores）
- 日级处理：五维打分结果 + 决策 -> 缓存到 five_domain_state.json，
  5min热路径只读缓存快照，不重算（§11.2 周期-职责矩阵：战略层=日级）。

所有决策不等式按§2.2写成"可代入不等式"，便于shadow审计时50字内秒答原因。
"""
from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .strategy_algo_layer import (  # noqa: E402 相对导入：避免sys.path根不同导致的ImportError
    ASSET_CLASSES,
    DEFAULT_NEUTRAL_SCORES,
    STYLE_ORDER,
    StrategyAlgorithmLayer,
    _normalize_0_100,
)


# =====================================================================
# FiveDomainState：战略层对外输出（9字段按类Dict，fail-open中性默认）
# =====================================================================
CLASSES = tuple(ASSET_CLASSES)  # 本地别名，便于书写


def _per_class_any() -> Dict[str, Any]:
    """工厂：按三类cls生成空Dict占位（fail-open填充时覆盖）。"""
    return {c: None for c in CLASSES}


def _per_class_bool_true_dict() -> Dict[str, Dict[str, bool]]:
    """工厂：allowed_style_mask 每类 6策略默认全True（fail-open等价mask全开）。"""
    return {c: {s: True for s in STYLE_ORDER} for c in CLASSES}


def _per_class_veto_flags() -> Dict[str, Dict[str, bool]]:
    """工厂：dimension_veto_flags 每类默认全False（无否决）。"""
    FLAG_NAMES = ("dao_xiao_40", "jiang_xiao_40", "fa_xiao_40",
                  "di_tian_shuang_cha", "dao_jv_fou_jue")
    return {c: {f: False for f in FLAG_NAMES} for c in CLASSES}


def _per_class_war_state() -> Dict[str, str]:
    """工厂：war_state 每类默认="ALLOW"（fail-open等价无闸门）。"""
    return {c: "ALLOW" for c in CLASSES}


def _per_class_1_0() -> Dict[str, float]:
    """工厂：position_mult / cross_asset_multiplier / aggregate_position_cap_pct 中性默认1.0。"""
    return {c: 1.0 for c in CLASSES}


def _per_class_band_none() -> Dict[str, Optional[Dict[str,float]]]:
    """工厂：front_layer_band 每类默认=None（不clip，方案B带宽全开）。"""
    return {c: None for c in CLASSES}


def _per_class_forced_close() -> Dict[str, Dict[str, bool]]:
    """工厂：forced_close_flags 每类 strong=False, protect=False。"""
    return {c: {"strong": False, "protect": False} for c in CLASSES}


def _per_class_scores() -> Dict[str, Dict[str, int]]:
    """工厂：five_scores 每类中性默认50/70（§4.2中性档）。"""
    return {c: dict(DEFAULT_NEUTRAL_SCORES) for c in CLASSES}


@dataclass
class FiveDomainState:
    """§15.4.1 战略层完整输出结构（9字段按类Dict）—— 默认值 = 完全 fail-open 中性：

    关闭 enable_five_domain 时，返回该结构的 default_fail_open()，
    字节等价战略层不存在，所有下游 min/max/叠加 操作都是 identity 操作。
    """
    # 1/9 是否允许交易（FREEZE=不出战 / COOLDOWN=5分滞回解冻中 / ALLOW=允许）
    war_state: Dict[str, str] = field(default_factory=_per_class_war_state)
    # 2/9 允许哪类策略（6策略 bool，emergency永远True）
    allowed_style_mask: Dict[str, Dict[str, bool]] = field(default_factory=_per_class_bool_true_dict)
    # 3/9 允许多大仓位 cap（§5.2 四档：≥85→1.00，75→0.80，60→0.50，<60→0.20）
    aggregate_position_cap_pct: Dict[str, float] = field(default_factory=_per_class_1_0)
    # 4/9 跨类相关性乘数（两类同时<60→三类全×0.8；否则1.0）
    cross_asset_multiplier: Dict[str, float] = field(default_factory=_per_class_1_0)
    # 5/9 是否需要降仓（维度否决→0.30/0.50，正常1.0）
    position_mult: Dict[str, float] = field(default_factory=_per_class_1_0)
    # 6/9 是否必须止损（strong=True=强平候选 / protect=True=保护模式SL收紧）
    forced_close_flags: Dict[str, Dict[str, bool]] = field(default_factory=_per_class_forced_close)
    # 7/9 前置层带宽（min/max范围；None=默认不clip）—— 方案B仅 np.clip 不乘系数
    front_layer_band: Dict[str, Optional[Dict[str, float]]] = field(default_factory=_per_class_band_none)
    # 8/9 5个维度否决旗标（dao/jiang/fa <40, 地天双差, 道否决）
    dimension_veto_flags: Dict[str, Dict[str, bool]] = field(default_factory=_per_class_veto_flags)
    # 9/9 五维评分原始快照（便于离线审计）
    five_scores: Dict[str, Dict[str, int]] = field(default_factory=_per_class_scores)

    # -----------------------------------------------------------------
    # 工厂：fail-open中性默认
    # -----------------------------------------------------------------
    @classmethod
    def default_fail_open(cls) -> "FiveDomainState":
        """§15.4.1表：所有字段取中性默认值——战略层关断时返回，字节等价无战略层。"""
        # cap默认0.20更严格（因为§5.2默认总分按中性50是<60档）→ 但fail-open要求=1.0不改变旧链路
        state = cls()
        # 上面的_factory已让 war_state=ALLOW/mask全T / mult=1.0 / flags=False / band=None
        # 显式校准 aggregate_position_cap_pct[c] = 1.0 for ALL c（避免默认 0.20 收紧）
        for c in CLASSES:
            state.aggregate_position_cap_pct[c] = 1.0
        return state

    # -----------------------------------------------------------------
    # 持久化：five_domain_state.json 日级缓存（热路径只读）
    # -----------------------------------------------------------------
    def to_json(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self._to_serializable(), f, ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, path: Path, fallback_on_error: bool = True) -> "FiveDomainState":
        """读取缓存；文件不存在/损坏 → 返回默认fail_open（F1 fail-open）。"""
        try:
            p = Path(path)
            if not p.exists():
                return cls.default_fail_open()
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return cls._from_serializable(data)
        except Exception:  # noqa: BLE001
            if fallback_on_error:
                return cls.default_fail_open()
            raise

    def _to_serializable(self) -> Dict[str, Any]:
        """numpy → 原生；避免JSON序列化失败。"""
        def clean(o):
            if isinstance(o, (np.integer,)): return int(o)
            if isinstance(o, (np.floating,)): return float(o)
            if isinstance(o, np.ndarray): return o.tolist()
            if isinstance(o, dict): return {k: clean(v) for k,v in o.items()}
            if isinstance(o, (list, tuple)): return [clean(x) for x in o]
            return o
        return clean(asdict(self))

    @classmethod
    def _from_serializable(cls, data: Dict[str, Any]) -> "FiveDomainState":
        # 取默认值；再用data覆盖存在的键；缺失自动默认 → R1白名单兼容
        defaults = asdict(cls.default_fail_open())
        for k in defaults.keys():
            if k in data:
                defaults[k] = data[k]
        return cls(**defaults)


# =====================================================================
# FiveDomainHeuristicScorer：启发式打分 + 决策不等式映射（§2.2）
# =====================================================================
class FiveDomainHeuristicScorer:
    """
    §2.2 全部决策不等式映射集中在一个函数 _apply_decision_rules()：
      6个核心问题 → 6类输出，按类cls完全独立。
    """

    # §4.2 三类资产差异化权重（和为 1.00，TDD 断言）
    WEIGHTS_BY_CLASS: Dict[str, Dict[str, float]] = {
        # 加密：政策一致性最重要 → dao 30%；趋势结构→地25%
        "crypto_usdt":    {"dao": 0.30, "tian": 0.15, "di": 0.25, "jiang": 0.15, "fa": 0.15},
        # 美股：基本面/财报季更强 → jiang 提升到 18%，天12
        "us_stock":       {"dao": 0.30, "tian": 0.12, "di": 0.25, "jiang": 0.18, "fa": 0.15},
        # 黄金：宏观（实际利率/美元指数）= 天 权重提升 22%
        "precious_metal": {"dao": 0.28, "tian": 0.22, "di": 0.20, "jiang": 0.15, "fa": 0.15},
    }
    # 健康性断言：权重和 == 1.00（每个类都要，单元测试启动即assert）
    for _cls, _w in WEIGHTS_BY_CLASS.items():
        assert abs(sum(_w.values()) - 1.00) < 1e-6, (
            f"[FiveDomainHeuristicScorer] WEIGHTS_BY_CLASS[{_cls}] 权重和≠1：{_w}"
        )
    del _cls, _w  # 清理类命名空间

    def __init__(
        self,
        enable: bool = False,  # ★ 总开关 enable_five_domain 默认False=F1 fail-open
        state_cache_path: Optional[Path] = None,
    ):
        self.enable = bool(enable)
        self.state_cache_path = Path(state_cache_path) if state_cache_path else (
            Path(__file__).resolve().parent / "runtime" / "five_domain_state.json"
        )
        # ★ FIX legacy#1/2：5 分滞回仅限**同进程内**连续 tick 有效（防止 5 分钟波动导致 FREEZE/ALLOW 来回切）。
        #   跨进程/单元测试 重新构造 Scorer 时，上一轮决策记忆清零：prev_ws=ALLOW。
        #   否则从全局 runtime/*.json 读取到旧进程的 COOLDOWN，会把 total<65 的合理判定锁死在 COOLDOWN，
        #   导致 dao<40 → FREEZE、total≥60 → ALLOW 等决策不等式永远无法生效。
        #   文件缓存仍用于 persist=True，供下游（polling_trader）消费 war_state/cap。
        self._last_state = FiveDomainState.default_fail_open()

    # =================================================================
    # 对外：score_and_decide —— 日级打分+决策 → 返回 FiveDomainState
    # =================================================================
    def score_and_decide(
        self,
        raw_scores_by_class: Optional[Dict[str, Dict[str, int]]] = None,
        persist: bool = False,
    ) -> FiveDomainState:
        """
        参数：
            raw_scores_by_class[c] = {"dao":0-100, "tian":0-100, "di":0-100, "jiang":0-100, "fa":0-100}
                传 None → 用 DEFAULT_NEUTRAL_SCORES（但总开关=False时还是返回默认fail-open）
        """
        # ★ F1 fail-open：enable=False → 返回完全中性默认值（字节等价五计不存在）
        if not self.enable:
            neutral = FiveDomainState.default_fail_open()
            if persist:
                neutral.to_json(self.state_cache_path)
            self._last_state = neutral
            return neutral

        try:
            # 防御：补齐不存在的类/维度 → 用中性默认值
            scores_by_cls: Dict[str, Dict[str,int]] = {}
            for cls in CLASSES:
                given = (raw_scores_by_class or {}).get(cls, {}) or {}
                cleaned = {}
                for dim in DEFAULT_NEUTRAL_SCORES.keys():
                    val = given.get(dim, DEFAULT_NEUTRAL_SCORES[dim])
                    cleaned[dim] = _normalize_0_100(val, scale=1.0)  # 已是0-100 → scale=1确保int/边界
                scores_by_cls[cls] = cleaned
            # 决策不等式映射（核心）
            state = self._apply_decision_rules(scores_by_cls)
        except Exception:  # noqa: BLE001 — F1 异常降级：默认fail-open
            state = FiveDomainState.default_fail_open()

        if persist:
            try:
                state.to_json(self.state_cache_path)
            except Exception:  # noqa: BLE001 — 持久化失败不阻塞主流程
                pass
        self._last_state = state
        return state

    # =================================================================
    # 内部：_weighted_total（§4.1 五维加权汇总庙算总分）
    # =================================================================
    def _weighted_total(self, scores_cls: Dict[str,int], cls: str) -> int:
        w = self.WEIGHTS_BY_CLASS.get(cls, self.WEIGHTS_BY_CLASS["crypto_usdt"])
        assert abs(sum(w.values()) - 1.00) < 1e-6, f"[{cls}] 权重和≠1：{w}"
        return int(round(sum(scores_cls.get(k, DEFAULT_NEUTRAL_SCORES[k]) * ww for k, ww in w.items())))

    # =================================================================
    # 内部核心：_apply_decision_rules（6决策不等式 按类独立）
    # =================================================================
    def _apply_decision_rules(self, scores_by_cls: Dict[str, Dict[str,int]]) -> FiveDomainState:
        """§2.2 6 决策不等式映射。所有条件写成可代入不等式+阈值+代入值，便于shadow审计。

        每类cls独立循环，变量互不共享 → TDD #9-12 按类独立性保证。
        """
        state = FiveDomainState.default_fail_open()  # 先全中性，再逐类覆写
        # ── 先跑三类总分，便于后面跨类相关性乘数 ──
        totals = {c: self._weighted_total(scores_by_cls[c], c) for c in CLASSES}

        for cls in CLASSES:
            s = scores_by_cls[cls]
            total = totals[cls]
            state.five_scores[cls] = dict(s)

            # ===== 不等式0：维度否决旗标（影响 position_mult / forced_close / veto） =====
            veto = state.dimension_veto_flags[cls] = {
                "dao_xiao_40":     (s["dao"]   < 40),
                "jiang_xiao_40":   (s["jiang"] < 40),
                "fa_xiao_40":      (s["fa"]    < 40),
                "di_tian_shuang_cha": (s["di"] < 40 and s["tian"] < 40),
                "dao_jv_fou_jue":  (s["dao"]   < 40),
            }

            # ===== 不等式1：war_state（Q1+Q6：是否允许交易+空仓等待）=====
            # 解冻滞回5分：FREEZE/COOLDOWN → 下次需 total≥65 才解冻回ALLOW
            prev_ws = getattr(self._last_state, "war_state", {}).get(cls, "ALLOW")
            if (prev_ws in ("FREEZE", "COOLDOWN")) and (total < 65):
                state.war_state[cls] = "COOLDOWN"
            elif (total < 60) or (veto["dao_jv_fou_jue"] is True):
                state.war_state[cls] = "FREEZE"
            else:
                state.war_state[cls] = "ALLOW"

            # ===== 不等式2：aggregate_position_cap_pct（Q3：允许多大仓位）=====
            if   total >= 85: cap = 1.00
            elif total >= 75: cap = 0.80
            elif total >= 60: cap = 0.50
            else:             cap = 0.20
            state.aggregate_position_cap_pct[cls] = float(cap)

            # ===== 不等式3：allowed_style_mask（Q2：允许哪类策略）=====
            m = state.allowed_style_mask[cls]
            m["emergency"]     = True   # R7红线：应急策略永不下架（强制赋值）
            # ★ 极差场景（FREEZE：total<60/dao否决/法否决）→ 除emergency外全部下架（只留应急豁免）
            is_extreme_bad = (total < 60) or veto["dao_jv_fou_jue"] or veto["fa_xiao_40"]
            if is_extreme_bad:
                m["trend_follow"]  = False
                m["breakout"]      = False
                m["mean_revert"]   = False
                m["momentum"]      = False
                m["volatility"]    = False
            else:
                # 非极差：按不等式正常放行（符合project_memory维度否决规则）
                m["trend_follow"]  = bool(total >= 70 and not veto["di_tian_shuang_cha"])
                m["breakout"]      = bool(total >= 65 and s["di"] >= 60)
                m["mean_revert"]   = bool(40 <= s["di"] <= 60)
                m["momentum"]      = bool(s["dao"] >= 70)
                m["volatility"]    = bool(veto["di_tian_shuang_cha"])  # 双差极端波动 → 波动率策略允许
            # 注意：emergency 永远 True，其余可被否决；且按类独立不串值（TDD #9/#10）。

            # ===== 不等式4：position_mult（Q5：是否需要降仓）=====
            if veto["dao_xiao_40"] or veto["jiang_xiao_40"]:
                mult = 0.30
            elif veto["fa_xiao_40"]:
                mult = 0.50
            else:
                mult = 1.0
            state.position_mult[cls] = float(mult)

            # ===== 不等式5：forced_close_flags（Q4：是否必须止损）=====
            fc = state.forced_close_flags[cls]
            fc["strong"]  = bool(veto["fa_xiao_40"])      # 法<40 = 纪律崩溃 → 强平候选
            fc["protect"] = bool(total < 50)               # 总分过低 → 收紧SL保护模式

            # ===== 不等式6：front_layer_band（§15.5.3 FRONT_BAND_RULES 映射）=====
            state.front_layer_band[cls] = StrategyAlgorithmLayer._compute_front_layer_band(s, total)

        # ===== 跨类相关性乘数（§5.3：2类同时<60 → 三类全部×0.8）=====
        low_count = sum(1 for c in CLASSES if totals[c] < 60)
        cross_mult = 0.8 if low_count >= 2 else 1.0
        for cls in CLASSES:
            state.cross_asset_multiplier[cls] = float(cross_mult)

        return state


__all__ = [
    "FiveDomainState",
    "FiveDomainHeuristicScorer",
    "CLASSES",
]
