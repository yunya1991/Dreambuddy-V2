#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 OKX 拉取日线 K 线，生成 evolution 流水线所需的 OHLCV CSV。

云端没有随仓库分发的 data/klines/*.csv 时，用本脚本先补数据，再执行
run_evolution_pipeline.py --sqlite-db 回填 regime_state_daily。

用法：
  python fetch_okx_klines_csv.py --symbols BTCUSDT,AMZNUSDT,BNBUSDT \
      --limit 300 --out-dir ../data/klines
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://www.okx.com"
CANDLES_PATH = "/api/v5/market/candles"


def _candidates(symbol: str) -> list[str]:
    """把 BTCUSDT / BTC-USDT-SWAP 归一化为候选 instId。"""
    s = symbol.strip().upper()
    for suffix in ("-USDT-SWAP", "-USDT"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s.endswith("USDT"):
        s = s[: -len("USDT")]
    return [f"{s}-USDT-SWAP", f"{s}-USDT"]


def _fetch_candles(inst_id: str, limit: int, retries: int = 3) -> list[list[str]]:
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                BASE_URL + CANDLES_PATH,
                params={"instId": inst_id, "bar": "1D", "limit": str(limit)},
                timeout=15,
            )
            payload = resp.json()
            if payload.get("code") != "0":
                last_err = payload.get("msg") or f"code={payload.get('code')}"
            else:
                return payload.get("data") or []
        except Exception as exc:  # noqa: BLE001 - 网络异常统一重试
            last_err = str(exc)
        if attempt < retries:
            time.sleep(2)
    raise RuntimeError(f"{inst_id}: {last_err}")


def _write_csv(path: Path, rows: list[list[str]]) -> int:
    # OKX 返回最新在前，按毫秒时间戳去重并升序写盘
    by_ts = {int(r[0]): r for r in rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for ts_ms in sorted(by_ts):
            r = by_ts[ts_ms]
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([ts, r[1], r[2], r[3], r[4], r[5]])
    return len(by_ts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OKX 日线 → OHLCV CSV")
    parser.add_argument("--symbols", required=True, help="逗号分隔，如 BTCUSDT,AMZNUSDT")
    parser.add_argument("--limit", type=int, default=300, help="K 线根数（OKX 上限 300）")
    parser.add_argument("--out-dir", default="../data/klines", help="CSV 输出目录")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    ok = 0
    failed: list[str] = []
    for raw in args.symbols.split(","):
        symbol = raw.strip().upper()
        if not symbol:
            continue
        last_err = ""
        for inst_id in _candidates(symbol):
            try:
                rows = _fetch_candles(inst_id, args.limit)
                path = out_dir / f"{symbol}_1D.csv"
                count = _write_csv(path, rows)
                print(f"[ok] {symbol} <- {inst_id} rows={count} -> {path}")
                ok += 1
                break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
        else:
            print(f"[fail] {symbol}: {last_err}")
            failed.append(symbol)

    print(f"[summary] ok={ok} failed={len(failed)} {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
