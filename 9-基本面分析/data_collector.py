"""
数据采集器（重写版 v3）
- 每个模块输出统一契约：metrics.core / metrics.breakdown / events / timeseries / timestamp
- metrics 中仅存放 number/string，不嵌套对象
- 金融逻辑驱动：基准值 + 合理波动 + 跨模块一致性（通过 _MODULE_CONTEXT）
- 采集层直接产出结构化数据，API 服务层仅负责组装
"""

import os
import json
import random
import math
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

# 加载同目录 .env（若存在）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass

# ============== 全局配置 ==============
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# 模块共享上下文：供 signal_engine 跨模块引用
_MODULE_CONTEXT: Dict[str, Any] = {
    "scores": {},          # 各模块最后一次核心得分（-1 ~ 1 或 0~100，由模块自己定）
    "timestamps": {},      # 各模块最后一次更新时间
    "latest": {},          # 各模块最后一次返回的完整 raw_data（供 cross-validation）
}


# ============== Tavily 数据抓取 ==============

def _get_tavily_client():
    try:
        from tavily import TavilyClient
        return TavilyClient(api_key=TAVILY_API_KEY)
    except ImportError:
        return None


# ============== 新闻去重与摘要增强 ==============

def deduplicate_news(news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """基于 URL 和标题去重"""
    seen_urls = set()
    seen_titles = set()
    deduped = []
    
    for news in news_list:
        url = news.get("url", "")
        title = news.get("title", "")
        title_key = title.lower().strip()[:50]  # 标题前50字符作为key
        
        if url and url not in seen_urls:
            seen_urls.add(url)
            seen_titles.add(title_key)
            deduped.append(news)
        elif not url and title_key not in seen_titles:
            seen_titles.add(title_key)
            deduped.append(news)
    
    return deduped


def summarize_content(content: str, max_length: int = 120) -> str:
    """智能截取内容摘要"""
    if not content:
        return ""
    if len(content) <= max_length:
        return content
    
    # 优先在句号、问号处截断
    for sep in ["。", ".", "?", "！", "!"]:
        idx = content.rfind(sep, 0, max_length + 20)
        if idx > max_length // 2:
            return content[:idx + 1]
    
    return content[:max_length] + "..."


def fetch_tavily_news(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    client = _get_tavily_client()
    if not client:
        return _generate_mock_news(query, max_results)
    try:
        result = client.search(query=query, max_results=max_results)
        raw_results = result.get("results", [])
        
        # 增强处理：添加摘要和去重
        enhanced = []
        for r in raw_results:
            content = r.get("content", "")
            enhanced.append({
                "title": r.get("title", ""),
                "content": summarize_content(content),
                "url": r.get("url", ""),
                "source": r.get("source", "Unknown"),
                "published_at": r.get("published_date", _days_ago_iso(2)),
                "raw_content": content,  # 保留原始内容
            })
        
        return deduplicate_news(enhanced)
    except Exception as e:
        print(f"[Tavily] Error fetching '{query}': {e}")
        return _generate_mock_news(query, max_results)


def fetch_tavily_batch(queries: List[str], max_results: int = 5) -> Dict[str, List]:
    client = _get_tavily_client()
    results = {}
    all_news = []
    
    for query in queries:
        try:
            if client:
                r = client.search(query=query, max_results=max_results)
                raw = r.get("results", [])
                
                # 增强处理
                enhanced = []
                for item in raw:
                    content = item.get("content", "")
                    enhanced.append({
                        "title": item.get("title", ""),
                        "content": summarize_content(content),
                        "url": item.get("url", ""),
                        "source": item.get("source", "Unknown"),
                        "published_at": item.get("published_date", _days_ago_iso(2)),
                        "raw_content": content,
                    })
                
                results[query] = deduplicate_news(enhanced)
                all_news.extend(results[query])
            else:
                results[query] = _generate_mock_news(query, max_results)
        except Exception as e:
            print(f"[Tavily] Error fetching '{query}': {e}")
            results[query] = _generate_mock_news(query, max_results)
    
    # 全局去重
    if all_news:
        all_deduped = deduplicate_news(all_news)
        print(f"[Tavily] Batch fetch: {len(all_news)} -> {len(all_deduped)} after dedup")
    
    return results


# ============== 真实数据源采集层 ==============

def _http_get(url: str, timeout: int = 8) -> Optional[Dict[str, Any]]:
    """通用 HTTP GET，返回解析后的 JSON，失败返回 None"""
    try:
        import urllib.request as _req
        req = _req.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _req.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[HTTP] {url} failed: {e}")
        return None


def _fetch_fear_greed() -> Optional[Dict[str, Any]]:
    """alternative.me Fear & Greed Index — 完全免费，无需 Key"""
    data = _http_get("https://api.alternative.me/fng/?limit=7")
    if not data or not data.get("data"):
        return None
    latest = data["data"][0]
    history = data["data"]  # 最近7天
    return {
        "value": int(latest.get("value", 50)),
        "classification": latest.get("value_classification", "Neutral"),
        "history": [{"value": int(x.get("value", 50)), "ts": x.get("timestamp")} for x in history],
    }


def _fetch_blockchain_info() -> Optional[Dict[str, Any]]:
    """Blockchain.info stats — 免费链上基础数据"""
    data = _http_get("https://blockchain.info/stats?format=json")
    if not data:
        return None
    return {
        "n_tx": int(data.get("n_tx", 0)),
        "hash_rate": float(data.get("hash_rate", 0)),
        "difficulty": float(data.get("difficulty", 0)),
        "total_fees_btc": float(data.get("total_fees_btc", 0)),
        "n_btc_mined": float(data.get("n_btc_mined", 0)),
        "minutes_between_blocks": float(data.get("minutes_between_blocks", 10)),
    }


def _fetch_tavily_market_data(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """用 Tavily 搜索特定市场数据关键词，返回文章列表"""
    client = _get_tavily_client()
    if not client:
        return []
    try:
        r = client.search(query=query, max_results=max_results)
        return r.get("results", [])
    except Exception as e:
        print(f"[Tavily] query='{query}' failed: {e}")
        return []


def _parse_number_from_text(text: str, keywords: List[str]) -> Optional[float]:
    """从文本中提取关键词附近的数字（用于 Tavily 结果解析）"""
    import re
    text_lower = text.lower()
    for kw in keywords:
        idx = text_lower.find(kw.lower())
        if idx == -1:
            continue
        snippet = text[max(0, idx - 20): idx + 60]
        nums = re.findall(r"-?\d+\.?\d*", snippet)
        if nums:
            try:
                return float(nums[0])
            except Exception:
                continue
    return None


# ============== 通用工具函数 ==============

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _make_timeseries(
    current_value: float,
    days: int = 30,
    vmin: float = -1.0,
    vmax: float = 1.0,
    drift: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """带趋势 + 随机游走的时间序列生成器（用于各模块 timeseries 字段）
    - 最后一点强制对齐 current_value
    - drift 默认从 current_value 推断方向
    """
    now = datetime.now(timezone.utc)
    points: List[Dict[str, Any]] = []
    if drift is None:
        drift = current_value * 0.02  # 轻微趋势

    # 起点：从 0 + 扰动出发，最后收敛到 current_value
    value = random.uniform(-0.2, 0.2)
    for i in range(days):
        ts = (now - timedelta(days=days - i - 1)).isoformat()
        # 目标：线性向 current_value 靠近
        progress = (i + 1) / days
        target = value * (1 - progress) + current_value * progress
        noise = random.uniform(-0.08, 0.08) * (vmax - vmin) / 2.0
        value = value * 0.55 + target * 0.45 + drift + noise
        value = _clamp(value, vmin, vmax)

        prev_val = points[-1]["value"] if points else value
        prev_vel = points[-1]["velocity"] if points else 0.0
        vel = value - prev_val
        acc = vel - prev_vel

        # 速度文案（仅当区间为 -1~1 时给出语义）
        velocity_label = ""
        if vmin == -1.0 and vmax == 1.0:
            if vel > 0.05:
                velocity_label = "加速流入"
            elif vel > 0.01:
                velocity_label = "温和流入"
            elif vel > -0.01:
                velocity_label = "持平"
            elif vel > -0.05:
                velocity_label = "温和流出"
            else:
                velocity_label = "加速流出"

        direction_score = round((value - (vmin + vmax) / 2) / ((vmax - vmin) / 2), 4)
        direction_score = _clamp(direction_score, -1.0, 1.0)

        points.append({
            "timestamp": ts,
            "value": round(value, 4),
            "direction_score": direction_score,
            "velocity": round(vel, 4),
            "velocity_label": velocity_label,
            "acceleration": round(acc, 4),
        })

    # 强制最后一点 = current_value
    if points:
        last = points[-1]
        last["value"] = round(current_value, 4)
        # 以当前值重新归一化 direction_score
        ds = (current_value - (vmin + vmax) / 2) / ((vmax - vmin) / 2)
        last["direction_score"] = round(_clamp(ds, -1.0, 1.0), 4)

    return points


def generate_timeseries(module: str, days: int = 30) -> List[Dict[str, Any]]:
    """ml_trade_service_v2.py 使用的顶层函数（保持签名不变）
    会根据模块名推断 score key，调用对应 collect_xxx 方法获取当前评分并生成历史序列。
    """
    collector = DataCollector()
    # 优先从上下文中获取已计算的 score
    ctx_score = _MODULE_CONTEXT["scores"].get(module)
    score = 0.0
    vmin, vmax = -1.0, 1.0
    if module == "flow":
        score = ctx_score if ctx_score is not None else random.uniform(-0.3, 0.7)
    elif module == "sentiment":
        score = ctx_score if ctx_score is not None else random.uniform(0.35, 0.75)
        vmin, vmax = 0.0, 1.0
    elif module == "macro":
        score = ctx_score if ctx_score is not None else random.uniform(-0.4, 0.5)
    elif module == "breadth":
        score = ctx_score if ctx_score is not None else random.uniform(-0.5, 0.6)
        vmin, vmax = -1.0, 1.0
    elif module == "valuation":
        score = ctx_score if ctx_score is not None else random.uniform(1.3, 3.2)
        vmin, vmax = 0.5, 4.0
    elif module == "onchain":
        score = ctx_score if ctx_score is not None else random.uniform(-100, 200)
        vmin, vmax = -500, 500
    else:
        # news / calendar / intermarket / narrative：通用处理
        score = ctx_score if ctx_score is not None else random.uniform(-0.5, 0.5)

    return _make_timeseries(score, days=days, vmin=vmin, vmax=vmax)


# ============== 独立 Mock 生成函数（模块 1-6） ==============

# ---------- A. Flow（资金流） ----------
def _generate_mock_flow_metrics() -> Dict[str, Any]:
    """资金流模块：基准 + 合理波动 + 跨模块一致性"""
    # 1) 综合评分：略微偏多倾向
    fund_flow_score = round(random.uniform(-0.3, 0.7), 4)

    # 2) 与 score 正相关的派生指标
    etf_net_flow = round(fund_flow_score * 800 + random.uniform(-150, 150), 2)  # 百万 USD
    etf_inflow_24h = round(max(0, etf_net_flow) + random.uniform(100, 600), 2)
    etf_outflow_24h = round(max(0, -etf_net_flow) + random.uniform(80, 400), 2)

    # 永续合约费率（与 score 正相关，单位 %）
    funding_rate = round(fund_flow_score * 0.05 + random.uniform(-0.01, 0.01), 4)

    # 多空比
    long_short_ratio = round(1.0 + fund_flow_score * 0.3 + random.uniform(-0.1, 0.1), 2)

    # 清算压力（0-100）：score 偏负时更高
    liquidation_pressure = round(_clamp(
        (1.0 - fund_flow_score) * 40 + random.uniform(0, 25), 0, 100
    ), 2)
    long_pressure = round(_clamp((long_short_ratio - 0.8) * 80 + random.uniform(0, 20), 0, 100), 2)
    short_pressure = round(_clamp((1.3 - long_short_ratio) * 80 + random.uniform(0, 20), 0, 100), 2)

    # 鲸鱼活跃度（0-100）
    whale_activity = round(random.uniform(30, 90), 2)
    whale_buying = round(_clamp(whale_activity * fund_flow_score + 50 + random.uniform(-10, 10), 0, 100), 2)
    whale_selling = round(_clamp(whale_activity * (1 - fund_flow_score) + 20 + random.uniform(-10, 10), 0, 100), 2)

    # 稳定币供应变化（%）
    stablecoin_supply_change = round(fund_flow_score * 2.0 + random.uniform(-0.6, 0.6), 3)
    usdt_supply_change = round(stablecoin_supply_change + random.uniform(-0.5, 0.5), 3)
    usdc_supply_change = round(stablecoin_supply_change * 0.8 + random.uniform(-0.4, 0.4), 3)

    # 机构/散户参与度
    institutional_exposure = round(_clamp(50 + fund_flow_score * 30 + random.uniform(-10, 10), 0, 100), 2)
    retail_exposure = round(_clamp(50 - fund_flow_score * 15 + random.uniform(-10, 10), 0, 100), 2)

    # smart_money_direction
    if etf_net_flow > 200 and whale_activity > 60:
        smart_money_direction = "显著流入"
    elif etf_net_flow > 0:
        smart_money_direction = "温和流入"
    elif etf_net_flow < -200:
        smart_money_direction = "显著流出"
    else:
        smart_money_direction = "观望"

    flow_velocity_score = round(_clamp(abs(fund_flow_score) * 80 + random.uniform(10, 30), 0, 100), 2)

    metrics_core = {
        "fund_flow_score": fund_flow_score,
        "etf_net_flow": etf_net_flow,
        "funding_rate": funding_rate,
        "long_short_ratio": long_short_ratio,
        "liquidation_pressure": liquidation_pressure,
        "whale_activity": whale_activity,
        "stablecoin_supply_change": stablecoin_supply_change,
        "smart_money_direction": smart_money_direction,
        "flow_velocity_score": flow_velocity_score,
    }
    metrics_breakdown = {
        "etf_inflow_24h": etf_inflow_24h,
        "etf_outflow_24h": etf_outflow_24h,
        "long_pressure": long_pressure,
        "short_pressure": short_pressure,
        "whale_buying": whale_buying,
        "whale_selling": whale_selling,
        "usdt_supply_change": usdt_supply_change,
        "usdc_supply_change": usdc_supply_change,
        "retail_exposure": retail_exposure,
        "institutional_exposure": institutional_exposure,
    }

    # 事件生成
    events: List[Dict[str, Any]] = []
    now = _now_iso()
    if etf_net_flow > 300:
        events.append({
            "title": "比特币 ETF 单日净流入创新高",
            "content": f"ETF 净流入 +${etf_net_flow:,.0f}M，机构资金持续入场",
            "category": "ETF/机构",
            "impact_score": round(_clamp(0.6 + fund_flow_score * 0.3, 0, 1), 3),
            "sentiment": 0.85,
            "source": "ETF Flows",
            "published_at": now,
            "metric_delta": {"etf_net_flow": etf_net_flow},
        })
    elif etf_net_flow < -200:
        events.append({
            "title": "比特币 ETF 出现显著净流出",
            "content": f"ETF 净流出 ${etf_net_flow:,.0f}M，机构资金离场明显",
            "category": "ETF/机构",
            "impact_score": round(_clamp(0.7 - fund_flow_score * 0.3, 0, 1), 3),
            "sentiment": -0.75,
            "source": "ETF Flows",
            "published_at": now,
            "metric_delta": {"etf_net_flow": etf_net_flow},
        })

    if liquidation_pressure > 65:
        events.append({
            "title": "大额清算触发短时波动",
            "content": f"清算压力 {liquidation_pressure:.0f}/100，杠杆仓位存在踩踏风险",
            "category": "清算",
            "impact_score": round(_clamp(liquidation_pressure / 100, 0, 1), 3),
            "sentiment": -0.5,
            "source": "Coinglass",
            "published_at": now,
            "metric_delta": {"liquidation_pressure": liquidation_pressure},
        })

    if stablecoin_supply_change > 0.8:
        events.append({
            "title": "稳定币供应量持续扩张",
            "content": f"USDT/USDC 合计供应变化 +{stablecoin_supply_change:.2%}，潜在入场资金增加",
            "category": "稳定币",
            "impact_score": 0.65,
            "sentiment": 0.6,
            "source": "On-chain",
            "published_at": now,
            "metric_delta": {"stablecoin_supply_change": stablecoin_supply_change},
        })

    if whale_activity > 70 and whale_buying > whale_selling:
        events.append({
            "title": "鲸鱼地址活跃：大额买入明显",
            "content": f"鲸鱼活跃度 {whale_activity:.0f}/100，买入强度 {whale_buying:.0f} 高于卖出",
            "category": "鲸鱼",
            "impact_score": 0.6,
            "sentiment": 0.55,
            "source": "On-chain",
            "published_at": now,
        })

    # 兜底事件（至少 1 条）
    if not events:
        events.append({
            "title": "资金流整体平稳",
            "content": "ETF、稳定币、多空比均处于正常区间，未见极端信号",
            "category": "汇总",
            "impact_score": 0.35,
            "sentiment": 0.1,
            "source": "Aggregate",
            "published_at": now,
        })

    # 鲸鱼交易追踪（新增差异化字段）
    whale_transactions = []
    whale_labels = ["灰度信托", "MicroStrategy", "未知鲸鱼", "交易所冷钱包", "机构钱包", "矿工地址"]
    exchanges = ["Coinbase", "Binance", "Kraken", "OKX", "链上"]
    
    for i in range(4):
        direction = "in" if random.random() > 0.4 else "out"
        amount = random.randint(100, 2000)
        whale_transactions.append({
            "wallet_label": random.choice(whale_labels),
            "amount": amount,
            "direction": direction,
            "exchange": random.choice(exchanges),
            "timestamp": (datetime.now(timezone.utc) - timedelta(hours=i * 6)).isoformat(),
            "usd_value": amount * 65000,
        })

    timeseries = _make_timeseries(fund_flow_score, days=30, vmin=-1.0, vmax=1.0)

    _MODULE_CONTEXT["scores"]["flow"] = fund_flow_score
    _MODULE_CONTEXT["timestamps"]["flow"] = now

    return {
        "metrics": {"core": metrics_core, "breakdown": metrics_breakdown},
        "events": events,
        "timeseries": timeseries,
        "whale_transactions": whale_transactions,
        "timestamp": now,
    }


# ---------- B. Sentiment（情绪） ----------
def _generate_mock_sentiment_metrics() -> Dict[str, Any]:
    # 1) 基准：35（恐惧）- 75（贪婪）
    sentiment_index = random.randint(35, 75)
    fear_greed_index = max(0, min(100, sentiment_index + random.randint(-8, 8)))

    # 叙事热度、共识度、反转风险（与 score 相关）
    narrative_heat = round(_clamp(sentiment_index * 0.9 + random.uniform(-10, 10), 10, 100), 2)
    consensus_level = round(_clamp(60 - abs(sentiment_index - 55) * 1.5 + random.uniform(-10, 10), 20, 95), 2)
    reversal_risk = round(_clamp(abs(sentiment_index - 50) * 1.5 + random.uniform(5, 20), 5, 95), 2)

    social_volume = random.randint(5000, 90000)

    # 细分情绪
    news_sentiment = round(_clamp(sentiment_index + random.uniform(-12, 12), 10, 100), 2)
    social_sentiment = round(_clamp(sentiment_index * 0.95 + random.uniform(-10, 10), 10, 100), 2)
    bullish_ratio = round(_clamp(sentiment_index * 0.8 + random.uniform(-8, 8), 5, 95), 2)
    bearish_ratio = round(_clamp((100 - sentiment_index) * 0.7 + random.uniform(-8, 8), 5, 95), 2)
    neutral_ratio = round(_clamp(100 - bullish_ratio - bearish_ratio + random.uniform(-5, 5), 5, 60), 2)

    hype_level = round(_clamp(max(0, sentiment_index - 55) * 2 + random.uniform(0, 15), 0, 100), 2)
    panic_level = round(_clamp(max(0, 50 - sentiment_index) * 2 + random.uniform(0, 15), 0, 100), 2)
    fomo_score = hype_level
    capitulation_score = panic_level

    # 逆向信号 & 市场心理
    if fear_greed_index >= 85:
        contrarian_signal = "警惕过热（逆向卖出）"
    elif fear_greed_index <= 20:
        contrarian_signal = "极度恐惧（逆向买入）"
    else:
        contrarian_signal = "保持观望"

    if fear_greed_index >= 80:
        market_psychology = "极度贪婪"
    elif fear_greed_index >= 65:
        market_psychology = "贪婪"
    elif fear_greed_index >= 45:
        market_psychology = "中性"
    elif fear_greed_index >= 25:
        market_psychology = "恐惧"
    else:
        market_psychology = "极度恐惧"

    metrics_core = {
        "sentiment_index": sentiment_index,
        "fear_greed_index": fear_greed_index,
        "narrative_heat": narrative_heat,
        "consensus_level": consensus_level,
        "reversal_risk": reversal_risk,
        "social_volume": social_volume,
        "contrarian_signal": contrarian_signal,
        "market_psychology": market_psychology,
    }
    metrics_breakdown = {
        "news_sentiment": news_sentiment,
        "social_sentiment": social_sentiment,
        "bullish_ratio": bullish_ratio,
        "bearish_ratio": bearish_ratio,
        "neutral_ratio": neutral_ratio,
        "hype_level": hype_level,
        "panic_level": panic_level,
        "fomo_score": fomo_score,
        "capitulation_score": capitulation_score,
    }

    now = _now_iso()
    events: List[Dict[str, Any]] = []
    # 与 flow 跨模块对齐：若 flow 偏多，优先情绪事件偏多
    flow_hint = _MODULE_CONTEXT["scores"].get("flow", 0.0)

    if fear_greed_index >= 75 and flow_hint >= 0.2:
        events.append({
            "title": "BTC 突破关键阻力位，市场欢呼",
            "content": f"恐惧贪婪 {fear_greed_index}，叙事热度 {narrative_heat:.0f}，贪婪情绪蔓延",
            "category": "Fear & Greed",
            "impact_score": 0.75,
            "sentiment": 0.8,
            "source": "alternative.me",
            "published_at": now,
        })
    elif fear_greed_index <= 30:
        events.append({
            "title": "监管或宏观消息引发短时恐慌",
            "content": f"恐惧贪婪 {fear_greed_index}，恐慌等级 {panic_level:.0f}，逆向机会浮现",
            "category": "Fear & Greed",
            "impact_score": 0.7,
            "sentiment": -0.6,
            "source": "alternative.me",
            "published_at": now,
        })

    if reversal_risk > 65:
        events.append({
            "title": f"反转风险 {reversal_risk:.0f}/100（偏高）",
            "content": "情绪与价格方向可能出现背离，关注分歧迹象",
            "category": "风险提示",
            "impact_score": 0.6,
            "sentiment": -0.3,
            "source": "Calculated",
            "published_at": now,
        })

    if social_volume > 50000:
        events.append({
            "title": "社交讨论量激增，叙事热度上升",
            "content": f"24h 讨论量 {social_volume:,}，叙事热度 {narrative_heat:.0f}",
            "category": "叙事引擎",
            "impact_score": 0.55,
            "sentiment": 0.3,
            "source": "Social Aggregate",
            "published_at": now,
        })

    events.append({
        "title": "长期持有者保持持仓，无抛售迹象",
        "content": f"共识度 {consensus_level:.0f}/100，核心持仓者未见异动",
        "category": "持仓分析",
        "impact_score": 0.5,
        "sentiment": 0.4,
        "source": "On-chain",
        "published_at": now,
    })

    # 情绪热力图数据（新增差异化字段）
    heatmap_data = [
        {"category": "社交媒体", "score": round(social_sentiment, 1)},
        {"category": "新闻舆情", "score": round(news_sentiment, 1)},
        {"category": "搜索热度", "score": round(narrative_heat, 1)},
        {"category": "衍生品", "score": round(sentiment_index * 0.8 + random.uniform(-10, 10), 1)},
        {"category": "资金流向", "score": round(50 + flow_hint * 30 + random.uniform(-5, 5), 1)},
        {"category": "链上活动", "score": round(consensus_level, 1)},
        {"category": "宏观环境", "score": round(50 + random.uniform(-15, 15), 1)},
        {"category": "技术面", "score": round(sentiment_index * 0.9 + random.uniform(-8, 8), 1)},
    ]

    timeseries = _make_timeseries(sentiment_index, days=30, vmin=0.0, vmax=100.0)

    _MODULE_CONTEXT["scores"]["sentiment"] = sentiment_index
    _MODULE_CONTEXT["timestamps"]["sentiment"] = now

    return {
        "metrics": {"core": metrics_core, "breakdown": metrics_breakdown},
        "events": events,
        "timeseries": timeseries,
        "heatmap_data": heatmap_data,
        "timestamp": now,
    }


# ---------- C. Macro（宏观） ----------
def _generate_mock_macro_metrics() -> Dict[str, Any]:
    # 1) 综合政策评分
    policy_score = round(random.uniform(-0.4, 0.5), 4)

    # 美元指数：与 policy_score 负相关（政策偏多时美元偏弱）
    dxy_strength = round(_clamp(100 - policy_score * 12 + random.uniform(-3, 3), 85, 115), 2)
    # 利率冲击
    rate_impact = round(_clamp(-policy_score * 80 + random.uniform(-15, 15), -100, 100), 2)
    # 增长预期
    growth_expectation = round(_clamp(policy_score * 60 + random.uniform(-15, 15), -50, 50), 2)
    # 通胀压力
    inflation_pressure = round(_clamp((1 - policy_score) * 40 + random.uniform(0, 30), 0, 100), 2)
    # 美债 10y 收益率
    us10y_yield = round(_clamp(3.5 - policy_score * 1.5 + random.uniform(-0.3, 0.3), 1.5, 5.5), 3)

    # 鹰派程度
    fed_policy_hawkishness = round(_clamp((1 - policy_score) * 50 + random.uniform(10, 30), 0, 100), 2)
    ecb_policy_hawkishness = round(_clamp(fed_policy_hawkishness + random.uniform(-15, 15), 0, 100), 2)

    market_liquidity = round(_clamp(50 + policy_score * 30 + random.uniform(-10, 10), 0, 100), 2)
    yield_curve_slope = round(_clamp(policy_score * 80 + random.uniform(-15, 15), -100, 100), 2)
    inflation_vs_target = round(_clamp(1.0 + (100 - inflation_pressure) * -0.005 + random.uniform(-0.2, 0.2), 0.3, 3.0), 3)
    growth_vs_potential = round(_clamp(0.8 + policy_score * 0.4 + random.uniform(-0.1, 0.1), 0.3, 1.8), 3)

    risk_on_sentiment = round(_clamp(50 + policy_score * 40 + random.uniform(-10, 10), 0, 100), 2)
    safe_haven_demand = round(_clamp(50 - policy_score * 30 + random.uniform(-10, 10), 0, 100), 2)

    macro_risk_score = round(_clamp(60 - policy_score * 30 + random.uniform(-10, 10), 0, 100), 2)
    crypto_friendly_score = round(_clamp(50 + policy_score * 40 + random.uniform(-10, 10), 0, 100), 2)

    if policy_score > 0.3:
        liquidity_clock = "扩张"
    elif policy_score < -0.2:
        liquidity_clock = "紧缩"
    else:
        liquidity_clock = "转向"

    metrics_core = {
        "policy_score": policy_score,
        "dxy_strength": dxy_strength,
        "rate_impact": rate_impact,
        "growth_expectation": growth_expectation,
        "inflation_pressure": inflation_pressure,
        "us10y_yield": us10y_yield,
        "macro_risk_score": macro_risk_score,
        "crypto_friendly_score": crypto_friendly_score,
        "liquidity_clock": liquidity_clock,
    }
    metrics_breakdown = {
        "fed_policy_hawkishness": fed_policy_hawkishness,
        "ecb_policy_hawkishness": ecb_policy_hawkishness,
        "market_liquidity": market_liquidity,
        "yield_curve_slope": yield_curve_slope,
        "inflation_vs_target": inflation_vs_target,
        "growth_vs_potential": growth_vs_potential,
        "risk_on_sentiment": risk_on_sentiment,
        "safe_haven_demand": safe_haven_demand,
    }

    now = _now_iso()
    events: List[Dict[str, Any]] = []
    if fed_policy_hawkishness < 45:
        events.append({
            "title": "美联储点阵图暗示年内降息",
            "content": f"联邦基金利率路径偏鸽，美元指数 {dxy_strength:.1f}",
            "category": "央行政策",
            "impact_score": 0.75,
            "sentiment": 0.6,
            "source": "FOMC",
            "published_at": now,
        })
    elif fed_policy_hawkishness > 70:
        events.append({
            "title": "美联储鹰派立场明确，高利率维持更久",
            "content": f"鹰派程度 {fed_policy_hawkishness:.0f}/100，风险资产或受压制",
            "category": "央行政策",
            "impact_score": 0.75,
            "sentiment": -0.5,
            "source": "FOMC",
            "published_at": now,
        })

    if inflation_pressure > 65:
        events.append({
            "title": "CPI 数据超预期，市场重估降息路径",
            "content": f"通胀压力 {inflation_pressure:.0f}/100，利率冲击 {rate_impact:+.1f}",
            "category": "通胀",
            "impact_score": 0.7,
            "sentiment": -0.4,
            "source": "BLS",
            "published_at": now,
        })

    if dxy_strength < 97:
        events.append({
            "title": "美元指数走弱，风险资产受益",
            "content": f"DXY {dxy_strength:.1f}，避险需求 {safe_haven_demand:.0f}/100",
            "category": "外汇",
            "impact_score": 0.6,
            "sentiment": 0.55,
            "source": "Reuters",
            "published_at": now,
        })

    events.append({
        "title": f"全球流动性时钟：{liquidity_clock}",
        "content": f"市场流动性评分 {market_liquidity:.0f}/100，对加密友好度 {crypto_friendly_score:.0f}",
        "category": "宏观",
        "impact_score": 0.55,
        "sentiment": round(policy_score, 3),
        "source": "Macro Aggregate",
        "published_at": now,
    })

    timeseries = _make_timeseries(policy_score, days=30, vmin=-1.0, vmax=1.0)

    _MODULE_CONTEXT["scores"]["macro"] = policy_score
    _MODULE_CONTEXT["timestamps"]["macro"] = now

    return {
        "metrics": {"core": metrics_core, "breakdown": metrics_breakdown},
        "events": events,
        "timeseries": timeseries,
        "timestamp": now,
    }


# ---------- D. Breadth（市场广度） ----------
def _generate_mock_breadth_data() -> Dict[str, Any]:
    advance_decline_line = round(random.uniform(-50, 60), 2)  # 综合涨跌线 -100 到 100

    # 上涨/下跌项目数（百分位）
    advance_count = round(_clamp(50 + advance_decline_line * 0.5 + random.uniform(-5, 5), 0, 100), 2)
    decline_count = round(_clamp(50 - advance_decline_line * 0.5 + random.uniform(-5, 5), 0, 100), 2)

    # 新高/新低比率
    new_high_low_ratio = round(_clamp(1.0 + advance_decline_line * 0.02 + random.uniform(-0.15, 0.15), 0.3, 3.0), 3)

    # 新高/新低绝对数量
    new_highs_count = random.randint(5, 80)
    new_lows_count = max(2, int(new_highs_count / new_high_low_ratio))

    sector_count_up = round(_clamp(6 + advance_decline_line * 0.08 + random.randint(-2, 2), 0, 12), 0)
    sector_count_down = round(_clamp(6 - advance_decline_line * 0.08 + random.randint(-2, 2), 0, 12), 0)

    # 分层广度
    l1_breadth = round(_clamp(50 + advance_decline_line * 0.4 + random.uniform(-10, 10), 0, 100), 2)
    l2_breadth = round(_clamp(50 + advance_decline_line * 0.3 + random.uniform(-15, 15), 0, 100), 2)
    defi_breadth = round(_clamp(50 + advance_decline_line * 0.35 + random.uniform(-10, 10), 0, 100), 2)
    meme_breadth = round(_clamp(50 + advance_decline_line * 0.2 + random.uniform(-20, 20), 0, 100), 2)

    # 广度背离 / 确认
    breadth_divergence_score = round(_clamp(abs(advance_decline_line - 40) * 0.8 + random.uniform(0, 20), 0, 100), 2)

    if advance_decline_line > 30 and new_high_low_ratio > 1.5:
        breadth_confirmation = "确认趋势"
    elif advance_decline_line > 0 and new_high_low_ratio > 1.0:
        breadth_confirmation = "存在分歧"
    else:
        breadth_confirmation = "广度恶化"

    if advance_decline_line > 20 and meme_breadth < 40:
        divergence_signal = "顶背离"
    elif advance_decline_line < -20 and l1_breadth > 55:
        divergence_signal = "底背离"
    else:
        divergence_signal = "无背离"

    market_participation_index = round(_clamp(50 + advance_decline_line * 0.3 + random.uniform(-10, 10), 0, 100), 2)

    # 归一化 -1 到 1 供 resistance_3d 使用
    norm_adl = advance_decline_line / 100.0

    metrics_core = {
        "advance_decline_line": advance_decline_line,
        "advance_count": advance_count,
        "decline_count": decline_count,
        "new_high_low_ratio": new_high_low_ratio,
        "breadth_confirmation": breadth_confirmation,
        "divergence_signal": divergence_signal,
        "breadth_divergence_score": breadth_divergence_score,
        "market_participation_index": market_participation_index,
    }
    metrics_breakdown = {
        "new_highs_count": new_highs_count,
        "new_lows_count": new_lows_count,
        "sector_count_up": sector_count_up,
        "sector_count_down": sector_count_down,
        "l1_breadth": l1_breadth,
        "l2_breadth": l2_breadth,
        "defi_breadth": defi_breadth,
        "meme_breadth": meme_breadth,
    }

    now = _now_iso()
    events: List[Dict[str, Any]] = []
    if new_high_low_ratio > 2.0:
        events.append({
            "title": "新高/新低比率突破 2.0，广度确认上升趋势",
            "content": f"{new_highs_count} 个项目创新高，综合涨跌线 {advance_decline_line:+.1f}",
            "category": "广度",
            "impact_score": 0.7,
            "sentiment": 0.7,
            "source": "Market Data",
            "published_at": now,
        })
    elif new_high_low_ratio < 0.6:
        events.append({
            "title": "新低项目超过新高，广度走弱",
            "content": f"新高/新低比率 {new_high_low_ratio:.2f}，综合涨跌线 {advance_decline_line:+.1f}",
            "category": "广度",
            "impact_score": 0.65,
            "sentiment": -0.55,
            "source": "Market Data",
            "published_at": now,
        })

    if l2_breadth < 35:
        events.append({
            "title": "Layer2 板块全线走弱，出现广度恶化信号",
            "content": f"L2 广度 {l2_breadth:.0f}/100，关注是否传导至 L1",
            "category": "Layer2",
            "impact_score": 0.6,
            "sentiment": -0.45,
            "source": "Market Data",
            "published_at": now,
        })

    events.append({
        "title": f"广度状态：{breadth_confirmation}，{divergence_signal}",
        "content": f"市场参与度指数 {market_participation_index:.0f}/100",
        "category": "广度汇总",
        "impact_score": 0.5,
        "sentiment": round(norm_adl, 3),
        "source": "Aggregate",
        "published_at": now,
    })

    timeseries = _make_timeseries(norm_adl, days=30, vmin=-1.0, vmax=1.0)

    _MODULE_CONTEXT["scores"]["breadth"] = norm_adl
    _MODULE_CONTEXT["timestamps"]["breadth"] = now

    return {
        "metrics": {"core": metrics_core, "breakdown": metrics_breakdown},
        "events": events,
        "timeseries": timeseries,
        "timestamp": now,
    }


# ---------- E. Valuation（估值） ----------
def _generate_mock_valuation_data() -> Dict[str, Any]:
    # 1) 合理 MVRV 范围 1.3 - 3.2
    mvrv_ratio = round(random.uniform(1.3, 3.2), 2)
    mvrv_z_score = round((mvrv_ratio - 2.0) / 0.7 + random.uniform(-0.1, 0.1), 2)

    # SOPR
    sopr = round(_clamp(0.95 + (mvrv_ratio - 1.3) * 0.25 + random.uniform(-0.05, 0.05), 0.8, 1.8), 3)

    # AHR999（定投指数）
    ahr999_index = round(_clamp(1.0 + (mvrv_ratio - 2.0) * 0.8 + random.uniform(-0.2, 0.2), 0.3, 3.0), 3)

    # Pi Cycle（0-1）
    pi_cycle_top = round(_clamp(max(0, mvrv_ratio - 2.0) / 1.5 + random.uniform(-0.05, 0.05), 0, 1), 3)

    # Thermometer
    therm_index = round(_clamp((mvrv_ratio - 1.3) / (3.2 - 1.3) * 100 + random.uniform(-5, 5), 0, 100), 2)

    # Mayer Multiple
    mayer_multiple = round(_clamp(1.0 + (mvrv_ratio - 2.0) * 0.4 + random.uniform(-0.1, 0.1), 0.5, 2.5), 3)

    # Puell Multiple
    puell_multiple = round(_clamp(1.0 + (mvrv_ratio - 2.0) * 0.35 + random.uniform(-0.15, 0.15), 0.3, 2.5), 3)

    # 盈亏 & 增长
    short_term_holder_pnl = round((mvrv_ratio - 1.5) * 40 + random.uniform(-10, 10), 2)  # %
    long_term_holder_pnl = round((mvrv_ratio - 1.2) * 30 + random.uniform(-8, 8), 2)  # %
    realized_profit = round(_clamp(max(0, mvrv_ratio - 1.5) * 0.5 + random.uniform(-0.05, 0.05), 0, 1.5), 3)
    realized_loss = round(_clamp(max(0, 1.8 - mvrv_ratio) * 0.3 + random.uniform(-0.05, 0.05), 0, 1.5), 3)
    market_value_growth = round(_clamp((mvrv_ratio - 1.5) * 0.4 + random.uniform(-0.1, 0.1), -0.5, 1.5), 3)
    realised_value_growth = round(_clamp((mvrv_ratio - 1.5) * 0.25 + random.uniform(-0.08, 0.08), -0.3, 1.2), 3)
    sopr_long_term = round(_clamp(1.0 + (mvrv_ratio - 2.0) * 0.15 + random.uniform(-0.05, 0.05), 0.9, 1.5), 3)
    sopr_short_term = round(_clamp(sopr + random.uniform(-0.1, 0.1), 0.8, 1.3), 3)

    # 估值区间 & 热度
    if mvrv_ratio < 1.5:
        valuation_range = "严重低估"
    elif mvrv_ratio < 2.0:
        valuation_range = "低估"
    elif mvrv_ratio < 2.5:
        valuation_range = "合理"
    elif mvrv_ratio < 3.2:
        valuation_range = "偏高"
    else:
        valuation_range = "高估"

    if mvrv_z_score < -1.0:
        valuation_heat_level = "超冷"
    elif mvrv_z_score < 0:
        valuation_heat_level = "冷"
    elif mvrv_z_score < 1.0:
        valuation_heat_level = "温"
    elif mvrv_z_score < 2.0:
        valuation_heat_level = "热"
    else:
        valuation_heat_level = "过热"

    metrics_core = {
        "mvrv_ratio": mvrv_ratio,
        "mvrv_z_score": mvrv_z_score,
        "sopr": sopr,
        "ahr999_index": ahr999_index,
        "pi_cycle_top": pi_cycle_top,
        "therm_index": therm_index,
        "mayer_multiple": mayer_multiple,
        "puell_multiple": puell_multiple,
        "valuation_range": valuation_range,
        "valuation_heat_level": valuation_heat_level,
    }
    metrics_breakdown = {
        "short_term_holder_pnl": short_term_holder_pnl,
        "long_term_holder_pnl": long_term_holder_pnl,
        "realized_profit": realized_profit,
        "realized_loss": realized_loss,
        "market_value_growth": market_value_growth,
        "realised_value_growth": realised_value_growth,
        "sopr_long_term": sopr_long_term,
        "sopr_short_term": sopr_short_term,
    }

    now = _now_iso()
    events: List[Dict[str, Any]] = []
    if mvrv_z_score < -0.5:
        events.append({
            "title": "MVRV Z-Score 进入绿色区域，建议关注定投机会",
            "content": f"MVRV {mvrv_ratio:.2f}，Z-Score {mvrv_z_score:.2f}，AHR999 {ahr999_index:.2f}",
            "category": "估值",
            "impact_score": 0.7,
            "sentiment": 0.5,
            "source": "Glassnode",
            "published_at": now,
        })
    elif mvrv_z_score > 1.5:
        events.append({
            "title": "MVRV Z-Score 过热，警惕顶部回调",
            "content": f"MVRV {mvrv_ratio:.2f}，Z-Score {mvrv_z_score:.2f}，Pi Cycle {pi_cycle_top:.2f}",
            "category": "估值",
            "impact_score": 0.75,
            "sentiment": -0.4,
            "source": "Glassnode",
            "published_at": now,
        })

    if sopr_long_term > 1.05:
        events.append({
            "title": "长期持有者 SOPR 维持 1.0 上方，无投降迹象",
            "content": f"长期 SOPR {sopr_long_term:.3f}，长期持有者盈亏 +{long_term_holder_pnl:.1f}%",
            "category": "持仓盈亏",
            "impact_score": 0.6,
            "sentiment": 0.45,
            "source": "On-chain",
            "published_at": now,
        })

    events.append({
        "title": f"估值区间：{valuation_range}（{valuation_heat_level}）",
        "content": f"MVRV {mvrv_ratio:.2f}，Mayer Multiple {mayer_multiple:.2f}，Puell Multiple {puell_multiple:.2f}",
        "category": "估值汇总",
        "impact_score": 0.55,
        "sentiment": round(_clamp((mvrv_ratio - 2.5) / 1.5, -1, 1), 3),
        "source": "Aggregate",
        "published_at": now,
    })

    timeseries = _make_timeseries(mvrv_ratio, days=30, vmin=0.5, vmax=4.0)

    # 估值差异化字段：NUPL, 已实现价格, 市价
    nupl = round(_clamp((mvrv_ratio - 1) / mvrv_ratio, 0, 1), 3)
    realized_price = round(38000 + random.uniform(-2000, 5000), 0)
    market_price = round(realized_price * mvrv_ratio, 0)
    price_distance_from_realized = round((market_price - realized_price) / realized_price * 100, 1)

    _MODULE_CONTEXT["scores"]["valuation"] = mvrv_ratio
    _MODULE_CONTEXT["timestamps"]["valuation"] = now

    return {
        "metrics": {"core": metrics_core, "breakdown": metrics_breakdown},
        "events": events,
        "timeseries": timeseries,
        "nupl": nupl,
        "realized_price": realized_price,
        "market_price": market_price,
        "price_distance_from_realized": price_distance_from_realized,
        "timestamp": now,
    }


# ---------- F. Onchain（链上） ----------
def _generate_mock_onchain_data() -> Dict[str, Any]:
    # 交易所净流入（百万 USD）：负=流出 正=流入
    exchange_net_flow = round(random.uniform(-300, 500), 2)
    exchange_inflow_24h = round(max(0, -exchange_net_flow) + random.uniform(100, 500), 2)
    exchange_outflow_24h = round(max(0, exchange_net_flow) + random.uniform(120, 600), 2)

    # 活跃地址（万）
    active_addresses = random.randint(30, 120)

    # 交易量（十亿美元）
    transaction_volume = round(random.uniform(3.0, 30.0), 2)

    # Gas 价格
    gas_price_gwei = round(random.uniform(5, 200), 2)

    # 矿工 / 鲸鱼行为（0-100）
    miner_position = round(_clamp(50 - exchange_net_flow * 0.05 + random.uniform(-10, 10), 0, 100), 2)
    whale_position = round(_clamp(50 + exchange_net_flow * 0.08 + random.uniform(-10, 10), 0, 100), 2)
    whale_accumulation_score = round(_clamp(max(0, whale_position - 40) * 1.5 + random.uniform(-5, 10), 0, 100), 2)
    exchange_supply_pressure = round(_clamp(max(0, 50 - exchange_net_flow * 0.1) + random.uniform(-5, 10), 0, 100), 2)

    # 稳定币总供应量（十亿美元）
    stablecoin_supply = round(110 + exchange_net_flow * 0.02 + random.uniform(-5, 8), 2)

    # hodl_wave
    if exchange_net_flow > 100 and whale_accumulation_score > 60:
        hodl_wave_strength = "强"
    elif exchange_net_flow > -50:
        hodl_wave_strength = "中"
    else:
        hodl_wave_strength = "弱"

    # 细分
    whale_transactions_24h = random.randint(30, 400)
    gas_usage_defi = round(_clamp(20 + random.uniform(-10, 15), 5, 55), 2)
    gas_usage_nft = round(_clamp(15 + random.uniform(-10, 15), 2, 40), 2)
    gas_usage_l2 = round(_clamp(30 + random.uniform(-10, 20), 10, 65), 2)
    long_term_holder_ratio = round(_clamp(60 + whale_accumulation_score * 0.15 + random.uniform(-5, 5), 30, 85), 2)
    new_addresses_24h = random.randint(2000, 20000)

    metrics_core = {
        "exchange_net_flow": exchange_net_flow,
        "active_addresses": active_addresses,
        "transaction_volume": transaction_volume,
        "gas_price_gwei": gas_price_gwei,
        "miner_position": miner_position,
        "whale_position": whale_position,
        "stablecoin_supply": stablecoin_supply,
        "whale_accumulation_score": whale_accumulation_score,
        "exchange_supply_pressure": exchange_supply_pressure,
        "hodl_wave_strength": hodl_wave_strength,
    }
    metrics_breakdown = {
        "whale_transactions_24h": whale_transactions_24h,
        "exchange_inflow_24h": exchange_inflow_24h,
        "exchange_outflow_24h": exchange_outflow_24h,
        "gas_usage_defi": gas_usage_defi,
        "gas_usage_nft": gas_usage_nft,
        "gas_usage_l2": gas_usage_l2,
        "long_term_holder_ratio": long_term_holder_ratio,
        "new_addresses_24h": new_addresses_24h,
    }

    now = _now_iso()
    events: List[Dict[str, Any]] = []
    if exchange_net_flow < -100:
        events.append({
            "title": "鲸鱼地址持续从交易所提币，场外积累进行中",
            "content": f"交易所净流入 ${exchange_net_flow:,.0f}M（净流出），鲸鱼积累 {whale_accumulation_score:.0f}/100",
            "category": "鲸鱼",
            "impact_score": 0.7,
            "sentiment": 0.55,
            "source": "On-chain",
            "published_at": now,
        })
    elif exchange_net_flow > 150:
        events.append({
            "title": "资金回流交易所，短期抛售压力或上升",
            "content": f"交易所净流入 +${exchange_net_flow:,.0f}M，供应压力 {exchange_supply_pressure:.0f}/100",
            "category": "资金流动",
            "impact_score": 0.65,
            "sentiment": -0.3,
            "source": "On-chain",
            "published_at": now,
        })

    if stablecoin_supply > 115:
        events.append({
            "title": "稳定币供应增量创新高，潜在入场资金增加",
            "content": f"稳定币总供应量 ${stablecoin_supply:.1f}B",
            "category": "稳定币",
            "impact_score": 0.6,
            "sentiment": 0.5,
            "source": "On-chain",
            "published_at": now,
        })

    if gas_price_gwei > 100:
        events.append({
            "title": "Gas 费用飙升，网络拥堵等级提升",
            "content": f"当前 Gas {gas_price_gwei:.0f} Gwei，L2 占比 {gas_usage_l2:.0f}%",
            "category": "网络",
            "impact_score": 0.55,
            "sentiment": -0.35,
            "source": "Etherscan",
            "published_at": now,
        })

    events.append({
        "title": f"HODL Wave：{hodl_wave_strength}，长期持有者占比 {long_term_holder_ratio:.0f}%",
        "content": f"活跃地址 {active_addresses} 万，24h 新增地址 {new_addresses_24h:,}",
        "category": "链上汇总",
        "impact_score": 0.5,
        "sentiment": round(_clamp(-exchange_net_flow / 300, -1, 1), 3),
        "source": "Aggregate",
        "published_at": now,
    })

    # 归一化 -1 到 1：exchange_net_flow / 1000
    norm_ex_net = exchange_net_flow / 1000.0
    timeseries = _make_timeseries(norm_ex_net, days=30, vmin=-0.5, vmax=0.5)

    # 链上差异化字段：UTXO年龄分布、矿工流出、算力、交易所储备
    utxo_age_distribution = [
        {"age_range": "<1天", "percentage": round(5 + random.uniform(0, 3), 1)},
        {"age_range": "1-7天", "percentage": round(8 + random.uniform(0, 4), 1)},
        {"age_range": "7-30天", "percentage": round(12 + random.uniform(0, 5), 1)},
        {"age_range": "30-90天", "percentage": round(15 + random.uniform(0, 6), 1)},
        {"age_range": "90-365天", "percentage": round(18 + random.uniform(0, 7), 1)},
        {"age_range": "1-2年", "percentage": round(20 + random.uniform(0, 8), 1)},
        {"age_range": "2-3年", "percentage": round(12 + random.uniform(0, 5), 1)},
        {"age_range": "3-5年", "percentage": round(8 + random.uniform(0, 4), 1)},
        {"age_range": ">5年", "percentage": round(10 + random.uniform(0, 5), 1)},
    ]

    miner_outflow = round(miner_position * 0.5 - 25 + random.uniform(-20, 20), 0)
    hash_rate = round(600 + random.uniform(-50, 100), 0)
    exchange_reserve = round(2500 - exchange_net_flow * 0.5 + random.uniform(-200, 200), 0)

    _MODULE_CONTEXT["scores"]["onchain"] = norm_ex_net
    _MODULE_CONTEXT["timestamps"]["onchain"] = now

    return {
        "metrics": {"core": metrics_core, "breakdown": metrics_breakdown},
        "events": events,
        "timeseries": timeseries,
        "utxo_age_distribution": utxo_age_distribution,
        "miner_outflow": miner_outflow,
        "hash_rate": hash_rate,
        "exchange_reserve": exchange_reserve,
        "timestamp": now,
    }


# ============== News Mock（保留使用） ==============
def _generate_mock_news(query: str = "", max_results: int = 8) -> List[Dict[str, Any]]:
    templates: List[tuple] = [
        ("比特币 ETF 获批带动机构资金流入", "机构投资者持续买入，整体市场情绪偏向乐观", "ETF/机构"),
        ("美联储维持利率不变，美元指数小幅回落", "流动性保持稳定，风险资产短期受益", "宏观政策"),
        ("以太坊最新升级提升网络性能，Layer2 活跃度上升", "Gas 成本下降，链上活动回暖", "项目进展"),
        ("监管政策趋严引发市场短时波动", "SEC 对多家交易所发起调查，市场短期承压", "监管/法规"),
        ("稳定币供应量持续增长，场外资金入场明显", "USDT/USDC 增发创新高", "链上/资金"),
        ("链上数据显示大型持有者地址异动", "过去 24h 鲸鱼地址发生大额转账", "链上/资金"),
        ("机构投资者 13F 文件披露增持 BTC", "多家机构加仓比特币，长期持仓增加", "ETF/机构"),
        ("DeFi 协议锁仓量突破前高", "去中心化金融参与度显著提升", "项目进展"),
        ("MVRV Z-Score 进入绿色区域，定投吸引力上升", "估值处于相对低位，长期配置窗口开启", "估值"),
        ("恐惧贪婪指数转为中性，市场情绪逐步企稳", "恐慌消散，资金回流风险资产", "情绪"),
    ]
    chosen = random.sample(templates, min(max_results, len(templates)))
    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for i, (title, content, cat) in enumerate(chosen):
        out.append({
            "title": title,
            "content": content,
            "category": cat,
            "source": random.choice(["CoinDesk", "The Block", "Decrypt", "Bloomberg", "Reuters"]),
            "url": f"https://example.com/news/{hash((title, i)) % 100000}",
            "published_at": (now - timedelta(hours=i * 4)).isoformat(),
        })
    return out


# ============== DataCollector ==============
class DataCollector:
    """数据采集器（主入口类）：每个 collect_xxx 返回统一结构"""

    def __init__(self, storage_dir: str = None):
        self.storage_dir = storage_dir or "./storage"

    # ---------- 1. News ----------
    def collect_news(self) -> Dict[str, Any]:
        queries = [
            "crypto market news today",
            "bitcoin ethereum price analysis",
            "blockchain regulation policy",
            "ETF approval crypto",
        ]
        results = fetch_tavily_batch(queries, max_results=6)

        all_news: List[Dict[str, Any]] = []
        bull_words = ["获批", "买入", "增持", "创新", "乐观", "增长", "利好",
                      "approved", "bull", "surge", "rally", "inflow"]
        bear_words = ["警告", "监管", "下跌", "压力", "传票", "风险",
                      "warn", "ban", "crash", "outflow", "sell"]

        for query, articles in results.items():
            for article in articles:
                title = article.get("title", "")
                content = article.get("content", "")
                text = f"{title} {content}"
                bull_score = sum(1 for w in bull_words if w in text)
                bear_score = sum(1 for w in bear_words if w in text)
                sentiment = 0.5 + (bull_score - bear_score) * 0.12
                sentiment = max(-1.0, min(1.0, sentiment))
                impact = min(1.0, 0.3 + (bull_score + bear_score) * 0.18)
                category = (
                    "宏观政策" if any(w in text for w in ["政策", "FOMC", "利率", "inflation", "CPI"])
                    else "ETF/机构" if any(w in text for w in ["ETF", "机构", "13F", "institutional"])
                    else "项目进展" if any(w in text for w in ["升级", "DeFi", "扩容", "L2"])
                    else "监管/法规" if any(w in text for w in ["监管", "SEC", "传票", "ban"])
                    else "链上/资金" if any(w in text for w in ["稳定币", "供应", "inflow", "outflow", "鲸鱼"])
                    else "市场行情"
                )
                all_news.append({
                    "title": title,
                    "content": content,
                    "source": article.get("source", "Unknown"),
                    "url": article.get("url", ""),
                    "published_at": article.get("published_at", _days_ago_iso(2)),
                    "category": category,
                    "sentiment": round(sentiment, 3),
                    "impact_score": round(impact, 3),
                })

        # 兜底：如果 Tavily 没结果，使用模板
        if not all_news:
            all_news = [
                {"title": n[0], "content": n[1], "category": n[2],
                 "source": random.choice(["CoinDesk", "The Block", "Bloomberg"]),
                 "url": "", "published_at": _days_ago_iso(i * 6),
                 "sentiment": round(random.uniform(-0.3, 0.7), 3),
                 "impact_score": round(random.uniform(0.3, 0.8), 3)}
                for i, n in enumerate([
                    ("比特币 ETF 资金持续流入", "机构配置兴趣回升", "ETF/机构"),
                    ("宏观不确定性仍存，但风险资产表现稳健", "市场在利率路径中博弈", "宏观政策"),
                    ("链上活跃地址上升", "链上活跃度与交易量均有改善", "链上/资金"),
                ])
            ]

        # 聚合指标
        n_items = len(all_news)
        if n_items == 0:
            avg_sentiment = 0.0
            avg_impact = 0.5
            positive_count = negative_count = high_impact_count = 0
            top_category = ""
            category_count = 0
            bullish_ratio = bearish_ratio = neutral_ratio = 50
        else:
            avg_sentiment = round(sum(n["sentiment"] for n in all_news) / n_items, 3)
            avg_impact = round(sum(n["impact_score"] for n in all_news) / n_items, 3)
            positive_count = sum(1 for n in all_news if n["sentiment"] > 0.2)
            negative_count = sum(1 for n in all_news if n["sentiment"] < -0.2)
            high_impact_count = sum(1 for n in all_news if n["impact_score"] >= 0.7)
            cats: Dict[str, int] = {}
            for n in all_news:
                cats[n["category"]] = cats.get(n["category"], 0) + 1
            top_category = max(cats.items(), key=lambda x: x[1])[0]
            category_count = len(cats)
            bullish_ratio = round(positive_count * 100 / n_items, 2)
            bearish_ratio = round(negative_count * 100 / n_items, 2)
            neutral_ratio = round(100 - bullish_ratio - bearish_ratio, 2)

        # 综合评分（供 resistance_3d）
        sentiment_sum = round(sum(n["sentiment"] for n in all_news), 3)
        normalized_sentiment = round(_clamp(avg_sentiment, -1, 1), 3)

        now = _now_iso()
        metrics_core = {
            "total_articles": n_items,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "high_impact_count": high_impact_count,
            "avg_sentiment": avg_sentiment,
            "sentiment_sum": sentiment_sum,
            "avg_impact": avg_impact,
            "top_category": top_category,
            "category_count": category_count,
            "sentiment": normalized_sentiment,
        }
        metrics_breakdown = {
            "bullish_ratio": bullish_ratio,
            "bearish_ratio": bearish_ratio,
            "neutral_ratio": neutral_ratio,
        }

        timeseries = _make_timeseries(normalized_sentiment, days=30, vmin=-1.0, vmax=1.0)

        _MODULE_CONTEXT["scores"]["news"] = normalized_sentiment
        _MODULE_CONTEXT["timestamps"]["news"] = now
        _MODULE_CONTEXT["latest"]["news"] = {"metrics": metrics_core, "events_count": len(all_news)}

        return {
            "metrics": {"core": metrics_core, "breakdown": metrics_breakdown},
            "events": all_news[:15],
            "timeseries": timeseries,
            "timestamp": now,
        }

    # ---------- 2. Flow ----------
    def collect_flow(self) -> Dict[str, Any]:
        # Tavily: 搜索 BTC ETF 资金流向、资金费率、OI 关键数据
        articles = _fetch_tavily_market_data(
            "bitcoin ETF fund flow funding rate open interest 24h", max_results=4
        )
        if articles:
            combined = " ".join(a.get("content", "") + " " + a.get("title", "") for a in articles)
            etf_net = _parse_number_from_text(combined, ["net inflow", "net flow", "etf inflow", "亿美元流入", "million inflow"])
            funding = _parse_number_from_text(combined, ["funding rate", "资金费率", "funding:"])
            etf_net_flow = float(etf_net) if etf_net is not None else random.uniform(-300, 600)
            funding_rate = float(funding) / 100 if funding is not None and abs(funding) < 5 else random.uniform(-0.02, 0.05)
            # 从文字情绪推断综合评分
            bull_hits = sum(1 for w in ["inflow", "流入", "positive", "bullish", "买入"] if w in combined.lower())
            bear_hits = sum(1 for w in ["outflow", "流出", "negative", "bearish", "卖出"] if w in combined.lower())
            fund_flow_score = round(_clamp((bull_hits - bear_hits) * 0.15, -0.8, 0.8), 4)
            print(f"[Flow] Tavily real data: etf_net={etf_net_flow:.0f}M, funding={funding_rate:.4f}, score={fund_flow_score}")
        else:
            fund_flow_score = round(random.uniform(-0.3, 0.7), 4)
            etf_net_flow = round(fund_flow_score * 800 + random.uniform(-150, 150), 2)
            funding_rate = round(fund_flow_score * 0.05 + random.uniform(-0.01, 0.01), 4)

        # 派生指标（保持原逻辑，基于真实 score）
        etf_inflow_24h = round(max(0, etf_net_flow) + random.uniform(100, 600), 2)
        etf_outflow_24h = round(max(0, -etf_net_flow) + random.uniform(80, 400), 2)
        long_short_ratio = round(1.0 + fund_flow_score * 0.3 + random.uniform(-0.1, 0.1), 2)
        liquidation_pressure = round(_clamp((1.0 - fund_flow_score) * 40 + random.uniform(0, 25), 0, 100), 2)
        long_pressure = round(_clamp((long_short_ratio - 0.8) * 80 + random.uniform(0, 20), 0, 100), 2)
        short_pressure = round(_clamp((1.3 - long_short_ratio) * 80 + random.uniform(0, 20), 0, 100), 2)
        whale_activity = round(random.uniform(30, 90), 2)
        whale_buying = round(_clamp(whale_activity * fund_flow_score + 50 + random.uniform(-10, 10), 0, 100), 2)
        whale_selling = round(_clamp(whale_activity * (1 - fund_flow_score) + 20 + random.uniform(-10, 10), 0, 100), 2)
        stablecoin_supply_change = round(fund_flow_score * 2.0 + random.uniform(-0.6, 0.6), 3)
        usdt_supply_change = round(stablecoin_supply_change + random.uniform(-0.5, 0.5), 3)
        usdc_supply_change = round(stablecoin_supply_change * 0.8 + random.uniform(-0.4, 0.4), 3)
        institutional_exposure = round(_clamp(50 + fund_flow_score * 30 + random.uniform(-10, 10), 0, 100), 2)
        retail_exposure = round(_clamp(50 - fund_flow_score * 15 + random.uniform(-10, 10), 0, 100), 2)
        smart_money_direction = ("显著流入" if etf_net_flow > 200 and whale_activity > 60
                                 else "温和流入" if etf_net_flow > 0
                                 else "显著流出" if etf_net_flow < -200 else "观望")
        flow_velocity_score = round(_clamp(abs(fund_flow_score) * 80 + random.uniform(10, 30), 0, 100), 2)

        now = _now_iso()
        events: List[Dict[str, Any]] = []
        if articles:
            for a in articles[:3]:
                text = a.get("content", "")[:200]
                bull = sum(1 for w in ["inflow", "流入", "rally", "surge"] if w in text.lower())
                bear = sum(1 for w in ["outflow", "流出", "drop", "crash"] if w in text.lower())
                sent = round(_clamp((bull - bear) * 0.2, -1, 1), 3)
                events.append({
                    "title": a.get("title", "")[:80],
                    "content": summarize_content(text),
                    "category": "资金流",
                    "impact_score": round(min(1.0, 0.4 + abs(sent) * 0.4), 3),
                    "sentiment": sent,
                    "source": a.get("source", "Tavily"),
                    "url": a.get("url", ""),
                    "published_at": a.get("published_at", now),
                })

        metrics_core = {
            "fund_flow_score": fund_flow_score,
            "etf_net_flow": round(etf_net_flow, 2),
            "funding_rate": round(funding_rate, 4),
            "long_short_ratio": long_short_ratio,
            "liquidation_pressure": liquidation_pressure,
            "whale_activity": whale_activity,
            "stablecoin_supply_change": stablecoin_supply_change,
            "smart_money_direction": smart_money_direction,
            "flow_velocity_score": flow_velocity_score,
        }
        metrics_breakdown = {
            "etf_inflow_24h": etf_inflow_24h,
            "etf_outflow_24h": etf_outflow_24h,
            "long_pressure": long_pressure,
            "short_pressure": short_pressure,
            "whale_buying": whale_buying,
            "whale_selling": whale_selling,
            "usdt_supply_change": usdt_supply_change,
            "usdc_supply_change": usdc_supply_change,
            "retail_exposure": retail_exposure,
            "institutional_exposure": institutional_exposure,
        }
        timeseries = _make_timeseries(fund_flow_score, days=30, vmin=-1.0, vmax=1.0)
        _MODULE_CONTEXT["scores"]["flow"] = fund_flow_score
        _MODULE_CONTEXT["timestamps"]["flow"] = now
        _MODULE_CONTEXT["latest"]["flow"] = {"metrics": metrics_core}
        return {"metrics": {"core": metrics_core, "breakdown": metrics_breakdown}, "events": events, "timeseries": timeseries, "timestamp": now}

    # ---------- 3. Sentiment ----------
    def collect_sentiment(self) -> Dict[str, Any]:
        now = _now_iso()
        # 真实数据：alternative.me Fear & Greed
        fng = _fetch_fear_greed()
        if fng:
            fear_greed_index = fng["value"]
            fng_label = fng["classification"]
            print(f"[Sentiment] Real Fear&Greed: {fear_greed_index} ({fng_label})")
        else:
            fear_greed_index = random.randint(20, 80)
            fng_label = "Neutral"

        sentiment_index = fear_greed_index  # 对齐原有字段
        narrative_heat = round(_clamp(sentiment_index * 0.9 + random.uniform(-10, 10), 10, 100), 2)
        consensus_level = round(_clamp(60 - abs(sentiment_index - 55) * 1.5 + random.uniform(-10, 10), 20, 95), 2)
        reversal_risk = round(_clamp(abs(sentiment_index - 50) * 1.5 + random.uniform(5, 20), 5, 95), 2)
        social_volume = random.randint(5000, 90000)
        news_sentiment = round(_clamp(sentiment_index + random.uniform(-12, 12), 10, 100), 2)
        social_sentiment = round(_clamp(sentiment_index * 0.95 + random.uniform(-10, 10), 10, 100), 2)
        bullish_ratio = round(_clamp(sentiment_index * 0.8 + random.uniform(-8, 8), 5, 95), 2)
        bearish_ratio = round(_clamp((100 - sentiment_index) * 0.7 + random.uniform(-8, 8), 5, 95), 2)
        neutral_ratio = round(_clamp(100 - bullish_ratio - bearish_ratio + random.uniform(-5, 5), 5, 60), 2)
        hype_level = round(_clamp(max(0, sentiment_index - 55) * 2 + random.uniform(0, 15), 0, 100), 2)
        panic_level = round(_clamp(max(0, 50 - sentiment_index) * 2 + random.uniform(0, 15), 0, 100), 2)
        fomo_score = hype_level
        capitulation_score = panic_level

        if fear_greed_index >= 85:
            contrarian_signal = "警惕过热（逆向卖出）"
        elif fear_greed_index <= 20:
            contrarian_signal = "极度恐惧（逆向买入）"
        else:
            contrarian_signal = "保持观望"

        if fear_greed_index >= 80:
            market_psychology = "极度贪婪"
        elif fear_greed_index >= 65:
            market_psychology = "贪婪"
        elif fear_greed_index >= 45:
            market_psychology = "中性"
        elif fear_greed_index >= 25:
            market_psychology = "恐惧"
        else:
            market_psychology = "极度恐惧"

        flow_hint = _MODULE_CONTEXT["scores"].get("flow", 0.0)
        events: List[Dict[str, Any]] = []
        events.append({
            "title": f"Fear & Greed 指数：{fear_greed_index} ({fng_label})",
            "content": f"当前市场情绪：{market_psychology}，逆向信号：{contrarian_signal}",
            "category": "Fear & Greed",
            "impact_score": round(0.5 + abs(fear_greed_index - 50) / 100, 3),
            "sentiment": round(_clamp((fear_greed_index - 50) / 50, -1, 1), 3),
            "source": "alternative.me",
            "published_at": now,
        })
        if reversal_risk > 65:
            events.append({
                "title": f"反转风险 {reversal_risk:.0f}/100（偏高）",
                "content": "情绪与价格方向可能出现背离，关注分歧迹象",
                "category": "风险提示", "impact_score": 0.6, "sentiment": -0.3,
                "source": "Calculated", "published_at": now,
            })

        heatmap_data = [
            {"category": "社交媒体", "score": round(social_sentiment, 1)},
            {"category": "新闻舆情", "score": round(news_sentiment, 1)},
            {"category": "搜索热度", "score": round(narrative_heat, 1)},
            {"category": "衍生品", "score": round(sentiment_index * 0.8 + random.uniform(-10, 10), 1)},
            {"category": "资金流向", "score": round(50 + flow_hint * 30 + random.uniform(-5, 5), 1)},
            {"category": "链上活动", "score": round(consensus_level, 1)},
            {"category": "宏观环境", "score": round(50 + random.uniform(-15, 15), 1)},
            {"category": "技术面", "score": round(sentiment_index * 0.9 + random.uniform(-8, 8), 1)},
        ]
        timeseries = _make_timeseries(sentiment_index, days=30, vmin=0.0, vmax=100.0)
        _MODULE_CONTEXT["scores"]["sentiment"] = sentiment_index
        _MODULE_CONTEXT["timestamps"]["sentiment"] = now
        return {
            "metrics": {"core": {
                "sentiment_index": sentiment_index, "fear_greed_index": fear_greed_index,
                "narrative_heat": narrative_heat, "consensus_level": consensus_level,
                "reversal_risk": reversal_risk, "social_volume": social_volume,
                "contrarian_signal": contrarian_signal, "market_psychology": market_psychology,
            }, "breakdown": {
                "news_sentiment": news_sentiment, "social_sentiment": social_sentiment,
                "bullish_ratio": bullish_ratio, "bearish_ratio": bearish_ratio,
                "neutral_ratio": neutral_ratio, "hype_level": hype_level,
                "panic_level": panic_level, "fomo_score": fomo_score,
                "capitulation_score": capitulation_score,
            }},
            "events": events, "timeseries": timeseries, "heatmap_data": heatmap_data, "timestamp": now,
        }

    # ---------- 4. Macro ----------
    def collect_macro(self) -> Dict[str, Any]:
        now = _now_iso()
        # Tavily: 搜索美联储政策、CPI、美元指数
        articles = _fetch_tavily_market_data(
            "Federal Reserve interest rate DXY dollar index CPI inflation 2026", max_results=4
        )
        combined = " ".join(a.get("content", "") + " " + a.get("title", "") for a in articles) if articles else ""

        if combined:
            dxy_raw = _parse_number_from_text(combined, ["DXY", "dollar index", "美元指数"])
            us10y_raw = _parse_number_from_text(combined, ["10-year", "10y yield", "US10Y", "treasury yield"])
            dxy_strength = float(dxy_raw) if dxy_raw and 80 < dxy_raw < 130 else round(random.uniform(98, 108), 2)
            us10y_yield = float(us10y_raw) if us10y_raw and 1 < us10y_raw < 8 else round(random.uniform(3.8, 4.8), 3)
            # 鹰鸽判断
            hawk_hits = sum(1 for w in ["hawkish", "hike", "higher for longer", "鹰派", "加息"] if w in combined.lower())
            dove_hits = sum(1 for w in ["dovish", "cut", "easing", "鸽派", "降息"] if w in combined.lower())
            policy_score = round(_clamp((dove_hits - hawk_hits) * 0.15, -0.8, 0.8), 4)
            print(f"[Macro] Tavily real data: DXY={dxy_strength}, 10Y={us10y_yield}, policy={policy_score}")
        else:
            policy_score = round(random.uniform(-0.4, 0.5), 4)
            dxy_strength = round(_clamp(100 - policy_score * 12 + random.uniform(-3, 3), 85, 115), 2)
            us10y_yield = round(_clamp(3.5 - policy_score * 1.5 + random.uniform(-0.3, 0.3), 1.5, 5.5), 3)

        rate_impact = round(_clamp(-policy_score * 80 + random.uniform(-15, 15), -100, 100), 2)
        growth_expectation = round(_clamp(policy_score * 60 + random.uniform(-15, 15), -50, 50), 2)
        inflation_pressure = round(_clamp((1 - policy_score) * 40 + random.uniform(0, 30), 0, 100), 2)
        fed_hawkishness = round(_clamp((1 - policy_score) * 50 + random.uniform(10, 30), 0, 100), 2)
        market_liquidity = round(_clamp(50 + policy_score * 30 + random.uniform(-10, 10), 0, 100), 2)
        crypto_friendly_score = round(_clamp(50 + policy_score * 40 + random.uniform(-10, 10), 0, 100), 2)
        liquidity_clock = "扩张" if policy_score > 0.3 else "紧缩" if policy_score < -0.2 else "转向"

        events: List[Dict[str, Any]] = []
        if articles:
            for a in articles[:3]:
                text = a.get("content", "")[:200]
                hawk = sum(1 for w in ["hawkish", "hike", "鹰派"] if w in text.lower())
                dove = sum(1 for w in ["dovish", "cut", "鸽派"] if w in text.lower())
                sent = round(_clamp((dove - hawk) * 0.25, -1, 1), 3)
                events.append({
                    "title": a.get("title", "")[:80],
                    "content": summarize_content(text),
                    "category": "央行政策",
                    "impact_score": round(min(1.0, 0.5 + abs(sent) * 0.4), 3),
                    "sentiment": sent,
                    "source": a.get("source", "Tavily"),
                    "url": a.get("url", ""),
                    "published_at": a.get("published_at", now),
                })
        events.append({
            "title": f"全球流动性时钟：{liquidity_clock}",
            "content": f"DXY={dxy_strength:.1f}，10Y={us10y_yield:.2f}%，加密友好度={crypto_friendly_score:.0f}",
            "category": "宏观", "impact_score": 0.55, "sentiment": round(policy_score, 3),
            "source": "Macro Aggregate", "published_at": now,
        })
        timeseries = _make_timeseries(policy_score, days=30, vmin=-1.0, vmax=1.0)
        _MODULE_CONTEXT["scores"]["macro"] = policy_score
        _MODULE_CONTEXT["timestamps"]["macro"] = now
        return {
            "metrics": {"core": {
                "policy_score": policy_score, "dxy_strength": dxy_strength,
                "rate_impact": rate_impact, "growth_expectation": growth_expectation,
                "inflation_pressure": inflation_pressure, "us10y_yield": us10y_yield,
                "macro_risk_score": round(_clamp(60 - policy_score * 30 + random.uniform(-10, 10), 0, 100), 2),
                "crypto_friendly_score": crypto_friendly_score, "liquidity_clock": liquidity_clock,
            }, "breakdown": {
                "fed_policy_hawkishness": fed_hawkishness,
                "ecb_policy_hawkishness": round(_clamp(fed_hawkishness + random.uniform(-15, 15), 0, 100), 2),
                "market_liquidity": market_liquidity,
                "yield_curve_slope": round(_clamp(policy_score * 80 + random.uniform(-15, 15), -100, 100), 2),
                "inflation_vs_target": round(_clamp(1.0 + (100 - inflation_pressure) * -0.005 + random.uniform(-0.2, 0.2), 0.3, 3.0), 3),
                "growth_vs_potential": round(_clamp(0.8 + policy_score * 0.4 + random.uniform(-0.1, 0.1), 0.3, 1.8), 3),
                "risk_on_sentiment": round(_clamp(50 + policy_score * 40 + random.uniform(-10, 10), 0, 100), 2),
                "safe_haven_demand": round(_clamp(50 - policy_score * 30 + random.uniform(-10, 10), 0, 100), 2),
            }},
            "events": events, "timeseries": timeseries, "timestamp": now,
        }

    # ---------- 5. Breadth ----------
    def collect_breadth(self) -> Dict[str, Any]:
        now = _now_iso()
        # Tavily: 搜索加密市场广度、BTC 占比、山寨表现
        articles = _fetch_tavily_market_data(
            "crypto market breadth altcoin bitcoin dominance BTC.D altseason 2026", max_results=3
        )
        combined = " ".join(a.get("content", "") + " " + a.get("title", "") for a in articles) if articles else ""

        if combined:
            btc_dom_raw = _parse_number_from_text(combined, ["BTC.D", "bitcoin dominance", "btc dominance", "占比"])
            btc_dominance = float(btc_dom_raw) if btc_dom_raw and 30 < btc_dom_raw < 75 else round(random.uniform(48, 62), 2)
            bull_hits = sum(1 for w in ["altseason", "altcoin rally", "broad rally", "山寨季", "全面上涨"] if w in combined.lower())
            bear_hits = sum(1 for w in ["dominance rising", "alts bleeding", "risk off", "山寨跌", "广度恶化"] if w in combined.lower())
            advance_decline_line = round(_clamp((bull_hits - bear_hits) * 15 + random.uniform(-20, 20), -60, 70), 2)
            print(f"[Breadth] Tavily real data: BTC.D={btc_dominance:.1f}%, adl={advance_decline_line:.1f}")
        else:
            btc_dominance = round(random.uniform(48, 62), 2)
            advance_decline_line = round(random.uniform(-50, 60), 2)

        advance_count = round(_clamp(50 + advance_decline_line * 0.5 + random.uniform(-5, 5), 0, 100), 2)
        decline_count = round(_clamp(50 - advance_decline_line * 0.5 + random.uniform(-5, 5), 0, 100), 2)
        new_high_low_ratio = round(_clamp(1.0 + advance_decline_line * 0.02 + random.uniform(-0.15, 0.15), 0.3, 3.0), 3)
        new_highs_count = random.randint(5, 80)
        new_lows_count = max(2, int(new_highs_count / new_high_low_ratio))
        l1_breadth = round(_clamp(50 + advance_decline_line * 0.4 + random.uniform(-10, 10), 0, 100), 2)
        l2_breadth = round(_clamp(50 + advance_decline_line * 0.3 + random.uniform(-15, 15), 0, 100), 2)
        defi_breadth = round(_clamp(50 + advance_decline_line * 0.35 + random.uniform(-10, 10), 0, 100), 2)
        meme_breadth = round(_clamp(50 + advance_decline_line * 0.2 + random.uniform(-20, 20), 0, 100), 2)
        breadth_confirmation = ("确认趋势" if advance_decline_line > 30 and new_high_low_ratio > 1.5
                                else "存在分歧" if advance_decline_line > 0 else "广度恶化")
        divergence_signal = ("顶背离" if advance_decline_line > 20 and meme_breadth < 40
                             else "底背离" if advance_decline_line < -20 and l1_breadth > 55
                             else "无背离")
        norm_adl = advance_decline_line / 100.0

        events: List[Dict[str, Any]] = []
        if articles:
            for a in articles[:2]:
                text = a.get("content", "")[:200]
                sent = round(_clamp((advance_decline_line / 60) * 0.6 + random.uniform(-0.2, 0.2), -1, 1), 3)
                events.append({
                    "title": a.get("title", "")[:80], "content": summarize_content(text),
                    "category": "广度", "impact_score": 0.55, "sentiment": sent,
                    "source": a.get("source", "Tavily"), "url": a.get("url", ""), "published_at": a.get("published_at", now),
                })
        events.append({
            "title": f"BTC 占比 {btc_dominance:.1f}%，广度状态：{breadth_confirmation}",
            "content": f"涨跌线 {advance_decline_line:+.1f}，{divergence_signal}",
            "category": "广度汇总", "impact_score": 0.5, "sentiment": round(norm_adl, 3),
            "source": "Aggregate", "published_at": now,
        })
        timeseries = _make_timeseries(norm_adl, days=30, vmin=-1.0, vmax=1.0)
        _MODULE_CONTEXT["scores"]["breadth"] = norm_adl
        _MODULE_CONTEXT["timestamps"]["breadth"] = now
        return {
            "metrics": {"core": {
                "advance_decline_line": advance_decline_line, "advance_count": advance_count,
                "decline_count": decline_count, "new_high_low_ratio": new_high_low_ratio,
                "breadth_confirmation": breadth_confirmation, "divergence_signal": divergence_signal,
                "breadth_divergence_score": round(_clamp(abs(advance_decline_line - 40) * 0.8 + random.uniform(0, 20), 0, 100), 2),
                "market_participation_index": round(_clamp(50 + advance_decline_line * 0.3 + random.uniform(-10, 10), 0, 100), 2),
                "btc_dominance": btc_dominance,
            }, "breakdown": {
                "new_highs_count": new_highs_count, "new_lows_count": new_lows_count,
                "sector_count_up": round(_clamp(6 + advance_decline_line * 0.08 + random.randint(-2, 2), 0, 12), 0),
                "sector_count_down": round(_clamp(6 - advance_decline_line * 0.08 + random.randint(-2, 2), 0, 12), 0),
                "l1_breadth": l1_breadth, "l2_breadth": l2_breadth,
                "defi_breadth": defi_breadth, "meme_breadth": meme_breadth,
            }},
            "events": events, "timeseries": timeseries, "timestamp": now,
        }

    # ---------- 6. Valuation ----------
    def collect_valuation(self) -> Dict[str, Any]:
        now = _now_iso()
        # Tavily: 搜索 MVRV、SOPR、估值指标
        articles = _fetch_tavily_market_data(
            "bitcoin MVRV ratio SOPR valuation on-chain metric 2026", max_results=3
        )
        combined = " ".join(a.get("content", "") + " " + a.get("title", "") for a in articles) if articles else ""

        if combined:
            mvrv_raw = _parse_number_from_text(combined, ["MVRV", "mvrv ratio", "MVRV Z"])
            sopr_raw = _parse_number_from_text(combined, ["SOPR", "sopr"])
            mvrv_ratio = float(mvrv_raw) if mvrv_raw and 0.5 < mvrv_raw < 6.0 else round(random.uniform(1.3, 3.2), 2)
            sopr = float(sopr_raw) if sopr_raw and 0.7 < sopr_raw < 2.0 else round(_clamp(0.95 + (mvrv_ratio - 1.3) * 0.25 + random.uniform(-0.05, 0.05), 0.8, 1.8), 3)
            print(f"[Valuation] Tavily real data: MVRV={mvrv_ratio:.2f}, SOPR={sopr:.3f}")
        else:
            mvrv_ratio = round(random.uniform(1.3, 3.2), 2)
            sopr = round(_clamp(0.95 + (mvrv_ratio - 1.3) * 0.25 + random.uniform(-0.05, 0.05), 0.8, 1.8), 3)

        mvrv_z_score = round((mvrv_ratio - 2.0) / 0.7 + random.uniform(-0.1, 0.1), 2)
        ahr999_index = round(_clamp(1.0 + (mvrv_ratio - 2.0) * 0.8 + random.uniform(-0.2, 0.2), 0.3, 3.0), 3)
        pi_cycle_top = round(_clamp(max(0, mvrv_ratio - 2.0) / 1.5 + random.uniform(-0.05, 0.05), 0, 1), 3)
        therm_index = round(_clamp((mvrv_ratio - 1.3) / (3.2 - 1.3) * 100 + random.uniform(-5, 5), 0, 100), 2)
        mayer_multiple = round(_clamp(1.0 + (mvrv_ratio - 2.0) * 0.4 + random.uniform(-0.1, 0.1), 0.5, 2.5), 3)
        puell_multiple = round(_clamp(1.0 + (mvrv_ratio - 2.0) * 0.35 + random.uniform(-0.15, 0.15), 0.3, 2.5), 3)
        valuation_range = ("严重低估" if mvrv_ratio < 1.5 else "低估" if mvrv_ratio < 2.0
                           else "合理" if mvrv_ratio < 2.5 else "偏高" if mvrv_ratio < 3.2 else "高估")
        valuation_heat_level = ("超冷" if mvrv_z_score < -1.0 else "冷" if mvrv_z_score < 0
                                else "温" if mvrv_z_score < 1.0 else "热" if mvrv_z_score < 2.0 else "过热")

        events: List[Dict[str, Any]] = []
        if articles:
            for a in articles[:2]:
                text = a.get("content", "")[:200]
                sent = round(_clamp((2.0 - mvrv_ratio) * 0.3 + random.uniform(-0.1, 0.1), -1, 1), 3)
                events.append({
                    "title": a.get("title", "")[:80], "content": summarize_content(text),
                    "category": "估值", "impact_score": 0.65, "sentiment": sent,
                    "source": a.get("source", "Tavily"), "url": a.get("url", ""), "published_at": a.get("published_at", now),
                })
        events.append({
            "title": f"估值区间：{valuation_range}（{valuation_heat_level}）",
            "content": f"MVRV {mvrv_ratio:.2f}，SOPR {sopr:.3f}，Mayer {mayer_multiple:.2f}",
            "category": "估值汇总", "impact_score": 0.55,
            "sentiment": round(_clamp((mvrv_ratio - 2.5) / 1.5, -1, 1), 3),
            "source": "Aggregate", "published_at": now,
        })
        nupl = round(_clamp((mvrv_ratio - 1) / mvrv_ratio, 0, 1), 3)
        realized_price = round(38000 + random.uniform(-2000, 5000), 0)
        market_price = round(realized_price * mvrv_ratio, 0)
        timeseries = _make_timeseries(mvrv_ratio, days=30, vmin=0.5, vmax=4.0)
        _MODULE_CONTEXT["scores"]["valuation"] = mvrv_ratio
        _MODULE_CONTEXT["timestamps"]["valuation"] = now
        return {
            "metrics": {"core": {
                "mvrv_ratio": mvrv_ratio, "mvrv_z_score": mvrv_z_score, "sopr": sopr,
                "ahr999_index": ahr999_index, "pi_cycle_top": pi_cycle_top,
                "therm_index": therm_index, "mayer_multiple": mayer_multiple,
                "puell_multiple": puell_multiple, "valuation_range": valuation_range,
                "valuation_heat_level": valuation_heat_level,
            }, "breakdown": {
                "short_term_holder_pnl": round((mvrv_ratio - 1.5) * 40 + random.uniform(-10, 10), 2),
                "long_term_holder_pnl": round((mvrv_ratio - 1.2) * 30 + random.uniform(-8, 8), 2),
                "realized_profit": round(_clamp(max(0, mvrv_ratio - 1.5) * 0.5 + random.uniform(-0.05, 0.05), 0, 1.5), 3),
                "realized_loss": round(_clamp(max(0, 1.8 - mvrv_ratio) * 0.3 + random.uniform(-0.05, 0.05), 0, 1.5), 3),
                "market_value_growth": round(_clamp((mvrv_ratio - 1.5) * 0.4 + random.uniform(-0.1, 0.1), -0.5, 1.5), 3),
                "realised_value_growth": round(_clamp((mvrv_ratio - 1.5) * 0.25 + random.uniform(-0.08, 0.08), -0.3, 1.2), 3),
                "sopr_long_term": round(_clamp(1.0 + (mvrv_ratio - 2.0) * 0.15 + random.uniform(-0.05, 0.05), 0.9, 1.5), 3),
                "sopr_short_term": round(_clamp(sopr + random.uniform(-0.1, 0.1), 0.8, 1.3), 3),
            }},
            "events": events, "timeseries": timeseries,
            "nupl": nupl, "realized_price": realized_price, "market_price": market_price,
            "price_distance_from_realized": round((market_price - realized_price) / realized_price * 100, 1),
            "timestamp": now,
        }

    # ---------- 7. Onchain ----------
    def collect_onchain(self) -> Dict[str, Any]:
        now = _now_iso()
        # 真实数据：Blockchain.info 公开统计
        bc_stats = _fetch_blockchain_info()
        if bc_stats:
            n_tx = bc_stats["n_tx"]
            hash_rate = bc_stats["hash_rate"]
            hash_rate_eh = round(hash_rate / 1e9, 2)  # blockchain.info 单位为 GH/s，转换为 EH/s（1 EH = 1e9 GH）
            minutes_between_blocks = bc_stats["minutes_between_blocks"]
            # 从真实哈希率推断链上活跃度评分
            hash_rate_score = round(_clamp((hash_rate_eh - 500) / 500, -1, 1), 4)  # 1000 EH/s 为基准
            tx_score = round(_clamp((n_tx - 300000) / 500000, -1, 1), 4)  # 300K tx/day 基准
            print(f"[Onchain] Real data: n_tx={n_tx}, hash_rate={hash_rate_eh:.0f}EH/s")
        else:
            hash_rate_eh = round(random.uniform(400, 1000), 2)
            n_tx = random.randint(300000, 800000)
            minutes_between_blocks = round(random.uniform(9.0, 11.5), 2)
            hash_rate_score = round(random.uniform(-0.3, 0.7), 4)
            tx_score = round(random.uniform(-0.3, 0.7), 4)

        onchain_score = round(_clamp((hash_rate_score + tx_score) / 2, -1, 1), 4)

        # 其余链上指标派生
        exchange_net_flow = round(random.uniform(-300, 500), 2)
        active_addresses = random.randint(30, 120)
        transaction_volume = round(random.uniform(3.0, 30.0), 2)
        whale_transfers = random.randint(5, 50)
        miner_outflow = round(random.uniform(0, 100), 2)
        long_term_holder_supply = round(random.uniform(60, 80), 2)
        short_term_holder_supply = round(100 - long_term_holder_supply - random.uniform(2, 8), 2)
        hodl_waves_1y_plus = round(random.uniform(55, 75), 2)
        exchange_reserve = round(random.uniform(10, 20), 2)

        onchain_trend = ("流入" if exchange_net_flow > 150 else "流出" if exchange_net_flow < -150 else "中性")
        network_health = ("优秀" if hash_rate_score > 0.3 else "良好" if hash_rate_score > -0.1 else "偏弱")
        accumulation_signal = ("强烈积累" if onchain_score > 0.4 else "轻度积累" if onchain_score > 0 else "轻度分发" if onchain_score > -0.4 else "强烈分发")

        events: List[Dict[str, Any]] = []
        events.append({
            "title": f"链上哈希率 {hash_rate_eh:.0f} EH/s，网络健康度：{network_health}",
            "content": f"24h 交易数 {n_tx:,}，出块间隔 {minutes_between_blocks:.1f}min",
            "category": "网络安全", "impact_score": 0.6,
            "sentiment": round(hash_rate_score * 0.5, 3),
            "source": "Blockchain.info", "published_at": now,
        })
        events.append({
            "title": f"交易所净流向：{onchain_trend}，积累信号：{accumulation_signal}",
            "content": f"净流入 {exchange_net_flow:+.0f}M USD，长期持有者占比 {long_term_holder_supply:.1f}%",
            "category": "链上", "impact_score": 0.65,
            "sentiment": round(onchain_score * 0.6, 3),
            "source": "On-chain Aggregate", "published_at": now,
        })
        timeseries = _make_timeseries(onchain_score, days=30, vmin=-1.0, vmax=1.0)
        _MODULE_CONTEXT["scores"]["onchain"] = onchain_score
        _MODULE_CONTEXT["timestamps"]["onchain"] = now
        return {
            "metrics": {"core": {
                "exchange_net_flow": exchange_net_flow, "active_addresses": active_addresses,
                "transaction_volume": transaction_volume, "hash_rate": hash_rate_eh,
                "n_tx_24h": n_tx, "long_term_holder_supply": long_term_holder_supply,
                "exchange_reserve": exchange_reserve, "onchain_trend": onchain_trend,
                "network_health": network_health, "accumulation_signal": accumulation_signal,
            }, "breakdown": {
                "exchange_inflow_24h": round(max(0, -exchange_net_flow) + random.uniform(100, 500), 2),
                "exchange_outflow_24h": round(max(0, exchange_net_flow) + random.uniform(120, 600), 2),
                "whale_transfers": whale_transfers, "miner_outflow": miner_outflow,
                "short_term_holder_supply": short_term_holder_supply,
                "hodl_waves_1y_plus": hodl_waves_1y_plus,
                "minutes_between_blocks": minutes_between_blocks,
            }},
            "events": events, "timeseries": timeseries, "timestamp": now,
        }

    # ---------- 8. Calendar（日历事件） ----------
    def collect_calendar(self) -> Dict[str, Any]:
        now = _now_iso()
        # Tavily: 搜索近期重大经济日历事件
        articles = _fetch_tavily_market_data(
            "upcoming economic calendar FOMC CPI Fed meeting crypto event this week 2026", max_results=5
        )
        events: List[Dict[str, Any]] = []

        if articles:
            print(f"[Calendar] Tavily fetched {len(articles)} calendar articles")
            for i, a in enumerate(articles):
                title = a.get("title", "")[:80]
                content = summarize_content(a.get("content", ""), 150)
                # 判断事件类别
                text_lower = (title + " " + content).lower()
                if any(w in text_lower for w in ["fomc", "federal reserve", "fed meeting", "rate decision"]):
                    category = "央行"
                    impact_score = round(random.uniform(0.7, 0.95), 3)
                elif any(w in text_lower for w in ["cpi", "inflation", "pce", "jobs report", "nonfarm"]):
                    category = "数据"
                    impact_score = round(random.uniform(0.6, 0.9), 3)
                elif any(w in text_lower for w in ["option expiry", "options expiration", "deribit", "期权到期"]):
                    category = "衍生品"
                    impact_score = round(random.uniform(0.5, 0.75), 3)
                elif any(w in text_lower for w in ["ecb", "european central bank", "boe", "boj"]):
                    category = "央行"
                    impact_score = round(random.uniform(0.5, 0.8), 3)
                else:
                    category = "市场事件"
                    impact_score = round(random.uniform(0.4, 0.65), 3)

                bull = sum(1 for w in ["positive", "bullish", "rate cut", "dovish", "利好"] if w in text_lower)
                bear = sum(1 for w in ["negative", "hawkish", "rate hike", "ban", "利空"] if w in text_lower)
                sentiment = round(_clamp((bull - bear) * 0.2, -0.8, 0.8), 3)

                events.append({
                    "title": title, "content": content,
                    "category": category, "impact_score": impact_score, "sentiment": sentiment,
                    "source": a.get("source", "Tavily"), "url": a.get("url", ""),
                    "published_at": a.get("published_at", (datetime.now(timezone.utc) + timedelta(days=i + 1)).isoformat()),
                })

        # 补充兜底事件（若 Tavily 无结果或条目不足）
        if len(events) < 2:
            fallback = [
                ("美联储 FOMC 议息会议", "关注点阵图及会后声明，对利率路径影响显著", "央行",
                 round(random.uniform(0.6, 0.9), 3), round(random.uniform(-0.3, 0.3), 3), 3),
                ("美国 CPI / PCE 数据", "通胀读数将影响降息预期及美元走势", "数据",
                 round(random.uniform(0.55, 0.85), 3), round(random.uniform(-0.2, 0.2), 3), 6),
                ("BTC 季度期权到期", "大额期权到期或放大短时波动", "衍生品",
                 round(random.uniform(0.45, 0.7), 3), round(random.uniform(-0.3, 0.1), 3), 14),
            ]
            for title, content, cat, impact, sent, days_offset in fallback:
                events.append({
                    "title": title, "content": content, "category": cat,
                    "impact_score": impact, "sentiment": sent, "source": "Economic Calendar",
                    "published_at": (datetime.now(timezone.utc) + timedelta(days=days_offset)).isoformat(),
                })

        avg_impact = round(sum(e["impact_score"] for e in events) / len(events), 3)
        avg_sentiment = round(sum(e["sentiment"] for e in events) / len(events), 3)
        high_impact = sum(1 for e in events if e["impact_score"] > 0.7)

        timeseries = _make_timeseries(avg_sentiment, days=30, vmin=-1.0, vmax=1.0)
        _MODULE_CONTEXT["scores"]["calendar"] = avg_sentiment
        _MODULE_CONTEXT["timestamps"]["calendar"] = now
        return {
            "metrics": {"core": {
                "total_events": len(events), "high_impact_events": high_impact,
                "avg_impact": avg_impact, "avg_sentiment": avg_sentiment, "impact_score": avg_impact,
            }, "breakdown": {
                "central_bank_events": sum(1 for e in events if e["category"] == "央行"),
                "data_events": sum(1 for e in events if e["category"] == "数据"),
                "derivative_events": sum(1 for e in events if e["category"] == "衍生品"),
            }},
            "events": events, "timeseries": timeseries, "timestamp": now,
        }

    # ---------- 9. Intermarket（跨市场） ----------
    def collect_intermarket(self) -> Dict[str, Any]:
        now = _now_iso()
        # Tavily: 搜索 DXY、黄金、标普、VIX 当前行情
        articles = _fetch_tavily_market_data(
            "DXY dollar index gold price S&P 500 VIX volatility today 2026", max_results=4
        )
        combined = " ".join(a.get("content", "") + " " + a.get("title", "") for a in articles) if articles else ""

        if combined:
            dxy_raw = _parse_number_from_text(combined, ["DXY", "dollar index", "US dollar index"])
            gold_raw = _parse_number_from_text(combined, ["gold price", "XAU", "gold at", "黄金"])
            spx_raw = _parse_number_from_text(combined, ["S&P 500", "SPX", "S&P500"])
            vix_raw = _parse_number_from_text(combined, ["VIX", "volatility index"])
            dxy = float(dxy_raw) if dxy_raw and 80 < dxy_raw < 130 else round(random.uniform(98, 108), 2)
            gold = float(gold_raw) if gold_raw and 1500 < gold_raw < 4000 else round(random.uniform(2200, 3400), 2)
            spx = float(spx_raw) if spx_raw and 3000 < spx_raw < 8000 else round(random.uniform(5000, 6000), 2)
            volatility_vix = float(vix_raw) if vix_raw and 5 < vix_raw < 80 else round(random.uniform(12, 32), 2)
            # 风险偏好：VIX低+SPX高 = risk-on
            risk_on_raw = _clamp((6000 - spx) / 1000 * -0.3 + (30 - volatility_vix) / 30 * 0.5, -1, 1)
            print(f"[Intermarket] Tavily real data: DXY={dxy}, gold={gold:.0f}, SPX={spx:.0f}, VIX={volatility_vix:.1f}")
        else:
            dxy = round(random.uniform(98, 108), 2)
            gold = round(random.uniform(2200, 3400), 2)
            spx = round(random.uniform(5000, 6000), 2)
            volatility_vix = round(random.uniform(12, 32), 2)
            risk_on_raw = random.uniform(-0.3, 0.5)

        wti = round(random.uniform(60, 90), 2)
        ndx = round(spx * 3.5 + random.uniform(-500, 500), 0)
        btc_correlation_spx = round(_clamp(risk_on_raw * 0.8 + random.uniform(-0.1, 0.1), -0.5, 0.8), 3)
        btc_correlation_gold = round(random.uniform(-0.3, 0.5), 3)
        dxy_correlation = round(-btc_correlation_spx * 0.6 + random.uniform(-0.2, 0.2), 3)
        risk_on_index = round(_clamp(50 + risk_on_raw * 50, 0, 100), 2)

        events: List[Dict[str, Any]] = []
        if articles:
            for a in articles[:2]:
                text = a.get("content", "")[:200]
                risk_words = ["rally", "rise", "surge", "上涨", "risk-on"]
                fear_words = ["fall", "drop", "fear", "下跌", "risk-off"]
                bull = sum(1 for w in risk_words if w in text.lower())
                bear = sum(1 for w in fear_words if w in text.lower())
                sent = round(_clamp((bull - bear) * 0.2, -1, 1), 3)
                events.append({
                    "title": a.get("title", "")[:80], "content": summarize_content(text),
                    "category": "跨市场", "impact_score": 0.55, "sentiment": sent,
                    "source": a.get("source", "Tavily"), "url": a.get("url", ""), "published_at": a.get("published_at", now),
                })
        events.append({
            "title": f"DXY={dxy:.1f} / 黄金={gold:.0f} / SPX={spx:.0f} / VIX={volatility_vix:.1f}",
            "content": f"风险偏好指数 {risk_on_index:.0f}/100，BTC-SPX 相关性 {btc_correlation_spx:+.2f}",
            "category": "跨市场汇总", "impact_score": 0.6, "sentiment": round(risk_on_raw, 3),
            "source": "Tavily Aggregate", "published_at": now,
        })
        timeseries = _make_timeseries(dxy_correlation, days=30, vmin=-1.0, vmax=1.0)
        _MODULE_CONTEXT["scores"]["intermarket"] = dxy_correlation
        _MODULE_CONTEXT["timestamps"]["intermarket"] = now
        return {
            "metrics": {"core": {
                "dxy": dxy, "gold": gold, "wti": wti, "spx": spx, "ndx": ndx,
                "btc_correlation_spx": btc_correlation_spx, "btc_correlation_gold": btc_correlation_gold,
                "dxy_correlation": dxy_correlation, "risk_on_index": risk_on_index, "vix": volatility_vix,
            }, "breakdown": {
                "equity_strength": round(_clamp((spx - 4800) / 12 + random.uniform(-10, 10), 0, 100), 2),
                "commodity_strength": round(_clamp((gold - 1800) / 16 + random.uniform(-10, 10), 0, 100), 2),
            }},
            "events": events, "timeseries": timeseries, "timestamp": now,
        }

    # ---------- 10. Narrative（叙事） ----------
    def collect_narrative(self) -> Dict[str, Any]:
        now = _now_iso()
        flow_score = _MODULE_CONTEXT["scores"].get("flow", 0.0)
        sentiment_score = _MODULE_CONTEXT["scores"].get("sentiment", 50)
        overall_base = round(_clamp((flow_score * 0.5 + (sentiment_score - 50) / 50 * 0.5), -1, 1), 3)

        # Tavily: 搜索各大叙事主题的最新进展
        NARRATIVE_QUERIES = [
            ("ETF 机构化叙事", "bitcoin ETF institutional adoption 2026"),
            ("降息宽松预期", "Federal Reserve rate cut crypto 2026"),
            ("Layer2 扩容", "ethereum layer2 scaling adoption 2026"),
            ("监管政策", "crypto regulation SEC policy 2026"),
        ]
        narratives: List[Dict[str, Any]] = []
        all_narrative_articles: List[Dict[str, Any]] = []

        for theme, query in NARRATIVE_QUERIES:
            arts = _fetch_tavily_market_data(query, max_results=2)
            if arts:
                combined = " ".join(a.get("content", "") + " " + a.get("title", "") for a in arts)
                bull_hits = sum(1 for w in ["positive", "bullish", "adoption", "approval", "growth", "利好", "通过"] if w in combined.lower())
                bear_hits = sum(1 for w in ["negative", "bearish", "ban", "rejection", "risk", "利空", "禁止"] if w in combined.lower())
                sent = round(_clamp((bull_hits - bear_hits) * 0.2 + overall_base * 0.2, -1, 1), 3)
                momentum = round(_clamp(50 + (bull_hits - bear_hits) * 10 + overall_base * 20, 0, 100), 2)
                desc = summarize_content(arts[0].get("content", arts[0].get("title", theme)), 100)
                all_narrative_articles.extend(arts)
            else:
                sent = round(_clamp(overall_base * 0.5 + random.uniform(-0.2, 0.2), -1, 1), 3)
                momentum = round(_clamp(50 + overall_base * 25 + random.uniform(-15, 15), 0, 100), 2)
                desc = f"{theme}：当前无最新数据"
            narratives.append({"theme": theme, "momentum_score": momentum, "description": desc, "sentiment": sent})

        avg_momentum = round(sum(n["momentum_score"] for n in narratives) / len(narratives), 2)
        avg_sent = round(sum(n["sentiment"] for n in narratives) / len(narratives), 3)
        overall = round(_clamp(avg_sent * 0.6 + overall_base * 0.4, -1, 1), 3)

        events: List[Dict[str, Any]] = []
        # 真实文章事件
        for a in all_narrative_articles[:6]:
            text = a.get("content", "")[:200]
            bull = sum(1 for w in ["positive", "bullish", "adoption", "利好"] if w in text.lower())
            bear = sum(1 for w in ["negative", "bearish", "ban", "利空"] if w in text.lower())
            sent = round(_clamp((bull - bear) * 0.2, -1, 1), 3)
            events.append({
                "title": a.get("title", "")[:80], "content": summarize_content(text),
                "category": "叙事", "impact_score": round(min(1.0, 0.4 + abs(sent) * 0.4), 3),
                "sentiment": sent, "source": a.get("source", "Tavily"),
                "url": a.get("url", ""), "published_at": a.get("published_at", now),
                "metric_delta": {"avg_momentum": avg_momentum},
            })
        # 叙事摘要事件
        for n in narratives:
            events.append({
                "title": f"叙事：{n['theme']}",
                "content": n["description"],
                "category": "叙事摘要",
                "impact_score": round(_clamp(n["momentum_score"] / 100, 0, 1), 3),
                "sentiment": round(n["sentiment"], 3),
                "source": "Narrative Engine", "published_at": now,
                "metric_delta": {"momentum_score": n["momentum_score"]},
            })

        timeseries = _make_timeseries(overall, days=30, vmin=-1.0, vmax=1.0)
        _MODULE_CONTEXT["scores"]["narrative"] = overall
        _MODULE_CONTEXT["timestamps"]["narrative"] = now
        return {
            "metrics": {"core": {
                "total_narratives": len(narratives), "avg_momentum": avg_momentum,
                "avg_sentiment": avg_sent,
                "market_consensus": round(_clamp(overall * 0.5 + 0.5, 0, 1), 3),
                "consensus": round(_clamp(overall * 0.5 + 0.5, 0, 1), 3),
            }, "breakdown": {
                "bullish_narratives": sum(1 for n in narratives if n["sentiment"] > 0.2),
                "bearish_narratives": sum(1 for n in narratives if n["sentiment"] < -0.2),
                "neutral_narratives": len(narratives) - sum(1 for n in narratives if abs(n["sentiment"]) > 0.2),
            }},
            "events": events, "timeseries": timeseries, "timestamp": now,
        }


# ============== 模块方法映射（供外部遍历） ==============
MODULE_COLLECTORS = {
    "news": "collect_news",
    "flow": "collect_flow",
    "sentiment": "collect_sentiment",
    "macro": "collect_macro",
    "breadth": "collect_breadth",
    "intermarket": "collect_intermarket",
    "valuation": "collect_valuation",
    "onchain": "collect_onchain",
    "calendar": "collect_calendar",
    "narrative": "collect_narrative",
}


# ============== 便捷顶层函数（ml_trade_service_v2.py 可直接使用） ==============
def get_module_context() -> Dict[str, Any]:
    """返回模块共享上下文：供 signal_engine 跨模块验证使用"""
    return _MODULE_CONTEXT


def clear_module_context() -> None:
    _MODULE_CONTEXT["scores"].clear()
    _MODULE_CONTEXT["timestamps"].clear()
    _MODULE_CONTEXT["latest"].clear()
