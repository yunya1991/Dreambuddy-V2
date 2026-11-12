"""VIX 三件套采集器 — SPEC-EMERGENCE-FINANCIAL-ENV §5.2 / §5.2.1（P1-B）。

纪律（三条硬约束）：
  1. **全仓唯一 VIX 采集实现**：本模块的 `fetch_vix()` 由 nanoclaw `market_data.py` 迁移而来
     （签名与容错逻辑保持不变，SPEC §5.2.1 第 2 条"提取提升，不重写"）。
  2. **主源 FRED `VIXCLS`**（日频 T+1，可回填、point-in-time 明确）；Yahoo `^VIX` 仅当日实时补充，
     落库 `metrics.source` 区分口径；同日 FRED 与 Yahoo 差 > 0.5 时告警且以 FRED 为准。
  3. **拿不到就留空**：`vix3m` / `vvix` / `put_call_ratio` 缺失时字段不出现在 metrics（JSON 层为 null），
     禁止填 0 冒充（G10 教训：多口径/伪值会让下游不可比）。

数据源：
  - FRED CSV（免 Key）：`VIXCLS`
  - CBOE CSV：`VIX3M`（3 个月期限结构）、`VVIX`（波动率的波动率）
  - put/call ratio：CBOE 无稳定公开 CSV 端点 → 默认留空（SPEC §5.2 允许 "CBOE 公开数据 / Yahoo"，
    无可用端点时按 null 纪律处理，不用 0 冒充）

fail-open：除 429 抛 RateLimitError 外，网络/解析异常一律降级为空序列，不阻塞交易热路径（H1）。
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record
from data_center.core.errors import RateLimitError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FRED_CSV_ENDPOINT = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CBOE_CSV_ENDPOINT = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"

# 主源（FRED 日频）+ 期限结构/二阶（CBOE）
FRED_SERIES = {"vix": "VIXCLS"}
CBOE_SERIES = {"vix3m": "VIX3M", "vvix": "VVIX"}

# RegimeSchema.vix 需落库的数值字段（缺失即缺省，不用 0 冒充）
# 方向契约（SPEC §5.2.1）：vix_ratio = VIX/VIX3M（<1 = contango，>1 = backwardation），
# 仅作原始比价；方向量请用 48/metrics/regime.py 的 RegimeSchema.slope（= VIX3M/VIX - 1，正 = contango）
VALUE_FIELDS = ("vix", "vix3m", "vix_ratio", "vvix", "put_call_ratio")

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) dream-data-center/1.0"


# ---------------------------------------------------------------------------
# 基础 HTTP（迁移自 nanoclaw market_data.py，容错逻辑不变）
# ---------------------------------------------------------------------------
def _http_json(url: str, params: dict | None = None, timeout: int = 10) -> Any:
    resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": _USER_AGENT})
    if resp.status_code == 429:
        raise RateLimitError(f"限流 429: {url}")
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {url}")
    return resp.json()


def _http_json_retry(
    url: str,
    params: dict | None = None,
    timeout: int = 10,
    retries: int = 3,
    backoff_s: float = 0.6,
) -> Any:
    last_err: Exception | None = None
    for i in range(max(1, int(retries))):
        try:
            return _http_json(url, params=params, timeout=timeout)
        except RateLimitError:
            raise
        except Exception as e:  # noqa: BLE001 — 重试后统一抛出原始异常
            last_err = e
            if i < retries - 1:
                time.sleep(backoff_s * (2**i))
    raise last_err  # type: ignore[misc]


def _last_two_closes(closes: list) -> tuple[float | None, float | None]:
    valid = [v for v in closes if isinstance(v, (int, float))]
    if len(valid) < 2:
        return None, None
    return float(valid[-1]), float(valid[-2])


def _yahoo_chart(symbol: str) -> dict | None:
    data = _http_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": "5d", "interval": "1d"},
        timeout=10,
    )
    chart = data.get("chart", {})
    result = (chart.get("result") or [{}])[0]
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    last_close, prev_close = _last_two_closes(quote.get("close") or [])
    if not last_close or not prev_close:
        return None
    change_pct = (last_close - prev_close) / prev_close * 100
    return {"value": last_close, "change_24h": change_pct, "source": "Yahoo Finance"}


def fetch_vix() -> dict:
    """获取 VIX 恐慌指数（全仓唯一实现，迁移自 nanoclaw market_data.py）。

    返回契约保持原样：`{"value": float, "source": str}`；不可用时 `{"value": 0, "source": "N/A"}`
    （0 仅为兼容旧消费方的"不可用"哨兵，落库前由调用方剔除）。
    """
    try:
        data = _http_json_retry(
            "https://www.alphavantage.co/query",
            params={
                "function": "GLOBAL_QUOTE",
                "symbol": "^VIX",
                "apikey": os.environ.get("ALPHA_VANTAGE_API_KEY", "demo"),
            },
            timeout=10,
            retries=2,
            backoff_s=0.8,
        )
        quote = data.get("Global Quote", {})
        value = float(quote.get("05. price", 0))
        if value > 0:
            return {"value": value, "source": "CBOE via Alpha Vantage"}
    except Exception:
        pass
    try:
        yahoo = _yahoo_chart("^VIX")
        if yahoo:
            return {"value": yahoo["value"], "source": yahoo["source"]}
    except Exception:
        pass
    return {"value": 0, "source": "N/A"}


# ---------------------------------------------------------------------------
# 历史序列（FRED / CBOE）
# ---------------------------------------------------------------------------
def _get_text(
    url: str, params: dict | None = None, timeout: int = 20, attempts: int = 3
) -> str | None:
    """GET 文本，带重试（CBOE/FRED 边缘对连续 python 请求会间歇性断连）。"""
    for i in range(attempts):
        try:
            resp = requests.get(
                url, params=params, timeout=timeout, headers={"User-Agent": _USER_AGENT}
            )
        except requests.RequestException:
            resp = None
        if resp is not None:
            if resp.status_code == 429:
                raise RateLimitError(f"限流 429: {url}")
            if resp.ok:
                return resp.text
        if i < attempts - 1:
            time.sleep(0.8 * (2**i))
    return None


def _fred_csv_text(series_id: str, timeout: int = 20) -> str | None:
    """取 FRED CSV 文本。

    实测：FRED 边缘对 python-requests 的 TLS 指纹直接断连（HTTP/1.1 与 httpx h2 均失败），
    而系统 curl 可正常拿到 → requests 失败时回退 curl，避免主源被静默降级为 Yahoo。
    """
    params = {"id": series_id}
    text = _get_text(FRED_CSV_ENDPOINT, params=params, timeout=timeout, attempts=2)
    if text:
        return text

    url = f"{FRED_CSV_ENDPOINT}?{urlencode(params)}"
    try:
        proc = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout
    return None


def _fred_pairs(series_id: str, timeout: int = 30) -> list[tuple[date, float]]:
    """FRED fredgraph.csv → [(date, value)]；缺失值 '.' 跳过。网络异常降级为空（fail-open）。"""
    text = _fred_csv_text(series_id, timeout=timeout)
    if not text:
        return []
    out: list[tuple[date, float]] = []
    for i, line in enumerate(text.strip().splitlines()):
        if i == 0:
            continue
        parts = line.split(",")
        if len(parts) != 2:
            continue
        raw_date, raw_val = parts[0].strip(), parts[1].strip()
        if not raw_date or raw_val in ("", "."):
            continue
        try:
            out.append((date.fromisoformat(raw_date), float(raw_val)))
        except ValueError:
            continue
    return out


def _cboe_pairs(symbol: str, timeout: int = 20) -> list[tuple[date, float]]:
    """CBOE `*_History.csv` → [(date, value)]；取最后一列（CLOSE 或值列）。网络异常降级为空。"""
    text = _get_text(CBOE_CSV_ENDPOINT.format(symbol=symbol), timeout=timeout)
    if not text:
        return []
    out: list[tuple[date, float]] = []
    for i, line in enumerate(text.strip().splitlines()):
        if i == 0:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[-1]:
            continue
        try:
            d = datetime.strptime(parts[0], "%m/%d/%Y").date()
            out.append((d, float(parts[-1])))
        except ValueError:
            continue
    return out


def fetch_history(key: str, days: int = 400, timeout: int = 30) -> list[dict]:
    """按 keys（vix / vix3m / vvix）拉历史，返回升序 [{"date","value"}]。

    put_call 无稳定公开 CSV → 返回空列表（调用方留 null）。
    """
    if key in FRED_SERIES:
        pairs = _fred_pairs(FRED_SERIES[key], timeout=timeout)
    elif key in CBOE_SERIES:
        pairs = _cboe_pairs(CBOE_SERIES[key], timeout=timeout)
    else:
        return []
    if not pairs:
        return []
    cutoff = pairs[-1][0] - timedelta(days=days)
    return [{"date": d.isoformat(), "value": v} for d, v in pairs if d >= cutoff]


# ---------------------------------------------------------------------------
# 单一口径合并
# ---------------------------------------------------------------------------
def merge_daily(days: int = 30, live: bool = True, warn: list[str] | None = None) -> list[dict]:
    """把 FRED / CBOE / Yahoo 合并为日频单一口径序列（升序）。

    - 主源：FRED `VIXCLS`（缺失的交易日不补、不前向填充）
    - 期限结构：CBOE `VIX3M`；`vix_ratio = vix / vix3m`（<1 = contango 常态，>1 = backwardation 倒挂）
    - 二阶：CBOE `VVIX`
    - put/call：无稳定公开源 → None
    - `live=True`：FRED T+1 未出当日值 → Yahoo `^VIX` 追加当日行（source=yahoo）；
      同日双源都 >0 且 |diff| > 0.5 → 记 warn 且保留 FRED
    """
    warn = warn if warn is not None else []
    series = {key: fetch_history(key, days=days) for key in (*FRED_SERIES, *CBOE_SERIES)}

    by_date: dict[str, dict[str, float]] = {}
    for key, rows in series.items():
        for row in rows:
            by_date.setdefault(row["date"], {})[key] = float(row["value"])

    merged: list[dict] = []
    for d in sorted(by_date):
        item = by_date[d]
        level, three_m = item.get("vix"), item.get("vix3m")
        merged.append(
            {
                "date": d,
                "vix": level,
                "vix3m": three_m,
                "vix_ratio": round(level / three_m, 6) if level and three_m else None,
                "vvix": item.get("vvix"),
                "put_call_ratio": None,  # CBOE put/call 无稳定公开 CSV，按 null 纪律留空
                "source": "fred" if level is not None else "cboe",
            }
        )

    if live:
        quote = fetch_vix()
        value = float(quote.get("value") or 0)
        today = datetime.now(timezone.utc).date().isoformat()
        last = merged[-1]["date"] if merged else None
        if value > 0 and (last is None or today > last):
            merged.append(
                {
                    "date": today,
                    "vix": value,
                    "vix3m": None,
                    "vix_ratio": None,
                    "vvix": None,
                    "put_call_ratio": None,
                    "source": "yahoo",
                }
            )
            warn.append(f"FRED T+1 缺口：{today} 用 Yahoo ^VIX 当日补充={value}")
        elif value > 0 and last == today and merged[-1].get("vix") is not None:
            diff = abs(float(merged[-1]["vix"]) - value)
            if diff > 0.5:
                warn.append(
                    f"{today} FRED={merged[-1]['vix']} vs Yahoo={value} 差 {diff:.2f}>0.5，以 FRED 为准"
                )
    return merged


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------
class VixCollector(BaseCollector):
    """VIX 三件套采集器（SDK 轨）。

    usage:
        dc.fetch("chain", source="vix", days=30)
    """

    source = "vix"
    category = "chain"

    def is_available(self) -> bool:
        # FRED/CBOE 公共 CSV 免 Key
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        days = int((params or {}).get("days", 30))
        live = bool((params or {}).get("live", True))
        records: list[DataRecord] = []
        for row in merge_daily(days=max(days, 30), live=live):
            metrics: dict = {"date": row["date"], "symbol": "VIX", "source": row["source"]}
            for field in VALUE_FIELDS:
                value = row.get(field)
                if isinstance(value, (int, float)):
                    metrics[field] = float(value)
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category="vix_daily",
                timestamp=f"{row['date']}T00:00:00+00:00",
                metrics=metrics,
                events=[],
                timeseries=[],
                raw={"merged": row},
            )
            validate_record(rec)
            records.append(rec)
        return records
