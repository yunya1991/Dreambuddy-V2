#!/usr/bin/env python3
"""
运行完整回测 - 使用真实历史数据
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

# 添加脚本路径
sys.path.insert(0, str(Path(__file__).parent))

from backtester import BacktestConfig, NewsSignalBacktester


def create_mock_news_for_backtest(start_date: str, end_date: str, prices: dict) -> list:
    """
    为回测期间创建模拟新闻数据

    由于我们没有历史新闻存档，这里使用价格数据生成"伪新闻"
    新闻情绪与当日涨跌相关联，但关键是：
    - 回测时只能使用当日及之前的新闻
    - 不能使用未来新闻预测当日行情

    这是一个简化的测试框架，真实回测需要历史新闻存档
    """
    import random
    random.seed(42)  # 可重复结果

    news = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    current_dt = start_dt

    while current_dt <= end_dt:
        # 周末新闻较少
        is_weekend = current_dt.weekday() >= 5
        num_news = random.randint(0, 3) if is_weekend else random.randint(2, 6)

        date_str = current_dt.strftime("%Y-%m-%d")
        price_data = prices.get(date_str, {})
        price_change = 0

        if price_data:
            open_p = price_data.get("open", 0)
            close_p = price_data.get("close", 0)
            if open_p > 0:
                price_change = (close_p - open_p) / open_p

        for i in range(num_news):
            # 新闻发布时间（均匀分布在全天）
            pub_hour = random.randint(0, 23)
            pub_minute = random.randint(0, 59)
            pub_dt = current_dt.replace(hour=pub_hour, minute=pub_minute)

            # 新闻情绪（与当日价格变化有一定相关性，但不完全相关）
            # 这模拟了现实：新闻确实影响价格，但不是唯一因素
            base_sentiment = random.gauss(0, 0.3)  # 基础情绪

            # 添加一些与价格变化相关的信号（但不使用未来数据）
            # 这里使用当日开盘前的信息（前一日变化）来模拟
            prev_date = (current_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            prev_price = prices.get(prev_date, {})
            if prev_price:
                prev_change = (prev_price.get("close", 0) - prev_price.get("open", 0)) / prev_price.get("open", 1)
                base_sentiment += prev_change * 0.2  # 前一日变化影响今日新闻情绪

            # 确保在 -1 到 1 之间
            sentiment = max(-1, min(1, base_sentiment + random.gauss(0, 0.2)))

            # 新闻模板
            if sentiment > 0.2:
                templates = [
                    "比特币 ETF 持续流入，机构需求强劲",
                    "链上数据显示长期持有者比例上升",
                    "分析师：比特币突破关键阻力位",
                    "某大型机构宣布增持比特币",
                    "美联储官员：货币政策可能转向宽松",
                ]
            elif sentiment < -0.2:
                templates = [
                    "监管担忧加剧，市场情绪承压",
                    "某交易所被传面临调查",
                    "宏观经济数据疲软，风险资产遭抛售",
                    "分析师：比特币可能测试支撑位",
                    "地缘政治紧张，避险情绪上升",
                ]
            else:
                templates = [
                    "比特币在关键区间震荡，等待方向选择",
                    "市场交投清淡，假期临近",
                    "分析师：短期无明显方向信号",
                    "ETF 流入流出基本平衡",
                ]

            news_item = {
                "title": random.choice(templates),
                "summary": f"模拟新闻 {i}",
                "published_at": pub_dt.isoformat(),
                "source_confidence": random.choice(["high", "medium", "low"]),
                "impact_horizon": random.choice(["T0", "T1", "T2"]),
                "sentiment_score": sentiment,
                "risk_flags": [] if random.random() > 0.2 else ["单源消息"],
                "category": random.choice(["onchain_data", "fed", "market_analysis"])
            }
            news.append(news_item)

        current_dt += timedelta(days=1)

    return news


def run_full_backtest():
    """运行完整回测"""
    data_dir = Path(__file__).parent.parent / "historical_data"

    # 加载价格数据
    price_file = data_dir / "btc_daily_prices.json"
    if not price_file.exists():
        print("[ERROR] 价格数据文件不存在，请先运行 fetch_historical_data.py")
        return None

    with open(price_file, 'r', encoding='utf-8') as f:
        prices = json.load(f)

    # 确定回测期间
    dates = sorted(prices.keys())
    start_date = dates[0]
    end_date = dates[-1]

    print("=" * 60)
    print("  新闻信号回测（真实价格数据 + 模拟新闻）")
    print("=" * 60)
    print(f"\n回测期间：{start_date} 至 {end_date}")
    print(f"交易日数：{len(dates)}")

    # 创建模拟新闻
    print("\n[INFO] 生成模拟新闻数据...")
    news = create_mock_news_for_backtest(start_date, end_date, prices)
    print(f"  新闻总数：{len(news)}")

    # 保存新闻数据供后续使用
    news_dir = data_dir / "historical_news"
    news_dir.mkdir(parents=True, exist_ok=True)

    # 按日期分组保存
    from collections import defaultdict
    news_by_date = defaultdict(list)
    for n in news:
        date = n.get("published_at", "")[:10]
        news_by_date[date].append(n)

    for date, date_news in news_by_date.items():
        news_file = news_dir / f"news_{date}.json"
        with open(news_file, 'w', encoding='utf-8') as f:
            json.dump(date_news, f, indent=2, ensure_ascii=False)

    print(f"  新闻数据已保存：{news_dir}")

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
            "lookback_days": config.lookback_days
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

    result_file = data_dir / "backtest_result.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_summary, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] 回测结果已保存：{result_file}")

    return result


if __name__ == "__main__":
    run_full_backtest()
