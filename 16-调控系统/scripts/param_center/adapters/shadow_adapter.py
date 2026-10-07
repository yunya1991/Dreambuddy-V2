"""ShadowLogger 适配器 — 历史 effective 值 → 经验参数

依赖: 11-易经推理系统/scripts/memory_l4/bcrm2/shadow_logger.py + storage.py
输出: 从 shadow_param_log 查询最近 N 条 effective 参数的均值
"""
from __future__ import annotations

from typing import Optional

from ..aggregator import AlgoObservation
from .base import BaseAdapter


class ShadowAdapter(BaseAdapter):
    name = "shadow"

    def __init__(self, lookback_days: int = 30) -> None:
        self.lookback_days = lookback_days

    def _observe_impl(
        self,
        symbol: str,
        market_data: Optional[dict] = None,
    ) -> Optional[AlgoObservation]:
        try:
            from memory_l4.bcrm2.storage import Storage
            storage = Storage()
            # 查询最近 N 天 effective 参数均值（接口签名按实际 storage 实现）
            records = storage.query_shadow_log(
                symbol=symbol,
                lookback_days=self.lookback_days,
            )
            if not records:
                return None
            # 取 effective 字段均值
            sls = [r.get("effective_sl", 0.05) for r in records]
            tps = [r.get("effective_tp", 0.15) for r in records]
            return AlgoObservation(
                algo_name=self.name,
                params={
                    "sl_floor": max(0.04, sum(sls) / len(sls)),
                    "tp_floor": max(0.12, sum(tps) / len(tps)),
                    "atr_mult": 4.5,
                },
                confidence=0.7,  # 历史经验置信度
            )
        except Exception:
            return None
