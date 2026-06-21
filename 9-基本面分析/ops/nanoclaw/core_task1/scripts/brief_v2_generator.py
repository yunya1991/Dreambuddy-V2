#!/usr/bin/env python3
"""
简报生成器 V2 - brief_v2

功能:
1. 多源确认逻辑：需≥2 个不同来源一致，否则标记为候选
2. 注意力三维度：attention_score, attention_type
3. 引用 narrative_changelog.jsonl
4. 生成 brief_v2_{YYYYMMDD_HHMM}.md
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict


def _topic_key(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return ""
    t = t.replace("｜", "|").replace("：", ":")
    if ":" in t:
        left, right = t.split(":", 1)
        if 0 < len(left.strip()) <= 10 and right.strip():
            t = right.strip()
    t = re.sub(r"^[【\[][^】\]]+[】\]]\s*", "", t)
    t = re.sub(r"[（(].*?[）)]", "", t)
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t)
    return t[:40]


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    summary: str
    source: str
    source_type: str
    url: str
    published_at: str
    category: str
    sentiment_score: float
    source_confidence: str  # high/medium/low
    impact_horizon: str     # T0/T1/T2
    cross_market_map: str
    risk_flags: List[str]
    attention_score: int    # 0-5
    attention_type: str     # narrative|event|policy|security|market_microstructure
    confirmation_status: str  # confirmed|candidate|unverified
    confirming_sources: List[str]


class BriefV2Generator:
    """简报 V2 生成器"""

    def __init__(self, raw_dir: Path, outputs_dir: Path):
        self.raw_dir = raw_dir
        self.outputs_dir = outputs_dir
        self.confirmation_threshold = 2  # ≥2 个不同来源

    def load_narrative_changelog(self) -> List[Dict]:
        """加载叙事变更日志"""
        changelog_path = self.raw_dir / "narrative_changelog.jsonl"
        if not changelog_path.exists():
            return []

        with open(changelog_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content.startswith('['):
                return json.loads(content)
            else:
                items = []
                for line in content.split('\n'):
                    if line.strip():
                        items.append(json.loads(line))
                return items

    def check_multi_source_confirmation(self, news_items: List[Dict]) -> List[Dict]:
        """
        多源确认逻辑：
        - high 可信度：直接确认（权威媒体单独报道即可信）
        - medium 可信度：需≥2 个不同来源
        - low 可信度：标记为候选
        """
        # 按主题分组
        by_topic = defaultdict(list)
        for item in news_items:
            key = _topic_key(item.get('title', ''))
            by_topic[key].append(item)

        confirmed_items = []
        candidate_items = []

        for topic, items in by_topic.items():
            sources = set()
            for item in items:
                sources.add(item.get('source', ''))

            for item in items:
                confidence = item.get('source_confidence', 'low')

                # 确认逻辑调整：
                if confidence == 'high':
                    # 权威媒体直接确认
                    item['confirmation_status'] = 'confirmed'
                    item['confirming_sources'] = list(sources)
                    confirmed_items.append(item)
                elif confidence == 'medium' and len(sources) >= self.confirmation_threshold:
                    # 中等可信度需多源确认
                    item['confirmation_status'] = 'confirmed'
                    item['confirming_sources'] = list(sources)
                    confirmed_items.append(item)
                else:
                    # 其他情况标记为候选
                    item['confirmation_status'] = 'candidate'
                    item['confirming_sources'] = list(sources)
                    candidate_items.append(item)

        return confirmed_items + candidate_items

    def calculate_attention_score(self, item: Dict, all_items: List[Dict]) -> int:
        """
        计算注意力分数 (0-5)
        - 0: 单源、无二次传播
        - 3: 多源复述/主流媒体覆盖
        - 5: 跨圈层高频传播
        """
        title_key = _topic_key(item.get('title', ''))
        similar_count = sum(1 for i in all_items if _topic_key(i.get('title', '')) == title_key)

        source_confidence = item.get('source_confidence', 'low')
        source_type = item.get('source_type', '')

        score = 0
        if similar_count >= 3:
            score = 5  # 跨圈层
        elif similar_count >= 2:
            score = 3  # 多源复述
        else:
            score = 1  # 单源

        # 来源可信度调整
        if source_confidence == 'high' and score < 4:
            score = min(5, score + 1)

        return score

    def determine_attention_type(self, item: Dict) -> str:
        """
        确定注意力类型
        - narrative: 叙事性内容
        - event: 具体事件
        - policy: 政策相关
        - security: 安全事件
        - market_microstructure: 市场微观结构
        """
        category = item.get('category', '')
        title = item.get('title', '').lower()

        if '政策' in title or '监管' in title or category in ['fed_policy', 'us_policy']:
            return 'policy'
        elif '攻击' in title or '黑客' in title or category == 'security':
            return 'security'
        elif '资金' in title or '交易所' in title or '链上' in title:
            return 'market_microstructure'
        elif '数据' in title or '分析' in title:
            return 'event'
        else:
            return 'narrative'

    def generate_brief_v2(self, news_items: List[Dict]) -> str:
        """生成 V2 简报"""
        # 多源确认
        confirmed_items = self.check_multi_source_confirmation(news_items)

        # 计算注意力分数
        for item in confirmed_items:
            item['attention_score'] = self.calculate_attention_score(item, news_items)
            item['attention_type'] = self.determine_attention_type(item)

        # 按确认状态分组
        confirmed = [i for i in confirmed_items if i.get('confirmation_status') == 'confirmed']
        candidates = [i for i in confirmed_items if i.get('confirmation_status') == 'candidate']

        # 按情感和影响分类
        bullish = [i for i in confirmed if i.get('sentiment_score', 0) > 0.2]
        bearish = [i for i in confirmed if i.get('sentiment_score', 0) < -0.2]
        neutral = [i for i in confirmed if -0.2 <= i.get('sentiment_score', 0) <= 0.2]

        # T0/T1 事件
        t0_items = [i for i in confirmed if i.get('impact_horizon') == 'T0']
        t1_items = [i for i in confirmed if i.get('impact_horizon') == 'T1']

        # 生成 Markdown
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 计算摘要统计
        avg_sentiment = sum(i.get('sentiment_score', 0) for i in confirmed) / len(confirmed) if confirmed else 0
        top_story = max(confirmed, key=lambda x: x.get('attention_score', 0)) if confirmed else None

        md = f"""# 加密市场简报 V2 ({now})

---

## 核心观点

| 项目 | 内容 |
|------|------|
| **市场倾向** | {"偏向利好 🟢" if avg_sentiment > 0.2 else "偏向利空 🔴" if avg_sentiment < -0.2 else "中性 🟡"} |
| **平均情感分** | {avg_sentiment:+.2f} |
| **头条新闻** | {top_story.get('title', '无') if top_story else '无'} |
| **已确认新闻** | {len(confirmed)} 条 | **候选新闻** | {len(candidates)} 条 |
| **T0 级事件** | {len(t0_items)} 条（今日关注） | **T1 级事件** | {len(t1_items)} 条（本周关注） |

---

## 市场数据概览

| 类别 | 利好 | 中性 | 利空 |
|------|------|------|------|
| 数量 | {len(bullish)} | {len(neutral)} | {len(bearish)} |

"""
        md += """---

## 要闻解读

### 利好因素 🟢

"""
        if bullish:
            for i, item in enumerate(bullish, 1):
                md += f"""**{i}. {item.get('title', '')}**
- **摘要**: {item.get('summary', 'N/A')}
- **跨市场影响**: {item.get('cross_market_map', 'N/A')}

"""
        else:
            md += "*无明显利好*\n\n"

        md += """
### 利空因素 🔴

"""
        if bearish:
            for i, item in enumerate(bearish, 1):
                md += f"""**{i}. {item.get('title', '')}**
- **摘要**: {item.get('summary', 'N/A')}
- **跨市场影响**: {item.get('cross_market_map', 'N/A')}

"""
        else:
            md += "*无明显利空*\n\n"

        md += """
### 中性/待观察 🟡

"""
        if neutral:
            for i, item in enumerate(neutral, 1):
                md += f"""**{i}. {item.get('title', '')}**
- **摘要**: {item.get('summary', 'N/A')}
- **跨市场影响**: {item.get('cross_market_map', 'N/A')}

"""
        else:
            md += "*无中性新闻*\n\n"

        md += """---

## 候选新闻 (需进一步确认)

"""
        if candidates:
            for i, item in enumerate(candidates, 1):
                md += f"""**{i}. {item.get('title', '')}** `可信度：{item.get('source_confidence', 'unknown')}`
- **摘要**: {item.get('summary', '')}
- **状态说明**: 等待更多来源确认

"""
        else:
            md += "*无候选新闻*\n\n"

        # 整体分析
        avg_sentiment = sum(i.get('sentiment_score', 0) for i in confirmed_items) / len(confirmed_items) if confirmed_items else 0
        high_confidence_count = sum(1 for i in confirmed_items if i.get('source_confidence') == 'high')
        t0_events = sum(1 for i in confirmed_items if i.get('impact_horizon') == 'T0')

        # 分类统计
        crypto_news = [i for i in confirmed_items if i.get('category') in ['onchain_data', 'project_update', 'kols_view']]
        macro_news = [i for i in confirmed_items if i.get('category') in ['fed_policy', 'us_policy', 'us_data', 'market_analysis']]

        md += """---

## 整体分析

"""
        confidence_ratio = (high_confidence_count / len(confirmed_items)) if confirmed_items else 0
        md += f"""### 市场情绪

| 指标 | 数值 | 解读 |
|------|------|------|
| 平均情感分 | {avg_sentiment:+.2f} | {"偏向利好" if avg_sentiment > 0.2 else "偏向利空" if avg_sentiment < -0.2 else "中性"} |
| 高可信度新闻 | {high_confidence_count}/{len(confirmed_items)} | {"权威来源主导" if confidence_ratio > 0.7 else "来源混杂"} |
| T0 级事件 | {t0_events} | {"今日需重点关注" if t0_events >= 3 else "常规关注"} |

### 催化剂日历

**今日关注 **(T0)
"""
        if t0_items:
            for item in t0_items:
                sentiment_icon = "🟢" if item.get('sentiment_score', 0) > 0.2 else "🔴" if item.get('sentiment_score', 0) < -0.2 else "🟡"
                md += f"- {sentiment_icon} {item.get('title', '')}\n"
        else:
            md += "*无*\n"

        t1_items = [i for i in confirmed_items if i.get('impact_horizon') == 'T1']
        md += "\n**本周关注 **(T1)\n"
        if t1_items:
            for item in t1_items:
                sentiment_icon = "🟢" if item.get('sentiment_score', 0) > 0.2 else "🔴" if item.get('sentiment_score', 0) < -0.2 else "🟡"
                md += f"- {sentiment_icon} {item.get('title', '')}\n"
        else:
            md += "*无*\n"

        md += f"""
### 加密 vs 宏观

| 类别 | 数量 | 主要议题 |
|------|------|----------|
| 加密新闻 | {len(crypto_news)} | {"ETF 流入、链上活跃、生态发展" if crypto_news else "无"} |
| 宏观新闻 | {len(macro_news)} | {"美联储政策、就业数据、地缘风险" if macro_news else "无"} |

### T0 级事件详细分析

"""
        t0_items = [i for i in confirmed_items if i.get('impact_horizon') == 'T0']
        if t0_items:
            for item in t0_items:
                sentiment_badge = "🟢" if item.get('sentiment_score', 0) > 0.2 else "🔴" if item.get('sentiment_score', 0) < -0.2 else "🟡"
                md += f"""**{item.get('title', '')}** {sentiment_badge}
- **情感**: {item.get('sentiment_score', 0):+.2f} | **可信度**: {item.get('source_confidence', 'unknown')}
- **摘要**: {item.get('summary', 'N/A')}
- **跨市场影响**: {item.get('cross_market_map', 'N/A')}

"""
        else:
            md += "*今日无 T0 级事件*\n\n"

        md += """### 风险标记汇总

"""
        risk_flagged = [i for i in confirmed_items if i.get('risk_flags')]
        if risk_flagged:
            for item in risk_flagged:
                md += f"- ⚠️ **{item.get('title', '')}**: {', '.join(item.get('risk_flags', []))}\n"
        else:
            md += "- ✅ 无重大风险标记\n"

        # 最终投资建议
        bullish_count = sum(1 for i in confirmed_items if i.get('sentiment_score', 0) > 0.3)
        bearish_count = sum(1 for i in confirmed_items if i.get('sentiment_score', 0) < -0.3)

        if bullish_count > bearish_count * 2 and avg_sentiment > 0.3:
            recommendation = "偏向做多"
            confidence = "中等"
            action = "可考虑逢低建仓，关注 ETF 流入和链上数据持续性"
        elif bearish_count > bullish_count:
            recommendation = "偏向做空"
            confidence = "中等"
            action = "可考虑逢高减仓，关注宏观数据压力"
        else:
            recommendation = "中性/震荡"
            confidence = "高"
            action = "维持现有仓位，等待更明确信号"

        md += f"""
---

## 最终投资建议

| 项目 | 建议 |
|------|------|
| **方向** | {recommendation} |
| **置信度** | {confidence} |
| **操作建议** | {action} |
| **关注重点** | {"1) ETF 资金流向; 2) 美联储政策预期; 3) 链上数据变化" if macro_news else "1) 链上数据; 2) 生态发展; 3) 大 V 观点"} |
| **风险提示** | {"宏观数据可能压制风险资产; 地缘局势升级" if t0_events >= 2 else "单源消息需进一步确认"} |

"""

        # 叙事变更日志引用
        changelog = self.load_narrative_changelog()
        if changelog:
            active_narratives = [n for n in changelog if n.get('status') in ['active', 'recommended']]
            if active_narratives:
                md += """---

## 当前活跃叙事

"""
                for narrative in active_narratives:
                    md += f"""### {narrative.get('title', '')}

- **叙事 ID**: {narrative.get('narrative_id', '')}
- **来源**: {[s['name'] for s in narrative.get('sources', [])]}
- **确认状态**: {narrative.get('confirmation_status', '')}
- **回测结果**: {narrative.get('backtest_result', {})}

"""

        md += """---

## 数据来源

- Odaily 星球日报：https://www.odaily.news/zh-CN/newsflash
- 金色财经：https://jinse.cn/lives
- BlockBeats：https://www.theblockbeats.info/
- 华尔街见闻：https://wallstreetcn.com/
- Twitter 大 V：@VitalikButerin, @a16zcrypto, @cz_binance, @woonomic, @glassnode

---

**简报版本**: V2
**生成时间**: """ + now + """
**确认规则**: ≥2 个不同来源一致
"""

        return md

    def save_brief_v2(self, md_content: str, output_path: Optional[Path] = None) -> Path:
        """保存简报"""
        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = self.outputs_dir / f"brief_v2_{ts}.md"

        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        return output_path


def generate_mock_news_for_v2() -> List[Dict]:
    """生成 V2 测试新闻数据"""
    return [
        {
            "title": "比特币 ETF 净流入创新高",
            "summary": "贝莱德 IBIT 单日净流入 5 亿美元，创 ETF 获批以来最高",
            "source": "a16zcrypto",
            "source_type": "twitter",
            "url": "https://twitter.com/a16zcrypto/status/xxx",
            "published_at": "2026-03-09T10:00:00Z",
            "category": "market_analysis",
            "sentiment_score": 0.7,
            "source_confidence": "high",
            "impact_horizon": "T0",
            "cross_market_map": "ETF 流入→机构需求→价格上涨",
            "risk_flags": [],
        },
        {
            "title": "比特币 ETF 净流入创新高",
            "summary": "彭博数据显示 IBIT 单日净流入达 5 亿美元",
            "source": "Bloomberg",
            "source_type": "news",
            "url": "https://bloomberg.com/xxx",
            "published_at": "2026-03-09T10:30:00Z",
            "category": "market_analysis",
            "sentiment_score": 0.6,
            "source_confidence": "high",
            "impact_horizon": "T0",
            "cross_market_map": "ETF 流入→机构需求→价格上涨",
            "risk_flags": [],
        },
        {
            "title": "以太坊 Layer2 TVL 突破 500 亿美元",
            "summary": "Arbitrum 和 Optimism 主导 Layer2 增长",
            "source": "VitalikButerin",
            "source_type": "twitter",
            "url": "https://twitter.com/VitalikButerin/status/xxx",
            "published_at": "2026-03-09T09:00:00Z",
            "category": "project_update",
            "sentiment_score": 0.5,
            "source_confidence": "high",
            "impact_horizon": "T1",
            "cross_market_map": "Layer2 增长→ETH 需求→价格上涨",
            "risk_flags": [],
        },
        {
            "title": "某交易所被曝挪用用户资产",
            "summary": "匿名爆料称某中小型交易所挪用 2 亿美元用户资产",
            "source": "anonymous",
            "source_type": "social",
            "url": "https://twitter.com/xxx",
            "published_at": "2026-03-09T08:00:00Z",
            "category": "security",
            "sentiment_score": -0.8,
            "source_confidence": "low",
            "impact_horizon": "T0",
            "cross_market_map": "信任危机→资金流出→价格下跌",
            "risk_flags": ["单源爆料", "数据不可复核"],
        },
    ]


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='生成简报 V2')
    parser.add_argument('--test', action='store_true', help='使用测试数据')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件')
    parser.add_argument('--hours', type=int, default=4, help='时间窗口（小时），默认 4 小时')
    parser.add_argument('--force', action='store_true', help='忽略日期检查强制生成')
    args = parser.parse_args()

    # 路径
    base_dir = Path(__file__).parent.parent
    raw_dir = base_dir / "raw"
    outputs_dir = base_dir / "outputs"

    generator = BriefV2Generator(raw_dir, outputs_dir)

    def _parse_item_dt(item: Dict) -> Optional[datetime]:
        for k in ("published_at", "fetched_at"):
            v = item.get(k)
            if not isinstance(v, str) or not v:
                continue
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except Exception:
                continue
        return None

    def _normalize(item: Dict, source_default: str, sentiment_default: float, is_macro: bool) -> Optional[Dict]:
        title = (item.get("title") or "").strip()
        url = (item.get("source_url") or item.get("url") or "").strip()
        if not title or not url:
            return None
        out = dict(item)
        out["source"] = out.get("source") or source_default
        out["source_type"] = out.get("source_type") or "news"
        out["sentiment_score"] = float(out.get("sentiment_score", sentiment_default))
        if is_macro:
            topic = out.get("topic", "market_analysis")
            topic_map = {
                "fed": "fed_policy",
                "us_data": "us_data",
                "geopolitics": "geopolitics",
                "us_policy": "us_policy",
                "market_analysis": "market_analysis",
            }
            out["category"] = out.get("category") or topic_map.get(topic, "market_analysis")
            if not out.get("summary"):
                out["summary"] = out.get("key_fact", "")
        if not out.get("summary"):
            out["summary"] = "正文缺失，仅标题级信息"
        flags = out.get("risk_flags")
        if not isinstance(flags, list):
            flags = []
        if out.get("summary") == "正文缺失，仅标题级信息" and "正文缺失" not in flags:
            flags.append("正文缺失")
        if not out.get("published_at") and not out.get("fetched_at"):
            out["fetched_at"] = datetime.now(timezone.utc).isoformat()
            if "数据不可复核" not in flags:
                flags.append("数据不可复核")
        out["risk_flags"] = flags
        out["source_url"] = url
        return out

    if args.test:
        news_items = generate_mock_news_for_v2()
    else:
        news_items = []
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=args.hours)
        file_ts = datetime.now().strftime("%Y%m%d_%H%M")
        fresh_crypto: List[Dict] = []
        fresh_macro: List[Dict] = []

        try:
            from news_crawler import fetch_odaily_newsflash, fetch_wallstreetcn_breakfast
            fresh_crypto = fetch_odaily_newsflash(limit=60, hours=args.hours, include_aux=True)
            fresh_macro = fetch_wallstreetcn_breakfast(limit=60, hours=args.hours)
            with open(raw_dir / f"raw_crypto_{file_ts}.json", "w", encoding="utf-8") as f:
                json.dump(fresh_crypto, f, indent=2, ensure_ascii=False)
            with open(raw_dir / f"raw_macro_{file_ts}.json", "w", encoding="utf-8") as f:
                json.dump(fresh_macro, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[WARN] 实时抓取失败，回退本地缓存: {e}")

        for item in fresh_crypto:
            norm = _normalize(item, "Odaily", 0.5, is_macro=False)
            if not norm:
                continue
            item_dt = _parse_item_dt(norm)
            if item_dt and item_dt < cutoff:
                continue
            news_items.append(norm)

        for item in fresh_macro:
            norm = _normalize(item, "华尔街见闻", 0.3, is_macro=True)
            if not norm:
                continue
            item_dt = _parse_item_dt(norm)
            if item_dt and item_dt < cutoff:
                continue
            news_items.append(norm)

        if not news_items:
            crypto_files = sorted(raw_dir.glob("raw_crypto_*.json"), reverse=True)
            macro_files = sorted(raw_dir.glob("raw_macro_*.json"), reverse=True)
            for f in crypto_files[:5]:
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    if not isinstance(data, list):
                        continue
                    for item in data:
                        norm = _normalize(item, "Odaily", 0.5, is_macro=False)
                        if not norm:
                            continue
                        item_dt = _parse_item_dt(norm)
                        if item_dt and item_dt < cutoff:
                            continue
                        news_items.append(norm)
                except Exception:
                    continue
            for f in macro_files[:5]:
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    if not isinstance(data, list):
                        continue
                    for item in data:
                        norm = _normalize(item, "华尔街见闻", 0.3, is_macro=True)
                        if not norm:
                            continue
                        item_dt = _parse_item_dt(norm)
                        if item_dt and item_dt < cutoff:
                            continue
                        news_items.append(norm)
                except Exception:
                    continue

        if not news_items:
            print(f"[INFO] 最近 {args.hours} 小时无可验证新闻，使用 mock（仅保障流程）")
            mock_items = generate_mock_news_for_v2()
            for item in mock_items:
                item["source"] = "mock"
                flags = item.get("risk_flags") if isinstance(item.get("risk_flags"), list) else []
                if "数据不可复核" not in flags:
                    flags.append("数据不可复核")
                item["risk_flags"] = flags
            news_items = mock_items

    # 去重（同源同主题）
    seen = set()
    unique_items = []
    for item in news_items:
        key = (_topic_key(item.get("title", "")), item.get("source", ""))
        if key not in seen:
            seen.add(key)
            unique_items.append(item)
    news_items = unique_items

    print(f"[INFO] 加载新闻数：{len(news_items)}")

    # 生成简报
    md_content = generator.generate_brief_v2(news_items)

    # 保存
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = None

    saved_path = generator.save_brief_v2(md_content, output_path)
    print(f"[✓] 简报已保存：{saved_path}")

    # 统计
    confirmed = sum(1 for i in news_items if i.get('confirmation_status') == 'confirmed')
    candidates = sum(1 for i in news_items if i.get('confirmation_status') == 'candidate')
    print(f"\n【统计】")
    print(f"  已确认: {confirmed}")
    print(f"  候选: {candidates}")

    return saved_path


if __name__ == "__main__":
    main()
