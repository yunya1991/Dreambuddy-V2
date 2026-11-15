# -*- coding: utf-8 -*-
"""D-E20 新闻统一出口（SPEC-54-统计图表化能力 L1S-03，P1）。

定位：把 `mm_metrics.social_volume` 的新闻条数 / 社交热度观测，统一成 L1-S 信封
（`capability/intent/answer/data/quality`），供 AGENT 工作台与前端直接消费。

硬边界：
  - **只读、零重算**：只把已入库观测按日对齐输出，不做情绪打分、不做方向判断；
  - **无方向措辞**（ADR-V10）：`answer` 与 `items` 不含看涨/看跌/建议/目标价等词，
    内部用 `scan_forbidden` 自检，命中即抛 `ValueError`（fail-closed）；
  - **不伪造条目**：库里没有新闻**条目表**（只有 24h 计数序列），故只出计数摘要，
    不编造标题/链接/正文；
  - **无观测即降级**：`status=empty` + `ok=false`，answer 说明原因（不补零）。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from .envelope import STATUS_GOOD, STATUS_PARTIAL, build, quality, unavailable

CAPABILITY = "D-E20"
INTENT = "trend_query"
SUB_CATEGORY = "social_volume"
NEWS_METRIC = "news_count_24h"
HEAT_METRIC = "social_volume"
# 方向措辞白名单（ADR-V10）：出现即视为措辞回归
FORBIDDEN_WORDS = (
    "看涨",
    "看跌",
    "建议买入",
    "建议卖出",
    "目标价",
    "多头",
    "空头",
    "推荐",
)
_MIN_OBS = 2
DEFAULT_DAYS = 30

MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def scan_forbidden(text: Any) -> List[str]:
    """返回命中禁用词的列表（空列表 = 通过）。"""
    body = str(text or "")
    return [word for word in FORBIDDEN_WORDS if word in body]


def _db_path(db_path: Optional[str] = None) -> str:
    if db_path:
        return db_path
    env = os.environ.get("DREAMBUDDY_CORE_DB")
    if env:
        return env
    return os.path.normpath(
        os.path.join(MODULE_ROOT, "..", "19-数据访问层", "data", "dreambuddy_core.db")
    )


def _load_series(db_path: str, metric: str, start_ts: int, end_ts: int) -> Dict[str, float]:
    from ..align import AlignError, load_daily

    try:
        return load_daily(db_path, SUB_CATEGORY, metric, start_ts=start_ts, end_ts=end_ts) or {}
    except (AlignError, OSError, sqlite3.Error):
        return {}


def news_digest(
    *,
    db_path: Optional[str] = None,
    as_of: Optional[str] = None,
    days: int = DEFAULT_DAYS,
) -> Dict[str, Any]:
    """新闻 / 社交热度日频摘要（统一信封）。

    `as_of` 给定时严格截断（`day <= as_of`），保证可回放；`items` 按日期降序。
    """
    window = max(int(days), 1)
    end_day = as_of or datetime.now().strftime("%Y-%m-%d")
    try:
        end_dt = datetime.strptime(end_day, "%Y-%m-%d")
    except ValueError:
        return unavailable(
            capability=CAPABILITY,
            intent=INTENT,
            reason=f"as_of 非法日期 {as_of!r}",
            sources=[f"datacenter.{SUB_CATEGORY}"],
        )
    end_ts = int(end_dt.replace(tzinfo=None).timestamp()) + 86400
    start_ts = end_ts - window * 86400

    target = _db_path(db_path)
    if not os.path.isfile(target):
        return unavailable(
            capability=CAPABILITY,
            intent=INTENT,
            reason="核心库不可读（只读副本缺失）",
            sources=[f"datacenter.{SUB_CATEGORY}"],
        )

    news = _load_series(target, NEWS_METRIC, start_ts, end_ts)
    heat = _load_series(target, HEAT_METRIC, start_ts, end_ts)
    dates = sorted(day for day in set(news) | set(heat) if not as_of or day <= as_of)
    if len(dates) < _MIN_OBS:
        return unavailable(
            capability=CAPABILITY,
            intent=INTENT,
            reason=f"{window} 日窗口内有效观测 {len(dates)} < {_MIN_OBS}",
            data={"window_days": window, "as_of": as_of},
            sources=[f"datacenter.{SUB_CATEGORY}"],
        )

    items: List[Dict[str, Any]] = []
    for day in reversed(dates):
        rows: Dict[str, Any] = {"date": day}
        if day in news:
            rows[NEWS_METRIC] = round(float(news[day]), 4)
        if day in heat:
            rows[HEAT_METRIC] = round(float(heat[day]), 4)
        items.append(rows)

    missing_news = sum(1 for row in items if NEWS_METRIC not in row)
    status = STATUS_GOOD if missing_news == 0 else STATUS_PARTIAL
    answer = (
        f"{as_of or end_day} 最近 {len(items)} 个交易日新闻与社交热度观测已就绪"
        f"（新闻条数缺失 {missing_news} 天）。"
        if status == STATUS_GOOD
        else f"{as_of or end_day} 最近 {len(items)} 个交易日中新闻条数缺失 {missing_news} 天，样本不完整，仅作参考。"
    )
    if scan_forbidden(answer):
        raise ValueError(f"新闻出口出现方向措辞: {scan_forbidden(answer)}")

    return build(
        capability=CAPABILITY,
        intent=INTENT,
        answer=answer,
        data={
            "as_of": as_of or end_day,
            "window_days": window,
            "source": f"mm_metrics.{SUB_CATEGORY}",
            "items": items,
            "notes": "仅含日频计数与热度观测；无新闻条目表，不编造标题/正文/链接",
        },
        quality_block=quality(
            status=status,
            sample_n=len(items),
            span=[dates[0], dates[-1]],
            degraded_reason=None if status == STATUS_GOOD else "news_metric_partial",
            sources=[f"datacenter.{SUB_CATEGORY}"],
        ),
    )
