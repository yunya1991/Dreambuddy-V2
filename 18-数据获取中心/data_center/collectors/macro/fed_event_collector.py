"""FedEventCollector — FOMC 决议 + FedWatch 概率采集。

数据源（纯爬虫，无需 API Key）：
  1. Investing.com Fed Rate Monitor → hike/cut/hold 概率（stealthy/http 模式）
  2. 美联储官网 FOMC 页面 → 决议结果

FAIL-OPEN：所有异常被捕获，失败时返回空列表。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record
from data_center.crawler.scrapling_engine import ScraplingEngine

logger = logging.getLogger(__name__)

# Investing.com Fed Rate Monitor 页面
_FEDWATCH_URL = "https://www.investing.com/central-banks/fed-rate-monitor"

# 美联储 FOMC 会议日历页
_FOMC_PAST_MEETINGS_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

_engine = ScraplingEngine()


def _parse_percent(text: str) -> float:
    """从字符串解析百分比，如 '85.3%' → 0.853。"""
    if not text:
        return 0.0
    text = text.strip().replace("—", "0").replace("-", "0")
    m = re.search(r"([\d.]+)", text)
    if m:
        return float(m.group(1)) / 100.0
    return 0.0


def _classify_probabilities(
    probabilities: dict, current_lower: float
) -> tuple[float, float, float]:
    """将 CME FedWatch 概率分布按 hike/cut/hold 分类。

    规则：rate_lower > current_lower 为 hike，< 为 cut，= 为 hold。
    probabilities 是百分比值，需 /100.0 转换为 [0,1]。

    Args:
        probabilities: {"3.75%-4.00%": 42.4, "4.00%-4.25%": 57.6} 百分比值
        current_lower: 当前目标利率区间下限，如 4.00

    Returns:
        (hike_prob, cut_prob, hold_prob) — [0,1] 区间，已 round 到 4 位小数
    """
    hike_prob = 0.0
    cut_prob = 0.0
    hold_prob = 0.0

    for rate_range, prob in probabilities.items():
        m = re.search(r"([\d.]+)", str(rate_range))
        if m:
            rate_lower = float(m.group(1))
            if rate_lower > current_lower:
                hike_prob += float(prob) / 100.0
            elif rate_lower < current_lower:
                cut_prob += float(prob) / 100.0
            else:
                hold_prob += float(prob) / 100.0

    return round(hike_prob, 4), round(cut_prob, 4), round(hold_prob, 4)


def _fetch_fedwatch_from_cme() -> dict:
    """从 CME FedWatch 官方数据采集下次会议概率。

    PyPI 包：cme-fedwatch 0.2.1
    接口：from cme_fedwatch import get_probabilities
    返回：{effr, current_target, target_source, trade_date,
           meetings:[{date, contract, probabilities:{...}}]}

    FAIL-OPEN：cme-fedwatch 未安装或调用失败时降级到 investing.com 爬虫
    （参考 SPEC-事件驱动策略P0盲区修复 §3.1.2）。
    """
    try:
        from cme_fedwatch import get_probabilities
    except ImportError:
        logger.warning(
            "[FedWatch] cme-fedwatch 包未安装，降级到 investing.com 爬虫"
        )
        return _fetch_fedwatch_from_investing()

    try:
        data = get_probabilities("next")
    except Exception as e:
        logger.warning(
            "[FedWatch] cme-fedwatch 调用失败，FAIL-OPEN 降级: %s", e
        )
        return _fetch_fedwatch_from_investing()

    if not data or not data.get("meetings"):
        logger.warning("[FedWatch] cme-fedwatch 返回空或无 meetings")
        return {}

    next_meeting = data["meetings"][0]
    probabilities = next_meeting.get("probabilities", {})
    if not probabilities:
        logger.warning("[FedWatch] cme-fedwatch 无概率数据")
        return {}

    effr = float(data.get("effr", 4.00))
    current_target = data.get("current_target", "4.00-4.25")

    # 解析 current_target 区间下限
    m = re.search(r"([\d.]+)", str(current_target))
    current_lower = float(m.group(1)) if m else 4.00

    hike_prob, cut_prob, hold_prob = _classify_probabilities(
        probabilities, current_lower
    )

    if hike_prob == 0 and cut_prob == 0 and hold_prob == 0:
        logger.warning("[FedWatch] cme-fedwatch 概率全为 0")
        return {}

    return {
        "hike_prob": hike_prob,
        "cut_prob": cut_prob,
        "hold_prob": hold_prob,
        "meeting_date": next_meeting.get("date", ""),
        "target_rate": next_meeting.get("contract", ""),
        "effr": effr,
        "current_target": current_target,
        "trade_date": data.get("trade_date", ""),
    }


def _fetch_fedwatch_from_investing() -> dict:
    """从 Investing.com Fed Rate Monitor 爬取下次会议概率。

    页面结构：多个表格，每个代表一次 FOMC 会议
    表格行：Target Rate | Current Probability% | Previous Day% | Previous Week%

    降级路径：cme-fedwatch 包未安装或调用失败时使用。
    """
    # 优先用 http 模式（curl_cffi TLS 指纹），降级到 static
    html = _engine.fetch_html(_FEDWATCH_URL, mode="http", timeout=30)
    if not html:
        logger.warning("[FedWatch] Investing.com 页面返回空")
        return {}

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")

        if not tables:
            logger.warning("[FedWatch] Investing.com 页面无表格")
            return {}

        # 第一个表格 = 最近一次 FOMC 会议
        first_table = tables[0]
        rows = first_table.find_all("tr")

        # 解析概率：按利率区间分类
        # 当前利率约 4.00-4.25（可从数据推断）
        hike_prob = 0.0  # 利率上升的概率
        cut_prob = 0.0   # 利率下降的概率
        hold_prob = 0.0  # 利率不变的概率
        meeting_date = ""
        target_rate = ""

        # 尝试提取会议日期
        text = soup.get_text()
        date_match = re.search(r"(\w{3} \d{1,2},? \d{4})", text)
        if date_match:
            meeting_date = date_match.group(1)

        # �要知道当前利率水平来判断 hike/cut/hold
        # 简化：最高利率区间 = hike，最低 = cut，中间 = hold
        # 更准确：比较利率区间与当前利率
        rate_ranges = []
        for row in rows[1:]:  # 跳过表头
            cells = row.find_all("td")
            if len(cells) >= 2:
                rate_range = cells[0].get_text(strip=True)
                prob_str = cells[1].get_text(strip=True)
                prob = _parse_percent(prob_str)
                rate_ranges.append((rate_range, prob))

        if not rate_ranges:
            logger.warning("[FedWatch] 未解析到利率区间数据")
            return {}

        # 按利率区间排序，最低为 cut，最高为 hike，中间为 hold
        # 当前利率约 4.00-4.25（FRED FEDFUNDS 显示约 4.00%）
        current_rate_approx = 4.00  # 可动态调整

        for rate_range, prob in rate_ranges:
            # 解析利率区间的下限
            m = re.search(r"([\d.]+)", rate_range)
            if m:
                rate_lower = float(m.group(1))
                if rate_lower >= current_rate_approx + 0.25:
                    hike_prob += prob
                elif rate_lower <= current_rate_approx - 0.25:
                    cut_prob += prob
                else:
                    hold_prob += prob
                target_rate = rate_range

        if hike_prob == 0 and cut_prob == 0 and hold_prob == 0:
            logger.warning("[FedWatch] 概率全为 0")
            return {}

        return {
            "hike_prob": round(hike_prob, 4),
            "cut_prob": round(cut_prob, 4),
            "hold_prob": round(hold_prob, 4),
            "meeting_date": meeting_date,
            "target_rate": target_rate,
        }

    except Exception as e:
        logger.warning("[FedWatch] Investing.com HTML 解析失败: %s", e)
        return {}


def _fetch_fomc_decision() -> dict:
    """从美联储官网爬取最近 FOMC 决议。

    步骤：
      1. 从日历页找到最近的声明链接
      2. 抓取声明页，解析利率变化
    """
    # Step 1: 从日历页找到最近的声明 URL
    calendar_html = _engine.fetch_html(_FOMC_PAST_MEETINGS_URL, mode="http", timeout=30)
    if not calendar_html:
        logger.warning("[FOMC] 日历页返回空")
        return {}

    statement_url = ""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(calendar_html, "html.parser")
        # 查找所有指向声明的链接，按日期排序取最新
        all_links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "pressreleases/monetary" in href and href.endswith("a.htm"):
                # 从 URL 提取日期：monetaryYYYYMMDDa.htm
                date_match = re.search(r"monetary(\d{4})(\d{2})(\d{2})a\.htm", href)
                if date_match:
                    date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                    all_links.append((date_str, href))
        # 按日期降序排序，取最新
        all_links.sort(key=lambda x: x[0], reverse=True)
        if all_links:
            href = all_links[0][1]
            if href.startswith("/"):
                href = "https://www.federalreserve.gov" + href
            statement_url = href
    except Exception:
        pass

    if not statement_url:
        logger.warning("[FOMC] 未在日历页找到声明链接")
        return {}

    # Step 2: 抓取声明页
    html = _engine.fetch_html(statement_url, mode="http", timeout=30)
    if not html or len(html) < 5000:
        logger.warning("[FOMC] 声明页返回空: %s", statement_url)
        return {}

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)

        # 解析决议关键词
        text_lower = text.lower()
        if any(kw in text_lower for kw in ("increase", "raise", "hike")):
            decision = "hike"
            rate_change = 0.25
        elif any(kw in text_lower for kw in ("decrease", "cut", "lower")):
            decision = "cut"
            rate_change = -0.25
        elif any(kw in text_lower for kw in ("maintain", "unchanged", "keep")):
            decision = "hold"
            rate_change = 0.0
        else:
            logger.warning("[FOMC] 声明页未找到决议关键词")
            return {}

        # 提取利率区间
        rate_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:to|[-–])\s*(\d+(?:\.\d+)?)\s*(?:percent|%)", text)
        new_rate_range = rate_match.group(0) if rate_match else ""
        if rate_match:
            low = float(rate_match.group(1))
            high = float(rate_match.group(2))
            # 推断 rate_change：与已知当前利率比较
            current_low = 4.00  # 从 FRED FEDFUNDS 推断
            if decision == "hike" and low > current_low:
                rate_change = round(high - low, 2)
            elif decision == "cut" and low < current_low:
                rate_change = -round(high - low, 2)

        # 提取会议日期
        date_match = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})|(\d{4}-\d{2}-\d{2})", text)
        meeting_date = date_match.group(0) if date_match else ""

        # 提取投票结果
        vote_match = re.search(r"(\d+)[-–](\d+)\s*vote", text, re.IGNORECASE)
        votes = f"{vote_match.group(1)}-{vote_match.group(2)}" if vote_match else "unknown"

        # 提取点阵图信息（如果有）
        dot_match = re.search(r"median.*?(\d+(?:\.\d+)?)\s*(?:percent|%)", text, re.IGNORECASE)
        dot_plot_median = float(dot_match.group(1)) if dot_match else 0.0

        return {
            "decision": decision,
            "rate_change": rate_change,
            "new_rate_range": new_rate_range,
            "dot_plot_median": dot_plot_median,
            "votes": votes,
            "meeting_date": meeting_date,
        }
    except Exception as e:
        logger.warning("[FOMC] 声明页解析失败: %s", e)
        return {}


class FedEventCollector(BaseCollector):
    """FOMC 事件 + FedWatch 概率采集器（纯爬虫）。"""

    source = "cme"
    category = "macro"

    def is_available(self) -> bool:
        """不需要 API Key，默认可用。"""
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """按 params["type"] 采集不同数据。

        Args:
            params: {"type": "fedwatch" | "fomc_decision"}

        Returns:
            DataRecord 列表，失败时返回空列表（FAIL-OPEN）。
        """
        event_type = params.get("type")

        if event_type == "fedwatch":
            return self._fetch_fedwatch()
        elif event_type == "fomc_decision":
            return self._fetch_fomc_decision_record()
        else:
            return []

    def _fetch_fedwatch(self) -> list[DataRecord]:
        try:
            data = _fetch_fedwatch_from_cme()
        except Exception as e:
            logger.warning("FedWatch 采集失败，FAIL-OPEN: %s", e)
            return []
        if not data:
            return []

        rec = DataRecord(
            source="cme",
            category="macro",
            sub_category="fedwatch",
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics={
                "hike_prob": data["hike_prob"],
                "cut_prob": data["cut_prob"],
                "hold_prob": data["hold_prob"],
                "meeting_date": data["meeting_date"],
                "target_rate": data["target_rate"],
                # P0 盲区修复新增字段（SPEC §3.1.2）：
                # effr 替代 EventDrivenStrategy._score_real_rate() 中
                #   BASE_RATE_MIDPOINT=3.625 硬编码（event_driven_strategy.py:253）
                # current_target/trade_date 供事件层 _assess_forward_guidance 引用
                # 降级路径（investing.com 爬虫）不返回这三个字段，用 0.0/"" 兜底
                # 契约校验禁止 None，下游用 .get(key, default) 识别降级值
                "effr": data.get("effr") or 0.0,
                "current_target": data.get("current_target") or "",
                "trade_date": data.get("trade_date") or "",
            },
            events=[],
            timeseries=[],
            raw=data,
        )
        validate_record(rec)
        return [rec]

    def _fetch_fomc_decision_record(self) -> list[DataRecord]:
        try:
            data = _fetch_fomc_decision()
        except Exception as e:
            logger.warning("FOMC 决议采集失败，FAIL-OPEN: %s", e)
            return []
        if not data:
            return []

        rec = DataRecord(
            source="cme",
            category="macro",
            sub_category="fomc_decision",
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics={
                "decision": data["decision"],
                "rate_change": data["rate_change"],
                "new_rate_range": data["new_rate_range"],
                "dot_plot_median": data["dot_plot_median"],
                "votes": data["votes"],
                "meeting_date": data["meeting_date"],
            },
            events=[],
            timeseries=[],
            raw=data,
        )
        validate_record(rec)
        return [rec]
