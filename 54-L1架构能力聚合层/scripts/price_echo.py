# -*- coding: utf-8 -*-
"""价格回显 CLI（S1-c 对齐层验证）。

用法：
    python scripts/price_echo.py --symbol BTC --at 2025-03-01
    python scripts/price_echo.py --symbol BTC --at now
    python scripts/price_echo.py --sub-category CPIAUCSL --metric value --at 2025-06-01
    python scripts/price_echo.py --symbol BTC --at 30天前 --json --no-live

口径：
  - 历史价：`<root>/19-数据访问层/data/dreambuddy_core.db` 的日频价格（UTC 日收盘）；
  - 实时价：OKX 公共 ticker（仅加密符号；失败则降级为库内最后一点并如实标注）；
  - 默认基准（硬约束）：加密→BTC；美股→标普/纳指/道指；美联储/宏观→黄金/美股指数；
    大宗商品→石油；避险→黄金；其他→BTC。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

_MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.align import AlignError, load_leader  # noqa: E402
from l1agg.price_echo import (  # noqa: E402
    PriceEchoError,
    format_echo,
    parse_day,
    price_echo,
    resolve_anchor,
)

DEFAULT_DB = os.path.normpath(
    os.path.join(_MODULE_ROOT, "..", "19-数据访问层", "data", "dreambuddy_core.db")
)
OKX_BASES = ("https://www.okx.com", "https://aws.okx.com")
LIVE_SYMBOLS = {"BTC", "ETH", "SOL"}


def fetch_live_ticker(symbol: str, timeout: float = 6.0) -> dict:
    """OKX 公共 ticker → {price, ts, source}；失败抛 PriceEchoError。"""
    inst_id = f"{symbol.upper()}-USDT"
    last_err = ""
    for base in OKX_BASES:
        try:
            req = urllib.request.Request(
                f"{base}/api/v5/market/ticker?instId={inst_id}",
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("code") == "0" and body.get("data"):
                row = body["data"][0]
                return {
                    "price": float(row["last"]),
                    "ts": int(row["ts"]) // 1000,
                    "source": f"{base}/api/v5/market/ticker",
                }
            last_err = body.get("msg") or "empty ticker data"
        except Exception as exc:  # 网络/解析失败均降级
            last_err = f"{type(exc).__name__}: {exc}"
    raise PriceEchoError(f"实时价获取失败（{inst_id}）：{last_err}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="价格回显：当时价 → 现价 → 变化")
    ap.add_argument("--symbol", help="价格锚符号（BTC/ETH/SOL/XAU/US500/CL…）")
    ap.add_argument("--sub-category", default="", help="指标 sub_category（用于自动选锚）")
    ap.add_argument("--metric", default="", help="指标 metric_name（用于自动选锚）")
    ap.add_argument("--category", default="", help="资产类别（crypto/us_stock/macro/energy…）")
    ap.add_argument("--at", default="now", help="目标时点：now / 2025-03-01 / 30天前")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--days", type=int, default=1825)
    ap.add_argument("--live", dest="live", action="store_true", default=True)
    ap.add_argument("--no-live", dest="live", action="store_false")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.sub_category or args.metric or args.category:
        anchor = resolve_anchor(args.sub_category, args.metric, args.category)
    else:
        anchor = None  # 由 symbol 的 asset_class 推断（BTC→加密、XAU→避险…）
    symbol = (args.symbol or (anchor.primary if anchor else "BTC")).upper()

    try:
        at_day = parse_day(args.at)
        series = load_leader(args.db, symbol, days=args.days)
    except (PriceEchoError, AlignError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    live, live_error = None, ""
    if args.live and symbol in LIVE_SYMBOLS:
        try:
            live = fetch_live_ticker(symbol)
        except PriceEchoError as exc:
            live_error = str(exc)

    try:
        echo = price_echo(
            series,
            at_day,
            symbol=symbol,
            anchor=anchor,
            now_price=live["price"] if live else None,
            now_ts=live["ts"] if live else None,
            source=(live["source"] + "+dal_mm_metrics") if live else "dal_mm_metrics",
        )
    except PriceEchoError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    if live_error:
        echo["live_error"] = live_error
    echo["ok"] = True
    if args.json:
        print(json.dumps(echo, ensure_ascii=False, indent=2))
    else:
        print(format_echo(echo))
        if live_error:
            print(f"[降级] {live_error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
