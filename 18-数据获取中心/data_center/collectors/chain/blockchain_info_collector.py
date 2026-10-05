"""Blockchain.com BTC 链上基础数据采集器 — 免费 REST API，无需 Key。

数据源:
  - https://blockchain.info/q          — 实时单值端点（totalbc / 24hrtransactioncount / marketcap / hashrate）
  - https://api.blockchain.info/charts — 图表数据（n-unique-addresses 活跃地址 / n-transactions / difficulty）

修复记录（2026-10-05）：
  1. tx_count_24h=0 根因：_get 返回 float，str(float).isdigit() 因小数点返回 False → 改用 _to_number() 安全转换
  2. difficulty 路径错误：/q/difficulty 实际请求 /q/q/difficulty → 404 → 修正为 /difficulty，并增加 charts API 兜底
  3. 新增 active_addresses：blockchain.info /q/activeaddresses 已 404 → 改用 charts/n-unique-addresses
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://blockchain.info/q"
_CHARTS = "https://api.blockchain.info/charts"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _to_number(v, *, as_int: bool = False):
    """安全数值转换：兼容 int/float/str/scientific notation，失败返回 0。"""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v) if as_int else float(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            f = float(s)
            return int(f) if as_int else f
        except ValueError:
            return 0
    return 0


class BlockchainInfoCollector(BaseCollector):
    """Blockchain.com BTC 链上基础数据采集器。"""

    source = "blockchain_info"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 免费 API 无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        # 实时单值端点
        total_bc = self._safe_get("/totalbc")
        tx_count_q = self._safe_get("/24hrtransactioncount")
        mcap = self._safe_get("/marketcap")
        difficulty_q = self._safe_get("/difficulty")  # 修正：原 /q/difficulty 导致 404
        hashrate = self._safe_get("/hashrate")

        # charts API：活跃地址（/q/activeaddresses 已 404）+ 日交易数 + 难度兜底 + 链上交易量
        active_addr = self._safe_chart("n-unique-addresses")
        tx_count_chart = self._safe_chart("n-transactions")
        difficulty_chart = self._safe_chart("difficulty")
        output_volume_btc = self._safe_chart("output-volume")  # 每日链上 BTC 转账总量

        if total_bc is None and tx_count_q is None and mcap is None and active_addr is None:
            return []  # fail-open

        total_btc = _to_number(total_bc) / 1e8  # satoshis → BTC
        diff_val = _to_number(difficulty_chart or difficulty_q)
        hr_val = _to_number(hashrate)
        # 交易数：优先 charts n-transactions（日粒度更准），回退 /q/24hrtransactioncount
        tx_val = int(_to_number(tx_count_chart or tx_count_q))
        mcap_val = _to_number(mcap)
        active_addr_val = int(_to_number(active_addr))
        output_vol_val = _to_number(output_volume_btc)

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
                "active_addresses": active_addr_val,
                "output_volume_btc": output_vol_val,
            },
            events=[],
            timeseries=[],
            raw={"source": "blockchain.info"},
        )
        validate_record(rec)
        return [rec]

    @staticmethod
    def _safe_get(path: str):
        """安全 GET /q 端点，单个失败返回 None 不影响其他。"""
        try:
            return BlockchainInfoCollector._get(path)
        except Exception:
            return None

    @staticmethod
    def _get(path: str):
        resp = requests.get(f"{_BASE}{path}", timeout=15)
        resp.raise_for_status()
        text = resp.text.strip()
        try:
            return float(text)
        except ValueError:
            return text

    @staticmethod
    def _safe_chart(chart_name: str):
        """从 charts API 获取最新值，失败返回 None。"""
        try:
            resp = requests.get(
                f"{_CHARTS}/{chart_name}",
                params={"timespan": "1days", "format": "json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            values = data.get("values", [])
            if values:
                return values[-1].get("y")
        except Exception:
            pass
        return None
