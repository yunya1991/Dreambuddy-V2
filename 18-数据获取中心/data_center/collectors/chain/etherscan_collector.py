"""Etherscan collector — 迁移自 flow_collector 链上段。

etherscan-python 薄封装，覆盖 gas/balance/whales 三种 kind + 巨鲸地址表 + 无 Key 降级。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from etherscan import Etherscan

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

# 巨鲸地址表 — 对齐 flow_collector WHALE_ADDRESSES_V1 的三个交易所热钱包
WHALE_ADDRESSES: dict[str, str] = {
    "binance_hot": "0x28C6c06298d514Db089934071355E5743bf21d60",
    "coinbase_hot": "0x5754284f345afc66a98fbBfe0a4602a9039518ca",
    "kraken_hot": "0x2910543Af39abA0Cd09dBb2D50200b3E800A63D2",
}

_WEI_PER_ETHER = 10**18


def _wei_to_ether(wei_str: str) -> float:
    """wei 字符串 -> ether 浮点。"""
    return int(wei_str) / _WEI_PER_ETHER


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class EtherscanCollector(BaseCollector):
    """Etherscan 链上数据采集器（gas / balance / whales）。"""

    source = "etherscan"
    category = "chain"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._api_key: str = (
            self.config.get("api_key")
            or os.environ.get("ETHERSCAN_API_KEY", "")
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _client(self) -> Etherscan:
        return Etherscan(api_key=self._api_key)

    def fetch(self, params: dict) -> list[DataRecord]:
        if not self.is_available():
            return []

        kind = params.get("kind", "gas")
        es = self._client()

        if kind == "gas":
            return self._fetch_gas(es)
        if kind == "balance":
            return self._fetch_balance(es, params["address"])
        if kind == "whales":
            return self._fetch_whales(es)
        return []  # 未知 kind，静默返回空

    def _fetch_gas(self, es: Etherscan) -> list[DataRecord]:
        oracle = es.get_gas_oracle()
        rec = DataRecord(
            source="etherscan",
            category="chain",
            sub_category="gas",
            timestamp=_now_iso(),
            metrics={
                "safe_gas": float(oracle.get("SafeGasPrice") or 0),
                "propose_gas": float(oracle.get("ProposeGasPrice") or 0),
                "fast_gas": float(oracle.get("FastGasPrice") or 0),
            },
            events=[],
            timeseries=[],
            raw=oracle,
        )
        validate_record(rec)
        return [rec]

    def _fetch_balance(self, es: Etherscan, address: str) -> list[DataRecord]:
        wei = es.get_eth_balance(address=address)
        rec = DataRecord(
            source="etherscan",
            category="chain",
            sub_category="balance",
            timestamp=_now_iso(),
            metrics={
                "address": address,
                "balance_ether": _wei_to_ether(wei),
            },
            events=[],
            timeseries=[],
            raw={"address": address, "balance_wei": wei},
        )
        validate_record(rec)
        return [rec]

    def _fetch_whales(self, es: Etherscan) -> list[DataRecord]:
        recs: list[DataRecord] = []
        ts = _now_iso()
        for label, address in WHALE_ADDRESSES.items():
            wei = es.get_eth_balance(address=address)
            rec = DataRecord(
                source="etherscan",
                category="chain",
                sub_category="whale_balance",
                timestamp=ts,
                metrics={
                    "label": label,
                    "address": address,
                    "balance_ether": _wei_to_ether(wei),
                },
                events=[],
                timeseries=[],
                raw={"label": label, "address": address, "balance_wei": wei},
            )
            validate_record(rec)
            recs.append(rec)
        return recs
