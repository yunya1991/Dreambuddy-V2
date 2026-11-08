"""OkxDerivativesCollector — OKX 衍生品数据采集器。

数据源: OKX 公开 API (https://www.okx.com/api/v5)
  - /public/funding-rate            资金费率（免 Key）
  - /rubik/stat/contracts/long-short-account-ratio  多空比·持仓人数（免 Key）
  - /public/open-interest           持仓量 OI（免 Key）
  - /rubik/stat/taker-volume        主动买卖量（免 Key，可算主动买卖比）

用途: 前端 capital_flow 模块 OKX 口径衍生品数据（与 Binance 口径交叉验证）。
FAIL-OPEN 铁律: 单端点异常跳过，全异常返回空列表不阻塞。
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
import requests
from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)

_API_BASE = "https://www.okx.com/api/v5"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class OkxDerivativesCollector(BaseCollector):
    """OKX 衍生品采集器（资金费率/多空比/OI/主动买卖比，免 Key）。"""

    source = "okx_derivatives"
    category = "chain"

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 OKX 衍生品数据。

        Args:
            params: {"instId": "BTC-USDT-SWAP", "ccy": "BTC"}
        Returns:
            list[DataRecord] — 单条记录，metrics 含四类指标。
        """
        inst_id = params.get("instId", "BTC-USDT-SWAP")
        ccy = params.get("ccy", "BTC")
        metrics: dict = {}

        # 1. 资金费率
        try:
            r = requests.get(
                f"{_API_BASE}/public/funding-rate",
                params={"instId": inst_id},
                timeout=15,
            )
            r.raise_for_status()
            d = r.json().get("data", [{}])[0]
            rate = float(d.get("fundingRate", 0.0))
            # OKX 每 8h 结算一次，年化 = rate * 3 * 365 * 100
            metrics["funding_rate_pct"] = round(rate * 100, 6)
            metrics["funding_rate_annualized_pct"] = round(rate * 3 * 365 * 100, 4)
            metrics["next_funding_rate_pct"] = round(
                float(d.get("nextFundingRate") or 0.0) * 100, 6
            )
        except Exception as e:
            logger.debug("okx funding-rate FAIL-OPEN: %s", e)

        # 2. 多空比（持仓人数比，5m 粒度取最新）
        try:
            r = requests.get(
                f"{_API_BASE}/rubik/stat/contracts/long-short-account-ratio",
                params={"ccy": ccy, "period": "5m"},
                timeout=15,
            )
            r.raise_for_status()
            rows = r.json().get("data", [])
            if rows:
                metrics["long_short_ratio"] = float(rows[0][1])
                metrics["long_account_pct"] = round(
                    float(rows[0][1]) / (1 + float(rows[0][1])) * 100, 2
                )
        except Exception as e:
            logger.debug("okx long-short FAIL-OPEN: %s", e)

        # 3. 持仓量 OI
        try:
            r = requests.get(
                f"{_API_BASE}/public/open-interest",
                params={"instType": "SWAP", "instId": inst_id},
                timeout=15,
            )
            r.raise_for_status()
            d = r.json().get("data", [{}])[0]
            metrics["open_interest_btc"] = round(float(d.get("oiCcy", 0.0)), 2)
            metrics["open_interest_usd"] = round(float(d.get("oiUsd", 0.0)), 2)
        except Exception as e:
            logger.debug("okx open-interest FAIL-OPEN: %s", e)

        # 4. 主动买卖量（5m 粒度取最新，算主动买卖比）
        try:
            r = requests.get(
                f"{_API_BASE}/rubik/stat/taker-volume",
                params={"ccy": ccy, "instType": "CONTRACTS", "period": "5m"},
                timeout=15,
            )
            r.raise_for_status()
            rows = r.json().get("data", [])
            if rows:
                # 行格式: [ts, sellVol, buyVol]（OKX 文档: 第二列卖、第三列买）
                sell_vol = float(rows[0][1])
                buy_vol = float(rows[0][2])
                metrics["taker_buy_vol"] = round(buy_vol, 2)
                metrics["taker_sell_vol"] = round(sell_vol, 2)
                if sell_vol > 0:
                    metrics["taker_buy_sell_ratio"] = round(buy_vol / sell_vol, 4)
        except Exception as e:
            logger.debug("okx taker-volume FAIL-OPEN: %s", e)

        if not metrics:
            return []

        rec = DataRecord(
            source=self.source,
            category=self.category,
            sub_category="okx_derivatives",
            timestamp=_now_iso(),
            metrics=metrics,
            events=[],
            timeseries=[],
            raw={"instId": inst_id, "ccy": ccy, "api": "okx_v5_public"},
        )
        validate_record(rec)
        return [rec]
