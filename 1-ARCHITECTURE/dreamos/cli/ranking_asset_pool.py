#!/usr/bin/env python3
"""多资产榜单池生产者 — OKX CLI 行情 + 40 周期网络评分 → ranking_asset_pool.json

定位：
    榜单专用多资产候选池（大宗商品 / 美股指数·ETF·个股），与交易用 coin_pool.json
    完全隔离，避免非加密标的进入 V15 实盘执行链。

数据源：
    1. 行情：51-OKX CLI 系统（okx CLI，读 OKX USDT 永续日线）
    2. 评分辅助：40-周期神经网络系统（cross_asset_matrix / asset_rotation / strategy_mapping）

输出：
    1-ARCHITECTURE/dreamos/cli/scheduler_data/ranking_asset_pool.json
    v1 schema: {version, generated_at, source, context, items:[...]}

用法：
    python3 ranking_asset_pool.py            # 生成并写入
    python3 ranking_asset_pool.py --dry-run  # 只打印摘要
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

POOL_FILE = Path(__file__).parent / "scheduler_data" / "ranking_asset_pool.json"
POOL_VERSION = 1
PER_CATEGORY_KEEP = 4  # 榜单只用 2 条，多留 2 条作为消费端降级缓冲
CANDLE_LIMIT = 220  # 覆盖 MA200
CONTEXT_MAX_AGE_DAYS = 5

# 40 资产注册表不可用时的兜底宇宙（与 40/asset_classes.py 对齐）
_FALLBACK_COMMODITY = ["XAU", "XAG", "XPT", "XPD", "XCU", "CL", "BZ", "NG", "USO"]
_FALLBACK_INDEX = [
    "US500",
    "US100",
    "SPX",
    "SPY",
    "QQQ",
    "IWM",
    "SMH",
    "XLE",
    "XLV",
    "XBI",
    "URNM",
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
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_module(path: Path, name: str) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _asset_universe() -> Dict[str, List[str]]:
    """从 40/asset_classes.py 读取资产宇宙，失败时用内置兜底表。"""
    module = _load_module(
        _repo_root() / "40-周期神经网络系统" / "asset_classes.py", "asset_classes_40"
    )
    classes = getattr(module, "ASSET_CLASSES", None) if module else None
    if not isinstance(classes, dict):
        return {"commodity": list(_FALLBACK_COMMODITY), "index": list(_FALLBACK_INDEX)}

    commodity: List[str] = []
    for key in ("precious_metal", "industrial_metal", "energy"):
        commodity.extend(classes.get(key, {}).get("members", []))

    index: List[str] = []
    for key in ("us_index", "us_etf", "us_stock"):
        index.extend(classes.get(key, {}).get("members", []))

    # 去重保序；TLT 属利率类，不纳入「美股/指数」榜单
    def _dedupe(symbols: List[str]) -> List[str]:
        seen = set()
        out = []
        for sym in symbols:
            if sym and sym not in seen and sym != "TLT":
                seen.add(sym)
                out.append(sym)
        return out

    return {"commodity": _dedupe(commodity), "index": _dedupe(index)}


# ── 行情 ────────────────────────────────────────────────────────────
class OkxFeed:
    """优先走 51 okx_venue Port，失败回退 okx CLI / OKX 公共 REST。"""

    def __init__(self) -> None:
        self.cli_path = os.getenv("OKX_VENUE_CLI", "okx")
        self.profile = os.getenv("OKX_VENUE_PROFILE", "demo")
        self._venue: Optional[Any] = None
        src = _repo_root() / "51-OKX CLI 系统" / "src"
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
        try:
            from okx_venue import OkxCliVenue, VenueConfig  # noqa: WPS433

            self._venue = OkxCliVenue(VenueConfig.from_env())
        except Exception:
            self._venue = None

    def candles(self, inst_id: str) -> List[List[Any]]:
        if self._venue is not None:
            try:
                return self._venue.get_candles(inst_id, bar="1D", limit=CANDLE_LIMIT)["candles"]
            except Exception:
                pass
        candles = self._cli_candles(inst_id)
        return candles or self._rest_candles(inst_id)

    def _cli_candles(self, inst_id: str) -> List[List[Any]]:
        argv = [
            self.cli_path,
            "--profile",
            self.profile,
            "market",
            "candles",
            inst_id,
            "--bar",
            "1D",
            "--limit",
            str(CANDLE_LIMIT),
            "--json",
        ]
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=30, shell=False, check=False
            )
            if completed.returncode != 0:
                return []
            payload = json.loads((completed.stdout or "").strip() or "[]")
        except Exception:
            return []
        return payload if isinstance(payload, list) else []

    def _rest_candles(self, inst_id: str) -> List[List[Any]]:
        query = urlencode({"instId": inst_id, "bar": "1D", "limit": CANDLE_LIMIT})
        try:
            with urlopen(f"https://www.okx.com/api/v5/market/candles?{query}", timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, list) else []


# ── 40 周期网络上下文 / 评分 ─────────────────────────────────────────
def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_fresh(payload: Optional[dict], max_age_days: int) -> bool:
    raw = (payload or {}).get("generated_at")
    if not raw:
        return False
    try:
        generated = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - generated <= timedelta(days=max_age_days)


def _load_cycle_context() -> dict:
    base = _repo_root() / "40-周期神经网络系统"
    rotation = _read_json(base / "asset_rotation.json")
    mapping = _read_json(base / "strategy_mapping.json")
    cycle = _read_json(base / "cycle_state.json")

    context = {
        "quadrant": None,
        "stance": None,
        "position_band_pct": None,
        "cycle_state": None,
        "source_fresh": False,
        "generated_at": None,
    }
    if _is_fresh(rotation, CONTEXT_MAX_AGE_DAYS):
        context["quadrant"] = (rotation.get("merrill_clock") or {}).get("quadrant")
        context["generated_at"] = rotation.get("generated_at")
        context["source_fresh"] = True
    if _is_fresh(mapping, CONTEXT_MAX_AGE_DAYS):
        suggestion = mapping.get("strategy_suggestion") or {}
        context["stance"] = suggestion.get("stance")
        context["position_band_pct"] = suggestion.get("position_band_pct")
    if _is_fresh(cycle, CONTEXT_MAX_AGE_DAYS):
        context["cycle_state"] = (cycle.get("real_cycle") or {}).get("state")
    return context


def _load_nn_scores() -> Dict[str, dict]:
    matrix = _read_json(_repo_root() / "40-周期神经网络系统" / "cross_asset_matrix.json")
    if not _is_fresh(matrix, CONTEXT_MAX_AGE_DAYS):
        return {}
    assets = matrix.get("assets") if isinstance(matrix, dict) else None
    if not isinstance(assets, dict):
        return {}
    out: Dict[str, dict] = {}
    for symbol, entry in assets.items():
        if isinstance(entry, dict):
            out[str(symbol).upper()] = entry
    return out


# ── 评分 ────────────────────────────────────────────────────────────
def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _norm_momentum(pct: Optional[float]) -> Optional[float]:
    """-20%..+20% 线性映射到 0..1。"""
    if pct is None:
        return None
    return _clamp((pct + 20.0) / 40.0)


def _ohlc_rows(candles: List[List[Any]]) -> List[dict]:
    rows = []
    for item in candles or []:
        if not isinstance(item, (list, tuple)) or len(item) < 5:
            continue
        try:
            rows.append({"ts": int(item[0]), "close": float(item[4])})
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["ts"])
    return rows


def score_symbol(
    symbol: str, candles: List[List[Any]], nn_entry: Optional[dict], context: dict
) -> Optional[dict]:
    rows = _ohlc_rows(candles)
    closes = [r["close"] for r in rows if r["close"] > 0]
    if len(closes) < 30:
        return None

    last = closes[-1]
    ma20 = statistics.fmean(closes[-20:])
    ma200 = statistics.fmean(closes[-200:]) if len(closes) >= 200 else None

    def _mom(days: int) -> Optional[float]:
        if len(closes) <= days:
            return None
        base = closes[-days - 1]
        return None if base <= 0 else (last / base - 1.0) * 100.0

    mom7, mom30, mom90 = _mom(7), _mom(30), _mom(90)
    tech_parts = [(mom7, 0.30), (mom30, 0.35), (mom90, 0.15)]
    weighted, weight_sum = 0.0, 0.0
    for pct, weight in tech_parts:
        normalized = _norm_momentum(pct)
        if normalized is None:
            continue
        weighted += normalized * weight
        weight_sum += weight
    tech = weighted / weight_sum if weight_sum > 0 else 0.5
    structure = 0.5 * (1.0 if last > ma20 else 0.0) + 0.5 * (
        1.0 if ma200 is not None and last > ma200 else 0.0
    )
    tech_score = _clamp(tech * 0.8 + structure * 0.2)

    reasons = []
    if mom7 is not None:
        reasons.append(f"7日{mom7:+.1f}%")
    if mom30 is not None:
        reasons.append(f"30日{mom30:+.1f}%")
    reasons.append("站上MA20" if last > ma20 else "低于MA20")
    if ma200 is not None:
        reasons.append("站上MA200" if last > ma200 else "低于MA200")

    final = tech_score
    nn_score = None
    if nn_entry:
        nn_mom = _norm_momentum(nn_entry.get("momentum_3m_pct"))
        nn_above = nn_entry.get("above_ma200")
        if nn_mom is not None:
            nn_score = nn_mom * 0.7 + (0.3 if nn_above else 0.0)
            final = _clamp(tech_score * 0.65 + nn_score * 0.35)
            reasons.append(f"40周期3月动量{nn_entry.get('momentum_3m_pct'):+.1f}%")

    quadrant = context.get("quadrant")
    if (
        quadrant
        and quadrant in {"stagflation", "reflation"}
        and symbol in _asset_universe()["commodity"]
    ):
        reasons.append(f"周期象限{quadrant}利好实物资产")

    return {
        "symbol": symbol,
        "score": round(final, 4),
        "confidence": round(final, 4),
        "reasons": reasons[:5],
        "metrics": {
            "last_close": round(last, 6),
            "ma20": round(ma20, 6),
            "ma200": round(ma200, 6) if ma200 is not None else None,
            "mom7_pct": round(mom7, 2) if mom7 is not None else None,
            "mom30_pct": round(mom30, 2) if mom30 is not None else None,
            "mom90_pct": round(mom90, 2) if mom90 is not None else None,
            "nn_score": round(nn_score, 4) if nn_score is not None else None,
        },
    }


def build_pool(dry_run: bool = False) -> dict:
    universe = _asset_universe()
    context = _load_cycle_context()
    nn_scores = _load_nn_scores()
    feed = OkxFeed()

    jobs = []
    for category in ("commodity", "index"):
        for symbol in universe[category]:
            jobs.append((category, symbol))

    def _work(job) -> Optional[dict]:
        category, symbol = job
        candles = feed.candles(f"{symbol}-USDT-SWAP")
        scored = score_symbol(symbol, candles, nn_scores.get(symbol), context)
        if scored is None:
            return None
        scored["category"] = category
        scored["inst_id"] = f"{symbol}-USDT-SWAP"
        return scored

    results: List[dict] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for item in executor.map(_work, jobs):
            if item is not None:
                results.append(item)

    items: List[dict] = []
    for category in ("commodity", "index"):
        ranked = sorted(
            [r for r in results if r["category"] == category],
            key=lambda r: r["score"],
            reverse=True,
        )[:PER_CATEGORY_KEEP]
        for rank, item in enumerate(ranked, start=1):
            item["category_rank"] = rank
            items.append(item)

    pool = {
        "version": POOL_VERSION,
        "generated_at": _now_iso(),
        "source": "okx-cli+40-cycle",
        "context": context,
        "coverage": {
            "commodity": len([i for i in items if i["category"] == "commodity"]),
            "index": len([i for i in items if i["category"] == "index"]),
        },
        "items": items,
    }

    if not dry_run:
        POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = POOL_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, POOL_FILE)

    return pool


def main() -> int:
    parser = argparse.ArgumentParser(description="多资产榜单池生产者（OKX CLI + 40 周期网络）")
    parser.add_argument("--dry-run", action="store_true", help="只打印摘要，不写文件")
    args = parser.parse_args()

    pool = build_pool(dry_run=args.dry_run)
    for item in pool["items"]:
        print(
            f"[{item['category']}#{item['category_rank']}] {item['symbol']:<8} "
            f"score={item['score']:.3f} reasons={','.join(item['reasons'][:3])}"
        )
    print(
        f"coverage: commodity={pool['coverage']['commodity']} index={pool['coverage']['index']} "
        f"-> {POOL_FILE}"
    )
    return 0 if pool["items"] else 1


if __name__ == "__main__":
    sys.exit(main())
