#!/usr/bin/env python3
"""
生成回测用事件账本（90 天完整数据）

基于历史价格数据生成匹配的事件账本
用于 V9.3 回测验证
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# 导入事件账本生成器
import sys
sys.path.insert(0, str(Path(__file__).parent))
from event_ledger_generator import EventLedgerGenerator, EventLedgerEntry


def generate_news_for_backtest(prices: Dict, days: int = 90) -> List[Dict]:
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

    # 新闻模板（带 sentiment_score）
    positive_templates = [
        ("比特币 ETF 单日净流入{amount}亿美元", "贝莱德 IBIT 单日流入{amount}亿美元", "onchain_data", "high", "T0", 0.7),
        ("链上活跃地址数创新高", "日活跃地址突破{amount}万", "onchain_data", "high", "T1", 0.5),
        ("机构持续增持比特币", "某机构宣布再买入{amount}万枚 BTC", "market_analysis", "medium", "T1", 0.6),
        ("分析师：BTC 目标价{price}万美元", "技术分析显示突破关键阻力位", "kols_view", "low", "T2", 0.4),
        ("稳定币市值突破{amount}亿美元", "USDT+USDC 总市值达{amount}亿", "onchain_data", "high", "T1", 0.5),
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
                price=random.randint(60, 100)
            )

            summary = template[1].format(
                amount=random.randint(1, 50),
                price=random.randint(60, 100)
            )

            # 生成发布时间
            pub_hour = random.randint(0, 23)
            pub_minute = random.randint(0, 59)
            pub_dt = date_dt.replace(hour=pub_hour, minute=pub_minute, second=random.randint(0, 59))

            # 风险旗标
            risk_flags = []
            if template[3] == "low":
                risk_flags.append("单源消息")

            news_item = {
                "title": title,
                "category": template[2],
                "source": "Odaily" if template[2] != "fed" else "华尔街见闻",
                "source_url": f"https://example.com/news/{random.randint(100000, 999999)}",
                "published_at": pub_dt.isoformat(),
                "summary": summary,
                "source_confidence": template[3],
                "impact_horizon": template[4],
                "sentiment_score": template[5] + random.gauss(0, 0.1),
                "cross_market_map": "宏观→加密传导",
                "risk_flags": risk_flags
            }

            all_news.append(news_item)

    # 按时间排序
    all_news.sort(key=lambda x: x["published_at"])

    return all_news


def generate_top_kol_news(dates: list[str], every_n_days: int = 5) -> List[Dict]:
    random.seed(43)
    templates = [
        ("VitalikButerin", "以太坊路线图更新", "Layer2 扩容方案取得进展，Rollup 效率提升", 0.55),
        ("a16zcrypto", "Web3 投资趋势", "AI+Crypto 成新热点，机构持续加码", 0.45),
        ("cz_binance", "市场风险提示", "杠杆率过高，建议投资者谨慎控制风险", -0.35),
    ]
    out: List[Dict] = []
    for idx, date in enumerate(dates):
        if every_n_days <= 0:
            continue
        if idx % every_n_days != 0:
            continue
        date_dt = datetime.strptime(date, "%Y-%m-%d")
        if date_dt.weekday() >= 5:
            continue
        influencer, title, summary, base_sent = random.choice(templates)
        pub_dt = date_dt.replace(hour=random.randint(9, 22), minute=random.randint(0, 59), second=random.randint(0, 59))
        out.append(
            {
                "title": title,
                "category": "kols_view",
                "source": f"twitter/{influencer}",
                "influencer": influencer,
                "source_url": f"https://twitter.com/{influencer}/status/{random.randint(10**8, 10**9-1)}",
                "published_at": pub_dt.isoformat(),
                "summary": summary,
                "source_confidence": "high",
                "impact_horizon": "T0",
                "sentiment_score": base_sent + random.gauss(0, 0.1),
                "cross_market_map": "大 V 观点→市场情绪→价格",
                "risk_flags": [],
            }
        )
    return out


def main():
    """主函数"""
    import argparse
    print("=" * 60)
    print("  生成回测用事件账本（90 天）")
    print("=" * 60)
    parser = argparse.ArgumentParser(description="生成回测用事件账本（支持 V9.5 / V9.7 Direct）")
    parser.add_argument("--days", type=int, default=90, help="生成天数")
    parser.add_argument("--ledger-version", type=str, default="9.5", choices=["9.5", "9.7_direct"], help="事件账本生成器版本")
    args = parser.parse_args()

    # 加载价格数据
    data_dir = Path(__file__).parent.parent / "historical_data"
    price_file = data_dir / "btc_daily_prices.json"

    if not price_file.exists():
        print("[ERROR] 价格数据文件不存在")
        return

    with open(price_file, 'r', encoding='utf-8') as f:
        prices = json.load(f)

    print(f"\n[INFO] 加载价格数据：{len(prices)} 天")

    # 生成新闻
    dates = sorted(prices.keys())[-args.days :]
    sliced_prices = {d: prices[d] for d in dates if d in prices}
    news_list = generate_news_for_backtest(sliced_prices, days=args.days)
    if args.ledger_version == "9.7_direct":
        news_list.extend(generate_top_kol_news(dates, every_n_days=5))
        news_list.sort(key=lambda x: x.get("published_at") or "")
    print(f"生成新闻数：{len(news_list)}")

    # 创建事件账本
    generator = EventLedgerGenerator(ledger_version=args.ledger_version)
    entries = generator.generate_ledger(news_list)
    print(f"生成事件账本条目：{len(entries)}")

    # 保存 JSONL
    output_dir = Path(__file__).parent.parent / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    suffix = "v97_direct" if args.ledger_version == "9.7_direct" else "v95"
    output_path = output_dir / f"event_ledger_backtest_{suffix}_{ts}.jsonl"

    generator.save_jsonl(entries, output_path)

    # 打印统计
    print(f"\n【事件账本统计】")

    by_type = {}
    by_window = {}
    by_surprise = {}
    by_action = {}

    for e in entries:
        t = e.event_type
        by_type[t] = by_type.get(t, 0) + 1

        w = e.window
        by_window[w] = by_window.get(w, 0) + 1

        s = e.surprise_bucket
        by_surprise[s] = by_surprise.get(s, 0) + 1

        a = e.risk_action_proposal
        by_action[a] = by_action.get(a, 0) + 1

    print("\n按事件类型:")
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c} 条")

    print("\n按时间窗口:")
    for w, c in sorted(by_window.items()):
        print(f"  {w}: {c} 条")

    print("\n按意外程度:")
    for s, c in sorted(by_surprise.items()):
        print(f"  {s}: {c} 条")

    print("\n按风险行动:")
    for a, c in sorted(by_action.items()):
        print(f"  {a}: {c} 条")

    print(f"\n[✓] 事件账本已保存：{output_path}")

    return output_path


if __name__ == "__main__":
    main()
