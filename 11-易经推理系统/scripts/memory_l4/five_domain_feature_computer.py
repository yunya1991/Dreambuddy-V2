#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FiveDomainFeatureComputer —— 五计庙算特征→评分计算层。

Spec: 2026-08-22-five-domain-feature-computer-design.md
上游: 2026-08-21-sunzi-five-domains-evaluation.md §三逐维打分详解

职责：从现有 bcrm2 特征 + 后置层 regime + 系统自省
      计算五维原始评分(0-100)，传给 FiveDomainHeuristicScorer.score_and_decide()。

周期（§11.1 L1204）：
  - 战略层日级一次粗评分
  - 道维度周级离线批打分不进热路径
  - 5min 热路径只读缓存快照

Fail-open（§九 L1180）：
  - enable=False → 返回 DEFAULT_NEUTRAL_SCORES
  - 子指标异常 → 中性 50
  - 整个 compute() 异常 → DEFAULT_NEUTRAL_SCORES
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np

try:  # noqa: E402 兼容包内相对导入和独立运行
    from .strategy_algo_layer import (
        ASSET_CLASSES,
        DEFAULT_NEUTRAL_SCORES,
        _normalize_0_100,
    )
except ImportError:
    from strategy_algo_layer import (
        ASSET_CLASSES,
        DEFAULT_NEUTRAL_SCORES,
        _normalize_0_100,
    )


# 美林时钟四阶段→天维度评分映射（§三 L128：复苏对风险资产利好→加分）
_MERRILL_PHASE_SCORES: Dict[str, int] = {
    "RECOVERY": 70,      # 复苏期：资金流入altcoin → 利好
    "OVERHEAT": 60,      # 过热期：altcoin疯狂但风险高
    "STAGFLATION": 40,   # 滞胀期：资金回流BTC
    "REFLATION": 30,     # 衰退期：资金流出加密市场
}

# 日历季节性基础分（§三 L127：Q1效应/Q4效应/周末效应/减半周期季节性）
# 基于BTC历史季度收益统计
_MONTH_BASE_SCORES: Dict[int, int] = {
    1: 68, 2: 65, 3: 62,   # Q1：历史正收益效应
    4: 55, 5: 52, 6: 48,   # Q2：混合表现
    7: 42, 8: 40, 9: 38,   # Q3：历史弱势（夏季低迷）
    10: 58, 11: 62, 12: 65 # Q4：历史强势（年底效应）
}


class FiveDomainFeatureComputer:
    """五维原始评分计算器：市场数据 + 系统状态 → 0-100 评分。

    Args:
        enable: 总开关。False 时返回中性默认值（字节等价战略层不存在）。
    """

    def __init__(self, enable: bool = True):
        self.enable = enable

    # ==================================================================
    # 公共入口
    # ==================================================================

    # 分层coin_data的判定键集合：若dict顶层存在这些键之一，则视为扁平结构
    _FLAT_COIN_DATA_KEYS = frozenset({
        "cycle4y_t_rel", "merrill_phase", "atr_percentile", "liquidity_score",
        "regime", "spring_force_score", "price_amplitude", "atr", "ftd_signal",
        "ma200_distance_percentile",
    })

    @classmethod
    def _resolve_class_coin_data(
        cls,
        coin_data: Optional[Dict[str, Any]],
        asset_class: str,
    ) -> Optional[Dict[str, Any]]:
        """按资产类解析coin_data：优先分层结构，缺失fallback到扁平结构。

        ★ FIX 问题1：差异化权重空转。
        - 分层结构：coin_data = {"crypto_usdt": {...}, "us_stock": {...}, ...}
          → 读取 coin_data[asset_class]
        - 扁平结构（旧版兼容）：coin_data = {"cycle4y_t_rel": ..., ...}
          → 直接原样返回
        - 分层结构中某类缺失：返回 None → 各维度 fail-open=50
        """
        if not coin_data:
            return None
        # 判定结构：若顶层存在扁平键，则是旧版扁平结构（或混合模式下该类不支持分层）
        has_flat_keys = bool(cls._FLAT_COIN_DATA_KEYS & coin_data.keys())
        # 尝试分层读取：仅当顶层不存在 ASSET_CLASS 以外的扁平键 或 明确存在 asset_class key
        if asset_class in coin_data:
            subset = coin_data[asset_class]
            if isinstance(subset, dict):
                return subset
        # 存在扁平键 → 视为扁平结构，原样返回保持兼容
        if has_flat_keys:
            return coin_data
        # 既无分层对应类数据，也无扁平键 → 无该类市场数据，fail-open=None
        return None

    def compute(
        self,
        coin_data: Optional[Dict[str, Any]] = None,
        system_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, int]]:
        """计算五维原始评分。

        Returns:
            Dict[asset_class, Dict[domain, int(0-100)]]
            asset_class ∈ ASSET_CLASSES
            domain ∈ {dao, tian, di, jiang, fa}

        支持两种 coin_data 输入格式：
        1) 分层结构（推荐，修复差异化问题）：
           {"crypto_usdt": {cycle4y_t_rel, merrill...}, "us_stock": {...}, ...}
        2) 扁平结构（兼容旧版）：
           {cycle4y_t_rel, merrill...} → 三类共享相同输入
        """
        if not self.enable:
            return {cls: dict(DEFAULT_NEUTRAL_SCORES) for cls in ASSET_CLASSES}

        try:
            result: Dict[str, Dict[str, int]] = {}
            for cls in ASSET_CLASSES:
                # ★ FIX 问题1：按资产类解析 coin_data，每类独立数据源
                cls_coin = self._resolve_class_coin_data(coin_data, cls)
                result[cls] = {
                    "dao": self._compute_dao(cls_coin, system_state, cls),
                    "tian": self._compute_tian(cls_coin, system_state, cls),
                    "di": self._compute_di(cls_coin, system_state, cls),
                    "jiang": self._compute_jiang(system_state, cls),
                    "fa": self._compute_fa(system_state, cls),
                }
            return result
        except Exception:
            # fail-open：整体异常→中性默认
            return {cls: dict(DEFAULT_NEUTRAL_SCORES) for cls in ASSET_CLASSES}

    # ==================================================================
    # 道 — 方向一致性（§三 L82-110）
    # ==================================================================

    def _compute_dao(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """道维度：5个子指标——P1用代理指标替代fail-open=50。

        §三 L82-110：
        - 子指标1: 央行政策方向 → fedfunds_rate 代理（降息=宽松→高分）
        - 子指标2: 机构资金净流入 → stablecoin_mcap_bln 代理（加密专用，其他类fail-open）
        - 子指标3: 政策景气度 → policy_sentiment_score 代理（加密专用）
        - 子指标4: 变化率(一阶差分) → fail-open 50（需历史对比，日级无法计算）
        - 子指标5: 大周期位置 → cycle4y_t_rel（已实现）
        P1: 前3个子指标用 coin_data 中的代理指标，缺失时 fail-open=50
        """
        try:
            # 子指标1: 央行政策方向 → fedfunds_rate 代理
            rate = (coin_data or {}).get("fedfunds_rate")
            if rate is not None and isinstance(rate, (int, float)):
                # 联邦基金利率 < 2% = 宽松 → 高分(70-85)；> 5% = 紧缩 → 低分(30-45)
                rate_score = int(np.clip(round(85 - rate * 8), 0, 100))
            else:
                rate_score = 50  # fail-open

            # 子指标2: 机构资金净流入 → stablecoin_mcap_bln 代理（仅 crypto 有值）
            stablecoin = (coin_data or {}).get("stablecoin_mcap_bln")
            if stablecoin is not None and isinstance(stablecoin, (int, float)) and stablecoin > 0:
                # 稳定币市值 > 150bn = 资金充裕 → 高分；< 80bn = 资金流出 → 低分
                sc_score = int(np.clip(round((stablecoin - 80) / 2), 30, 85))
            else:
                sc_score = 50  # fail-open（非 crypto 类或数据缺失）

            # 子指标3: 政策景气度 → policy_sentiment_score 代理（仅 crypto 有值）
            # 注意：fetcher._sentiment_score 返回 0-1 范围（0.5=中性），需 ×100 映射
            sentiment = (coin_data or {}).get("policy_sentiment_score")
            if sentiment is not None and isinstance(sentiment, (int, float)):
                # 0-1 → 0-100：sentiment=0.5→50中性, sentiment=1.0→100全利好
                # 兼容：若传入已是 0-100 范围（>1.0），则直接使用
                sent_val = sentiment * 100.0 if 0.0 <= sentiment <= 1.0 else sentiment
                sent_score = int(np.clip(round(sent_val), 0, 100))
            else:
                sent_score = 50  # fail-open

            # 子指标4: 变化率 → 稳定币市值一阶差分（P2-3 接入真实数据）
            # stablecoin_change_rate = (当前 - 上次) / 上次
            sc_change = (coin_data or {}).get("stablecoin_change_rate")
            if sc_change is not None and isinstance(sc_change, (int, float)):
                # 正变化率→资金流入→高分；负变化率→资金流出→低分
                # 映射：±5% 变化 → 30~70 分，0%→50 中性
                diff_score = int(np.clip(round(50 + sc_change * 400), 0, 100))
            else:
                diff_score = 50  # fail-open（首次运行无历史快照）

            # 子指标5: 大周期位置 → cycle4y_t_rel（已实现）
            cycle_score = self._compute_cycle4y_position(coin_data)

            # 5个子指标等权
            dao_raw = (rate_score + sc_score + sent_score + diff_score + cycle_score) / 5.0
            return _normalize_0_100(dao_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["dao"]

    def _compute_cycle4y_position(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """4年周期锚点 t_rel 位置→评分。

        §三 L100：底部区域→加分，顶部区域→减分。
        """
        if not coin_data:
            return 50
        # 从 coin_data 读取 t_rel（如果存在）
        t_rel = coin_data.get("cycle4y_t_rel")
        if t_rel is None:
            return 50
        # t_rel ∈ [0, 1]：0=周期起点（底部），1=周期终点（顶部）
        # 底部→高分（70-90），中段→中分（50-70），顶部→低分（30-50）
        if t_rel < 0.25:
            return 80  # 底部区域：加高分
        elif t_rel < 0.50:
            return 65  # 上升初期
        elif t_rel < 0.75:
            return 50  # 中段偏热
        else:
            return 35  # 顶部区域：减分

    # ==================================================================
    # 天 — 时间节奏（§三 L114-138）
    # ==================================================================

    def _compute_tian(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """天维度：日历季节性 + 美林时钟 + 波动率周期 + 流动性周期。"""
        try:
            now = datetime.now()
            month = now.month
            day = now.day
            weekday = now.weekday()  # 0=Mon, 6=Sun

            # 子指标1：日历季节性
            cal_score = self._compute_calendar_seasonality(month, day, weekday)

            # 子指标2：美林时钟位置
            phase = (coin_data or {}).get("merrill_phase", "RECOVERY")
            merrill_score = self._compute_merrill_clock_score(phase)

            # 子指标3：波动率周期（ATR分位）
            atr_percentile = (coin_data or {}).get("atr_percentile", 0.5)
            vol_score = self._compute_volatility_cycle_score(atr_percentile)

            # 子指标4：流动性周期
            liquidity_score = (coin_data or {}).get("liquidity_score", 0.5)
            liq_score = self._compute_liquidity_cycle_score(liquidity_score)

            # 4子指标等权（§三未指定权重，§八 L1166：不要把季节性权重给太高）
            tian_raw = (cal_score + merrill_score + vol_score + liq_score) / 4.0
            return _normalize_0_100(tian_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["tian"]

    def _compute_calendar_seasonality(
        self, month: int, day: int = 15, weekday: int = 0
    ) -> int:
        """日历季节性：Q1/Q4效应 + 周末效应。

        §三 L127：统计历史均值，正收益期→加分。
        """
        base = _MONTH_BASE_SCORES.get(month, 50)

        # 周末效应（§三 L127）：周末波动率低 → 评分中性偏低
        if weekday >= 5:  # 周六/日
            base = max(40, base - 5)

        return int(np.clip(base, 0, 100))

    def _compute_merrill_clock_score(self, phase: str) -> int:
        """美林时钟四阶段→评分映射。

        §三 L128：复苏对风险资产利好→加分。
        """
        return _MERRILL_PHASE_SCORES.get(phase.upper(), 50)

    def _compute_volatility_cycle_score(self, atr_percentile: float) -> int:
        """波动率周期：ATR分位→评分。

        §三 L129：高位适合趋势策略，低位适合均值回归。
        """
        # atr_percentile ∈ [0, 1]
        # 高分位→趋势策略利好→高分；低分位→均值回归→中分
        # 线性映射：0→45, 1→85
        score = 45 + atr_percentile * 40
        return int(np.clip(round(score), 0, 100))

    def _compute_liquidity_cycle_score(self, liquidity_score: float) -> int:
        """流动性周期：QE/QT阶段→评分。

        §三 L130：QE→加分，QT→减分。
        """
        # liquidity_score ∈ [0, 1]：0=QT（紧缩），1=QE（宽松）
        # 线性映射：0→25, 1→75
        score = 25 + liquidity_score * 50
        return int(np.clip(round(score), 0, 100))

    # ==================================================================
    # 地 — 市场结构与价格位置（§三 L142-172）
    # ==================================================================

    def _compute_di(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """地维度：regime代理 + 弹簧力场MA + 补强指标。"""
        try:
            # 子指标1：regime 代理（后置层5态→分数映射）
            regime = (coin_data or {}).get("regime", "ranging")
            regime_score = self._compute_regime_score(regime)

            # 子指标2：弹簧力场MA评分
            ma_score = self._compute_spring_force_score(coin_data)

            # 子指标3-5：补强指标（盘整持续/FTD/MA200距离）
            consolidation = self._compute_consolidation_duration(coin_data)
            ftd = self._compute_follow_through_day(coin_data)
            ma200_dist = self._compute_ma200_distance(coin_data)

            # 5子指标等权
            di_raw = (regime_score + ma_score + consolidation + ftd + ma200_dist) / 5.0
            return _normalize_0_100(di_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["di"]

    def _compute_regime_score(self, regime: str) -> int:
        """后置层5态→分数映射。

        §11.1 L1204：地=regime→分数映射。
        """
        _REGIME_SCORES = {
            "trend_up": 75,      # 上升趋势
            "trend_down": 30,    # 下降趋势
            "ranging": 50,       # 震荡
            "high_volatility": 45, # 高波动
            "breakout": 70,      # 突破
        }
        return _REGIME_SCORES.get(regime, 50)

    def _compute_spring_force_score(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """弹簧力场5MA评分。

        §三 L147：MA30/65/128/200 + 1400大周期。
        """
        if not coin_data:
            return 50
        # 从 coin_data 读取弹簧力场评分（如果存在）
        spring = coin_data.get("spring_force_score")
        if spring is None:
            return 50
        return int(np.clip(round(spring), 0, 100))

    def _compute_consolidation_duration(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """盘整持续时间量化。

        §三 L153：价格振幅/ATR比值，持续低于阈值=盘整。
        """
        if not coin_data:
            return 50
        amplitude = coin_data.get("price_amplitude")
        atr = coin_data.get("atr")
        if amplitude is None or atr is None or atr <= 0:
            return 50
        # 振幅/ATR比值低 → 盘整 → 中性偏低（适合均值回归）
        ratio = float(amplitude) / float(atr)
        if ratio < 2.0:
            return 45  # 盘整
        elif ratio < 4.0:
            return 55  # 正常
        else:
            return 65  # 趋势

    def _compute_follow_through_day(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """Follow-through Day确认。

        §三 L154：下跌→上涨转换信号。
        """
        if not coin_data:
            return 50
        ftd_signal = coin_data.get("ftd_signal")
        if ftd_signal is None:
            return 50
        if ftd_signal > 0:
            return 70  # FTD正面信号
        elif ftd_signal < 0:
            return 30  # FTD负面信号
        return 50

    def _compute_ma200_distance(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """价格vs MA200距离分位。

        §三 L155：分位统计。
        """
        if not coin_data:
            return 50
        ma200_dist_pct = coin_data.get("ma200_distance_percentile")
        if ma200_dist_pct is None:
            return 50
        # 距离MA200上方远 → 强势 → 高分
        # 距离MA200下方远 → 弱势 → 低分
        score = 50 + (ma200_dist_pct - 0.5) * 60
        return int(np.clip(round(score), 0, 100))

    # ==================================================================
    # P0-辅助：_cls_get 按类取值优先，缺失回退全局字段（方案 A 增量嵌套 + 全局回退）
    # ==================================================================
    @staticmethod
    def _cls_get(
        system_state: Optional[Dict[str, Any]],
        cls: str,
        key: str,
        default: Any,
    ) -> Any:
        """按优先级：system_state['_by_class'][cls][key] > system_state[key] > default。

        方案 A：fail-open 三层兜底——即使调用方没传 _by_class，也完全兼容旧行为。
        """
        if not system_state:
            return default
        # 1. 优先取按类嵌套值
        by_cls = system_state.get("_by_class")
        if isinstance(by_cls, dict):
            cls_block = by_cls.get(cls)
            if isinstance(cls_block, dict) and (key in cls_block):
                return cls_block[key]
        # 2. 回退：取全局根级值
        if key in system_state:
            return system_state[key]
        # 3. 兜底：默认值
        return default

    # ==================================================================
    # 将 — 决策质量与执行纪律（§三 L176-210）
    # ==================================================================

    def _classify_terrain(self, coin_data: Optional[Dict[str, Any]]) -> str:
        """六种地形分类（§三 L157-166，《孙子兵法·地形篇》）。

        Returns: tong/gua/zhi/ai/xian/yuan
        """
        if not coin_data:
            return "yuan"  # 无数据→远形（观望）
        regime = coin_data.get("regime", "ranging")
        atr_pct = coin_data.get("atr_percentile", 0.5)
        amplitude = coin_data.get("price_amplitude", 0.0)
        atr = coin_data.get("atr", 1.0)
        ratio = amplitude / atr if atr > 0 else 0.0

        # 通形：趋势明确（trend + 高振幅）
        if regime in ("trend_up", "trend_down") and ratio > 3.0:
            return "tong"
        # 挂形：突破后难回撤（trend + 低振幅）
        if regime in ("trend_up", "trend_down") and ratio <= 3.0:
            return "gua"
        # 险形：高波动区间（ranging + 高ATR分位）
        if regime == "ranging" and atr_pct > 0.7:
            return "xian"
        # 支形：震荡盘整（ranging + 低振幅）
        if regime == "ranging" and ratio < 2.0:
            return "zhi"
        # 隘形：关键支撑阻力位（ranging + 中振幅 + 低ATR）
        if regime == "ranging" and atr_pct < 0.4 and 2.0 <= ratio <= 3.0:
            return "ai"
        # 远形：趋势不明（其余）
        return "yuan"

    def _compute_jiang(
        self,
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """将维度：智×20% + 信×25% + 仁×25% + 勇×15% + 严×15%。

        §三 L196：将 = 智×20% + 信×25% + 仁×25% + 勇×15% + 严×15%
        P0：5子指标按 cls 优先读 _by_class[cls]，缺失回退全局字段。
        """
        try:
            zhi = self._compute_zhi(system_state, cls)
            xin = self._compute_xin(system_state, cls)
            ren = self._compute_ren(system_state, cls)
            yong = self._compute_yong(system_state, cls)
            yan = self._compute_yan(system_state, cls)

            jiang_raw = zhi * 0.20 + xin * 0.25 + ren * 0.25 + yong * 0.15 + yan * 0.15
            return _normalize_0_100(jiang_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["jiang"]

    def _compute_zhi(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """智：因子覆盖度/回测完整度/样本外验证。P0：按 cls 取值。"""
        if not system_state:
            return 50
        factor_coverage = self._cls_get(system_state, cls, "factor_coverage_pct", 0.5)
        score = factor_coverage * 100
        return int(np.clip(round(score), 0, 100))

    def _compute_xin(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """信：IC/胜率/盈亏比。P0：按 cls 取值实现差异化 win_rate/profit_factor。"""
        if not system_state:
            return 50
        win_rate = self._cls_get(system_state, cls, "win_rate", 0.5)
        profit_factor = self._cls_get(system_state, cls, "profit_factor", 1.0)
        wr_score = win_rate * 100
        pf_score = min(100, (profit_factor / 2.0) * 100)
        return int(np.clip(round((wr_score + pf_score) / 2.0), 0, 100))

    def _compute_ren(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """仁：单笔风险≤1-2%/连续亏损降仓。P0：按 cls 取值。"""
        if not system_state:
            return 50
        position_pct = self._cls_get(system_state, cls, "position_pct", 0.20)
        max_consecutive = self._cls_get(system_state, cls, "max_consecutive_losses", 999)
        risk_score = 80 if position_pct <= 0.02 else 50
        rule_score = 80 if max_consecutive <= 5 else 30
        return int(np.clip(round((risk_score + rule_score) / 2.0), 0, 100))

    def _compute_yong(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """勇：执行果断。P0：按 cls 取值（当前全局相同，未来可按类设置自动执行权限）。"""
        if not system_state:
            return 50
        auto_execute = self._cls_get(system_state, cls, "auto_execute", False)
        return 80 if auto_execute else 50

    def _compute_yan(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """严：止损/回撤/单日交易次数/仓位上限。P0：按 cls 取值。"""
        if not system_state:
            return 50
        has_stop_loss = self._cls_get(system_state, cls, "has_stop_loss", True)
        has_drawdown_limit = self._cls_get(system_state, cls, "has_drawdown_limit", True)
        has_daily_trade_limit = self._cls_get(system_state, cls, "has_daily_trade_limit", False)
        has_position_cap = self._cls_get(system_state, cls, "has_position_cap", True)
        score = (has_stop_loss * 25 + has_drawdown_limit * 25 +
                 has_daily_trade_limit * 25 + has_position_cap * 25)
        return int(np.clip(round(score), 0, 100))

    # ==================================================================
    # 法 — 策略库与执行规则（§三 L214-242）
    # ==================================================================

    def _compute_fa(
        self,
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """法维度：策略库完备性×20% + 策略适配度×25% + 风控规则×25% + 回测验证×20% + 复盘迭代×10%。

        §三 L240：法 = 策略库完备性×20% + 策略适配度×25% + 风控规则×25% + 回测验证×20% + 复盘迭代×10%
        P0：5子指标按 cls 优先读 _by_class[cls]，缺失回退全局字段。
        """
        try:
            completeness = self._compute_strategy_completeness(system_state, cls)
            adaptation = self._compute_strategy_adaptation(system_state, cls)
            risk_rules = self._compute_risk_rule_completeness(system_state, cls)
            backtest = self._compute_backtest_verification(system_state, cls)
            review = self._compute_review_iteration(system_state, cls)

            fa_raw = (completeness * 0.20 + adaptation * 0.25 +
                      risk_rules * 0.25 + backtest * 0.20 + review * 0.10)
            return _normalize_0_100(fa_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["fa"]

    def _compute_strategy_completeness(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """策略库完备性：6类策略是否实现。P0：按 cls 取值（不同类策略库可以不同）。"""
        if not system_state:
            return 50
        implemented = self._cls_get(system_state, cls, "implemented_strategies", [])
        total = 6
        count = len([s for s in implemented if s])
        score = (count / total) * 100
        return int(np.clip(round(score), 0, 100))

    def _compute_strategy_adaptation(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """策略适配度：地形vs策略匹配。P0：按 cls 取值。"""
        if not system_state:
            return 50
        match_pct = self._cls_get(system_state, cls, "strategy_match_pct", 0.5)
        return int(np.clip(round(match_pct * 100), 0, 100))

    def _compute_risk_rule_completeness(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """风控规则完整度：止损/回撤/仓位/相关性。P0：按 cls 取值（不同类风控强度可以不同）。"""
        if not system_state:
            return 50
        rules = self._cls_get(system_state, cls, "risk_rules", {})
        rules = rules if isinstance(rules, dict) else {}
        has_sl = rules.get("stop_loss", True)
        has_dd = rules.get("drawdown_limit", True)
        has_pos = rules.get("position_cap", True)
        has_corr = rules.get("correlation_limit", False)
        score = (has_sl + has_dd + has_pos + has_corr) * 25
        return int(np.clip(round(score), 0, 100))

    def _compute_backtest_verification(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """回测验证度：样本外/夏普/最大回撤/换手率。P0：按 cls 取值（不同类夏普/回撤差异显著）。"""
        if not system_state:
            return 50
        backtest = self._cls_get(system_state, cls, "backtest_metrics", {})
        backtest = backtest if isinstance(backtest, dict) else {}
        sharpe = backtest.get("sharpe", 0.0)
        max_dd = backtest.get("max_drawdown", 0.5)
        sharpe_score = min(100, (sharpe / 2.0) * 100)
        dd_score = max(0, 100 - max_dd * 200)
        return int(np.clip(round((sharpe_score + dd_score) / 2.0), 0, 100))

    def _compute_review_iteration(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """复盘迭代机制：定期归因/降权/退役。P0：按 cls 取值。"""
        if not system_state:
            return 50
        has_review = self._cls_get(system_state, cls, "has_review_cycle", False)
        has_retirement = self._cls_get(system_state, cls, "has_strategy_retirement", False)
        score = (has_review + has_retirement) * 50
        return int(np.clip(round(score), 0, 100))


# =====================================================================
# 辅助函数：7子开关状态 → 人类可读日志描述（修复问题2：描述不准确）
# =====================================================================

# 7子开关 → 编号(B1-B7)+短名 映射
_SUB_SWITCH_NAME_MAP = (
    # (attr_name,                code, short_label)
    ("enable_five_domain_style_mask",           "B1", "style_mask"),
    ("enable_five_domain_war_state",             "B2", "war_state"),
    ("enable_five_domain_position_cap",          "B3", "position_cap"),
    ("enable_five_domain_cross_asset",           "B4", "cross_asset"),
    ("enable_five_domain_dimensio",              "B5", "dimension_veto"),
    ("enable_five_domain_front_layer_band",      "B6", "front_layer_band"),
    ("enable_five_domain_ol",                    "B7", "ol_position_mult"),
)


def describe_five_domain_subswitches(cfg: Any) -> str:
    """根据 StrategyAlgoConfig 生成准确的子开关状态日志描述。

    修复：原日志硬编码「7子开关全False=下游零影响」，
    当 enable_five_domain_style_mask=True（或其他任一子开关开启）时描述失真。

    Returns:
        形如：
        - 全关：「7子开关全False=下游零影响」
        - B1单开：「仅1个子开关开启（B1:style_mask），其余6项下游零影响」
        - 多开：「共3个子开关开启：B1(style_mask)、B2(war_state)、B3(position_cap)」
    """
    enabled: list[tuple[str, str]] = []
    for attr, code, label in _SUB_SWITCH_NAME_MAP:
        if getattr(cfg, attr, False):
            enabled.append((code, label))

    if not enabled:
        return "7子开关全False=下游零影响"

    if len(enabled) == 1:
        code, label = enabled[0]
        others = len(_SUB_SWITCH_NAME_MAP) - len(enabled)
        return (
            f"仅1个子开关开启（{code}:{label}），"
            f"其余{others}项下游零影响"
        )

    # 多个开启
    items = "、".join(f"{c}({n})" for c, n in enabled)
    return f"共{len(enabled)}个子开关开启：{items}"
