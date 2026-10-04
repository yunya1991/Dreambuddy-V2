"""SemiconductorCycleCollector — 半导体周期数据采集 (T13c 数据源)

为 AiCycleScorer 提供 3 项数据:
  1. sox_change_30d         — SOX(费城半导体指数) 30 天涨幅% (yfinance ^SOX)
  2. semiconductor_capex_yoy — 半导体资本开支同比% (配置驱动)
  3. hbm_demand_index       — HBM 需求指数 0.0-1.0 (配置驱动)

FAIL-OPEN：所有异常被捕获，失败时返回空列表，不阻塞交易热路径。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)

# 默认 SOX 指数 yfinance symbol
_DEFAULT_SOX_SYMBOL = "^SOX"


class SemiconductorCycleCollector(BaseCollector):
    """半导体周期数据采集器。"""

    source = "semiconductor"
    category = "macro"

    SUPPORTED_METRICS = (
        "sox_change_30d",
        "semiconductor_capex_yoy",
        "hbm_demand_index",
    )

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._sox_symbol = (config or {}).get("sox_symbol", _DEFAULT_SOX_SYMBOL)

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """按 params["metric"] 采集，返回 DataRecord 列表。"""
        metric = params.get("metric", "")
        if metric == "sox_change_30d":
            return self._fetch_sox_change()
        elif metric == "semiconductor_capex_yoy":
            return self._fetch_config_value("semiconductor_capex_yoy")
        elif metric == "hbm_demand_index":
            return self._fetch_config_value("hbm_demand_index")
        else:
            logger.debug("[SemiCycle] unknown metric: %s", metric)
            return []

    def fetch_all(self) -> list[DataRecord]:
        """采集所有指标。"""
        recs: list[DataRecord] = []
        recs.extend(self._fetch_sox_change())
        recs.extend(self._fetch_config_value("semiconductor_capex_yoy"))
        recs.extend(self._fetch_config_value("hbm_demand_index"))
        return recs

    def _fetch_sox_change(self) -> list[DataRecord]:
        """从 yfinance 获取 SOX 指数 30 天涨幅%。"""
        try:
            ticker = yf.Ticker(self._sox_symbol)
            hist = ticker.history(period="2mo")
            if hist is None or hist.empty or len(hist) < 2:
                logger.warning("[SemiCycle] SOX history empty")
                return []

            closes = hist["Close"].dropna()
            if len(closes) < 2:
                return []

            latest = float(closes.iloc[-1])
            earliest = float(closes.iloc[0])
            if earliest == 0:
                return []

            change_pct = round((latest - earliest) / earliest * 100.0, 2)
            now_iso = datetime.now(timezone.utc).astimezone().isoformat()

            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category="sox_change_30d",
                timestamp=now_iso,
                metrics={"value": change_pct, "symbol": self._sox_symbol},
                events=[],
                timeseries=[
                    {"date": str(closes.index[0].date()), "close": earliest},
                    {"date": str(closes.index[-1].date()), "close": latest},
                ],
                raw={"symbol": self._sox_symbol, "change_pct": change_pct},
            )
            validate_record(rec)
            return [rec]
        except Exception as e:
            logger.warning("[SemiCycle] SOX fetch FAIL-OPEN: %s", e, exc_info=False)
            return []

    def _fetch_config_value(self, key: str) -> list[DataRecord]:
        """从配置读取 CapEx/HBM 值。支持长短两种 key 别名。"""
        # key 别名：metric 全名 → config 短名
        _aliases = {
            "semiconductor_capex_yoy": ("semiconductor_capex_yoy", "capex_yoy"),
            "hbm_demand_index": ("hbm_demand_index", "hbm_demand_index"),
        }
        try:
            val = None
            for alias in _aliases.get(key, (key,)):
                val = self.config.get(alias)
                if val is not None:
                    break

            if val is None:
                logger.debug("[SemiCycle] %s not in config", key)
                return []

            val_float = float(val)
            now_iso = datetime.now(timezone.utc).astimezone().isoformat()

            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=key,
                timestamp=now_iso,
                metrics={"value": val_float},
                events=[],
                timeseries=[],
                raw={"config_key": key, "value": val_float},
            )
            validate_record(rec)
            return [rec]
        except (TypeError, ValueError) as e:
            logger.warning("[SemiCycle] %s config invalid: %s", key, e)
            return []
        except Exception as e:
            logger.warning("[SemiCycle] %s FAIL-OPEN: %s", key, e, exc_info=False)
            return []
