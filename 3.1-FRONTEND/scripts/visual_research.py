#!/usr/bin/env python3
"""visual_research.py — 「数据研究」页只读聚合出口（设计稿 v3 五子页）。

供 `/api/visual/research` 调用。数据来源全部为**已落库产物**：
  - MERS 注册表 `data/mers/registry.db::relationship_eval`（评估结果）
  - `config/discovery_space.yaml`（预注册空间）/ `config/algorithm_registry.yaml`（关系类）
  - `reports/discovery/<期>/patterns.json`（若有）
  - L0 `dreambuddy_core.db::mm_metrics`（数据域覆盖，只做「是否存在」判定）

纪律：
  - 只读，不写库、不落盘、不重算任何统计量；聚合仅做计数 / 均值 / 极值投影；
  - 产物缺失 → 对应区块 `available=false` + `reason`，不补造；
  - 不输出买卖方向、不给因果句。

用法：
  python3 scripts/visual_research.py [--top 12]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
_L1_DIR = os.path.join(_REPO_ROOT, "54-L1架构能力聚合层")

DB_PATH = os.environ.get("DREAMBUDDY_CORE_DB") or os.path.join(
    _REPO_ROOT, "19-数据访问层", "data", "dreambuddy_core.db"
)
DISCOVERY_DIR = os.path.join(_L1_DIR, "reports", "discovery")
SPACE_FILE = os.path.join(_L1_DIR, "config", "discovery_space.yaml")
ALGORITHM_FILE = os.path.join(_L1_DIR, "config", "algorithm_registry.yaml")

REGISTRY_CANDIDATES = (
    os.environ.get("VISUAL_REGISTRY") or "",
    os.path.join(_L1_DIR, "data", "mers", "registry.db"),
    os.path.join(_REPO_ROOT, "data", "mers", "registry.db"),
)

DOMAINS: Tuple[Tuple[str, str], ...] = (
    ("price", "价格自身"),
    ("macro", "宏观利率"),
    ("sentiment", "情绪"),
    ("flow", "资金流"),
    ("leverage", "持仓/杠杆"),
)
DOMAIN_SERIES: Dict[str, Tuple[str, ...]] = {
    "macro": ("DGS10", "T10Y2Y", "NASDAQCOM", "DCOILWTICO", "VIXCLS", "DTWEXBGS"),
    "sentiment": ("crypto_fear_greed", "fear_greed_enhanced"),
    "flow": ("etf_flow", "stablecoins_top_10", "stablecoin_hist_usdt", "stablecoin_hist_usdc"),
    "leverage": ("funding_rate", "open_interest", "derivatives_spot"),
}
MIN_N = 250
RELATION_ORDER = ("R1", "R2", "R3", "R4", "R5", "R6")
# 覆盖矩阵优先展示核心资产，其余按评估行数降序（不改变口径，只改展示顺序）
CORE_TARGETS = ("BTC", "ETH", "SOL", "NVDA", "XAU")


def _registry_path() -> Optional[str]:
    for candidate in REGISTRY_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _read_yaml(path: str) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _short_target(target: str) -> str:
    text = str(target or "")
    return text.split("/", 1)[0] if "/" in text else text


def _relation_roles() -> Dict[str, List[str]]:
    """method → 全部关系角色（一个方法可服务多个关系类）。"""
    registry = _read_yaml(ALGORITHM_FILE)
    mapping: Dict[str, List[str]] = {}
    for method, roles in (registry.get("method_roles") or {}).items():
        if isinstance(roles, (list, tuple)) and roles:
            mapping[str(method)] = [str(role) for role in roles]
    return mapping


def _relation_map() -> Dict[str, str]:
    """method → 主关系类（首个角色），用于推荐表与证据链。"""
    return {method: roles[0] for method, roles in _relation_roles().items()}


def _relation_defs() -> List[Dict[str, Any]]:
    registry = _read_yaml(ALGORITHM_FILE)
    out = []
    for item in registry.get("relation_types") or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "question": str(item.get("question") or ""),
                "hypothesis": str(item.get("hypothesis") or ""),
                "enabled": bool(item.get("enabled", True)),
                "blocked_by": str(item.get("blocked_by") or ""),
                "judge": [str(x) for x in item.get("judge") or []],
            }
        )
    return out


def _space_block() -> Dict[str, Any]:
    space = _read_yaml(SPACE_FILE)
    budget = space.get("budget") or {}
    split = space.get("split") or {}
    fdr = space.get("fdr") or {}
    dedupe = space.get("dedupe") or {}
    series = (space.get("series") or {}).get("assets") or []
    macro = (space.get("series") or {}).get("macro") or []
    return {
        "available": bool(space),
        "version": space.get("version"),
        "updated": space.get("updated"),
        "seed": space.get("seed"),
        "series_count": len(series) + len(macro),
        "series": [str(x) for x in list(series) + list(macro)],
        "transform_count": len(space.get("transforms") or []),
        "transforms": [str(x) for x in space.get("transforms") or []],
        "method_count": len(space.get("methods") or []),
        "methods": [str(x) for x in space.get("methods") or []],
        "horizons": [int(x) for x in (space.get("targets") or {}).get("horizons") or []],
        "max_units": _int(budget.get("max_units")),
        "max_minutes": _int(budget.get("max_minutes")),
        "max_findings": _int(budget.get("max_findings")),
        "max_pairs": _int((space.get("combos") or {}).get("max_pairs")),
        "alpha": _num(fdr.get("alpha")),
        "corr_threshold": _num(dedupe.get("corr_threshold")),
        "screen_ratio": _num(split.get("screen_ratio")),
        "holdout_ratio": _num(split.get("holdout_ratio")),
        "min_holdout_agreement": _num(split.get("min_holdout_agreement")),
    }


def _domain_status(conn: Optional[sqlite3.Connection]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for key in DOMAIN_SERIES:
        out[key] = {"state": "unknown", "n": 0, "series": 0}
    if conn is None:
        return out
    try:
        for key, names in DOMAIN_SERIES.items():
            marks = ", ".join("?" for _ in names)
            row = conn.execute(
                f"SELECT COUNT(*) AS n, COUNT(DISTINCT sub_category) AS series "
                f"FROM mm_metrics WHERE sub_category IN ({marks})",
                names,
            ).fetchone()
            n = _int(row[0] if row else 0)
            series = _int(row[1] if row else 0)
            state = "ok" if n >= MIN_N else ("partial" if n > 0 else "missing")
            out[key] = {"state": state, "n": n, "series": series}
    except sqlite3.Error:
        pass
    return out


def _load_eval_rows(path: str) -> List[Dict[str, Any]]:
    columns = (
        "eval_id",
        "target",
        "method",
        "transform",
        "horizon",
        "n",
        "n_eff",
        "rank_ic",
        "hit_rate",
        "base_rate",
        "excess_hit",
        "hit_rate_lb",
        "p_adj",
        "stability",
        "holdout_hit_rate",
        "holdout_agree",
        "pass_streak",
        "fail_streak",
        "status",
        "gate_pass",
        "eval_at",
        "data_version",
    )
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []
    try:
        present = {row[1] for row in conn.execute("PRAGMA table_info(relationship_eval)")}
        picked = [column for column in columns if column in present]
        rows = [
            dict(row) for row in conn.execute(f"SELECT {', '.join(picked)} FROM relationship_eval")
        ]
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return rows


def _latest_report() -> Optional[Dict[str, Any]]:
    try:
        names = sorted(
            (name for name in os.listdir(DISCOVERY_DIR) if len(name) == 13 and name[8] == "-"),
            reverse=True,
        )
    except OSError:
        return None
    for name in names:
        patterns_path = os.path.join(DISCOVERY_DIR, name, "patterns.json")
        if not os.path.isfile(patterns_path):
            continue
        try:
            with open(patterns_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh) or {}
        except (OSError, ValueError):
            continue
        patterns = payload.get("patterns") if isinstance(payload, dict) else None
        return {"name": name, "patterns": patterns if isinstance(patterns, list) else []}
    return None


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    picked = [float(v) for v in values if v is not None]
    return round(sum(picked) / len(picked), 4) if picked else None


def _coverage(
    rows: List[Dict[str, Any]], domains: Dict[str, Dict[str, Any]], limit: int
) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        target = str(row.get("target") or "")
        if not target:
            continue
        bucket = grouped.setdefault(target, {"target": target, "n": 0, "gate_pass": 0, "rows": 0})
        bucket["rows"] += 1
        bucket["n"] = max(bucket["n"], _int(row.get("n")))
        bucket["gate_pass"] += 1 if _int(row.get("gate_pass")) == 1 else 0

    def _order(item: Dict[str, Any]) -> Tuple[int, int, str]:
        label = _short_target(item["target"])
        rank = CORE_TARGETS.index(label) if label in CORE_TARGETS else len(CORE_TARGETS)
        return (rank, -item["rows"], item["target"])

    ordered = sorted(grouped.values(), key=_order)[:limit]
    out_rows = []
    for item in ordered:
        n = item["n"]
        price_state = "ok" if n >= MIN_N else ("partial" if n > 0 else "missing")
        cell = {"price": {"state": price_state, "n": n, "scope": "asset"}}
        for key in ("macro", "sentiment", "flow", "leverage"):
            fact = domains.get(key) or {"state": "unknown", "n": 0}
            cell[key] = {"state": fact["state"], "n": fact["n"], "scope": "global"}
        out_rows.append(
            {
                "target": item["target"],
                "label": _short_target(item["target"]),
                "n": n,
                "rows": item["rows"],
                "gate_pass": item["gate_pass"],
                "domains": cell,
            }
        )
    return {
        "available": bool(out_rows),
        "domains": [{"key": key, "label": label} for key, label in DOMAINS],
        "rows": out_rows,
        "notes": [
            "覆盖只反映「能不能算」，不代表关系成立；价格域按标的样本量判定。",
            "宏观 / 情绪 / 资金流 / 持仓杠杆为跨资产序列，同一期对所有标的共用覆盖状态。",
        ],
    }


def _classes(
    rows: List[Dict[str, Any]], relation_defs: List[Dict[str, Any]], roles_of: Dict[str, List[str]]
) -> List[Dict[str, Any]]:
    methods_of: Dict[str, List[str]] = {}
    for method, roles in roles_of.items():
        for relation in roles:
            methods_of.setdefault(relation, []).append(method)
    out = []
    for item in relation_defs:
        relation = item["id"]
        members = set(methods_of.get(relation) or [])
        subset = [row for row in rows if str(row.get("method")) in members]
        packages = {
            (
                row.get("method"),
                row.get("transform"),
                row.get("target"),
                row.get("horizon"),
            )
            for row in subset
        }
        gate_pass = sum(1 for row in subset if _int(row.get("gate_pass")) == 1)
        states = {"stable": 0, "candidate": 0, "decayed": 0, "other": 0}
        for row in subset:
            status = str(row.get("status") or "")
            if status in states:
                states[status] += 1
            else:
                states["other"] += 1
        horizon_counts: Dict[int, int] = {}
        for row in subset:
            horizon_counts[_int(row.get("horizon"))] = (
                horizon_counts.get(_int(row.get("horizon")), 0) + 1
            )
        top_horizon = max(horizon_counts, key=horizon_counts.get) if horizon_counts else None
        out.append(
            {
                **item,
                "members": sorted(members),
                "packages": len(packages),
                "gate_pass": gate_pass,
                "mean_abs_rank_ic": (
                    _mean([abs(_num(row.get("rank_ic")) or 0.0) for row in subset])
                    if subset
                    else None
                ),
                "mean_hit": _mean([_num(row.get("hit_rate")) for row in subset]),
                "states": states,
                "top_horizon": top_horizon,
                "rows": len(subset),
            }
        )
    return out


def _patterns(
    rows: List[Dict[str, Any]], relation_of: Dict[str, str], report: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    if report and report.get("patterns"):
        items = []
        for entry in report["patterns"]:
            if not isinstance(entry, dict):
                continue
            support = _int(entry.get("support"))
            oppose = _int(entry.get("oppose"))
            total = support + oppose
            items.append(
                {
                    "id": str(
                        entry.get("pattern_id") or entry.get("id") or entry.get("relation") or ""
                    ),
                    "relation": str(entry.get("relation_type") or entry.get("relation") or ""),
                    "horizon": entry.get("horizon"),
                    "support": support,
                    "oppose": oppose,
                    "agreement": (
                        _num(entry.get("agreement"))
                        if entry.get("agreement") is not None
                        else (round(support / total, 4) if total else None)
                    ),
                    "p_adj": _num(entry.get("p_adj")),
                    "status": str(entry.get("status") or ""),
                }
            )
        return {
            "available": bool(items),
            "source": "report",
            "report": report["name"],
            "rows": items,
        }

    grouped: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for row in rows:
        relation = relation_of.get(str(row.get("method")))
        if not relation:
            continue
        horizon = _int(row.get("horizon"))
        bucket = grouped.setdefault((relation, horizon), {"support": 0, "oppose": 0, "p_adj": []})
        ic = _num(row.get("rank_ic"))
        if ic is None:
            continue
        if ic > 0:
            bucket["support"] += 1
        elif ic < 0:
            bucket["oppose"] += 1
        p_adj = _num(row.get("p_adj"))
        if p_adj is not None:
            bucket["p_adj"].append(p_adj)
    items = []
    for (relation, horizon), bucket in sorted(
        grouped.items(),
        key=lambda kv: (
            RELATION_ORDER.index(kv[0][0]) if kv[0][0] in RELATION_ORDER else 99,
            kv[0][1],
        ),
    ):
        total = bucket["support"] + bucket["oppose"]
        if total == 0:
            continue
        agreement = round(bucket["support"] / total, 4)
        p_adj = min(bucket["p_adj"]) if bucket["p_adj"] else None
        if agreement >= 0.7 and (p_adj is not None and p_adj < 0.05):
            status = "strong"
        elif agreement >= 0.6:
            status = "weak"
        else:
            status = "opposed" if agreement < 0.5 else "weak"
        items.append(
            {
                "id": f"PAT-{relation}-h{horizon}",
                "relation": relation,
                "horizon": horizon,
                "support": bucket["support"],
                "oppose": bucket["oppose"],
                "agreement": agreement,
                "p_adj": p_adj,
                "status": status,
            }
        )
    return {
        "available": bool(items),
        "source": "derived",
        "report": None,
        "rows": items[:24],
    }


def _funnel(
    rows: List[Dict[str, Any]], space: Dict[str, Any], latest: Dict[str, int]
) -> List[Dict[str, Any]]:
    base = _int(space.get("max_units")) or max(len(rows), 1)
    steps = [
        ("预注册单元", base),
        ("n ≥ 250", latest["evaluable"]),
        ("p_adj < 0.05", latest["significant"]),
        ("样本外同号", latest["holdout_agree"]),
        ("过四门禁", latest["gate_pass"]),
        ("stable（≥3 连击）", latest["stable"]),
    ]
    return [
        {
            "step": name,
            "count": int(count),
            "ratio": round(count / base, 6) if base else None,
        }
        for name, count in steps
    ]


def _gates(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    g1 = sum(
        1
        for row in rows
        if (_num(row.get("hit_rate")) or 0.0) >= 0.60
        and (_num(row.get("hit_rate_lb")) or 0.0) > 0.50
    )
    g2 = sum(1 for row in rows if _int(row.get("holdout_agree")) == 1)
    g3 = sum(
        1
        for row in rows
        if (_num(row.get("p_adj")) is not None and (_num(row.get("p_adj")) or 1.0) < 0.05)
    )
    g4 = sum(1 for row in rows if _int(row.get("pass_streak")) >= 3)
    total = len(rows)
    return [
        {
            "id": "G1",
            "name": "方向命中率",
            "rule": "hit ≥ 0.60 且 Wilson 95% 下界 > 0.50",
            "status": "已实现",
            "pass": g1,
            "total": total,
        },
        {
            "id": "G2",
            "name": "样本外同号",
            "rule": "70/30 · holdout hit ≥ 0.55 且与 screen 同号",
            "status": "已实现",
            "pass": g2,
            "total": total,
        },
        {
            "id": "G3",
            "name": "多重检验",
            "rule": "整期 BH-FDR · p_adj < 0.05",
            "status": "已实现",
            "pass": g3,
            "total": total,
        },
        {
            "id": "G4",
            "name": "稳定性连击",
            "rule": "pass_streak ≥ 3 → stable；fail ≥ 2 → decayed",
            "status": "已实现",
            "pass": g4,
            "total": total,
        },
    ]


def _recommendations(
    rows: List[Dict[str, Any]], relation_of: Dict[str, str], top: int, *, gate_only: bool = True
) -> List[Dict[str, Any]]:
    picked = [
        row
        for row in rows
        if _num(row.get("rank_ic")) is not None
        and (not gate_only or _int(row.get("gate_pass")) == 1)
    ]
    picked.sort(key=lambda row: (-abs(_num(row.get("rank_ic")) or 0.0), -_int(row.get("n"))))
    out = []
    for row in picked[:top]:
        out.append(
            {
                "eval_id": row.get("eval_id"),
                "relation": relation_of.get(str(row.get("method"))) or "unmapped",
                "target": _short_target(str(row.get("target") or "")),
                "method": row.get("method"),
                "transform": row.get("transform"),
                "horizon": _int(row.get("horizon")),
                "rank_ic": _num(row.get("rank_ic")),
                "hit_rate": _num(row.get("hit_rate")),
                "hit_rate_lb": _num(row.get("hit_rate_lb")),
                "holdout_hit_rate": _num(row.get("holdout_hit_rate")),
                "n": _int(row.get("n")),
                "n_eff": _int(row.get("n_eff")),
                "p_adj": _num(row.get("p_adj")),
                "status": row.get("status"),
                "gate_pass": _int(row.get("gate_pass")),
                "stability": _num(row.get("stability")),
                "eval_at": row.get("eval_at"),
                "data_version": row.get("data_version"),
            }
        )
    return out


def _distribution(recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
    horizons = sorted({_int(item.get("horizon")) for item in recommendations} - {0})
    values = []
    for relation in RELATION_ORDER:
        row = []
        for horizon in horizons:
            row.append(
                sum(
                    1
                    for item in recommendations
                    if item.get("relation") == relation and _int(item.get("horizon")) == horizon
                )
            )
        values.append(row)
    return {"relations": list(RELATION_ORDER), "horizons": horizons, "values": values}


def _evidence(recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not recommendations:
        return {"available": False, "nodes": [], "edges": []}
    head = recommendations[0]
    target = str(head.get("target") or "")
    method = str(head.get("method") or "")
    transform = str(head.get("transform") or "")
    nodes = [
        {"id": f"target:{target}", "label": target, "group": "target"},
        {"id": f"method:{method}", "label": method, "group": "method"},
    ]
    edges = [
        {
            "src": f"method:{method}",
            "dst": f"target:{target}",
            "weight": abs(_num(head.get("rank_ic")) or 0.0),
        }
    ]
    if transform:
        nodes.append({"id": f"transform:{transform}", "label": transform, "group": "transform"})
        edges.append({"src": f"transform:{transform}", "dst": f"method:{method}", "weight": None})
    return {"available": True, "nodes": nodes, "edges": edges, "headline": head.get("eval_id")}


def build(top: int = 12) -> Dict[str, Any]:
    path = _registry_path()
    space = _space_block()
    relation_of = _relation_map()
    roles_of = _relation_roles()
    relation_defs = _relation_defs()
    report = _latest_report()

    l0 = None
    if os.path.isfile(DB_PATH):
        try:
            l0 = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            l0 = None
    domains = _domain_status(l0)
    if l0 is not None:
        l0.close()

    if not path:
        return {
            "ok": True,
            "as_of": None,
            "degraded": True,
            "reason": "关系评估注册表尚未生成",
            "source": {"registry": None, "registry_exists": False, "registry_rows": 0},
            "space": space,
            "coverage": {
                "available": False,
                "domains": [{"key": k, "label": v} for k, v in DOMAINS],
                "rows": [],
                "notes": [],
            },
            "latest": {"available": False, "reason": "关系评估注册表尚未生成"},
            "classes": [],
            "patterns": {"available": False, "source": "none", "rows": []},
            "gates": [],
            "funnel": [],
            "holdout": {"available": False, "reason": "注册表缺失", "points": []},
            "recommendations": [],
            "candidates": [],
            "distribution": {"relations": [], "horizons": [], "values": []},
            "evidence": {"available": False, "nodes": [], "edges": []},
        }

    rows = _load_eval_rows(path)
    evaluable = [row for row in rows if _int(row.get("n")) >= MIN_N]
    significant = [
        row
        for row in evaluable
        if (_num(row.get("p_adj")) is not None and (_num(row.get("p_adj")) or 1.0) < 0.05)
    ]
    holdout_agree = [row for row in significant if _int(row.get("holdout_agree")) == 1]
    gate_pass = [row for row in evaluable if _int(row.get("gate_pass")) == 1]
    stable = [row for row in rows if str(row.get("status")) == "stable"]
    latest_counts = {
        "registry_rows": len(rows),
        "evaluable": len(evaluable),
        "significant": len(significant),
        "holdout_agree": len(holdout_agree),
        "gate_pass": len(gate_pass),
        "stable": len(stable),
    }
    eval_at = max((str(row.get("eval_at") or "") for row in rows), default="")
    run_id = next((str(row.get("run_id") or "") for row in rows if row.get("run_id")), "")
    data_version = next(
        (str(row.get("data_version") or "") for row in rows if row.get("data_version")), ""
    )

    recommendations = _recommendations(rows, relation_of, top)
    candidates = (
        _recommendations(rows, relation_of, top, gate_only=False) if not recommendations else []
    )
    classes = _classes(rows, relation_defs, roles_of)
    patterns = _patterns(rows, relation_of, report)
    funnel = _funnel(rows, space, latest_counts)
    gates = _gates(evaluable)

    return {
        "ok": True,
        "as_of": eval_at[:10] or None,
        "degraded": len(rows) == 0,
        "reason": "" if rows else "注册表为空",
        "source": {
            "registry": path,
            "registry_exists": True,
            "registry_rows": len(rows),
            "data_version": data_version,
            "run_id": run_id,
            "eval_at": eval_at,
            "reports_dir": DISCOVERY_DIR if report else None,
            "report": (report or {}).get("name"),
        },
        "space": space,
        "coverage": _coverage(rows, domains, limit=8),
        "latest": {
            "available": bool(rows),
            "report": (report or {}).get("name"),
            "eval_at": eval_at,
            "data_version": data_version,
            **latest_counts,
        },
        "classes": classes,
        "patterns": patterns,
        "gates": gates,
        "funnel": funnel,
        "holdout": {
            "available": False,
            "reason": "注册表按当期覆盖写入，不保留逐季 holdout 序列；季度曲线需等 MERS 归档历史期",
            "points": [],
        },
        "recommendations": recommendations,
        "candidates": candidates,
        "distribution": _distribution(recommendations or candidates),
        "evidence": _evidence(recommendations or candidates),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--top", type=int, default=12)
    args, _ = parser.parse_known_args(argv or sys.argv[1:])
    try:
        payload = build(top=max(1, min(int(args.top), 50)))
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        payload = {
            "ok": False,
            "degraded": True,
            "reason": f"{type(exc).__name__}: {exc}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
