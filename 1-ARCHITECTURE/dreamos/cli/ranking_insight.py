#!/usr/bin/env python3
"""榜单统计洞察生产者 — 「⚠风险」「⟲类比」的真实统计产出。

所有数值来自 54-L1 架构能力聚合层（回撤画像 / VaR·CVaR / 波动率条件分布），
禁止硬编码；前端据此渲染回撤面积图、风险分解条形图与前瞻收益分布。

产出：
  1-ARCHITECTURE/dreamos/cli/scheduler_data/ranking_insights.json
  {version, generated_at, source, items:{SYMBOL:{risk, analogy, charts, warnings}}}

消费端：
  trading_ranking.py 合并到决策卡（覆盖 riskLevel / historicalAnalogy，并写入 insight）。

用法:
  python3 ranking_insight.py                 # 自动收集候选并写入
  python3 ranking_insight.py BTC ETH AMD     # 指定标的
  python3 ranking_insight.py --dry-run       # 只打印摘要
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

INSIGHT_VERSION = 1


def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here.parent.parent


REPO = _repo_root()
SCHED = REPO / "1-ARCHITECTURE" / "dreamos" / "cli" / "scheduler_data"
OUT = SCHED / "ranking_insights.json"

# L1 统计能力层 + 复用 OkxFeed
L1_DIR = REPO / "54-L1架构能力聚合层"
for path in (str(L1_DIR), str(SCHED.parent)):
    if Path(path).is_dir() and path not in sys.path:
        sys.path.insert(0, path)

# 回撤画像门禁 250 点 → 生产端日线取 300 根留出对齐余量
MIN_PRICES = 60
VOL_WINDOW = 20
# 4 桶 × 每桶非重叠样本 ≥30：300 根日线（对齐后约 280）可稳定落在 4 桶，
# 低于该阈值时由统计层自行降为 2 桶并在 quality 中披露。
MIN_BUCKET_N = 30
PIT_WINDOW = 60

# 风险评分：分量 → (指标名, 权重, 归一化下界, 归一化上界)，上界取满风险=100
_RISK_COMPONENTS = (
    ("mdd", "最大回撤", 35, 10.0, 70.0),
    ("var", "VaR 95%", 25, 1.0, 10.0),
    ("vol", "日波动率", 25, 1.0, 7.0),
    ("current", "当前回撤", 15, 0.0, 40.0),
)
_RISK_DRIVERS = {
    "最大回撤": "回撤深",
    "VaR 95%": "尾部风险高",
    "日波动率": "波动高",
    "当前回撤": "仍处深回撤",
}
_RANKING_CORE_CRYPTO = ("BTC", "ETH", "SOL", "BNB", "UNI", "HYPE", "PUMP", "ZEC", "ARB", "LINK")


# ── L1 统计层加载（FAIL-OPEN） ──────────────────────────────────────
def load_stats() -> Optional[Tuple[Any, Any, Any]]:
    """返回 (stats 能力模块, run_method, simple_returns)；不可用返回 None。"""
    try:
        from l1agg.align import simple_returns
        from l1agg.capabilities import stats as stats_mod
        from l1agg.methods import run as run_method
    except Exception:
        return None
    return stats_mod, run_method, simple_returns


def stats_available() -> bool:
    return load_stats() is not None


# ── 风险评分 ────────────────────────────────────────────────────────
def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _norm(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return _clamp01((value - low) / (high - low))


def risk_level(score: float) -> Tuple[str, str]:
    """0-100 风险分 → (前端 riskLevel, 展示标签)。"""
    if score < 35:
        return "novice", "低风险"
    if score < 65:
        return "intermediate", "中等风险"
    return "expert", "高风险"


def _risk_block(
    stats_mod: Any,
    run_method: Any,
    simple_returns: Any,
    symbol: str,
    prices: List[float],
    dates: List[str],
    profile: Dict[str, Any],
    quality: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    returns = simple_returns(prices)
    var = cvar = None
    port = stats_mod.portfolio_risk({symbol: returns}, dates=dates[1:] if dates else None)
    if port.get("ok"):
        asset = ((port["data"].get("capabilities") or {}).get("D-G16") or {}).get("assets") or {}
        detail = asset.get(symbol) or next(iter(asset.values()), {})
        var = (detail.get("var") or {}).get("var")
        cvar = (detail.get("cvar") or {}).get("cvar")
    if var is None:
        var_block = run_method("D17", returns, q=5.0)
        if var_block.get("gate") == "ok":
            var = var_block["result"]["var"]
    if cvar is None:
        cvar_block = run_method("D18", returns, q=5.0)
        if cvar_block.get("gate") == "ok":
            cvar = cvar_block["result"]["cvar"]
    vol_block = run_method("S09", returns)
    daily_vol = vol_block["result"]["std"] if vol_block.get("gate") == "ok" else None

    raw_values = {
        "mdd": float(profile.get("mdd") or 0.0) * 100.0,
        "var": float(var) * 100.0 if var is not None else None,
        "vol": float(daily_vol) * 100.0 if daily_vol is not None else None,
        "current": float(profile.get("current_drawdown") or 0.0) * 100.0,
    }

    breakdown: List[Dict[str, Any]] = []
    weighted = 0.0
    weight_sum = 0.0
    for key, name, weight, low, high in _RISK_COMPONENTS:
        value = raw_values.get(key)
        if value is None:
            continue
        score_part = _norm(value, low, high)
        breakdown.append(
            {
                "name": name,
                "value": round(value, 2),
                "score": round(score_part, 3),
                "weight": weight,
            }
        )
        weighted += score_part * weight
        weight_sum += weight
    if weight_sum <= 0:
        return None

    score = round(weighted / weight_sum * 100.0, 1)
    level, label = risk_level(score)

    ranked = sorted(breakdown, key=lambda item: item["score"] * item["weight"], reverse=True)
    drivers = [_RISK_DRIVERS[item["name"]] for item in ranked if item["score"] >= 0.3][:2]
    detail_label = "·".join(drivers) if drivers else "风险特征均衡"

    quality = quality or {}
    return {
        "score": score,
        "level": level,
        "label": label,
        "detail": detail_label,
        "metrics": {
            "mdd": round(raw_values["mdd"], 2),
            "currentDrawdown": round(raw_values["current"], 2),
            "var95": round(raw_values["var"], 2) if raw_values["var"] is not None else None,
            "cvar95": round(float(cvar) * 100.0, 2) if cvar is not None else None,
            "dailyVol": round(raw_values["vol"], 2) if raw_values["vol"] is not None else None,
            "durationDays": profile.get("duration_days"),
            "sampleSize": quality.get("sample_n") or len(prices),
        },
        "breakdown": breakdown,
        "quality": str(quality.get("status") or ""),
    }


# ── 历史类比（波动率同状态条件分布） ────────────────────────────────
def _analogy_block(symbol: str, prices: List[float], dates: List[str]) -> Optional[Dict[str, Any]]:
    try:
        from l1agg.persistence.profile import conditional_distribution
    except Exception:
        return None
    try:
        a8 = conditional_distribution(
            prices,
            dates,
            window=PIT_WINDOW,
            vol_window=VOL_WINDOW,
            min_bucket_n=MIN_BUCKET_N,
        )
    except Exception:
        return None
    result = a8.get("result") if isinstance(a8, dict) else None
    rows = (result or {}).get("by_horizon") or []
    if not rows:
        return None
    main = rows[0]
    if not main.get("effective_n"):
        return None

    current_bucket = result.get("bucket")
    buckets = [
        {
            "bucket": f"Q{int(row['bucket']) + 1}",
            "meanReturn": round(float(row["mean"] or 0.0) * 100.0, 2),
            "winRate": round(float(row["win_rate"] or 0.0) * 100.0, 1),
            "sampleSize": int(row.get("effective_n") or 0),
            "current": row["bucket"] == current_bucket,
        }
        for row in main.get("by_bucket") or []
    ]
    percentile = result.get("current_percentile")
    avg_return = round(float(main["mean"] or 0.0) * 100.0, 2)
    median_return = round(float(main["median"] or 0.0) * 100.0, 2)
    win_rate = round(float(main["win_rate"] or 0.0) * 100.0, 1)
    p10 = round(float(main["p10"] or 0.0) * 100.0, 2)
    p90 = round(float(main["p90"] or 0.0) * 100.0, 2)
    sample_n = int(main.get("effective_n") or 0)
    buckets_n = a8.get("buckets") or len(buckets)
    pct_text = f"{float(percentile):.1f}% 分位" if percentile is not None else "当前波动状态"

    text = (
        f"历史同波动状态（{pct_text}，{buckets_n} 桶，n={sample_n}）后 1 日："
        f"均值 {avg_return:+.2f}%、中位 {median_return:+.2f}%、"
        f"上涨概率 {win_rate:.1f}%，80% 区间 [{p10:+.2f}%, {p90:+.2f}%]。历史统计，不代表未来。"
    )
    return {
        "winRate": win_rate,
        "avgReturn": avg_return,
        "medianReturn": median_return,
        "sampleSize": sample_n,
        "horizon": 1,
        "currentPercentile": round(float(percentile), 1) if percentile is not None else None,
        "buckets": buckets,
        "text": text,
        "quality": str(a8.get("gate") or ""),
    }


# ── 单标的计算 ──────────────────────────────────────────────────────
def compute_insight(symbol: str, prices: Sequence[Any], dates: Sequence[Any]) -> Dict[str, Any]:
    """纯计算入口（便于单测）：返回 {risk, analogy, charts:{drawdownPath}, warnings}。"""
    pairs: List[Tuple[float, Any]] = []
    for price, day in zip(prices, dates, strict=False):
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if value > 0:
            pairs.append((value, day))
    clean_prices = [price for price, _ in pairs]
    clean_dates = [
        day.isoformat() if hasattr(day, "isoformat") else str(day)[:10] for _, day in pairs
    ]

    payload: Dict[str, Any] = {
        "risk": None,
        "analogy": None,
        "charts": {"drawdownPath": []},
        "warnings": [],
    }

    loaded = load_stats()
    if loaded is None:
        payload["warnings"].append("l1_stats_unavailable")
        return payload
    stats_mod, run_method, simple_returns = loaded

    if len(clean_prices) < MIN_PRICES:
        payload["warnings"].append(f"insufficient_history:{len(clean_prices)}")
        return payload

    # 合成合约无成交时会连续复制同一收盘价：这种假行情算出的「零风险」会误导用户
    recent = clean_prices[-31:]
    if len(recent) >= 31 and (max(recent) - min(recent)) / max(recent) < 0.001:
        payload["warnings"].append("flat_quotes")
        return payload

    risk = None
    dd = stats_mod.drawdown(clean_prices, symbol=symbol, dates=clean_dates)
    if dd.get("ok"):
        profile = ((dd.get("data") or {}).get("capabilities") or {}).get("D-E10") or {}
        risk = _risk_block(
            stats_mod,
            run_method,
            simple_returns,
            symbol,
            clean_prices,
            clean_dates,
            profile,
            dd.get("quality") or {},
        )
    if risk is not None:
        payload["risk"] = risk
        payload["charts"]["drawdownPath"] = [
            {
                "date": point.get("date"),
                "value": round(-float(point.get("drawdown") or 0.0) * 100.0, 2),
            }
            for point in profile.get("drawdown_path") or []
        ]
    else:
        payload["warnings"].append("risk_unavailable")

    analogy = _analogy_block(symbol, clean_prices, clean_dates)
    if analogy is not None:
        payload["analogy"] = analogy
    else:
        payload["warnings"].append("analogy_insufficient_samples")

    return payload


# ── 候选收集 / 行情 ────────────────────────────────────────────────
def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _collect_symbols() -> List[str]:
    symbols: List[str] = []
    seen = set()

    pool = _read_json(SCHED / "coin_pool.json") or {}
    for key in ("long_pool", "short_pool"):
        for entry in pool.get(key) or []:
            symbol = entry.get("symbol", "") if isinstance(entry, dict) else str(entry)
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)

    asset_pool = _read_json(SCHED / "ranking_asset_pool.json") or {}
    for entry in asset_pool.get("items") or []:
        symbol = entry.get("symbol", "") if isinstance(entry, dict) else str(entry)
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)

    for symbol in _RANKING_CORE_CRYPTO:
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def _normalize_symbol(symbol: str) -> str:
    """XAU-USDT-SWAP / XAU/USDT:USDT → XAU（与 trading_ranking 消费端口径一致）。"""
    text = str(symbol or "").upper()
    for suffix in ("-USDT-SWAP", "/USDT:USDT", "/USDT", "-USDT", "-SWAP"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _to_inst_id(symbol: str) -> str:
    return f"{symbol.upper().replace('-', '').replace('/', '')}-USDT-SWAP"


def _parse_candles(raw: List[List[Any]]) -> Tuple[List[float], List[str]]:
    """OKX 日线 → (收盘价升序, ISO 日期)。"""
    rows = []
    for item in raw or []:
        if not isinstance(item, (list, tuple)) or len(item) < 5:
            continue
        try:
            ts = int(item[0])
            close = float(item[4])
        except (TypeError, ValueError):
            continue
        if close > 0:
            rows.append((ts, close))
    dedup: Dict[int, float] = {}
    for ts, close in rows:
        dedup[ts] = close
    ordered = sorted(dedup.items())
    dates = [
        datetime.fromtimestamp(ts / 1000, timezone.utc).date().isoformat() for ts, _ in ordered
    ]
    return [close for _, close in ordered], dates


def _work(symbol: str, feed: Any) -> Tuple[str, Dict[str, Any]]:
    try:
        raw = feed.candles(_to_inst_id(symbol))
    except Exception as exc:
        return symbol, {"warnings": [f"candles_failed:{type(exc).__name__}"]}
    prices, dates = _parse_candles(raw)
    return symbol, compute_insight(symbol, prices, dates)


# ── 主流程 ──────────────────────────────────────────────────────────
def build_insights(symbols: Optional[List[str]] = None, dry_run: bool = False) -> Dict[str, Any]:
    from ranking_asset_pool import OkxFeed  # noqa: WPS433

    symbols = symbols or _collect_symbols()
    generated_at = datetime.now(timezone.utc).isoformat()
    feed = OkxFeed()
    items: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    started = time.time()

    print(f"[ranking_insight] 目标 {len(symbols)} 个标的，开始 {generated_at}")
    with ThreadPoolExecutor(max_workers=6) as executor:
        for symbol, insight in executor.map(lambda s: _work(s, feed), symbols):
            items[_normalize_symbol(symbol)] = insight
            risk = insight.get("risk") or {}
            analogy = insight.get("analogy") or {}
            print(
                f"  {symbol:<10} risk={risk.get('score', '-')}/{risk.get('level', '-')} "
                f"analogy_n={analogy.get('sampleSize', '-')}"
            )

    if not stats_available():
        warnings.append("l1_stats_unavailable")

    payload = {
        "version": INSIGHT_VERSION,
        "generated_at": generated_at,
        "source": "ranking_insight.py",
        "warnings": warnings,
        "items": items,
    }

    if not dry_run:
        SCHED.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, OUT)
        print(
            f"[ranking_insight] 完成 {len(items)} 标的，耗时 {time.time() - started:.1f}s → {OUT}"
        )
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="榜单统计洞察生产者（风险 / 类比）")
    parser.add_argument("--dry-run", action="store_true", help="只打印摘要，不写文件")
    parser.add_argument("symbols", nargs="*", help="指定标的（默认自动收集）")
    args = parser.parse_args(argv)

    payload = build_insights(args.symbols or None, dry_run=args.dry_run)
    return 0 if payload.get("items") else 1


if __name__ == "__main__":
    raise SystemExit(main())
