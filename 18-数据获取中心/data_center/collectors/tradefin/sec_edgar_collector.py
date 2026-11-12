"""SecEdgarCollector — SEC EDGAR 官方财报 / 重大事项事件（SPEC §3.2 P0-C）。

数据源（官方公开 API，无需 Key）：
  1. https://www.sec.gov/files/company_tickers.json      ticker → CIK（本地缓存 7 天）
  2. https://data.sec.gov/submissions/CIK##########.json 最近申报（含 acceptanceDateTime）

关键点：`available_at` 直接取 SEC 的 `acceptanceDateTime`（官方受理时间，精确到秒），
因此不存在前视歧义，事件质量 = A。

成员表唯一真源 = 40 `asset_classes.py` 的 us_stock 类（此处只读投影，不复制）。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data_center.collectors.tradefin._http import get_json

logger = logging.getLogger(__name__)

SOURCE = "sec_edgar"

_BASE = Path(__file__).resolve().parents[3]  # 18-数据获取中心
_ASSET_CLASSES = _BASE.parent / "40-周期神经网络系统" / "asset_classes.py"
_CACHE_PATH = _BASE / "data" / "tradefin_cache" / "company_tickers.json"
_CACHE_TTL_DAYS = 7

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# 财报 / 重大事项类表；Form 4（内部人交易）等噪音表不采
FORMS = {"8-K", "10-Q", "10-K", "20-F", "40-F", "6-K"}

# 40 成员符号 → SEC ticker（SEC 用 BRK-B 写法）
TICKER_ALIASES = {"BRKB": "BRK-B", "GOOGL": "GOOGL", "BRK.A": "BRK-A"}

# 8-K items 语义映射（§3.1 的 type 枚举有限，其余归 regulatory）
ITEM_TYPE = {
    "2.02": "earnings",  # results of operations
    "1.01": "mna",  # material definitive agreement
    "2.01": "mna",  # completion of acquisition
    "3.01": "legal",  # delisting / failure to satisfy listing rules
    "5.02": "regulatory",  # director / officer departure
}


def us_stock_symbols() -> list[str]:
    """从 40 资产注册表只读投影 us_stock 成员（FAIL-OPEN → 空列表）。"""
    try:
        spec = importlib.util.spec_from_file_location("dreambuddy_asset_classes", _ASSET_CLASSES)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return list(module.ASSET_CLASSES["us_stock"]["members"])
    except Exception as e:  # noqa: BLE001
        logger.warning("[sec_edgar] 读取 40 资产注册表失败：%s", e)
        return []


def load_company_tickers(force_refresh: bool = False) -> dict[str, int]:
    """加载 ticker→CIK；缓存 7 天，缓存不可用且网络失败时抛错。"""
    if not force_refresh and _CACHE_PATH.is_file():
        try:
            cached = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(cached["updated_at"])
            if datetime.now(timezone.utc) - updated < timedelta(days=_CACHE_TTL_DAYS):
                return {k: int(v) for k, v in cached["map"].items()}
        except Exception as e:  # noqa: BLE001
            logger.debug("[sec_edgar] 缓存不可用：%s", e)

    payload = get_json(COMPANY_TICKERS_URL)
    mapping = {row["ticker"]: int(row["cik_str"]) for row in payload.values()}
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(
                {"updated_at": datetime.now(timezone.utc).isoformat(), "map": mapping},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001 — 缓存写失败不影响采集
        logger.debug("[sec_edgar] 缓存写入失败：%s", e)
    return mapping


def classify(form: str, items: str) -> tuple[str, str]:
    """Form + 8-K items → (type, subtype)。"""
    if form in ("10-K", "10-Q", "20-F", "40-F", "6-K"):
        return "earnings", form
    item_list = [i.strip() for i in str(items or "").split(",") if i.strip()]
    for item in item_list:
        if item in ITEM_TYPE:
            return ITEM_TYPE[item], f"{form} {item}"
    return "regulatory", form


def _iso_z(ts: str) -> str:
    """SEC 的 2026-11-10T16:05:03.000Z → 2026-11-10T16:05:03Z。"""
    raw = str(ts).replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw).astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def filings_to_events(
    payload: dict, symbol: str, *, days: int = 30, now: datetime | None = None
) -> list[dict]:
    """把 submissions JSON 的 filings.recent 转成 EventRecord 列表（窗口过滤）。"""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accepted = recent.get("acceptanceDateTime") or []
    items = recent.get("items") or []
    accessions = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    report_dates = recent.get("reportDate") or []
    cik = int(payload.get("cik") or 0)

    events: list[dict] = []
    for i, form in enumerate(forms):
        if form not in FORMS:
            continue
        if i >= len(accepted) or not accepted[i]:
            continue
        available_at = _iso_z(accepted[i])
        ts = datetime.fromisoformat(available_at.replace("Z", "+00:00"))
        if not (start <= ts <= now):
            continue

        item = items[i] if i < len(items) else ""
        type_, subtype = classify(form, item)
        accession = accessions[i] if i < len(accessions) else ""
        doc = docs[i] if i < len(docs) else ""
        report_date = report_dates[i] if i < len(report_dates) else ""

        url = None
        if accession and doc:
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession.replace('-', '')}/{doc}"
            )

        detail = f" items={item}" if item else ""
        period = f" period={report_date}" if report_date else ""
        events.append(
            {
                "type": type_,
                "subtype": subtype,
                "symbols": [symbol],
                "sector": "us_stock",
                "event_time": available_at,
                "available_at": available_at,
                "source": SOURCE,
                "source_url": url,
                "title": f"{symbol} files {form}{detail}{period}",
                "confidence": 1.0,
                "quality": "A",
            }
        )
    return events


def fetch(
    days: int = 30,
    symbols: list[str] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """采集近 N 天 SEC 申报事件；单个标的失败不影响其他标的（FAIL-OPEN）。"""
    symbols = symbols or us_stock_symbols()
    if not symbols:
        return []
    try:
        tickers = load_company_tickers()
    except Exception as e:  # noqa: BLE001
        logger.warning("[sec_edgar] ticker→CIK 获取失败，跳过本轮：%s", e)
        return []

    events: list[dict] = []
    for sym in symbols:
        ticker = TICKER_ALIASES.get(sym, sym)
        cik = tickers.get(ticker)
        if not cik:
            logger.debug("[sec_edgar] %s 无 CIK，跳过", sym)
            continue
        try:
            payload = get_json(SUBMISSIONS_URL.format(cik=cik))
        except Exception as e:  # noqa: BLE001
            logger.warning("[sec_edgar] %s submissions 失败：%s", sym, e)
            continue
        events.extend(filings_to_events(payload, sym, days=days, now=now))
        time.sleep(0.05)
    return events
