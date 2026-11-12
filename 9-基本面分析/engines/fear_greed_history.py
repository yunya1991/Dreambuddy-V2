"""P2 fear_greed 长历史旁路：19-DAL 真实观测适配到 sentiment 历史。

只负责数据源适配；幂等写入与全部统计仍由 `engines.dimension_history` 执行。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engines.dimension_history import append_observations, get_dimension_history

SUB_CATEGORY = "crypto_fear_greed"
METRIC_NAME = "value"
MODULE = "sentiment"
SOURCE = "19_dal:mm_metrics.crypto_fear_greed.value"


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _written_at(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    return str(value)


def observations_from_fear_greed(
    rows: list[tuple], written_at: str | datetime | None = None
) -> list[dict]:
    """DAL `(source, metric, value, timestamp)` 行 → 每日一条真实观测。

    同日多条取时间戳最晚者；非 0-100、非有限值或缺合法时间戳的行拒绝转换。
    """
    daily: dict[str, tuple[datetime, float]] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        try:
            value = float(row[2])
        except (TypeError, ValueError):
            continue
        observed_at = _as_utc(row[3])
        if observed_at is None or not math.isfinite(value) or not 0.0 <= value <= 100.0:
            continue
        day = observed_at.date().isoformat()
        previous = daily.get(day)
        if previous is None or observed_at >= previous[0]:
            daily[day] = (observed_at, value)

    stamp = _written_at(written_at)
    observations: list[dict] = []
    previous_score = 0.0
    previous_velocity = 0.0
    for index, day in enumerate(sorted(daily)):
        value = daily[day][1]
        score = max(-1.0, min(1.0, (value - 50.0) / 50.0))
        direction = "up" if score > 0.3 else "down" if score < -0.3 else "neutral"
        velocity = score - previous_score if index else 0.0
        acceleration = velocity - previous_velocity if index else 0.0
        observations.append(
            {
                "date": day,
                "module": MODULE,
                "value": value,
                "value_scale": "index_0_100",
                "direction": direction,
                "direction_score": round(score, 4),
                "velocity": round(velocity, 4),
                "acceleration": round(acceleration, 4),
                "velocity_label": "",
                "confidence": 0.5,
                "data_points": index + 1,
                "observed_date_source": "dal_timestamp",
                "source": SOURCE,
                "written_at": stamp,
                "schema_version": 1,
            }
        )
        previous_score = score
        previous_velocity = velocity
    return observations


def backfill_fear_greed(
    *,
    repo: Any = None,
    start: datetime | None = None,
    end: datetime | None = None,
    base_dir: Path | None = None,
    written_at: str | datetime | None = None,
    dry_run: bool = False,
) -> dict:
    """从 19-DAL 回填全量 fear_greed；`dry_run=True` 只读取，绝不写盘。"""
    if repo is None:
        from dal_snapshot_provider import DalSnapshotProvider  # noqa: PLC0415

        repo = DalSnapshotProvider().get_repo()
    if repo is None:
        raise RuntimeError("19-DAL MarketMacroRepository 不可用，未执行回填")

    start = start or datetime(1970, 1, 1, tzinfo=timezone.utc)
    end = end or datetime.now(timezone.utc)
    rows = repo.query_metric_by_time(SUB_CATEGORY, METRIC_NAME, start, end)
    observations = observations_from_fear_greed(rows, written_at=written_at)
    written = 0 if dry_run else append_observations(MODULE, observations, base_dir=base_dir)
    result = {
        "module": MODULE,
        "source": SOURCE,
        "fetched": len(rows),
        "observations": len(observations),
        "written": written,
        "dry_run": dry_run,
        "first_day": observations[0]["date"] if observations else None,
        "last_day": observations[-1]["date"] if observations else None,
        "history": None,
    }
    if not dry_run:
        result["history"] = get_dimension_history(MODULE, base_dir=base_dir)
    return result
