#!/usr/bin/env python3
"""
使用真实历史新闻运行回测

基于已抓取的历史新闻和真实价格数据
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from backtester import BacktestConfig, NewsSignalBacktester


def load_historical_news(news_dir: Path) -> list:
    """加载已抓取的历史新闻"""
    if not news_dir.exists():
        print(f"[ERROR] 新闻目录不存在：{news_dir}")
        return []

    all_news = []
    for news_file in sorted(news_dir.glob("news_*.json")):
        if "cache" in str(news_file):
            continue
        try:
            with open(news_file, 'r', encoding='utf-8') as f:
                day_news = json.load(f)
                if isinstance(day_news, list):
                    all_news.extend(day_news)
                else:
                    all_news.append(day_news)
        except Exception as e:
            print(f"[WARN] 读取失败 {news_file}: {e}")

    print(f"[INFO] 加载历史新闻：{len(all_news)} 条")
    return all_news


def normalize_news_for_backtest(news_list: list) -> list:
    """
    将抓取的新闻格式转换为回测框架兼容格式

    添加 sentiment_score 字段（如果缺失）
    """
    normalized = []

    for n in news_list:
        item = n.copy()

        # 确保有 sentiment_score
        if "sentiment_score" not in item:
            # 基于标题情感计算
            title = item.get("title", "")

            positive_keywords = ["流入", "突破", "新高", "上涨", "利好", "超越", "批准", "宽松", "强劲"]
            negative_keywords = ["流出", "下跌", "攻击", "损失", "暂停", "担忧", "收紧", "疲软", "承压"]

            score = 0
            for kw in positive_keywords:
                if kw in title:
                    score += 0.3
            for kw in negative_keywords:
                if kw in title:
                    score -= 0.3

            item["sentiment_score"] = max(-1, min(1, score))

        # 确保有 source_confidence
        if "source_confidence" not in item:
            item["source_confidence"] = "medium"

        # 确保有 impact_horizon
        if "impact_horizon" not in item:
            item["impact_horizon"] = "T1"

        # 确保有 risk_flags
        if "risk_flags" not in item:
            item["risk_flags"] = []

        normalized.append(item)

    return normalized


def run_backtest_with_real_news():
    """使用真实历史新闻运行回测"""
    data_dir = Path(__file__).parent.parent / "historical_data"

    # 加载价格数据
    price_file = data_dir / "btc_daily_prices.json"
    if not price_file.exists():
        print("[ERROR] 价格数据文件不存在，请先运行 fetch_historical_prices.py")
        return None

    with open(price_file, 'r', encoding='utf-8') as f:
        prices = json.load(f)

    # 加载历史新闻
    news_dir = data_dir / "historical_news"
    news_list = load_historical_news(news_dir)

    if not news_list:
        print("[ERROR] 没有历史新闻数据，请先运行 historical_news_crawler.py")
        return None

    # 标准化新闻格式
    news_list = normalize_news_for_backtest(news_list)

    # 确定回测期间
    dates = sorted(prices.keys())
    start_date = dates[0]
    end_date = dates[-1]

    print("=" * 60)
    print("  新闻信号回测（真实价格 + 真实新闻）")
    print("=" * 60)
    print(f"\n回测期间：{start_date} 至 {end_date}")
    print(f"交易日数：{len(dates)}")
    print(f"新闻总数：{len(news_list)}")

    # 保存新闻数据（用于回测器加载）
    news_dir = data_dir / "historical_news"
    news_dir.mkdir(parents=True, exist_ok=True)

    # 按日期分组保存
    from collections import defaultdict
    news_by_date = defaultdict(list)
    for n in news_list:
        date = n.get("published_at", "")[:10]
        news_by_date[date].append(n)

    for date, date_news in news_by_date.items():
        news_file = news_dir / f"news_{date}.json"
        with open(news_file, 'w', encoding='utf-8') as f:
            json.dump(date_news, f, indent=2, ensure_ascii=False)

    print(f"  新闻数据已整理：{len(news_by_date)} 天")

    # 运行回测
    print("\n[INFO] 运行回测...")

    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=100000,
        transaction_cost=0.001,
        lookback_days=7,
        hold_period=1
    )

    backtester = NewsSignalBacktester(config)
    result = backtester.run_backtest(data_dir)

    # 打印报告
    print(backtester.generate_report(result))

    # 保存结果
    result_summary = {
        "backtest_config": {
            "start_date": config.start_date,
            "end_date": config.end_date,
            "initial_capital": config.initial_capital,
            "transaction_cost": config.transaction_cost,
            "lookback_days": config.lookback_days,
            "data_source": "真实新闻 + 真实价格"
        },
        "results": {
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades
        },
        "daily_equity": result.daily_equity
    }

    result_file = data_dir / "backtest_result_real_news.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_summary, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] 回测结果已保存：{result_file}")

    return result


def main():
    """主函数"""
    result = run_backtest_with_real_news()
    return result


if __name__ == "__main__":
    main()
