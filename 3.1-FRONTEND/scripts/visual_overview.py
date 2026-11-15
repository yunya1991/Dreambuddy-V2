#!/usr/bin/env python3
"""visual_overview.py — T3 全景 / T2 曲线聚合器（SPEC-54）。

供 `/api/visual/overview` Next.js API Route 调用：读 L0（只读 DB）→ 调能力层
→ 产出 `tree/graph/series/table` 图规格 + 动态推荐列表。

约定：
  - 前端零统计，所有数值来自能力层信封（ADR-V13 零重算）；
  - 只读，FAIL-OPEN：任何异常输出 `{ok: false}`，由前端降级空态；
  - 资产池可由 `--symbols` 覆盖（页面用回测排行榜 Top 标的驱动）。

用法：
  python3 scripts/visual_overview.py [--symbols BTC,ETH,SOL] [--base BTC] [--days 1200]
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
_L1_DIR = os.path.join(_REPO_ROOT, "54-L1架构能力聚合层")
if _L1_DIR not in sys.path:
    sys.path.insert(0, _L1_DIR)

DB_PATH = os.environ.get("DREAMBUDDY_CORE_DB") or os.path.join(
    _REPO_ROOT, "19-数据访问层", "data", "dreambuddy_core.db"
)

# 默认资产池：覆盖加密 / 贵金属 / 股指 / 美股（均已在 40 层龙头注册表绑定）
DEFAULT_ASSETS = ("BTC", "ETH", "SOL", "XAU", "US500", "NVDA", "AAPL")
MIN_PAIR_OBS = 60


def _parse_args(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--days", type=int, default=1200)
    args, _ = parser.parse_known_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        symbols = list(DEFAULT_ASSETS)
    # 去重保序，最多 8 个资产（相关矩阵上限由能力层自律，这里只控制输入规模）
    seen = set()
    deduped = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            deduped.append(symbol)
    base = args.base.strip().upper() or deduped[0]
    if base not in deduped:
        deduped.insert(0, base)
    return deduped[:8], base, max(int(args.days), 120)


def _load_series(symbols, days):
    """读龙头序列并对齐公共日期轴；未采集的资产记录原因后跳过。"""
    from l1agg.align import AlignError, load_leader

    raw = {}
    unavailable = []
    for symbol in symbols:
        try:
            series = load_leader(DB_PATH, symbol, days=days)
        except (AlignError, OSError) as exc:
            unavailable.append({"asset": symbol, "reason": str(exc)})
            continue
        if len(series) < MIN_PAIR_OBS:
            unavailable.append(
                {"asset": symbol, "reason": f"有效观测 {len(series)} < {MIN_PAIR_OBS}"}
            )
            continue
        raw[symbol] = series

    if not raw:
        return {}, [], [], unavailable

    common = set.intersection(*(set(values) for values in raw.values()))
    dates = sorted(common)
    if len(dates) < MIN_PAIR_OBS:
        return (
            {},
            [],
            [],
            unavailable + [{"asset": "*", "reason": f"公共日期轴 {len(dates)} < {MIN_PAIR_OBS}"}],
        )
    aligned = {name: [values[date] for date in dates] for name, values in raw.items()}
    return aligned, dates, dates[-1], unavailable


def _collect(blocks, envelope, only=None):
    """把信封里的能力块合并进 blocks（不重算，先到先得）。"""
    for capability, block in ((envelope or {}).get("data") or {}).get("capabilities", {}).items():
        if only and capability not in only:
            continue
        blocks.setdefault(capability, block)


def _run(capability, **kwargs):
    from l1agg.capabilities.stats import run_capability

    return run_capability(capability, **kwargs)


def _build_visuals(blocks, envelopes, base, as_of):
    """产出图规格列表；任何门禁不通过的能力不产图（FAIL-OPEN）。"""
    from l1agg.capabilities.overview import build_graph, build_tree
    from l1agg.capabilities.visual import build_visual

    visuals = []

    tree = build_tree(blocks=blocks, as_of=as_of)
    visuals.append({"id": "tree", **tree})

    graph = build_graph(blocks=blocks)
    if graph is not None:
        visuals.append({"id": "graph", **graph})

    for capability, visual_id in (
        ("D-E15", "series:d-e15"),
        ("D-E10", "series:d-e10"),
        ("D-E12", "table:d-e12"),
    ):
        envelope = envelopes.get(capability)
        if not envelope:
            continue
        visual = build_visual(
            capability=capability,
            data=envelope.get("data") or {},
            quality_block=envelope.get("quality"),
        )
        if visual is not None:
            visuals.append({"id": visual_id, **visual})

    return visuals


def _recommend(visuals, blocks, assets, base, unavailable):
    """动态推荐：只推荐真实产出的图，理由来自能力块与门禁事实。"""
    by_id = {visual["id"]: visual for visual in visuals}
    items = []

    def add(visual_id, reason):
        if visual_id in by_id:
            items.append(
                {
                    "id": visual_id,
                    "title": by_id[visual_id]["title"],
                    "kind": by_id[visual_id]["kind"],
                    "reason": reason,
                }
            )

    pairs = ((blocks.get("D-E05") or {}).get("relationship_topk") or {}).get("pairs") or []
    add("tree", f"{len(assets)} 个资产 / {len(blocks)} 项能力已聚合，可逐层下钻")
    add("graph", f"D-E05 共振网络：{len(assets)} 节点 / {len(pairs)} 条相关边")
    add("series:d-e15", f"{base} 价格与 EMA26 平滑曲线")
    add("series:d-e10", f"{base} 回撤路径（MDD 口径同 D20）")
    add("table:d-e12", "跨资产对齐切片：有效观测 / 陈旧占比 / 区间收益")
    if unavailable:
        items.append(
            {
                "id": "",
                "title": "未采集资产",
                "kind": "note",
                "reason": "、".join(f"{row['asset']}" for row in unavailable),
            }
        )
    return items


def main():
    symbols, base, days = _parse_args(sys.argv[1:])
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(f"db not found: {DB_PATH}")

    series, dates, as_of, unavailable = _load_series(symbols, days)
    if not series:
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "as_of": None,
                    "base": base,
                    "assets": [],
                    "unavailable": unavailable,
                    "visuals": [],
                    "recommended": [],
                    "degraded": True,
                    "error": "no_collected_assets",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        return

    blocks = {}
    envelopes = {}

    # 先跑多资产矩阵：D-E05 全景叶依赖 matrix/average_correlation/relationship_topk
    matrix = _run("D-E05", series=series, dates=dates)
    envelopes["D-E05"] = matrix
    _collect(blocks, matrix, only={"D-E05"})

    other = next((name for name in series if name != base), None)
    if other is not None:
        pair = _run(
            "D-E06", x=series[base], y=series[other], dates=dates, x_name=base, y_name=other
        )
        envelopes["D-E06"] = pair
        # 先到先得：矩阵块保留 D-E05，pair 只补 D-E06 / D-E11
        _collect(blocks, pair)

    alignment = _run("D-E12", series=series, dates=dates)
    envelopes["D-E12"] = alignment
    _collect(blocks, alignment)

    prices = series[base]
    drawdown = _run("D-E10", prices=prices, dates=dates, symbol=base)
    envelopes["D-E10"] = drawdown
    _collect(blocks, drawdown)

    trend = _run("D-E15", prices=prices, dates=dates, symbol=base)
    envelopes["D-E15"] = trend
    _collect(blocks, trend)

    returns = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices)) if prices[i - 1]]
    significance = _run("D-G22", series=returns, name=base)
    envelopes["D-G22"] = significance
    _collect(blocks, significance)

    visuals = _build_visuals(blocks, envelopes, base, as_of)
    payload = {
        "ok": True,
        "as_of": as_of,
        "base": base,
        "assets": list(series),
        "unavailable": unavailable,
        "visuals": visuals,
        "recommended": _recommend(visuals, blocks, list(series), base, unavailable),
        "degraded": bool(unavailable)
        or any((envelope or {}).get("ok") is False for envelope in envelopes.values()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # FAIL-OPEN：前端降级空态，不抛给 Next.js
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=3),
                    "visuals": [],
                    "recommended": [],
                    "degraded": True,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
