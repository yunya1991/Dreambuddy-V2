"""P1 T6: 算法观察适配器基类

每个适配器包装一个算法，统一输出 AlgoObservation。
具体适配器（hmm/bagua/hurst/pmapper/shadow/cusum）继承 BaseAdapter。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from ..aggregator import AlgoObservation

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """算法观察适配器基类。

    子类必须实现 observe()，返回 AlgoObservation。
    FAIL-OPEN：observe() 异常时返回 None（聚合器自动跳过）。
    """

    name: str = "base"

    @abstractmethod
    def _observe_impl(
        self,
        symbol: str,
        market_data: Optional[dict] = None,
    ) -> Optional[AlgoObservation]:
        """子类实现：从算法获取观察，返回 AlgoObservation 或 None"""
        raise NotImplementedError

    def observe(
        self,
        symbol: str,
        market_data: Optional[dict] = None,
    ) -> Optional[AlgoObservation]:
        """对外接口：调用算法获取观察，异常时返回 None"""
        try:
            return self._observe_impl(symbol, market_data)
        except Exception as exc:
            logger.warning(
                "Adapter[%s] FAIL-OPEN: observe 异常 symbol=%s err=%s",
                self.name, symbol, exc,
            )
            return None
