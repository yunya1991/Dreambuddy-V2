"""下载 Binance BTCUSDT 30m K 线 (5 年, ~88K 点) → btc_close_30m.json.

用途: NeuralSDE 第 3 轮数据扩充 (TDD-013 配套).
- 根因 3: 数据量 17469 点偏少 → 扩充至 ~88K 点 (5 年 30m K 线)
- Binance 公共 API (无需 auth): https://api.binance.com/api/v3/klines
- 单次最大 1000 条, 用 startTime 分页
- 输出格式: list of float (close 价), 与 btc_close.json 兼容

用法:
    python download_binance_klines.py
    python download_binance_klines.py --years 5 --interval 30m \\
        --output data/btc_close_30m.json

可选参数:
    --symbol BTCUSDT (默认)
    --interval 30m (默认)
    --years 5 (默认)
    --output data/btc_close_30m.json (默认)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "dreambuddy_evolution" / "data"

# Binance 公共 API (无需 auth)
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# 单次请求最大条数 (Binance 上限 1000)
PAGE_LIMIT = 1000

# 30m 间隔毫秒
INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def fetch_klines_page(
    symbol: str,
    interval: str,
    start_ms: int,
    limit: int = PAGE_LIMIT,
    retries: int = 3,
    sleep_on_429: float = 5.0,
) -> list[list]:
    """单次拉取一页 klines.

    Binance 返回格式: [[open_time, open, high, low, close, volume, ...], ...]
    索引 4 = close price (string).
    """
    params = urlencode({
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "limit": limit,
    })
    url = f"{BINANCE_KLINES_URL}?{params}"

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "neural-sde-data-download/1.0"})
            with urlopen(req, timeout=30) as resp:
                payload = resp.read()
            data = json.loads(payload)
            if isinstance(data, list):
                return data
            last_err = RuntimeError(f"Binance API 非 list 响应: {type(data).__name__}")
        except HTTPError as e:
            if e.code == 429:
                # 限流
                time.sleep(sleep_on_429)
                last_err = e
                continue
            last_err = e
        except (URLError, TimeoutError) as e:
            last_err = e
            time.sleep(1.0)
    raise RuntimeError(f"拉取失败 ({url}): {last_err}")


def download_klines(
    symbol: str,
    interval: str,
    years: float,
) -> list[float]:
    """下载指定年限的 close 序列.

    Returns:
        list of close price (float), 按时间升序
    """
    now_ms = int(time.time() * 1000)
    interval_step = INTERVAL_MS.get(interval)
    if interval_step is None:
        raise ValueError(f"不支持的 interval: {interval}")

    start_ms = now_ms - int(years * 365 * 24 * 3600 * 1000)

    all_closes: list[float] = []
    cursor = start_ms
    page_count = 0
    expected_pages = int(years * 365 * 24 * 3600 * 1000 / interval_step / PAGE_LIMIT) + 1
    print(
        f"[download] {symbol} {interval} {years}y, "
        f"预期 ~{expected_pages} 页, 预期 ~{int(years * 365 * 24 * 3600 * 1000 / interval_step)} 条"
    )

    while cursor < now_ms:
        page = fetch_klines_page(symbol, interval, cursor, PAGE_LIMIT)
        if not page:
            print(f"[download] page {page_count + 1} 空, 终止")
            break

        for row in page:
            # row[4] = close price (string)
            try:
                close = float(row[4])
            except (IndexError, ValueError, TypeError):
                continue
            all_closes.append(close)

        # 推进 cursor 到最后一根 K 线的 close_time + 1ms
        last_close_time = int(page[-1][6])  # row[6] = close_time
        cursor = last_close_time + 1
        page_count += 1

        if page_count % 10 == 0 or page_count == 1:
            print(
                f"[download] page {page_count}/{expected_pages}, "
                f"累计 {len(all_closes)} 条, 当前 cursor={cursor}"
            )

        # Binance 限流保护: 每页间隔 0.2s (权重 1, 1200 weight/min 足够)
        time.sleep(0.2)

        if len(page) < PAGE_LIMIT:
            print(f"[download] page {page_count} 不满 ({len(page)} < {PAGE_LIMIT}), 终止")
            break

    # 去重 + 排序 (按时间隐式升序, 但 close 不含时间戳, 这里只保证顺序)
    # 注: 不去重, 因为同一时间戳不会被返回两次 (startTime 推进)
    print(f"[download] 完成, 共 {len(all_closes)} 条 close")
    return all_closes


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 Binance K 线 close 序列")
    parser.add_argument("--symbol", default="BTCUSDT", help="交易对 (默认 BTCUSDT)")
    parser.add_argument("--interval", default="30m", help="K 线间隔 (默认 30m)")
    parser.add_argument("--years", type=float, default=5.0, help="下载年限 (默认 5)")
    parser.add_argument(
        "--output",
        default=str(DATA_DIR / "btc_close_30m.json"),
        help="输出文件路径",
    )
    args = parser.parse_args()

    print("=" * 70)
    print(f"Binance K 线下载: {args.symbol} {args.interval} {args.years}y")
    print(f"输出: {args.output}")
    print("=" * 70)

    closes = download_klines(args.symbol, args.interval, args.years)
    if not closes:
        print("[FAIL] 未下载到任何数据")
        return 1

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(closes, f)

    print(f"[OK] 保存 {len(closes)} 条 close → {out_path}")
    print(f"     首 3: {closes[:3]}")
    print(f"     末 3: {closes[-3:]}")
    print(f"     min={min(closes):.2f}, max={max(closes):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
