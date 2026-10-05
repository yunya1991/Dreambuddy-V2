"""SocialVolumeCollector — 社交声量采集器。

数据源: 本地 DB 新闻采集器记录计数（cryptopanic/gdelt/rsshub/tavily/odaily 等）

由于免费 API 不直接提供社交声量（CryptoQuant/Santiment 需 key），
采用新闻计数派生法:
  - 统计最近 24h 内各新闻源写入的 records 数量
  - 乘以放大系数（100）映射到 social_volume 量级（5000-90000）

产出: social_volume + news_count_24h + total_news_records

FAIL-OPEN 铁律: DB 异常 → 返回空列表不阻塞。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DB_PATH = _REPO_ROOT / "data_center.db"

_NEWS_SOURCES = ("cryptopanic", "gdelt", "rsshub", "tavily", "odaily_newsflash",
                 "feedparser", "theblockbeats_dataview", "cointelegraph_cn")
_VOLUME_MULTIPLIER = 100  # 新闻数 → social_volume 放大系数


class SocialVolumeCollector(BaseCollector):
    """社交声量采集器（18 新闻记录计数派生）。"""

    source = "news_aggregator"
    category = "chain"

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集社交声量。

        Args:
            params: {}

        Returns:
            list[DataRecord] — 含 social_volume / news_count_24h / total_news_records。
        """
        try:
            news_count_24h, total_news = self._count_news()
            social_volume = news_count_24h * _VOLUME_MULTIPLIER
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category="social_volume",
                timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
                metrics={
                    "social_volume": social_volume,
                    "news_count_24h": news_count_24h,
                    "total_news_records": total_news,
                },
                events=[],
                timeseries=[],
                raw={
                    "source": "18-news-collectors",
                    "method": "news_count_derived",
                    "multiplier": _VOLUME_MULTIPLIER,
                },
            )
            validate_record(rec)
            return [rec]
        except Exception as e:
            logger.debug("SocialVolumeCollector FAIL-OPEN: %s", e)
            return []

    @staticmethod
    def _count_news() -> tuple[int, int]:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            placeholders = ",".join("?" for _ in _NEWS_SOURCES)
            row = conn.execute(
                f"SELECT COUNT(*) FROM records WHERE source IN ({placeholders}) "
                f"AND timestamp >= datetime('now', '-1 day')",
                _NEWS_SOURCES,
            ).fetchone()
            news_count_24h = row[0] if row else 0

            row2 = conn.execute(
                f"SELECT COUNT(*) FROM records WHERE source IN ({placeholders})",
                _NEWS_SOURCES,
            ).fetchone()
            total_news = row2[0] if row2 else 0
            return news_count_24h, total_news
        finally:
            conn.close()
