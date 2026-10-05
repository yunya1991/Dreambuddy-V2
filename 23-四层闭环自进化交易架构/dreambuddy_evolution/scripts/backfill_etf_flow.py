#!/usr/bin/env python3
"""
backfill_etf_flow.py — BTC ETF 资金流历史补采脚本 (Phase 3).

数据源: Farside Investors HTML 表格 (免费)
  https://farside.co.uk/bitcoin-etf-flow-all-data/

补采范围: 2024-01-11 (IBIT 等现货 ETF 批准) 至今.
每日净流量 (USD, 汇总所有发行商).
写入 19-DAL mm_metrics (sub_category=etf_flow, metric_name=total_flow).

FAIL-OPEN: 网络/解析异常 → 记录日志退出, 不中断.

用法:
  python backfill_etf_flow.py [--start 2024-01-11] [--end 2025-01-01]
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_etf_flow")

_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_html() -> str:
    """拉取 Farside ETF 资金流 HTML 页面 (cloudscraper 绕过 Cloudflare)."""
    # 优先用 cloudscraper (绕过 Cloudflare), 回退到 requests
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(_URL, timeout=30)
        resp.raise_for_status()
        if "<table" in resp.text:
            return resp.text
    except ImportError:
        logger.debug("cloudscraper 未安装, 回退到 requests")
    except Exception as exc:
        logger.debug("cloudscraper 拉取失败: %s, 回退到 requests", exc)
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.error("拉取 ETF 资金流 HTML 失败: %s", exc)
        return ""


def _parse_flow_value(val: str) -> float:
    """解析资金流数值, 处理括号负数 (如 (95.1) → -95.1) 和逗号."""
    val = val.strip().replace(",", "")
    if not val or val == "-":
        return 0.0
    neg = val.startswith("(") and val.endswith(")")
    if neg:
        val = val[1:-1]
    try:
        v = float(val)
    except ValueError:
        return 0.0
    return -v if neg else v


def parse_html_table(html: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """解析 Farside HTML 表格, 返回 [(date, total_flow_usd), ...].

    表格结构:
      <table>
        <thead><tr><th>Date</th><th>IBIT</th>...<th>Total</th></tr></thead>
        <tbody><tr><td>11 Jan 2024</td><td>111.7</td>...<td>655.3</td></tr>...</tbody>
      </table>
    单位: 百万美元.
    """
    if not html:
        return []

    results: list[tuple[datetime, float]] = []

    # 用 pandas.read_html 解析 (最稳健)
    try:
        import pandas as pd
        tables = pd.read_html(html)
        if not tables:
            logger.warning("pandas.read_html 未找到表格")
            return []
        df = tables[0]
        # 找 Total 列
        total_col = None
        for col in df.columns:
            if "total" in str(col).lower():
                total_col = col
                break

        for _, row in df.iterrows():
            date_str = str(row.iloc[0]).strip()
            # 跳过汇总行
            if date_str.lower() in ("total", "average", "maximum", "minimum", ""):
                continue
            try:
                # 日期格式: "11 Jan 2024"
                dt = datetime.strptime(date_str, "%d %b %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if dt < start or dt > end:
                continue
            if total_col is not None:
                flow_musd = _parse_flow_value(str(row[total_col]))
            else:
                # 无 Total 列, 汇总所有数值列 (跳过第 1 列日期)
                flow_musd = 0.0
                for col in df.columns[1:]:
                    flow_musd += _parse_flow_value(str(row[col]))
            results.append((dt, flow_musd * 1_000_000))  # 百万 → 美元
        return results
    except ImportError:
        logger.warning("pandas 不可用, 回退到正则解析")
    except Exception as exc:
        logger.warning("pandas 解析失败: %s, 回退到正则解析", exc)

    # 回退: 正则解析 <tr> 行
    tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
    tag_pattern = re.compile(r"<[^>]+>")

    for tr_match in tr_pattern.finditer(html):
        cells_html = td_pattern.findall(tr_match.group(1))
        if len(cells_html) < 3:
            continue
        cells = [tag_pattern.sub("", c).strip() for c in cells_html]
        date_str = cells[0]
        if date_str.lower() in ("total", "average", "maximum", "minimum", ""):
            continue
        try:
            dt = datetime.strptime(date_str, "%d %b %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt < start or dt > end:
            continue
        # Total 通常是最后一列
        total_val = _parse_flow_value(cells[-1])
        results.append((dt, total_val * 1_000_000))

    return results


def write_to_dal(records: list[tuple[datetime, float]]) -> int:
    """将 ETF 资金流记录写入 19-DAL."""
    if not records:
        return 0
    try:
        from dreambuddy_dal import get_market_macro_repo
        repo = get_market_macro_repo(backend="sqlite_unified")
    except Exception as exc:
        logger.error("无法获取 DAL repo: %s", exc)
        return 0

    written = 0
    for dt, flow in records:
        try:
            repo.upsert_metric(
                source="farside",
                sub_category="etf_flow",
                metric_name="total_flow",
                metric_value=flow,
                ts=dt,
            )
            written += 1
        except Exception as exc:
            logger.debug("写入失败: %s", exc)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC ETF 资金流历史补采")
    parser.add_argument("--start", default="2024-01-11", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD (默认今天)")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc)

    logger.info("拉取 ETF 资金流: %s ~ %s", start.date(), end.date())
    html = fetch_html()
    if not html:
        logger.error("未获取到 HTML 数据")
        return

    records = parse_html_table(html, start, end)
    logger.info("解析到 %d 条记录", len(records))

    written = write_to_dal(records)
    logger.info("补采完成, 共写入 %d 条", written)


if __name__ == "__main__":
    main()
