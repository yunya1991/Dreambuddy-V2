#!/usr/bin/env python3
"""
获取最新 BTC 价格数据
"""
import json
import urllib.request
from datetime import datetime, timezone

def fetch_binance_btc_prices(limit=90):
    """从 Binance 获取 BTC/USDT 日线数据"""
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit={limit}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        prices = {}
        for candle in data:
            timestamp = int(candle[0]) / 1000
            date_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
            prices[date_str] = {
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "source": "Binance"
            }

        return prices
    except Exception as e:
        print(f"[ERROR] Fetch failed: {e}")
        return {}

if __name__ == "__main__":
    prices = fetch_binance_btc_prices(90)
    print(f"获取到 {len(prices)} 天价格数据")

    if prices:
        # 保存到文件
        output_file = "/workspace/ops/nanoclaw/core_task1/historical_data/btc_daily_prices.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(prices, f, indent=2)
        print(f"已保存到：{output_file}")

        # 显示最新数据
        latest_date = sorted(prices.keys())[-1]
        print(f"最新数据：{latest_date} 收盘价 ${prices[latest_date]['close']:,.2f}")
