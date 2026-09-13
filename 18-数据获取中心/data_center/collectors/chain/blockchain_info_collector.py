"""Blockchain.com BTC 链上基础数据采集器 — 免费 REST API，无需 Key。

数据源: https://blockchain.info/q
- BTC 地址数/交易数/难度/哈希率
- 与 mempool.space 互补
- 完全免费无限制

端点：
  GET /q/totalbc — BTC 总流通量
  GET /q/difficulty — 当前难度
  GET /q/hashrate — 当前哈希率
  GET /q/24hrtransactioncount — 24h 交易数
  GET /q/activeaddresses — 活跃地址数
  GET /q/marketcap — BTC 市值
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://blockchain.info/q"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class BlockchainInfoCollector(BaseCollector):
    """Blockchain.com BTC 链上基础数据采集器。"""

    source = "blockchain_info"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 免费 API 无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        # 各端点独立拉取，单个失败不影响其他
        total_bc = self._safe_get("/totalbc")
        tx_count_24h = self._safe_get("/24hrtransactioncount")
        mcap = self._safe_get("/marketcap")
        difficulty = self._safe_get("/q/difficulty") or 0
        hashrate = self._safe_get("/q/hashrate") or 0

        if total_bc is None and tx_count_24h is None and mcap is None:
            return []  # fail-open

        # 转换 BTC 单位（totalbc 返回 satoshis）
        total_btc = float(total_bc) / 1e8 if isinstance(total_bc, (int, float, str)) and str(total_bc).replace(".", "").isdigit() else 0
        diff_val = float(difficulty) if isinstance(difficulty, (int, float, str)) and str(difficulty).replace(".", "").isdigit() else 0
        hr_val = float(hashrate) if isinstance(hashrate, (int, float, str)) and str(hashrate).replace(".", "").replace("e", "").replace("+", "").isdigit() else 0
        tx_val = int(tx_count_24h) if isinstance(tx_count_24h, (int, float, str)) and str(tx_count_24h).isdigit() else 0
        mcap_val = float(mcap) if isinstance(mcap, (int, float, str)) and str(mcap).replace(".", "").isdigit() else 0

        rec = DataRecord(
            source="blockchain_info",
            category="chain",
            sub_category="btc_basics",
            timestamp=_now_iso(),
            metrics={
                "total_btc": round(total_btc, 2),
                "difficulty": diff_val,
                "hashrate": hr_val,
                "tx_count_24h": tx_val,
                "market_cap_usd": mcap_val,
            },
            events=[],
            timeseries=[],
            raw={"source": "blockchain.info"},
        )
        validate_record(rec)
        return [rec]

    @staticmethod
    def _safe_get(path: str):
        """安全 GET，单个端点失败返回 None 不影响其他。"""
        try:
            return BlockchainInfoCollector._get(path)
        except Exception:
            return None

    @staticmethod
    def _get(path: str):
        resp = requests.get(f"{_BASE}{path}", timeout=15)
        resp.raise_for_status()
        # blockchain.info /q 返回纯文本或数字
        text = resp.text.strip()
        try:
            return float(text)
        except ValueError:
            return text
