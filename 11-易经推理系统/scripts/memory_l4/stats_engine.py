"""统计引擎模块 — 象限驱动的全局统计。

从全部 TradeCase / ReviewRecord / DistillRecord 中聚合：
- 象限分布、A0-A9 阶段覆盖率、胜率、平均收益
- L4 状态机分布、错误码分布

v0.2 新增模块 — Phase P0
"""

import json
import math
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import (
    memory_l4_cases_dir,
    memory_l4_distills_dir,
    memory_l4_reviews_dir,
    memory_l4_stats_dir,
)

# ---------------------------------------------------------------------------
# v0.2: category & severity extraction
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS = {
    "trend": ["trend", "momentum", "breakout", "follow"],
    "reversal": ["reversal", "mean_revert", "counter", "pullback"],
    "arbitrage": ["arbitrage", "arb", "spread", "converge"],
}


def _tag_matches_category(tag: str, keyword: str) -> bool:
    """匹配 tag 是否属于该 keyword 类别。

    两种策略:
    1) 复合词精确匹配: 'mean_revert' in tag
    2) 词边界匹配: 将 tag 拆分后匹配 'counter', 'pullback' 等单段词
    """
    # 复合词直接包含
    if keyword in tag:
        return True
    # 单段词边界匹配: 'counter' 匹配 'counter_trend' 中的 'counter'
    parts = tag.replace("_", " ").replace("-", " ").split()
    return keyword in parts


def extract_category_from_case(case: Dict[str, Any]) -> Optional[str]:
    """从 case 的 tags / strategy_references 推断交易类型。

    优先级: tags 精确匹配 > strategy_references > None
    """
    tags = [str(t).lower() for t in (case.get("tags") or [])]

    # reversal 优先，避免 'counter_trend' 被 'trend' 误匹配
    for cat in ["reversal", "arbitrage", "trend"]:
        keywords = _CATEGORY_KEYWORDS[cat]
        if any(_tag_matches_category(tag, kw) for tag in tags for kw in keywords):
            return cat

    refs = case.get("strategy_references") or {}
    sr = str(refs.get("strategy_id") or "").lower()
    if sr:
        for cat in ["reversal", "arbitrage", "trend"]:
            keywords = _CATEGORY_KEYWORDS[cat]
            if any(_tag_matches_category(sr, kw) for kw in keywords):
                return cat
    return None


def extract_severity_from_case(case: Dict[str, Any]) -> Optional[float]:
    """从 pnl 幅度和回撤计算影响程度 (0-1)。

    severity = min(1, |pnl|/10 * 0.7 + max_drawdown/20 * 0.3)
    """
    do = case.get("decision_outcome") or {}
    pnl = do.get("pnl_pct")
    dd = do.get("max_drawdown_pct")
    if pnl is None and dd is None:
        return None
    pnl_score = min(1.0, abs(float(pnl)) / 10.0) if pnl is not None else 0.0
    dd_score = min(1.0, abs(float(dd)) / 20.0) if dd is not None else 0.0
    return round(pnl_score * 0.7 + dd_score * 0.3, 3)


# ---------------------------------------------------------------------------
# v0.2: event_library — 四象限静态事件库
# ---------------------------------------------------------------------------

_X_BINS = [(-1.0, -0.33, "low"), (-0.33, 0.33, "mid"), (0.33, 1.0, "high")]
_Y_BINS = [(0.0, 0.5, "low"), (0.5, 1.0, "high")]


def _bin_x(x: float) -> str:
    for lo, hi, label in _X_BINS:
        if lo <= x <= hi:
            return label
    return "mid"


def _bin_y(y: float) -> str:
    for lo, hi, label in _Y_BINS:
        if lo <= y <= hi:
            return label
    return "low"


def compute_event_library(cases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """构建四象限事件库，按 (regime, category, x_range, y_range) 四维索引。

    产出:
      total_events: 总事件数
      by_regime: {regime: count}
      by_category: {category: count}
      quadrant_density: {x_range_y_range: count}
    """
    if cases is None:
        cases = _load_all_cases()

    total = 0
    by_regime: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    quadrant_density: Dict[str, int] = {}

    for c in cases:
        q = c.get("quadrant") or {}
        x = q.get("x")
        y = q.get("y")
        if x is None or y is None:
            continue

        regime = (c.get("environment_snapshot") or {}).get("regime") or "unknown"
        category = extract_category_from_case(c) or "uncategorized"
        x_bin = _bin_x(float(x))
        y_bin = _bin_y(float(y))

        total += 1
        by_regime[regime] = by_regime.get(regime, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1

        qd_key = f"{x_bin}_{y_bin}"
        quadrant_density[qd_key] = quadrant_density.get(qd_key, 0) + 1

    return {
        "total_events": total,
        "by_regime": by_regime,
        "by_category": by_category,
        "quadrant_density": quadrant_density,
    }


# ---------------------------------------------------------------------------
# v0.2: evolution_metrics — 演化指标
# ---------------------------------------------------------------------------

def _load_all_distills() -> List[Dict[str, Any]]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in _list_json(memory_l4_distills_dir())
    ]


def _distill_ts(distill: Dict[str, Any]) -> Optional[str]:
    """获取蒸馏记录的时间戳 (从 created_at / process_trace / fallback)。"""
    if distill.get("created_at"):
        return distill["created_at"]
    pt = distill.get("process_trace") or {}
    if pt.get("created_at"):
        return pt["created_at"]
    return None


def _distill_y(distill: Dict[str, Any]) -> Optional[float]:
    """获取蒸馏的 y 轴值。"""
    q = distill.get("quadrant") or {}
    y = q.get("y")
    if y is not None:
        return float(y)
    return None


def compute_evolution_metrics(distills: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """计算演化指标：y 轴增长率、模式稳定性、新兴模式。"""
    if distills is None:
        distills = _load_all_distills()

    # 按时间排序有 y 值的蒸馏
    timed: List[Tuple[str, float]] = []
    for d in distills:
        ts = _distill_ts(d)
        y = _distill_y(d)
        if ts is not None and y is not None:
            timed.append((ts, y))

    if len(timed) < 2:
        return {
            "y_growth_rate": None,
            "pattern_stability": None,
            "emerging_patterns": [],
        }

    # y_growth_rate: 按时间序列的平均环比增长率
    timed.sort(key=lambda t: t[0])
    growth_rates = []
    for i in range(1, len(timed)):
        prev_y = timed[i - 1][1]
        curr_y = timed[i][1]
        if prev_y > 0:
            growth_rates.append((curr_y - prev_y) / prev_y)
        else:
            growth_rates.append(0.0)
    avg_growth = round(sum(growth_rates) / len(growth_rates), 4) if growth_rates else 0.0

    # pattern_stability: y 值序列的变异系数倒数 (1 - cv, clipped to [0,1])
    mean_y = sum(t[1] for t in timed) / len(timed)
    if mean_y > 0:
        variance = sum((t[1] - mean_y) ** 2 for t in timed) / len(timed)
        std_y = math.sqrt(variance)
        cv = std_y / mean_y
        stability = round(max(0.0, min(1.0, 1.0 - cv)), 4)
    else:
        stability = 0.0

    # emerging_patterns: 识别聚类
    emerging = identify_emerging_patterns(distills)

    return {
        "y_growth_rate": avg_growth,
        "pattern_stability": stability,
        "emerging_patterns": emerging,
    }


def identify_emerging_patterns(
    distills: List[Dict[str, Any]],
    min_cases: int = 2,
    radius: float = 0.3,
) -> List[Dict[str, Any]]:
    """从蒸馏记录中识别新兴模式 (简单密度聚类)。

    思路: 在 (x, y) 空间中，将距离 < radius 的蒸馏聚为一组，
    组内 case_count >= min_cases 的视为新兴模式。
    """
    points: List[Tuple[float, float, Dict[str, Any]]] = []
    for d in distills:
        q = d.get("quadrant") or {}
        x = q.get("x")
        y = q.get("y")
        if x is not None and y is not None:
            points.append((float(x), float(y), d))

    if len(points) < 2:
        return []

    # 简单贪心聚类: 对每个未分组的点，找 radius 内的邻居
    visited = [False] * len(points)
    clusters: List[List[int]] = []

    for i in range(len(points)):
        if visited[i]:
            continue
        cluster = [i]
        visited[i] = True
        for j in range(i + 1, len(points)):
            if visited[j]:
                continue
            dist = math.sqrt((points[i][0] - points[j][0]) ** 2 + (points[i][1] - points[j][1]) ** 2)
            if dist <= radius:
                cluster.append(j)
                visited[j] = True
        if len(cluster) >= 2:
            clusters.append(cluster)

    result = []
    for cluster in clusters:
        pts = [points[idx] for idx in cluster]
        center_x = sum(p[0] for p in pts) / len(pts)
        center_y = sum(p[1] for p in pts) / len(pts)

        # 收集该聚类所有支持案例
        all_cases = set()
        for _, _, d in pts:
            for cid in d.get("supporting_case_ids") or []:
                all_cases.add(cid)

        maturity = pattern_maturity_score(
            center_x=center_x,
            center_y=center_y,
            case_count=len(all_cases),
            cluster_points=pts,
        )

        result.append({
            "cluster_center": {
                "x": round(center_x, 3),
                "y": round(center_y, 3),
            },
            "maturity_score": maturity["score"],
            "case_count": len(all_cases),
            "consistency": maturity["consistency"],
        })

    result.sort(key=lambda r: r["maturity_score"], reverse=True)
    return result


def pattern_maturity_score(
    center_x: float,
    center_y: float,
    case_count: int,
    cluster_points: List[Tuple[float, float, Dict[str, Any]]],
) -> Dict[str, float]:
    """计算模式成熟度分数。

    综合考虑:
    - y 轴高度 (0.35): 高 y 代表高置信度
    - 案例数量 (0.25): 支持案例越多越成熟
    - 聚类紧密度 (0.25): 点越密集越稳定
    - x 轴绝对值 (0.15): 远离 0 代表更明确的方向
    """
    # y 分量
    y_score = min(1.0, center_y)

    # 案例数量 (log scale, 10 cases → 1.0)
    case_score = min(1.0, math.log2(case_count + 1) / math.log2(11))

    # 紧密度 (点间平均距离反比)
    if len(cluster_points) >= 2:
        dists = []
        for i in range(len(cluster_points)):
            for j in range(i + 1, len(cluster_points)):
                d = math.sqrt(
                    (cluster_points[i][0] - cluster_points[j][0]) ** 2
                    + (cluster_points[i][1] - cluster_points[j][1]) ** 2
                )
                dists.append(d)
        avg_dist = sum(dists) / len(dists)
        tightness = max(0.0, 1.0 - avg_dist / 0.6)
    else:
        tightness = 1.0

    # x 轴明确度
    x_clarity = min(1.0, abs(center_x) * 2)

    score = round(y_score * 0.35 + case_score * 0.25 + tightness * 0.25 + x_clarity * 0.15, 3)
    consistency = round(tightness, 3)

    return {"score": score, "consistency": consistency}


# ---------------------------------------------------------------------------
# existing functions below


def now_iso_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _list_json(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file()])


def _load_all_cases() -> List[Dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in _list_json(memory_l4_cases_dir())]


def compute_stage_coverage(cases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """统计 A0-A9 各阶段覆盖情况。"""
    if cases is None:
        cases = _load_all_cases()
    stage_counts = {f"A{i}": 0 for i in range(10)}
    total = len(cases)
    for c in cases:
        seen = set()
        for entry in c.get("thinking_chain") or []:
            s = entry.get("stage")
            if s and s in stage_counts:
                seen.add(s)
        for s in seen:
            stage_counts[s] += 1
    return {
        "total_cases": total,
        "stage_counts": stage_counts,
        "stage_rates": {s: round(v / total, 3) if total else 0 for s, v in stage_counts.items()},
    }


def compute_quadrant_distribution(cases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """统计象限分布。"""
    if cases is None:
        cases = _load_all_cases()
    xs, ys = [], []
    for c in cases:
        q = c.get("quadrant") or {}
        if q.get("x") is not None and q.get("y") is not None:
            xs.append(q["x"])
            ys.append(q["y"])
    return {
        "count": len(xs),
        "x_mean": round(sum(xs) / len(xs), 3) if xs else 0,
        "y_mean": round(sum(ys) / len(ys), 3) if ys else 0,
        "x_range": [round(min(xs), 3), round(max(xs), 3)] if xs else [0, 0],
        "y_range": [round(min(ys), 3), round(max(ys), 3)] if ys else [0, 0],
    }


def compute_pnl_stats(cases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """统计收益分布。"""
    if cases is None:
        cases = _load_all_cases()
    pnls = []
    for c in cases:
        do = c.get("decision_outcome") or {}
        p = do.get("pnl_pct")
        if p is not None:
            pnls.append(float(p))
    if not pnls:
        return {"count": 0, "mean": 0, "median": 0, "win_rate": 0, "max": 0, "min": 0}
    pnls.sort()
    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    if n % 2 == 1:
        median = pnls[n // 2]
    else:
        median = (pnls[n // 2 - 1] + pnls[n // 2]) / 2
    return {
        "count": n,
        "mean": round(sum(pnls) / n, 3),
        "median": round(median, 3),
        "win_rate": round(wins / n, 3),
        "max": round(max(pnls), 3),
        "min": round(min(pnls), 3),
    }


def compute_l4_status_distribution(cases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """统计 L4 状态机分布。"""
    if cases is None:
        cases = _load_all_cases()
    status_counts: Dict[str, int] = {}
    for c in cases:
        s = c.get("l4_status") or "UNKNOWN"
        status_counts[s] = status_counts.get(s, 0) + 1
    total = len(cases)
    return {
        "total": total,
        "distribution": status_counts,
        "rates": {s: round(v / total, 3) if total else 0 for s, v in status_counts.items()},
    }


def compute_full_stats(snapshot_ts: Optional[str] = None) -> Dict[str, Any]:
    """聚合全部统计，产出 StatsSnapshot v0.2。"""
    ts = snapshot_ts or now_iso_local()
    cases = _load_all_cases()
    distills = _load_all_distills()
    return {
        "snapshot_id": f"STATS_{ts.replace(':', '').replace('-', '').replace('+', '')[:15]}",
        "snapshot_ts": ts,
        "version": "v0.2",
        "stage_coverage": compute_stage_coverage(cases),
        "quadrant_distribution": compute_quadrant_distribution(cases),
        "pnl_stats": compute_pnl_stats(cases),
        "l4_status_distribution": compute_l4_status_distribution(cases),
        "event_library": compute_event_library(cases),
        "evolution_metrics": compute_evolution_metrics(distills),
        "distill_count": len(_list_json(memory_l4_distills_dir())),
        "review_count": len(_list_json(memory_l4_reviews_dir())),
    }


def save_stats(stats: Dict[str, Any], out_path: Optional[Path] = None) -> Path:
    """保存统计快照。"""
    target = out_path or (memory_l4_stats_dir() / f"{stats['snapshot_id']}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# v0.2: migration_trends — from deprecated stats_builder.py
# ---------------------------------------------------------------------------

def build_migration_trends(
    snapshot_ts: str,
    distills: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """从蒸馏记录构建迁移趋势序列。"""
    if distills is None:
        distills = _load_all_distills()
    out: List[Dict[str, Any]] = []
    for d in distills:
        did = str(d.get("distill_id") or "")
        if not did:
            continue
        q = d.get("quadrant") or {}
        y_now = float(q.get("y") or 0.0)
        history = d.get("migration_history") or []

        series: List[Dict[str, Any]] = []
        for rec in history:
            ts = rec.get("ts")
            y_new = rec.get("y_new")
            if ts is None or y_new is None:
                continue
            series.append({"ts": str(ts), "y": float(y_new)})
        series.append({"ts": snapshot_ts, "y": y_now})

        out.append({"id": did, "kind": "distill", "series": series})
    return out


# ---------------------------------------------------------------------------
# v0.2: performance — from deprecated stats_builder.py
# ---------------------------------------------------------------------------

def _episode_pnl(ep: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """从 episode outcome 提取 pnl (usdt, pct)。"""
    out = ep.get("outcome") or {}
    pos = ep.get("position") or {}
    pnl_usdt = out.get("unrealized_pnl_usdt")
    if pnl_usdt is None:
        pnl_usdt = out.get("unrealized_pnl")
    if pnl_usdt is None:
        pnl_usdt = pos.get("upl")
    pnl_pct = out.get("unrealized_pnl_pct")
    return (
        float(pnl_usdt) if pnl_usdt is not None else None,
        float(pnl_pct) if pnl_pct is not None else None,
    )


def _extract_episode_ref_path(case: Dict[str, Any]) -> Optional[str]:
    """从 TradeCase 提取 episode 文件路径。"""
    refs = ((case.get("execution") or {}).get("episode_refs") or [])
    if not refs:
        return None
    p = str((refs[0] or {}).get("path") or "").strip()
    return p if p else None


def _read_episode(path: str) -> Dict[str, Any]:
    """读取 episode JSON 文件。"""
    ep = Path(path)
    if not ep.is_absolute():
        ep = _ROOT / ep
    if not ep.exists():
        return {}
    try:
        return json.loads(ep.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_episodes_by_case_id(cases: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """从 cases 批量加载 episodes，按 case_id 索引。"""
    out: Dict[str, Dict[str, Any]] = {}
    for c in cases:
        cid = str(c.get("case_id") or "")
        if not cid:
            continue
        p = _extract_episode_ref_path(c)
        out[cid] = _read_episode(p) if p else {}
    return out


def _compute_max_drawdown(series: List[float]) -> float:
    """计算累计收益曲线的最大回撤。"""
    if not series:
        return 0.0
    peak = series[0]
    mdd = 0.0
    for v in series:
        if v > peak:
            peak = v
        drawdown = peak - v
        if drawdown > mdd:
            mdd = drawdown
    return mdd


def compute_performance(
    cases: Optional[List[Dict[str, Any]]] = None,
    episodes_by_case_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """计算详细收益指标：胜率、盈亏比、最大回撤等。"""
    if cases is None:
        cases = _load_all_cases()
    if episodes_by_case_id is None:
        episodes_by_case_id = _load_episodes_by_case_id(cases)

    wins = 0
    losses = 0
    n_with_outcome = 0
    pnl_usdts: List[float] = []
    pnl_pcts: List[float] = []

    ordered_cases = sorted(cases, key=lambda c: str(c.get("ts_start") or ""))
    cum = 0.0
    equity_curve: List[float] = [0.0]
    for c in ordered_cases:
        cid = str(c.get("case_id") or "")
        ep = episodes_by_case_id.get(cid) or {}
        pnl_usdt, pnl_pct = _episode_pnl(ep)
        if pnl_usdt is None and pnl_pct is None:
            continue
        n_with_outcome += 1
        if pnl_pct is not None:
            pnl_pcts.append(float(pnl_pct))
            if pnl_pct > 0:
                wins += 1
            elif pnl_pct < 0:
                losses += 1
        elif pnl_usdt is not None:
            if pnl_usdt > 0:
                wins += 1
            elif pnl_usdt < 0:
                losses += 1
        if pnl_usdt is not None:
            pnl_usdts.append(float(pnl_usdt))
            cum += float(pnl_usdt)
            equity_curve.append(cum)

    denom = wins + losses
    win_rate = (float(wins) / float(denom)) if denom > 0 else 0.0
    avg_pnl_usdt = (sum(pnl_usdts) / len(pnl_usdts)) if pnl_usdts else None
    avg_pnl_pct = (sum(pnl_pcts) / len(pnl_pcts)) if pnl_pcts else None
    gross_win = sum(x for x in pnl_usdts if x > 0)
    gross_loss = abs(sum(x for x in pnl_usdts if x < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    mdd = _compute_max_drawdown(equity_curve) if pnl_usdts else None

    return {
        "n_cases": len(cases),
        "n_with_outcome": n_with_outcome,
        "wins": wins,
        "losses": losses,
        "win_rate": round(float(win_rate), 4),
        "avg_pnl_usdt": round(float(avg_pnl_usdt), 4) if avg_pnl_usdt is not None else None,
        "avg_pnl_pct": round(float(avg_pnl_pct), 4) if avg_pnl_pct is not None else None,
        "profit_factor": round(float(profit_factor), 4) if profit_factor is not None else None,
        "max_drawdown": round(float(mdd), 4) if mdd is not None else None,
    }
