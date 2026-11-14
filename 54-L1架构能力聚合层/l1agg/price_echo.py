# -*- coding: utf-8 -*-
"""S1-c: 价格回显（asof 对齐验证）。

用途：给定任意时间点，返回「该时间点当时可得的价格」+「当前价格」+「变化」，
用于端到端验证 `align` 层的 UTC 日收盘 / asof / 陈旧判定是否成立。

纪律：
  - 核心纯函数：不联网、不写库；实时价由调用方注入（`now_price`）；
  - asof 语义：取 <= 目标日的最近一个价格点，**禁止未来函数**；
  - 默认对齐基准（用户 2026-11-14 确认，硬约束）：
      加密市场 → BTC；美股/股指 → 标普/纳指/道指（主 US500）；
      美联储/宏观 → 黄金/美股指数（主 XAU）；大宗商品 → 石油（CL）；
      避险资产 → 黄金；其他 → BTC；
  - 任何输出必带 `asof_day / staleness_days / sample_n / span / align_method / timezone / gate`。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Mapping, Optional, Tuple

# 日频价格的最大容忍陈旧天数（超过即标 stale，但仍如实回显）
MAX_STALE_DAYS = 3
TIMEZONE = "UTC"
ALIGN_METHOD = "asof_daily_last"


class PriceEchoError(ValueError):
    """价格回显参数/数据错误（无数据、日期非法、目标早于首点）。"""


# ============================================================
# 默认对齐基准（硬约束）：类别 → 价格锚
# ============================================================


@dataclass(frozen=True)
class Anchor:
    """一组价格锚：`primary` 用于数值回显，`alternates` 供后续相关性扩展。"""

    group: str
    label: str
    primary: str
    alternates: Tuple[str, ...] = ()
    reason: str = ""


ANCHORS: Dict[str, Anchor] = {
    "crypto": Anchor("crypto", "加密市场", "BTC", ("ETH", "SOL"), "加密域内数据统一对齐 BTC"),
    "us_equity": Anchor(
        "us_equity",
        "美股/股指",
        "US500",
        ("US100", "DJIA"),
        "美股个股/ETF/股指对齐标普、纳指、道指（主标普）",
    ),
    "macro": Anchor(
        "macro",
        "美联储/宏观",
        "XAU",
        ("US500", "US100"),
        "美联储/宏观信息对齐黄金与美股指数（主黄金）",
    ),
    "commodity": Anchor("commodity", "大宗商品", "CL", ("BZ", "NG"), "大宗商品对齐石油（主 WTI）"),
    "safe_haven": Anchor("safe_haven", "避险资产", "XAU", (), "避险资产对齐黄金"),
    "default": Anchor("default", "其他", "BTC", (), "未分类数据默认对齐 BTC"),
}

# leader_registry 的 asset_class → 锚组
_CLASS_TO_GROUP = {
    "crypto": "crypto",
    "us_index": "us_equity",
    "us_stock": "us_equity",
    "us_etf": "us_equity",
    "macro": "macro",
    "rates_credit": "macro",
    "fx": "macro",
    "energy": "commodity",
    "industrial_metal": "commodity",
    "commodity": "commodity",
    "precious_metal": "safe_haven",
}

# 指标名/子类关键词 → 锚组（按顺序匹配，先命中先返回）
_KEYWORD_GROUPS: List[Tuple[str, Tuple[str, ...]]] = [
    ("safe_haven", ("黄金", "gold", "xau", "xag", "白银", "避险")),
    (
        "commodity",
        ("wti", "brent", "原油", "石油", "油价", "天然气", "dcoil", "dhhngsp", "xcu", "铜"),
    ),
    (
        "macro",
        (
            "dgs10",
            "fedfunds",
            "cpiaucsl",
            "cpi",
            "ppi",
            "ppiaco",
            "m2",
            "fedwatch",
            "vix",
            "dxy",
            "dtwexbgs",
            "t10y2y",
            "hy_oas",
            "indpro",
            "美债",
            "利率",
            "通胀",
            "美联储",
            "降息",
            "美元指数",
        ),
    ),
    (
        "us_equity",
        (
            "sp500",
            "nasdaq",
            "djia",
            "spy",
            "qqq",
            "nvda",
            "aapl",
            "msft",
            "tsla",
            "amzn",
            "googl",
            "meta",
            "标普",
            "纳指",
            "道指",
            "美股",
        ),
    ),
    (
        "crypto",
        (
            "btc",
            "eth",
            "sol",
            "crypto",
            "加密",
            "fear_greed",
            "恐惧贪婪",
            "funding",
            "open_interest",
            "long_short",
            "多空",
            "etf_flow",
            "etf_flow",
            "whale",
            "巨鲸",
            "onchain",
            "链上",
            "tvl",
            "dominance",
            "市占率",
            "stablecoin",
            "稳定币",
            "hashrate",
            "算力",
            "mvrv",
            "sopr",
            "nupl",
            "liquidation",
            "清算",
            "taker",
            "options",
            "期权",
            "deribit",
            "okx",
            "binance",
            "coinglass",
            "交易所",
        ),
    ),
]


def resolve_anchor(
    sub_category: str = "",
    metric_name: str = "",
    category: str = "",
) -> Anchor:
    """按用户确认的默认基准解析价格锚。

    Args:
        sub_category / metric_name: `mm_metrics` 的序列标识（用于关键词兜底）。
        category: 40 层资产类别（`asset_classes.py` / leader_registry 的 asset_class）。

    Returns:
        Anchor；无法判定时返回 `default`（BTC），并在 `reason` 中说明。
    """
    cat = str(category or "").strip().lower()
    if cat in _CLASS_TO_GROUP:
        return ANCHORS[_CLASS_TO_GROUP[cat]]

    haystack = f"{sub_category} {metric_name}".lower()
    if haystack.strip():
        for group, keywords in _KEYWORD_GROUPS:
            if any(kw in haystack for kw in keywords):
                return ANCHORS[group]
    return ANCHORS["default"]


# ============================================================
# 日期解析
# ============================================================


def _today(today: Optional[date] = None) -> date:
    return today or datetime.now(tz=timezone.utc).date()


def _fmt(d: date) -> str:
    return d.isoformat()


def parse_day(text: str, *, today: Optional[date] = None) -> str:
    """自然语言/标准日期 → `YYYY-MM-DD`（UTC 口径）。

    支持：`2025-03-01`、`2025/3/1`、`2025年3月1日`、`现在/今天`、`昨天`、`前天`、
    `N天前`、`N周前`、`N个月前`、`上周`、`上个月`、`年初`。

    Raises:
        PriceEchoError: 无法识别或日期非法。
    """
    day = find_day_reference(text, today=today, include_now=True)
    if day is None:
        raise PriceEchoError(f"无法识别日期：{text!r}")
    return day


def find_day_reference(
    text: str,
    *,
    today: Optional[date] = None,
    include_now: bool = False,
) -> Optional[str]:
    """从文本提取日期；未命中返回 None。

    Args:
        include_now: True 时把「现在/今天/实时」解析为今天；False 时返回 None
                     （供「是否属于历史回显」的判定使用）。
    """
    if not text:
        return None
    raw = str(text).strip()
    low = raw.lower()
    base = _today(today)

    if include_now and any(k in low for k in ("现在", "当前", "实时", "今天", "today", "now")):
        return _fmt(base)
    if "前天" in low:
        return _fmt(base - timedelta(days=2))
    if any(k in low for k in ("昨天", "昨日", "yesterday")):
        return _fmt(base - timedelta(days=1))
    if "上周" in low:
        return _fmt(base - timedelta(days=7))
    if any(k in low for k in ("上个月", "上月", "last month")):
        return _fmt(base - timedelta(days=30))
    if "年初" in low:
        return _fmt(date(base.year, 1, 1))

    m = re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?", raw)
    if not m:
        m = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", raw)
    if m:
        try:
            return _fmt(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError as exc:
            raise PriceEchoError(f"非法日期：{raw!r}（{exc}）") from exc

    # 无年份「9月9日 / 9月9号」：默认今年，若晚于今天则回退去年（如「12月1日」在 11 月问）
    m = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", raw)
    if m:
        month, dom = int(m.group(1)), int(m.group(2))
        candidate = None
        for year in (base.year, base.year - 1):
            try:
                candidate = date(year, month, dom)
            except ValueError:
                continue
            if candidate <= base:
                break
            candidate = None
        if candidate is None:
            raise PriceEchoError(f"非法日期：{raw!r}（{month}月{dom}日）")
        return _fmt(candidate)

    m = re.search(r"(\d+)\s*个?\s*(天|日|周|月)\s*前", raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"天": n, "日": n, "周": n * 7, "月": n * 30}[unit]
        return _fmt(base - timedelta(days=delta))
    return None


def find_past_day_reference(text: str, *, today: Optional[date] = None) -> Optional[str]:
    """只识别「过去」的日期引用；「现在/今天」返回 None（走实时价路径）。"""
    return find_day_reference(text, today=today, include_now=False)


# ============================================================
# asof 与回显
# ============================================================


@dataclass
class AsofPoint:
    """某一目标日的当时价格快照（永不晚于目标日）。"""

    day: str
    asof_day: str
    price: float
    staleness_days: int
    stale: bool = False
    meta: Dict[str, object] = field(default_factory=dict)


def asof_price(
    series: Mapping[str, float],
    day: str,
    *,
    max_stale_days: int = MAX_STALE_DAYS,
) -> AsofPoint:
    """取 `<= day` 的最近一个价格点（asof 连接）。

    Raises:
        PriceEchoError: 序列为空，或目标日早于序列首点。
    """
    if not series:
        raise PriceEchoError("price series is empty")
    try:
        target = date.fromisoformat(day)
    except ValueError as exc:
        raise PriceEchoError(f"invalid day: {day}") from exc

    candidates = [d for d in series if d <= day]
    if not candidates:
        raise PriceEchoError(f"no price on/before {day}; series starts {min(series)}")
    asof_day = max(candidates)
    stale_days = (target - date.fromisoformat(asof_day)).days
    return AsofPoint(
        day=day,
        asof_day=asof_day,
        price=float(series[asof_day]),
        staleness_days=stale_days,
        stale=stale_days > max_stale_days,
    )


def price_echo(
    series: Mapping[str, float],
    at_day: str,
    *,
    symbol: str,
    anchor: Optional[Anchor] = None,
    now_price: Optional[float] = None,
    now_ts: Optional[int] = None,
    now_day: Optional[str] = None,
    source: str = "dal_mm_metrics",
    max_stale_days: int = MAX_STALE_DAYS,
    today: Optional[date] = None,
) -> Dict[str, object]:
    """构造「当时价 → 现价 → 变化」回显（纯函数）。

    Args:
        series: {YYYY-MM-DD: price}，来自 `align.load_leader` / `align.load_price`。
        at_day: 目标历史日。
        symbol: 回显标的价格符号（如 BTC / US500 / XAU）。
        anchor: 默认基准；None 时按 symbol 归属推断。
        now_price: 实时价（调用方注入，如 OKX ticker）；None 时用库内最后一点。
        now_ts: 实时价时间戳（epoch 秒，UTC）。
        now_day: 实时价所属 UTC 日；None 时由 now_ts 或今天推断。
        source: 数据来源标注（如 `okx_ticker+dal_mm_metrics`）。
    """
    if anchor is None:
        from l1agg.leader_registry import resolve

        binding = resolve(symbol)
        anchor = resolve_anchor(category=binding.asset_class if binding else "")

    at = asof_price(series, at_day, max_stale_days=max_stale_days)

    base_today = _today(today)
    if now_price is not None:
        kind = "live"
        if now_day is None:
            if now_ts is not None:
                now_day = datetime.fromtimestamp(int(now_ts), tz=timezone.utc).date().isoformat()
            else:
                now_day = _fmt(base_today)
        now_value = float(now_price)
        now_stale_days = (base_today - date.fromisoformat(now_day)).days
    else:
        kind = "last_available"
        last_day = max(series)
        now_day = now_day or last_day
        now_value = float(series[last_day])
        now_stale_days = (base_today - date.fromisoformat(last_day)).days

    change_abs = now_value - at.price
    change_pct = (now_value / at.price - 1.0) * 100.0 if at.price else None
    dates = sorted(series)
    gate = "ok"
    if at.stale or now_stale_days > max_stale_days:
        gate = "stale"

    return {
        "symbol": symbol,
        "anchor": {
            "group": anchor.group,
            "label": anchor.label,
            "primary": anchor.primary,
            "alternates": list(anchor.alternates),
            "reason": anchor.reason,
        },
        "at": {
            "day": at.day,
            "asof_day": at.asof_day,
            "price": at.price,
            "staleness_days": at.staleness_days,
        },
        "now": {
            "day": now_day,
            "price": now_value,
            "kind": kind,
            "staleness_days": max(0, now_stale_days),
        },
        "change": {
            "abs": round(change_abs, 6),
            "pct": None if change_pct is None else round(change_pct, 4),
        },
        "sample_n": len(dates),
        "span": f"{dates[0]}~{dates[-1]}",
        "align_method": ALIGN_METHOD,
        "timezone": TIMEZONE,
        "source": source,
        "gate": gate,
    }


def format_echo(echo: Mapping[str, object]) -> str:
    """回显结果 → 中文单句（含口径与门禁）。"""
    at = echo["at"]  # type: ignore[index]
    now = echo["now"]  # type: ignore[index]
    chg = echo["change"]  # type: ignore[index]
    anchor = echo["anchor"]  # type: ignore[index]
    pct = chg.get("pct")
    sign = "+" if (pct or 0) >= 0 else ""
    kind_label = "实时" if now.get("kind") == "live" else "库内最后一点（非实时）"
    text = (
        f"{echo['symbol']}（{anchor['label']}基准）：{at['day']} 当时价 "
        f"{at['price']:,.2f}（UTC 日收盘，实际取 {at['asof_day']}，滞后 {at['staleness_days']} 天）；"
        f"当前{kind_label} {now['price']:,.2f}；"
        f"变化 {sign}{pct:.2f}%（{sign}{chg['abs']:,.2f}）。"
        f"口径 {echo['align_method']}｜时区 {echo['timezone']}｜样本 {echo['sample_n']}｜"
        f"跨度 {echo['span']}。"
    )
    if echo.get("gate") != "ok":
        text += "｜数据陈旧或非实时，仅作对齐链路验证。"
    return text


def echo_anchor_price(
    db_path: str,
    at_day: str,
    *,
    sub_category: str = "",
    metric_name: str = "",
    category: str = "",
    symbol: str = "",
    days: int = 1825,
    now_price: Optional[float] = None,
    now_ts: Optional[int] = None,
    source: str = "dal_mm_metrics",
) -> Dict[str, object]:
    """按默认基准自动选锚并回显（从 DAL 读价格，不联网）。

    指标类查询（加密/美股/宏观/大宗/避险）走这里：由 `sub_category/metric_name`
    解析锚组，再读该锚的日频价格序列。
    """
    from l1agg.align import load_leader

    anchor = resolve_anchor(sub_category, metric_name, category)
    target = symbol or anchor.primary
    if not os.path.isfile(db_path):
        raise PriceEchoError(f"db not found: {db_path}")
    series = load_leader(db_path, target, days=days)
    return price_echo(
        series,
        at_day,
        symbol=target,
        anchor=anchor,
        now_price=now_price,
        now_ts=now_ts,
        source=source,
    )
