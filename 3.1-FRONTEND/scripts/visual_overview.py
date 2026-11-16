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
# D-E19 `conflict` 只读旗标的输入序列与阈值（SPEC §5.3；T10Y2Y 未入池时 `curve_inverted` 不可达）
VIX_SYMBOL = "VIX"
CURVE_SYMBOL = "T10Y2Y"
VIX_PCT_THRESHOLD = 0.90
FLAG_WINDOW = 20

# I36 前瞻分布（SPEC §4.0 第 5 条 / §5.1 `foresight`）：`q90−q10` 宽度只作**证据与旗标**，
# 不进轴（`foresight.strength` 仍取 `coherence` 归一，保持 LT-AC3 一致性契约）
FORESIGHT_HORIZON = 20
FORESIGHT_MIN_PAIRS = 500
FORESIGHT_DISPERSION_REF = 2.5632  # 2×Φ⁻¹(0.9)：正态 90% 区间宽度的 σ 倍数
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
    parser.add_argument("--history", type=int, default=0)
    args, _ = parser.parse_known_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        symbols = _default_assets()
    # 去重保序，最多 16 个资产（默认池 13 + 动态美股龙头 3 的余量）
    seen = set()
    deduped = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            deduped.append(symbol)
    base = args.base.strip().upper() or deduped[0]
    if base not in deduped:
        deduped.insert(0, base)
    return deduped[:16], base, max(int(args.days), 120), max(0, int(args.history))


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
    # 面板 as_of 取各资产最新日的最大值：保留最新数据，不被公共日期轴截断；
    # 每个资产的实际最新日随 lights.rows[].as_of 下发并在前端行内标注。
    panel_as_of = max((max(values) for values in raw.values() if values), default=dates[-1])
    return aligned, dates, panel_as_of, unavailable, raw


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


def _load_l0_flow_series(base, days):
    """L0 巨鲸净流入（USD → 亿美元）→ T3 资金流序列叶；无数据返回 None（不伪造）。"""
    from l1agg.align import AlignError, load_daily

    end_ts = int(datetime.now(tz=timezone.utc).timestamp()) + 86400
    start_ts = end_ts - int(days) * 86400
    try:
        history = load_daily(
            DB_PATH,
            "exchanges_whales",
            "whale_netflow_to_ex_usd",
            start_ts=start_ts,
            end_ts=end_ts,
        )
    except (AlignError, OSError, sqlite3.Error):
        return None
    if not history:
        return None
    latest_day = max(history)
    return [
        {
            "asset": base,
            "series_id": "exchanges_whales::whale_netflow_to_ex_usd",
            "value": history[latest_day] / 1e8,
        }
    ]


def _run_crowding(base):
    """D-A14：复用 L1 直答同一取数口径；数据不足时仍返回信封，让树披露门禁原因。"""
    try:
        from data_query_executor import _load_crowding_panel
    except Exception:  # noqa: BLE001  FAIL-OPEN：直答模块不可用时不阻塞其余图
        return None
    panel, dates, _missing = _load_crowding_panel()
    envelope = _run("D-A14", series=panel, dates=dates, symbol=base)
    data = envelope.get("data")
    if not isinstance(data, dict):
        data = {}
        envelope["data"] = data
    if not (data.get("capabilities") or {}):
        # empty 信封不带能力块；补一条 no_data 事实，供 T3 树披露真实门禁原因。
        reason = (envelope.get("quality") or {}).get("degraded_reason") or "拥挤度数据不足"
        data["capabilities"] = {"D-A14": {"gate": "no_data", "reason": reason}}
    return envelope


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


def _foresight_reference(raw, symbol, base=None):
    """前瞻共振参考标的：`base` 优先（龙头 vs 成员，SPEC §5.1）；`base` 缺席或自比时取首个其他标的。"""
    candidates = [name for name in raw if name != symbol]
    if not candidates:
        return None
    if base and base != symbol and base in raw:
        return base
    return candidates[0]


def _daily_returns(history, dates):
    """价格序列 → `{日期: 简单收益}`（首日无前值不产收益，不伪造）。"""
    out = {}
    prev = None
    for day in dates:
        price = float(history[day])
        if prev is not None and prev > 0.0:
            out[day] = price / prev - 1.0
        prev = price
    return out


def _percentile_rank(values, value):
    """经验 CDF：`values` 中 ≤ `value` 的占比（[0,1]）；空序列 → None。"""
    if not values:
        return None
    return sum(1 for item in values if item <= value) / float(len(values))


def _conflict_flags(raw, symbol, as_of=None):
    """D-E19 `conflict` 只读旗标（SPEC §5.3）：只读已加载序列，不改 `foresight` 强度。

    - `vix_pct_ge_0.90`：VIX 在截至 `as_of` 的全历史经验分位 ≥ 0.90；
    - `vix_divergence`：标的自 20 日与 VIX 同向上行（价格涨、波动率也涨）；
    - `curve_inverted`：`T10Y2Y` 最新值 < 0（该序列未入池时不可达，不伪造）。
    """
    flags = []
    history = raw.get(symbol) or {}
    dates = sorted(day for day in history if not as_of or day <= as_of)
    vix = raw.get(VIX_SYMBOL) or {}
    if dates and vix:
        vix_dates = sorted(day for day in vix if not as_of or day <= as_of)
        if vix_dates:
            now = float(vix[vix_dates[-1]])
            rank = _percentile_rank([float(vix[day]) for day in vix_dates], now)
            if rank is not None and rank >= VIX_PCT_THRESHOLD:
                flags.append("vix_pct_ge_0.90")
        if symbol != VIX_SYMBOL:
            common = [day for day in dates if day in vix]
            if len(common) > FLAG_WINDOW:
                start, end = common[-FLAG_WINDOW - 1], common[-1]
                if float(history[end]) > float(history[start]) and float(vix[end]) > float(
                    vix[start]
                ):
                    flags.append("vix_divergence")
    curve = raw.get(CURVE_SYMBOL) or {}
    if curve:
        curve_dates = sorted(day for day in curve if not as_of or day <= as_of)
        if curve_dates and float(curve[curve_dates[-1]]) < 0.0:
            flags.append("curve_inverted")
    return flags


def _forward_distribution(returns, dates, *, horizon=None, min_pairs=None):
    """I36 前瞻分布（`q10/q50/q90/dispersion`）：不重算，只调方法层。

    `x` = 过去 `horizon` 日累计收益、`y` = 未来 `horizon` 日**已实现**累计收益
    （构造只用 `t+horizon` 之前的数据，不改写 `as_of` 截断后的样本）；
    有效对 `< min_pairs` 或方法层 `gate != ok` → 返回 None（不补造、不降级伪造）。
    """
    from l1agg.methods import run as run_method

    horizon = FORESIGHT_HORIZON if horizon is None else int(horizon)
    min_pairs = FORESIGHT_MIN_PAIRS if min_pairs is None else int(min_pairs)
    series = [float(returns[day]) for day in dates if day in returns]
    if len(series) < min_pairs + 2 * horizon:
        return None
    xs, ys = [], []
    for index in range(horizon, len(series) - horizon):
        xs.append(sum(series[index - horizon + 1 : index + 1]))
        ys.append(sum(series[index + 1 : index + horizon + 1]))
    if len(xs) < min_pairs:
        return None
    outcome = run_method("I36", {"x": xs, "y": ys}) or {}
    if str(outcome.get("gate")) != "ok":
        return None
    result = outcome.get("result") or {}
    dispersion = result.get("dispersion")
    if dispersion is None:
        return None
    recent = series[-horizon:]
    mean = sum(recent) / float(len(recent))
    scale = (sum((value - mean) ** 2 for value in recent) / float(len(recent))) ** 0.5
    scale *= horizon**0.5
    return {
        "capability": "I36",
        "horizon": horizon,
        "n": len(xs),
        "q10": result.get("q10"),
        "q50": result.get("q50"),
        "q90": result.get("q90"),
        "dispersion": float(dispersion),
        "scale": round(scale, 6) if scale > 0.0 else None,
        "dispersion_ref": FORESIGHT_DISPERSION_REF,
    }


def _forward_dispersion_flag(forward):
    """I36 宽度 ≥ 正态校准宽度（`2×1.2816σ`）→ `forward_dispersion_wide`（尾部风险扩张）。

    只做轴级旗标披露，不在 `CONFLICT_FLAGS` 内，因此不改变 `lights.state`。
    """
    scale = (forward or {}).get("scale")
    dispersion = (forward or {}).get("dispersion")
    if not scale or dispersion is None:
        return None
    if float(dispersion) >= FORESIGHT_DISPERSION_REF * float(scale):
        return "forward_dispersion_wide"
    return None


def _lights_entries(raw, pool, *, as_of=None, base=None):
    """逐标的 D-E15 → `direction_rule.score` 轴值（+ I39 cycle / D-E11 共振）→ D-E19 输入（不重算、不补造）。"""
    from l1agg.capabilities.lights import I39_MIN_N, cycle_from_bandpass
    from l1agg.direction_rule import score
    from l1agg.leader_registry import class_of, view_of
    from l1agg.methods import run as run_method
    from l1agg.trading import rule_inputs

    returns = {}
    for symbol, history in raw.items():
        days = sorted(day for day in history if not as_of or day <= as_of)
        returns[symbol] = _daily_returns(history, days)

    entries = []
    for symbol, history in raw.items():
        dates = sorted(day for day in history if not as_of or day <= as_of)
        if not dates:
            continue
        prices = [float(history[day]) for day in dates]
        trend = _run("D-E15", prices=prices, dates=dates, symbol=symbol) or {}
        caps = dict(((trend.get("data") or {}).get("capabilities")) or {})
        # 前瞻共振（D-E11/C18）：与参考标的的自然月同向率。C18 契约吃**收益**序列
        # （`_monthly_returns` 按日收益复利），传价格会让每月乘积恒正 → ratio 恒 1.0；
        # 缺参考/对齐点不足时该块缺席，由 direction_rule 打 `coherence_missing`（不补零）
        reference = _foresight_reference(raw, symbol, base)
        if reference:
            other = returns.get(reference) or {}
            common = [day for day in dates if day in returns[symbol] and day in other]
            if common:
                pair = (
                    _run(
                        "D-E11",
                        x=[returns[symbol][day] for day in common],
                        y=[other[day] for day in common],
                        dates=common,
                    )
                    or {}
                )
                pair_caps = (pair.get("data") or {}).get("capabilities") or {}
                if "D-E11" in pair_caps:
                    caps["D-E11"] = pair_caps["D-E11"]
        entry = {
            "symbol": symbol,
            "class": view_of(symbol) or class_of(symbol) or "未分类",
            "as_of": dates[-1] if dates else None,
            "n": len(prices),
            "status": str((trend.get("quality") or {}).get("status") or "available"),
            "gate": "ok",
            # 外部风险旗标（VIX 分位/背离/曲线倒挂）：只读已加载序列，未接线项不伪造
            "foresight_flags": _conflict_flags(raw, symbol, as_of),
        }
        threshold = _min_rows(pool, symbol)
        if threshold:
            entry["min_rows"] = threshold
        # foresight 的统计事实（I36 前瞻分布宽度）：只披露 + 轴级旗标，不改轴强度
        forward = _forward_distribution(returns.get(symbol) or {}, dates)
        if forward:
            entry["forward_distribution"] = forward
            flag = _forward_dispersion_flag(forward)
            if flag:
                entry["foresight_flags"].append(flag)
            entry["foresight_evidence"] = {
                "method": "I36",
                "horizon": forward["horizon"],
                "q10": forward["q10"],
                "q50": forward["q50"],
                "q90": forward["q90"],
                "dispersion": forward["dispersion"],
                "pairs": forward["n"],
            }
        if "D-E15" in caps:
            entry["scored"] = score(rule_inputs.build_inputs(caps))
        # cycle 轴：I39 带通（min_n=750；样本不足由方法层返回非 ok，不产周期事实）
        if len(prices) >= I39_MIN_N:
            outcome = run_method("I39", {"series": prices}) or {}
            if str(outcome.get("gate")) == "ok":
                entry["cycle"] = cycle_from_bandpass(outcome.get("result") or {})
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


def _core_assets():
    """主览图核心资产（BTC/黄金/标普/原油）→ 后端注册表标签，前端零硬编码。"""
    from l1agg.capabilities.visual import CORE_ASSET_KEYS
    from l1agg.leader_registry import resolve

    out = []
    for symbol in CORE_ASSET_KEYS:
        binding = resolve(symbol)
        out.append({"key": symbol, "label": binding.label if binding else symbol})
    return out


def _lights_history_cache_path():
    """离线制品路径：54 侧 artifacts，按 base/upto/periods/step 命中即复用。"""
    import l1agg

    root = os.path.dirname(os.path.dirname(os.path.abspath(l1agg.__file__)))
    return os.path.join(root, "artifacts", "visual", "lights_history.json")


def _lights_history(
    raw,
    pool,
    *,
    base,
    upto,
    periods,
    step=5,
):
    """逐期回放 D-E19 点亮（T9-2 影带）：同一进程内按 as_of 截断历史，每 `step` 个交易日采一期。

    不重算任何统计口径——每期都走与最新一期完全相同的 `_lights_entries → lights` 链路；
    只保留后端判定出的 state/strength/summary，前端零重算。期数不足时不补造。
    """
    from l1agg.capabilities.lights import lights

    cache_path = _lights_history_cache_path()
    signature = {"base": base, "upto": upto or "", "periods": int(periods), "step": int(step)}
    try:
        if os.path.isfile(cache_path):
            with open(cache_path, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
            if all(cached.get(key) == value for key, value in signature.items()) and cached.get(
                "history"
            ):
                return cached["history"]
    except (OSError, ValueError):
        pass

    calendar = sorted(
        {day for history in raw.values() for day in history if not upto or day <= upto}
    )
    if not calendar or periods <= 0:
        return []
    picks = calendar[::-1][:: max(1, int(step))][: int(periods)]
    out = []
    for day in sorted(picks):
        entries = _lights_entries(raw, pool, as_of=day, base=base)
        env = lights(entries) if entries else {}
        block = ((env.get("data") or {}).get("capabilities") or {}).get("D-E19") or {}
        rows = list(block.get("lights") or [])
        if not rows:
            continue
        out.append({"as_of": day, "rows": rows})

    if out:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        **signature,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "history": out,
                    },
                    fh,
                    ensure_ascii=False,
                )
        except OSError:
            pass
    return out


def _row_state(row, lit_pct: float, warm_pct: float):
    """合成状态（只读投影）：conflict 轴优先，其次按 strength 与阈值分档。"""
    axes = row.get("axes") or {}
    if any(str((axes.get(axis) or {}).get("state")) == "conflict" for axis in axes):
        return "conflict"
    strength = row.get("strength")
    if strength is None:
        return "unavailable"
    try:
        value = float(strength)
    except (TypeError, ValueError):
        return "unavailable"
    if value >= lit_pct:
        return "lit"
    if value >= warm_pct:
        return "warm"
    return "dim"


def _persistence(history, meta):
    """由逐期点亮快照投影持续性（连续 lit / 24d lit 占比 / 翻转次数）。

    仅做状态序列计数，不重算任何统计量；缺失期跳过，不补造。
    """
    thresholds = (meta or {}).get("thresholds") or {}
    try:
        lit_pct = float(thresholds.get("lit_pct", 0.70))
        warm_pct = float(thresholds.get("warm_pct", 0.40))
    except (TypeError, ValueError):
        lit_pct, warm_pct = 0.70, 0.40

    series = {}
    for period in history or []:
        for row in period.get("rows") or []:
            symbol = str(row.get("symbol") or "")
            if not symbol:
                continue
            series.setdefault(symbol, []).append(_row_state(row, lit_pct, warm_pct))
    rows = []
    for symbol, states in series.items():
        valid = [state for state in states if state != "unavailable"]
        if not valid:
            rows.append(
                {
                    "symbol": symbol,
                    "available": False,
                    "consecutive_lit": None,
                    "lit_ratio": None,
                    "flips": None,
                }
            )
            continue
        consecutive = 0
        for state in reversed(states):
            if state == "lit":
                consecutive += 1
            elif state == "unavailable":
                continue
            else:
                break
        lit_ratio = sum(1 for state in valid if state == "lit") / float(len(valid))
        flips = sum(
            1
            for prev, cur in zip(valid, valid[1:], strict=False)
            if (prev == "lit") != (cur == "lit")
        )
        rows.append(
            {
                "symbol": symbol,
                "available": True,
                "consecutive_lit": consecutive,
                "lit_ratio": round(lit_ratio, 4),
                "flips": flips,
                "periods": len(valid),
                "state": valid[-1],
            }
        )
    rows.sort(key=lambda item: (-(item.get("consecutive_lit") or -1), item["symbol"]))
    return {"available": bool(rows), "periods": len(history or []), "rows": rows}


def _extra_panels(raw, aligned, base, blocks, envelopes, days, as_of=None, history_periods=0):
    """一次进程产出 B 链路四面板：D-E19 点亮 → D-E16 聚合 → D-E17 看板 → D-E18 导图。

    `as_of` 必须贯穿：点亮行与聚合曲线都按面板数据截止日截断，避免行日期/曲线尾部
    越过顶部标注的「数据截至」。
    """
    from l1agg.asset_pool import load as load_asset_pool
    from l1agg.capabilities.aggregate import aggregate_curve, class_board
    from l1agg.capabilities.flow import flow_graph
    from l1agg.capabilities.lights import lights
    from l1agg.capabilities.visual import (
        build_visual,
        core_asset_series,
        signal_matrix,
    )
    from l1agg.leader_registry import resolve

    try:
        pool = load_asset_pool()
    except Exception:  # 配置缺失不阻塞其余面板（FAIL-OPEN）
        pool = None

    visuals = []

    # 1) D-E19 点亮（先算：D-E17 只消费 lit_n/warm_n 计数）
    entries = _lights_entries(raw, pool, as_of=as_of, base=base)
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

    # 1.0) 多期点亮影带（T9-2）：仅在显式请求 `--history N` 时回放，默认 0 保持旧 payload
    if history_periods > 0:
        try:
            history = _lights_history(raw, pool, base=base, upto=as_of, periods=history_periods)
            lights_payload["history"] = history
            lights_payload["persistence"] = _persistence(history, lights_block.get("meta") or {})
        except Exception as exc:  # FAIL-OPEN：影带回放失败不影响当期点亮
            lights_payload["history"] = []
            lights_payload["persistence"] = {"available": False, "rows": []}
            lights_payload["history_error"] = f"{type(exc).__name__}: {exc}"

    # 1.1) 主览图右：加权信号点阵（资产 × 四轴，状态/强度/轴值符号零重算）
    labels = {}
    for row in light_rows:
        symbol = str(row.get("symbol"))
        binding = resolve(symbol)
        labels[symbol] = binding.label if binding else symbol
    matrix_visual = signal_matrix(lights_block, lights_env.get("quality"), labels=labels)
    if matrix_visual is not None:
        visuals.append({"id": "matrix:signals", **matrix_visual})

    # 2) D-E16 聚合曲线（逐标的历史先按 as_of 截断，再 rebase 加权，曲线不越过数据截止）
    agg_series = {
        symbol: {day: value for day, value in history.items() if not as_of or day <= as_of}
        for symbol, history in raw.items()
    }
    agg_env = aggregate_curve(agg_series) or {}
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
        # 2.1) 主览图左：核心资产归一化多线（只裁剪 members，不重算）
        core_visual = core_asset_series(
            ((agg_env.get("data") or {}).get("capabilities") or {}).get("D-E16") or {},
            agg_env.get("quality"),
            assets=_core_assets(),
        )
        if core_visual is not None:
            visuals.append({"id": "series:core-assets", **core_visual})

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


def _build_visuals(blocks, envelopes, base, as_of, series_inputs=None):
    """产出图规格列表；任何门禁不通过的能力不产图（FAIL-OPEN）。"""
    from l1agg.capabilities.overview import build_graph, build_tree
    from l1agg.capabilities.visual import build_visual

    visuals = []

    tree = build_tree(blocks=blocks, as_of=as_of, series_inputs=series_inputs)
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
    symbols, base, days, history_periods = _parse_args(sys.argv[1:])
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

    # 单资产能力（D-E10/D-E15/D-G22）只依赖 base 自身历史，必须用 raw 自有日期轴；
    # 公共交集只服务多资产矩阵（D-E05）与对齐切片（D-E12），否则 D-G22 会被截断到 <250。
    base_history = raw.get(base) or {}
    if base_history:
        base_dates = sorted(base_history)
        prices = [base_history[day] for day in base_dates]
    else:
        base_dates = list(dates)
        prices = list(series[base])

    drawdown = _run("D-E10", prices=prices, dates=base_dates, symbol=base)
    envelopes["D-E10"] = drawdown
    _collect(blocks, drawdown)

    trend = _run("D-E15", prices=prices, dates=base_dates, symbol=base)
    envelopes["D-E15"] = trend
    _collect(blocks, trend)

    returns = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices)) if prices[i - 1]]
    significance = _run("D-G22", series=returns, name=base)
    envelopes["D-G22"] = significance
    _collect(blocks, significance)

    crowding = _run_crowding(base)
    if crowding:
        envelopes["D-A14"] = crowding
        _collect(blocks, crowding)

    # 技术叠加的分位条（T9-3）：D-A04 末值历史分位；不进 blocks，避免污染树/网络构建
    percentile_env = _run("D-A04", values=prices, dates=base_dates, symbol=base)
    percentile_block = ((percentile_env.get("data") or {}).get("capabilities") or {}).get(
        "D-A04"
    ) or {}

    # 技术叠加右侧读数（设计稿 v3）：波动 / 回撤 / 拥挤；只读能力块，不进 blocks
    volatility_env = _run("D-A06", values=prices, dates=base_dates, symbol=base)
    volatility_block = ((volatility_env.get("data") or {}).get("capabilities") or {}).get(
        "D-A06"
    ) or {}
    trend_block = ((trend.get("data") or {}).get("capabilities") or {}).get("D-E15") or {}
    drawdown_block = ((drawdown.get("data") or {}).get("capabilities") or {}).get("D-E10") or {}
    crowding_block = ((crowding or {}).get("data") or {}).get("capabilities", {}).get("D-A14") or {}
    kalman = dict(trend_block.get("kalman") or {})
    panel_metrics = {
        "trend": {
            "ema": trend_block.get("ema"),
            "ema_order": trend_block.get("ema_order"),
            "slope_table": trend_block.get("slope_table") or [],
            "kalman": {
                "level": kalman.get("level"),
                "band": kalman.get("band"),
                "slope": kalman.get("slope"),
                "slope_se": kalman.get("slope_se"),
            },
        },
        "volatility": {
            "annualized": volatility_block.get("volatility"),
            "window": volatility_block.get("window"),
            "sample_n": volatility_block.get("sample_n"),
            "capability": "D-A06",
        },
        "drawdown": {
            "mdd": drawdown_block.get("mdd"),
            "current": drawdown_block.get("current_drawdown"),
            "peak_date": drawdown_block.get("peak_date"),
            "trough_price": drawdown_block.get("trough_price"),
            "peak_price": drawdown_block.get("peak_price"),
            "peak_to_trough_days": drawdown_block.get("peak_to_trough_days"),
            "duration_days": drawdown_block.get("duration_days"),
            "recovery_days": drawdown_block.get("recovery_days"),
            "recovered": drawdown_block.get("recovered"),
            "capability": "D-E10",
        },
        "crowding": {
            "score": crowding_block.get("score"),
            "percentile": crowding_block.get("percentile"),
            "level": crowding_block.get("level"),
            "n": crowding_block.get("n"),
            "as_of": crowding_block.get("as_of"),
            "capability": "D-A14",
        },
    }

    series_inputs = _load_l0_flow_series(base, days)
    visuals = _build_visuals(blocks, envelopes, base, as_of, series_inputs)
    # B 链路四面板：同一进程内直调能力层（避免每图一次 python spawn）
    extra_visuals, lights_payload = _extra_panels(
        raw, series, base, blocks, envelopes, days, history_periods=history_periods
    )
    visuals.extend(extra_visuals)
    # 主览图前置（前端按 id 取用，顺序只影响"全景观图"标签栏的阅读顺序）
    main_ids = ("matrix:signals", "series:core-assets")
    visuals = [item for item in visuals if item.get("id") in main_ids] + [
        item for item in visuals if item.get("id") not in main_ids
    ]
    payload = {
        "ok": True,
        "as_of": as_of,
        "base": base,
        "assets": list(series),
        "unavailable": unavailable,
        "visuals": visuals,
        "lights": lights_payload,
        "base_metrics": {
            "percentile": {
                "value": percentile_block.get("percentile"),
                "lookback": percentile_block.get("lookback"),
                "sample_n": percentile_block.get("sample_n"),
                "capability": "D-A04",
            },
            "as_of": as_of,
        },
        "panel_metrics": panel_metrics,
        "recommended": _recommend(visuals, blocks, list(series), base, unavailable),
        "degraded": bool(unavailable)
        or any((envelope or {}).get("ok") is False for envelope in envelopes.values()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # ADR-V12 / L1S-04：T1–T3 制品按 capability + as_of 幂等落盘（制品内不含时钟字段）
        from l1agg.persistence.artifacts import persist_visuals

        payload["artifacts"] = persist_visuals(visuals, as_of, extra={"base": base})
    except Exception as exc:  # FAIL-OPEN：制品失败不影响图输出
        payload["artifacts"] = {"enabled": False, "error": f"{type(exc).__name__}: {exc}"}
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
