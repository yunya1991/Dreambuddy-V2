#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""加密域内指标历史回填：OI / 多空比 / 资金费率 / ETF 净流入 → mm_metrics。

为什么需要：`l1agg/series_catalog.py` 的 crypto 类内指标（`open_interest`/
`long_short_ratio`/`okx_derivatives`/`etf_flow`）在 2026-11-14 体检时只有 8~17 天，
远低于 S2 相关性/条件收益的 250 日样本门禁。本脚本把可免费获取的历史补齐。

数据源（均免 Key，2026-11-14 云端实测可用）：
  - 持仓量 OI：OKX `rubik/stat/contracts/open-interest-volume`，**最多 180 天**
    （更早窗口返回 50030 Illegal time range，免费源无法突破）
  - 多空账户比：OKX `rubik/stat/contracts/long-short-account-ratio`，同样 180 天
  - 大户多空比：OKX `rubik/stat/contracts/long-short-account-ratio-contract`，
    支持 `begin/end` 回溯 700+ 天（分窗口抓取）
  - 资金费率：OKX `public/funding-rate-history` 只保留约 96 天；
    长历史用 Binance `fapi/v1/fundingRate`（2019 起，免 Key）
  - 持仓量长历史：Binance Vision 日频 `metrics`（`sum_open_interest_value`，USD，
    免 Key，2020 起）；**单所口径，禁止与 OKX 聚合/ccxt 单合约拼接**
  - BTC ETF 净流入：Farside 全量表格（2024-01-11 起），云端直连 Cloudflare 403，
    经 `r.jina.ai` 只读代理拿 Markdown 表格

诚实登记（不编造）：清算（liquidation）无免费历史源——OKX/Binance 仅给 24h 快照，
Coinglass 需 Key —— 见 `UNBOUND`，输出中显式标 `not_collected`。

存储契约（与 18 域 collector 保持一致）：
  - OI / 资金费率：source=okx_derivatives, sub_category=okx_derivatives,
    metric=open_interest_usd / funding_rate_pct / funding_rate_annualized_pct
  - 全合约口径 OI：source=okx, sub_category=open_interest,
    metric=open_interest_value_ccy（与 ccxt 单合约 open_interest_value 分开，禁止拼接）
  - 多空比：source=okx, sub_category=long_short_ratio,
    metric=long_short_ratio / long_account_pct / short_account_pct（大户加 `_top`）
  - Binance 资金费率：source=binance_funding_rate, sub_category=funding_rate,
    metric=funding_rate_pct / funding_rate_annualized_pct
  - Binance 持仓量（单所）：source=binance_vision, sub_category=open_interest,
    metric=open_interest_value_binance（USD） / open_interest_btc_binance（币）
  - ETF 净流入：source=farside, sub_category=etf_flow,
    metric=<发行商列名> + total_flow，单位=百万美元（与前端一致）

幂等：mm_metrics 主键 (source, sub_category, metric_name, timestamp)，
重复运行只做 INSERT OR REPLACE，可安全重跑。

用法:
  python3 scripts/backfill_crypto_derivatives.py --dry-run
  python3 scripts/backfill_crypto_derivatives.py --only okx_oi,binance_funding
  python3 scripts/backfill_crypto_derivatives.py --json
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_DAL_ROOT = os.path.join(_MODULE_ROOT, "..", "19-数据访问层")
for _p in (_MODULE_ROOT, _DAL_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DEFAULT_DB = os.path.join(_MODULE_ROOT, "..", "19-数据访问层", "data", "dreambuddy_core.db")
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

_OKX_BASE = "https://www.okx.com/api/v5"
_BINANCE_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"
_VISION_METRICS = (
    "https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/"
    "{symbol}-metrics-{day}.zip"
)
_FARSIDE_MIRROR = "https://r.jina.ai/https://farside.co.uk/bitcoin-etf-flow-all-data/"
_FETCH_RETRIES = 3
_OKX_FUNDING_MAX_PAGES = 20
_BINANCE_FUNDING_PAGE = 1000
_BINANCE_MAX_PAGES = 30

# 无免费历史源，诚实登记（不写库，输出 not_collected）
UNBOUND = {
    "liquidation": "无免费历史源：OKX/Binance 仅提供 24h 快照，Coinglass 历史需付费 Key",
}

# key → 落库契约。fetchers 必须返回 [{"ts": datetime, "values": {metric: float}}]
TARGETS = (
    {
        "key": "okx_oi",
        "source": "okx_derivatives",
        "sub": "okx_derivatives",
        "label": "OKX 持仓量",
        "days": 180,
    },
    # OKX rubik 的 OI 是「该币种全部合约」聚合口径，与 `open_interest.open_interest_value`
    # （ccxt 单合约口径）不可直接拼接（实测同一日相差 ~35%），故单列 `_ccy` 指标，
    # 避免在规范序列里制造假跳变；规范序列的长期历史仍需付费源。
    {
        "key": "oi_market",
        "source": "okx",
        "sub": "open_interest",
        "label": "合约持仓量（全合约口径）",
        "days": 180,
    },
    {
        "key": "okx_ls",
        "source": "okx",
        "sub": "long_short_ratio",
        "label": "OKX 多空账户比",
        "days": 180,
    },
    {
        "key": "okx_ls_top",
        "source": "okx",
        "sub": "long_short_ratio",
        "label": "OKX 大户多空比",
        "days": 730,
    },
    {
        "key": "okx_funding",
        "source": "okx_derivatives",
        "sub": "okx_derivatives",
        "label": "OKX 资金费率",
        "days": 120,
    },
    {
        "key": "binance_funding",
        "source": "binance_funding_rate",
        "sub": "funding_rate",
        "label": "Binance 资金费率",
        "days": 1095,
    },
    {
        "key": "binance_oi",
        "source": "binance_vision",
        "sub": "open_interest",
        "label": "Binance 持仓量（USD，单所）",
        "days": 1095,
    },
    {
        "key": "etf_flow",
        "source": "farside",
        "sub": "etf_flow",
        "label": "BTC ETF 净流入",
        "days": 1095,
    },
)


def _get_text(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def _get_json(url: str, timeout: float = 30.0) -> dict:
    return json.loads(_get_text(url, timeout))


def _get_bytes(url: str, timeout: float = 30.0) -> bytes | None:
    """取二进制；404（当日文件未生成/不存在）返回 None，其余网络错误上抛重试。"""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _curl_text(url: str, timeout: float = 90.0) -> str:
    """curl 取文本（r.jina.ai 对 urllib 指纹返回 403，curl 默认 UA 正常）。"""
    proc = subprocess.run(
        ["curl", "-s", "--http1.1", "-m", str(int(timeout)), url],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl exit={proc.returncode}: {(proc.stderr or '')[:120]}")
    return proc.stdout


def _retry(fn, *args, **kwargs):
    last = None
    for attempt in range(1, _FETCH_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 网络类异常统一重试
            last = exc
            if attempt < _FETCH_RETRIES:
                time.sleep(0.8 * attempt)
    raise last


def _ms(d: datetime.date) -> int:
    return int(datetime.datetime.combine(d, datetime.time(), datetime.UTC).timestamp() * 1000)


def _utc_date(ms) -> datetime.datetime:
    return datetime.datetime.combine(
        datetime.datetime.fromtimestamp(int(ms) / 1000, datetime.UTC).date(),
        datetime.time(),
        datetime.UTC,
    )


# ============================================================
# 抓取
# ============================================================


def fetch_okx_oi(ccy: str = "BTC", start: datetime.date | None = None) -> list:
    """OKX 持仓量（USD）日频；免费源最多 180 天。"""
    body = _retry(
        _get_json,
        f"{_OKX_BASE}/rubik/stat/contracts/open-interest-volume?ccy={ccy}&period=1D",
    )
    out = []
    for row in body.get("data") or []:
        try:
            ts = _utc_date(row[0])
            oi = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if start and ts.date() < start:
            continue
        out.append({"ts": ts, "values": {"open_interest_usd": oi}})
    out.sort(key=lambda r: r["ts"])
    return out


def fetch_okx_long_short(ccy: str = "BTC", start: datetime.date | None = None) -> list:
    """OKX 多空账户比日频 → ratio + 多/空账户占比。"""
    body = _retry(
        _get_json,
        f"{_OKX_BASE}/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=1D",
    )
    out = []
    for row in body.get("data") or []:
        try:
            ts = _utc_date(row[0])
            ratio = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if ratio <= 0 or (start and ts.date() < start):
            continue
        long_pct = round(ratio / (1 + ratio) * 100, 2)
        out.append(
            {
                "ts": ts,
                "values": {
                    "long_short_ratio": ratio,
                    "long_account_pct": long_pct,
                    "short_account_pct": round(100 - long_pct, 2),
                },
            }
        )
    out.sort(key=lambda r: r["ts"])
    return out


def fetch_okx_long_short_top(
    inst_id: str = "BTC-USDT-SWAP",
    start: datetime.date | None = None,
    today: datetime.date | None = None,
    chunk_days: int = 90,
) -> list:
    """OKX 大户多空比：begin/end 分窗口回溯（单窗 ≤100 条，实测可到 700+ 天）。"""
    today = today or datetime.date.today()
    start = start or (today - datetime.timedelta(days=730))
    seen: dict = {}
    cursor = start
    while cursor <= today:
        end = min(cursor + datetime.timedelta(days=chunk_days - 1), today)
        url = (
            f"{_OKX_BASE}/rubik/stat/contracts/long-short-account-ratio-contract"
            f"?instId={inst_id}&period=1D&begin={_ms(cursor)}&end={_ms(end) + 86400000 - 1}"
        )
        try:
            body = _retry(_get_json, url)
        except Exception:
            cursor = end + datetime.timedelta(days=1)
            continue
        for row in body.get("data") or []:
            try:
                ts = _utc_date(row[0])
                ratio = float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if ratio > 0:
                seen[ts] = ratio
        cursor = end + datetime.timedelta(days=1)
        time.sleep(0.1)
    return [{"ts": ts, "values": {"long_short_ratio_top": val}} for ts, val in sorted(seen.items())]


def fetch_okx_funding(inst_id: str = "BTC-USDT-SWAP", start: datetime.date | None = None) -> list:
    """OKX 资金费率 8h 频；`after=<最早 fundingTime>` 向更旧翻页（约 96 天）。"""
    base = f"{_OKX_BASE}/public/funding-rate-history?instId={inst_id}&limit=100"
    cursor = None
    out = []
    for _ in range(_OKX_FUNDING_MAX_PAGES):
        url = base + (f"&after={cursor}" if cursor else "")
        try:
            body = _retry(_get_json, url)
        except Exception:
            break
        rows = body.get("data") or []
        if not rows:
            break
        oldest = None
        for row in rows:
            try:
                ts_ms = int(row["fundingTime"])
                rate = float(row["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            oldest = ts_ms if oldest is None else min(oldest, ts_ms)
            ts = datetime.datetime.fromtimestamp(ts_ms / 1000, datetime.UTC)
            if start and ts.date() < start:
                continue
            out.append(
                {
                    "ts": ts,
                    "values": {
                        "funding_rate_pct": round(rate * 100, 6),
                        "funding_rate_annualized_pct": round(rate * 3 * 365 * 100, 4),
                    },
                }
            )
        if oldest is None or (start and _utc_date(oldest).date() < start):
            break
        if cursor is not None and oldest >= cursor:
            break  # 无进展，防死循环
        cursor = oldest
        time.sleep(0.12)
    out.sort(key=lambda r: r["ts"])
    return out


def fetch_binance_funding(
    symbol: str = "BTCUSDT",
    start: datetime.date | None = None,
    today: datetime.date | None = None,
) -> list:
    """Binance 资金费率 8h 频，startTime 正向翻页（2019 起，长历史主源）。"""
    today = today or datetime.date.today()
    start = start or (today - datetime.timedelta(days=1095))
    cursor = _ms(start)
    end_ms = _ms(today) + 86400000
    out = []
    for _ in range(_BINANCE_MAX_PAGES):
        url = f"{_BINANCE_FUNDING}?symbol={symbol}&limit={_BINANCE_FUNDING_PAGE}&startTime={cursor}"
        try:
            rows = _retry(_get_json, url)
        except Exception:
            break
        if not isinstance(rows, list) or not rows:
            break
        latest = None
        for row in rows:
            try:
                ts_ms = int(row["fundingTime"])
                rate = float(row["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            latest = ts_ms if latest is None else max(latest, ts_ms)
            if ts_ms > end_ms:
                continue
            out.append(
                {
                    "ts": datetime.datetime.fromtimestamp(ts_ms / 1000, datetime.UTC),
                    "values": {
                        "funding_rate_pct": round(rate * 100, 6),
                        "funding_rate_annualized_pct": round(rate * 3 * 365 * 100, 4),
                    },
                }
            )
        if latest is None or len(rows) < _BINANCE_FUNDING_PAGE:
            break
        cursor = latest + 1
        time.sleep(0.12)
    out.sort(key=lambda r: r["ts"])
    return out


def _parse_num(text: str) -> float:
    val = str(text).strip().replace(",", "")
    if not val or val == "-":
        return 0.0
    neg = val.startswith("(") and val.endswith(")")
    if neg:
        val = val[1:-1]
    try:
        out = float(val)
    except ValueError:
        return 0.0
    return -out if neg else out


def parse_farside_markdown(text: str, start: datetime.date | None = None) -> list:
    """解析 Farside Markdown 表格 → [{ts, values}]，单位=百万美元。"""
    header = None
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if header is None:
            if str(cells[0]).lower().startswith("date"):
                header = cells
            continue
        if all(set(c) <= {"-", ":"} for c in cells):
            continue
        try:
            day = datetime.datetime.strptime(cells[0], "%d %b %Y").date()
        except ValueError:
            continue  # Total/Average 等汇总行
        if start and day < start:
            continue
        values = {}
        for name, cell in zip(header[1:], cells[1:], strict=False):
            metric = "total_flow" if name.lower() == "total" else name
            values[metric] = _parse_num(cell)
        if values:
            out.append(
                {
                    "ts": datetime.datetime.combine(day, datetime.time(), datetime.UTC),
                    "values": values,
                }
            )
    out.sort(key=lambda r: r["ts"])
    return out


def fetch_etf_flow(start: datetime.date | None = None) -> list:
    """Farside → r.jina.ai Markdown 代理（云端直连 Cloudflare 403）。"""
    text = _retry(_curl_text, _FARSIDE_MIRROR, timeout=90.0)
    return parse_farside_markdown(text, start)


def oi_as_market(rows: list) -> list:
    """OKX OI（全合约口径）→ `open_interest.open_interest_value_ccy`。"""
    return [
        {"ts": r["ts"], "values": {"open_interest_value_ccy": r["values"]["open_interest_usd"]}}
        for r in rows
        if "open_interest_usd" in (r.get("values") or {})
    ]


def parse_vision_metrics_csv(text: str) -> dict | None:
    """解析 Binance Vision `metrics` CSV（5 分钟粒度）→ 当日最后一行 OI。"""
    rows = list(csv.reader(io.StringIO(text or "")))
    if len(rows) < 2:
        return None
    header = [str(c).strip() for c in rows[0]]
    try:
        i_val = header.index("sum_open_interest_value")
        i_amt = header.index("sum_open_interest")
    except ValueError:
        return None
    last = rows[-1]
    try:
        return {
            "open_interest_value_binance": float(last[i_val]),
            "open_interest_btc_binance": float(last[i_amt]),
        }
    except (IndexError, TypeError, ValueError):
        return None


def fetch_binance_vision_oi(
    start: datetime.date,
    today: datetime.date | None = None,
    symbol: str = "BTCUSDT",
    sleep_s: float = 0.04,
) -> list:
    """Binance Vision 日频 metrics → 单所 OI 长历史（USD + 币）。

    每日一个 zip（约 11KB，内含 288 行 5 分钟快照），取当日最后一行；
    文件缺失（404）跳过，不伪造。1095 天约 6~10 分钟，建议云端 nohup。
    """
    today = today or datetime.date.today()
    day = start
    end = today - datetime.timedelta(days=1)  # 当天文件收盘后才生成
    out = []
    while day <= end:
        url = _VISION_METRICS.format(symbol=symbol, day=day.isoformat())
        raw = None
        try:
            raw = _retry(_get_bytes, url)
        except Exception:
            raw = None
        if raw:
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    text = zf.read(zf.namelist()[0]).decode("utf-8", "ignore")
                values = parse_vision_metrics_csv(text)
            except Exception:
                values = None
            if values:
                out.append(
                    {
                        "ts": datetime.datetime.combine(day, datetime.time(), datetime.UTC),
                        "values": values,
                    }
                )
        day += datetime.timedelta(days=1)
        if sleep_s:
            time.sleep(sleep_s)
    out.sort(key=lambda r: r["ts"])
    return out


def default_fetchers() -> dict:
    return {
        "okx_oi": lambda start, today: fetch_okx_oi(start=start),
        "oi_market": lambda start, today: oi_as_market(fetch_okx_oi(start=start)),
        "okx_ls": lambda start, today: fetch_okx_long_short(start=start),
        "okx_ls_top": lambda start, today: fetch_okx_long_short_top(start=start, today=today),
        "okx_funding": lambda start, today: fetch_okx_funding(start=start),
        "binance_funding": lambda start, today: fetch_binance_funding(start=start, today=today),
        "binance_oi": lambda start, today: fetch_binance_vision_oi(start, today=today),
        "etf_flow": lambda start, today: fetch_etf_flow(start=start),
    }


# ============================================================
# 编排
# ============================================================


def run(
    fetchers: dict,
    writer,
    *,
    dry_run: bool = False,
    only=None,
    today: datetime.date | None = None,
) -> dict:
    """按 TARGETS 回填。fetchers = {key: callable(start_date, today) -> rows}。"""
    today = today or datetime.date.today()
    wanted = {s.strip() for s in (only or []) if s.strip()}
    results = []
    for target in TARGETS:
        key = target["key"]
        if wanted and key not in wanted:
            continue
        rec = {
            "key": key,
            "label": target["label"],
            "source": target["source"],
            "sub": target["sub"],
            "fetched": 0,
            "written": 0,
            "first": "",
            "last": "",
            "errors": [],
            "status": "ok",
        }
        fetcher = fetchers.get(key)
        if fetcher is None:
            rec["errors"].append(f"no fetcher for {key}")
            rec["status"] = "error"
            results.append(rec)
            continue
        start = today - datetime.timedelta(days=int(target["days"]))
        try:
            rows = fetcher(start, today)
        except Exception as exc:  # noqa: BLE001 - 单源失败不阻塞其他源
            rec["errors"].append(f"fetch: {type(exc).__name__}: {exc}")
            rec["status"] = "error"
            results.append(rec)
            continue
        rec["fetched"] = len(rows)
        if rows:
            rec["first"] = rows[0]["ts"].date().isoformat()
            rec["last"] = rows[-1]["ts"].date().isoformat()
        for row in rows:
            for metric, value in (row.get("values") or {}).items():
                if value is None:
                    continue
                if not dry_run:
                    writer(target["source"], target["sub"], metric, float(value), row["ts"])
                rec["written"] += 1
        if rec["fetched"] == 0:
            rec["status"] = "empty"
        results.append(rec)

    total = sum(r["written"] for r in results)
    unbound = [
        {"key": k, "status": "not_collected", "reason": v}
        for k, v in UNBOUND.items()
        if not wanted or k in wanted
    ]
    return {
        "start": (today - datetime.timedelta(days=1095)).isoformat(),
        "today": today.isoformat(),
        "dry_run": dry_run,
        "targets": results,
        "unbound": unbound,
        "total_written": total,
        "ok": all(r["status"] in ("ok", "empty") for r in results),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="加密域内指标历史回填")
    parser.add_argument("--db", default=_DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--only", default="", help="逗号分隔 key，如 okx_oi,binance_funding")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )

    repo = SqliteMarketMacroRepository(os.path.abspath(args.db))
    result = run(
        default_fetchers(),
        repo.upsert_metric,
        dry_run=args.dry_run,
        only=[s for s in args.only.split(",") if s.strip()],
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"[加密域回填] db={os.path.abspath(args.db)} dry_run={args.dry_run}")
        for r in result["targets"]:
            print(
                f"  {r['key']:18s} n={r['written']:6d} {r['first']}~{r['last']} " f"[{r['status']}]"
            )
            for err in r["errors"]:
                print(f"    ! {err}")
        for u in result["unbound"]:
            print(f"  {u['key']:18s} not_collected — {u['reason']}")
        print(f"  total_written={result['total_written']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
