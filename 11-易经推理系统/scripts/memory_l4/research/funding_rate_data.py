"""E1 资金费率：只读回填 + 1H 对齐特征。

设计约束（见 docs/SPEC-20261127-E1-funding-rate-ab.md）：
- 只写本地 CSV，不写 18/19 生产库；
- 资金费率按 funding_time 幂等合并；
- 对齐到 1H 时只允许使用 bar 收盘时已结算的费率（禁止 bfill / 未来窗口）；
- 4 个预注册特征：fr_bps / fr_z90 / fr_cum7d_bps / fr_hours_since。

用法：
    python3 scripts/memory_l4/research/funding_rate_data.py \
        --symbols BTC ETH SOL --start 2023-01-01
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "micro" / "funding_rate"

_BASE = "https://fapi.binance.com/fapi/v1/fundingRate"
_SETTLE_HOURS = 8.0


def _ms(iso: str) -> int:
    dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _symbol_to_binance(symbol: str) -> str:
    s = symbol.upper()
    return s if s.endswith("USDT") else f"{s}USDT"


def fetch_funding(symbol: str, start_ms: int, end_ms: int, sleep_sec: float = 0.2) -> list[dict]:
    """分页拉取 Binance fundingRate；单页最多 1000 条。"""
    binance_symbol = _symbol_to_binance(symbol)
    rows: list[dict] = []
    cursor = start_ms
    while cursor < end_ms:
        for attempt in range(4):
            try:
                resp = requests.get(
                    _BASE,
                    params={
                        "symbol": binance_symbol,
                        "startTime": cursor,
                        "endTime": end_ms,
                        "limit": 1000,
                    },
                    timeout=20,
                )
                if resp.status_code in (418, 429):
                    time.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        else:  # pragma: no cover - 仅网络重试耗尽
            break

        if not isinstance(data, list) or not data:
            break
        for item in data:
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "funding_time_ms": int(item["fundingTime"]),
                    "funding_rate": float(item["fundingRate"]),
                    "source": "binance_futures",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        last_ms = int(data[-1]["fundingTime"])
        if len(data) < 1000 or last_ms < cursor:
            break
        cursor = last_ms + 1
        time.sleep(sleep_sec)
    return rows


def merge_csv(path: Path, rows: list[dict]) -> pd.DataFrame:
    """幂等合并：按 funding_time_ms 去重，排序后原子写入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(path) if path.exists() else pd.DataFrame()
    new = pd.DataFrame(rows)
    df = pd.concat([old, new], ignore_index=True) if len(old) else new
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["funding_time_ms"], keep="last")
    df = df.sort_values("funding_time_ms").reset_index(drop=True)
    df["funding_time_iso"] = pd.to_datetime(df["funding_time_ms"], unit="ms", utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%S%z"
    )
    tmp = path.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)
    return df


def load_funding(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    idx = pd.to_datetime(df["funding_time_ms"], unit="ms", utc=True)
    out = df[["funding_rate"]].copy()
    out.index = idx
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def build_features(index: pd.DatetimeIndex, funding: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """把 8h 资金费率转为 1H 对齐的 4 个特征，并返回覆盖诊断。

    对齐原则：每个 1H bar 只使用 funding_time <= bar_time 的最近一次结算。
    """
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")

    s = funding["funding_rate"].astype(float).sort_index()
    s = s[s.index <= index[-1]]

    fr_bps = s * 10000.0
    roll90 = fr_bps.rolling("90D", min_periods=60)
    fr_z90 = (fr_bps - roll90.mean()) / roll90.std(ddof=0)
    fr_cum7d = fr_bps.rolling("7D", min_periods=7).sum()

    feats8 = pd.DataFrame(
        {
            "fr_bps": fr_bps,
            "fr_z90": fr_z90,
            "fr_cum7d_bps": fr_cum7d,
        }
    )
    feats = feats8.reindex(index, method="ffill")

    settle_series = pd.Series(s.index, index=s.index)
    last_settle = settle_series.reindex(index, method="ffill")
    bar_series = pd.Series(index, index=index)
    feats["fr_hours_since"] = (bar_series - last_settle).dt.total_seconds() / 3600.0

    # ── 防前视断言：最近结算时间绝不能晚于 bar 时间 ──
    if last_settle.notna().any():
        bad = (last_settle > bar_series).fillna(False)
        if bool(bad.any()):
            raise AssertionError(f"资金费率对齐出现前视: {int(bad.sum())} 根 bar")

    gaps = s.index.to_series().diff().dt.total_seconds() / 3600.0
    expected = (
        int((s.index[-1] - s.index[0]).total_seconds() / (_SETTLE_HOURS * 3600)) + 1
        if len(s)
        else 0
    )
    diag = {
        "settlements": int(len(s)),
        "first": str(s.index[0]) if len(s) else None,
        "last": str(s.index[-1]) if len(s) else None,
        "expected_settlements": expected,
        "missing_ratio": round(1 - len(s) / expected, 6) if expected else None,
        "max_gap_hours": round(float(gaps.max()), 2) if len(gaps.dropna()) else None,
        "gaps_over_24h_ratio": round(float((gaps > 24).mean()), 6) if len(gaps.dropna()) else None,
        "aligned_coverage": round(float(last_settle.notna().mean()), 6),
        "first_valid_bar": str(feats["fr_bps"].first_valid_index()),
        "warmup_bars_z90": int(feats["fr_z90"].isna().sum()),
    }
    return feats, diag


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--sleep", type=float, default=0.2)
    args = ap.parse_args()

    start_ms = _ms(args.start)
    end_ms = _ms(args.end) if args.end else int(datetime.now(timezone.utc).timestamp() * 1000)
    out_dir = Path(args.out_dir)

    summary = {}
    for symbol in args.symbols:
        path = out_dir / f"{symbol.upper()}_8h.csv"
        rows = fetch_funding(symbol, start_ms, end_ms, sleep_sec=args.sleep)
        df = merge_csv(path, rows)
        funding = load_funding(path) if path.exists() else pd.DataFrame()
        gaps = funding.index.to_series().diff().dt.total_seconds() / 3600.0
        summary[symbol.upper()] = {
            "path": str(path),
            "rows": int(len(df)),
            "new_rows": int(len(rows)),
            "first": str(funding.index[0]) if len(funding) else None,
            "last": str(funding.index[-1]) if len(funding) else None,
            "max_gap_hours": round(float(gaps.max()), 2) if len(gaps.dropna()) else None,
        }
        print(json.dumps(summary[symbol.upper()], ensure_ascii=False))

    print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
