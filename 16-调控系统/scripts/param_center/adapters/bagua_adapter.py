"""8-state Bagua 适配器 — RegimeParams 直接映射

依赖: 11-易经推理系统/scripts/memory_l4/bcrm2/market_regime.py
输出: RegimeParams(tp_atr, sl_atr, long_conf_threshold, short_conf_threshold) → 参数建议

真实 RegimeParams 字段（见 market_regime.py L44-68）:
  - tp_atr:           止盈 ATR 倍数 (1.2 ~ 5.0)
  - sl_atr:           止损 ATR 倍数 (1.5 ~ 3.0)
  - long_conf_threshold:  多头置信度阈值 (0.30 ~ 0.60)
  - short_conf_threshold: 空头置信度阈值 (0.30 ~ 0.65)

转换逻辑:
  - atr_mult = sl_atr (ATR 倍数直接用)
  - sl_floor = max(0.04, sl_atr * 0.025)  # sl_atr=2 → 5%, sl_atr=3 → 7.5%
  - tp_floor = max(0.12, tp_atr * 0.04)  # tp_atr=3 → 12%, tp_atr=5 → 20%
  - confidence = mean(long_conf_threshold, short_conf_threshold)
"""
from __future__ import annotations

from typing import Optional

from ..aggregator import AlgoObservation
from .base import BaseAdapter


class BaguaAdapter(BaseAdapter):
    name = "bagua"

    def _observe_impl(
        self,
        symbol: str,
        market_data: Optional[dict] = None,
    ) -> Optional[AlgoObservation]:
        if not market_data or "regime_name" not in market_data:
            return None

        regime_name = market_data["regime_name"]
        # market_regime.py 中 get_regime_params 是 MarketRegimeClassifier 的方法，
        # 直接访问 DEFAULT_REGIME_PARAMS dict 更简单可靠
        try:
            from memory_l4.bcrm2.market_regime import DEFAULT_REGIME_PARAMS  # type: ignore
            rp = DEFAULT_REGIME_PARAMS.get(
                regime_name, DEFAULT_REGIME_PARAMS["CONSOLIDATION"],
            )
        except Exception:
            return None

        # 真实字段名（market_regime.py L44-68）
        sl_atr = float(getattr(rp, "sl_atr", 2.0))
        tp_atr = float(getattr(rp, "tp_atr", 3.0))
        long_thr = float(getattr(rp, "long_conf_threshold", 0.40))
        short_thr = float(getattr(rp, "short_conf_threshold", 0.40))

        # 转换到 AlgoObservation 参数空间
        # sl_atr ∈ [1.2, 3.0] → sl_floor ∈ [0.03, 0.075]
        # tp_atr ∈ [2.0, 5.0] → tp_floor ∈ [0.12, 0.20]
        sl_floor = max(0.03, sl_atr * 0.025)
        tp_floor = max(0.12, tp_atr * 0.04)

        # 置信度：多空阈值的均值取反（阈值越低 → 越激进 → 置信度越高）
        confidence = max(0.3, min(0.95, 1.0 - (long_thr + short_thr) / 2.0))

        return AlgoObservation(
            algo_name=self.name,
            params={
                "sl_floor": sl_floor,
                "tp_floor": tp_floor,
                "atr_mult": sl_atr,  # 直接用 sl_atr 作为 ATR 倍数
            },
            confidence=confidence,
        )
