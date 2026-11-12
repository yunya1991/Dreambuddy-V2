"""统一行情价格源（SPEC §2.4 U-1 / 缺口 G10）。

职责：**全仓唯一 OHLCV 实现**。40 周期神经网络的 p1/p2/p3、18 compat 兼容层、
48 涌现架构的联合验证，都必须从这里取日线，禁止各自直连交易所。

口径契约（硬约束）：
  - 主源 = OKX `-USDT-SWAP` 永续，日线用 `1Dutc`（UTC 零点对齐，避免 OKX 默认 1D 的 UTC+8 偏移）
  - fallback = Binance 现货日线，仅当 OKX 无数据时启用，且每根 bar 的 `source` 字段必须标注真实来源
  - 只返回**已收盘**的 bar（OKX `confirm=1` / Binance `closeTime <= now`），未收盘的当日 bar 丢弃
  - canonical bar：`ts_ms / open / high / low / close / volume / source`
  - yfinance 指数/ETF 序列不经过本模块（SPEC U-1：仅作 G0 宏观，不进因子）

缓存：`18-数据获取中心/data/market/ohlcv/<BASE>_1D.csv` + `<BASE>_1D.meta.json`，
带 `source / inst_id / first / last / n_bars / gaps` 溯源。

用法：
    python -m data_center.market.price_source --backfill BTC,ETH,SOL,AVAX,LINK --days 2200
    python -m data_center.market.price_source --check
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_BASE = Path(__file__).resolve().parents[2]  # 18-数据获取中心
CACHE_DIR = _BASE / "data" / "market" / "ohlcv"

OKX_API = "https://www.okx.com/api/v5/market"
BINANCE_API = "https://api.binance.com/api/v3"

PRIMARY = "okx"
FALLBACK = ("binance",)

CANONICAL_COLUMNS = ("ts_ms", "open", "high", "low", "close", "volume", "source")
DAY_MS = 86_400_000
OKX_PAGE = 100
BINANCE_PAGE = 1000
DEFAULT_DAYS = 400
MAX_RETRIES = 3
TIMEOUT = 25

_SYMBOL_SUFFIXES = ("-USDT-SWAP", "/USDT:USDT", "/USDT", "-USDT", "-SWAP")


class PriceSourceError(RuntimeError):
    """主源与 fallback 均无法提供数据。"""


def to_inst_id(symbol: str) -> str:
    """任意写法 → OKX instId：`BTC/USDT`、`BTC/USDT:USDT`、`BTC-USDT-SWAP` → `BTC-USDT-SWAP`。"""
    sym = str(symbol).strip().upper()
    for suffix in _SYMBOL_SUFFIXES:
        if sym.endswith(suffix):
            return f"{sym[: -len(suffix)]}-USDT-SWAP"
    return f"{sym}-USDT-SWAP"


def to_binance_symbol(symbol: str) -> str:
    """任意写法 → Binance symbol：`BTC/USDT:USDT` → `BTCUSDT`。"""
    return to_inst_id(symbol).removesuffix("-USDT-SWAP") + "USDT"


def _get_json(url: str, retries: int = MAX_RETRIES, timeout: int = TIMEOUT) -> dict:
    """GET + 指数退避；对端限频/网络抖动重试，最终失败抛 PriceSourceError。"""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (2**attempt))
    raise PriceSourceError(f"请求失败 {url}: {type(last).__name__}: {last}")


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _okx_bar(row: list) -> dict | None:
    """OKX candle → canonical bar；`confirm != 1`（未收盘）返回 None。"""
    if len(row) < 6 or str(row[8]) != "1":
        return None
    return {
        "ts_ms": int(row[0]),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "source": "okx",
    }


def _okx_daily(inst_id: str, days: int) -> list[dict]:
    """OKX `1Dutc` 分页回溯；按 ts 去重、升序、截断到最近 days 根。"""
    bars: dict[int, dict] = {}
    cursor = _now_ms()

    first = _get_json(f"{OKX_API}/candles?instId={inst_id}&bar=1Dutc&limit={OKX_PAGE}")
    if first.get("code") != "0":
        raise PriceSourceError(f"OKX candles code={first.get('code')} msg={first.get('msg')}")
    for row in first.get("data") or []:
        bar = _okx_bar(row)
        if bar:
            bars[bar["ts_ms"]] = bar
    if bars:
        cursor = min(bars) + 1

    while len(bars) < days:
        page = _get_json(
            f"{OKX_API}/history-candles?instId={inst_id}&bar=1Dutc&limit={OKX_PAGE}&after={cursor}"
        )
        if page.get("code") != "0":
            break
        rows = page.get("data") or []
        if not rows:
            break
        before = len(bars)
        for row in rows:
            bar = _okx_bar(row)
            if bar:
                bars[bar["ts_ms"]] = bar
        oldest = min(int(row[0]) for row in rows)
        if len(bars) == before or oldest >= cursor:
            break
        cursor = oldest
        time.sleep(0.12)
    return sorted(bars.values(), key=lambda b: b["ts_ms"])[-days:]


def _binance_daily(symbol: str, days: int) -> list[dict]:
    """Binance 现货日线（UTC）分页；只保留已收盘 bar。"""
    rows: dict[int, dict] = {}
    start = _now_ms() - (days + 5) * DAY_MS
    now = _now_ms()
    while True:
        url = (
            f"{BINANCE_API}/klines?symbol={symbol}&interval=1d"
            f"&startTime={start}&limit={BINANCE_PAGE}"
        )
        data = _get_json(url)
        if not isinstance(data, list) or not data:
            break
        for item in data:
            if int(item[6]) > now:
                continue
            ts = int(item[0])
            rows[ts] = {
                "ts_ms": ts,
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "source": "binance",
            }
        if len(data) < BINANCE_PAGE:
            break
        start = int(data[-1][0]) + DAY_MS
        if start >= now:
            break
    return sorted(rows.values(), key=lambda b: b["ts_ms"])[-days:]


def _summarize(bars: list[dict]) -> dict:
    return {
        "n_bars": len(bars),
        "first": _iso(bars[0]["ts_ms"]) if bars else None,
        "last": _iso(bars[-1]["ts_ms"]) if bars else None,
    }


def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).date().isoformat()


def fetch_daily(symbol: str, days: int = DEFAULT_DAYS, source: str | None = None) -> dict:
    """取日线；主源 OKX，空则显式 fallback 到 Binance。

    Returns:
        {"inst_id","source","bars","n_bars","first","last","fallback_used"}
    """
    inst_id = to_inst_id(symbol)
    order = (source,) if source else (PRIMARY, *FALLBACK)
    errors: list[str] = []
    for name in order:
        try:
            if name == "okx":
                bars = _okx_daily(inst_id, days)
            elif name == "binance":
                bars = _binance_daily(to_binance_symbol(symbol), days)
            else:
                raise PriceSourceError(f"未知价格源：{name}")
        except PriceSourceError as exc:
            errors.append(f"{name}: {exc}")
            continue
        if bars:
            return {
                "inst_id": inst_id,
                "source": name,
                "bars": bars,
                "fallback_used": name != order[0],
                **_summarize(bars),
            }
        errors.append(f"{name}: 无已收盘 bar")
    raise PriceSourceError(f"{inst_id} 取价失败；" + "；".join(errors))


def fetch_closes(symbol: str, days: int = DEFAULT_DAYS) -> list[float]:
    """只取收盘价序列（升序），供 MA/动量计算。"""
    return [bar["close"] for bar in fetch_daily(symbol, days=days)["bars"]]


def cache_paths(base: str) -> tuple[Path, Path]:
    sym = to_inst_id(base).removesuffix("-USDT-SWAP")
    return CACHE_DIR / f"{sym}_1D.csv", CACHE_DIR / f"{sym}_1D.meta.json"


def write_cache(symbol: str, result: dict) -> dict:
    """把 fetch_daily 结果落盘（CSV + meta），返回 meta（含缺口统计）。"""
    csv_path, meta_path = cache_paths(symbol)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    bars = result["bars"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CANONICAL_COLUMNS))
        writer.writeheader()
        for bar in bars:
            writer.writerow({k: bar[k] for k in CANONICAL_COLUMNS})

    gaps = []
    for prev, cur in zip(bars, bars[1:], strict=False):
        missing = (cur["ts_ms"] - prev["ts_ms"]) // DAY_MS - 1
        if missing > 0:
            gaps.append({"after": _iso(prev["ts_ms"]), "missing_days": int(missing)})
    meta = {
        "symbol": to_inst_id(symbol),
        "source": result["source"],
        "fallback_used": result["fallback_used"],
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "n_bars": result["n_bars"],
        "first": result["first"],
        "last": result["last"],
        "n_gaps": len(gaps),
        "missing_days_total": sum(g["missing_days"] for g in gaps),
        "gaps": gaps[:20],
        "csv": str(csv_path),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def read_cache(symbol: str):
    """读缓存为 DataFrame（无缓存返回 None）；列 = canonical + `date`。"""
    import pandas as pd

    csv_path, _ = cache_paths(symbol)
    if not csv_path.is_file():
        return None
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.date
    return df.loc[:, ["date", *CANONICAL_COLUMNS]]


def load_daily(symbol: str, days: int = DEFAULT_DAYS, refresh: bool = False):
    """统一读取入口：缓存优先，缺失或 refresh 时回源并写缓存。返回 (df, meta)。"""
    _, meta_path = cache_paths(symbol)
    if not refresh:
        df = read_cache(symbol)
        if df is not None and len(df) >= days:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return df.tail(days).reset_index(drop=True), meta
    result = fetch_daily(symbol, days=days)
    meta = write_cache(symbol, result)
    df = read_cache(symbol)
    return (df.tail(days).reset_index(drop=True) if df is not None else None), meta


def backfill(symbols: list[str], days: int = DEFAULT_DAYS) -> list[dict]:
    """批量回填统一缓存；单标的失败不中止（FAIL-OPEN，如实回报）。"""
    out: list[dict] = []
    for sym in symbols:
        try:
            out.append(write_cache(sym, fetch_daily(sym, days=days)))
        except PriceSourceError as exc:
            out.append({"symbol": to_inst_id(sym), "error": str(exc)[:200]})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="统一价格源（G10）")
    parser.add_argument("--backfill", help="逗号分隔标的，如 BTC,ETH,SOL")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--check", action="store_true", help="打印缓存覆盖与缺口")
    args = parser.parse_args(argv)

    if args.backfill:
        symbols = [s.strip() for s in args.backfill.split(",") if s.strip()]
        print(json.dumps(backfill(symbols, days=args.days), ensure_ascii=False, indent=2))
        return 0
    if args.check:
        files = sorted(CACHE_DIR.glob("*_1D.meta.json"))
        if not files:
            print(f"[EMPTY] 无缓存：{CACHE_DIR}")
            return 1
        for path in files:
            meta = json.loads(path.read_text(encoding="utf-8"))
            print(
                f"{meta['symbol']:<18} source={meta['source']:<8} "
                f"{meta['first']} → {meta['last']} n={meta['n_bars']} gaps={meta['n_gaps']}"
            )
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
