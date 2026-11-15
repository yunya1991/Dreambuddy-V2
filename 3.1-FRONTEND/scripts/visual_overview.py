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
import math
import os
import sqlite3
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

# 默认资产池来自后端龙头注册表（前端/脚本零硬编码，口径见 leader_registry.DEFAULT_POOL）
MIN_PAIR_OBS = 60
# `etf_flow` 中的聚合/元信息行，不是单只 ETF 的净流入，不产 flow 边
_FLOW_AGGREGATE_KEYS = frozenset(
    {"total_flow", "total_net_flow", "latest_total_flow_btc", "record_count", "Total"}
)


def _default_assets():
    from l1agg.leader_registry import default_pool

    return default_pool()


def _parse_args(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--days", type=int, default=1200)
    args, _ = parser.parse_known_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        symbols = _default_assets()
    # 去重保序，最多 12 个资产（相关矩阵上限由能力层自律，这里只控制输入规模）
    seen = set()
    deduped = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            deduped.append(symbol)
    base = args.base.strip().upper() or deduped[0]
    if base not in deduped:
        deduped.insert(0, base)
    return deduped[:12], base, max(int(args.days), 120)


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
        return {}, [], [], unavailable, {}

    common = set.intersection(*(set(values) for values in raw.values()))
    dates = sorted(common)
    if len(dates) < MIN_PAIR_OBS:
        return (
            {},
            [],
            [],
            unavailable + [{"asset": "*", "reason": f"公共日期轴 {len(dates)} < {MIN_PAIR_OBS}"}],
            raw,
        )
    aligned = {name: [values[date] for date in dates] for name, values in raw.items()}
    # raw 保留逐标的自有历史（D-E16 聚合按成员各自可用日 rebase，禁止前向填充）
    return aligned, dates, dates[-1], unavailable, raw


def _collect(blocks, envelope, only=None):
    """把信封里的能力块合并进 blocks（不重算，先到先得）。"""
    for capability, block in ((envelope or {}).get("data") or {}).get("capabilities", {}).items():
        if only and capability not in only:
            continue
        blocks.setdefault(capability, block)


def _run(capability, **kwargs):
    from l1agg.capabilities.stats import run_capability

    return run_capability(capability, **kwargs)


# ------------------------------------------------------------ B 链路四面板（P0 编排）
def _zscore(values):
    """样本 z-score；样本 <2 或 std=0 返回 None（不伪造）。"""
    series = [float(v) for v in values if v is not None]
    if len(series) < 2:
        return None
    mean = sum(series) / len(series)
    var = sum((v - mean) ** 2 for v in series) / len(series)
    std = math.sqrt(var)
    if std <= 0.0:
        return None
    return (series[-1] - mean) / std


def _load_flows(days):
    """`etf_flow` 净流入 → flow 边事实（ETF 申购资金流向 BTC 现货）。

    口径：逐 ETF 取日频净流入（`mm_metrics`，单位百万美元），滚动 `FLOW_WINDOW`
    日求和后取样本 z-score 作为 `flow_z`；样本不足 2 个滚动窗的 ETF 直接跳过。
    未采集资产（无 `mm_metrics` 行）不产边——由 `flow_graph` 降级 corr-only（LT-G7）。
    """
    if not os.path.isfile(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            names = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT metric_name FROM mm_metrics WHERE sub_category = 'etf_flow'"
                ).fetchall()
            ]
        finally:
            conn.close()
    except sqlite3.Error:
        return []

    from l1agg.align import AlignError, load_daily
    from l1agg.capabilities.flow import DEFAULT_WINDOW

    window = int(DEFAULT_WINDOW)
    end_ts = int(datetime.now(tz=timezone.utc).timestamp()) + 86400
    start_ts = end_ts - int(days) * 86400
    rows = []
    for name in sorted(str(n) for n in names if n):
        if name in _FLOW_AGGREGATE_KEYS:
            continue
        try:
            series = load_daily(DB_PATH, "etf_flow", name, start_ts=start_ts, end_ts=end_ts)
        except (AlignError, OSError, sqlite3.Error):
            continue
        values = [series[day] for day in sorted(series)]
        if len(values) <= window:
            continue
        rolling = [sum(values[i - window : i]) for i in range(window, len(values) + 1)]
        flow_z = _zscore(rolling)
        if flow_z is None:
            continue
        rows.append(
            {
                "src": f"etf:{name}",
                "dst": "asset:BTC",
                "flow_z": round(flow_z, 6),
                "flow_usdt": round(rolling[-1], 2),
                "window": window,
                "direction": "net_out_of_src",
            }
        )
    return rows


def _flow_nodes(flows):
    """ETF → BTC 节点；标签取龙头注册表（缺失回落符号本身）。"""
    from l1agg.leader_registry import resolve

    binding = resolve("BTC")
    nodes = [
        {
            "id": "asset:BTC",
            "label": binding.label if binding else "BTC",
            "group": "asset",
        }
    ]
    seen = set()
    for row in flows:
        node_id = str(row.get("src") or "")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        nodes.append({"id": node_id, "label": node_id.split(":", 1)[-1], "group": "etf"})
    return nodes


def _min_rows(pool, symbol):
    """per-anchor 质量下限（LTL-14）；无锚定返回 0（交给能力层默认值）。"""
    if pool is None:
        return 0
    try:
        anchor = pool.resolve(symbol)
    except Exception:
        return 0
    if anchor is None:
        return 0
    try:
        return int(pool.min_rows_for(anchor))
    except Exception:
        return 0


def _lights_entries(raw, pool):
    """逐标的 D-E15 → `direction_rule.score` 轴值 → D-E19 输入（不重算、不补造）。"""
    from l1agg.direction_rule import score
    from l1agg.leader_registry import class_of, view_of
    from l1agg.trading import rule_inputs

    entries = []
    for symbol, history in raw.items():
        dates = sorted(history)
        prices = [float(history[day]) for day in dates]
        trend = _run("D-E15", prices=prices, dates=dates, symbol=symbol) or {}
        caps = ((trend.get("data") or {}).get("capabilities")) or {}
        entry = {
            "symbol": symbol,
            "class": view_of(symbol) or class_of(symbol) or "未分类",
            "as_of": dates[-1] if dates else None,
            "n": len(prices),
            "status": str((trend.get("quality") or {}).get("status") or "available"),
            "gate": "ok",
            # 外部风险旗标（VIX 分位/背离/曲线倒挂）未接 D-E19，留空不伪造 conflict
            "foresight_flags": [],
        }
        threshold = _min_rows(pool, symbol)
        if threshold:
            entry["min_rows"] = threshold
        if "D-E15" in caps:
            entry["scored"] = score(rule_inputs.build_inputs(caps))
        entries.append(entry)
    return entries


def _board_assets(aligned, base, counts, pool):
    """D-E17 入参：**公共日期轴**（与 D-E12 同口径，LT-AC5）+ 点亮计数（零重算）。"""
    from l1agg.leader_registry import resolve, view_of

    base_prices = aligned.get(base)
    assets = {}
    for symbol, prices in aligned.items():
        binding = resolve(symbol)
        assets[symbol] = {
            "prices": list(prices),
            "label": binding.label if binding else symbol,
            "view": view_of(symbol) or (binding.asset_class if binding else "未分类"),
            "min_rows": _min_rows(pool, symbol),
            "lit_n": int((counts.get(symbol) or {}).get("lit_n") or 0),
            "warm_n": int((counts.get(symbol) or {}).get("warm_n") or 0),
            "leader_prices": base_prices if symbol != base else None,
        }
    return assets


def _extra_panels(raw, aligned, base, blocks, envelopes, days):
    """一次进程产出 B 链路四面板：D-E19 点亮 → D-E16 聚合 → D-E17 看板 → D-E18 导图。"""
    from l1agg.asset_pool import load as load_asset_pool
    from l1agg.capabilities.aggregate import aggregate_curve, class_board
    from l1agg.capabilities.flow import flow_graph
    from l1agg.capabilities.lights import lights
    from l1agg.capabilities.visual import build_visual

    try:
        pool = load_asset_pool()
    except Exception:  # 配置缺失不阻塞其余面板（FAIL-OPEN）
        pool = None

    visuals = []

    # 1) D-E19 点亮（先算：D-E17 只消费 lit_n/warm_n 计数）
    entries = _lights_entries(raw, pool)
    lights_env = lights(entries) if entries else {}
    lights_block = ((lights_env.get("data") or {}).get("capabilities") or {}).get("D-E19") or {}
    light_rows = list(lights_block.get("lights") or [])
    counts = {str(row.get("symbol")): dict(row.get("summary") or {}) for row in light_rows}
    lights_payload = {
        "ok": bool(lights_env.get("ok")),
        "answer": lights_env.get("answer"),
        "quality": lights_env.get("quality"),
        "rows": light_rows,
        "meta": lights_block.get("meta") or {},
    }
    if lights_env:
        envelopes["D-E19"] = lights_env
        _collect(blocks, lights_env, only={"D-E19"})

    # 2) D-E16 聚合曲线（逐标的自有历史，成员 rebase 后加权）
    agg_env = aggregate_curve(raw) or {}
    if agg_env:
        envelopes["D-E16"] = agg_env
        _collect(blocks, agg_env, only={"D-E16"})
        visual = build_visual(
            capability="D-E16",
            data=agg_env.get("data") or {},
            quality_block=agg_env.get("quality"),
        )
        if visual is not None:
            visuals.append({"id": "series:d-e16", **visual})

    # 3) D-E17 类别看板（公共轴 + 组内 ret_60 降序）
    board_env = class_board(_board_assets(aligned, base, counts, pool)) or {}
    if board_env:
        envelopes["D-E17"] = board_env
        _collect(blocks, board_env, only={"D-E17"})
        visual = build_visual(
            capability="D-E17",
            data=board_env.get("data") or {},
            quality_block=board_env.get("quality"),
        )
        if visual is not None:
            visuals.append({"id": "table:d-e17", **visual})

    # 4) D-E18 资金流导图（无流数据 → corr-only，绝不伪造边）
    corr_block = (((envelopes.get("D-E05") or {}).get("data") or {}).get("capabilities") or {}).get(
        "D-E05"
    )
    flows = _load_flows(days)
    flow_env = flow_graph(flows, nodes=_flow_nodes(flows), corr_block=corr_block) or {}
    if flow_env:
        envelopes["D-E18"] = flow_env
        _collect(blocks, flow_env, only={"D-E18"})
        # graph 图由 flow_block 直接产出（`build_visual` 无 D-E18 生产者）
        flow_block = ((flow_env.get("data") or {}).get("capabilities") or {}).get("D-E18") or {}
        if flow_block.get("visual"):
            visuals.append({"id": "graph:d-e18", **flow_block["visual"]})

    return visuals, lights_payload


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
    add("series:d-e16", "多成员加权聚合曲线（先 rebase 后加权，逐点覆盖度）")
    add("table:d-e17", "类别看板：五类分组 + 组内 ret_60 降序 + 点亮计数")
    add("graph:d-e18", "资金流向导图：ETF 净流入 → BTC（无数据时降级相关网络）")
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

    series, dates, as_of, unavailable, raw = _load_series(symbols, days)
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
                    "lights": None,
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
    # B 链路四面板：同一进程内直调能力层（避免每图一次 python spawn）
    extra_visuals, lights_payload = _extra_panels(raw, series, base, blocks, envelopes, days)
    visuals.extend(extra_visuals)
    payload = {
        "ok": True,
        "as_of": as_of,
        "base": base,
        "assets": list(series),
        "unavailable": unavailable,
        "visuals": visuals,
        "lights": lights_payload,
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
