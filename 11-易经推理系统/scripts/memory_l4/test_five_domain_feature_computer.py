#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FiveDomainFeatureComputer 测试套件 — TDD 驱动。

按 §七 落地优先级排序：P1天 → P2地 → P3将 → P4道 → P5法 → P0全局。
严格对齐 spec：2026-08-21-sunzi-five-domains-evaluation.md §三逐维打分详解。
"""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

# 确保能 import 同级模块
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from strategy_algo_layer import ASSET_CLASSES, DEFAULT_NEUTRAL_SCORES, _normalize_0_100
from five_domain_feature_computer import FiveDomainFeatureComputer


# =====================================================================
# P0 全局：compute() 返回结构 + fail-open + 开关
# =====================================================================

class TestComputeStructure:
    """P0-1: compute() 返回所有资产类的五维评分。"""

    def test_compute_returns_all_asset_classes(self):
        """compute() 必须返回 ASSET_CLASSES 中所有类的评分。"""
        computer = FiveDomainFeatureComputer(enable=True)
        result = computer.compute()
        for cls in ASSET_CLASSES:
            assert cls in result, f"缺少资产类 {cls}"

    def test_compute_returns_all_five_domains(self):
        """每个类必须包含 dao/tian/di/jiang/fa 五维评分。"""
        computer = FiveDomainFeatureComputer(enable=True)
        result = computer.compute()
        for cls in ASSET_CLASSES:
            for domain in ("dao", "tian", "di", "jiang", "fa"):
                assert domain in result[cls], f"{cls} 缺少维度 {domain}"

    def test_compute_scores_are_int_0_100(self):
        """所有评分必须是 0-100 的整数。"""
        computer = FiveDomainFeatureComputer(enable=True)
        result = computer.compute()
        for cls in ASSET_CLASSES:
            for domain, score in result[cls].items():
                assert isinstance(score, int), f"{cls}.{domain}={score} 不是int"
                assert 0 <= score <= 100, f"{cls}.{domain}={score} 越界"


class TestFailOpen:
    """P0-2: enable=False 时返回中性默认值。"""

    def test_disabled_returns_neutral_defaults(self):
        """enable=False 时返回 DEFAULT_NEUTRAL_SCORES。"""
        computer = FiveDomainFeatureComputer(enable=False)
        result = computer.compute()
        for cls in ASSET_CLASSES:
            for domain, expected in DEFAULT_NEUTRAL_SCORES.items():
                assert result[cls][domain] == expected, \
                    f"{cls}.{domain}={result[cls][domain]} != 中性默认 {expected}"

    def test_exception_returns_neutral_defaults(self):
        """compute() 内部异常时返回中性默认值（fail-open）。"""
        computer = FiveDomainFeatureComputer(enable=True)
        # 注入一个会抛异常的 mock
        computer._compute_tian = MagicMock(side_effect=RuntimeError("test"))
        result = computer.compute()
        # 天维度应 fail-open 到 50
        for cls in ASSET_CLASSES:
            assert result[cls]["tian"] == 50


# =====================================================================
# P1 天维度：日历季节性 / 美林时钟 / 波动率周期 / 流动性周期
# =====================================================================

class TestTianCalendar:
    """P1-1: 日历季节性 Q1/Q4 效应。"""

    def test_q1_seasonality_positive(self):
        """Q1（1-3月）历史均正收益 → 评分 > 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        # 模拟 3 月 15 日
        score = computer._compute_calendar_seasonality(month=3, day=15)
        assert score > 50, f"Q1效应应 > 50, got {score}"

    def test_q3_seasonality_lower(self):
        """Q3（7-9月）历史通常弱势 → 评分 < 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_calendar_seasonality(month=8, day=15)
        assert score < 50, f"Q3弱势应 < 50, got {score}"

    def test_weekend_effect(self):
        """周末效应（周六/日）波动率低 → 评分中性偏低。"""
        computer = FiveDomainFeatureComputer(enable=True)
        # 模拟周六
        score = computer._compute_calendar_seasonality(month=3, day=15, weekday=5)
        assert 40 <= score <= 60, f"周末效应应中性 40-60, got {score}"


class TestTianMerrillClock:
    """P1-2: 美林时钟四阶段映射。"""

    def test_recovery_phase_high_score(self):
        """复苏期对风险资产利好 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_merrill_clock_score(phase="RECOVERY")
        assert score > 60, f"复苏期应 > 60, got {score}"

    def test_reflation_phase_low_score(self):
        """衰退期资金流出加密 → 评分 < 40。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_merrill_clock_score(phase="REFLATION")
        assert score < 40, f"衰退期应 < 40, got {score}"

    def test_overheat_phase_moderate(self):
        """过热期altcoin疯狂但风险高 → 评分 50-70。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_merrill_clock_score(phase="OVERHEAT")
        assert 50 <= score <= 70, f"过热期应 50-70, got {score}"

    def test_stagflation_phase_low(self):
        """滞胀期资金回流BTC → 评分 30-50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_merrill_clock_score(phase="STAGFLATION")
        assert 30 <= score <= 50, f"滞胀期应 30-50, got {score}"


class TestTianVolatilityCycle:
    """P1-3: ATR 分位统计。"""

    def test_high_atr_percentile_favorable_for_trend(self):
        """ATR 高分位（>0.8）适合趋势策略 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_volatility_cycle_score(atr_percentile=0.85)
        assert score > 60, f"高分位ATR应 > 60, got {score}"

    def test_low_atr_percentile_for_mean_revert(self):
        """ATR 低分位（<0.2）适合均值回归 → 评分 40-55。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_volatility_cycle_score(atr_percentile=0.15)
        assert 40 <= score <= 55, f"低分位ATR应 40-55, got {score}"


class TestTianLiquidityCycle:
    """P1-4: 流动性周期（QE/QT 阶段）。"""

    def test_qe_phase_high_score(self):
        """QE（宽松）阶段 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_liquidity_cycle_score(liquidity_score=0.8)
        assert score > 60, f"QE阶段应 > 60, got {score}"

    def test_qt_phase_low_score(self):
        """QT（紧缩）阶段 → 评分 < 40。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_liquidity_cycle_score(liquidity_score=0.2)
        assert score < 40, f"QT阶段应 < 40, got {score}"


# =====================================================================
# P2 地维度：regime代理 / 弹簧力场MA / 六种地形 / 盘整 / FTD / MA200
# =====================================================================

class TestDiRegime:
    """P2-1: 后置层 regime→分数映射。"""

    def test_trend_up_high_score(self):
        """上升趋势 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_regime_score("trend_up")
        assert score > 60, f"上升趋势应 > 60, got {score}"

    def test_trend_down_low_score(self):
        """下降趋势 → 评分 < 40。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_regime_score("trend_down")
        assert score < 40, f"下降趋势应 < 40, got {score}"

    def test_ranging_neutral(self):
        """震荡 → 评分 45-55。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_regime_score("ranging")
        assert 45 <= score <= 55, f"震荡应 45-55, got {score}"


class TestDiSpringForce:
    """P2-2: 弹簧力场MA评分。"""

    def test_no_data_returns_neutral(self):
        """无数据 → 中性 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_spring_force_score(None)
        assert score == 50

    def test_valid_score_passed_through(self):
        """有效弹簧力场评分 → 直接传递。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_spring_force_score({"spring_force_score": 75})
        assert score == 75


class TestDiConsolidation:
    """P2-3: 盘整持续时间量化。"""

    def test_low_amplitude_consolidation(self):
        """低振幅/ATR → 盘整 → 评分 < 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_consolidation_duration(
            {"price_amplitude": 1.0, "atr": 1.0}
        )
        assert score < 50, f"盘整应 < 50, got {score}"

    def test_high_amplitude_trend(self):
        """高振幅/ATR → 趋势 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_consolidation_duration(
            {"price_amplitude": 5.0, "atr": 1.0}
        )
        assert score > 60, f"趋势应 > 60, got {score}"


class TestDiFTD:
    """P2-4: Follow-through Day 信号。"""

    def test_positive_ftd(self):
        """FTD正面信号 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_follow_through_day({"ftd_signal": 1})
        assert score > 60, f"正面FTD应 > 60, got {score}"

    def test_negative_ftd(self):
        """FTD负面信号 → 评分 < 40。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_follow_through_day({"ftd_signal": -1})
        assert score < 40, f"负面FTD应 < 40, got {score}"


class TestDiMA200Distance:
    """P2-5: 价格vs MA200距离分位。"""

    def test_above_ma200_high_score(self):
        """价格在MA200上方远 → 高分。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_ma200_distance(
            {"ma200_distance_percentile": 0.9}
        )
        assert score > 60, f"MA200上方远应 > 60, got {score}"

    def test_below_ma200_low_score(self):
        """价格在MA200下方远 → 低分。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_ma200_distance(
            {"ma200_distance_percentile": 0.1}
        )
        assert score < 40, f"MA200下方远应 < 40, got {score}"


class TestDiTerrainClassification:
    """P2-6: 六种地形分类（§三 L157-166）。"""

    def test_tong_terrain_trend_clear(self):
        """通形：趋势明确 → 趋势跟踪策略。"""
        computer = FiveDomainFeatureComputer(enable=True)
        terrain = computer._classify_terrain(
            {"regime": "trend_up", "atr_percentile": 0.7, "price_amplitude": 5.0, "atr": 1.0}
        )
        assert terrain == "tong", f"趋势明确应=通形, got {terrain}"

    def test_zhi_terrain_ranging(self):
        """支形：震荡盘整 → 均值回归策略。"""
        computer = FiveDomainFeatureComputer(enable=True)
        terrain = computer._classify_terrain(
            {"regime": "ranging", "atr_percentile": 0.3, "price_amplitude": 1.0, "atr": 1.0}
        )
        assert terrain == "zhi", f"震荡应=支形, got {terrain}"

    def test_yuan_terrain_unclear(self):
        """远形：趋势不明 → 观望/对冲。"""
        computer = FiveDomainFeatureComputer(enable=True)
        terrain = computer._classify_terrain(
            {"regime": "ranging", "atr_percentile": 0.5, "price_amplitude": 2.0, "atr": 1.0}
        )
        assert terrain == "yuan", f"趋势不明应=远形, got {terrain}"


# =====================================================================
# P3 将维度：智/信/仁/勇/严 五维自省评分
# =====================================================================

class TestJiangZhi:
    """P3-1: 智（因子覆盖度/回测完整度）。"""

    def test_high_coverage_high_score(self):
        """因子覆盖度高 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_zhi({"factor_coverage_pct": 0.9})
        assert score > 60, f"高覆盖度应 > 60, got {score}"

    def test_no_data_neutral(self):
        """无数据 → 中性 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_zhi(None)
        assert score == 50


class TestJiangXin:
    """P3-2: 信（IC/胜率/盈亏比）。"""

    def test_good_stats_high_score(self):
        """高胜率+高盈亏比 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_xin({"win_rate": 0.6, "profit_factor": 2.0})
        assert score > 60, f"好统计应 > 60, got {score}"

    def test_poor_stats_low_score(self):
        """低胜率+低盈亏比 → 评分 < 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_xin({"win_rate": 0.3, "profit_factor": 0.8})
        assert score < 50, f"差统计应 < 50, got {score}"


class TestJiangRen:
    """P3-3: 仁（单笔风险/连续亏损降仓）。"""

    def test_safe_risk_high_score(self):
        """单笔≤2%+连续亏损降仓启用 → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_ren({"position_pct": 0.01, "max_consecutive_losses": 3})
        assert score > 60, f"安全风险应 > 60, got {score}"

    def test_unsafe_risk_low_score(self):
        """连续亏损降仓禁用(999) → 评分 < 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_ren({"position_pct": 0.20, "max_consecutive_losses": 999})
        assert score < 50, f"不安全风险应 < 50, got {score}"


class TestJiangYan:
    """P3-4: 严（止损/回撤/单日交易次数/仓位上限）。"""

    def test_all_rules_present(self):
        """4项硬规则全有 → 评分 > 80。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_yan({
            "has_stop_loss": True, "has_drawdown_limit": True,
            "has_daily_trade_limit": True, "has_position_cap": True,
        })
        assert score >= 80, f"全规则应≥80, got {score}"

    def test_missing_daily_trade_limit(self):
        """缺单日交易次数上限 → 评分 = 75。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_yan({
            "has_stop_loss": True, "has_drawdown_limit": True,
            "has_daily_trade_limit": False, "has_position_cap": True,
        })
        assert score == 75, f"缺1项应=75, got {score}"


# =====================================================================
# P4 道维度：大周期位置 / 外部数据fail-open / 三层道架构
# =====================================================================

class TestDaoCycle4Y:
    """P4-1: 4年大周期锚点 t_rel 位置评分。"""

    def test_bottom_zone_high_score(self):
        """底部区域(t_rel<0.25) → 评分 > 70。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_cycle4y_position({"cycle4y_t_rel": 0.1})
        assert score > 70, f"底部应 > 70, got {score}"

    def test_top_zone_low_score(self):
        """顶部区域(t_rel≥0.75) → 评分 < 40。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_cycle4y_position({"cycle4y_t_rel": 0.9})
        assert score < 40, f"顶部应 < 40, got {score}"

    def test_no_data_neutral(self):
        """无数据 → 中性 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_cycle4y_position(None)
        assert score == 50


class TestDaoFailOpen:
    """P4-2: 外部数据缺失 fail-open。"""

    def test_no_external_data_dao_near_neutral(self):
        """无外部数据 → 道分接近中性(50)。"""
        computer = FiveDomainFeatureComputer(enable=True)
        # 无 coin_data → 全 fail-open
        score = computer._compute_dao(None, None, "crypto_usdt")
        # 4个fail-open(50) + 1个无数据(50) → 50
        assert score == 50, f"无外部数据应=50, got {score}"


# =====================================================================
# P5 法维度：策略库完备性 / 回测验证 / 复盘迭代
# =====================================================================

class TestFaCompleteness:
    """P5-1: 策略库完备性。"""

    def test_all_six_implemented(self):
        """6类策略全实现 → 评分 100。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_strategy_completeness(
            {"implemented_strategies": ["trend", "mean_revert", "breakout",
                                        "momentum", "hedge", "emergency"]}
        )
        assert score == 100, f"全实现应=100, got {score}"

    def test_three_implemented(self):
        """3类策略实现 → 评分 50。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_strategy_completeness(
            {"implemented_strategies": ["trend", "breakout", "emergency"]}
        )
        assert score == 50, f"3类应=50, got {score}"


class TestFaBacktest:
    """P5-2: 回测验证度。"""

    def test_good_backtest_high_score(self):
        """夏普>1.5+回撤<20% → 评分 > 60。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_backtest_verification(
            {"backtest_metrics": {"sharpe": 2.0, "max_drawdown": 0.1}}
        )
        assert score > 60, f"好回测应 > 60, got {score}"

    def test_poor_backtest_low_score(self):
        """夏普<0.5+回撤>50% → 评分 < 40。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_backtest_verification(
            {"backtest_metrics": {"sharpe": 0.3, "max_drawdown": 0.6}}
        )
        assert score < 40, f"差回测应 < 40, got {score}"


class TestFaReview:
    """P5-3: 复盘迭代机制。"""

    def test_has_review_and_retirement(self):
        """有复盘周期+策略退役 → 评分 100。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_review_iteration(
            {"has_review_cycle": True, "has_strategy_retirement": True}
        )
        assert score == 100, f"全有应=100, got {score}"

    def test_no_review(self):
        """无复盘 → 评分 0。"""
        computer = FiveDomainFeatureComputer(enable=True)
        score = computer._compute_review_iteration(
            {"has_review_cycle": False, "has_strategy_retirement": False}
        )
        assert score == 0, f"无复盘应=0, got {score}"


# =====================================================================
# P6 三类资产五维特征差异化（修复问题1：差异化权重空转）
# =====================================================================

class TestPerClassCoinDataDifferentiation:
    """P6-1: compute() 须按资产类读取分层 coin_data，输出差异化 five_scores。"""

    def test_flat_coin_data_all_same_legacy_bug(self):
        """【BUG复现】旧版输入全局扁平 coin_data → 三类评分完全相同。"""
        computer = FiveDomainFeatureComputer(enable=True)
        # 旧版：扁平结构，所有资产类读同一套值
        flat_coin_data = {
            "cycle4y_t_rel": 0.15,
            "merrill_phase": "RECOVERY",
            "atr_percentile": 0.55,
            "liquidity_score": 0.60,
            "regime": "ranging",
            "spring_force_score": 65,
            "price_amplitude": 3.0,
            "atr": 1.0,
            "ftd_signal": 0,
            "ma200_distance_percentile": 0.55,
        }
        result = computer.compute(coin_data=flat_coin_data)
        crypto_scores = tuple(result["crypto_usdt"].values())
        stock_scores = tuple(result["us_stock"].values())
        metal_scores = tuple(result["precious_metal"].values())
        # ★ BUG：三类完全相同 → 差异化权重空转
        assert crypto_scores == stock_scores == metal_scores, (
            "BUG未复现？三类评分应相同（扁平输入旧行为）"
            f"crypto={crypto_scores}, stock={stock_scores}, metal={metal_scores}"
        )

    def test_layered_coin_data_produces_differentiated_scores(self):
        """【修复验证】分层 coin_data → 三类 five_scores 存在差异化。"""
        computer = FiveDomainFeatureComputer(enable=True)
        # 新版：按资产类分层，每类有独立市场参数
        layered_coin_data = {
            "crypto_usdt": {
                "cycle4y_t_rel": 0.15,      # BTC减半周期：底部区域
                "merrill_phase": "RECOVERY",# 复苏：利好加密
                "atr_percentile": 0.70,
                "liquidity_score": 0.65,
                "regime": "trend_up",
                "spring_force_score": 72,
                "price_amplitude": 4.5,
                "atr": 1.2,
                "ftd_signal": 1,
                "ma200_distance_percentile": 0.70,
            },
            "us_stock": {
                "cycle4y_t_rel": 0.55,      # 美股总统周期：中段
                "merrill_phase": "OVERHEAT",# 过热：美股承压
                "atr_percentile": 0.40,
                "liquidity_score": 0.50,
                "regime": "ranging",
                "spring_force_score": 55,
                "price_amplitude": 2.0,
                "atr": 0.8,
                "ftd_signal": 0,
                "ma200_distance_percentile": 0.45,
            },
            "precious_metal": {
                "cycle4y_t_rel": 0.35,      # 黄金：中段偏下
                "merrill_phase": "STAGFLATION", # 滞胀：黄金避险利好
                "atr_percentile": 0.50,
                "liquidity_score": 0.55,
                "regime": "breakout",
                "spring_force_score": 68,
                "price_amplitude": 2.8,
                "atr": 0.9,
                "ftd_signal": 0,
                "ma200_distance_percentile": 0.65,
            },
        }
        result = computer.compute(coin_data=layered_coin_data)
        crypto_scores = tuple(result["crypto_usdt"].values())
        stock_scores = tuple(result["us_stock"].values())
        metal_scores = tuple(result["precious_metal"].values())
        # 三类 five_scores 至少有一类不同 → 差异化权重不再空转
        assert not (crypto_scores == stock_scores == metal_scores), (
            "差异化输入后三类评分仍完全相同！分层coin_data读取未生效\n"
            f"crypto={crypto_scores}\nstock={stock_scores}\nmetal={metal_scores}"
        )

    def test_coin_data_lookup_by_asset_class_key(self):
        """分层coin_data必须按cls键正确读取，fallback兼容旧扁平结构。"""
        computer = FiveDomainFeatureComputer(enable=True)
        # 仅给crypto数据，其他类无分层数据 → 应该fail-open=50读取
        partial_layered = {
            "crypto_usdt": {"cycle4y_t_rel": 0.10},  # 底部→dao分高
        }
        result = computer.compute(coin_data=partial_layered)
        crypto_dao = result["crypto_usdt"]["dao"]
        stock_dao = result["us_stock"]["dao"]
        metal_dao = result["precious_metal"]["dao"]
        # crypto: 4个50(外部) + 80(底部) → (4*50+80)/5 = 56 → normalize=56
        # stock/metal: 全部无数据fail-open=50
        assert crypto_dao >= 55, f"crypto dao应≥55（读到底部t_rel）, got {crypto_dao}"
        # 兼容性：非分层key（扁平）不影响，stock/metal dao=50 中性
        assert stock_dao == 50, f"us_stock缺分层dao应fail-open=50, got {stock_dao}"
        assert metal_dao == 50, f"metal缺分层dao应fail-open=50, got {metal_dao}"


# =====================================================================
# P7 开关描述辅助函数（修复问题2：初始化日志描述不准确）
# =====================================================================

class TestSubswitchDescriptor:
    """P7-1: 7子开关开启状态 → 日志描述生成（修复「7子开关全False」描述bug）。"""

    def test_all_7_subswitches_false_descriptor(self):
        """7子开关全False → 描述包含「全False」和「下游零影响」。"""
        from strategy_algo_layer import StrategyAlgoConfig
        cfg = StrategyAlgoConfig(
            enable_strategy_layer=True,
            enable_five_domain=False,
            enable_five_domain_shadow_mode=True,
            # 7子开关全False
            enable_five_domain_war_state=False,
            enable_five_domain_style_mask=False,
            enable_five_domain_position_cap=False,
            enable_five_domain_cross_asset=False,
            enable_five_domain_dimensio=False,
            enable_five_domain_front_layer_band=False,
            enable_five_domain_ol=False,
        )
        from five_domain_feature_computer import describe_five_domain_subswitches
        desc = describe_five_domain_subswitches(cfg)
        assert "7子开关全False" in desc, f"描述应含'7子开关全False', got: {desc}"
        assert "下游零影响" in desc, f"描述应含'下游零影响', got: {desc}"

    def test_style_mask_only_true_descriptor(self):
        """仅enable_five_domain_style_mask=True（当前生产配置）→ 描述包含具体开关，不得写'全False'。"""
        from strategy_algo_layer import StrategyAlgoConfig
        cfg = StrategyAlgoConfig(
            enable_strategy_layer=True,
            enable_five_domain=False,
            enable_five_domain_shadow_mode=True,
            enable_five_domain_war_state=False,
            enable_five_domain_style_mask=True,   # B1 单独开启
            enable_five_domain_position_cap=False,
            enable_five_domain_cross_asset=False,
            enable_five_domain_dimensio=False,
            enable_five_domain_front_layer_band=False,
            enable_five_domain_ol=False,
        )
        from five_domain_feature_computer import describe_five_domain_subswitches
        desc = describe_five_domain_subswitches(cfg)
        assert "全False" not in desc, (
            f"style_mask=True时描述不应出现'全False'，got: {desc}"
        )
        assert "style_mask" in desc.lower() or "B1" in desc, (
            f"描述应包含style_mask/B1标识，got: {desc}"
        )

    def test_multiple_subswitches_true_lists_names(self):
        """多子开关True → 描述列出所有开启项名称。"""
        from strategy_algo_layer import StrategyAlgoConfig
        cfg = StrategyAlgoConfig(
            enable_strategy_layer=True,
            enable_five_domain=False,
            enable_five_domain_shadow_mode=True,
            enable_five_domain_war_state=True,    # B2
            enable_five_domain_style_mask=True,   # B1
            enable_five_domain_position_cap=True, # B3
            enable_five_domain_cross_asset=False,
            enable_five_domain_dimensio=False,
            enable_five_domain_front_layer_band=False,
            enable_five_domain_ol=False,
        )
        from five_domain_feature_computer import describe_five_domain_subswitches
        desc = describe_five_domain_subswitches(cfg)
        assert "war_state" in desc.lower() or "B2" in desc
        assert "style_mask" in desc.lower() or "B1" in desc
        assert "position_cap" in desc.lower() or "B3" in desc
        assert "3个子开关" in desc or "共3" in desc
