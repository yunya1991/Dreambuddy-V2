#!/usr/bin/env python3
"""类内龙头共振矩阵：每个成员相对**自己类别龙头**的 R(s)。

为什么需要：
  - resonance_matrix.json 只算 BTC 锚（加密层）；
  - cross_asset_matrix.json 只算 G1 龙头相对 BTC；
  - 50 的「龙头 → 成员」传导必须用成员与所属类别龙头的历史共振，
    否则贵金属/美股会拿 BTC 的相关性误传导。

数据源：18 统一价格源（G10，OKX 主源 + Binance fallback），USDT 永续日线 240 根。
输出：40/leader_resonance.json
  {generated_at, min_samples, granger_lags, granger_alpha,
   assets: {SYM: {class, leader, inst_id, corr0, lag_profile, beta, down_corr,
                  granger_p, n_samples, degraded}}}

fail-open：
  - 单标的拉取失败 → 该标的 degraded=fetch_failed，不阻塞其他标的；
  - 类别龙头失败 → 该类别成员标 leader_missing；
  - 脚本恒返回 0，避免中断 40 日更流水线。
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_40_ROOT = os.path.dirname(_SCRIPT_DIR)
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(_40_ROOT)
OUT = Path(_DREAMBUDDY_ROOT) / "40-周期神经网络系统" / "leader_resonance.json"

for _p in (_40_ROOT, _SCRIPT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.insert(0, os.path.join(_DREAMBUDDY_ROOT, "18-数据获取中心"))

from asset_classes import ASSET_CLASSES  # noqa: E402
from p3_cross_asset_matrix import (  # noqa: E402
    align_pair,
    fetch_daily_series,
    to_ccxt_swap_symbol,
)
from p3_resonance_matrix import (  # noqa: E402
    GRANGER_ALPHA,
    GRANGER_LAGS,
    MIN_SAMPLES,
    compute_resonance,
    granger_test,
)


def member_inst_id(sym: str, cfg: dict) -> str | None:
    """成员 instId：龙头的配置优先；其余按 sym-USDT-SWAP 约定。"""
    if sym == cfg.get("leader"):
        return cfg.get("inst_id")
    return f"{sym}-USDT-SWAP"


def build_member_entry(sym: str, cls: str, cfg: dict, member_series, leader_series) -> dict:
    """构造单个成员的龙头共振条目（fail-open）。"""
    entry = {
        "class": cls,
        "leader": cfg.get("leader"),
        "inst_id": member_inst_id(sym, cfg),
        "corr0": 1.0,
        "lag_profile": [1.0],
        "beta": 1.0,
        "down_corr": 1.0,
        "granger_p": None,
        "n_samples": 0,
        "degraded": [],
    }

    ts, closes = member_series if member_series else (None, None)
    if not closes:
        entry["degraded"].append("fetch_failed")
        return entry

    l_ts, l_closes = leader_series if leader_series else (None, None)
    if not l_closes:
        entry["degraded"].append("leader_missing")
        return entry

    a, b, n, deg = align_pair(l_ts, l_closes, ts, closes)
    entry["degraded"].extend(deg)
    entry["n_samples"] = n
    if n < MIN_SAMPLES:
        entry["degraded"].append("resonance_fallback")
        return entry

    r = compute_resonance(a, b)
    for key in ("corr0", "lag_profile", "beta", "down_corr"):
        entry[key] = r[key]
    if r.get("degraded"):
        entry["degraded"].append(str(r["degraded"]))

    entry["granger_p"] = granger_test(a, b, lags=GRANGER_LAGS)[1]
    return entry


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"=== p3_leader_resonance start {now} ===")

    assets: dict[str, dict] = {}
    classes_meta: dict[str, dict] = {}

    for cls, cfg in ASSET_CLASSES.items():
        leader = cfg.get("leader")
        leader_inst = cfg.get("inst_id")
        members = [m for m in (cfg.get("members") or []) if m != leader]
        if not leader or not leader_inst or not members:
            continue
        if cfg.get("session") == "macro_series_only":
            continue

        try:
            leader_ts, leader_closes = fetch_daily_series(to_ccxt_swap_symbol(leader_inst))
        except Exception as exc:  # noqa: BLE001  fail-open
            print(f"  [{cls}] leader {leader}: ERROR {exc}")
            leader_ts, leader_closes = None, None

        classes_meta[cls] = {
            "leader": leader,
            "n_members": len(members),
            "leader_ok": bool(leader_closes),
        }
        if leader_closes:
            print(f"  [{cls}] leader {leader}: {len(leader_closes)} bars")
        else:
            print(f"  [{cls}] leader {leader}: fetch failed")

        for sym in members:
            inst = member_inst_id(sym, cfg)
            try:
                ts, closes = fetch_daily_series(to_ccxt_swap_symbol(inst))
            except Exception as exc:  # noqa: BLE001
                print(f"    {sym}: ERROR {exc}")
                ts, closes = None, None
            entry = build_member_entry(sym, cls, cfg, (ts, closes), (leader_ts, leader_closes))
            assets[sym] = entry
            print(
                f"    {sym:<6} corr0={entry['corr0']:.3f} down_corr={entry['down_corr']:.3f} "
                f"n={entry['n_samples']} granger_p={entry['granger_p']} "
                f"degraded={entry['degraded']}"
            )

    output = {
        "generated_at": now,
        "min_samples": MIN_SAMPLES,
        "granger_lags": GRANGER_LAGS,
        "granger_alpha": GRANGER_ALPHA,
        "classes": classes_meta,
        "assets": assets,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"saved: {OUT} ({len(assets)} assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
