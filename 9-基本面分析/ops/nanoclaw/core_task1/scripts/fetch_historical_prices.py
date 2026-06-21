#!/usr/bin/env python3
"""
历史价格数据下载器
从 Binance 和 CoinGecko 下载 BTC 历史价格数据

支持：
1. Binance API - 分钟级/小时级/日线数据
2. CoinGecko API - 日线数据（备用）
3. 数据格式兼容回测框架
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("[ERROR] 请安装 requests: pip3 install requests")
    sys.exit(1)


class BinanceAPI:
    """Binance API 客户端"""

    BASE_URL = "https://api.binance.com"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "X-MBX-APIKEY": ""  # 公共端点不需要
        })

    def get_klines(self, symbol: str, interval: str, start_time: int, end_time: int, limit: int = 1000) -> List[Dict]:
        """
        获取 K 线数据

        Args:
            symbol: 交易对 (如 BTCUSDT)
            interval: 时间间隔 (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            start_time: 开始时间戳 (毫秒)
            end_time: 结束时间戳 (毫秒)
            limit: 单次请求数量 (最大 1000)

        Returns:
            K 线数据列表
        """
        url = f"{self.BASE_URL}/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_time,
            "endTime": end_time,
            "limit": min(limit, 1000)
        }

        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # 解析 K 线数据
            klines = []
            for k in data:
                klines.append({
                    "timestamp": k[0],
                    "datetime": datetime.fromtimestamp(k[0] / 1000).isoformat(),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                })

            return klines

        except Exception as e:
            print(f"[ERROR] Binance API 请求失败：{e}")
            return []

    def fetch_daily_prices(self, days: int = 90) -> Dict[str, Dict]:
        """
        获取日线价格数据

        Args:
            days: 获取天数

        Returns:
            日期 -> 价格数据的字典
        """
        print(f"[INFO] 从 Binance 获取最近 {days} 天 BTC 日线数据...")

        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        # 获取日线数据
        klines = self.get_klines("BTCUSDT", "1d", start_time, end_time, limit=1000)

        if not klines:
            print("[WARN] Binance 数据为空，尝试 CoinGecko...")
            return self._fetch_coingecko_daily(days)

        # 转换为日期索引格式
        daily_prices = {}
        for k in klines:
            date_str = k["datetime"][:10]
            daily_prices[date_str] = {
                "open": k["open"],
                "high": k["high"],
                "low": k["low"],
                "close": k["close"],
                "volume": k["volume"],
                "source": "Binance"
            }

        print(f"[✓] 获取成功：{len(daily_prices)} 天数据")
        return daily_prices

    def _fetch_coingecko_daily(self, days: int = 90) -> Dict[str, Dict]:
        """从 CoinGecko 获取日线数据（备用）"""
        print(f"[INFO] 从 CoinGecko 获取最近 {days} 天 BTC 数据...")

        try:
            url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            params = {
                "vs_currency": "usd",
                "days": days,
                "interval": "daily"
            }

            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            daily_prices = {}
            for price_data in data.get("prices", []):
                timestamp = price_data[0] / 1000
                price = price_data[1]
                date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

                daily_prices[date_str] = {
                    "open": price,  # CoinGecko 只提供收盘价
                    "high": price * 1.02,
                    "low": price * 0.98,
                    "close": price,
                    "volume": 0,
                    "source": "CoinGecko"
                }

            print(f"[✓] 获取成功：{len(daily_prices)} 天数据")
            return daily_prices

        except Exception as e:
            print(f"[ERROR] CoinGecko 请求失败：{e}")
            return {}


class HistoricalDataDownloader:
    """历史数据下载器"""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api = BinanceAPI()

    def download_btc_prices(self, days: int = 90, save: bool = True) -> Dict[str, Dict]:
        """
        下载 BTC 历史价格

        Args:
            days: 下载天数
            save: 是否保存到文件

        Returns:
            日线价格字典
        """
        prices = self.api.fetch_daily_prices(days=days)

        if save and prices:
            self._save_prices(prices, "btc_daily_prices.json")

        return prices

    def _save_prices(self, prices: Dict, filename: str):
        """保存价格数据"""
        output_path = self.output_dir / filename

        # 按日期排序
        sorted_prices = dict(sorted(prices.items()))

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(sorted_prices, f, indent=2, ensure_ascii=False)

        print(f"[✓] 价格数据已保存：{output_path}")

    def download_all(self, days: int = 90) -> Dict:
        """
        下载所有历史数据

        Returns:
            包含所有数据的字典
        """
        print("=" * 60)
        print("  历史数据下载器")
        print("=" * 60)

        # 下载价格数据
        prices = self.download_btc_prices(days=days)

        # 统计信息
        result = {
            "downloaded_at": datetime.now().isoformat(),
            "days": days,
            "price_data": {
                "total_days": len(prices),
                "date_range": f"{min(prices.keys())} ~ {max(prices.keys())}" if prices else "N/A",
                "source": list(prices.values())[0].get("source", "unknown") if prices else "N/A"
            }
        }

        print(f"\n【下载完成】")
        print(f"  - 价格数据：{len(prices)} 天")
        print(f"  - 日期范围：{result['price_data']['date_range']}")
        print(f"  - 数据源：{result['price_data']['source']}")

        return result


def fetch_historical_data(days: int = 90, output_dir: Path = None):
    """
    获取历史数据的主函数

    Args:
        days: 下载天数
        output_dir: 输出目录

    Returns:
        下载结果
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "historical_data"

    downloader = HistoricalDataDownloader(output_dir)
    return downloader.download_all(days=days)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='历史价格数据下载器')
    parser.add_argument('--days', '-d', type=int, default=90, help='下载天数')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出目录')
    args = parser.parse_args()

    output_dir = Path(args.output) if args.output else None

    result = fetch_historical_data(days=args.days, output_dir=output_dir)

    # 打印摘要
    print(f"\n【价格统计】")
    prices_file = Path(__file__).parent.parent / "historical_data" / "btc_daily_prices.json"
    if prices_file.exists():
        with open(prices_file, 'r') as f:
            prices = json.load(f)

        if prices:
            closes = [p["close"] for p in prices.values()]
            print(f"  - 最高价：${max(closes):,.2f}")
            print(f"  - 最低价：${min(closes):,.2f}")
            print(f"  - 平均价：${sum(closes)/len(closes):,.2f}")

    return result


if __name__ == "__main__":
    main()
