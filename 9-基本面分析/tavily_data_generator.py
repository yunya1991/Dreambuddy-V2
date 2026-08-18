import json
import os
import sys
import random
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "core_engine"))
from least_resistance import run_module_analysis, compute_resistance_3d

STORAGE_DIR = os.path.join(BASE_DIR, "storage")
SNAPSHOT_FILE = os.path.join(STORAGE_DIR, "latest_snapshot.json")

TAVILY_API_KEY = "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"
TAVILY_ENDPOINT = "https://api.tavily.com/search"

POSITIVE_KW = [
    "bullish", "rally", "surge", "approval", "inflow", "positive", "adoption",
    "利好", "上涨", "突破", "机构", "流入",
]
NEGATIVE_KW = [
    "bearish", "crash", "selloff", "ban", "hack", "fraud", "liquidation",
    "outflow", "reject", "negative",
    "利空", "下跌", "暴跌", "监管", "禁令", "清算",
]

NEW_QUERIES = {
    "news": ["crypto market news", "bitcoin ethereum price analysis", "blockchain industry"],
    "flow": ["bitcoin ETF inflow", "stablecoin supply", "institutional crypto capital flow"],
    "sentiment": ["crypto market sentiment", "fear greed index", "investor psychology cryptocurrency"],
    "macro": ["fed interest rate decision", "us dollar index crypto", "macroeconomic inflation recession"],
}

MODULE_KEYWORDS = {
    "news": ["news", "price", "industry", "market", "新闻", "价格", "行业", "市场"],
    "flow": ["inflow", "outflow", "capital", "supply", "etf", "资金", "流入", "流出", "供应"],
    "sentiment": ["sentiment", "fear", "greed", "psychology", "情绪", "恐惧", "贪婪"],
    "macro": ["fed", "interest", "inflation", "recession", "dollar", "宏观", "利率", "通胀", "衰退", "美元"],
}


def _ensure_storage():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR, exist_ok=True)


def analyze_sentiment_keywords(text: str) -> float:
    if not text:
        return 0.0
    low = text.lower()
    pos = sum(low.count(k.lower()) for k in POSITIVE_KW)
    neg = sum(low.count(k.lower()) for k in NEGATIVE_KW)
    total = pos + neg
    if total == 0:
        return 0.0
    score = (pos - neg) / total
    return max(-1.0, min(1.0, score))


def classify_event_category(text: str) -> str:
    if not text:
        return "news"
    low = text.lower()
    best = "news"
    best_count = 0
    for module, kws in MODULE_KEYWORDS.items():
        c = sum(low.count(k.lower()) for k in kws)
        if c > best_count:
            best_count = c
            best = module
    return best if best_count > 0 else "news"


def generate_mock_events(query: str) -> list:
    events = []
    now = datetime.utcnow()
    samples = [
        f"Breaking news: {query} shows bullish momentum as institutional inflow accelerates.",
        f"Analysis: {query} faces regulatory scrutiny, causing short-term selloff.",
        f"Update: {query} market sentiment remains positive with stablecoin supply growing.",
        f"Report: {query} — fed decision impacts risk assets, dollar strengthens.",
        f"News: {query} sees strong adoption signals and price rally continues.",
        f"Alert: {query} experiences liquidation pressure and negative narrative.",
        f"Digest: {query} blockchain activity surges, investor psychology optimistic.",
        f"Insight: {query} macro backdrop mixed, inflation data drives volatility.",
    ]
    for i, content in enumerate(samples):
        ts = now.isoformat() + "Z"
        sentiment = analyze_sentiment_keywords(content)
        category = classify_event_category(content)
        events.append({
            "timestamp": ts,
            "title": f"[{category.upper()}] {query[:40]} sample-{i+1}",
            "content": content,
            "sentiment": sentiment,
            "category": category,
            "impact_score": abs(sentiment) * 100,
        })
    return events


def fetch_tavily_news(query: str) -> list:
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": False,
        "include_raw_content": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        results = body.get("results", []) or []
        events = []
        now = datetime.utcnow().isoformat() + "Z"
        for r in results:
            title = r.get("title") or r.get("url") or query
            content = r.get("content") or title
            sentiment = analyze_sentiment_keywords(content)
            category = classify_event_category(content)
            events.append({
                "timestamp": now,
                "title": title,
                "content": content,
                "sentiment": sentiment,
                "category": category,
                "impact_score": abs(sentiment) * 100,
            })
        if not events:
            return generate_mock_events(query)
        return events
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception) as e:
        print(f"[tavily] fetch 失败，回落到模拟数据: {e}")
        return generate_mock_events(query)


def _gather_module_events(module_name: str, use_tavily: bool) -> list:
    queries = NEW_QUERIES.get(module_name, [])
    all_events = []
    for q in queries:
        if use_tavily:
            evs = fetch_tavily_news(q)
        else:
            evs = generate_mock_events(q)
        all_events.extend(evs)
    return all_events


def _compute_module_metrics(module_name: str, events: list):
    sentiments = [e.get("sentiment", 0.0) for e in events] if events else [0.0]
    mean_sent = sum(sentiments) / len(sentiments)
    heat = min(1.0, len(events) / 20.0)
    if module_name == "flow":
        flow_idx = 50 + mean_sent * 50
        sentiment_idx = 50 + mean_sent * 25
    else:
        sentiment_idx = 50 + mean_sent * 50
        flow_idx = 50 + mean_sent * 25
    high_count = sum(1 for s in sentiments if abs(s) > 0.5)
    stress = "high" if events and (high_count / max(1, len(events))) > 0.4 else "normal"
    raw_score = mean_sent
    return raw_score, sentiment_idx, flow_idx, heat, stress


def run_full_pipeline(use_tavily: bool = True) -> dict:
    _ensure_storage()
    ts = datetime.utcnow().isoformat() + "Z"
    modules_result = {}
    overall_scores = []
    weights = {"news": 0.25, "flow": 0.30, "sentiment": 0.20, "macro": 0.25}
    for module in ["news", "flow", "sentiment", "macro"]:
        events = _gather_module_events(module, use_tavily)
        raw_score, sentiment_idx, flow_idx, heat, stress = _compute_module_metrics(module, events)
        result = run_module_analysis(module, events, raw_score, sentiment_idx, flow_idx, heat, stress)
        modules_result[module] = result
        overall_scores.append((raw_score, weights.get(module, 0.25)))
    total_w = sum(w for _, w in overall_scores)
    avg_score = sum(s * w for s, w in overall_scores) / total_w if total_w > 0 else 0.0
    overall_r3d = compute_resistance_3d(avg_score, [])
    snapshot = {
        "ts": ts,
        "overall": {
            "raw_score": avg_score,
            "direction": overall_r3d["direction"],
            "velocity": overall_r3d["velocity"],
            "acceleration": overall_r3d["acceleration"],
            "confidence": overall_r3d["confidence"],
        },
        "modules": modules_result,
    }
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return snapshot


def get_latest_snapshot():
    if not os.path.exists(SNAPSHOT_FILE):
        return None
    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


if __name__ == "__main__":
    use_tavily = "--no-tavily" not in sys.argv
    if "--seed" in sys.argv:
        try:
            idx = sys.argv.index("--seed")
            random.seed(int(sys.argv[idx + 1]))
        except Exception:
            pass
    snap = run_full_pipeline(use_tavily=use_tavily)
    print(json.dumps({
        "ts": snap["ts"],
        "overall": snap["overall"],
        "modules": {k: {"direction": v["resistance_3d"]["direction"],
                        "sentiment_index": round(v["metrics"]["sentiment_index"], 2),
                        "heat": round(v["metrics"]["heat"], 2),
                        "recommendation": v["signals"]["recommendation"]["type"]}
                   for k, v in snap["modules"].items()},
    }, ensure_ascii=False, indent=2))
    print("tavily_data_generator 写入完成" if False else "tavily_data_generator 执行完成")
