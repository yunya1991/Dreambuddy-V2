# -*- coding: utf-8 -*-
"""backtest_evaluator.py — E2 config 级回测评估器（shadow 代理口径）。

职责：evaluator(variant) → {is_metrics, oos_metrics, slice_metrics}，
供 ablation_gate 做过拟合 + 稳定性双判据准入。

口径声明（诚实边界）：
- 数据：11 域本地 K 线缓存（scripts/data/klines/*.csv，1H 真实行情），零外部请求；
- 映射：变体 threshold_bins → 回测参数（confidence 门控 / position_pct 仓位 /
  max_positions 并发上限 / interval 持有周期）；开关位掩码不映射（代理口径）；
- 策略：动量门控代理（24bar 动量过 confidence 门才开仓，持有 interval bar 平仓）；
- 分割：IS 前 70% / OOS 后 30%；slice = OOS 三等分；
- FAIL-OPEN：任何异常返回 {}（run_e2 视为该变体不可评估，不中断批次）。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
KLINE_DIR = _REPO_ROOT / "11-易经推理系统" / "scripts" / "data" / "klines"
DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "BNB")
INITIAL_CAPITAL = 10000.0
MOMENTUM_WINDOW = 24
MIN_BARS = 200


def _load_kline(symbol: str) -> List[Dict[str, float]]:
    path = KLINE_DIR / (symbol + "_1H.csv")
    if not path.exists():
        return []
    rows: List[Dict[str, float]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    rows.append(float(r["close"]))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return rows


def _backtest_segment(
    closes: List[float],
    start: int,
    end: int,
    confidence: float,
    position_pct: float,
    max_positions: int,
    interval_bars: int,
) -> Dict[str, Any]:
    capital = INITIAL_CAPITAL
    open_pos: List[Dict[str, float]] = []
    trade_pnls: List[float] = []
    peak = capital
    max_dd = 0.0
    for i in range(start, end):
        c = closes[i]
        # 先平仓到期持仓
        for p in list(open_pos):
            p["bars"] += 1
            if p["bars"] >= interval_bars:
                pnl = (c - p["entry"]) * p["qty"] * p["dir"]
                capital += pnl
                trade_pnls.append(pnl)
                open_pos.remove(p)
        # 动量信号 + confidence 门控开仓
        if i >= MOMENTUM_WINDOW and closes[i - MOMENTUM_WINDOW] > 0:
            sig = (c - closes[i - MOMENTUM_WINDOW]) / closes[i - MOMENTUM_WINDOW]
            sig = max(-1.0, min(1.0, sig))
            if abs(sig) >= confidence and len(open_pos) < max_positions and c > 0:
                qty = (capital * position_pct) / c
                if qty > 0:
                    open_pos.append(
                        {
                            "dir": 1.0 if sig > 0 else -1.0,
                            "entry": c,
                            "qty": qty,
                            "bars": 0,
                        }
                    )
        # 权益曲线回撤
        equity = capital + sum((c - p["entry"]) * p["qty"] * p["dir"] for p in open_pos)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak) if peak > 0 else max_dd
    # 段末强平
    last = closes[end - 1] if end > start else 0.0
    for p in open_pos:
        pnl = (last - p["entry"]) * p["qty"] * p["dir"]
        capital += pnl
        trade_pnls.append(pnl)
    n = len(trade_pnls)
    wins = sum(1 for t in trade_pnls if t > 0)
    if n >= 2:
        mean = sum(trade_pnls) / n
        var = sum((t - mean) ** 2 for t in trade_pnls) / (n - 1)
        sharpe = mean / (var**0.5) if var > 0 else 0.0
    else:
        sharpe = 0.0
    return {
        "total_pnl_pct": round((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 4),
        "n_trades": n,
        "win_rate": round(wins / n, 4) if n else 0.0,
        "sharpe_per_trade": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
    }


# ============================================================
# 可插拔多源加载层（2026-11-07 升级：不局限于 11 域 K 线缓存）
# 源规格（source spec）支持四种形态：
#   a) {"type": "kline_csv", "dir": 路径, "symbols": [..]}   — CSV 目录源（任意域）
#   b) {"type": "json_ts", "path": 路径, "name": 名称}        — JSON dict（含 closes 数组，如 23 域 btc_1h_ts.json）
#   c) {"type": "json_closes", "path": 路径, "name": 名称}    — JSON 纯收盘价 list（如 btc_closes_1h.json）
#   d) {"type": "memory", "name": 名称, "closes": [..]}      — 内存序列源（调用方自带）
# FAIL-OPEN：单源加载失败跳过该源，不中断批次。
def _load_source(spec: Dict[str, Any]) -> Dict[str, List[float]]:
    """加载单个源规格 → {名称: 收盘价序列}。异常返回空 dict（FAIL-OPEN）。"""
    try:
        stype = str(spec.get("type") or "")
        if stype == "kline_csv":
            d = Path(spec["dir"])
            syms = spec.get("symbols") or []
            out: Dict[str, List[float]] = {}
            for sym in syms:
                path = d / (str(sym) + "_1H.csv")
                if not path.exists():
                    continue
                rows = []
                with path.open("r", encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        try:
                            rows.append(float(r["close"]))
                        except (KeyError, TypeError, ValueError):
                            continue
                if len(rows) >= MIN_BARS:
                    out[str(sym)] = rows
            return out
        if stype == "json_ts":
            data = json.loads(Path(spec["path"]).read_text(encoding="utf-8"))
            closes = [float(x) for x in data.get("closes", [])]
            name = str(spec.get("name") or data.get("symbol") or Path(spec["path"]).stem)
            return {name: closes} if len(closes) >= MIN_BARS else {}
        if stype == "json_closes":
            closes = [float(x) for x in json.loads(Path(spec["path"]).read_text(encoding="utf-8"))]
            name = str(spec.get("name") or Path(spec["path"]).stem)
            return {name: closes} if len(closes) >= MIN_BARS else {}
        if stype == "memory":
            closes = [float(x) for x in spec.get("closes", [])]
            return {str(spec["name"]): closes} if len(closes) >= MIN_BARS else {}
        return {}
    except Exception:
        return {}


def load_extra_sources(
    extra_sources: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, List[float]]:
    """批量加载额外源（去重：后加载不覆盖先加载）。FAIL-OPEN。"""
    merged: Dict[str, List[float]] = {}
    for spec in extra_sources or []:
        for name, closes in _load_source(spec).items():
            merged.setdefault(name, closes)
    return merged


def make_evaluator(
    symbols: Optional[List[str]] = None,
    extra_sources: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    """多源评估器：默认 11 域 K 线缓存；extra_sources 可插拔接入任意域数据源
    （kline_csv / json_ts / json_closes / memory 四种源规格，见 _load_source）。"""
    use = symbols or list(DEFAULT_SYMBOLS)
    series = {s: _load_kline(s) for s in use}
    series = {s: k for s, k in series.items() if len(k) >= MIN_BARS}
    for name, closes in load_extra_sources(extra_sources).items():
        series.setdefault(name, closes)

    def evaluator(variant: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not series:
                return {}
            sv = variant.get("struct_vector") or {}
            tb = sv.get("threshold_bins") or [10, 3, 10, 4]
            confidence = min(0.095, max(0.005, float(tb[0]) * 0.005))
            max_positions = max(1, int(tb[1]))
            position_pct = min(1.0, max(0.01, float(tb[2]) / 100.0))
            interval_bars = max(2, int(tb[3]))

            agg: Dict[str, Dict[str, float]] = {}
            for name, (seg_start, seg_end) in (
                ("is", (0.0, 0.7)),
                ("oos", (0.7, 1.0)),
                ("slice0", (0.7, 0.8)),
                ("slice1", (0.8, 0.9)),
                ("slice2", (0.9, 1.0)),
            ):
                pnl = 0.0
                trades = 0
                wins = 0
                dd = 0.0
                for closes in series.values():
                    n = len(closes)
                    s = int(n * seg_start)
                    e = max(s + 1, int(n * seg_end))
                    r = _backtest_segment(
                        closes,
                        s,
                        e,
                        confidence,
                        position_pct,
                        max_positions,
                        interval_bars,
                    )
                    pnl += r["total_pnl_pct"]
                    trades += r["n_trades"]
                    wins += r["win_rate"] * r["n_trades"]
                    dd = max(dd, r["max_drawdown_pct"])
                agg[name] = {
                    "total_pnl_pct": round(pnl, 4),
                    "n_trades": trades,
                    "win_rate": round(wins / trades, 4) if trades else 0.0,
                    "max_drawdown_pct": round(dd, 4),
                }
            return {
                "is_metrics": agg["is"],
                "oos_metrics": agg["oos"],
                "slice_metrics": [
                    agg["slice0"]["total_pnl_pct"],
                    agg["slice1"]["total_pnl_pct"],
                    agg["slice2"]["total_pnl_pct"],
                ],
                "evaluator": "backtest_evaluator_proxy_v2_multisrc",
                "data_symbols": sorted(series.keys()),
            }
        except Exception:
            return {}

    return evaluator


if __name__ == "__main__":
    ev = make_evaluator()
    demo = {"struct_vector": {"threshold_bins": [10, 3, 10, 4]}}
    import json

    print(json.dumps(ev(demo), ensure_ascii=False, indent=2))
