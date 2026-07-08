#!/usr/bin/env python3
"""
Tavily 宏观数据集成 - 为易经推理模型提供真实宏观数据
通过 Tavily Search API 获取最新宏观经济、市场新闻等数据
"""
import json
import os
import time
from typing import Dict, List, Optional
from datetime import datetime, timezone
from pathlib import Path


CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "tavily"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CACHE_FILE = CONFIG_DIR / "macro_cache.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.tavily.com",
    "cache_ttl_seconds": 3600,
    "max_results": 10,
}

DEFAULT_SEARCH_TOPICS = [
    "BTC Bitcoin macro economic outlook",
    "Federal Reserve interest rate policy latest",
    "US CPI inflation data latest",
    "Bitcoin ETF flow institutional",
    "Crypto market regulation news",
    "Global macroeconomic indicators USD dollar index",
]


def _load_config() -> Dict:
    config_path = CONFIG_DIR / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    return DEFAULT_CONFIG.copy()


def _save_config(cfg: Dict) -> None:
    config_path = CONFIG_DIR / "config.json"
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(config_path, 0o600)


def configure(api_key: str = None) -> Dict:
    """配置 Tavily API"""
    cfg = _load_config()
    if api_key is not None:
        cfg["api_key"] = api_key
    _save_config(cfg)
    safe_cfg = {k: v for k, v in cfg.items()}
    if safe_cfg.get("api_key"):
        safe_cfg["api_key"] = safe_cfg["api_key"][:8] + "..."
    return safe_cfg


def _load_cache() -> Dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: Dict) -> None:
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def tavily_search(query: str, max_results: int = None,
                  search_depth: str = "basic",
                  topic: str = "general") -> Dict:
    """
    调用 Tavily Search API

    Args:
        query: 搜索查询
        max_results: 最大结果数
        search_depth: basic / advanced
        topic: general / news / finance

    Returns:
        搜索结果
    """
    import urllib.request
    import urllib.error

    cfg = _load_config()
    api_key = cfg["api_key"]
    if not api_key:
        return {"ok": False, "error": "tavily api key not configured"}

    max_results = max_results or cfg["max_results"]

    cache = _load_cache()
    cache_key = f"{query}_{max_results}_{search_depth}_{topic}"
    now = time.time()

    if cache_key in cache:
        cached = cache[cache_key]
        if now - cached.get("ts", 0) < cfg["cache_ttl_seconds"]:
            return {"ok": True, "cached": True, "results": cached.get("results", [])}

    body = json.dumps({
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "topic": topic,
        "include_answer": True,
        "include_raw_content": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        cfg["base_url"] + "/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results", [])
        answer = data.get("answer", "")

        cache[cache_key] = {
            "ts": now,
            "query": query,
            "results": results,
            "answer": answer,
        }
        _save_cache(cache)

        return {
            "ok": True,
            "cached": False,
            "query": query,
            "answer": answer,
            "results": results,
            "count": len(results),
        }
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fetch_macro_data(topics: List[str] = None) -> Dict:
    """
    获取宏观数据（多个主题聚合）

    Args:
        topics: 搜索主题列表（None 使用默认）

    Returns:
        聚合后的宏观数据
    """
    topics = topics or DEFAULT_SEARCH_TOPICS
    all_results = []
    answers = {}

    for topic in topics:
        r = tavily_search(topic, max_results=5, topic="news")
        if r.get("ok"):
            all_results.extend(r.get("results", []))
            if r.get("answer"):
                answers[topic] = r["answer"]
        time.sleep(0.2)

    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "topics": topics,
        "total_results": len(all_results),
        "answers": answers,
        "results": all_results[:20],
        "sources": list(set(r.get("url", "").split("/")[2] for r in all_results if r.get("url")))[:10],
    }


def get_macro_summary() -> Dict:
    """
    获取宏观数据摘要（供 BCRM 推理使用）

    Returns:
        宏观数据摘要
    """
    cache = _load_cache()
    latest_key = None
    latest_ts = 0

    for key, val in cache.items():
        if val.get("ts", 0) > latest_ts:
            latest_ts = val["ts"]
            latest_key = key

    if not latest_key:
        return {"ok": False, "error": "no cached macro data, run fetch first"}

    cfg = _load_config()
    age = time.time() - latest_ts
    is_fresh = age < cfg["cache_ttl_seconds"]

    results = []
    for key, val in cache.items():
        for r in val.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:300],
                "published_date": r.get("published_date", ""),
                "score": r.get("score", 0),
            })

    return {
        "ok": True,
        "fresh": is_fresh,
        "cache_age_seconds": round(age, 1),
        "result_count": len(results),
        "latest_results": results[:10],
    }


def publish_macro_to_bus() -> Dict:
    """
    获取宏观数据并发布到 shared_memory_bus
    """
    from scripts.memory_l4.shared_memory_bus import publish_shared_memory_event
    from scripts.memory_l4.ab_bridge import ACL_CONFIG

    macro_data = fetch_macro_data()
    if not macro_data.get("ok"):
        return {"ok": False, "error": macro_data.get("error")}

    payload = {
        "data_type": "macro_news",
        "source": "tavily",
        "total_results": macro_data.get("total_results", 0),
        "answers": macro_data.get("answers", {}),
        "results": [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:500],
                "published_date": r.get("published_date", ""),
            }
            for r in macro_data.get("results", [])[:10]
        ],
        "sources": macro_data.get("sources", []),
    }

    result = publish_shared_memory_event(
        snapshot_ts=macro_data.get("ts", ""),
        agent_id="tavily_macro",
        event_type="macro_data_update",
        payload=payload,
        acl_config=ACL_CONFIG,
    )

    return {
        "ok": result.get("ok", False),
        "published": result.get("ok", False),
        "macro_summary": {
            "total_results": macro_data.get("total_results", 0),
            "sources": macro_data.get("sources", []),
        },
    }


def cli():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.memory_l4.tavily_macro <command> [args]")
        print("Commands:")
        print("  config --key <api_key>")
        print("  search <query>")
        print("  fetch")
        print("  summary")
        print("  publish")
        return

    cmd = sys.argv[1]

    if cmd == "config":
        kwargs = {}
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--key" and i + 1 < len(sys.argv):
                kwargs["api_key"] = sys.argv[i + 1]; i += 2
            else:
                i += 1
        result = configure(**kwargs)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if cmd == "search":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Bitcoin latest news"
        r = tavily_search(query, max_results=5)
        print(json.dumps(r, indent=2, ensure_ascii=False)[:3000])
        return

    if cmd == "fetch":
        r = fetch_macro_data()
        summary = {k: v for k, v in r.items() if k != "results" and k != "answers"}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\n前5个结果标题:")
        for i, res in enumerate(r.get("results", [])[:5]):
            print(f"  {i+1}. {res.get('title', 'N/A')}")
        return

    if cmd == "summary":
        r = get_macro_summary()
        print(json.dumps(r, indent=2, ensure_ascii=False)[:3000])
        return

    if cmd == "publish":
        r = publish_macro_to_bus()
        print(json.dumps(r, indent=2, ensure_ascii=False)[:3000])
        return

    print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    cli()
