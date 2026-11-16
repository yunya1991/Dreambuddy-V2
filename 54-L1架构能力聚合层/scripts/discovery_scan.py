# -*- coding: utf-8 -*-
"""Discovery 报告生产者（SPEC-54c / D-K02 上游产物）。

按 `config/discovery_space.yaml` 的**预注册冻结项**执行一次确定性扫描，产出：

    reports/discovery/<YYYYMMDD-HHMM>/manifest.json
    reports/discovery/<YYYYMMDD-HHMM>/findings.jsonl
    reports/discovery/<YYYYMMDD-HHMM>/patterns.json   （默认调用 build_patterns）

纪律：
  - 只读 DB、只写报告目录；不写库、不修改搜索空间；
  - 枚举顺序固定：单序列 → 双序列，序列 / 变换 / 期限；
  - 变换固定 6 种、期限固定 {1,5,20}、分段固定 70/30（holdout 只验证不选参）；
  - BH-FDR α=0.05 强制开启；|corr|>0.95 去重；发现上限 manifest 记录；
  - 统计量走方法层 B14（RankIC）/B13（IC），不在本脚本重写口径；
  - 结果一律 `status=candidate`，不表述因果或预测。

用法：
    python3 scripts/discovery_scan.py
    python3 scripts/discovery_scan.py --days 1200 --dry-run
    python3 scripts/discovery_scan.py --max-units 2000 --skip-patterns
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sqlite3
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_REPO_ROOT = os.path.normpath(os.path.join(_MODULE_ROOT, ".."))
for _p in (_MODULE_ROOT, os.path.join(_REPO_ROOT, "19-数据访问层")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from l1agg import discovery  # noqa: E402
from l1agg.align import forward_returns, load_leader  # noqa: E402
from l1agg.capabilities.eval_exports import REPORTS_DIR  # noqa: E402
from l1agg.methods import run as run_method  # noqa: E402
from l1agg.persistence._stats import spearman  # noqa: E402

DB_PATH = os.path.join(_REPO_ROOT, "19-数据访问层", "data", "dreambuddy_core.db")
DEFAULT_DAYS = 1200
MIN_UNIT_N = 250
MIN_HOLDOUT_N = 30
TRANSFORMS = ("raw", "diff", "pct", "zscore60", "ts_rank60", "quintile5")
# 序列池名 → mm_metrics (sub_category, metric_name)；资产池价格另走 load_leader
MACRO_METRICS: Dict[str, Tuple[str, str]] = {
    "NASDAQCOM": ("NASDAQCOM", "value"),
    "SP500": ("SP500", "value"),
    "DGS10": ("DGS10", "value"),
    "T10Y2Y": ("T10Y2Y", "value"),
    "VIXCLS": ("VIXCLS", "value"),
    "DTWEXBGS": ("DTWEXBGS", "value"),
    "DCOILWTICO": ("DCOILWTICO", "value"),
    "crypto_fear_greed": ("crypto_fear_greed", "value"),
    "btc_funding_rate": ("funding_rate", "funding_rate_pct"),
    "btc_open_interest": ("open_interest", "open_interest_value_binance"),
    "stablecoin_supply_usd": ("stablecoin_supply", "total_circulating_usd_bln"),
    "etf_net_flow_usd": ("etf_flow", "total_flow"),
}
FALLBACK_MACRO: Dict[str, Tuple[str, str]] = {
    "stablecoin_supply_usd": ("stablecoins_top_10", "total_circulating_usd_bln"),
}


def _load_metric(sub_category: str, metric: str) -> Dict[str, float]:
    sql = (
        "SELECT date(timestamp,'unixepoch') AS d, metric_value FROM mm_metrics "
        "WHERE sub_category=? AND metric_name=? AND metric_value IS NOT NULL ORDER BY timestamp"
    )
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
        rows = conn.execute(sql, (sub_category, metric)).fetchall()
    out: Dict[str, float] = {}
    for day, value in rows:
        if day and value is not None:
            out[str(day)] = float(value)
    return out


def _load_series(name: str, days: int) -> Dict[str, float]:
    """先读宏观/域内指标，再回退资产池价格；统一截取最后 `days` 个交易日。"""
    for mapping in (MACRO_METRICS, FALLBACK_MACRO):
        spec = mapping.get(name)
        if spec is None:
            continue
        values = _load_metric(*spec)
        if values:
            keys = sorted(values)[-days:]
            return {key: values[key] for key in keys}
    try:
        values = load_leader(DB_PATH, name, days=days)
    except Exception:  # noqa: BLE001 — 单序列失败不阻断整体扫描
        return {}
    return dict(values)


def _transform(values: Sequence[float], kind: str) -> List[Optional[float]]:
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if kind == "raw":
        return [float(v) for v in values]
    if kind == "diff":
        for i in range(1, n):
            out[i] = values[i] - values[i - 1]
        return out
    if kind == "pct":
        for i in range(1, n):
            if values[i - 1]:
                out[i] = values[i] / values[i - 1] - 1.0
        return out
    if kind in ("zscore60", "ts_rank60"):
        window = 60
        for i in range(window - 1, n):
            sample = values[i + 1 - window : i + 1]
            if kind == "zscore60":
                mean = sum(sample) / window
                var = sum((v - mean) ** 2 for v in sample) / window
                if var > 0:
                    out[i] = (values[i] - mean) / math.sqrt(var)
            else:
                out[i] = sum(1 for v in sample if v <= values[i]) / window
        return out
    if kind == "quintile5":
        for i in range(59, n):
            sample = values[i - 59 : i + 1]
            rank = sum(1 for v in sample if v <= values[i])
            bucket = min(4, int(rank / len(sample) * 5))
            out[i] = float(bucket)
        return out
    raise ValueError(f"unknown transform: {kind}")


def _pairs(
    factor: Dict[str, float],
    target: Dict[str, float],
    transform: str,
    horizon: int,
) -> Tuple[List[float], List[float]]:
    common = sorted(set(factor) & set(target))
    if len(common) < MIN_UNIT_N:
        return [], []
    prices = [target[day] for day in common]
    forward = forward_returns(prices, horizon)
    raw = _transform([factor[day] for day in common], transform)
    xs: List[float] = []
    ys: List[float] = []
    for value, fwd in zip(raw, forward, strict=False):
        if value is None or fwd is None:
            continue
        if not (math.isfinite(value) and math.isfinite(fwd)):
            continue
        xs.append(float(value))
        ys.append(float(fwd))
    return xs, ys


def _ic(xs: Sequence[float], ys: Sequence[float]) -> Optional[Dict[str, Any]]:
    if len(xs) < MIN_UNIT_N:
        return None
    env = run_method("B14", {"factor": list(xs), "target": list(ys)})
    return env.get("result")


def _holdout_ic(xs: Sequence[float], ys: Sequence[float], ratio: float) -> Optional[float]:
    cut = int(len(xs) * ratio)
    xs2, ys2 = xs[cut:], ys[cut:]
    if len(xs2) < MIN_HOLDOUT_N:
        return None
    value = spearman(xs2, ys2)
    return float(value) if math.isfinite(value) else None


def _bh_fdr(p_values: Sequence[float], alpha: float) -> List[Optional[float]]:
    """BH-FDR：返回每项校正后 p 值（未通过时为 None）。"""
    m = len(p_values)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted: List[Optional[float]] = [None] * m
    running = 1.0
    for rank in range(m, 0, -1):
        index = order[rank - 1]
        running = min(running, p_values[index] * m / rank)
        adjusted[index] = min(1.0, running)
    return [value if value is not None and value <= alpha else None for value in adjusted]


def _corr(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    return float(spearman(list(a[:n]), list(b[:n])))


def _units(space: Dict[str, Any], budget: int) -> Iterable[Dict[str, Any]]:
    """固定枚举顺序：单序列 → 双序列；序列 / 变换 / 期限。"""
    series = list(space["series"])
    count = 0
    for name in series:
        for transform in TRANSFORMS:
            for horizon in space["horizons"]:
                if count >= budget:
                    return
                count += 1
                yield {
                    "mode": "single",
                    "series": name,
                    "target": name,
                    "transform": transform,
                    "horizon": int(horizon),
                }
    if not space["pair"]:
        return
    for i, left in enumerate(series):
        for right in series[i + 1 :]:
            for direction in ((left, right), (right, left)):
                for transform in TRANSFORMS:
                    for horizon in space["horizons"]:
                        if count >= budget:
                            return
                        count += 1
                        yield {
                            "mode": "pair",
                            "series": direction[0],
                            "target": direction[1],
                            "transform": transform,
                            "horizon": int(horizon),
                        }


def scan(
    space: Dict[str, Any], days: int, budget: int
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cache: Dict[str, Dict[str, float]] = {}
    raw_units = list(_units(space, budget))
    truncated = budget < space["estimates"]["total_units"]
    rows: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = {"short": 0, "no_ic": 0}
    for unit in raw_units:
        for name in (unit["series"], unit["target"]):
            if name not in cache:
                cache[name] = _load_series(name, days)
        if not cache[unit["series"]] or not cache[unit["target"]]:
            skipped["short"] += 1
            continue
        xs, ys = _pairs(
            cache[unit["series"]], cache[unit["target"]], unit["transform"], unit["horizon"]
        )
        result = _ic(xs, ys)
        if result is None:
            skipped["short"] += 1
            continue
        holdout = _holdout_ic(xs, ys, float(space["split"]["screen_ratio"]))
        agreement = None
        if holdout is not None and result["rank_ic"]:
            agreement = 1.0 if (holdout >= 0) == (result["rank_ic"] >= 0) else 0.0
        rows.append(
            {
                "method": "B14",
                "series": unit["series"],
                "target": unit["target"],
                "mode": unit["mode"],
                "transform": unit["transform"],
                "horizon": unit["horizon"],
                "n": int(result["n"]),
                "rank_ic": float(result["rank_ic"]),
                "p_value": float(result["p"]),
                "holdout_ic": holdout,
                "stability": agreement,
                "_xs": xs,
            }
        )
    if not rows:
        return [], {
            "units": len(raw_units),
            "evaluated": 0,
            "truncated": truncated,
            "skipped": skipped,
            "series": sorted(cache),
        }
    flags = _bh_fdr([row["p_value"] for row in rows], float(space["fdr"]["alpha"]))
    picked: List[Dict[str, Any]] = []
    accepted: List[List[float]] = []
    for row, p_adj in zip(rows, flags, strict=False):
        if p_adj is None:
            continue
        if row["holdout_ic"] is None or row["stability"] is None:
            continue
        if row["stability"] < float(space["split"]["min_holdout_agreement"]):
            continue
        row = dict(row)
        row["p_adj"] = round(float(p_adj), 6)
        if any(
            abs(_corr(row["_xs"], other)) > space["dedupe"]["corr_threshold"] for other in accepted
        ):
            continue
        accepted.append(row["_xs"])
        picked.append(row)
        if len(picked) >= int(space["budget"]["max_findings"]):
            break
    meta = {
        "units": len(raw_units),
        "evaluated": len(rows),
        "truncated": truncated,
        "skipped": skipped,
        "series_loaded": len(cache),
        "passed_fdr": int(sum(1 for value in flags if value is not None)),
    }
    return picked, meta


def _write_report(
    root: str, space: Dict[str, Any], findings: List[Dict[str, Any]], meta: Dict[str, Any]
) -> str:
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M")
    directory = os.path.join(root, stamp)
    os.makedirs(directory, exist_ok=True)
    data_version = _dt.datetime.now().strftime("db@%Y%m%d")
    manifest = {
        "report": stamp,
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "space_version": space["version"],
        "space_hash": space["space_hash"],
        "seed": space["seed"],
        "data_version": data_version,
        "series": space["series"],
        "transforms": list(TRANSFORMS),
        "methods": ["B14"],
        "evaluated_methods": ["B14"],
        "truncated": {
            "methods": [m for m in space["methods"] if m != "B14"],
        },
        "horizons": space["horizons"],
        "units": meta,
        "n_units": meta["evaluated"],
        "fdr": space["fdr"],
        "split": space["split"],
        "dedupe": space["dedupe"],
    }
    with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(directory, "findings.jsonl"), "w", encoding="utf-8") as fh:
        for item in findings:
            row = {k: v for k, v in item.items() if not k.startswith("_")}
            row.update(
                {
                    "status": "candidate",
                    "data_version": data_version,
                    "eval_at": manifest["created_at"],
                }
            )
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return directory


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Discovery 报告生产者（D-K02 上游）")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--max-units", type=int, default=0, help="覆盖预算上限（默认取预注册）")
    parser.add_argument("--output-root", default=REPORTS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-patterns", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    space = discovery.load_space()
    budget = int(args.max_units or space["budget"]["max_units"])
    findings, meta = scan(space, int(args.days), budget)
    directory = ""
    if not args.dry_run:
        directory = _write_report(args.output_root, space, findings, meta)
        if not args.skip_patterns:
            try:
                from build_patterns import main as build_main

                build_main(["--report-dir", directory])
            except Exception:  # noqa: BLE001 — patterns 失败不阻断报告
                pass
    output = {"ok": True, "report_dir": directory, "findings": len(findings), **meta}
    if args.json:
        sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
