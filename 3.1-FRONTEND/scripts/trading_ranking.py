#!/usr/bin/env python3
"""交易榜单聚合器 — orchestrator 输出 → TradingRankingItem[] 前端格式。

前端 /api/trading-ranking/today 调用此脚本, 替代 mock 数据。
走统一壳层 (dsh_frontend_bridge), FAIL-OPEN 降级返回空列表。
"""

import importlib.util
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone


def _resolve_34_core_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, "..", "..", "34-前端应用训练系统", "core"))


def _resolve_repo_root() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, "..", ".."))


# 多资产榜单池（大宗商品 / 美股指数·ETF·个股），由 ranking_asset_pool.py 周期产出
_RANKING_POOL_FILE = os.path.join(
    _resolve_repo_root(),
    "1-ARCHITECTURE",
    "dreamos",
    "cli",
    "scheduler_data",
    "ranking_asset_pool.json",
)
_RANKING_POOL_MAX_AGE_DAYS = 8

# P0 决策卡预计算（BCRM2 / ATR / CBR），由 ranking_decision_card.py 每日产出
_DECISION_CARD_FILE = os.path.join(
    _resolve_repo_root(),
    "1-ARCHITECTURE",
    "dreamos",
    "cli",
    "scheduler_data",
    "ranking_decision_cards.json",
)
_DECISION_CARD_MAX_AGE_HOURS = 36  # 1 天 + 缓冲

# 品类配额（对齐 TOP10_RANKING_RECOMMENDATION_SPEC §3.1 / §4.4：6+2+2）
_CATEGORY_QUOTA = (("crypto", 6), ("commodity", 2), ("index", 2))
_TOP_N = 10


def _score_to_signal(score: float) -> str:
    """0-1 score → TradingRankingItem.signal。"""
    if score >= 0.75:
        return "STRONG_BUY"
    if score >= 0.6:
        return "BUY"
    if score >= 0.52:
        return "WEAK_BUY"
    if score <= 0.25:
        return "STRONG_SELL"
    if score <= 0.4:
        return "SELL"
    if score <= 0.48:
        return "WEAK_SELL"
    return "NEUTRAL"


_FALLBACK_COMMODITY = {"XAU", "XAG", "XPT", "XPD", "XCU", "CL", "BZ", "NG", "USO"}
_FALLBACK_INDEX = {
    "US500",
    "US100",
    "SPX",
    "JP225",
    "KR200",
    "SPY",
    "QQQ",
    "IWM",
    "SMH",
    "XLE",
    "XLV",
    "XBI",
    "URNM",
    "TLT",
    "NVDA",
    "AMD",
    "AVGO",
    "TSM",
    "ASML",
    "MU",
    "ARM",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NFLX",
    "GS",
    "JPM",
    "V",
    "BRKB",
    "IBKR",
    "COIN",
    "MSTR",
    "HOOD",
    "CRCL",
    "XOM",
    "CVX",
    "OXY",
    "GE",
    "DELL",
}


def _normalize_symbol(symbol: str) -> str:
    """XAU-USDT-SWAP / XAU/USDT:USDT → XAU。"""
    text = str(symbol or "").upper()
    for suffix in ("-USDT-SWAP", "/USDT:USDT", "/USDT", "-USDT", "-SWAP"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _asset_class_sets() -> tuple:
    """品类符号表：优先读 40/asset_classes.py，失败时用内置兜底。"""
    commodity = set(_FALLBACK_COMMODITY)
    index = set(_FALLBACK_INDEX)
    path = os.path.join(_resolve_repo_root(), "40-周期神经网络系统", "asset_classes.py")
    if not os.path.isfile(path):
        return commodity, index
    try:
        spec = importlib.util.spec_from_file_location("asset_classes_40", path)
        if spec is None or spec.loader is None:
            return commodity, index
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        classes = getattr(module, "ASSET_CLASSES", {})
        commodity = {
            sym
            for key in ("precious_metal", "industrial_metal", "energy")
            for sym in classes.get(key, {}).get("members", [])
        } or commodity
        index = {
            sym
            for key in ("us_index", "us_etf", "us_stock")
            for sym in classes.get(key, {}).get("members", [])
            if sym != "TLT"
        } or index
    except Exception:
        pass
    return commodity, index


_COMMODITY_SYMBOLS, _INDEX_SYMBOLS = _asset_class_sets()


def _symbol_category(symbol: str) -> str:
    """symbol → crypto / commodity / index。"""
    text = _normalize_symbol(symbol)
    if text in _COMMODITY_SYMBOLS or text.split("=")[0] in {"GC", "CL", "SI", "HG"}:
        return "commodity"
    if text in _INDEX_SYMBOLS or text.startswith("^"):
        return "index"
    return "crypto"


def _load_ranking_asset_pool() -> list:
    """读取多资产榜单池；文件缺失/过期/损坏时返回空列表（FAIL-OPEN）。"""
    try:
        if not os.path.isfile(_RANKING_POOL_FILE):
            return []
        with open(_RANKING_POOL_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        generated_at = data.get("generated_at")
        if not generated_at:
            return []
        generated = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - generated
        if age > timedelta(days=_RANKING_POOL_MAX_AGE_DAYS):
            return []
        items = data.get("items")
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _load_decision_cards() -> dict:
    """读取 P0 决策卡预计算；文件缺失/过期/损坏时返回 {}（FAIL-OPEN）。"""
    try:
        if not os.path.isfile(_DECISION_CARD_FILE):
            return {}
        with open(_DECISION_CARD_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        generated_at = data.get("generated_at")
        if not generated_at:
            return {}
        generated = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - generated
        if age > timedelta(hours=_DECISION_CARD_MAX_AGE_HOURS):
            return {}
        items = data.get("items")
        return items if isinstance(items, dict) else {}
    except Exception:
        return {}


# ---- 加密候选流动性 / 市值门槛（过滤 HEMI 这类未上 OKX、成交额或市值过小的标的）----
_MIN_QUOTE_VOLUME_USD = float(os.environ.get("RANKING_MIN_QUOTE_VOLUME_USD", "5000000"))
_MIN_MARKET_CAP_USD = float(os.environ.get("RANKING_MIN_MARKET_CAP_USD", "100000000"))
_LIQUIDITY_CACHE_FILE = os.path.join(tempfile.gettempdir(), "trading_ranking_liquidity.json")
_LIQUIDITY_CACHE_TTL = timedelta(hours=6)
_OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers?instType={}"
_COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&symbols={}&per_page=250&sparkline=false"
)


def _http_json(url: str, timeout: int = 8):
    req = urllib.request.Request(url, headers={"User-Agent": "trading-ranking/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_okx_markets() -> dict:
    """OKX 现货+永续 ticker → {symbol: {last, quote_volume_usd}}，同一 symbol 取成交额较大者。"""
    markets: dict = {}
    for inst_type in ("SPOT", "SWAP"):
        payload = _http_json(_OKX_TICKERS_URL.format(inst_type))
        for row in payload.get("data", []) or []:
            inst_id = row.get("instId", "")
            if not (inst_id.endswith("-USDT") or "-USDT-" in inst_id):
                continue
            symbol = _normalize_symbol(inst_id)
            try:
                last = float(row.get("last") or 0)
                # 口径实测：现货 volCcy24h 已是 USDT 成交额；永续为币本位，需乘最新价折算美元
                if inst_type == "SPOT":
                    volume = float(row.get("volCcy24h") or 0)
                else:
                    volume = float(row.get("volCcy24h") or 0) * last
            except (TypeError, ValueError):
                continue
            if symbol and last > 0 and volume > markets.get(symbol, {}).get("quote_volume_usd", 0):
                markets[symbol] = {"last": last, "quote_volume_usd": volume}
    return markets


def _fetch_market_caps(symbols: list) -> dict:
    """CoinGecko 市值（美元）。未收录/失败返回空，由 OKX 成交额门槛兜底。"""
    if not symbols:
        return {}
    query = ",".join(sorted({_normalize_symbol(s).lower() for s in symbols}))
    payload = _http_json(_COINGECKO_URL.format(query))
    caps: dict = {}
    for row in payload if isinstance(payload, list) else []:
        sym = str(row.get("symbol") or "").upper()
        cap = row.get("market_cap")
        if sym and isinstance(cap, (int, float)):
            caps[sym] = max(float(cap), caps.get(sym, 0))
    return caps


def _load_liquidity(symbols: list) -> dict:
    """OKX 行情 + CoinGecko 市值（6h 缓存）；OKX 整体不可用时 degraded=True，过滤降级放行。"""
    try:
        with open(_LIQUIDITY_CACHE_FILE, encoding="utf-8") as fh:
            cache = json.load(fh)
        fetched = datetime.fromisoformat(cache["fetched_at"])
        if datetime.now(timezone.utc) - fetched < _LIQUIDITY_CACHE_TTL:
            return cache
    except Exception:
        pass

    try:
        markets = _fetch_okx_markets()
    except Exception:
        return {"markets": {}, "market_caps": {}, "degraded": True}
    try:
        caps = _fetch_market_caps(symbols)
    except Exception:
        caps = {}
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
        "market_caps": caps,
        "degraded": False,
    }
    try:
        with open(_LIQUIDITY_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh)
    except Exception:
        pass
    return snapshot


def _filter_crypto_candidates(candidates: list, snapshot: dict) -> list:
    """加密候选须 OKX 可交易 + 24h 成交额达标 +（有数据时）市值达标。

    大宗/美股不过滤；snapshot 降级或无行情时整体放行（FAIL-OPEN）。
    """
    if snapshot.get("degraded"):
        return candidates
    markets = snapshot.get("markets") or {}
    caps = snapshot.get("market_caps") or {}
    if not markets:
        return candidates
    kept = []
    for candidate in candidates:
        if candidate.get("category") != "crypto":
            kept.append(candidate)
            continue
        market = markets.get(_normalize_symbol(candidate["symbol"]))
        if not market:
            continue  # OKX 未上市（如 HEMI），用户无法交易
        if market.get("quote_volume_usd", 0) < _MIN_QUOTE_VOLUME_USD:
            continue
        cap = caps.get(_normalize_symbol(candidate["symbol"]))
        if cap is not None and cap < _MIN_MARKET_CAP_USD:
            continue
        kept.append(candidate)
    return kept


def _select_top10(candidates: list, total: int = _TOP_N) -> list:
    """按 6 crypto + 2 commodity + 2 index 配额选 TopN；品类不足时用剩余最高分补足。"""
    ordered = sorted(candidates, key=lambda c: c["score"], reverse=True)
    picked = []
    picked_keys = set()

    for category, quota in _CATEGORY_QUOTA:
        taken = 0
        for candidate in ordered:
            if taken >= quota:
                break
            key = _normalize_symbol(candidate["symbol"])
            if candidate.get("category") != category or key in picked_keys:
                continue
            picked.append(candidate)
            picked_keys.add(key)
            taken += 1

    for candidate in ordered:
        if len(picked) >= total:
            break
        key = _normalize_symbol(candidate["symbol"])
        if key in picked_keys:
            continue
        picked.append(candidate)
        picked_keys.add(key)

    picked.sort(key=lambda c: c["score"], reverse=True)
    return picked[:total]


# orchestrator 影子模式里可能触发信号的币种 + 基础分数
_SHADOW_SIGNAL_BASE = {
    "BTC": 0.55,
    "ETH": 0.50,
    "SOL": 0.48,
    "UNI": 0.45,
    "HYPE": 0.44,
    "PUMP": 0.43,
    "ARB": 0.43,
    "LINK": 0.43,
}

# 完整 24 币种池 (影子模式潜在候选)
_FULL_COIN_POOL = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "OKB",
    "UNI",
    "HYPE",
    "PUMP",
    "ZEC",
    "ARB",
    "LINK",
    "XAU",
    "XAG",
    "MU",
    "SKHYNIX",
    "GOOGL",
    "NVDA",
    "AMZN",
    "SNDK",
    "SPCX",
    "MSTR",
    "COIN",
    "CRCL",
    "BMNR",
]


def _orchestrator_to_items(orch_data: dict, decision_cards: dict | None = None) -> list:
    """orchestrator 输出 → TradingRankingItem[]。

    orchestrator 输出结构 (可能两种):
      A (扁平): selection: { long_pool: [...], short_pool: [...] }
      B (嵌套): selection: { pools: { long_pool: [...], short_pool: [...] }, status: "OK" }
      signal: { symbol, direction, confidence, ... }
      execution: { position: { status, ... } }
    """
    items = []
    selection = orch_data.get("selection", {}) or {}
    signal = orch_data.get("signal", {}) or {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 同时支持扁平结构和嵌套 pools 结构
    pools = selection.get("pools") or selection
    long_pool = pools.get("long_pool", []) or []
    short_pool = pools.get("short_pool", []) or []

    # 1. 从 long/short_pool 收集带 orchestrator 真实分数的候选
    candidates = []
    used_symbols = set()
    for entry in long_pool:
        symbol = entry.get("symbol", "")
        score = float(entry.get("score", 0))
        key = _normalize_symbol(symbol)
        if key in used_symbols:
            continue
        used_symbols.add(key)
        candidates.append(
            {
                "symbol": symbol,
                "score": score,
                "direction": "BUY",
                "category": _symbol_category(symbol),
                "reasons": entry.get("reasons", []) or ["orchestrator long_pool"],
            }
        )
    for entry in short_pool:
        symbol = entry.get("symbol", "")
        score = float(entry.get("score", 0))
        key = _normalize_symbol(symbol)
        if key in used_symbols:
            continue
        used_symbols.add(key)
        candidates.append(
            {
                "symbol": symbol,
                "score": score,
                "direction": "SELL",
                "category": _symbol_category(symbol),
                "reasons": entry.get("reasons", []) or ["orchestrator short_pool"],
            }
        )

    # 1.5 多资产榜单池（大宗商品 / 美股指数·ETF·个股），由 40+OKX CLI 周期产出
    for entry in _load_ranking_asset_pool():
        symbol = entry.get("symbol", "")
        key = _normalize_symbol(symbol)
        if not key or key in used_symbols:
            continue
        used_symbols.add(key)
        candidates.append(
            {
                "symbol": symbol,
                "score": float(entry.get("score", 0)),
                "direction": "BUY",
                "category": entry.get("category") or _symbol_category(symbol),
                "reasons": entry.get("reasons", []) or ["multi-asset pool"],
                "price": (entry.get("metrics") or {}).get("last_close"),
            }
        )

    # 2. 用影子模式触发信号的币种补足 (分数从 0.43-0.55 区间)
    for sym, base in _SHADOW_SIGNAL_BASE.items():
        if sym in used_symbols:
            continue
        used_symbols.add(sym)
        candidates.append(
            {
                "symbol": sym,
                "score": base,
                "direction": "BUY",
                "category": _symbol_category(sym),
                "reasons": ["rebound signal", "shadow mode trigger"],
            }
        )

    # 3. 如果还不够, 从 24 币池里补
    for sym in _FULL_COIN_POOL:
        if len(candidates) >= 10:
            break
        if sym in used_symbols:
            continue
        used_symbols.add(sym)
        # 给低优先级默认分 (0.30-0.42 递减)
        fallback_score = 0.30 + (0.12 * (1 - len(candidates) / 10))
        candidates.append(
            {
                "symbol": sym,
                "score": round(fallback_score, 3),
                "direction": "HOLD",
                "category": _symbol_category(sym),
                "reasons": ["full pool candidate"],
            }
        )

    # 4. 如果 orchestrator 只给了单一 signal, 也加进去
    if signal and signal.get("symbol") and signal["symbol"] not in used_symbols:
        sym = signal["symbol"]
        conf = float(signal.get("confidence", 0.5))
        used_symbols.add(sym)
        candidates.append(
            {
                "symbol": sym,
                "score": conf,
                "direction": signal.get("direction", "HOLD"),
                "category": _symbol_category(sym),
                "reasons": [],
            }
        )

    # 5. 加密候选流动性/市值过滤（剔除 HEMI 这类未上 OKX / 成交额或市值过小的标的）
    crypto_symbols = [c["symbol"] for c in candidates if c.get("category") == "crypto"]
    liquidity = _load_liquidity(crypto_symbols)
    candidates = _filter_crypto_candidates(candidates, liquidity)

    # 6. 按 6 crypto + 2 commodity + 2 index 配额选 Top10
    candidates = _select_top10(candidates)

    for i, c in enumerate(candidates):
        symbol = c["symbol"]
        score = c["score"]
        direction = c["direction"]
        category = c.get("category") or _symbol_category(symbol)
        signal_type = (
            _score_to_signal(score) if direction != "SELL" else _score_to_signal(1 - score)
        )

        # 最新价：大宗/美股取池内 last_close，加密取 OKX ticker；都没有则为 None（前端做空值展示）
        price = c.get("price")
        if price is None and category == "crypto":
            price = (liquidity.get("markets", {}).get(_normalize_symbol(symbol)) or {}).get("last")

        # 决策卡：默认简化版，如 P0 预计算有该标的则用其覆盖（BCRM2 + ATR + CBR）
        decision = {
            "entry": {
                "price": price,
                "range": [None, None],
                "batches": [],
            },
            "stopLoss": None,
            "takeProfit": [],
            "events": [],
            "riskLevel": "intermediate",
            "historicalAnalogy": "",
            "inferred": False,
            "logic": {
                "bullish": c.get("reasons", [])[:3],
                "bearish": [],
                "confidence": round(score, 2),
            },
        }

        # P0 合并预计算决策卡（FAIL-OPEN：无预计算则保留默认值）
        pre = (decision_cards or {}).get(symbol)
        if isinstance(pre, dict) and pre.get("inferred"):
            # 入场
            if pre.get("entry"):
                decision["entry"] = pre["entry"]
            elif price is not None:
                decision["entry"]["price"] = price
            # 止损止盈
            if pre.get("stopLoss") is not None:
                decision["stopLoss"] = pre["stopLoss"]
            if pre.get("takeProfit"):
                decision["takeProfit"] = pre["takeProfit"]
            # 风险分级
            decision["riskLevel"] = pre.get("riskLevel", decision["riskLevel"])
            # 历史类比
            if pre.get("historicalAnalogy"):
                decision["historicalAnalogy"] = pre["historicalAnalogy"]
            # 方向/置信度（BCRM2 推理的）
            if pre.get("direction"):
                decision["bcrm2Direction"] = pre["direction"]
            if pre.get("confidence") is not None:
                decision["bcrm2Confidence"] = pre["confidence"]
            if pre.get("positionFactor") is not None:
                decision["positionFactor"] = pre["positionFactor"]
            if pre.get("warnings"):
                decision["warnings"] = pre["warnings"]
            decision["inferred"] = True

        items.append(
            {
                "rank": i + 1,
                "symbol": symbol,
                "category": category,
                "score": round(score, 3),
                "signal": signal_type,
                "confidence": round(score, 2),
                "decisionCard": decision,
                "date": today,
            }
        )

    return items


def main():
    core_dir = _resolve_34_core_dir()
    if os.path.isdir(core_dir) and core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    # 抑制 orchestrator/call_handler 内部所有 print/日志到 stdout
    # (它们会污染 execFileAsync 捕获的 JSON 输出)
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        from dsh_frontend_bridge import call_handler

        items = []
        orch_ok = False
        # P0：加载预计算决策卡（BCRM2 / ATR / CBR），FAIL-OPEN 空 dict
        decision_cards = _load_decision_cards()
        try:
            r = call_handler("orchestrator", {"node_output": {"symbol": "BTC"}})
            if r.get("ok") and r.get("output"):
                orch_ok = True
                items = _orchestrator_to_items(r["output"], decision_cards=decision_cards)
        except Exception:
            pass
    finally:
        sys.stdout = _real_stdout

    # 兜底: 如果 orchestrator 没数据, 返回空 items (前端已有 mock 降级)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "success": orch_ok and len(items) > 0,
        "items": items,
        "metrics": {
            "date": today,
            "satisfaction": None,
            "conversionRate": None,
            "abandonRate": None,
            "pushReachRate": None,
            "unsubscribeRate": None,
            "matu": None,
            "kFactor": None,
        },
        "source": "orchestrator" if orch_ok else "fallback",
        "degraded": not orch_ok,
    }

    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout = sys.__stdout__
        sys.stdout.write(
            json.dumps(
                {
                    "success": False,
                    "items": [],
                    "metrics": {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
                    "source": "error",
                    "degraded": True,
                    "error": f"{type(e).__name__}: {e}",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        sys.stdout.flush()
