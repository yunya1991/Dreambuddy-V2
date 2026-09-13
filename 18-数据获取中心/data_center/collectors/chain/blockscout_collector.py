"""Blockscout ETH 链上采集器 — 兼容 Etherscan V2 API，免费 tier 无需 Key。

数据源: https://eth.blockscout.com/api
- 开源区块浏览器，免费
- 兼容 Etherscan V2 API 格式
- 支持交易/事件日志/合约 ABI

端点：
  GET /api?module=stats&action=ethsupply          — ETH 总供应量
  GET /api?module=proxy&action=eth_block_number    — 最新区块号
  GET /api?module=stats&action=ethsupplyexchange   — ETH 交易所余额
  GET /api?module=gastracker&action=gasoracle      — Gas 费率

用于 AGI 蓝图 L1 数据层 ETH 链上数据，与 etherscan 互补。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://eth.blockscout.com/api"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class BlockscoutCollector(BaseCollector):
    """Blockscout ETH 链上数据采集器。"""

    source = "blockscout"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 免费 tier 无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        kind = params.get("kind", "overview")
        try:
            if kind == "overview":
                return self._fetch_overview(params)
            if kind == "gas":
                return self._fetch_gas(params)
        except Exception:
            return []  # fail-open

    def _get(self, params: dict) -> dict:
        resp = requests.get(_BASE, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _fetch_overview(self, params: dict) -> list[DataRecord]:
        # 拉取多个端点
        block_num_data = self._get({"module": "proxy", "action": "eth_block_number"})
        supply_data = self._get({"module": "stats", "action": "ethsupply"})

        block_num_hex = block_num_data.get("result", "0x0") if isinstance(block_num_data, dict) else "0x0"
        block_num = int(block_num_hex, 16) if isinstance(block_num_hex, str) and block_num_hex.startswith("0x") else 0

        supply_wei = supply_data.get("result", "0") if isinstance(supply_data, dict) else "0"
        supply_eth = float(int(supply_wei)) / 1e18 if isinstance(supply_wei, str) and supply_wei.isdigit() else 0.0

        rec = DataRecord(
            source="blockscout",
            category="chain",
            sub_category="eth_onchain",
            timestamp=_now_iso(),
            metrics={
                "latest_block": block_num,
                "eth_total_supply": round(supply_eth, 2),
            },
            events=[],
            timeseries=[],
            raw={
                "source": "eth.blockscout.com",
                "block_number": block_num,
                "supply_wei": supply_wei,
            },
        )
        validate_record(rec)
        return [rec]

    def _fetch_gas(self, params: dict) -> list[DataRecord]:
        data = self._get({"module": "gastracker", "action": "gasoracle"})
        result = data.get("result", {}) if isinstance(data, dict) else {}

        rec = DataRecord(
            source="blockscout",
            category="chain",
            sub_category="eth_gas",
            timestamp=_now_iso(),
            metrics={
                "safe_gas_price": float(result.get("SafeGasPrice", 0) or 0),
                "propose_gas_price": float(result.get("ProposeGasPrice", 0) or 0),
                "fast_gas_price": float(result.get("FastGasPrice", 0) or 0),
                "base_fee": float(result.get("suggestBaseFee", 0) or 0),
            },
            events=[],
            timeseries=[],
            raw={"source": "eth.blockscout.com", "gas_oracle": result},
        )
        validate_record(rec)
        return [rec]
