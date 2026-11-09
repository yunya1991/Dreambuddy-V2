"""Odaily 星球日报深度文章 Collector — news 域长文数据源。

与 odaily_newsflash 互补：
  - newsflash：/newsflash/page 短消息流（几十字快讯）
  - post：    /post/page 长文（标题+摘要+tags+深度板块标识）

上游 API（实测 2026-11-09）：
  GET https://web-api.odaily.news/post/page?page=1&limit=20
    - 无鉴权 / 无反爬（与 newsflash 同域名 web-api.odaily.news）
    - 翻页参数为 page=N（1-based），cursor/pageNum/pn 等均被忽略
    - 列表字段固定 12 个：id/title/cover/summary/isTop/isHot/publishTimestamp/
                         tags[{id,name}]/depthPlateId/viewpoint/isCollection/isLike
    - 列表不含 content 正文；正文需二次爬 https://www.odaily.news/post/{id} HTML（本采集器暂不实现）
    - depthPlateId 为深度板块标识（None/0=非深度，>=1 为深度栏目）

契约（12 个扁平 metrics，全部 number/string，前缀 odp_ 与 newsflash 区分）：
  odp_source_id            int    文章 id
  odp_policy_sentiment_0_1 float  情绪分（lazy sentiment_engine，FAIL-OPEN 0.5）
  odp_event_type           str    9 类事件（复用 newsflash 分类器）
  odp_attention_type       str    5 类注意力方向
  odp_is_important         str    "true"/"false"（isTop or isHot 推导）
  odp_is_depth             str    "true"/"false"（depthPlateId 非空且 >0）
  odp_decay_hl_hrs         int    半衰期小时（复用 newsflash _DECAY_HRS）
  odp_title_hash           str    title md5[:8]
  odp_tickers_hit_csl      str    逗号分隔 TICKER（复用 newsflash 提取器）
  odp_depth_plate_id       int    深度板块 id（None → -1）
  odp_tags_csl             str    tags.name 逗号拼接
  odp_summary_hash         str    summary md5[:8]

fetch 参数：
  route       "latest"（默认，page=1）
  page        int   指定页码（默认 1）
  limit       int   每页条数（默认 20，最大 100）
  last_id     int   本地增量过滤：仅保留 id > last_id
  depth_only  bool  True 时仅保留 is_depth="true" 的记录

FAIL-OPEN：
  L1 网络/解析异常 → []
  L2 sentiment_engine 导入失败 → sentiment=0.5
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from data_center.collectors._base import BaseCollector

# 复用 newsflash 的常量与工具函数（DRY，避免双份维护）
from data_center.collectors.news.odaily_newsflash import (
    _ATTENTION_TYPE_ENUM,
    _DECAY_HRS,
    _attention_type,
    _classify_event_type,
    _extract_tickers_from_title,
    _md5_8,
    _now_iso,
    _sentiment_lazy,
)
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger("data_center.collectors.news.odaily_post")

_ODAILY_POST_API = "https://web-api.odaily.news/post/page"
_HTTP_HEADERS = {"locale": "zh-CN", "User-Agent": "DreamBuddy-DC/1.0"}
_HTTP_TIMEOUT = 10
_MAX_LIMIT = 100


class OdailyPostCollector(BaseCollector):
    """Odaily 星球日报深度文章采集器（news / odaily_post）。"""

    source = "odaily_post"
    category = "news"

    def is_available(self) -> bool:
        return True  # web-api 公开，无 key

    def fetch(self, params: dict) -> list[DataRecord]:
        params = params or {}
        try:
            page = int(params.get("page", 1) or 1)
            limit = min(_MAX_LIMIT, max(1, int(params.get("limit", 20) or 20)))
            last_id = params.get("last_id")
            depth_only = bool(params.get("depth_only", False))

            recs = self._fetch_page(page=page, limit=limit)

            # 本地增量过滤
            if last_id is not None:
                try:
                    lid = int(last_id)
                    recs = [r for r in recs if int(r.metrics.get("odp_source_id", 0)) > lid]
                except (TypeError, ValueError):
                    pass  # last_id 非法 → 不过滤（FAIL-OPEN）

            # 深度文章过滤
            if depth_only:
                recs = [r for r in recs if r.metrics.get("odp_is_depth") == "true"]

            return recs
        except Exception as e:  # noqa: BLE003  FAIL-OPEN L1 硬约束
            logger.warning(
                "[FAIL-OPEN L1] OdailyPost fetch 异常 %s: %s，静默回退 []",
                type(e).__name__,
                str(e)[:200],
                stack_info=True,
            )
            return []

    def _fetch_page(self, page: int, limit: int) -> list[DataRecord]:
        resp = requests.get(
            _ODAILY_POST_API,
            params={"page": int(page), "limit": int(limit)},
            headers=_HTTP_HEADERS,
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 429:
            from data_center.core.errors import RateLimitError

            raise RateLimitError("Odaily post 429 rate limited")
        try:
            data = resp.json()
        except ValueError:
            logger.warning("[FAIL-OPEN] Odaily post JSON 解析失败，返回空")
            return []
        if not isinstance(data, dict):
            return []
        items: list[dict[str, Any]] = (data.get("data") or {}).get("list") or []
        if not isinstance(items, list):
            return []

        ts = _now_iso()
        recs: list[DataRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            rec = self._item_to_record(item, ts)
            if rec is not None:
                recs.append(rec)
        return recs

    def _item_to_record(self, item: dict, ts: str) -> DataRecord | None:
        """单条 item → DataRecord。单条异常 → None 跳过（不阻塞其他）。"""
        try:
            od_id = item.get("id")
            try:
                od_id = int(od_id) if od_id is not None else 0
            except (TypeError, ValueError):
                od_id = 0

            title = str(item.get("title", "") or "")
            summary = str(item.get("summary", "") or "")
            is_top = bool(item.get("isTop", False))
            is_hot = bool(item.get("isHot", False))
            is_important = is_top or is_hot  # 置顶或热门 → 重要

            publish_ms = item.get("publishTimestamp")
            try:
                publish_ms = int(publish_ms) if publish_ms is not None else 0
            except (TypeError, ValueError):
                publish_ms = 0

            # 深度板块 id
            depth_plate = item.get("depthPlateId")
            try:
                depth_plate_id = int(depth_plate) if depth_plate is not None else -1
            except (TypeError, ValueError):
                depth_plate_id = -1
            is_depth = depth_plate_id > 0

            # tags → csl
            tags_raw = item.get("tags") or []
            tag_names: list[str] = []
            if isinstance(tags_raw, list):
                for t in tags_raw:
                    if isinstance(t, dict):
                        n = t.get("name")
                        if n:
                            tag_names.append(str(n))
                    elif isinstance(t, str) and t:
                        tag_names.append(t)
            tags_csl = ",".join(tag_names)

            # 情绪（lazy sentiment_engine，FAIL-OPEN 0.5）
            s_float, _ = _sentiment_lazy(title, summary)

            # 事件分类（复用 newsflash 9 类管道）
            et = _classify_event_type(title, summary)

            # ticker 提取（复用 newsflash 提取器）
            ticks = _extract_tickers_from_title(title, summary)
            ticks_csl = ",".join(ticks) if ticks else ""

            # 注意力方向
            att = _attention_type(et, title)
            if att not in _ATTENTION_TYPE_ENUM:
                att = "neutral"

            # 半衰期
            decay = _DECAY_HRS.get(et, 24)

            rec = DataRecord(
                source="odaily_post",
                category="news",
                sub_category=f"post_{od_id}",
                timestamp=ts,
                metrics={
                    "odp_source_id": int(od_id),
                    "odp_policy_sentiment_0_1": float(s_float),
                    "odp_event_type": str(et),
                    "odp_attention_type": str(att),
                    "odp_is_important": "true" if is_important else "false",
                    "odp_is_depth": "true" if is_depth else "false",
                    "odp_decay_hl_hrs": int(decay),
                    "odp_title_hash": _md5_8(title),
                    "odp_tickers_hit_csl": ticks_csl,
                    "odp_depth_plate_id": int(depth_plate_id),
                    "odp_tags_csl": tags_csl,
                    "odp_summary_hash": _md5_8(summary),
                },
                events=[
                    {
                        "event_type": et,
                        "importance": 2 if is_important else 1,
                        "published_ms": int(publish_ms),
                    }
                ],
                timeseries=[],
                raw={
                    "id": od_id,
                    "title": title,
                    "summary": summary,
                    "cover": item.get("cover", ""),
                    "isTop": is_top,
                    "isHot": is_hot,
                    "publishTimestamp": publish_ms,
                    "tags": tags_raw,
                    "depthPlateId": item.get("depthPlateId"),
                    "viewpoint": item.get("viewpoint"),
                    "isCollection": bool(item.get("isCollection", False)),
                    "tickers_hit": ticks,
                    # 正文入口：下游如需全文可二次爬此 URL
                    "post_url": f"https://www.odaily.news/post/{od_id}" if od_id else "",
                },
            )
            validate_record(rec)
            return rec
        except Exception as e:  # noqa: BLE003  单条 FAIL-OPEN
            logger.info(
                "[FAIL-OPEN] OdailyPost item 转换失败 %s: %s，跳过",
                type(e).__name__,
                str(e)[:120],
            )
            return None
