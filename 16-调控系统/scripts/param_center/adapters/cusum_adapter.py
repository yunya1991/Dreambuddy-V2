"""CUSUM 适配器 — 结构性突变事件 → 触发重新归总

真实依赖: 23-四层闭环自进化交易架构/dreambuddy_evolution/core/structural_break_detector.py
  (旧路径 memory_l4.correlation_break 不存在，已废弃)

StructuralBreakDetector.detect_all(price, returns=None, benchmark=None) -> dict
  返回 4 个 key:
    - volatility_regime_shift: {detected, current_regime: high_vol/low_vol, ...}
    - correlation_break:        {detected, p_value, t_statistic, mean_diff, ...}
    - market_form_shift:        {detected, current_form: trend/revert/random, ...}
    - any_structural_break:     bool

输出策略:
  - 无突变 → None（聚合器自动跳过，不干扰稳态参数）
  - 突变 + market_form="trend" → 上涨突变 → 紧SL宽TP
  - 突变 + market_form="revert" → 下跌/反转突变 → 宽SL紧TP
  - 突变 + volatility_regime="high_vol" → 高波动 → 提升 ATR 倍数
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
from typing import Optional

from ..aggregator import AlgoObservation
from .base import BaseAdapter

# 路径设置：注入 23-四层闭环自进化交易架构 到 sys.path
_THIS = _Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent.parent          # .../16-调控系统/scripts
_PROJECT_ROOT = _SCRIPTS_16.parent.parent          # dreambuddy-v2
_EVO_ROOT = _PROJECT_ROOT / "23-四层闭环自进化交易架构"
if str(_EVO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_EVO_ROOT))


class CusumAdapter(BaseAdapter):
    name = "cusum"

    def _observe_impl(
        self,
        symbol: str,
        market_data: Optional[dict] = None,
    ) -> Optional[AlgoObservation]:
        if not market_data or "closes" not in market_data:
            return None

        closes = market_data["closes"]
        if len(closes) < 120:  # StructuralBreakDetector 需要 min_samples=60
            return None

        try:
            from dreambuddy_evolution.core.structural_break_detector import (
                StructuralBreakDetector,
            )
            detector = StructuralBreakDetector(min_samples=60)
            # detect_all 接受 price ndarray
            result = detector.detect_all(closes)
        except Exception:
            return None

        if not result or not result.get("any_structural_break", False):
            return None  # 无突变 → 不贡献观察

        # 综合 market_form_shift + volatility_regime_shift
        mfs = result.get("market_form_shift") or {}
        vrs = result.get("volatility_regime_shift") or {}

        current_form = str(mfs.get("current_form", "random"))  # trend/revert/random
        vol_regime = str(vrs.get("current_regime", "normal"))   # high_vol/low_vol

        # 基础参数
        sl_floor = 0.05
        tp_floor = 0.15
        atr_mult = 4.5
        confidence = 0.75

        # market_form 影响 SL/TP
        if current_form == "trend":
            # 趋势态 → 紧SL宽TP
            sl_floor = 0.04
            tp_floor = 0.20
            confidence = 0.8
        elif current_form == "revert":
            # 反转/震荡 → 宽SL紧TP
            sl_floor = 0.08
            tp_floor = 0.12
            confidence = 0.8

        # vol_regime 影响 ATR 倍数
        if vol_regime == "high_vol":
            atr_mult = 5.5  # 高波动 → 更宽的 ATR 倍数
            confidence = min(0.95, confidence + 0.1)
        elif vol_regime == "low_vol":
            atr_mult = 3.5  # 低波动 → 收紧 ATR 倍数

        return AlgoObservation(
            algo_name=self.name,
            params={
                "sl_floor": sl_floor,
                "tp_floor": tp_floor,
                "atr_mult": atr_mult,
            },
            confidence=confidence,
        )
