"""SecRssCollector — SEC 执法行动 / 加密政策事件采集。

SPEC-Phase2 §6.3:
  - 数据源: SEC RSS 三个 feed
    1. sec.gov/enforcement-litigation/administrative-proceedings/rss
    2. sec.gov/enforcement-litigation/litigation-releases/rss
    3. sec.gov/xml/investor/pressreleases
  - direction 关键词匹配: BEARISH→short, BULLISH→long, 否则 neutral
  - crypto_related: 标题含 crypto/bitcoin/token/digital asset 等
  - 三层去重: dc:creator 精确 + 标题 Jaccard>0.7(24h) + 实体名交集(24h)
  - FAIL-OPEN: feed 解析失败返回空列表
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)

# 跨重启去重状态文件（SPEC §6.3: sec_rss_processed）
_DEFAULT_STATE_FILE = Path(__file__).resolve().parents[3] / "data" / "sec_rss_processed.json"
_DEDUP_WINDOW_HOURS = 24


class SecRssCollector(BaseCollector):
    """SEC RSS 执法行动 / 加密政策事件采集器。"""

    source = "sec"
    category = "news"  # DataRecord 契约合法值（"enforcement" 不在 CATEGORIES）

    # SEC RSS 三个 feed
    FEED_URLS = [
        "https://www.sec.gov/enforcement-litigation/administrative-proceedings/rss",
        "https://www.sec.gov/enforcement-litigation/litigation-releases/rss",
        "https://www.sec.gov/xml/investor/pressreleases",
    ]

    # 方向关键词（SPEC §6.3）
    BEARISH_KEYWORDS = [
        "charge", "sue", "fraud", "enforcement", "delist", "ban", "penalty",
    ]
    BULLISH_KEYWORDS = [
        "approve", "exempt", "innovation", "relief", "proposal", "modernize",
    ]
    CRYPTO_KEYWORDS = [
        "crypto", "bitcoin", "ethereum", "token", "digital asset",
        "blockchain", "exchange-traded", "coinbase", "binance",
    ]

    def is_available(self) -> bool:
        """SEC RSS 公开无需 API Key，始终可用。"""
        return True

    @property
    def _state_file(self) -> Path:
        """跨重启去重状态文件路径（可通过 config['state_file'] 覆盖，便于测试）。"""
        path = self.config.get("state_file") if self.config else None
        return Path(path) if path else _DEFAULT_STATE_FILE

    def fetch(self, params: dict) -> list[DataRecord]:
        """
        采集 SEC RSS 事件（发布即推送）。

        Returns:
            DataRecord 列表，失败时返回空列表（FAIL-OPEN）。
        """
        try:
            entries = self._fetch_feeds()
        except Exception as e:
            logger.warning("SecRss feed 采集失败，FAIL-OPEN: %s", e)
            return []

        if not entries:
            return []

        # 解析 + 三层去重（含跨重启已处理项）
        records: list[DataRecord] = []
        seen: list[dict] = self._load_recent_items()  # 跨重启已处理项
        accepted: list[dict] = []
        ts = datetime.now(timezone.utc).astimezone().isoformat()

        for entry in entries:
            title = entry.get("title", "")
            if not title:
                continue

            item = self._normalize_entry(entry)
            if self.is_duplicate(item, seen):
                continue
            seen.append(item)
            accepted.append(item)

            direction = self._compute_direction(title)
            crypto_related = self._is_crypto_related(title)

            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category="sec_deadline",
                timestamp=ts,
                metrics={
                    "event_type": "sec_deadline",
                    "direction": direction,
                    "is_scheduled": False,
                    "crypto_related": crypto_related,
                    "creator": item.get("creator", ""),
                    "pub_date": item.get("pub_date_iso", ""),
                    "title": title,
                },
                events=[{
                    "title": title,
                    "link": entry.get("link", ""),
                    "creator": item.get("creator", ""),
                    "pub_date": item.get("pub_date_iso", ""),
                }],
                timeseries=[],
                raw=dict(entry),
            )
            validate_record(rec)
            records.append(rec)

        # 跨重启持久化已处理项（SPEC §6.3: sec_rss_processed）
        if accepted:
            self._persist_processed(accepted)

        return records

    # ---------------------------------------------------------------- RSS 抓取

    def _fetch_feeds(self) -> list[dict]:
        """抓取 3 个 SEC RSS feed，返回合并的 entries 列表。

        FAIL-OPEN: feedparser 未安装或网络异常时，该 feed 返回空，不影响其他 feed。
        """
        try:
            import feedparser
        except ImportError:
            logger.warning("SecRss: feedparser 未安装，FAIL-OPEN 返回空")
            return []

        all_entries: list[dict] = []
        for url in self.FEED_URLS:
            try:
                parsed = feedparser.parse(url)
                entries = parsed.get("entries", []) if isinstance(parsed, dict) else []
                all_entries.extend(entries)
            except Exception as e:
                logger.debug("SecRss feed %s 解析失败: %s", url, e)
                continue
        return all_entries

    # ---------------------------------------------------------------- 方向判定

    def _compute_direction(self, title: str) -> str:
        """关键词匹配判定 direction。"""
        lower = title.lower()
        score = 0.0
        for kw in self.BEARISH_KEYWORDS:
            if kw in lower:
                score -= 1.0
        for kw in self.BULLISH_KEYWORDS:
            if kw in lower:
                score += 1.0
        if score > 0:
            return "long"
        elif score < 0:
            return "short"
        return "neutral"

    def _is_crypto_related(self, title: str) -> bool:
        """标题是否含加密关键词。"""
        lower = title.lower()
        return any(kw in lower for kw in self.CRYPTO_KEYWORDS)

    # ---------------------------------------------------------------- 三层去重

    def _load_recent_items(self) -> list[dict]:
        """从状态文件加载最近 24h 已处理项（跨重启去重）。

        FAIL-OPEN: 文件不存在或解析失败返回空列表。
        """
        try:
            state_file = self._state_file
            if not state_file.exists():
                return []
            data = json.loads(state_file.read_text(encoding="utf-8"))
            cutoff = datetime.now(timezone.utc) - timedelta(hours=_DEDUP_WINDOW_HOURS)
            items = []
            for it in data:
                pub_raw = it.get("pub_date_iso", "")
                if not pub_raw:
                    continue
                try:
                    pub = datetime.fromisoformat(pub_raw)
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if pub >= cutoff:
                    # 恢复 pub_date datetime 供 is_duplicate 使用
                    items.append({
                        "creator": it.get("creator", ""),
                        "title": it.get("title", ""),
                        "pub_date": pub,
                    })
            return items
        except Exception as e:
            logger.debug("[FO] SecRss _load_recent_items fail: %s", e)
            return []

    def _persist_processed(self, items: list[dict]) -> None:
        """将本次接受的项追加到状态文件，清理超过 24h 的旧项。

        FAIL-OPEN: 写入失败不影响采集结果。
        """
        try:
            state_file = self._state_file
            state_file.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if state_file.exists():
                try:
                    existing = json.loads(state_file.read_text(encoding="utf-8"))
                except Exception:
                    existing = []
            cutoff = datetime.now(timezone.utc) - timedelta(hours=_DEDUP_WINDOW_HOURS)
            # 清理旧项
            kept = []
            for it in existing:
                pub_raw = it.get("pub_date_iso", "")
                if pub_raw:
                    try:
                        pub = datetime.fromisoformat(pub_raw)
                        if pub.tzinfo is None:
                            pub = pub.replace(tzinfo=timezone.utc)
                        if pub < cutoff:
                            continue
                    except Exception:
                        continue
                kept.append(it)
            # 追加新项（序列化 pub_date 为 ISO 字符串）
            for it in items:
                pub = it.get("pub_date")
                kept.append({
                    "creator": it.get("creator", ""),
                    "title": it.get("title", ""),
                    "pub_date_iso": pub.isoformat() if pub else "",
                })
            state_file.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug("[FO] SecRss _persist_processed fail: %s", e)

    @staticmethod
    def _normalize_entry(entry: dict) -> dict:
        """提取去重所需字段（creator/title/pub_date）。"""
        creator = entry.get("dc_creator") or entry.get("author") or ""
        title = entry.get("title", "")
        pub_date = None
        pub_raw = entry.get("published") or entry.get("updated") or ""
        if pub_raw:
            try:
                pub_date = parsedate_to_datetime(pub_raw)
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
            except Exception:
                pub_date = None
        pub_date_iso = pub_date.isoformat() if pub_date else ""
        return {
            "creator": creator,
            "title": title,
            "pub_date": pub_date,
            "pub_date_iso": pub_date_iso,
        }

    def is_duplicate(
        self, new_item: dict, recent_items: list[dict], window_hours: int = 24
    ) -> bool:
        """三层去重判定（SPEC §6.3 M2）。

        1. dc:creator 完全匹配 → 重复
        2. 标题 Jaccard 相似度 > 0.7 且 24h 内 → 重复
        3. 实体名交集 > 0 且 24h 内 → 重复
        任一命中即视为重复。
        """
        if not recent_items:
            return False

        new_creator = new_item.get("creator") or new_item.get("dc_creator") or ""
        new_title = new_item.get("title", "")
        new_pub = new_item.get("pub_date")

        # 第 1 层：dc:creator 精确匹配
        if new_creator:
            for it in recent_items:
                old_creator = it.get("creator") or it.get("dc_creator") or ""
                if old_creator and old_creator == new_creator:
                    return True

        # 第 2、3 层需时间窗口
        if new_pub is None:
            return False

        new_tokens = set(new_title.lower().split())
        new_entities = self._extract_entities(new_title)

        for item in recent_items:
            old_pub = item.get("pub_date")
            if old_pub is None:
                continue
            delta = abs((new_pub - old_pub).total_seconds())
            if delta > window_hours * 3600:
                continue

            # 第 2 层：标题 Jaccard 相似度
            old_tokens = set(item.get("title", "").lower().split())
            if old_tokens:
                jaccard = len(new_tokens & old_tokens) / max(1, len(new_tokens | old_tokens))
                if jaccard > 0.7:
                    return True

            # 第 3 层：实体名交集
            old_entities = self._extract_entities(item.get("title", ""))
            if new_entities & old_entities:
                return True

        return False

    @staticmethod
    def _extract_entities(title: str) -> set[str]:
        """从标题提取实体名（连续大写词 / 全大写缩写）。

        排除 SEC（feed 发行方，出现在几乎所有条目中）及常见大写停用词，
        避免误判为同一实体。

        例: "SEC Charges Binance With Fraud" → {"Binance"}
        """
        # 匹配首字母大写的词（长度 >= 2）
        entities = set(re.findall(r"\b[A-Z][a-zA-Z]{1,}\b", title))
        # 全大写缩写
        entities |= set(re.findall(r"\b[A-Z]{2,}\b", title))
        # 排除发行方与常见停用词（避免误去重）
        entities -= {"SEC", "The", "With", "For", "New", "Its", "From", "Into", "Over"}
        return entities
