"""mempool.space BTC 链上采集器 — 免费 REST API，无需 Key。

端点：
  GET /blocks/tip/height          — 当前区块高度
  GET /mempool                     — Mempool 状态（交易数/总手续费/费率直方图）
  GET /v1/difficulty-adjustment    — 难度调整预估
  GET /blocks                      — 最近区块列表（矿工/手续费/交易数）
  GET /v1/mining/pools/24h         — 矿池 24h 统计

用于战略层"地"维度 BTC 链上基础数据（D9扩展）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://mempool.space/api"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class MempoolCollector(BaseCollector):
    """mempool.space BTC 链上数据采集器。"""

    source = "mempool"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 免费 API 无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        kind = params.get("kind", "overview")
        try:
            if kind == "overview":
                return self._fetch_overview(params)
            if kind == "blocks":
                return self._fetch_blocks(params)
        except Exception:
            return []  # fail-open

    def _get(self, path: str, **kw) -> dict | list:
        resp = requests.get(f"{_BASE}{path}", timeout=15, **kw)
        resp.raise_for_status()
        return resp.json()

    def _fetch_overview(self, params: dict) -> list[DataRecord]:
        # 并行拉取多个端点
        tip_height = self._get("/blocks/tip/height")
        mempool = self._get("/mempool")
        diff_adj = self._get("/v1/difficulty-adjustment")
        pools = self._get("/v1/mining/pools/24h")

        # 提取扁平 metrics
        top_pools = pools[:5] if isinstance(pools, list) else []
        pool_names = ",".join(p.get("name", "") for p in top_pools)
        pool_shares = ",".join(str(p.get("share", 0)) for p in top_pools)

        mempool_data = mempool.get("mempool", {})
        fee_histogram = mempool.get("mempool", {}).get("feeHistogram", [])

        # 难度调整预估
        diff_pct = diff_adj.get("progressPercent", 0) if isinstance(diff_adj, dict) else 0
        est_diff = diff_adj.get("difficultyChange", 0) if isinstance(diff_adj, dict) else 0
        rem_blocks = diff_adj.get("remainingBlocks", 0) if isinstance(diff_adj, dict) else 0

        rec = DataRecord(
            source="mempool",
            category="chain",
            sub_category="btc_onchain",
            timestamp=_now_iso(),
            metrics={
                "tip_height": int(tip_height) if isinstance(tip_height, (int, float)) else 0,
                "mempool_count": int(mempool_data.get("count", 0)),
                "mempool_size_kb": float(mempool_data.get("size", 0)) / 1000.0,
                "mempool_fee_btc": float(mempool_data.get("fee", 0)),
                "difficulty_change_pct": float(est_diff),
                "difficulty_progress_pct": float(diff_pct),
                "remaining_blocks": int(rem_blocks),
                "top_pools": pool_names[:200],
                "top_pools_shares": pool_shares[:200],
            },
            events=[],
            timeseries=[
                {"fee_rate": h.get("fee", 0), "count": h.get("count", 0)}
                for h in fee_histogram[:20]
            ],
            raw={
                "source": "mempool.space",
                "tip_height": tip_height,
                "mempool": mempool,
                "difficulty_adjustment": diff_adj,
            },
        )
        validate_record(rec)
        return [rec]

    def _fetch_blocks(self, params: dict) -> list[DataRecord]:
        limit = params.get("limit", 10)
        blocks = self._get("/blocks", params={"limit": limit})
        if not isinstance(blocks, list):
            return []

        ts = _now_iso()
        recs: list[DataRecord] = []
        for blk in blocks[:limit]:
            rec = DataRecord(
                source="mempool",
                category="chain",
                sub_category="btc_block",
                timestamp=ts,
                metrics={
                    "height": int(blk.get("height", 0)),
                    "tx_count": int(blk.get("tx_count", 0)),
                    "fee_btc": float(blk.get("fee", 0)),
                    "size_kb": float(blk.get("size", 0)) / 1000.0,
                    "pool_name": str(blk.get("extras", {}).get("pool", {}).get("name", "")),
                },
                events=[],
                timeseries=[],
                raw={"block": blk},
            )
            recs.append(rec)
        return recs
