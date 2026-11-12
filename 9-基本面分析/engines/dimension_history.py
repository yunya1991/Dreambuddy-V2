"""9 域各维历史统计 — SPEC-9DOMAIN-HISTORY-CONTEXT-v1.1 P0 权威实现。

唯一入口：历史读写 + 统计口径（§5.2 预注册冻结）。

- 写入：`storage/dimension_history/{module}.jsonl`，按 `(module, date)` 幂等 upsert
- 读取：`as_of` 严格前视截断（`date <= as_of`）
- 统计：纯函数，缺失一律 `null` + `notes` 说明，不插值、不填 0
- 合成数据不进本层（mock 只存在于快照 `meta.timeseries_synthetic`）
"""

from __future__ import annotations

import json
import math
import os
from bisect import bisect_left, bisect_right
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from engines.least_resistance import compute_resistance_3d, velocity_label_of

BASE_DIR = Path(__file__).resolve().parents[1]
HISTORY_DIR = BASE_DIR / "storage" / "dimension_history"

MODULES = (
    "news",
    "flow",
    "sentiment",
    "macro",
    "breadth",
    "intermarket",
    "valuation",
    "onchain",
    "calendar",
    "narrative",
)

# §1.4：value 的量纲随模块漂移，跨模块比较一律用 direction_score
VALUE_SCALE = {
    "news": "score_neg1_pos1",
    "flow": "score_neg1_pos1",
    "macro": "score_neg1_pos1",
    "breadth": "score_neg1_pos1",
    "intermarket": "score_neg1_pos1",
    "calendar": "score_neg1_pos1",
    "narrative": "score_neg1_pos1",
    "sentiment": "index_0_100",
    "valuation": "ratio",
    "onchain": "level",
}

STATS_MIN_DAYS = {
    "pct_rank_1y": 250,
    "pct_rank_3y": 750,
    "extreme_days": 60,
    "mean_revert_z": 60,
    "trend_20d": 20,
    "regime_switch_30d": 31,
}

Z_WINDOW = 60
EXTREME_Z = 2.0
EXTREME_SCAN_WINDOW = 250
RANK_WINDOW_1Y = 250
RANK_WINDOW_3Y = 750
Z_CLAMP = 3.0
STALE_GAP_DAYS = 7
AVAILABILITY_LONG = 900
AVAILABILITY_SHORT = 30

STAT_KEYS = (
    "pct_rank_1y",
    "pct_rank_3y",
    "extreme_days",
    "mean_revert_z",
    "trend_20d",
    "regime_switch_30d",
)

_SCHEMA_VERSION = 1


# ============== 基础工具 ==============


def _parse_day(value: Any) -> date | None:
    """宽松解析 ISO 日期 / 时间戳前缀；失败返回 None。"""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((x - mu) ** 2 for x in values) / (len(values) - 1))


def _average_ranks(values: list[float]) -> list[float]:
    """并列取平均秩（0-based）。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rx, ry = _average_ranks(xs), _average_ranks(ys)
    mx, my = _mean(rx), _mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _average_rank_of(sorted_vals: list[float], x: float) -> float:
    lo = bisect_left(sorted_vals, x)
    hi = bisect_right(sorted_vals, x)
    return (lo + hi - 1) / 2.0


# ============== 读写 ==============


def _series_path(module: str, base_dir: Path | None = None) -> Path:
    if base_dir is None:
        return HISTORY_DIR / f"{module}.jsonl"
    return Path(base_dir) / "dimension_history" / f"{module}.jsonl"


def append_observations(module: str, observations: list[dict], base_dir: Path | None = None) -> int:
    """批量幂等 upsert，单次读写；返回有效观测数，缺 date 的条目拒写。"""
    valid = [(_parse_day(obs.get("date")), obs) for obs in observations]
    valid = [(day, obs) for day, obs in valid if day is not None]
    if not valid:
        return 0

    path = _series_path(module, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = _parse_day(row.get("date"))
            if key is not None:
                existing[key.isoformat()] = row

    for day, obs in valid:
        key = day.isoformat()
        record = dict(obs)
        record["date"] = key
        record["module"] = module
        record.setdefault("value_scale", VALUE_SCALE.get(module, "score_neg1_pos1"))
        record.setdefault("schema_version", _SCHEMA_VERSION)

        prev = existing.get(key)
        if prev is None or str(record.get("written_at", "")) >= str(prev.get("written_at", "")):
            existing[key] = record

    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for d in sorted(existing):
            fh.write(json.dumps(existing[d], ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return len(valid)


def append_observation(module: str, obs: dict, base_dir: Path | None = None) -> bool:
    """按 (module, date) 幂等 upsert；缺 date / 不可解析 → False（fail-closed）。"""
    return append_observations(module, [obs], base_dir=base_dir) == 1


def load_series(module: str, as_of: str | None = None, base_dir: Path | None = None) -> list[dict]:
    """按 date 升序返回；as_of 严格截断（date <= as_of）。"""
    path = _series_path(module, base_dir)
    if not path.exists():
        return []

    cutoff = _parse_day(as_of) if as_of else None
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        day = _parse_day(row.get("date"))
        if day is None or (cutoff is not None and day > cutoff):
            continue
        rows[day.isoformat()] = row
    return [rows[d] for d in sorted(rows)]


# ============== 统计 ==============


def _pct_rank(values: list[float], window: int) -> float | None:
    m = min(len(values), window)
    sample = values[-m:]
    if m < window:
        return None
    sorted_vals = sorted(sample)
    return _average_rank_of(sorted_vals, sample[-1]) / (m - 1)


def _mean_revert_z(values: list[float]) -> tuple[float | None, bool]:
    window = values[-Z_WINDOW:]
    mu, sd = _mean(window), _std(window)
    if sd == 0:
        return None, False
    z = (window[-1] - mu) / sd
    clamped = abs(z) > Z_CLAMP
    return (Z_CLAMP if z > 0 else -Z_CLAMP) if clamped else z, clamped


def _extreme_days(values: list[float]) -> int | None:
    if len(values) < Z_WINDOW:
        return None
    start = max(Z_WINDOW - 1, len(values) - EXTREME_SCAN_WINDOW)
    count = 0
    for i in range(start, len(values)):
        window = values[i - Z_WINDOW + 1 : i + 1]
        mu, sd = _mean(window), _std(window)
        if sd == 0:
            continue
        if abs((values[i] - mu) / sd) >= EXTREME_Z:
            count += 1
    return count


def _regime_switches(series: list[dict]) -> int | None:
    if len(series) < STATS_MIN_DAYS["regime_switch_30d"]:
        return None

    dirs = [str(row.get("direction") or "neutral") for row in series]
    confirmed = [dirs[0]]
    for i in range(1, len(dirs)):
        confirmed.append(dirs[i] if dirs[i] == dirs[i - 1] else confirmed[-1])

    tail = confirmed[-30:]
    return sum(1 for i in range(1, len(tail)) if tail[i] != tail[i - 1])


def _coverage(series: list[dict]) -> dict:
    days = [str(row["date"]) for row in series]
    observed = len(days)
    if observed == 0:
        return {
            "observed_days": 0,
            "expected_days": 0,
            "missing_days": 0,
            "max_gap_days": 0,
            "median_gap_days": 0,
            "first_day": None,
            "last_day": None,
        }

    dates = [date.fromisoformat(d) for d in days]
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    span = (dates[-1] - dates[0]).days
    med_gap = median(gaps) if gaps else 1
    step = max(1, int(round(med_gap)))
    expected = int(round(span / step)) + 1
    return {
        "observed_days": observed,
        "expected_days": expected,
        "missing_days": max(0, expected - observed),
        "max_gap_days": max(gaps) if gaps else 0,
        "median_gap_days": med_gap,
        "first_day": days[0],
        "last_day": days[-1],
    }


def _availability(observed: int) -> str:
    if observed >= AVAILABILITY_LONG:
        return "long"
    if observed >= AVAILABILITY_SHORT:
        return "short"
    return "none"


def compute_dimension_history(series: list[dict], module: str, as_of: str | None = None) -> dict:
    """纯函数：由已加载观测序列计算 DimensionHistory（§3.1）。"""
    scale = VALUE_SCALE.get(module, "score_neg1_pos1")

    rows: list[dict] = []
    for row in series or []:
        day = _parse_day(row.get("date"))
        value = _to_float(row.get("value"))
        if day is None or value is None:
            continue
        clean = dict(row)
        clean["date"] = day.isoformat()
        clean["value"] = value
        rows.append(clean)

    cutoff = _parse_day(as_of) if as_of else None
    if cutoff is not None:
        rows = [r for r in rows if date.fromisoformat(r["date"]) <= cutoff]
    rows.sort(key=lambda r: r["date"])

    notes: list[str] = []
    coverage = _coverage(rows)
    values = [r["value"] for r in rows]
    n = len(values)

    stats: dict[str, Any] = dict.fromkeys(STAT_KEYS)
    if n:
        pr1 = _pct_rank(values, RANK_WINDOW_1Y)
        stats["pct_rank_1y"] = pr1
        if pr1 is None:
            notes.append(f"pct_rank_1y: insufficient_history({n}<{RANK_WINDOW_1Y})")

        pr3 = _pct_rank(values, RANK_WINDOW_3Y)
        stats["pct_rank_3y"] = pr3
        if pr3 is None:
            notes.append(f"pct_rank_3y: insufficient_history({n}<{RANK_WINDOW_3Y})")

        if n >= STATS_MIN_DAYS["mean_revert_z"]:
            z, clamped = _mean_revert_z(values)
            stats["mean_revert_z"] = z
            if z is None:
                notes.append("mean_revert_z: zero_variance")
            elif clamped:
                notes.append(f"mean_revert_z: winsor_clamped({'+' if z > 0 else '-'}{Z_CLAMP:g})")
        else:
            notes.append(f"mean_revert_z: insufficient_history({n}<{Z_WINDOW})")

        stats["extreme_days"] = _extreme_days(values)
        if stats["extreme_days"] is None:
            notes.append(f"extreme_days: insufficient_history({n}<{Z_WINDOW})")

        if n >= STATS_MIN_DAYS["trend_20d"]:
            window = values[-20:]
            stats["trend_20d"] = _spearman([float(i) for i in range(20)], window)
        else:
            notes.append(f"trend_20d: insufficient_history({n}<20)")

        stats["regime_switch_30d"] = _regime_switches(rows)
        if stats["regime_switch_30d"] is None:
            notes.append(
                f"regime_switch_30d: insufficient_history({n}<{STATS_MIN_DAYS['regime_switch_30d']})"
            )

    latest: dict[str, Any] = {}
    if rows:
        r3d = compute_resistance_3d(values[-1], values[:-1])
        r3d["velocity_label"] = velocity_label_of(r3d["velocity"], scale)
        latest = r3d

    if coverage["max_gap_days"] > STALE_GAP_DAYS:
        notes.append(f"stale_series: max_gap_days={coverage['max_gap_days']}")
    if not rows:
        notes.append("no_observations")

    resolved_as_of = as_of
    if resolved_as_of is None and rows:
        resolved_as_of = rows[-1]["date"]

    return {
        "module": module,
        "as_of": resolved_as_of,
        "source": "9_storage_jsonl" if rows else "none",
        "value_scale": scale,
        "lookback_days": n,
        "availability": _availability(n),
        "coverage": coverage,
        "latest": latest,
        "stats": stats,
        "notes": notes,
    }


def get_dimension_history(
    module: str, as_of: str | None = None, base_dir: Path | None = None
) -> dict:
    """读取 + 计算的便捷入口。"""
    series = load_series(module, as_of=as_of, base_dir=base_dir)
    return compute_dimension_history(series, module, as_of)


def observation_from_snapshot(snapshot: dict) -> dict | None:
    """从 9 域快照提取一条观测（§4.2 观测日只认 meta.observed_date）。"""
    if not isinstance(snapshot, dict):
        return None
    meta = snapshot.get("meta") or {}
    day = meta.get("observed_date")
    if _parse_day(day) is None:
        return None

    module = snapshot.get("module")
    r3d = snapshot.get("resistance_3d") or {}
    value = None
    ts = snapshot.get("timeseries")
    if isinstance(ts, list) and ts:
        value = _to_float((ts[-1] or {}).get("value"))
    if value is None:
        value = _to_float(r3d.get("direction_score"))
    if value is None:
        return None

    return {
        "date": str(day)[:10],
        "module": module,
        "value": value,
        "value_scale": VALUE_SCALE.get(module, "score_neg1_pos1"),
        "direction": r3d.get("direction"),
        "direction_score": r3d.get("direction_score"),
        "velocity": r3d.get("velocity"),
        "acceleration": r3d.get("acceleration"),
        "velocity_label": r3d.get("velocity_label", ""),
        "confidence": r3d.get("confidence"),
        "data_points": r3d.get("data_points"),
        "written_at": snapshot.get("ts"),
        "schema_version": _SCHEMA_VERSION,
    }
