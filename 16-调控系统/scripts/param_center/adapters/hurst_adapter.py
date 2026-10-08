"""Hurst Exponent 适配器 — 趋势持续性 → 参数调整系数

依赖: 11-易经推理系统/scripts/memory_l4/bcrm2/classic_experience_features.py
输出: hurst_category (0/1/2) → 调整系数

真实接口签名 (compute_hurst_features L703-725):
  返回 dict {hurst_exp_50, hurst_exp_100, hurst_category}
  hurst_category 是 int (0/1/2)，不是字符串：
    - 0: H<0.45 均值回归（震荡态）→ "range"
    - 1: 0.45≤H≤0.55 随机游走 → "random"
    - 2: H>0.55 趋势性 → "trend"
"""
from __future__ import annotations

from typing import Optional

from ..aggregator import AlgoObservation
from .base import BaseAdapter

# Hurst category (int) → 调整系数
# 真实返回: 0=均值回归, 1=随机, 2=趋势
_HURST_ADJUST = {
    0: {"sl_mult": 0.85, "tp_mult": 1.0},   # 震荡 → 收紧止损（趋势不明，快止损），止盈不变保持RR
    1: {"sl_mult": 1.0, "tp_mult": 1.0},   # 随机 → 不变
    2: {"sl_mult": 0.9, "tp_mult": 1.2},  # 趋势 → 紧SL宽TP
}
_BASE = {"sl_floor": 0.05, "tp_floor": 0.15, "atr_mult": 4.5}


class HurstAdapter(BaseAdapter):
    name = "hurst"

    def _observe_impl(
        self,
        symbol: str,
        market_data: Optional[dict] = None,
    ) -> Optional[AlgoObservation]:
        if not market_data or "closes" not in market_data:
            return None

        closes = market_data["closes"]
        if len(closes) < 100:
            return None

        try:
            from memory_l4.bcrm2.classic_experience_features import compute_hurst_features
            feats = compute_hurst_features(closes)
            # 真实返回 int 0/1/2（不是字符串）
            category_raw = feats.get("hurst_category", 1)
            category = int(category_raw)
        except Exception:
            category = 1  # 默认随机

        adjust = _HURST_ADJUST.get(category, _HURST_ADJUST[1])
        return AlgoObservation(
            algo_name=self.name,
            params={
                "sl_floor": max(0.03, _BASE["sl_floor"] * adjust["sl_mult"]),
                "tp_floor": max(0.12, _BASE["tp_floor"] * adjust["tp_mult"]),
                "atr_mult": _BASE["atr_mult"],
            },
            confidence=0.6,
        )
