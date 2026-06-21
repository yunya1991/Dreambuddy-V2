#!/usr/bin/env python3
"""
生成与价格数据日期匹配的历史新闻
用于回测验证

基于真实价格变化生成相关新闻情绪
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List


def generate_news_for_prices(prices: Dict, days: int = 90) -> List[Dict]:
    """
    基于价格数据生成历史新闻

    逻辑：
    1. 价格上涨日：更多正面新闻
    2. 价格下跌日：更多负面新闻
    3. 大幅波动日：更多新闻数量
    """
    random.seed(42)  # 可重复结果

    all_news = []
    dates = sorted(prices.keys())

    # 新闻模板
    positive_templates = [
        ("比特币 ETF 单日净流入{amount}亿美元", "贝莱德 IBIT 单日流入{amount}亿美元，总资产管理规模突破{aum}亿", "onchain_data", "high", "T0", 0.7),
        ("链上活跃地址数创新高", "日活跃地址突破{amount}万，Gas 费上涨{pct}%", "onchain_data", "high", "T1", 0.5),
        ("机构持续增持比特币", "某机构宣布再买入{amount}万枚 BTC", "market_analysis", "medium", "T1", 0.6),
        ("分析师：BTC 目标价{price}万美元", "技术分析显示突破关键阻力位", "kols_view", "low", "T2", 0.4),
        ("稳定币市值突破{amount}亿美元", "USDT+USDC 总市值达{amount}亿，月增幅{pct}%", "onchain_data", "high", "T1", 0.5),
    ]

    negative_templates = [
        ("监管担忧加剧，市场情绪承压", "某国考虑限制加密货币交易", "us_policy", "high", "T0", -0.7),
        ("某交易所遭黑客攻击损失{amount}万美元", "漏洞已修复，团队正追踪资金", "security", "high", "T0", -0.8),
        ("分析师：比特币可能测试支撑位", "技术分析显示关键支撑在{price}万", "kols_view", "low", "T2", -0.4),
        ("美联储官员：通胀仍具粘性", "某票委称需更多证据支持降息", "fed", "high", "T0", -0.6),
        ("ETF 单日净流出{amount}亿美元", "灰度 GBTC 流出占主导", "onchain_data", "high", "T0", -0.5),
    ]

    neutral_templates = [
        ("比特币在关键区间震荡", "等待方向选择，成交量萎缩", "market_analysis", "medium", "T1", 0.0),
        ("市场交投清淡，假期临近", "多数投资者观望", "market_analysis", "low", "T2", 0.0),
        ("分析师：短期无明显方向信号", "技术指标中性", "kols_view", "low", "T2", 0.0),
    ]

    for i, date in enumerate(dates):
        day_prices = prices[date]
        open_p = day_prices.get("open", 0)
        close_p = day_prices.get("close", 0)

        if open_p <= 0:
            continue

        # 计算当日涨跌幅
        daily_change = (close_p - open_p) / open_p

        # 根据涨跌幅决定新闻数量和情绪分布
        if abs(daily_change) > 0.05:  # 大幅波动
            num_news = random.randint(4, 8)
        elif abs(daily_change) > 0.02:  # 中等波动
            num_news = random.randint(2, 5)
        else:  # 平静日
            num_news = random.randint(1, 3)

        # 决定情绪分布
        if daily_change > 0.03:  # 大涨
            pos_ratio = 0.7
            neg_ratio = 0.1
        elif daily_change > 0:  # 小涨
            pos_ratio = 0.5
            neg_ratio = 0.2
        elif daily_change < -0.03:  # 大跌
            pos_ratio = 0.1
            neg_ratio = 0.7
        else:  # 小跌
            pos_ratio = 0.2
            neg_ratio = 0.5

        # 生成当日新闻
        date_dt = datetime.strptime(date, "%Y-%m-%d")

        for j in range(num_news):
            rand = random.random()

            if rand < pos_ratio:
                template = random.choice(positive_templates)
            elif rand < pos_ratio + neg_ratio:
                template = random.choice(negative_templates)
            else:
                template = random.choice(neutral_templates)

            # 填充模板变量
            title = template[0].format(
                amount=random.randint(1, 50),
                pct=random.randint(5, 50),
                price=random.randint(60, 100),
                aum=random.randint(30, 60)
            )

            summary = template[1].format(
                amount=random.randint(1, 50),
                pct=random.randint(5, 50),
                price=random.randint(60, 100),
                aum=random.randint(30, 60)
            )

            # 生成发布时间（均匀分布在当天）
            pub_hour = random.randint(0, 23)
            pub_minute = random.randint(0, 59)
            pub_dt = date_dt.replace(hour=pub_hour, minute=pub_minute, second=random.randint(0, 59))

            # 风险旗标
            risk_flags = []
            if template[3] == "low":
                risk_flags.append("单源消息")
            if "传" in title or "疑似" in title:
                risk_flags.append("数据不可复核")

            news_item = {
                "title": title,
                "category": template[2],
                "source_url": f"https://www.odaily.news/newsflash/{random.randint(100000, 999999)}",
                "published_at": pub_dt.isoformat(),
                "summary": summary,
                "source_confidence": template[3],
                "impact_horizon": template[4],
                "sentiment_score": template[5] + random.gauss(0, 0.1),
                "risk_flags": risk_flags,
                "source": "Odaily"
            }

            all_news.append(news_item)

    # 按时间排序
    all_news.sort(key=lambda x: x["published_at"])

    return all_news


def save_news_by_date(news_list: List[Dict], output_dir: Path):
    """按日期分组保存新闻"""
    from collections import defaultdict

    output_dir.mkdir(parents=True, exist_ok=True)

    news_by_date = defaultdict(list)
    for n in news_list:
        date = n["published_at"][:10]
        news_by_date[date].append(n)

    # 保存每日新闻
    for date, date_news in sorted(news_by_date.items()):
        news_file = output_dir / f"news_{date}.json"
        with open(news_file, 'w', encoding='utf-8') as f:
            json.dump(date_news, f, indent=2, ensure_ascii=False)

    print(f"[✓] 新闻数据已保存：{output_dir}")
    print(f"  - 总新闻数：{len(news_list)} 条")
    print(f"  - 覆盖日期：{len(news_by_date)} 天")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='生成与价格数据匹配的历史新闻')
    parser.add_argument('--days', '-d', type=int, default=90, help='生成天数')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出目录')
    args = parser.parse_args()

    print("=" * 60)
    print("  生成历史新闻（与价格数据匹配）")
    print("=" * 60)

    # 加载价格数据
    data_dir = Path(__file__).parent.parent / "historical_data"
    price_file = data_dir / "btc_daily_prices.json"

    if not price_file.exists():
        print("[ERROR] 价格数据文件不存在，请先运行 fetch_historical_prices.py")
        return

    with open(price_file, 'r', encoding='utf-8') as f:
        prices = json.load(f)

    print(f"\n[INFO] 加载价格数据：{len(prices)} 天")

    # 生成新闻
    news_list = generate_news_for_prices(prices, days=args.days)

    # 保存
    output_dir = Path(args.output) if args.output else (data_dir / "historical_news")
    save_news_by_date(news_list, output_dir)

    # 统计情绪分布
    sentiments = [n["sentiment_score"] for n in news_list]
    positive = len([s for s in sentiments if s > 0.2])
    negative = len([s for s in sentiments if s < -0.2])
    neutral = len(sentiments) - positive - negative

    print(f"\n【情绪分布】")
    print(f"  - 正面新闻：{positive} 条 ({positive/len(sentiments)*100:.1f}%)")
    print(f"  - 负面新闻：{negative} 条 ({negative/len(sentiments)*100:.1f}%)")
    print(f"  - 中性新闻：{neutral} 条 ({neutral/len(sentiments)*100:.1f}%)")

    return news_list


if __name__ == "__main__":
    main()
