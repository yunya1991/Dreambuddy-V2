#!/usr/bin/env python3
"""
基本面参考信号桥接模块
- 当 A1/A6 研报缺失或过期时，提供基本面 + 情绪面参考信号
- 数据来源：OKX CLI（funding-rate / news / ticker）
- 引擎：9-基本面分析的 SignalEngine + SentimentEngine
- 零 Token 消耗，纯本地计算
"""
import json, os, sys, subprocess, math
from datetime import datetime, timezone, timedelta
from pathlib import Path

HOME_BIN = "/opt/homebrew/bin"
os.environ["PATH"] = HOME_BIN + ":" + os.environ.get("PATH", "")

OKX_PROFILE = "screen_trade"
INST_SPOT = "BTC-USDT"
INST_SWAP = "BTC-USDT-SWAP"

# 接入 9-基本面分析的引擎
# fundamental_bridge.py 在 dreambuddy-v2/experiments/ab-trading/
# 9-基本面分析 在 dreambuddy-v2/9-基本面分析/
FUNDAMENTAL_ROOT = Path(__file__).resolve().parents[2] / "9-基本面分析"
if str(FUNDAMENTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(FUNDAMENTAL_ROOT))

try:
    from engines.signal_engine import SignalEngine
    from engines.sentiment_engine import SentimentEngine
    from engines.least_resistance import compute_resistance_3d
    ENGINES_AVAILABLE = True
except Exception as e:
    ENGINES_AVAILABLE = False
    _IMPORT_ERROR = str(e)

# 研报新鲜度阈值
REPORT_MAX_AGE_H = {
    "weekly": 168,   # 7天
    "a1_daily": 24,  # 1天
    "a6_intel": 6,   # 6小时
}

_cache: dict = {}
_CACHE_TTL = 300  # 5分钟缓存


def _run_okx(args):
    try:
        r = subprocess.run(
            ["okx", "--profile", OKX_PROFILE] + args,
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "NO_UPDATE_CHECK": "1"}
        )
        stdout = "\n".join(l for l in r.stdout.split("\n")
                           if "Update available" not in l and "Run: npm" not in l).strip()
        stderr = "\n".join(l for l in r.stderr.split("\n")
                           if "Update available" not in l and "Run: npm" not in l).strip()
        if r.returncode != 0 and stderr:
            return {"ok": False, "err": stderr[:200]}
        if stdout.startswith("[") or stdout.startswith("{"):
            return {"ok": True, "data": json.loads(stdout)}
        return {"ok": True, "data": stdout}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _fetch_funding_rate(inst_id: str = INST_SWAP) -> dict:
    """获取资金费率"""
    r = _run_okx(["market", "funding-rate", inst_id, "--json"])
    if not r["ok"]:
        return {}
    data = r["data"]
    if isinstance(data, list) and data:
        fr = float(data[0].get("fundingRate", 0))
        return {"funding_rate": fr, "funding_rate_pct": round(fr * 100, 4)}
    return {}


def _fetch_news(coins: str = "BTC", limit: int = 15) -> list:
    """获取最新新闻文本列表"""
    r = _run_okx(["news", "latest", "--coins", coins, "--lang", "zh-CN",
                  "--limit", str(limit), "--json"])
    if not r["ok"]:
        return []
    data = r["data"]
    if not isinstance(data, list):
        return []
    texts = []
    for item in data:
        title = item.get("title", "")
        summary = item.get("summary", item.get("content", ""))
        text = f"{title} {summary}".strip()
        if text:
            texts.append(text)
    return texts


def _fetch_candles(inst_id: str, bar: str, limit: int) -> list:
    """获取K线"""
    r = _run_okx(["market", "candles", inst_id, "--bar", bar,
                  "--limit", str(limit), "--json"])
    if not r["ok"]:
        return []
    raw = r["data"]
    candles = []
    for c in raw:
        candles.append({
            "ts": int(c[0]), "o": float(c[1]), "h": float(c[2]),
            "l": float(c[3]), "c": float(c[4]), "vol": float(c[5]),
        })
    return list(reversed(candles))


def _calc_resistance_3d(daily_closes: list) -> dict:
    """
    用价格动量构造三维度指标
    - direction: 基于近5日价格变化率
    - velocity: tanh(变化率)
    - acceleration: 近3日 vs 近7日动量差
    """
    if len(daily_closes) < 7:
        return compute_resistance_3d(0.0)

    price = daily_closes[-1]
    mom_5d = (price / daily_closes[-6] - 1) if len(daily_closes) >= 6 else 0
    mom_3d = (price / daily_closes[-4] - 1) if len(daily_closes) >= 4 else 0
    mom_7d = (price / daily_closes[-8] - 1) if len(daily_closes) >= 8 else 0

    # 归一化到 [-1, 1]
    raw_score = math.tanh(mom_5d * 10)
    acceleration = math.tanh((mom_3d - mom_7d) * 10)

    return {
        "direction": "up" if raw_score > 0.3 else "down" if raw_score < -0.3 else "neutral",
        "direction_score": round(raw_score, 4),
        "velocity": round(raw_score, 4),
        "acceleration": round(acceleration, 4),
        "confidence": round(min(1.0, abs(raw_score) * 0.8 + 0.3), 4),
        "data_points": len(daily_closes),
        "trend_summary": _trend_text(raw_score, acceleration),
    }


def _trend_text(score: float, accel: float) -> str:
    if score > 0.3:
        return "多方主导，趋势" + ("加速中" if accel > 0 else "减弱中")
    if score < -0.3:
        return "空方主导，趋势" + ("加速下行" if accel < 0 else "减弱中")
    return "多空僵持，趋势不明"


def _check_reports_freshness() -> dict:
    """检查 A1/A6/周报的新鲜度，判断是否需要基本面参考"""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from report_loader import get_all_reports
        reports = get_all_reports()
    except Exception:
        return {"weekly": False, "a1_daily": False, "a6_intel": False, "any_fresh": False}

    now = datetime.now(timezone.utc)
    freshness = {}

    for key, max_age_h in REPORT_MAX_AGE_H.items():
        rpt = reports.get(key) or {}
        if rpt.get("error") or not rpt:
            freshness[key] = False
            continue
        date_str = rpt.get("date") or rpt.get("timestamp", "")
        if not date_str:
            freshness[key] = False
            continue
        try:
            # 尝试解析日期
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_h = (now - dt).total_seconds() / 3600
            freshness[key] = age_h <= max_age_h
        except Exception:
            freshness[key] = True  # 无法解析时假定可用

    freshness["any_fresh"] = any(freshness.values())
    return freshness


def get_fundamental_signals(symbol: str = "BTC") -> dict:
    """
    获取基本面参考信号
    返回: {
        available: bool,
        engines_ok: bool,
        reports_fresh: {...},
        role: "primary" | "reference" | "fallback",
        sentiment: {...},
        signals: [...],
        composite: {...},
        summary: "...",
        metrics_used: {...},
        generated_at: "..."
    }
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    if not ENGINES_AVAILABLE:
        return {
            "available": False,
            "engines_ok": False,
            "error": f"引擎导入失败: {_IMPORT_ERROR}",
            "generated_at": now_iso,
        }

    # 缓存检查
    cache_key = f"fund_{symbol}"
    cached = _cache.get(cache_key)
    if cached:
        age = (datetime.now(timezone.utc) - cached["_fetched_at"]).total_seconds()
        if age < _CACHE_TTL:
            return cached["data"]

    # 1. 研报新鲜度
    reports_fresh = _check_reports_freshness()
    role = "reference"
    if not reports_fresh.get("any_fresh"):
        role = "fallback"
    elif not reports_fresh.get("a6_intel") or not reports_fresh.get("a1_daily"):
        role = "primary"

    # 2. 获取 OKX 数据
    spot_inst = f"{symbol}-USDT" if symbol != "BTC" else INST_SPOT
    swap_inst = f"{symbol}-USDT-SWAP" if symbol != "BTC" else INST_SWAP

    funding = _fetch_funding_rate(swap_inst)
    news_texts = _fetch_news(symbol if symbol != "BTC" else "BTC", 15)
    daily = _fetch_candles(spot_inst, "1D", 30)

    # 3. 情绪分析
    se = SentimentEngine()
    sentiment_result = se.analyze_batch(news_texts) if news_texts else {
        "score": 0, "sentiment": "neutral", "sentiment_index": 50,
        "count": 0, "positive_count": 0, "negative_count": 0,
        "category_distribution": {},
    }
    fear_greed = se.get_fear_greed_estimate(sentiment_result.get("sentiment_index", 50))

    # 4. 构造 metrics
    daily_closes = [c["c"] for c in daily] if daily else []
    price = daily_closes[-1] if daily_closes else 0

    metrics = {
        "funding_rate": funding.get("funding_rate", 0),
        "sentiment": sentiment_result.get("sentiment_index", 50),
        "fear_greed_index": sentiment_result.get("sentiment_index", 50),
        "news_sentiment": sentiment_result.get("score", 0),
        "news_volume": sentiment_result.get("count", 0),
    }

    # 5. 三维度计算
    resistance_3d = _calc_resistance_3d(daily_closes) if daily_closes else compute_resistance_3d(0.0)

    # 6. 信号生成
    engine = SignalEngine()
    raw_signals = engine.generate_signals(resistance_3d, metrics, events=None, stress="normal")
    ranked_signals = engine.rank_signals(raw_signals)
    summary_text = engine.generate_summary(raw_signals, top_n=3)

    # 7. 综合信号（构造单模块 snapshot）
    module_snapshots = {
        "flow": {
            "resistance_3d": {"direction_score": resistance_3d.get("direction_score", 0),
                              "confidence": resistance_3d.get("confidence", 0.5),
                              "velocity": resistance_3d.get("velocity", 0)},
            "metrics": {"funding_rate": metrics["funding_rate"]},
        },
        "sentiment": {
            "resistance_3d": {"direction_score": (sentiment_result.get("score", 0)),
                              "confidence": 0.6, "velocity": 0},
            "metrics": {"sentiment_index": metrics["sentiment"],
                        "fear_greed_index": metrics["fear_greed_index"]},
        },
        "news": {
            "resistance_3d": {"direction_score": metrics.get("news_sentiment", 0),
                              "confidence": 0.55, "velocity": 0},
            "metrics": {"news_sentiment": metrics.get("news_sentiment", 0),
                        "news_volume": metrics.get("news_volume", 0)},
        },
    }
    composite = engine.generate_composite_signals(module_snapshots)

    result = {
        "available": True,
        "engines_ok": True,
        "symbol": symbol,
        "price": round(price, 2),
        "role": role,
        "reports_fresh": reports_fresh,
        "sentiment": {
            "sentiment_index": sentiment_result.get("sentiment_index", 50),
            "sentiment_label": sentiment_result.get("sentiment", "neutral"),
            "fear_greed": fear_greed,
            "news_count": sentiment_result.get("count", 0),
            "positive_count": sentiment_result.get("positive_count", 0),
            "negative_count": sentiment_result.get("negative_count", 0),
            "category_distribution": sentiment_result.get("category_distribution", {}),
        },
        "resistance_3d": resistance_3d,
        "metrics_used": {
            "funding_rate": funding.get("funding_rate", 0),
            "funding_rate_pct": funding.get("funding_rate_pct", 0),
            "sentiment_index": metrics["sentiment"],
            "news_sentiment": metrics.get("news_sentiment", 0),
        },
        "signals": ranked_signals[:5],
        "composite": composite,
        "summary": summary_text,
        "generated_at": now_iso,
    }

    _cache[cache_key] = {"data": result, "_fetched_at": datetime.now(timezone.utc)}
    return result


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    result = get_fundamental_signals(sym)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
