# -*- coding: utf-8 -*-
"""PUMP 原生数据采集器 — 从 pump.fun/pump-token 爬取回购销毁数据。

SSR 页面，requests 可直接获取 HTML 含完整数据（2MB，224 script tags）。
采集字段（对齐 BDSM E5/E7 信号需求）：
  - annualized_revenue_usd: 年化协议收入
  - daily_revenue_avg_usd: 日均收入（90d avg）
  - total_buyback_burned_usd: 累计回购销毁 USD
  - total_pump_burned: 累计销毁 PUMP 数量
  - total_supply_offset_pct: 总供应量抵消百分比
  - pump_fdv_usd: PUMP 完全稀释估值
  - pump_price_usd: PUMP 当前价格
  - buyback_allocation_pct: 回购分配比例（50%）
  - daily_active_wallets_solana: Solana 日活钱包
  - timeseries: 每日销毁表格 [{date, pump_burned, sol_spent, usd, price, revenue_pct}]

FAIL-OPEN: 网络异常/解析失败 → 返回空列表，不抛异常。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord

logger = logging.getLogger("data_center.collectors.bdsm.pump")

_PUMP_URL = "https://pump.fun/pump-token"
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (DreamBuddy-BDSM/1.0)"}
_HTTP_TIMEOUT = 15

# 数值解析正则
_MONEY_RE = re.compile(r"\$?\s*([\d.]+)\s*([KMB]?)", re.IGNORECASE)
_PERCENT_RE = re.compile(r"([\d.]+)\s*%")
_NUMBER_RE = re.compile(r"(\d[\d.]*)")


def _parse_money(text: str) -> float:
    """解析 '$436.35M' 或 '436.35M' → 436350000.0, '$4.72B' 或 '4.72B' → 4720000000.0."""
    m = _MONEY_RE.search(text)
    if not m:
        return 0.0
    num = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == "K":
        num *= 1_000
    elif suffix == "M":
        num *= 1_000_000
    elif suffix == "B":
        num *= 1_000_000_000
    return num


def _parse_percent(text: str) -> float:
    """解析 '16.354%' → 16.354."""
    m = _PERCENT_RE.search(text)
    return float(m.group(1)) if m else 0.0


def _parse_number(text: str) -> float:
    """解析 '163.54B' → 163540000000, '815.7K' → 815700."""
    m = _MONEY_RE.search(text)
    if m:
        num = float(m.group(1))
        suffix = m.group(2).upper()
        if suffix == "K":
            num *= 1_000
        elif suffix == "M":
            num *= 1_000_000
        elif suffix == "B":
            num *= 1_000_000_000
        return num
    # 尝试纯数字
    m2 = _NUMBER_RE.search(text)
    return float(m2.group(1)) if m2 else 0.0


def _clean_html(html: str) -> str:
    """清理 HTML 为纯文本（移除 script/template/style/标签）。"""
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html)
    text = re.sub(r"<template[^>]*>[\s\S]*?</template>", " ", text)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def _extract_metric(html: str, label: str, parser=_parse_money) -> float:
    """从 HTML 中提取标签后的数值（兼容 React Streaming SSR）。

    策略：清理 HTML 为纯文本后搜索 label，取后续 200 字符窗口。
    """
    text = _clean_html(html)
    idx = text.find(label)
    if idx < 0:
        return 0.0
    snippet = text[idx: idx + 200]
    return parser(snippet)


def _extract_by_pattern(text: str, pattern: str, group: int = 1, parser=_parse_money) -> float:
    """用正则模式从纯文本中提取数值。"""
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return 0.0
    return parser(m.group(group))


def _parse_daily_table(text: str) -> list[dict]:
    """解析每日销毁表格（在清理后的纯文本上运行）。

    清理后文本格式：
      Aug 31, 2026 229.0M 10.0K $1.03M $ 0.004513 51.88 %
    """
    timeseries = []
    row_re = re.compile(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s*\d{4})\s+"
        r"([\d.]+[MBK]?)\s+"   # PUMP burned
        r"([\d.]+[MBK]?)\s+"   # SOL spent
        r"\$\s*([\d.]+[MBK]?)\s+"  # USD
        r"\$\s*([\d.]+)\s+"   # Price ($ 后可能有空格)
        r"([\d.]+)\s*%",       # % of revenue
        re.IGNORECASE,
    )
    for m in row_re.finditer(text):
        try:
            date_str = m.group(1)
            pump_burned = _parse_number(m.group(2))
            sol_spent = _parse_number(m.group(3))
            usd = _parse_money("$" + m.group(4))
            price = float(m.group(5))
            revenue_pct = float(m.group(6))
            timeseries.append({
                "date": date_str,
                "pump_burned": pump_burned,
                "sol_spent": sol_spent,
                "usd": usd,
                "price": price,
                "revenue_pct": revenue_pct,
            })
        except (ValueError, IndexError):
            continue
    return timeseries


class PumpNativeCollector(BaseCollector):
    """PUMP 原生数据采集器 — pump.fun/pump-token SSR HTML 爬取。"""

    source = "bdsm_pump"
    category = "bdsm"

    def is_available(self) -> bool:
        return True  # 公共页面，无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        """爬取 pump.fun/pump-token，返回 DataRecord 列表。"""
        try:
            resp = requests.get(
                _PUMP_URL, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT
            )
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            logger.warning("PUMP fetch failed: %s", exc)
            return []  # FAIL-OPEN

        return [self._parse_to_record(html)]

    def _parse_to_record(self, html: str) -> DataRecord:
        """解析 HTML 为 DataRecord（基于纯文本 + 精确正则）。"""
        now = datetime.now(timezone.utc).isoformat()
        text = _clean_html(html)

        metrics: dict[str, Any] = {
            # Annualized revenue $436.35M
            "annualized_revenue_usd": _extract_by_pattern(
                text, r"Annualized revenue\s+\$([\d.]+[KMB])"
            ),
            # ≈ $1.20M / day
            "daily_revenue_avg_usd": _extract_by_pattern(
                text, r"≈\s*\$([\d.]+[KMB])\s*/\s*day"
            ),
            # Cumulative buybacks $445.43M
            "total_buyback_burned_usd": _extract_by_pattern(
                text, r"Cumulative buybacks\s+\$([\d.]+[KMB])"
            ),
            # 163.54B $PUMP burned
            "total_pump_burned": _extract_by_pattern(
                text, r"([\d.]+[BMK])\s*\$?PUMP\s+burned", parser=_parse_number
            ),
            # 16.354% (后跟 163.54B $PUMP removed)
            "total_supply_offset_pct": _extract_by_pattern(
                text, r"([\d.]+)%\s*[\d.]+[BMK]?\s*\$?PUMP\s+removed",
                parser=lambda s: float(s) if s else 0.0,
            ),
            # $PUMP price $0.004391
            "pump_price_usd": _extract_by_pattern(
                text, r"\$PUMP\s+price\s+\$([\d.]+)"
            ),
            # $PUMP FDV $4.72B
            "pump_fdv_usd": _extract_by_pattern(
                text, r"FDV\s+\$([\d.]+[KMB])"
            ),
            # Active wallets Solana 815.7K
            "daily_active_wallets_solana": _extract_by_pattern(
                text, r"Solana\s+([\d.]+[KM])", parser=_parse_number
            ),
            "daily_active_wallets_excl_pump": _extract_by_pattern(
                text, r"excl\.\s*Pump\s+([\d.]+[KM])", parser=_parse_number
            ),
            "buyback_allocation_pct": 50.0,  # 固定 50%
        }

        timeseries = _parse_daily_table(text)

        return DataRecord(
            source=self.source,
            category=self.category,
            sub_category="pump_token",
            timestamp=now,
            metrics=metrics,
            events=[],
            timeseries=timeseries,
            raw={"url": _PUMP_URL, "html_length": len(html)},
        )
