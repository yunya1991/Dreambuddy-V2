#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C 组自进化系统历史快照落盘。

每次运行：
  1. 对白名单 symbols 逐个调 EvolutionPipeline.run_symbol()
  2. 收集 action / level0_confidence / regime / l0_costs 等关键字段
  3. 追加一行 JSON 到 evolution_history.jsonl（原子写 + 滚动上限）
  4. 同时刷新 evolution_latest.json（供 ranking_backtest.py 和前端直接读）

和 42 run_bus.py 的关系：
  - run_bus.py 负责 B 组（42→50-NN）信号，已内置 bus_history.jsonl 归档
  - 本脚本负责 C 组（23 自进化独立路径）信号，evolution_history.jsonl 归档
  - 两者独立演进，互不依赖

用法：
  python3 run_evolution_snapshot.py [--symbols BTC,ETH,BNB] [--cap 500]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in (p, *p.parents):
        if (parent / ".git").is_dir() or (parent / ".git").is_file():
            return parent
    return p.parent.parent.parent.parent  # 兜底


_REPO = _find_repo_root()
_23_ROOT = _REPO / "23-四层闭环自进化交易架构"
_RUNTIME = _23_ROOT / "dreambuddy_evolution" / "runtime"

EVOLUTION_HISTORY_PATH = _RUNTIME / "evolution_history.jsonl"
EVOLUTION_LATEST_PATH = _RUNTIME / "evolution_latest.json"
GENE_ROOT = _23_ROOT / "dreambuddy_evolution" / "gene_data"

DEFAULT_SYMBOLS = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "HYPE",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "XAU",
    "XPT",
    "NG",
    "USO",
    "US500",
    "AMD",
    "NVDA",
]

HISTORY_CAP = 500


def _ensure_path() -> None:
    _RUNTIME.mkdir(parents=True, exist_ok=True)


def _append_history(entry: dict, cap: int = HISTORY_CAP) -> None:
    """追加一行到 evolution_history.jsonl（滚动上限，原子写）。"""
    _ensure_path()
    existing: List[str] = []
    if EVOLUTION_HISTORY_PATH.exists():
        try:
            existing = EVOLUTION_HISTORY_PATH.read_text(encoding="utf-8").splitlines()
        except Exception:
            existing = []

    if len(existing) >= cap:
        existing = existing[-(cap - 1) :]

    existing.append(json.dumps(entry, ensure_ascii=False))
    tmp = EVOLUTION_HISTORY_PATH.with_suffix(".jsonl.tmp")
    try:
        tmp.write_text("\n".join(existing) + "\n", encoding="utf-8")
        os.replace(tmp, EVOLUTION_HISTORY_PATH)
    except Exception:
        if tmp.exists():
            tmp.unlink()


def _write_latest(snapshot: dict) -> None:
    """刷新 evolution_latest.json（原子写）。"""
    _ensure_path()
    tmp = EVOLUTION_LATEST_PATH.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, EVOLUTION_LATEST_PATH)
    except Exception:
        if tmp.exists():
            tmp.unlink()


def _try_klines(symbol: str, days: int = 250) -> Optional[Dict[str, List[float]]]:
    """拉 K 线：本地缓存（多命名）→ OkxFeed CLI 兜底。"""
    cache_dir = _REPO / "11-易经推理系统" / "scripts" / "data" / "klines"

    # 候选命名
    for name in [
        f"{symbol}_1D.csv",
        f"{symbol}-USDT-SWAP_1D.csv",
        f"{symbol}-USDT-SWAP_1d.csv",
        f"{symbol}_USDT_SWAP_1d.csv",
        f"{symbol}_1D_full.csv",
    ]:
        f = cache_dir / name
        if f.exists():
            try:
                import pandas as pd

                df = pd.read_csv(f)
                col_map = {}
                for c in df.columns:
                    cl = c.strip().lower()
                    if "close" in cl:
                        col_map[c] = "close"
                    elif "high" in cl:
                        col_map[c] = "high"
                    elif "low" in cl:
                        col_map[c] = "low"
                if {"close", "high", "low"} <= set(col_map.values()):
                    df = df.rename(columns=col_map).tail(days)
                    if len(df) >= 60:
                        return {
                            "closes": df["close"].astype(float).values.tolist(),
                            "highs": df["high"].astype(float).values.tolist(),
                            "lows": df["low"].astype(float).values.tolist(),
                        }
            except Exception:
                continue

    # 兜底：OkxFeed CLI
    try:
        if "1-ARCHITECTURE/dreamos/cli" not in sys.path:
            sys.path.insert(0, str(_REPO / "1-ARCHITECTURE" / "dreamos" / "cli"))
        import pandas as pd
        from ranking_asset_pool import OkxFeed

        raw = OkxFeed().candles(f"{symbol}-USDT-SWAP")
        if raw and len(raw) >= 60:
            df = pd.DataFrame(
                raw,
                columns=["ts", "open", "high", "low", "close", "volume"]
                + [f"x{i}" for i in range(len(raw[0]) - 6)],
            )
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"]).tail(days)
            # 缓存
            f = cache_dir / f"{symbol}-USDT-SWAP_1D.csv"
            cache_dir.mkdir(parents=True, exist_ok=True)
            df[["ts", "open", "high", "low", "close", "volume"]].to_csv(f, index=False)
            return {
                "closes": df["close"].astype(float).values.tolist(),
                "highs": df["high"].astype(float).values.tolist(),
                "lows": df["low"].astype(float).values.tolist(),
            }
    except Exception:
        pass

    return None


def run_evolution_snapshot(
    symbols: Optional[List[str]] = None,
    cap: int = HISTORY_CAP,
) -> dict:
    """执行一次 23 EvolutionPipeline 快照落盘。"""
    symbols = symbols or DEFAULT_SYMBOLS

    # 保证 23 模块在 sys.path 里
    if str(_23_ROOT) not in sys.path:
        sys.path.insert(0, str(_23_ROOT))

    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    pipe = EvolutionPipeline(gene_root=GENE_ROOT)

    now_iso = datetime.now(timezone.utc).isoformat()
    results: List[dict] = []
    errors: List[dict] = []

    for sym in symbols:
        klines = _try_klines(sym)
        if klines is None:
            errors.append({"symbol": sym, "reason": "no_klines"})
            results.append(
                {
                    "symbol": sym,
                    "status": "no_klines",
                    "action": None,
                    "level0_confidence": None,
                    "regime": None,
                }
            )
            continue

        market_data = {
            "source_asset": "BTC",
            "symbol": sym,
            **klines,
        }

        try:
            raw = pipe.run_symbol(sym, market_data)
            entry = {
                "symbol": sym,
                "status": "ok",
                "action": str(raw.get("action", "WAIT")).upper(),
                "level0_confidence": float(raw.get("level0_confidence", 0.0) or 0.0),
                "regime": raw.get("regime"),
                "level0_costs": raw.get("level0_costs"),
                "aligned": raw.get("aligned"),
                "l4_v": raw.get("l4_v"),
                "l2_combo_id": (raw.get("l2_top_combo") or {}).get("combo_id"),
            }
        except Exception as exc:
            entry = {
                "symbol": sym,
                "status": "error",
                "action": None,
                "level0_confidence": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors.append({"symbol": sym, "error": entry["error"]})
            traceback.print_exc()

        results.append(entry)

    # 汇总 + 落盘
    snapshot = {
        "generated_at": now_iso,
        "source": "23-evolution-pipeline",
        "version": "1.0",
        "symbols": results,
        "errors": errors,
    }

    # 追加 history（整批一行）+ 刷新 latest
    _append_history(snapshot, cap=cap)
    _write_latest(snapshot)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    print(f"[evolution_snapshot] {now_iso}")
    print(f"  symbols: {len(results)}  ok={ok_count}  errors={len(errors)}")
    for r in results:
        if r["status"] == "ok":
            print(
                f"    {r['symbol']:8s}  {r['action']:5s}  conf={r['level0_confidence']:.3f}  regime={r.get('regime')}"
            )
    if errors:
        print("  errors:")
        for e in errors:
            print(f"    {e['symbol']:8s}  {e.get('reason', e.get('error', 'unknown'))}")
    print(f"  history → {EVOLUTION_HISTORY_PATH}")
    print(f"  latest  → {EVOLUTION_LATEST_PATH}")

    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="23 自进化系统快照落盘（C 组回测底座）")
    parser.add_argument("--symbols", default=None, help="逗号分隔 symbols（默认全白名单）")
    parser.add_argument("--cap", type=int, default=HISTORY_CAP, help="history 滚动上限")
    parser.add_argument("--dry-run", action="store_true", help="只跑不落盘")
    args = parser.parse_args()

    symbols = args.symbols.split(",") if args.symbols else None
    if args.dry_run:
        snapshot = run_evolution_snapshot(symbols=symbols, cap=args.cap)
        print(f"\n[dry-run] snapshot keys: {list(snapshot.keys())}")
        return 0

    run_evolution_snapshot(symbols=symbols, cap=args.cap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
