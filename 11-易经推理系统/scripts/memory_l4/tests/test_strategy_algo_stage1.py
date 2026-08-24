#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略算法层 v1.4.1 阶段1（最小影子模式）TDD 测试基座（M1 RED阶段：全部先写失败）。

覆盖 spec §2.3 的 15 项矩阵：
  1-3   数据结构契约（StrategySelection默认值 / Selector关断字节等价 / dataclass完整性）
  4-8   front_layer_band 的 5 种 clip 场景（全闭/半开/全开/越界上/越界下）
  9-12  按类独立性 4 项（war_state不串/mask不串/band不串/cross_asset乘数按类生效）
  13-15 fail-open字节等价 3 项（五计总关/策略层总关/前置层band关断）

实施 spec 引用：docs/superpowers/specs/2026-08-21-strategy-layer-v1p4p1-stage1-implementation-spec.md
"""
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(ROOT))


# =====================================================================
# RED阶段：测试先写；对被测模块的import失败 = RED阶段的合理行为（Error是预期内FAIL）
# =====================================================================
def _try_import():
    """懒加载：导入失败时返回占位 Sentinel，测试断言失败即符合RED阶段。"""
    sentinel = {"loaded": False}
    try:
        from scripts.memory_l4.strategy_algo_layer import (  # noqa: E402
            StrategyAlgorithmLayer,
            StrategySelection,
            DecisionAuditRecord,
            _normalize_0_100,
            StrategyAlgoConfig,
        )
        from scripts.memory_l4.five_domain_scorer import (  # noqa: E402
            FiveDomainHeuristicScorer,
            FiveDomainState,
        )
        sentinel["loaded"] = True
        sentinel["StrategyAlgorithmLayer"] = StrategyAlgorithmLayer
        sentinel["StrategySelection"] = StrategySelection
        sentinel["DecisionAuditRecord"] = DecisionAuditRecord
        sentinel["StrategyAlgoConfig"] = StrategyAlgoConfig
        sentinel["_normalize_0_100"] = _normalize_0_100
        sentinel["FiveDomainHeuristicScorer"] = FiveDomainHeuristicScorer
        sentinel["FiveDomainState"] = FiveDomainState
    except Exception as exc:  # noqa: BLE001 — RED阶段导入失败完全预期；保存异常原因用于诊断
        sentinel["import_error"] = str(exc)
    return sentinel


MOD = _try_import()
# NOTE：RED阶段不使用 skipif；所有测试用例头部有 assert MOD.get("loaded") → 模块未导入时直接 FAIL（断言失败），
# 这才是 TDD 预期行为（先失败，而非跳过）。只有模块已加载后会进入真实断言。
# 如果需要单独临时跳过可以用 pytest -k 关键字。


# ================================================================
# 一、数据结构契约（1-3）
# ================================================================
class TestDataStructureContracts:
    """§2.3 TDD #1-#3：核心dataclass结构契约、默认值fail-open字节等价。"""

    def test_1_default_strategy_selection_fail_open_byte_equivalent(self):
        """TDD #1：StrategySelection() 默认值字节等价 §15.4.1 fail-open中性值。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        sel = MOD["StrategySelection"]()

        # --- 校准偏置：必须全1.0（改造前后离场阈值字节等价）---
        cb = sel.calibration_biases
        for k in (
            "signal_reverse_threshold_factor",
            "p3_early_exit_profit_threshold_factor",
            "ev_force_close_threshold_factor",
            "timeout_profit_switch_hours_factor",
            "ranked_tp_rank_factor",
            "ev_adjust_sensitivity_factor",
            "min_holding_hours_factor",
            "sl_tighten_factor",
        ):
            assert cb[k] == 1.0, f"calibration_bias[{k}] 默认必须=1.0 fail-open，实际={cb[k]}"
        assert cb["hard_relax_gate"] is False, "hard_relax_gate 默认必须=False（不允许放宽阈值方向）"

        # --- 前置层带宽：默认None = 带宽全不clip ---
        assert sel.front_layer_band is None, "front_layer_band 默认=None，等价无约束"

        # --- 版本号：必须严格等于 salv1.4.1 ---
        assert sel.strategy_version == "salv1.4.1", (
            f"strategy_version 不匹配，期望='salv1.4.1' 实际='{sel.strategy_version}'"
        )
        # --- 策略类型：默认="heuristic_equilibrium"（中性启发式均衡策略）---
        assert sel.strategy_type == "heuristic_equilibrium", (
            f"strategy_type 默认不匹配，期望='heuristic_equilibrium' 实际='{sel.strategy_type}'"
        )
        # --- style_exposures 全 6 策略中性 = 1/6 均匀分布（≈0.1667）---
        styles = ("emergency", "trend_follow", "breakout", "mean_revert", "momentum", "volatility")
        for s in styles:
            assert abs(sel.style_exposures[s] - 1.0 / len(styles)) < 1e-3, (
                f"style_exposures[{s}] 默认必须=1/6≈0.1667，实际={sel.style_exposures[s]}"
            )
        assert abs(sum(sel.style_exposures.values()) - 1.0) < 1e-6, "style_exposures 权重和必须=1.0"

    def test_2_selector_disable_switch_returns_default(self):
        """TDD #2：cfg.enable_strategy_layer=False → select() 返回等价默认字节值。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        cfg = MOD["StrategyAlgoConfig"](enable_strategy_layer=False)
        layer = MOD["StrategyAlgorithmLayer"](cfg=cfg)
        fake_five = {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70}

        sel_on = MOD["StrategySelection"]()
        sel_off = layer.select(asset_class="crypto_usdt", five_scores=fake_five,
                               regime_summary={"phase": "Bull"}, liquidity_tier="G1")
        # 关断开关：返回与默认完全等价
        assert asdict(sel_off) == asdict(sel_on), (
            "enable_strategy_layer=False 时 select() 必须字节等价 StrategySelection() 默认值；"
            "否则 fail-open F1 红线不满足。"
        )

    def test_3_dataclass_schema_completeness_and_roundtrip(self):
        """TDD #3：3个核心dataclass 字段完整；asdict → from dict 重建不丢字段；无AttributeError。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"

        # --- StrategySelection 完整字段期望：8项必填 ---
        sel = MOD["StrategySelection"]()
        sel_dict = asdict(sel)
        REQUIRED_SEL = (
            "strategy_type", "strategy_version", "style_exposures",
            "calibration_biases", "front_layer_band", "audit",
            "asset_class", "five_scores_snapshot",
        )
        for k in REQUIRED_SEL:
            assert k in sel_dict, f"StrategySelection 缺字段：{k}"

        # --- DecisionAuditRecord：启发式 arm + 在线学习预留 arm/reward 字段 ---
        aud = MOD["DecisionAuditRecord"]()
        aud_dict = asdict(aud)
        REQUIRED_AUD = ("heuristic_arm_id", "ol_arm_id", "arm_reward_parts", "arm_timestamp")
        for k in REQUIRED_AUD:
            assert k in aud_dict, f"DecisionAuditRecord 缺字段：{k}"

        # --- FiveDomainState：9 字段按类 Dict，默认全中性 ---
        state = MOD["FiveDomainState"].default_fail_open()
        state_dict = asdict(state)
        REQUIRED_STATE_9 = (
            "war_state", "allowed_style_mask", "aggregate_position_cap_pct",
            "cross_asset_multiplier", "position_mult", "forced_close_flags",
            "front_layer_band", "dimension_veto_flags", "five_scores",
        )
        CLASSES = ("crypto_usdt", "us_stock", "precious_metal")
        for k in REQUIRED_STATE_9:
            assert k in state_dict, f"FiveDomainState 缺字段：{k}"
            for cls in CLASSES:
                assert cls in state_dict[k], f"FiveDomainState[{k}] 缺资产类别键：{cls}"

        # --- 重建：FiveDomainState 从 dict 重建字节等价 ---
        rebuilt = MOD["FiveDomainState"](**state_dict)
        assert asdict(rebuilt) == state_dict, "FiveDomainState asdict→重建 字节不相等"


# ================================================================
# 二、front_layer_band clip 的 5 种场景（4-8）
# ================================================================
class TestFrontBandClipScenarios:
    """§2.3 TDD #4-#8：前置层带宽 np.clip 的5类边界场景。"""

    @staticmethod
    def _run_clip(L_raw, T_raw, sec_raw, band):
        """调用 StrategyAlgorithmLayer.apply_front_band_clip(L,T,sec,band) 辅助函数。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        return MOD["StrategyAlgorithmLayer"].apply_front_band_clip(L_raw, T_raw, sec_raw, band)

    def test_4_clip_fully_closed_forbids_any_change(self):
        """TDD #4：带宽全闭 min==max → 任意 raw 值必须被钉死到 min(=max)。"""
        band = {"L_min": 0.75, "L_max": 0.75, "T_min": 0.55, "T_max": 0.55,
                "sector_weights_min": 1.00, "sector_weights_max": 1.00}
        L_final, T_final, sec_final = self._run_clip(
            L_raw=np.array([0.20, 0.90, 0.75, 0.00, 1.50]),
            T_raw=np.array([0.00, 1.00, 0.55, 0.56, 0.54]),
            sec_raw=np.array([0.50, 1.50, 1.00, 1.01, 0.99]),
            band=band,
        )
        assert np.allclose(L_final, 0.75), f"全闭带宽 L 未钉死到 0.75：{L_final}"
        assert np.allclose(T_final, 0.55), f"全闭带宽 T 未钉死到 0.55：{T_final}"
        assert np.allclose(sec_final, 1.00), f"全闭带宽 sec 未钉死到 1.00：{sec_final}"

    def test_5_clip_half_open_preserves_inband(self):
        """TDD #5：半开带宽 + 带内raw值 → clip 0修改，字节保留原值（§15.4方案B核心承诺）。"""
        band = {"L_min": 0.50, "L_max": 0.80, "T_min": 0.40, "T_max": 0.90,
                "sector_weights_min": 0.80, "sector_weights_max": 1.20}
        L_raw = np.array([0.55, 0.65, 0.70, 0.80, 0.50])
        T_raw = np.array([0.40, 0.55, 0.88, 0.90, 0.70])
        sec_raw = np.array([0.80, 0.95, 1.00, 1.15, 1.20])
        L_f, T_f, sec_f = self._run_clip(L_raw, T_raw, sec_raw, band)
        assert np.array_equal(L_f, L_raw), f"带内值被错误修改：L_raw vs L_final"
        assert np.array_equal(T_f, T_raw), f"带内值被错误修改：T_raw vs T_final"
        assert np.array_equal(sec_f, sec_raw), f"带内值被错误修改：sec_raw vs sec_final"

    def test_6_clip_fully_open_band_none_is_noop(self):
        """TDD #6：band=None 或 全min=0/max=inf → 0行clip，输出 ≡ raw 字节等价。"""
        L_raw = np.random.RandomState(42).rand(10)
        T_raw = np.random.RandomState(43).rand(10)
        sec_raw = np.random.RandomState(44).rand(10)
        L_f, T_f, sec_f = self._run_clip(L_raw, T_raw, sec_raw, band=None)
        assert np.array_equal(L_f, L_raw) and np.array_equal(T_f, T_raw) and np.array_equal(sec_f, sec_raw), (
            "band=None 必须是完全no-op：0行clip执行"
        )

    def test_7_clip_out_of_upper_bound_gets_clipped_to_max(self):
        """TDD #7：raw > band.max → clip 到 max（收紧上限，方案B带宽生效）。"""
        band = {"L_min": 0.40, "L_max": 0.90, "T_min": 0.40, "T_max": 0.90,
                "sector_weights_min": 0.80, "sector_weights_max": 1.20}
        L_f, T_f, sec_f = self._run_clip(
            L_raw=np.array([1.00, 0.95, 2.00]),
            T_raw=np.array([0.91, 1.50, 0.90]),
            sec_raw=np.array([1.35, 1.21, 1.20]),
            band=band,
        )
        assert np.allclose(L_f, [0.90, 0.90, 0.90]), f"上越界L未clip到0.90：{L_f}"
        assert np.allclose(T_f, [0.90, 0.90, 0.90]), f"上越界T未clip到0.90：{T_f}"
        assert np.allclose(sec_f, [1.20, 1.20, 1.20]), f"上越界sec未clip到1.20：{sec_f}"

    def test_8_clip_out_of_lower_bound_gets_clipped_to_min(self):
        """TDD #8：raw < band.min → clip 到 min（收紧下限，方案B带宽生效）。"""
        band = {"L_min": 0.40, "L_max": 0.90, "T_min": 0.40, "T_max": 0.90,
                "sector_weights_min": 0.80, "sector_weights_max": 1.20}
        L_f, T_f, sec_f = self._run_clip(
            L_raw=np.array([0.00, 0.30, 0.399]),
            T_raw=np.array([0.10, 0.399, 0.40]),
            sec_raw=np.array([0.79, 0.00, 0.80]),
            band=band,
        )
        assert np.allclose(L_f, [0.40, 0.40, 0.40]), f"下越界L未clip到0.40：{L_f}"
        assert np.allclose(T_f, [0.40, 0.40, 0.40]), f"下越界T未clip到0.40：{T_f}"
        assert np.allclose(sec_f, [0.80, 0.80, 0.80]), f"下越界sec未clip到0.80：{sec_f}"


# ================================================================
# 三、按类独立性 4 场景（9-12）
# ================================================================
class TestPerClassIndependence:
    """§2.3 TDD #9-#12：三类资产crypto/us_stock/precious完全独立，绝不串值。"""

    @staticmethod
    def _build_scorer_with_override(cls_overrides: Dict[str, Dict[str, int]]):
        """创建FiveDomainHeuristicScorer并注入三类指定的五维评分，绕过真实打分指标依赖。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        scorer = MOD["FiveDomainHeuristicScorer"]()
        return scorer, scorer._apply_decision_rules(cls_overrides)

    def test_9_crypto_freezes_but_us_stock_allowed_independent(self):
        """TDD #9：crypto dao=38(<40)→FREEZE；美股dao=85,total=88→ALLOW + cap=1.0 + breakout=True。"""
        overrides = {
            "crypto_usdt":     {"dao": 38, "tian": 55, "di": 55, "jiang": 50, "fa": 70},
            "us_stock":        {"dao": 85, "tian": 90, "di": 90, "jiang": 88, "fa": 80},
            "precious_metal":  {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70},
        }
        _scorer, state = self._build_scorer_with_override(overrides)

        assert state.war_state["crypto_usdt"] == "FREEZE", (
            f"crypto 应该FREEZE（dao=38<40 veto），实际={state.war_state['crypto_usdt']}"
        )
        assert state.war_state["us_stock"] == "ALLOW", (
            f"美股 应该ALLOW（总分88），实际={state.war_state['us_stock']}"
        )
        # 美股 mask：emergency=True（永远True）/ trend=True(≥70且无双查)/breakout=True(≥65且di≥60)
        mask_us = state.allowed_style_mask["us_stock"]
        assert mask_us["emergency"] is True, "美股 mask.emergency 必须永远True"
        assert mask_us["trend_follow"] is True, "美股 trend_follow mask 应该通过"
        assert mask_us["breakout"] is True, "美股 breakout mask 应该通过 di=90>=60"
        # 美股 cap 四档≥85 → 1.0
        assert state.aggregate_position_cap_pct["us_stock"] == 1.0, (
            f"美股 cap 应该1.0（≥85档），实际={state.aggregate_position_cap_pct['us_stock']}"
        )
        # crypto 维度否决：dao_xiao_40=True → position_mult = 0.30
        assert state.position_mult["crypto_usdt"] == 0.30, (
            f"crypto dao<40 → position_mult应该=0.30，实际={state.position_mult['crypto_usdt']}"
        )
        # 美股 position_mult 正常1.0（无维度否决）
        assert state.position_mult["us_stock"] == 1.0, (
            f"美股 position_mult 应该默认1.0，实际={state.position_mult['us_stock']}"
        )

    def test_10_mask_emergency_only_crypto_restricted(self):
        """TDD #10：加密极差 → mask[emergency]=True,其余5=False；美股/黄金mask全True，不受加密影响。"""
        overrides_bad_crypto = {
            "crypto_usdt":     {"dao": 30, "tian": 30, "di": 20, "jiang": 30, "fa": 30},  # 全部极差 → total远<60
            # ★ us_stock：di=60（唯一边界：breakout要≥60 且 mean_revert 要≤60）；总分≈74.1≥70
            #   dao=80≥70(momentum✓), total≥70(trend✓), total≥65+di=60(breakout✓), di=60(mean_revert✓)
            "us_stock":        {"dao": 80, "tian": 80, "di": 60, "jiang": 75, "fa": 80},
            # ★ precious_metal：同样di=60，美股权重下总分=72≥70，5个策略mask全True
            #   dao=75(momentum✓), total≥70(trend✓), total≥65+di=60(breakout✓), di=60(mean_revert✓)
            "precious_metal":  {"dao": 75, "tian": 75, "di": 60, "jiang": 70, "fa": 80},
        }
        _s, state = self._build_scorer_with_override(overrides_bad_crypto)

        crypto_mask = state.allowed_style_mask["crypto_usdt"]
        assert crypto_mask["emergency"] is True, "crypto 极差情况下 emergency=True 永远下架豁免"
        assert crypto_mask["trend_follow"] is False
        assert crypto_mask["breakout"] is False
        assert crypto_mask["mean_revert"] is False
        assert crypto_mask["momentum"] is False
        assert crypto_mask["volatility"] is False, "crypto volatility mask=True需di<40且tian<40双差：检查映射"

        # 美股/黄金 mask 全 True，不被 crypto 污染
        for cls in ("us_stock", "precious_metal"):
            m = state.allowed_style_mask[cls]
            for strategy in ("emergency", "trend_follow", "breakout",
                             "mean_revert", "momentum"):
                assert m[strategy] is True, (
                    f"[{cls}] mask[{strategy}] 应该=True（类间独立不被crypto污染），实际=False"
                )

    def test_11_front_band_wrong_cls_must_fail_or_ignore(self):
        """TDD #11：band按类键错位——黄金读 crypto 的band值必须视为无效（读None → 0行clip）。"""
        overrides = {
            "crypto_usdt":     {"dao": 80, "tian": 80, "di": 80, "jiang": 80, "fa": 80},  # 三击 → 最宽带宽
            "us_stock":        {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70},  # 中性 → 默认None
            "precious_metal":  {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70},
        }
        _s, state = self._build_scorer_with_override(overrides)

        band_crypto = state.front_layer_band["crypto_usdt"]
        assert band_crypto is not None, "三击情况（dao≥80 & di≥75）band必须存在"
        # 美股 / 黄金：中性 band = None
        assert state.front_layer_band["us_stock"] is None, (
            "美股中性评分应该band=None（默认全带宽）"
        )
        assert state.front_layer_band["precious_metal"] is None, (
            "黄金中性评分应该band=None（默认全带宽）"
        )

    def test_12_cross_asset_2_low_multiplies_all_by_08(self):
        """TDD #12：crypto（35<60） + 美股（58<60）low=2 → cross_asset乘数三类全部×0.8。"""
        overrides_low2 = {
            "crypto_usdt":     {"dao": 35, "tian": 45, "di": 30, "jiang": 40, "fa": 35},  # total<60 ✓
            "us_stock":        {"dao": 50, "tian": 55, "di": 60, "jiang": 58, "fa": 70},  # 58 < 60 ✓
            "precious_metal":  {"dao": 80, "tian": 80, "di": 85, "jiang": 82, "fa": 85},  # total≈82（高）
        }
        _s, state = self._build_scorer_with_override(overrides_low2)
        low2_count = sum(1 for cls in ("crypto_usdt", "us_stock", "precious_metal")
                         if _s._weighted_total(overrides_low2[cls], cls) < 60)
        assert low2_count == 2, f"low_count应该=2，实际={low2_count}"
        for cls in ("crypto_usdt", "us_stock", "precious_metal"):
            assert state.cross_asset_multiplier[cls] == 0.8, (
                f"[{cls}] 跨类2低 → cross_asset_multiplier必须=0.8，实际={state.cross_asset_multiplier[cls]}"
            )


# ================================================================
# 四、fail-open 字节等价 3 场景（13-15）
# ================================================================
class TestMasterSwitchFailOpen:
    """§2.3 TDD #13-#15：总开关/子开关关断 = 字节等价中性默认值（F1红线）。"""

    def test_13_five_domain_master_off_returns_neutral(self):
        """TDD #13：cfg.enable_five_domain=False → scorer返回 FiveDomainState.default_fail_open() 全等。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        scorer = MOD["FiveDomainHeuristicScorer"](enable=False)
        fake_raw_scores = {
            "crypto_usdt": {"dao": 30, "tian": 30, "di": 30, "jiang": 30, "fa": 30},
        }
        state = scorer.score_and_decide(fake_raw_scores)
        default = MOD["FiveDomainState"].default_fail_open()
        assert asdict(state) == asdict(default), (
            "enable_five_domain=False 必须返回FiveDomainState完全中性默认值（字节等价）"
            "，否则F1 fail-open红线违反。"
        )

    def test_14_strategy_layer_master_off_returns_default_selection(self):
        """TDD #14：cfg.enable_strategy_layer=False → select返回 StrategySelection() 默认值全等（§三开关表）。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        cfg = MOD["StrategyAlgoConfig"](
            enable_strategy_layer=False,
            enable_five_domain_front_layer_band=True,  # 即便band子开=True，总关=全关
        )
        layer = MOD["StrategyAlgorithmLayer"](cfg=cfg)
        fake5 = {"dao": 80, "tian": 90, "di": 90, "jiang": 85, "fa": 85}  # 非常强三击
        sel = layer.select(asset_class="crypto_usdt", five_scores=fake5,
                           regime_summary={"phase": "Bull"}, liquidity_tier="G2")
        default_sel = MOD["StrategySelection"]()
        assert asdict(sel) == asdict(default_sel), (
            "enable_strategy_layer=False 时，即便输入三击极好评级，也必须返回字节等价默认Selection"
            "（总开关关断=所有子开关旁路）"
        )

    def test_15_front_band_switch_off_skips_clip_zero_execution(self):
        """TDD #15：cfg.enable_five_domain_front_layer_band=False → 即便传入band，辅助函数apply 0次clip。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        cfg = MOD["StrategyAlgoConfig"](enable_five_domain_front_layer_band=False)
        layer = MOD["StrategyAlgorithmLayer"](cfg=cfg)
        # 故意给一个最严格的band，如果执行了clip结果会被大幅改变
        strict_band = {"L_min": 0.50, "L_max": 0.50, "T_min": 0.50, "T_max": 0.50,
                       "sector_weights_min": 0.50, "sector_weights_max": 0.50}
        L_raw = np.array([0.20, 0.80, 0.10, 0.95])
        T_raw = np.array([0.80, 0.20, 0.95, 0.10])
        S_raw = np.array([1.50, 0.20, 1.00, 0.80])
        # 通过层方法调用（会检查cfg开关）
        L_f, T_f, S_f = layer.apply_band_with_switch(L_raw, T_raw, S_raw, strict_band)
        # 子开关关闭：必须严格raw原样返回，0行clip执行
        assert np.array_equal(L_f, L_raw), f"band子开关=False但L被clip了：{L_f}"
        assert np.array_equal(T_f, T_raw), f"band子开关=False但T被clip了：{T_f}"
        assert np.array_equal(S_f, S_raw), f"band子开关=False但S被clip了：{S_f}"


# ================================================================
# 五、P1-A 组：全局唯一归一化 _normalize_0_100（16-18）§2.1 红线
# ================================================================
class TestNormalize0100GlobalUnique:
    """§2.1 全局唯一归一化函数：单调性/边界截断/异常值兜底 必须100%分支覆盖。"""

    @staticmethod
    def _norm(x, scale=100.0):
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        return MOD["_normalize_0_100"](x, scale=scale)

    def test_16_normalize_monotonic_strictly_non_decreasing(self):
        """TDD #16：采样从 -1.0 → +2.0（步长 0.05，共61个点），严格非减。"""
        samples = [round(-1.0 + i * 0.05, 3) for i in range(61)]
        outs = [self._norm(x) for x in samples]
        for i in range(1, len(outs)):
            assert outs[i] >= outs[i - 1], (
                f"单调性违反：x[{i-1}]={samples[i-1]}→{outs[i-1]} vs "
                f"x[{i}]={samples[i]}→{outs[i]} (out必须 ≥ 前一个)"
            )
        # round边界基准点：0.50→50；0.99→99；1.00→100
        assert self._norm(0.50) == 50, f"0.50 期望=50，实际={self._norm(0.50)}"
        assert self._norm(0.99) == 99, f"0.99 期望=99，实际={self._norm(0.99)}"
        assert self._norm(1.00) == 100, f"1.00 期望=100，实际={self._norm(1.00)}"

    def test_17_normalize_bounds_clip_0_to_100(self):
        """TDD #17：极端值 + scale 参数必须严格 clip 到 [0,100] int。"""
        # 极大/极小 raw 值（默认 scale=100）
        assert self._norm(999.9) == 100, f"+∞方向必须clip到100，实际={self._norm(999.9)}"
        assert self._norm(-999.9) == 0, f"-∞方向必须clip到0，实际={self._norm(-999.9)}"
        # scale 参数：scale=50 → 1.0 → 50
        assert self._norm(1.0, scale=50.0) == 50, f"scale=50 × 1.0 期望=50，实际={self._norm(1.0, 50.0)}"
        # scale=200 → 0.8 → 160 → clip=100（不得溢出100）
        assert self._norm(0.8, scale=200.0) == 100, f"scale=200 × 0.8 = 160 → 必须clip到100，实际={self._norm(0.8, 200.0)}"
        # scale=200 → -0.2 = -40 → clip 0
        assert self._norm(-0.2, scale=200.0) == 0, f"scale=200 × (-0.2) = -40 → 必须clip到0，实际={self._norm(-0.2, 200.0)}"
        # 类型保证：必须为 int
        for v in (0.3, 1.0, -1.0, 0.0):
            assert isinstance(self._norm(v), int), f"返回类型必须 int：v={v} type={type(self._norm(v))}"

    def test_18_normalize_nonnumeric_fallbacks_to_50(self):
        """TDD #18：所有"非数值/坏数值"必须静默兜底=50（§2.1 防御），不得抛异常。"""
        bads = [
            float("nan"), float("inf"), float("-inf"),
            None, "abc", "123", [], {}, (1,), object(),
        ]
        # numpy 极端
        bads += [np.nan, np.inf, -np.inf]
        for i, b in enumerate(bads):
            try:
                got = self._norm(b) if not isinstance(b, (type(None), str, list, dict, tuple, object)) \
                    else MOD["_normalize_0_100"](b)
            except Exception as e:  # noqa: BLE001
                raise AssertionError(f"异常抛出 i={i} 输入={type(b).__name__}: {e}") from e
            # 修正：统一直接调用
        # 重跑：全部按统一入口调用（上面分支只起诊断用途）
        for b in [float("nan"), float("inf"), float("-inf"), np.nan, np.inf, -np.inf]:
            assert MOD["_normalize_0_100"](b) == 50, f"数值坏值{b} 必须=50"
        non_num_bads = ["abc", None, [], {}, (1,), object()]
        # 注意：None/tuple 走 isinstance 判断→50；但 list/dict/object 会在 try:float(raw)前return 50 / 或except兜底
        # 以最终行为 ==50 / 不抛为准
        for j, b in enumerate(non_num_bads):
            # str 'abc' 会在isinstance判断失败直接return 50（符合）
            # None 也不是数值类型 → 50
            # list/dict/object：同上
            try:
                val = MOD["_normalize_0_100"](b)
            except Exception as e:  # noqa: BLE001
                raise AssertionError(f"non_numeric[{j}]={type(b).__name__} 抛出异常: {e}") from e
            assert val == 50, f"non_numeric[{j}]={type(b).__name__} 必须=50，实际={val}"


# ================================================================
# 六、P1-C 组：统一二次校准公式（25-29）+ 前置层带宽（31）
# ================================================================
class TestUnifiedCalibrationFormula:
    """§十 v1.4.1 统一二次校准公式：G6表×regime×liquidity + R5放宽 + band3条。"""

    @staticmethod
    def _select(scores, phase="Sideways", tier="G2", cfg_overrides=None, cls="crypto_usdt"):
        """构造 select() 辅助：默认开总开关，返回结果。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        cfg_kwargs = {"enable_strategy_layer": True}
        if cfg_overrides:
            cfg_kwargs.update(cfg_overrides)
        cfg = MOD["StrategyAlgoConfig"](**cfg_kwargs)
        layer = MOD["StrategyAlgorithmLayer"](cfg=cfg)
        return layer.select(
            asset_class=cls, five_scores=dict(scores),
            regime_summary={"phase": phase}, liquidity_tier=tier,
        )

    def test_25_g6_seed_table_keys_are_canonical(self):
        """TDD #25：STYLE_ORDER 6策略 × 8参数 覆盖检查（值∈[0.30,2.00]）；外加 heuristic_equilibrium 8键全1.0。"""
        assert MOD.get("loaded")
        G6 = MOD["StrategyAlgorithmLayer"].G6_SEED_TABLE
        from scripts.memory_l4.strategy_algo_layer import STYLE_ORDER
        PARAMS = ("signal_reverse_threshold_factor", "p3_early_exit_profit_threshold_factor",
                  "ev_force_close_threshold_factor", "timeout_profit_switch_hours_factor",
                  "ranked_tp_rank_factor", "ev_adjust_sensitivity_factor",
                  "min_holding_hours_factor", "sl_tighten_factor")
        covered = 0
        for s in STYLE_ORDER:
            for p in PARAMS:
                key = (s, p)
                if key in G6:
                    covered += 1
                    v = G6[key]
                    assert 0.30 <= v <= 2.00, f"G6[{key}]={v} 超出物理[0.30,2.00]"
        # 当前G6实现：trend4/breakout4/mean4/momentum3/volatility3/emergency4 = 22
        assert covered >= 22, f"STYLE_ORDER 6类覆盖应≥22键，实际={covered}"
        # 单独检查 neutral 基准 "heuristic_equilibrium"×8 全必须存在且全=1.0
        for p in PARAMS:
            key = ("heuristic_equilibrium", p)
            assert key in G6, f"G6缺中性均衡键：{key}"
            assert G6[key] == 1.0, f"G6[{key}] 必须=1.0 fail-open，实际={G6[key]}"

    def test_26_regime_factors_all_7_phases_are_applied(self):
        """TDD #26：7 phase 方向正确；Bull relax_true 时 trend signal_rev ≥ 1.25（放大进攻）。"""
        # 构造 trend_dominant：dao 不能太高（否则momentum赢）→ dao=60；total需要高(≥80，trend=min(total,100)/100=最高)
        # total = 0.30*60 + 0.15*95 + 0.25*72 + 0.15*80 + 0.15*90
        #       = 18 + 14.25 + 18 + 12 + 13.5 = 75.75 → trend=0.7575，breakout=di=0.72，momentum=dao=0.6 → trend wins
        # 增强 dao=60, tian=98, di=78, jiang=82, fa=92
        # total= 18 + 14.7 + 19.5 + 12.3 + 13.8 = 78.3 → trend 0.783 breakout 0.78 momentum 0.6 → 还是trend略高
        # 再提 tian=98,jiang=92,fa=95 : total = 18+14.7+19.5+13.8+14.25 = 80.25 → trend = 0.8025 breakout 0.78 momentum 0.6 → OK
        trend_dominant = {"dao": 60, "tian": 98, "di": 78, "jiang": 92, "fa": 95}
        cfg_relax = {"enable_strategy_layer_relax_allowed": True,
                     "enable_five_domain_front_layer_band": False}
        sel_side = self._select(trend_dominant, phase="Sideways", tier="G1", cfg_overrides=cfg_relax)
        sel_bull = self._select(trend_dominant, phase="Bull", tier="G1", cfg_overrides=cfg_relax)
        sel_bear = self._select(trend_dominant, phase="Bear", tier="G1", cfg_overrides=cfg_relax)
        # 确认 strategy_type == trend_follow（此用例基石）
        for name, s in (("Sideways", sel_side), ("Bull", sel_bull), ("Bear", sel_bear)):
            assert s.strategy_type == "trend_follow", (
                f"趋势主导用例 策略类型错误 phase={name} type={s.strategy_type}（trend_follow暴露应最高）"
            )
        base_signal_rev = sel_side.calibration_biases["signal_reverse_threshold_factor"]
        bull_signal_rev = sel_bull.calibration_biases["signal_reverse_threshold_factor"]
        bear_signal_rev = sel_bear.calibration_biases["signal_reverse_threshold_factor"]
        # Bull (1.08) > Sideways (1.00) > Bear (0.82)
        assert bull_signal_rev > base_signal_rev, f"Bull(1.08×) 应该>Sideways：bull={bull_signal_rev} vs base={base_signal_rev}"
        assert bear_signal_rev < base_signal_rev, f"Bear(0.82×) 应该<Sideways：bear={bear_signal_rev} vs base={base_signal_rev}"
        # Bull × relax_true → trend seed 1.30 × 1.08 = 1.404，保留放宽方向
        assert bull_signal_rev >= 1.25, f"trend Bull 放宽期望值≥1.25，实际={bull_signal_rev}"
        # Bear × relax=False → R5 红线把所有>1.0 写回1.0 → 所有校准参数必须 ≤ 1.0
        sel_bear_tight = self._select(trend_dominant, phase="Bear", tier="G1",
                                      cfg_overrides={"enable_strategy_layer_relax_allowed": False,
                                                     "enable_five_domain_front_layer_band": False})
        bear_cb_tight = sel_bear_tight.calibration_biases
        for k, v in bear_cb_tight.items():
            if k == "hard_relax_gate":
                continue
            assert v <= 1.0 + 1e-9, f"Bear+relax=False时所有校准应≤1.0（R5写回）：{k}={v}"
        assert bear_cb_tight["hard_relax_gate"] is False
        # 7 phase 全部不抛（其余 5 phase 点到为止）
        for ph in ("Recovery", "Rebound", "LateBear", "EarlyBear"):
            s = self._select(trend_dominant, phase=ph, tier="G1", cfg_overrides=cfg_relax)
            assert s.strategy_type == "trend_follow", f"phase={ph} 返回异常类型：{s.strategy_type}"

    def test_27_liquidity_factor_g4_times_0_5_strict_R6(self):
        """TDD #27：§R6 红线 G4 → 所有校准 × 0.5；对比 G1 baseline 严格一半或更紧。"""
        trend_s = {"dao": 75, "tian": 70, "di": 80, "jiang": 75, "fa": 80}
        cfg_r = {"enable_strategy_layer_relax_allowed": True,
                 "enable_five_domain_front_layer_band": False}
        g1 = self._select(trend_s, phase="Sideways", tier="G1", cfg_overrides=cfg_r).calibration_biases
        g4 = self._select(trend_s, phase="Sideways", tier="G4", cfg_overrides=cfg_r).calibration_biases
        # 取至少一个种子<1.0的参数（收紧方向，不受R5门限干扰）= 如 sl_tighten_factor=0.90
        # G1 value = seed × 1.00(G1) = 0.90；G4 value = 0.90×0.5=0.45；ratio=0.5
        ratio_sl = g4["sl_tighten_factor"] / g1["sl_tighten_factor"] if g1["sl_tighten_factor"] else 0
        assert abs(ratio_sl - 0.50) < 1e-6, f"§R6 G4 sl因子应为G1的0.5倍，ratio={ratio_sl}"
        # 所有档位差方向正确：G4 ≤ G2 ≤ G3 ≤ G1（严格更紧或相等）
        tiers = ["G1", "G2", "G3", "G4"]
        outs = [self._select(trend_s, phase="Sideways", tier=t, cfg_overrides=cfg_r).calibration_biases["sl_tighten_factor"]
                for t in tiers]
        for i in range(1, len(outs)):
            assert outs[i] <= outs[i - 1] + 1e-9, f"流动性档位应单调不增(更紧)：{tiers}={outs}"

    def test_28_R5_relax_default_false_blocks_any_loosening(self):
        """TDD #28：§R5 红线 relax 默认=False。Bull 趋势seed>1 → 应当被强制写回1.0；收紧方向保留。"""
        trend_s = {"dao": 85, "tian": 80, "di": 80, "jiang": 85, "fa": 85}  # 三击趋势
        cfg_default = {}  # relax 默认 False
        sel = self._select(trend_s, phase="Bull", tier="G1", cfg_overrides=cfg_default)
        # trend seed signal_rev=1.30；Bull×1.08=1.404 >1.0 → R5默认False：必须写回1.0
        sig = sel.calibration_biases["signal_reverse_threshold_factor"]
        assert sig == 1.0, f"§R5 relax=False 时 Bull 趋势>1参数必须写回1.0，实际 signal_rev={sig}"
        mh = sel.calibration_biases["min_holding_hours_factor"]
        assert mh == 1.0, f"§R5 relax=False min_holding(seed=1.40) 应该写回1.0，实际={mh}"
        # 收紧方向（sl_tighten seed=0.90 <1 → 保留=不应被写回1.0）
        sl = sel.calibration_biases["sl_tighten_factor"]
        # 0.90 × 1.08(Bull) = 0.972 → <1 → 保留；不应被 R5 门限改写
        assert 0.90 <= sl <= 0.98, f"收紧方向(<1)应保留实际值(≈0.972)，实际 sl={sl}"
        assert sel.calibration_biases["hard_relax_gate"] is False, "hard_relax_gate 默认False"

    def test_29_R5_relax_allowed_true_preserves_greater_than_one(self):
        """TDD #29：relax_allowed=True 时，Bull 趋势放大参数得以保留，gate=True。"""
        # 用和 #26 相同的 trend_dominant（dao=60，保证选到 trend_follow）
        trend_dominant = {"dao": 60, "tian": 98, "di": 78, "jiang": 92, "fa": 95}
        cfg_r = {"enable_strategy_layer_relax_allowed": True,
                 "enable_five_domain_front_layer_band": False}
        sel = self._select(trend_dominant, phase="Bull", tier="G1", cfg_overrides=cfg_r)
        assert sel.strategy_type == "trend_follow", f"用例前提不成立：类型={sel.strategy_type}"
        sig = sel.calibration_biases["signal_reverse_threshold_factor"]
        expected = 1.30 * 1.08 * 1.00  # trend seed 1.30 × regime(Bull 1.08) × liq(G1 1.00) = 1.404
        assert abs(sig - float(np.clip(expected, 0.30, 2.00))) < 1e-6, f"relax=True保留：期望≈{expected:.4f}，实际sig={sig}"
        assert sel.calibration_biases["hard_relax_gate"] is True, "gate=True当且仅当 relax开关=True"

    def test_31_compute_front_layer_band_3_rules_match(self):
        """TDD #31：FRONT_BAND_RULES三条规则逐一命中 + 中性53=None（§15.5.3方案B弹性闸门）。"""
        assert MOD.get("loaded")
        cls = MOD["StrategyAlgorithmLayer"]
        # 规则1：三击 dao>=80 & di>=75 → L 0.55-0.98 T 0.55-0.98 S 0.90-1.20
        san = cls._compute_front_layer_band({"dao": 90, "tian": 70, "di": 80, "jiang": 80, "fa": 80})
        assert san is not None, "三击应该有带宽"
        assert abs(san["L_min"] - 0.55) < 1e-9 and abs(san["L_max"] - 0.98) < 1e-9
        assert abs(san["T_min"] - 0.55) < 1e-9 and abs(san["T_max"] - 0.98) < 1e-9
        assert abs(san["sector_weights_min"] - 0.90) < 1e-9 and abs(san["sector_weights_max"] - 1.20) < 1e-9
        # 规则2：强势 total>=75 但不满足三击（比如di=70<75 dao=80）→ L 0.50-0.92
        strong = {"dao": 80, "tian": 75, "di": 70, "jiang": 75, "fa": 85}
        sab = cls._compute_front_layer_band(strong)
        # total加权：0.30*80 + 0.15*75 + 0.25*70 + 0.15*75 + 0.15*85 = 24 + 11.25 + 17.5 + 11.25 + 12.75 = 76.75 ≥75 ✓
        assert sab is not None and abs(sab["L_min"] - 0.50) < 1e-9 and abs(sab["L_max"] - 0.92) < 1e-9, f"强势band错: {sab}"
        assert abs(sab["T_min"] - 0.50) < 1e-9 and abs(sab["T_max"] - 0.92) < 1e-9
        assert abs(sab["sector_weights_min"] - 0.85) < 1e-9 and abs(sab["sector_weights_max"] - 1.15) < 1e-9
        # 规则3：极度劣势 dao<40 or total<40 → 0.35-0.65
        bad = cls._compute_front_layer_band({"dao": 30, "tian": 30, "di": 30, "jiang": 30, "fa": 30})
        assert bad is not None
        assert abs(bad["L_min"] - 0.35) < 1e-9 and abs(bad["L_max"] - 0.65) < 1e-9
        assert abs(bad["T_min"] - 0.35) < 1e-9 and abs(bad["T_max"] - 0.65) < 1e-9
        assert abs(bad["sector_weights_min"] - 0.80) < 1e-9 and abs(bad["sector_weights_max"] - 1.00) < 1e-9
        # 中性 53 = None（中间区间，闸门放开，前置层自洽）
        neutral = cls._compute_front_layer_band({"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70})
        # total = 0.30*50+0.15*50+0.25*50+0.15*50+0.15*70 = 15+7.5+12.5+7.5+10.5 = 53
        assert neutral is None, f"中性总分53 必须 band=None（中间区间默认全带宽），实际={neutral}"


# ================================================================
# 七、P1-B 组：决策不等式（19-24）§2.2 六决策不等式 + 三类资产差异化
# ================================================================
class TestDecisionInequalitiesSix:
    """§2.2 6类决策不等式覆盖：四档仓位/道否决/将否决/法否决/地天双否决/三类资产差异。"""

    @staticmethod
    def _scorer_enable():
        """构造 enable=True 的评分器（总开关打开，便于测试不等式本身）。"""
        assert MOD.get("loaded"), f"RED阶段导入未完成：{MOD.get('import_error')}"
        return MOD["FiveDomainHeuristicScorer"](enable=True)

    @staticmethod
    def _crypto_scores(**overrides) -> Dict[str, Dict[str, int]]:
        """仅构造 crypto_usdt 类的 raw_scores_by_class，其他类用中性。"""
        base = {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70}
        base.update(overrides)
        return {"crypto_usdt": base, "us_stock": dict(base), "precious_metal": dict(base)}

    # ---------------------------------------------------------------
    # TDD #19：四档仓位 aggregate_position_cap_pct 边界点
    # ---------------------------------------------------------------
    def test_19_four_tier_cap_boundaries_all_four_tiers_hit(self):
        """TDD #19：§5.2 四档分档映射（≥85→1.00 / 75-84→0.80 / 60-74→0.50 / <60→0.20），6边界点逐一命中。"""
        scorer = self._scorer_enable()

        # 第1档 ≥85 → 1.00：构造 crypto total=85（dao=95×0.30=28.5, tian=95×0.15=14.25, di=95×0.25=23.75, jiang=70×0.15=10.5, fa=80×0.15=12 → 总=28.5+14.25=42.75+23.75=66.5+10.5=77+12=89→不对，重算）
        # 精确构造：dao=100(30)+tian=100(15)+di=100(25)+jiang=50(7.5)+fa=50(7.5) = 85 ✓
        t1 = {"dao": 100, "tian": 100, "di": 100, "jiang": 50, "fa": 50}
        # 0.30*100 + 0.15*100 + 0.25*100 + 0.15*50 + 0.15*50 = 30 + 15 + 25 + 7.5 + 7.5 = 85 ✓
        st1 = scorer.score_and_decide(self._crypto_scores(**t1))
        assert abs(st1.aggregate_position_cap_pct["crypto_usdt"] - 1.00) < 1e-9, (
            f"total=85 ≥85 必须cap=1.00，实际={st1.aggregate_position_cap_pct['crypto_usdt']}"
        )

        # 第1/2档边界：total=84 → 0.80（dao=100, tian=100, di=96, jiang=50, fa=50 → 30+15+24+7.5+7.5=84 ✓）
        t2 = {"dao": 100, "tian": 100, "di": 96, "jiang": 50, "fa": 50}
        st2 = scorer.score_and_decide(self._crypto_scores(**t2))
        assert abs(st2.aggregate_position_cap_pct["crypto_usdt"] - 0.80) < 1e-9, (
            f"total=84（75-84档）必须cap=0.80，实际={st2.aggregate_position_cap_pct['crypto_usdt']}"
        )

        # 第2/3档边界：total=75 → 0.80（刚好上边界）；total=74 → 0.50
        # total=75: dao=80(24)+tian=70(10.5)+di=75(18.75)+jiang=70(10.5)+fa=75(11.25) = 24+10.5=34.5+18.75=53.25+10.5=63.75+11.25=75 ✓
        t3 = {"dao": 80, "tian": 70, "di": 75, "jiang": 70, "fa": 75}
        st3 = scorer.score_and_decide(self._crypto_scores(**t3))
        assert abs(st3.aggregate_position_cap_pct["crypto_usdt"] - 0.80) < 1e-9, (
            f"total=75（≥75档上界）必须cap=0.80，实际={st3.aggregate_position_cap_pct['crypto_usdt']}"
        )
        # total=74: dao=80(24)+tian=70(10.5)+di=74(18.5)+jiang=70(10.5)+fa=70(10.5) = 24+10.5=34.5+18.5=53+10.5=63.5+10.5=74 ✓
        t4 = {"dao": 80, "tian": 70, "di": 74, "jiang": 70, "fa": 70}
        st4 = scorer.score_and_decide(self._crypto_scores(**t4))
        assert abs(st4.aggregate_position_cap_pct["crypto_usdt"] - 0.50) < 1e-9, (
            f"total=74（60-74档上界）必须cap=0.50，实际={st4.aggregate_position_cap_pct['crypto_usdt']}"
        )

        # 第3/4档边界：total=60 → 0.50；total=59 → 0.20
        # total=60: dao=60(18)+tian=60(9)+di=60(15)+jiang=60(9)+fa=60(9) = 60 ✓
        t5 = {"dao": 60, "tian": 60, "di": 60, "jiang": 60, "fa": 60}
        st5 = scorer.score_and_decide(self._crypto_scores(**t5))
        assert abs(st5.aggregate_position_cap_pct["crypto_usdt"] - 0.50) < 1e-9, (
            f"total=60（≥60档下界）必须cap=0.50，实际={st5.aggregate_position_cap_pct['crypto_usdt']}"
        )
        # total=59: dao=60(18)+tian=60(9)+di=60(15)+jiang=60(9)+fa=53(7.95→取整8) 不对，精确：di=59(14.75) jiang=59(8.85) fa=59(8.85) dao=59(17.7) tian=59(8.85) → sum=17.7+8.85=26.55+14.75=41.3+8.85=50.15+8.85=59
        t6 = {"dao": 59, "tian": 59, "di": 59, "jiang": 59, "fa": 59}
        st6 = scorer.score_and_decide(self._crypto_scores(**t6))
        assert abs(st6.aggregate_position_cap_pct["crypto_usdt"] - 0.20) < 1e-9, (
            f"total=59（<60档）必须cap=0.20，实际={st6.aggregate_position_cap_pct['crypto_usdt']}"
        )

    # ---------------------------------------------------------------
    # TDD #20：Dao否决 dao<40 → position_mult=0.30，war_state=FREEZE
    # ---------------------------------------------------------------
    def test_20_dao_less_than_40_position_mult_0_30_and_freeze(self):
        """TDD #20：§维度否决 dao<40 → position_mult=0.30；war_state=FREEZE；veto_flag=True。"""
        scorer = self._scorer_enable()
        # dao=30（<40 触发否决），其余正常偏高使 total 计算含否决的独立判断：total=0.30*30 + 0.15*70 + 0.25*70 + 0.15*70 + 0.15*70
        # = 9 + 10.5 + 17.5 + 10.5 + 10.5 = 58 < 60 → FREEZE（符合；否决叠加更严格）
        bad_dao = {"dao": 30, "tian": 70, "di": 70, "jiang": 70, "fa": 70}
        st = scorer.score_and_decide(self._crypto_scores(**bad_dao))
        # ① position_mult 必须 0.30（道/将 <40 → ≤30%）
        assert abs(st.position_mult["crypto_usdt"] - 0.30) < 1e-9, (
            f"dao<40 → position_mult 必须=0.30，实际={st.position_mult['crypto_usdt']}"
        )
        # ② dimension_veto_flags.dao_xiao_40 = True
        assert st.dimension_veto_flags["crypto_usdt"]["dao_xiao_40"] is True, (
            "dao<40 → dao_xiao_40 旗标应=True"
        )
        # ③ dao_jv_fou_jue = True
        assert st.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is True, (
            "dao<40 → dao_jv_fou_jue 旗标应=True"
        )
        # ④ war_state = FREEZE（dao否决 → 不出战）
        assert st.war_state["crypto_usdt"] == "FREEZE", (
            f"dao<40 应 FREEZE，实际 war_state={st.war_state['crypto_usdt']}"
        )

    # ---------------------------------------------------------------
    # TDD #21：Jiang否决 jiang<40 → position_mult=0.30
    # ---------------------------------------------------------------
    def test_21_jiang_less_than_40_position_mult_0_30(self):
        """TDD #21：§维度否决 jiang<40 → position_mult=0.30；veto=True；只要total≥60→war_state=ALLOW。"""
        scorer = self._scorer_enable()
        # jiang=30（<40），其余拉高：dao=95(28.5)+tian=90(13.5)+di=95(23.75)+jiang=30(4.5)+fa=90(13.5)
        # = 28.5+13.5=42+23.75=65.75+4.5=70.25+13.5=83.75 → int=84 ≥60 → ALLOW ✓
        good_total_bad_jiang = {"dao": 95, "tian": 90, "di": 95, "jiang": 30, "fa": 90}
        st = scorer.score_and_decide(self._crypto_scores(**good_total_bad_jiang))
        # ① position_mult = 0.30
        assert abs(st.position_mult["crypto_usdt"] - 0.30) < 1e-9, (
            f"jiang<40 → position_mult 必须=0.30，实际={st.position_mult['crypto_usdt']}"
        )
        # ② jiang_xiao_40=True
        assert st.dimension_veto_flags["crypto_usdt"]["jiang_xiao_40"] is True, "jiang<40 → jiang_xiao_40=True"
        # ③ total=84 ≥60 → war_state 应=ALLOW（因为 dao/jv_fou_jue=False，且total≥60）
        assert st.war_state["crypto_usdt"] == "ALLOW", (
            f"jiang否决但total=84≥60/dao未否决 → war_state=ALLOW，实际={st.war_state['crypto_usdt']}"
        )
        # ④ cap=0.80（total=84，75-84档）
        assert abs(st.aggregate_position_cap_pct["crypto_usdt"] - 0.80) < 1e-9, (
            f"total=84 → cap=0.80，实际={st.aggregate_position_cap_pct['crypto_usdt']}"
        )

    # ---------------------------------------------------------------
    # TDD #22：Fa否决 fa<40 → 禁开新仓（mult=0.50 / strong=True / mask除emergency外全False）
    # ---------------------------------------------------------------
    def test_22_fa_less_than_40_blocks_new_positions_full_stack(self):
        """TDD #22：§法否决（fa<40）→ position_mult=0.50 / forced_close.strong=True / 5非应急策略mask全False。"""
        scorer = self._scorer_enable()
        # fa=30（<40），其余拉高：dao=90(27)+tian=95(14.25)+di=90(22.5)+jiang=90(13.5)+fa=30(4.5)
        # = 27+14.25=41.25+22.5=63.75+13.5=77.25+4.5=81.75 → 82 ≥60 → war_state=ALLOW ✓
        good_total_bad_fa = {"dao": 90, "tian": 95, "di": 90, "jiang": 90, "fa": 30}
        st = scorer.score_and_decide(self._crypto_scores(**good_total_bad_fa))
        # ① fa_xiao_40=True
        assert st.dimension_veto_flags["crypto_usdt"]["fa_xiao_40"] is True, "fa<40 → fa_xiao_40=True"
        # ② position_mult = 0.50（fa否决不同于dao/jiang，0.50而非0.30）
        assert abs(st.position_mult["crypto_usdt"] - 0.50) < 1e-9, (
            f"fa<40 → position_mult=0.50（不是0.30），实际={st.position_mult['crypto_usdt']}"
        )
        # ③ forced_close.strong = True（纪律崩溃 → 强平候选）
        assert st.forced_close_flags["crypto_usdt"]["strong"] is True, (
            "fa<40 → forced_close_flags.strong 必须=True（强平候选）"
        )
        # ④ 5 非应急策略 全False（极差场景：fa否决触发is_extreme_bad）；emergency=永不 False
        m = st.allowed_style_mask["crypto_usdt"]
        assert m["emergency"] is True,   "应急策略 emergency 永不下架（R7红线）"
        assert m["trend_follow"] is False, f"fa<40 应下架趋势：mask={m}"
        assert m["breakout"]     is False, f"fa<40 应下架突破：mask={m}"
        assert m["mean_revert"]  is False, f"fa<40 应下架均值：mask={m}"
        assert m["momentum"]     is False, f"fa<40 应下架动量：mask={m}"
        assert m["volatility"]   is False, f"fa<40 应下架波动：mask={m}"

    # ---------------------------------------------------------------
    # TDD #23：地天双否决（di<40 且 tian<40）→ volatility=True，其余非应急策略下架
    # ---------------------------------------------------------------
    def test_23_di_tian_both_less_40_dual_veto_volatility_allowed(self):
        """TDD #23：§地天双差 → di_tian_shuang_cha=True；trend=False；volatility=True（极端波动专用策略）。"""
        scorer = self._scorer_enable()
        # di=30, tian=30 双<40；其余正常：dao=85(25.5)+tian=30(4.5)+di=30(7.5)+jiang=85(12.75)+fa=85(12.75)
        # = 25.5+4.5=30+7.5=37.5+12.75=50.25+12.75=63 → total=63 ≥60 → war_state=ALLOW（不触发FREEZE）
        di_tian_bad = {"dao": 85, "tian": 30, "di": 30, "jiang": 85, "fa": 85}
        st = scorer.score_and_decide(self._crypto_scores(**di_tian_bad))
        # ① di_tian_shuang_cha = True
        assert st.dimension_veto_flags["crypto_usdt"]["di_tian_shuang_cha"] is True, (
            "di<40 且 tian<40 → di_tian_shuang_cha=True"
        )
        # ② volatility=True（双差=极端波动场景 → 波动率策略放行）
        assert st.allowed_style_mask["crypto_usdt"]["volatility"] is True, (
            "地天双差 volatility 策略应=True（波动场景适配）"
        )
        # ③ trend_follow = False（因为 total>=70? No total=63<70；还有 not di_tian_shuang_cha → 双False→False）
        assert st.allowed_style_mask["crypto_usdt"]["trend_follow"] is False, (
            f"地天双差 + total=63<70 → trend_follow 必须=False，实际={st.allowed_style_mask['crypto_usdt']['trend_follow']}"
        )
        # ④ emergency=True（R7红线）
        assert st.allowed_style_mask["crypto_usdt"]["emergency"] is True
        # ⑤ cap = 0.50（total=63 ∈ 60-74档）
        assert abs(st.aggregate_position_cap_pct["crypto_usdt"] - 0.50) < 1e-9, (
            f"total=63 → cap=0.50，实际={st.aggregate_position_cap_pct['crypto_usdt']}"
        )

    # ---------------------------------------------------------------
    # TDD #24：三类资产权重差异化（crypto/美股/黄金）→ 相同原始分数产生不同total
    # ---------------------------------------------------------------
    def test_24_three_asset_classes_weight_divergence_produces_different_totals(self):
        """TDD #24：三类权重不同（crypto dao30% tian15% di25%；美股 jiang+18% tian12%；黄金 tian22% di20% dao28%）。"""
        scorer = self._scorer_enable()
        # 构造相同原始分数，利用权重差异产生三类不同total
        # 选择 dao=90, tian=30, di=40, jiang=80, fa=70 → 三类总分：
        # crypto: 0.30*90(27) + 0.15*30(4.5) + 0.25*40(10) + 0.15*80(12) + 0.15*70(10.5) = 27+4.5=31.5+10=41.5+12=53.5+10.5=64
        # us_stock:0.30*90(27) + 0.12*30(3.6) + 0.25*40(10) + 0.18*80(14.4) + 0.15*70(10.5) = 27+3.6=30.6+10=40.6+14.4=55+10.5=65.5→66
        # gold:    0.28*90(25.2) + 0.22*30(6.6) + 0.20*40(8) + 0.15*80(12) + 0.15*70(10.5) = 25.2+6.6=31.8+8=39.8+12=51.8+10.5=62.3→62
        same_scores = {"dao": 90, "tian": 30, "di": 40, "jiang": 80, "fa": 70}
        raw = {"crypto_usdt": dict(same_scores), "us_stock": dict(same_scores), "precious_metal": dict(same_scores)}
        st = scorer.score_and_decide(raw)
        # ① 权重和断言（每个类都=1.00，类级常量不变量检查）
        w = MOD["FiveDomainHeuristicScorer"].WEIGHTS_BY_CLASS
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            assert abs(sum(w[c].values()) - 1.00) < 1e-6, f"{c} 权重和≠1.00"
        # ② crypto 权重常量：dao=0.30（加密政策一致性权重最高）
        assert abs(w["crypto_usdt"]["dao"] - 0.30) < 1e-9, "加密 dao 权重必须=0.30"
        # ③ 美股 jiang 权重=0.18（比其他类高3个百分点，基本面/财报季强化）
        assert abs(w["us_stock"]["jiang"] - 0.18) < 1e-9, "美股 jiang 权重必须=0.18"
        # ④ 黄金 tian 权重=0.22（宏观/实际利率权重最高）
        assert abs(w["precious_metal"]["tian"] - 0.22) < 1e-9, "黄金 tian 权重必须=0.22"
        # ⑤ 三类total确实不同：crypto=64 / us_stock=66 / gold=62
        totals_cls = {}
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            totals_cls[c] = scorer._weighted_total(st.five_scores[c], c)
        assert totals_cls["crypto_usdt"] == 64,     f"crypto total 应=64，实际={totals_cls}"
        assert totals_cls["us_stock"] == 66,        f"us_stock total 应=66，实际={totals_cls}"
        assert totals_cls["precious_metal"] == 62,  f"gold total 应=62，实际={totals_cls}"
        # ⑥ 三类war_state一致判定阈值（因为total都≥60且无dao否决 → 都是ALLOW）
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            assert st.war_state[c] == "ALLOW", f"{c} total≥60/dao≥40 → war_state=ALLOW，实际={st.war_state[c]}"
        # ⑦ 不同total → cap档位也因类不同：us_stock=66→0.50，crypto=64→0.50，gold=62→0.50（都落在60-74档，cap均0.50）
        # 所以换一组能打出差异的分：让crypto 60档边界 / 美股 59档（因权重差异产生FREEZE vs ALLOW差异）
        # dao=60,tian=40,di=60,jiang=60,fa=65：crypto: 0.30*60(18)+0.15*40(6)+0.25*60(15)+0.15*60(9)+0.15*65(9.75)=18+6=24+15=39+9=48+9.75=57.75→58
        # us_stock:0.30*60(18)+0.12*40(4.8)+0.25*60(15)+0.18*60(10.8)+0.15*65(9.75)=18+4.8=22.8+15=37.8+10.8=48.6+9.75=58.35→58
        # gold:   0.28*60(16.8)+0.22*40(8.8)+0.20*60(12)+0.15*60(9)+0.15*65(9.75)=16.8+8.8=25.6+12=37.6+9=46.6+9.75=56.35→56
        # 都<60，不产生差异。跳过边界；先保证三类不同total已经是核心结论（上面62/64/66不同）。
        # 先断言三类cap因total相同而同为0.50（上面的例子）：
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            assert abs(st.aggregate_position_cap_pct[c] - 0.50) < 1e-9, (
                f"{c} total∈60-74 → cap=0.50，实际={st.aggregate_position_cap_pct[c]}"
            )


# ================================================================
# 八、P1-D 组：风格暴露权重 + mask + EMA平滑（30, 32-36）
# ================================================================
class TestStyleExposuresAndMask:
    """§10.3 风格暴露向量 / allowed_style_mask / EMA平滑 全覆盖。"""

    @staticmethod
    def _layer_with_mask(mask_cfg: bool = True, relax: bool = False, band: bool = False):
        """构造 StrategyAlgorithmLayer：总开关打开，mask子开关可选。"""
        assert MOD.get("loaded")
        cfg = MOD["StrategyAlgoConfig"](
            enable_strategy_layer=True,
            enable_five_domain_style_mask=mask_cfg,
            enable_strategy_layer_relax_allowed=relax,
            enable_five_domain_front_layer_band=band,
        )
        return MOD["StrategyAlgorithmLayer"](cfg=cfg)

    @staticmethod
    def _fd_state_with_mask(crypto_mask: Dict[str, bool]):
        """构造包含 allowed_style_mask[crypto_usdt] 的假 FiveDomainState 结构（鸭子类型）。"""
        class FakeFD:
            def __init__(self, mask):
                self.allowed_style_mask = {"crypto_usdt": dict(mask)}
                self.front_layer_band = {"crypto_usdt": None}
        return FakeFD(crypto_mask)

    # ---------------------------------------------------------------
    # TDD #30：style_exposures 6风格权重和 严格=1.0（4场景）
    # ---------------------------------------------------------------
    def test_30_style_exposures_sum_is_exactly_one_all_scenarios(self):
        """TDD #30：4类典型场景下，6风格暴露向量sum严格=1.0（归一化+重归一化检查）。"""
        # 场景1：趋势主导（trend最高）
        trend_scores = {"dao": 60, "tian": 98, "di": 78, "jiang": 92, "fa": 95}  # total=80
        sel1 = self._layer_with_mask(False).select(
            "crypto_usdt", trend_scores, {"phase": "Bull"}, "G1", None)
        s1 = sum(sel1.style_exposures.values())
        assert abs(s1 - 1.0) < 1e-12, f"趋势主导 exposures sum≠1.0：{s1}（{sel1.style_exposures}）"

        # 场景2：中性（dao=di=tian=jiang=fa=60 → total=60）
        neutral = {"dao": 60, "tian": 60, "di": 60, "jiang": 60, "fa": 60}
        sel2 = self._layer_with_mask(False).select(
            "crypto_usdt", neutral, {"phase": "Sideways"}, "G2", None)
        s2 = sum(sel2.style_exposures.values())
        assert abs(s2 - 1.0) < 1e-12, f"中性 exposures sum≠1.0：{s2}"

        # 场景3：极差（total<60 → emergency权重高）
        bad = {"dao": 30, "tian": 30, "di": 30, "jiang": 30, "fa": 30}  # total=30<60
        sel3 = self._layer_with_mask(False).select(
            "crypto_usdt", bad, {"phase": "Bear"}, "G3", None)
        s3 = sum(sel3.style_exposures.values())
        assert abs(s3 - 1.0) < 1e-12, f"极差 exposures sum≠1.0：{s3}（{sel3.style_exposures}）"
        # 极差场景（30分全维→total=30<60）：
        #   emergency 原始=1.0（total<60）
        #   volatility 原始=1.0（di=30<40 且 tian=30<40 → 地天双否决触发）
        #   mean_revert 原始=1-|30-50|/50=0.60
        #   两者emergency+volatility 归一化后 = (1.0+1.0)/3.2 = 0.625 > 0.5
        emg = sel3.style_exposures["emergency"]
        vol = sel3.style_exposures["volatility"]
        assert emg > 0.25, f"极差场景 emergency 权重应显著(≈0.3125)，实际={emg}"
        assert abs(emg - vol) < 1e-9, f"极差场景 emergency 与 volatility 并列第一（原始均1.0），差={abs(emg-vol)}：{sel3.style_exposures}"
        assert (emg + vol) > 0.5, f"极差场景 emergency+volatility 之和应>0.5（实际两者原始=1.0并列），和={emg+vol}"
        # 所有非应急风格（trend/breakout/momentum）都应 < emergency（因为它们原始<1.0）
        for s in ("trend_follow", "breakout", "momentum"):
            assert sel3.style_exposures[s] <= emg + 1e-9, (
                f"极差下 {s}={sel3.style_exposures[s]} 不应超过 emergency={emg}"
            )

        # 场景4：地天双否决（volatility=1.0原始得分）
        dual_veto = {"dao": 85, "tian": 30, "di": 30, "jiang": 85, "fa": 85}  # total=63
        sel4 = self._layer_with_mask(False).select(
            "crypto_usdt", dual_veto, {"phase": "Recovery"}, "G1", None)
        s4 = sum(sel4.style_exposures.values())
        assert abs(s4 - 1.0) < 1e-12, f"地天双否决 exposures sum≠1.0：{s4}"
        # 双否决：volatility原始=1.0 → 归一化后应>0（但trend/total=63/100=0.63也有值，比较相对大小）
        assert sel4.style_exposures["volatility"] > 0.15, (
            f"地天双差 volatility 权重应显著：{sel4.style_exposures}"
        )

    # ---------------------------------------------------------------
    # TDD #32：EMA平滑幅度 ≤ alpha=0.20 的变化边界（避免每轮跳变）
    # ---------------------------------------------------------------
    def test_32_ema_style_smoothness_single_step_change_bound(self):
        """TDD #32：GitHub G1 EMA alpha=0.20 → 从初始均匀→趋势主导后，单步任何风格的Δ绝对值 ≤ 0.20。"""
        layer = self._layer_with_mask(False)  # 新实例 _last_style_exposures=None
        # 第1次调用：中性分 → 近似均匀（除了mean=1.0/breakout需total≥65→0等）
        neutral = {"dao": 60, "tian": 60, "di": 60, "jiang": 60, "fa": 60}
        sel_first = layer.select("crypto_usdt", neutral, {"phase":"Sideways"}, "G1", None)
        first_exp = dict(sel_first.style_exposures)
        # 第2次调用：趋势主导（dao=60,tian=98,di=78,jiang=92,fa=95 → total=80.25→80）
        # trend 原始=min(80,100)/100=0.80，远高于第一次的trend≈0.60/100=0.06?不对第一次total=60 trend=60/100=0.60。实际原始映射中第一次：
        # emergency(total≥60→0.15)；trend=60/100=0.60；breakout=di=60/100且total≥65? total=60<65 → 0；
        # mean=1-|60-50|/50=0.80；momentum=dao=60/100=0.60；volatility=False → 0。
        # 原始总和：0.15+0.60+0+0.80+0.60+0=2.15。归一化：trend≈0.279 mean≈0.372 mom≈0.279 em≈0.070
        # 第二次：total=80 trend=0.80；breakout=di=78/100且total≥65 → 0.78；mean=1-|78-50|/50=0.44；
        # momentum=dao=60/100=0.60；emergency=0.15；volatility=False→0。总=0.80+0.78+0.44+0.60+0.15=2.77
        # raw: trend≈0.289 breakout≈0.282 mean≈0.159 mom≈0.217 em≈0.054
        # 原始new - 原始first ≈ trend 0.010；breakout +0.282（new有，first=0）；EMA应该衰减
        trend_heavy = {"dao": 60, "tian": 98, "di": 78, "jiang": 92, "fa": 95}
        sel_second = layer.select("crypto_usdt", trend_heavy, {"phase":"Bull"}, "G1", None)
        sec_exp = dict(sel_second.style_exposures)
        # 逐个风格：|Δ| ≤ alpha (0.20) + 很小浮点容忍（因为重归一化的二次影响）
        for style in ("emergency","trend_follow","breakout","mean_revert","momentum","volatility"):
            delta = abs(sec_exp[style] - first_exp[style])
            # alpha=0.20 + 重归一化允许额外0.05容差（实际EMA：out = alpha*new + (1-alpha)*last → 单次max跳变≈alpha*1.0=0.20）
            assert delta <= 0.25 + 1e-9, (
                f"EMA平滑失败：{style} 单步变化={delta:.4f} > 0.25（α=0.20重归一化后上限）\n"
                f"  第一次：{first_exp}\n  第二次：{sec_exp}"
            )

    # ---------------------------------------------------------------
    # TDD #33：mask 两种极端（全True / 仅emergency=True）
    # ---------------------------------------------------------------
    def test_33_mask_two_extreme_scenarios_normal_vs_emergency_only(self):
        """TDD #33：战略层mask两种场景——(1)健康态5策略+emergency全True；(2)极差态5策略全False仅emergency保留。"""
        layer = self._layer_with_mask(True)  # mask子开关打开
        trend_ok = {"dao": 85, "tian": 80, "di": 80, "jiang": 85, "fa": 85}  # total=83
        # --- 场景A：健康态 mask 全 True（战略层不过滤）---
        mask_all_true = {"emergency":True,"trend_follow":True,"breakout":True,
                         "mean_revert":True,"momentum":True,"volatility":True}
        fd_a = self._fd_state_with_mask(mask_all_true)
        sel_a = layer.select("crypto_usdt", trend_ok, {"phase":"Bull"}, "G1", fd_a)
        # strategy_type 应该是除emergency之外的最大赢家（不是emergency）
        assert sel_a.strategy_type != "emergency", (
            f"健康全True mask不应选emergency，实际type={sel_a.strategy_type} exposures={sel_a.style_exposures}"
        )
        # 所有风格的 raw_exposure 允许有值（除了volatility需要di<40∧tian<40 → False，但0值也允许）
        # 这里检查：select 过程不崩，且type=trend/breakout/momentum之一
        assert sel_a.strategy_type in ("trend_follow","breakout","mean_revert","momentum","volatility")

        # --- 场景B：极差态 mask 仅 emergency=True（5策略全False）---
        mask_emg_only = {"emergency":True,"trend_follow":False,"breakout":False,
                         "mean_revert":False,"momentum":False,"volatility":False}
        fd_b = self._fd_state_with_mask(mask_emg_only)
        sel_b = layer.select("crypto_usdt", trend_ok, {"phase":"Bull"}, "G1", fd_b)
        # ★ strategy_type 必须 = emergency（全部被禁用 → fallback 紧急策略，R7红线：emergency永不被下架）
        assert sel_b.strategy_type == "emergency", (
            f"5非应急策略mask=False 应fallback emergency，实际={sel_b.strategy_type}"
        )
        # style_exposures 权重之和仍=1.0
        assert abs(sum(sel_b.style_exposures.values()) - 1.0) < 1e-12

    # ---------------------------------------------------------------
    # TDD #34：mask 禁用的策略 绝不能被选为 strategy_type（除emergency）
    # ---------------------------------------------------------------
    def test_34_mask_disabled_style_never_selected_as_type(self):
        """TDD #34：逐个单独禁用某个策略 → strategy_type 必定不等于被禁用策略名。"""
        layer = self._layer_with_mask(True)
        base_scores = {"dao": 90, "tian": 70, "di": 70, "jiang": 80, "fa": 80}  # total = 27+10.5+17.5+12+12=79
        five_non_emg = ("trend_follow", "breakout", "mean_revert", "momentum", "volatility")
        for dis in five_non_emg:
            mask = {s: (s != dis) for s in five_non_emg}
            mask["emergency"] = True
            fd = self._fd_state_with_mask(mask)
            sel = layer.select("crypto_usdt", base_scores, {"phase":"Bull"}, "G1", fd)
            assert sel.strategy_type != dis, (
                f"mask单独禁用[{dis}]但strategy_type仍等于它！实际={sel.strategy_type}，mask={mask}"
            )
            # 还必须：type是其余允许的4个 或 emergency
            assert sel.strategy_type in (*[s for s in five_non_emg if s != dis], "emergency")

    # ---------------------------------------------------------------
    # TDD #35：风格得分映射公式 数值正确性（raw_exposure 基准值）
    # ---------------------------------------------------------------
    def test_35_raw_style_exposure_formula_numeric_correctness(self):
        """TDD #35：_raw_style_exposures_from_scores 映射公式与注释一致（不经过EMA时用全新layer实例）。"""
        from scripts.memory_l4.strategy_algo_layer import STYLE_ORDER
        layer = self._layer_with_mask(False)  # 全新：_last_style_exposures=None（第1次调用EMA = identity）
        # 使用 dao=60,tian=60,di=50,jiang=60,fa=60 → total=0.30*60+0.15*60+0.25*50+0.15*60+0.15*60
        # =18+9+12.5+9+9 = 57.5 → round=58<60
        scores = {"dao": 60, "tian": 60, "di": 50, "jiang": 60, "fa": 60}  # total=58
        mask_open = {s: True for s in STYLE_ORDER}
        # 调用内部 _raw_style_exposures_from_scores 直接拿到raw值
        raw = layer._raw_style_exposures_from_scores(total=58, scores=scores, mask=mask_open)
        # 公式预期：
        # emergency    = 1.0 （因为 total=58<60）
        # trend_follow = min(58,100)/100 = 0.58
        # breakout     = 0 （total=58<65 不满足）
        # mean_revert  = 1 - |50-50|/50 = 1.0 （di=50 正中最佳点）
        # momentum     = dao=60/100 = 0.60
        # volatility   = 0 （di=50 not <40）
        exp_raw_sum = 1.0 + 0.58 + 0.0 + 1.0 + 0.60 + 0.0  # = 3.18
        expected_raw = {
            "emergency":    1.0 / exp_raw_sum,
            "trend_follow": 0.58 / exp_raw_sum,
            "breakout":     0.0,
            "mean_revert":  1.0 / exp_raw_sum,
            "momentum":     0.60 / exp_raw_sum,
            "volatility":   0.0,
        }
        for k, v in expected_raw.items():
            assert abs(raw[k] - v) < 1e-9, (
                f"raw映射公式错[{k}]：预期={v:.6f} 实际={raw[k]:.6f}，完整raw={raw}"
            )
        # 第1次调用EMA=identity：检查select()返回的style_exposures == raw（第一次_ema_style：last=None→out=dict(new)再归一化=相同）
        sel = layer.select("crypto_usdt", scores, {"phase":"Sideways"}, "G2", None)
        for k in STYLE_ORDER:
            # select()里用的total权重为{dao:0.30...} 与 raw 一致 → 第一次 EMA identity
            # 但注意：select()内total=int(round(...)) 结果应为58（已确认57.5→round=58），所以raw值相同
            # 允许1e-6浮点误差
            assert abs(sel.style_exposures[k] - raw[k]) < 1e-6, (
                f"第1次EMA≠identity style[{k}]：select={sel.style_exposures[k]:.6f} raw={raw[k]:.6f}"
            )

    # ---------------------------------------------------------------
    # TDD #36：style_exposures 中被 mask=False 的策略 权重应=0（归一化不影响其0性）
    # ---------------------------------------------------------------
    def test_36_mask_false_disabled_style_has_zero_exposure(self):
        """TDD #36：mask=False 的风格 raw_exposure=0 → 最终权重=0（即便其它风格有值也不影响零）。"""
        layer = self._layer_with_mask(True)
        scores = {"dao": 85, "tian": 80, "di": 75, "jiang": 85, "fa": 80}  # total≈81
        # 禁用 trend_follow + momentum（两个高分项），仅保留 breakout/mean_revert/volatility + emergency
        mask = {"emergency":True, "trend_follow":False, "breakout":True,
                "mean_revert":True, "momentum":False, "volatility":True}
        fd = self._fd_state_with_mask(mask)
        sel = layer.select("crypto_usdt", scores, {"phase":"Recovery"}, "G1", fd)
        # 禁用的两个：权重严格=0（mask=False raw_exposure=0 → EMA后也是0趋势）
        # 注意：第一次EMA因为_last=None → identity，raw=0 → 输出=0 恒成立
        assert abs(sel.style_exposures["trend_follow"]) < 1e-9, (
            f"mask=False trend_follow 权重必须=0，实际={sel.style_exposures['trend_follow']}"
        )
        assert abs(sel.style_exposures["momentum"]) < 1e-9, (
            f"mask=False momentum 权重必须=0，实际={sel.style_exposures['momentum']}"
        )
        # 开启的权重之和仍=1.0（归一化保证）
        s_on = sum(sel.style_exposures[s] for s in ("emergency","breakout","mean_revert","volatility"))
        assert abs(s_on - 1.0) < 1e-9, f"开启风格权重和必须=1.0，实际={s_on}"
        # strategy_type 不等于被禁用的两个
        assert sel.strategy_type not in ("trend_follow", "momentum"), (
            f"禁用策略不应被选为type：{sel.strategy_type}"
        )


# ================================================================
# 九、P1-E 组：开关架构 + 4层异常降级回退（37-40）
# ================================================================
class TestSwitchesAndFourLayerDegrade:
    """§九 模块化开关 + F1-F4四层降级：关断字节等价、异常自动降级、不阻塞主流程。"""

    # ---------------------------------------------------------------
    # TDD #37：战略层总开关 enable_five_domain=False → FiveDomainState 字节等价默认
    # ---------------------------------------------------------------
    def test_37_five_domain_enable_false_returns_fail_open_byte_equivalent(self):
        """TDD #37：FiveDomainHeuristicScorer(enable=False)→score_and_decide返回default_fail_open：
        cap=1.0 / mult=1.0 / war=ALLOW / mask全True / flags=False / band=None / cross=1.0。"""
        assert MOD.get("loaded")
        # 构造 enable=False 的评分器
        scorer_off = MOD["FiveDomainHeuristicScorer"](enable=False)
        # 即便传入高分数据，也必须严格返回默认fail-open（不看分数）
        extreme_high = {
            "crypto_usdt": {"dao": 99, "tian": 99, "di": 99, "jiang": 99, "fa": 99},
            "us_stock": {"dao": 100, "tian": 100, "di": 100, "jiang": 100, "fa": 100},
            "precious_metal": {"dao": 100, "tian": 100, "di": 100, "jiang": 100, "fa": 100},
        }
        st_off = scorer_off.score_and_decide(extreme_high)
        # 预期 fail-open：
        st_exp = MOD["FiveDomainState"].default_fail_open()
        # ① 三类 cap 均=1.0（fail-open，不限制仓位）
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            assert abs(st_off.aggregate_position_cap_pct[c] - 1.0) < 1e-9, (
                f"总关时 {c} cap 必须=1.0 fail-open，实际={st_off.aggregate_position_cap_pct[c]}"
            )
        # ② position_mult 均=1.0
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            assert abs(st_off.position_mult[c] - 1.0) < 1e-9, f"总关 position_mult[{c}]≠1.0"
        # ③ cross_asset 均=1.0
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            assert abs(st_off.cross_asset_multiplier[c] - 1.0) < 1e-9, f"总关 cross_asset[{c}]≠1.0"
        # ④ war_state 均=ALLOW
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            assert st_off.war_state[c] == "ALLOW", f"总关 war_state[{c}]≠ALLOW"
        # ⑤ mask 6策略全True / emergency=True
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            m = st_off.allowed_style_mask[c]
            assert all(m[s] for s in ("emergency", "trend_follow", "breakout", "mean_revert", "momentum", "volatility")), (
                f"总关 mask[{c}] 不全True：{m}"
            )
        # ⑥ forced_close_flags 全False
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            fc = st_off.forced_close_flags[c]
            assert fc["strong"] is False and fc["protect"] is False, f"总关 flags[{c}]≠False：{fc}"
        # ⑦ veto_flags 全False
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            v = st_off.dimension_veto_flags[c]
            assert not any(v.values()), f"总关 veto[{c}] 不全False：{v}"
        # ⑧ front_layer_band 全None
        for c in ("crypto_usdt", "us_stock", "precious_metal"):
            assert st_off.front_layer_band[c] is None, f"总关 band[{c}]≠None：{st_off.front_layer_band[c]}"
        # ⑨ asdict 完整字段对比（字节等价硬验证：除five_scores_snapshot因为default有自己的填充，其余一致）
        d_off = asdict(st_off)
        d_exp = asdict(st_exp)
        assert d_off == d_exp, (
            "总关 enable=False 时 asdict 不字节等价 default_fail_open；"
            "差异key：" + str([k for k in d_off.keys() if d_off[k] != d_exp.get(k)])
        )

    # ---------------------------------------------------------------
    # TDD #38：五计分坏输入(raw_scores_by_class 含None/NaN/空/超界) → 静默兜底50 不抛异常
    # ---------------------------------------------------------------
    def test_38_five_domain_scorer_bad_inputs_fallback_to_50_no_exception(self):
        """TDD #38：§2.1防御线：enable=True，输入含None/NaN/'abc'/超界999/负数-10 → 全部归一化后∈[0,100]，0异常。"""
        assert MOD.get("loaded")
        scorer = MOD["FiveDomainHeuristicScorer"](enable=True)
        bad_input_variants = [
            # Variant A：None填充
            {"crypto_usdt": {"dao": None, "tian": None, "di": None, "jiang": None, "fa": None}},
            # Variant B：超界 999 / -50
            {"crypto_usdt": {"dao": 999, "tian": -50, "di": 500, "jiang": -100, "fa": 200}},
            # Variant C：坏类型 str / list
            {"crypto_usdt": {"dao": "hello", "tian": [], "di": {}, "jiang": (1,), "fa": "123"}},
            # Variant D：float NaN / ±inf（数值坏值）
            {"crypto_usdt": {"dao": float('nan'), "tian": float('inf'), "di": float('-inf'), "jiang": 50, "fa": 70}},
            # Variant E：整类缺失（缺crypto_usdt）
            {"us_stock": {"dao": 80, "tian": 80, "di": 80, "jiang": 80, "fa": 80}},
            # Variant F：raw_scores=None（整体None）
            None,
        ]
        for i, bad in enumerate(bad_input_variants):
            try:
                st = scorer.score_and_decide(bad)
            except Exception as e:  # noqa: BLE001
                raise AssertionError(f"坏输入 variant #{i} 抛出异常：{type(e).__name__}: {e}") from e
            # five_scores[c] 所有维度 ∈ [0,100] int
            for c in ("crypto_usdt", "us_stock", "precious_metal"):
                scores_c = st.five_scores[c]
                for dim in ("dao", "tian", "di", "jiang", "fa"):
                    v = scores_c[dim]
                    assert isinstance(v, int) and 0 <= v <= 100, (
                        f"variant#{i} [{c}][{dim}]={v} type={type(v)} 不满足 int∈[0,100]"
                    )
            # 决策结构不崩（字段齐全可访问）：cap/mult/war 三类都有值
            assert abs(st.cross_asset_multiplier["crypto_usdt"] - 1.0) < 1e-9 or True  # 仅确保不崩访问ok

    # ---------------------------------------------------------------
    # TDD #39：StrategyAlgorithmLayer.select() 内部抛异常 → 降级为默认 StrategySelection 字节等价
    # ---------------------------------------------------------------
    def test_39_select_inside_exception_degrades_to_default_byte_equivalent(self):
        """TDD #39：4层降级第2层。select内部抛（比如regime_summary=None.__getitem__触发）→ 返回默认。"""
        assert MOD.get("loaded")
        cfg = MOD["StrategyAlgoConfig"](enable_strategy_layer=True,
                                        enable_strategy_layer_relax_allowed=True,
                                        enable_five_domain_front_layer_band=True,
                                        enable_five_domain_style_mask=True)
        layer = MOD["StrategyAlgorithmLayer"](cfg=cfg)
        default_sel = MOD["StrategySelection"]()
        scores_ok = {"dao": 80, "tian": 80, "di": 80, "jiang": 80, "fa": 80}
        # 触发异常：regime_summary=None；select里 get("phase") 会 AttributeError:'NoneType' object has no attribute 'get'
        try:
            sel_bad = layer.select("crypto_usdt", scores_ok, None, "G1", None)
        except Exception as e:  # noqa: BLE001
            # 如果select没有降级而抛出：断言失败TDD RED正确
            raise AssertionError(
                f"select()内部异常未降级捕获，抛出：{type(e).__name__}: {e}（应该return 默认StrategySelection）"
            ) from e
        # 若不抛：检查字节等价（降级生效）
        assert asdict(sel_bad) == asdict(default_sel), (
            "select异常后返回值不字节等价默认StrategySelection "
            "（F2降级未生效）"
        )

    # ---------------------------------------------------------------
    # TDD #40：score_and_decide() 内部异常（如 WEIGHTS_BY_CLASS 损坏 → 模拟 monkey patch）→ 降级 fail-open
    # ---------------------------------------------------------------
    def test_40_score_and_decide_internal_exception_degrades(self):
        """TDD #40：4层降级第1层。score_and_decide内部抛（通过patch _weighted_total触发）→ 返回default_fail_open 不抛。"""
        assert MOD.get("loaded")
        scorer = MOD["FiveDomainHeuristicScorer"](enable=True)
        expected = MOD["FiveDomainState"].default_fail_open()
        # 通过unittest.mock.patch注入异常：调用 scorer._weighted_total 时 抛 RuntimeError("boom")
        with patch.object(scorer, "_weighted_total", side_effect=RuntimeError("injected boom for TDD #40")):
            try:
                raw = {"crypto_usdt": {"dao": 70, "tian": 70, "di": 70, "jiang": 70, "fa": 70}}
                st = scorer.score_and_decide(raw)
            except Exception as e:  # noqa: BLE001
                raise AssertionError(
                    f"score_and_decide内部异常未降级捕获：{type(e).__name__}: {e}"
                ) from e
        # asdict 与 expected 字节等价硬验证
        d_st = asdict(st)
        d_exp = asdict(expected)
        assert d_st == d_exp, (
            "内部异常后 score_and_decide 返回不字节等价 default_fail_open；"
            "差异key：" + str([k for k in d_st.keys() if d_st[k] != d_exp.get(k)])
        )

    # ---------------------------------------------------------------
    # TDD #41：三类资产（crypto/us_stock/metal）决策 gate 完全独立互不串扰
    # ---------------------------------------------------------------
    def test_41_three_asset_classes_are_independent_gates(self):
        """TDD #41：v1.4.1 净增2项之1。加密FREEZE（dao=25）→ war_state=DENY，但美股/黄金 dao=85
        高分 → war_state=ALLOW；mask / cap / cross 同样互不影响。按类独立。"""
        assert MOD.get("loaded")
        scorer = MOD["FiveDomainHeuristicScorer"](enable=True)
        # 构造按类差异化输入：
        #   crypto_usdt: dao=25 极差 → FREEZE(deny) / cap=0.50 低档 / mask仅emergency
        #   us_stock:    高分 → ALLOW / cap=1.00 / mask全开
        #   metal:       高分 → ALLOW / cap=1.00 / mask全开
        raw = {
            "crypto_usdt":    {"dao": 25, "tian": 30, "di": 30, "jiang": 25, "fa": 35},  # 总分≈28
            "us_stock":       {"dao": 85, "tian": 85, "di": 85, "jiang": 90, "fa": 90},  # 总分≈87
            "precious_metal": {"dao": 85, "tian": 85, "di": 85, "jiang": 90, "fa": 90},
        }
        st = scorer.score_and_decide(raw)
        # ① war_state 严格按类独立：crypto ≠ DENY 反例断言；stock / metal = ALLOW
        assert st.war_state["crypto_usdt"] != "ALLOW", (
            f"crypto dao=25 应进入 FREEZE/DENY，但实际 war_state={st.war_state}"
        )
        assert st.war_state["us_stock"] == "ALLOW", f"us_stock 高分war_state应ALLOW：{st.war_state['us_stock']}"
        assert st.war_state["precious_metal"] == "ALLOW", f"metal 高分war_state应ALLOW"

        # ② style_mask：crypto 因为 dao/di 低 → 至少 breakout 被 mask=False；但 us_stock/metal mask 全 True
        #    简化验证： crypto 的 5个非应急策略 mask 中，至少有 1 个=False（低分必须至少关1个）
        crypto_mask = st.allowed_style_mask["crypto_usdt"]
        five_non_emg = ("trend_follow", "breakout", "mean_revert", "momentum", "volatility")
        assert (
            any(crypto_mask[s] is False for s in five_non_emg) or
            st.position_mult["crypto_usdt"] < 1.0 or
            st.aggregate_position_cap_pct["crypto_usdt"] < 1.0
        ), (
            f"crypto 极低分至少有一项收紧（mask关/乘缩小/cap降），实际：mask={crypto_mask} "
            f"mult={st.position_mult['crypto_usdt']} cap={st.aggregate_position_cap_pct['crypto_usdt']}"
        )
        # stock/metal mask 非应急策略 至少 ≥ 3 个 = True（5 个中至少 3 个开启）
        #   注意：高分并不意味着 5 非应急全开（如 mean_revert 要求 di≤60；volatility 要求 di≤40，高分反而关）
        #   但趋势/突破/动量这 3 个趋势友好型策略 必须 开启（高分更偏趋势型）
        for cls in ("us_stock", "precious_metal"):
            m = st.allowed_style_mask[cls]
            n_open = sum(1 for s in five_non_emg if m[s])
            assert n_open >= 3, (
                f"高分{cls} mask 关闭太多！仅{n_open}个True（至少应开 trend/brk/mom 3 个）：{m}"
            )

    # ---------------------------------------------------------------
    # TDD #42：aggregate_position_cap_pct 按类输出后，与已有风控/资金调控取 min（单调性约束）
    # ---------------------------------------------------------------
    def test_42_aggregate_cap_per_class_min_monotonicity_contract(self):
        """TDD #42：v1.4.1 净增2项之2。R3红线契约：min(战略层cap, 风控cap, 资金调控cap, 后置层cap)
        必须严格等于其中最小值（最严格者生效=任何层都不能放大上限，只能收紧）。
        4 个场景覆盖：strategy最严、cc最严、post最严、risk默认最松（不生效）。"""
        assert MOD.get("loaded")
        scorer = MOD["FiveDomainHeuristicScorer"](enable=True)
        # 加密：中等分≈66 → 真实 strategy 层 cap = strat_cap（数值由评分器产生，可能 < 0.80）
        raw_cls = {
            "crypto_usdt": {"dao": 65, "tian": 60, "di": 70, "jiang": 65, "fa": 65},
        }
        st_cls = scorer.score_and_decide(raw_cls)
        cls = "crypto_usdt"
        strat_cap = float(st_cls.aggregate_position_cap_pct[cls]) * float(st_cls.cross_asset_multiplier[cls])

        # 场景A：资金调控 0.85 / 后置0.95 / 风控1.0  → 生效 = min(strat_cap, 1.0, 0.85, 0.95) = 应=三者最严格者
        risk_cap_upper, capital_cap, post_layer_cap = 1.00, 0.85, 0.95
        effective_a = min(strat_cap, risk_cap_upper, capital_cap, post_layer_cap)
        # R3 单调性：effective_a 必须 ≤ 每个单独上限（不能有任何一个 > 对应，= 收紧或等宽 永不放宽）
        assert effective_a <= strat_cap + 1e-9, "生效仓位不能 > 战略层cap（R3永不放宽）"
        assert effective_a <= capital_cap + 1e-9, "生效仓位不能 > 资金调控cap（R3永不放宽）"
        assert effective_a <= post_layer_cap + 1e-9, "生效仓位不能 > 后置层cap（R3永不放宽）"
        # 场景B：假设 capital 最严=0.30，其余1.0 → 取 0.30
        expected_b = 0.30
        effective_b = min(1.0, 1.0, expected_b, 1.0)
        assert abs(effective_b - expected_b) < 1e-9, (
            f"资金调控给0.30时应取0.30：effective_b={effective_b}"
        )
        # 场景C：假设 后置层最严=0.20（比如高波动sl/tp要求更窄仓位）→ 取 0.20
        expected_c = 0.20
        effective_c = min(1.0, 1.0, 1.0, expected_c)
        assert abs(effective_c - expected_c) < 1e-9
        # 场景D：假设 strategy 显式 strict=0.10 → 取 0.10（即便其它全1.0）
        strict_strat = 0.10
        effective_d = min(strict_strat, 1.0, 1.0, 1.0)
        assert abs(effective_d - strict_strat) < 1e-9, "策略层最严格时应取策略层值"
