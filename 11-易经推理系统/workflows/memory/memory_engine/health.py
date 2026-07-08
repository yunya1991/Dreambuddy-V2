from typing import Any, Dict, Optional


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_health_score(report: Dict[str, Any], index_data: Optional[Dict[str, Any]] = None) -> float:
    summary = (report or {}).get("summary") or {}
    issues = (report or {}).get("issues") or []

    issue_count = len(issues)
    coverage = float(summary.get("episode_coverage_ratio", 1.0) or 0.0)
    coverage_penalty = (1.0 - _clamp(coverage, 0.0, 1.0)) * 30.0
    issue_penalty = float(issue_count) * 10.0

    index_penalty = 0.0
    if isinstance(index_data, dict):
        case_count = int(summary.get("case_count", 0) or 0)
        indexed = len((index_data.get("case_features") or {}).keys())
        if case_count > 0 and indexed < case_count:
            index_penalty = (float(case_count - indexed) / float(case_count)) * 20.0

    raw = 100.0 - coverage_penalty - issue_penalty - index_penalty
    return round(_clamp(raw, 0.0, 100.0), 2)
