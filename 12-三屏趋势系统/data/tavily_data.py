"""三屏趋势系统 — Path B Tavily 基本面数据采集模块

通过 Tavily API 实时搜索获取 4 个基本面维度的数据：
    C. 矿工经济 — hashrate, production cost, Puell Multiple, MPI
    D. 链上估值 — MVRV, SOPR, NUPL, realized price
    E. 宏观金融 — Fed rate, DXY, US10Y, global M2
    F. 跨市场   — S&P 500, gold, BTC dominance, risk appetite

数据采集后通过算法评分，输出与 annotation JSON 兼容的格式，
供 fundamental_screen1.py 的 7 维分析框架使用。

设计原则：
    - 纯算法驱动，不依赖 AI
    - Tavily 搜索 + 文本解析 + 阈值评分
    - 30 分钟缓存避免 API 浪费
    - 解析失败时返回 NEUTRAL，不阻断流程
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any

# ── 配置 ──
TAVILY_API_KEY = os.environ.get(
    "TAVILY_API_KEY",
    "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",
)

# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache", "tavily")
CACHE_DURATION_SEC = 1800  # 30 分钟

# 权威域名白名单
FINANCE_DOMAINS = [
    "coindesk.com",
    "cointelegraph.com",
    "coinmarketcap.com",
    "bloomberg.com",
    "reuters.com",
    "finance.yahoo.com",
    "glassnode.com",
    "cryptoquant.com",
    "blockchain.com",
    "tradingview.com",
    "investopedia.com",
    "defillama.com",
]


# ── Tavily 客户端 ──

def _get_tavily_client():
    """获取 Tavily 客户端（优先 SDK，回退 HTTP）"""
    try:
        from tavily import TavilyClient
        return TavilyClient(api_key=TAVILY_API_KEY), "sdk"
    except ImportError:
        return None, "http"


def _tavily_search_http(query: str, max_results: int = 5, topic: str = "news") -> dict:
    """HTTP 直调 Tavily API（SDK 不可用时的回退）"""
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": max_results,
        "topic": topic,
        "search_depth": "basic",
        "include_answer": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tavily_search(query: str, max_results: int = 5, topic: str = "news") -> Optional[dict]:
    """
    Tavily 搜索（带缓存）

    返回:
        {"answer": str, "results": [{"title", "url", "content", "score", "published_date"}], ...}
        失败返回 None
    """
    # 缓存键
    cache_key = hashlib.md5(f"{query}:{topic}:{max_results}".encode()).hexdigest()
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    # 检查缓存
    if os.path.exists(cache_file):
        file_age = time.time() - os.path.getmtime(cache_file)
        if file_age < CACHE_DURATION_SEC:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

    # 调用 API
    try:
        client, mode = _get_tavily_client()
        if client:
            result = client.search(
                query=query,
                max_results=max_results,
                topic=topic,
                search_depth="basic",
                include_answer=True,
            )
        else:
            result = _tavily_search_http(query, max_results, topic)

        # 写缓存
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)

        return result
    except Exception as e:
        # 尝试读取过期缓存
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return None


# ── 文本解析工具 ──

def _parse_number_near(text: str, keywords: List[str], default: float = 0) -> float:
    """
    在文本中搜索关键词附近的数字

    参数:
        text: 搜索文本
        keywords: 关键词列表（如 ["DXY", "dollar index"]）
        default: 未找到时的默认值

    返回:
        找到的数字，或 default
    """
    if not text:
        return default

    text_lower = text.lower()

    def _is_year(val: float) -> bool:
        """过滤年份（2020-2030）"""
        return 2020 <= val <= 2030

    for kw in keywords:
        kw_lower = kw.lower()
        idx = text_lower.find(kw_lower)
        if idx >= 0:
            # 在关键词之后搜索（跳过关键词本身）
            search_start = idx + len(kw_lower)
            window = text[search_start:search_start + 200]
            # 匹配浮点数（含负数和小数）
            numbers = re.findall(r'[-]?\d+\.?\d*', window)
            if numbers:
                for n in numbers:
                    val = float(n)
                    # 跳过年份和过小的值
                    if _is_year(val):
                        continue
                    if abs(val) > 0.001:
                        return val
    return default


def _extract_all_text(result: dict) -> str:
    """从 Tavily 响应中提取所有文本"""
    if not result:
        return ""
    parts = []
    if result.get("answer"):
        parts.append(result["answer"])
    for r in result.get("results", []):
        if r.get("title"):
            parts.append(r["title"])
        if r.get("content"):
            parts.append(r["content"])
    return " ".join(parts)


# ── 4 维数据采集与评分 ──

def collect_miner_economics() -> dict:
    """
    维度 C：矿工经济

    搜索指标：Hashrate, Production Cost, Puell Multiple, MPI
    评分规则：综合判断矿工行为（囤积/抛售/投降）
    """
    queries = [
        "Bitcoin hash rate difficulty adjustment 2026",
        "Bitcoin miner production cost break even 2026",
        "Bitcoin Puell Multiple current 2026",
    ]

    all_text = ""
    for q in queries:
        result = tavily_search(q, max_results=3, topic="news")
        all_text += _extract_all_text(result) + " "

    if not all_text.strip():
        return _make_dim_result("C_miner", False, 0, "NEUTRAL", "Tavily 搜索无结果")

    # 解析关键指标
    hashrate = _parse_number_near(all_text, ["hash rate", "hashrate", "EH/s"], 0)
    puell_multiple = _parse_number_near(all_text, ["Puell Multiple", "puell"], 0)
    production_cost = _parse_number_near(all_text, ["production cost", "break even", "mining cost"], 0)

    # 评分逻辑
    score = 0
    signals = []

    # Puell Multiple < 0.5 → 矿工投降，底部信号（看多）
    if 0 < puell_multiple < 0.5:
        score += 8
        signals.append("Puell Multiple 低位(矿工投降→底部信号)")
    elif puell_multiple > 4:
        score -= 8
        signals.append("Puell Multiple 高位(矿工盈利丰厚→顶部信号)")
    elif 0 < puell_multiple <= 1.0:
        score += 3
        signals.append("Puell Multiple 偏低(矿工收入承压)")

    # 综合文本情绪
    bearish_words = ["capitulation", "miner selling", "shutdown", "distress", "投降", "关机"]
    bullish_words = ["accumulation", "holding", "confident", "囤积", "信心"]
    bear_count = sum(1 for w in bearish_words if w.lower() in all_text.lower())
    bull_count = sum(1 for w in bullish_words if w.lower() in all_text.lower())

    if bear_count > bull_count:
        score -= 5
        signals.append(f"文本情绪偏空({bear_count} vs {bull_count})")
    elif bull_count > bear_count:
        score += 5
        signals.append(f"文本情绪偏多({bull_count} vs {bear_count})")

    direction = "BULL" if score > 3 else ("BEAR" if score < -3 else "NEUTRAL")
    reasoning = f"矿工经济分析：Puell={puell_multiple:.2f}, Hashrate={hashrate:.0f}EH/s, " + "; ".join(signals)

    return _make_dim_result("C_miner", True, score, direction, reasoning, {
        "hashrate_ehs": hashrate,
        "puell_multiple": puell_multiple,
        "production_cost": production_cost,
    })


def collect_onchain_valuation() -> dict:
    """
    维度 D：链上估值

    搜索指标：MVRV, SOPR, NUPL, Realized Price
    评分规则：链上估值过高→看空，过低→看多
    """
    queries = [
        "Bitcoin MVRV ratio current 2026",
        "Bitcoin SOPR spent output profit ratio 2026",
        "Bitcoin NUPL net unrealized profit loss 2026",
    ]

    all_text = ""
    for q in queries:
        result = tavily_search(q, max_results=3, topic="news")
        all_text += _extract_all_text(result) + " "

    if not all_text.strip():
        return _make_dim_result("D_onchain", False, 0, "NEUTRAL", "Tavily 搜索无结果")

    # 解析
    mvrv = _parse_number_near(all_text, ["MVRV", "market value to realized value"], 0)
    sopr = _parse_number_near(all_text, ["SOPR", "spent output profit ratio"], 0)
    nupl = _parse_number_near(all_text, ["NUPL", "net unrealized profit loss"], 0)

    score = 0
    signals = []

    # MVRV 评分
    if mvrv > 0:
        if mvrv > 3.5:
            score -= 10
            signals.append(f"MVRV={mvrv:.2f} 过热(>3.5)")
        elif mvrv > 2.5:
            score -= 5
            signals.append(f"MVRV={mvrv:.2f} 偏高")
        elif mvrv < 1.0:
            score += 10
            signals.append(f"MVRV={mvrv:.2f} 低估(<1.0)")
        elif mvrv < 1.5:
            score += 5
            signals.append(f"MVRV={mvrv:.2f} 偏低")

    # SOPR 评分
    if sopr > 0:
        if sopr > 1.1:
            score -= 5
            signals.append(f"SOPR={sopr:.2f} 持有者盈利卖出(>1.1)")
        elif sopr < 0.95:
            score += 5
            signals.append(f"SOPR={sopr:.2f} 持有者亏损卖出(<0.95)")

    # NUPL 评分
    if nupl != 0:
        if nupl > 0.5:
            score -= 5
            signals.append(f"NUPL={nupl:.2f} 极度贪婪(>0.5)")
        elif nupl < -0.1:
            score += 5
            signals.append(f"NUPL={nupl:.2f} 恐惧/投降(<-0.1)")

    direction = "BULL" if score > 3 else ("BEAR" if score < -3 else "NEUTRAL")
    reasoning = f"链上估值：MVRV={mvrv:.2f}, SOPR={sopr:.2f}, NUPL={nupl:.2f}; " + "; ".join(signals)

    return _make_dim_result("D_onchain", True, score, direction, reasoning, {
        "mvrv": mvrv,
        "sopr": sopr,
        "nupl": nupl,
    })


def collect_macro_finance() -> dict:
    """
    维度 E：宏观金融

    搜索指标：Fed Rate, DXY, US 10Y Yield, Global M2
    评分规则：流动性宽松→看多，紧缩→看空
    """
    queries = [
        "Federal Reserve interest rate decision 2026",
        "DXY dollar index current 2026",
        "US 10 year treasury yield 2026",
    ]

    all_text = ""
    for q in queries:
        result = tavily_search(q, max_results=3, topic="news")
        all_text += _extract_all_text(result) + " "

    if not all_text.strip():
        return _make_dim_result("E_macro", False, 0, "NEUTRAL", "Tavily 搜索无结果")

    # 解析
    dxy = _parse_number_near(all_text, ["DXY", "dollar index"], 0)
    us10y = _parse_number_near(all_text, ["10 year", "10-year", "10Y", "treasury yield"], 0)

    score = 0
    signals = []

    # DXY 评分：美元走强→利空BTC，走弱→利多
    if dxy > 0:
        if dxy > 105:
            score -= 8
            signals.append(f"DXY={dxy:.1f} 美元强势(>105)")
        elif dxy < 95:
            score += 8
            signals.append(f"DXY={dxy:.1f} 美元弱势(<95)")
        elif dxy < 100:
            score += 3
            signals.append(f"DXY={dxy:.1f} 美元偏弱")

    # 10Y 评分：高利率→利空风险资产
    if us10y > 0:
        if us10y > 5.0:
            score -= 6
            signals.append(f"10Y={us10y:.2f}% 高利率环境(>5%)")
        elif us10y < 3.0:
            score += 6
            signals.append(f"10Y={us10y:.2f}% 低利率环境(<3%)")

    # 文本情绪
    dovish_words = ["rate cut", "dovish", "pause", "鸽派", "降息", "暂停加息"]
    hawkish_words = ["rate hike", "hawkish", "tightening", "鹰派", "加息", "缩表"]
    dovish_count = sum(1 for w in dovish_words if w.lower() in all_text.lower())
    hawkish_count = sum(1 for w in hawkish_words if w.lower() in all_text.lower())

    if dovish_count > hawkish_count:
        score += 5
        signals.append(f"货币政策偏鸽({dovish_count} vs {hawkish_count})")
    elif hawkish_count > dovish_count:
        score -= 5
        signals.append(f"货币政策偏鹰({hawkish_count} vs {dovish_count})")

    direction = "BULL" if score > 3 else ("BEAR" if score < -3 else "NEUTRAL")
    reasoning = f"宏观金融：DXY={dxy:.1f}, 10Y={us10y:.2f}%; " + "; ".join(signals)

    return _make_dim_result("E_macro", True, score, direction, reasoning, {
        "dxy": dxy,
        "us10y": us10y,
    })


def collect_cross_market() -> dict:
    """
    维度 F：跨市场

    搜索指标：S&P 500 trend, Gold trend, BTC dominance, Risk appetite
    评分规则：风险偏好高→利好BTC，Risk-off→利空
    """
    queries = [
        "S&P 500 stock market trend today 2026",
        "gold price trend 2026",
        "crypto market risk appetite sentiment 2026",
    ]

    all_text = ""
    for q in queries:
        result = tavily_search(q, max_results=3, topic="news")
        all_text += _extract_all_text(result) + " "

    if not all_text.strip():
        return _make_dim_result("F_cross_market", False, 0, "NEUTRAL", "Tavily 搜索无结果")

    score = 0
    signals = []

    # 文本情绪分析
    risk_on_words = ["risk on", "rally", "bull market", "optimism", "反弹", "上涨", "乐观"]
    risk_off_words = ["risk off", "selloff", "correction", "fear", "恐慌", "下跌", "抛售"]

    risk_on_count = sum(1 for w in risk_on_words if w.lower() in all_text.lower())
    risk_off_count = sum(1 for w in risk_off_words if w.lower() in all_text.lower())

    if risk_on_count > risk_off_count:
        score += 5
        signals.append(f"市场风险偏好偏高(Risk-On {risk_on_count} vs {risk_off_count})")
    elif risk_off_count > risk_on_count:
        score -= 5
        signals.append(f"市场风险偏好偏低(Risk-Off {risk_off_count} vs {risk_on_count})")

    # 黄金趋势：避险资产走强通常意味着风险偏好下降
    gold_bullish = any(w in all_text.lower() for w in ["gold rally", "gold surge", "黄金上涨", "金价飙升"])
    gold_bearish = any(w in all_text.lower() for w in ["gold drop", "gold decline", "黄金下跌"])

    if gold_bullish:
        score -= 3
        signals.append("黄金走强(避险情绪上升)")
    elif gold_bearish:
        score += 3
        signals.append("黄金走弱(风险偏好上升)")

    direction = "BULL" if score > 2 else ("BEAR" if score < -2 else "NEUTRAL")
    reasoning = "; ".join(signals) if signals else "无明显跨市场信号"

    return _make_dim_result("F_cross_market", True, score, direction, reasoning, {
        "risk_on_signals": risk_on_count,
        "risk_off_signals": risk_off_count,
    })


# ── 统一输出格式 ──

def _make_dim_result(
    dim_name: str,
    available: bool,
    score: float,
    signal: str,
    reasoning: str,
    metrics: Optional[Dict] = None,
) -> dict:
    """构造与 annotation JSON 兼容的维度结果"""
    weights = {
        "C_miner": 0.15,
        "D_onchain": 0.15,
        "E_macro": 0.10,
        "F_cross_market": 0.05,
    }
    now = datetime.now(timezone.utc).isoformat()
    return {
        "available": available,
        "dimension": dim_name,
        "weight": weights.get(dim_name, 0),
        "score": score,
        "signal": signal,
        "reasoning": reasoning,
        "metrics": metrics or {},
        "generated_at": now,
        "freshness_days": 1,  # Tavily 数据当天有效
        "source": "tavily_api",
    }


def fetch_all_tavily_dimensions() -> Dict[str, dict]:
    """
    一次性采集全部 4 个 Tavily 维度

    返回:
        {
            "C_miner": {...},
            "D_onchain": {...},
            "E_macro": {...},
            "F_cross_market": {...},
        }
    """
    return {
        "C_miner": collect_miner_economics(),
        "D_onchain": collect_onchain_valuation(),
        "E_macro": collect_macro_finance(),
        "F_cross_market": collect_cross_market(),
    }
