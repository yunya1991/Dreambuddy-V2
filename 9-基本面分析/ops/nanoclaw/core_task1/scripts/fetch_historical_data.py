#!/usr/bin/env python3
"""
历史数据下载器
获取真实的 BTC 历史价格数据用于回测

数据源：
1. CoinGecko API (免费，有速率限制)
2. Binance API (免费，需要较少限制)
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def fetch_btc_prices_from_coingecko(days: int = 90) -> dict:
    """
    从 CoinGecko 获取 BTC 历史价格

    API: https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days=90
    """
    if not HAS_REQUESTS:
        print("[ERROR] 需要安装 requests 库：pip install requests")
        return {}

    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days={days}"

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        # API 限流处理
        if resp.status_code == 429:
            print("[WARN] 触发 API 限流，等待 60 秒...")
            time.sleep(60)
            return fetch_btc_prices_from_coingecko(days)

        data = resp.json()

        # 转换为日期 -> OHLC 格式
        prices = {}
        for candle in data:
            timestamp = candle[0] / 1000  # 毫秒转秒
            dt = datetime.fromtimestamp(timestamp)
            date_str = dt.strftime("%Y-%m-%d")

            prices[date_str] = {
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
                "volume": candle[5] if len(candle) > 5 else 0
            }

        return prices

    except Exception as e:
        print(f"[ERROR] 获取价格数据失败：{e}")
        return {}


def fetch_btc_prices_from_binance(days: int = 90) -> dict:
    """
    从 Binance 获取 BTC 历史价格（备用）

    API: https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=90
    """
    if not HAS_REQUESTS:
        return {}

    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": "BTCUSDT",
        "interval": "1d",
        "limit": days
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        prices = {}

        for candle in data:
            timestamp = candle[0] / 1000
            dt = datetime.fromtimestamp(timestamp)
            date_str = dt.strftime("%Y-%m-%d")

            prices[date_str] = {
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5])
            }

        return prices

    except Exception as e:
        print(f"[ERROR] 获取 Binance 数据失败：{e}")
        return {}


def create_historical_news_from_outputs(data_dir: Path) -> list:
    """
    从已有的简报输出中提取历史新闻（用于回测）

    这确保我们使用的是当时实际生成的新闻，没有未来数据
    """
    outputs_dir = data_dir.parent / "outputs"
    if not outputs_dir.exists():
        print(f"[WARN] 输出目录不存在：{outputs_dir}")
        return []

    all_news = []

    # 读取所有简报文件
    for brief_file in outputs_dir.glob("brief_*.md"):
        try:
            with open(brief_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取生成时间
            import re
            time_match = re.search(r'\*\*生成时间\*\*: ([^\n]+)', content)
            if not time_match:
                continue

            generated_at = time_match.group(1).strip()

            # 提取新闻标题和分类（简化解析）
            # 实际使用时应该更精确地解析 Markdown
            sections = content.split("###")
            for section in sections[1:]:  # 跳过第一个空段
                lines = section.strip().split("\n")
                if not lines:
                    continue

                title = lines[0].strip()

                # 跳过提示性文字
                if "⚠️" in title:
                    title = title.split("⚠️")[0].strip()

                # 提取关键事实
                fact = ""
                for line in lines:
                    if "**事实**:" in line or "**关键事实**:" in line:
                        fact = line.split(":", 1)[1].strip()
                        break
                    if "**观点**:" in line or "**事件**:" in line:
                        fact = line.split(":", 1)[1].strip()
                        break

                # 提取来源
                source = ""
                for line in lines:
                    if "来源" in line and "http" in line:
                        import re
                        url_match = re.search(r'\[.*\]\((https?://[^)]+)\)', line)
                        if url_match:
                            source = url_match.group(1)
                        break

                # 估算情绪分数（基于关键词）
                sentiment = estimate_sentiment(title + " " + fact)

                news_item = {
                    "title": title,
                    "summary": fact,
                    "published_at": generated_at,
                    "source_url": source,
                    "sentiment_score": sentiment,
                    "source_confidence": "medium",  # 默认
                    "impact_horizon": "T1",
                    "risk_flags": ["⚠️" in section] if "⚠️" in section else [],
                    "original_file": str(brief_file)
                }
                all_news.append(news_item)

        except Exception as e:
            print(f"[WARN] 解析简报文件失败：{brief_file}, 错误：{e}")
            continue

    # 按时间排序
    all_news.sort(key=lambda x: x.get("published_at", ""))

    print(f"[INFO] 从简报中提取了 {len(all_news)} 条历史新闻")
    return all_news


def estimate_sentiment(text: str) -> float:
    """估算文本情绪分数 (-1 到 +1)"""
    text = text.lower()

    positive_words = [
        "利好", "上涨", "突破", "新高", "流入", "强劲", "超预期",
        "宽松", "支持", "增长", "繁荣", "复苏", "受益", "利好"
    ]
    negative_words = [
        "利空", "下跌", "抛售", "调查", "风险", "担忧", "收紧",
        "监管", "制裁", "衰退", "危机", "违约", "恶化", "承压",
        "恐慌", "暴跌", "崩盘"
    ]

    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in negative_words)

    total = pos_count + neg_count
    if total == 0:
        return 0.0

    # 归一化到 -1 到 +1
    return (pos_count - neg_count) / total


def save_historical_data(data_dir: Path):
    """保存历史数据到文件"""
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. 获取价格数据
    print("[INFO] 正在获取 BTC 历史价格数据...")
    prices = fetch_btc_prices_from_binance(days=365)  # 获取 1 年数据

    if prices:
        price_file = data_dir / "btc_daily_prices.json"
        with open(price_file, 'w', encoding='utf-8') as f:
            json.dump(prices, f, indent=2, ensure_ascii=False)
        print(f"[✓] 价格数据已保存：{price_file} ({len(prices)} 天)")
    else:
        print("[ERROR] 无法获取价格数据")

    # 2. 从简报提取历史新闻
    print("[INFO] 正在从历史简报中提取新闻...")
    news = create_historical_news_from_outputs(data_dir.parent)

    if news:
        news_dir = data_dir / "historical_news"
        news_dir.mkdir(parents=True, exist_ok=True)

        # 按日期分组保存
        news_by_date = {}
        for n in news:
            date = n.get("published_at", "")[:10]
            if date not in news_by_date:
                news_by_date[date] = []
            news_by_date[date].append(n)

        for date, date_news in news_by_date.items():
            news_file = news_dir / f"news_{date}.json"
            with open(news_file, 'w', encoding='utf-8') as f:
                json.dump(date_news, f, indent=2, ensure_ascii=False)

        print(f"[✓] 新闻数据已保存：{news_dir} ({len(news_by_date)} 天)")
    else:
        print("[WARN] 没有找到历史新闻数据")


def main():
    """主函数"""
    data_dir = Path(__file__).parent.parent / "historical_data"

    print("=" * 60)
    print("  历史数据下载器")
    print("=" * 60)

    save_historical_data(data_dir)

    # 验证数据
    print("\n[INFO] 验证数据...")

    price_file = data_dir / "btc_daily_prices.json"
    if price_file.exists():
        with open(price_file, 'r') as f:
            prices = json.load(f)
        print(f"  价格数据：{len(prices)} 天")
        if prices:
            first_date = list(prices.keys())[0]
            last_date = list(prices.keys())[-1]
            print(f"  日期范围：{first_date} 至 {last_date}")
            print(f"  最新收盘价：${prices[last_date]['close']:,.2f}")

    print("\n[INFO] 数据准备完成！")
    print(f"  数据目录：{data_dir}")


if __name__ == "__main__":
    main()
