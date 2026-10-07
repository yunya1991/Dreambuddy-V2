"""ParameterMapper 适配器 — 6维参数 [lo, hi] → SL/TP/ATR 建议

依赖: 11-易经推理系统/scripts/memory_l4/bcrm2/parameter_mapper.py
真实签名: ParameterMapper().map_global_parameters(L, T, C, ...) -> Dict[str, Tuple[lo, hi]]
  输出 6 个 key（不含 sl_floor/tp_floor/atr_mult 直接对应项）:
    - global_position_mult  ∈ [0.30, 1.60]
    - ls_ratio_cap           ∈ [0.20, 1.00]
    - long_bias              ∈ [-0.30, 0.30]
    - short_bias             ∈ [-0.30, 0.30]
    - long_threshold_mult    ∈ [0.70, 1.50]   # 多头开仓阈值乘数
    - short_threshold_mult   ∈ [0.70, 1.50]   # 空头开仓阈值乘数

映射规则:
  - long_threshold_mult ↑ (>1) → 多头谨慎 → SL 稍宽 → sl_floor ↑
  - long_threshold_mult ↓ (<1) → 多头激进 → SL 紧 → sl_floor ↓
  - short_threshold_mult ↑ → 空头谨慎 → TP 稍宽 → tp_floor ↑
  - short_threshold_mult ↓ → 空头激进 → TP 紧 → tp_floor ↓
  - position_mult ↓ → 风险偏好低 → atr_mult ↓（更保守的 ATR 倍数）

输入 market_data 可选: L/T/C 三个 key (默认 0/0/0 = identity)
"""
from __future__ import annotations

from typing import Optional

from ..aggregator import AlgoObservation
from .base import BaseAdapter


class PmapperAdapter(BaseAdapter):
    name = "pmapper"

    def _observe_impl(
        self,
        symbol: str,
        market_data: Optional[dict] = None,
    ) -> Optional[AlgoObservation]:
        # 从 market_data 取 L/T/C，默认 0/0/0 = identity
        L = float((market_data or {}).get("L", 0.0))
        T = float((market_data or {}).get("T", 0.0))
        C = float((market_data or {}).get("C", 0.0))

        try:
            from memory_l4.bcrm2.parameter_mapper import ParameterMapper  # type: ignore
            mapper = ParameterMapper()
            ranges = mapper.map_global_parameters(L=L, T=T, C=C)
        except Exception:
            return None

        if not isinstance(ranges, dict) or not ranges:
            return None

        # 取每个参数的中点
        def _mid(key: str, default: float) -> float:
            v = ranges.get(key)
            if isinstance(v, (list, tuple)) and len(v) == 2:
                return (float(v[0]) + float(v[1])) / 2.0
            if isinstance(v, (int, float)):
                return float(v)
            return default

        long_thr = _mid("long_threshold_mult", 1.0)
        short_thr = _mid("short_threshold_mult", 1.0)
        pos_mult = _mid("global_position_mult", 1.0)

        # threshold_mult ∈ [0.70, 1.50] → sl_floor ∈ [0.04, 0.07]
        # 公式: sl_floor = 0.04 + (long_thr - 0.70) * 0.0375
        sl_floor = max(0.04, 0.04 + (long_thr - 0.70) * 0.0375)
        # threshold_mult ∈ [0.70, 1.50] → tp_floor ∈ [0.12, 0.18]
        tp_floor = max(0.12, 0.12 + (short_thr - 0.70) * 0.075)
        # position_mult ∈ [0.30, 1.60] → atr_mult ∈ [3.0, 5.0]
        # 仓位系数越低 → 越保守 → ATR 倍数越低
        atr_mult = max(2.5, min(6.0, 3.0 + pos_mult * 1.5))

        return AlgoObservation(
            algo_name=self.name,
            params={
                "sl_floor": sl_floor,
                "tp_floor": tp_floor,
                "atr_mult": atr_mult,
            },
            confidence=0.65,
        )
