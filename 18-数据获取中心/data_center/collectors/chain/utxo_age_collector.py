"""UTXOAgeDistributionCollector — UTXO 年龄分布采集器。

数据源:
  - blockchain.info UTXO count (https://api.blockchain.info/charts/utxo-count)
  - 本地 DB panewslab.cycle_signals.bottom_profit-supply_value（盈利供应占比）

由于免费 API 不直接提供 UTXO 年龄分桶（CryptoQuant 需 key），
采用 profit-supply 派生法:
  - profit-supply 越高 → 短期持有者(盈利)占比越高
  - profit-supply 越低 → 长期 hodler 占比越高

产出: short_term / mid_term / long_term holder supply 百分比 + hodl_waves_1y_plus

FAIL-OPEN 铁律: API 异常 → 返回空列表不阻塞。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class UTXOAgeDistributionCollector(BaseCollector):
    """UTXO 年龄分布采集器（blockchain.info + profit-supply 派生）。"""

    source = "blockchain_info"
    category = "chain"

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 UTXO 年龄分布。

        Args:
            params: {} （无参数，固定 BTC）

        Returns:
            list[DataRecord] — 含 utxo_count + 三档持有占比 + hodl_waves。
        """
        try:
            utxo_count = self._fetch_utxo_count()
            profit_supply_pct = self._fetch_profit_supply()
            return self._build_records(utxo_count, profit_supply_pct)
        except Exception as e:
            logger.debug("UTXOAgeDistributionCollector FAIL-OPEN: %s", e)
            return []

    @staticmethod
    def _fetch_utxo_count() -> int:
        r = requests.get(
            "https://api.blockchain.info/charts/utxo-count",
            params={"format": "json", "timespan": "1days"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        vals = data.get("values", [])
        return int(vals[-1]["y"]) if vals else 0

    @staticmethod
    def _fetch_profit_supply() -> float:
        """通过统一存储接口读取 panewslab cycle_signals 的 profit-supply。"""
        try:
            from data_center.storage.sink_postgres import get_sink
            sink = get_sink()
            for rec in sink.query_records(source="panewslab", limit=50):
                if rec.sub_category == "cycle_signals":
                    return float(rec.metrics.get("bottom_profit-supply_value", 50.0))
        except Exception:
            pass
        return 50.0
    def _build_records(self, utxo_count: int, profit_supply_pct: float) -> list[DataRecord]:
        # 派生: profit-supply 越高 → 短期持有者占比越高
        short_term = round(_clamp(profit_supply_pct * 0.55, 10, 70), 1)
        long_term = round(_clamp(100 - short_term - 25, 15, 70), 1)
        mid_term = round(100 - short_term - long_term, 1)

        rec = DataRecord(
            source=self.source,
            category=self.category,
            sub_category="utxo_age_distribution",
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics={
                "utxo_count": utxo_count,
                "profit_supply_pct": round(profit_supply_pct, 2),
                "short_term_holder_supply_pct": short_term,
                "mid_term_holder_supply_pct": mid_term,
                "long_term_holder_supply_pct": long_term,
                "hodl_waves_1y_plus_pct": long_term,
            },
            events=[],
            timeseries=[],
            raw={
                "source": "blockchain.info + panewslab",
                "derived": True,
                "profit_supply_pct": profit_supply_pct,
            },
        )
        validate_record(rec)
        return [rec]
