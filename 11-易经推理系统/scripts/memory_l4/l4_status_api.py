"""L4 认知闭环状态 API

提供 /api/l4-status 端点所需的数据聚合函数。
实时展示各环节数据量和状态。
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import memory_l4_cases_dir, memory_l4_reviews_dir, memory_l4_distills_dir, memory_l4_stats_dir


def _list_json(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file() and "_v02_backup" not in p.name])


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_l4_status() -> Dict[str, Any]:
    """获取 L4 认知闭环完整状态

    Returns:
        {
            "timestamp": "...",
            "pipeline": {
                "cases": {"total": N, "by_system": {...}, "by_status": {...}},
                "reviews": {"total": N, "success": N, "failure": N},
                "distills": {"total": N},
                "stats": {"total": N, "latest": {...}},
                "qmm": {"snapshots": N, "latest": {...}},
            },
            "health": {
                "pipeline_connected": bool,  # Review→Distill→Stats 是否通畅
                "qmm_consuming_real": bool,  # QMM 是否消费真实案例
                "schema_compliance": float,  # schema 合规率
            },
            "evolution": {
                "review_rate": float,  # 复盘覆盖率
                "distill_rate": float,  # 蒸馏转化率
                "avg_consistency_score": float,  # 平均理论一致性
            }
        }
    """
    wb = _ROOT / ".workbuddy" / "memory_l4"

    cases_dir = wb / "cases"
    reviews_dir = wb / "reviews"
    distills_dir = wb / "distills"
    stats_dir = wb / "stats"
    qmm_dir = wb / "qmm"

    # === Cases ===
    case_files = _list_json(cases_dir)
    cases_total = len(case_files)
    cases_by_system: Dict[str, int] = {}
    cases_by_status: Dict[str, int] = {}
    schema_valid = 0
    schema_invalid = 0

    for f in case_files:
        case = _load_json(f)
        if not case:
            continue
        system = case.get("system_source", "unknown")
        cases_by_system[system] = cases_by_system.get(system, 0) + 1
        status = case.get("l4_status", "M0_CASE_REGISTERED")
        cases_by_status[status] = cases_by_status.get(status, 0) + 1
        if "_validation_errors" not in case:
            schema_valid += 1
        else:
            schema_invalid += 1

    # === Reviews ===
    review_files = _list_json(reviews_dir)
    reviews_total = len(review_files)
    review_success = 0
    review_failure = 0
    total_consistency_score = 0.0
    consistency_count = 0

    for f in review_files:
        review = _load_json(f)
        if not review:
            continue
        direction = review.get("direction")
        if direction == "success":
            review_success += 1
        elif direction == "failure":
            review_failure += 1

        tpa = review.get("theory_practice_analysis", {})
        score = tpa.get("consistency_score")
        if score is not None:
            total_consistency_score += score
            consistency_count += 1

    # === Distills ===
    distill_files = _list_json(distills_dir)
    distills_total = len(distill_files)

    # === Stats ===
    stats_files = _list_json(stats_dir)
    stats_total = len(stats_files)
    latest_stats = None
    if stats_files:
        latest_stats = _load_json(stats_files[-1])

    # === QMM ===
    qmm_files = _list_json(qmm_dir)
    qmm_snapshots = len([f for f in qmm_files if f.name.startswith("qmm_snapshot_")])
    latest_qmm = None
    for f in reversed(qmm_files):
        if f.name.startswith("qmm_snapshot_"):
            latest_qmm = _load_json(f)
            break

    # === Health Checks ===
    # 判断 QMM 是否消费真实案例（非测试案例）
    qmm_consuming_real = False
    if latest_qmm:
        system_stats = latest_qmm.get("system_source_stats", {})
        # 如果包含大量 qmm_test 相关的系统来源，说明消费的是测试案例
        qmm_consuming_real = not any("qmm_test" in str(k) for k in system_stats.keys())

    # Pipeline 是否通畅：有案例、有复盘、有蒸馏、有统计
    pipeline_connected = cases_total > 0 and reviews_total > 0 and distills_total > 0 and stats_total > 0

    # Schema 合规率
    schema_compliance = schema_valid / (schema_valid + schema_invalid) if (schema_valid + schema_invalid) > 0 else 1.0

    # === Evolution Metrics ===
    review_rate = reviews_total / cases_total if cases_total > 0 else 0.0
    distill_rate = distills_total / reviews_total if reviews_total > 0 else 0.0
    avg_consistency = total_consistency_score / consistency_count if consistency_count > 0 else 0.0

    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pipeline": {
            "cases": {
                "total": cases_total,
                "by_system": cases_by_system,
                "by_status": cases_by_status,
            },
            "reviews": {
                "total": reviews_total,
                "success": review_success,
                "failure": review_failure,
            },
            "distills": {
                "total": distills_total,
            },
            "stats": {
                "total": stats_total,
                "latest": {
                    "snapshot_id": latest_stats.get("snapshot_id") if latest_stats else None,
                    "snapshot_ts": latest_stats.get("snapshot_ts") if latest_stats else None,
                },
            },
            "qmm": {
                "snapshots": qmm_snapshots,
                "latest": {
                    "trend_state": latest_qmm.get("trend_state") if latest_qmm else None,
                    "uncertainty": latest_qmm.get("uncertainty") if latest_qmm else None,
                    "snapshot_ts": latest_qmm.get("snapshot_ts") if latest_qmm else None,
                },
            },
        },
        "health": {
            "pipeline_connected": pipeline_connected,
            "qmm_consuming_real": qmm_consuming_real,
            "schema_compliance": round(schema_compliance, 4),
            "schema_valid": schema_valid,
            "schema_invalid": schema_invalid,
        },
        "evolution": {
            "review_rate": round(review_rate, 4),
            "distill_rate": round(distill_rate, 4),
            "avg_consistency_score": round(avg_consistency, 4),
        },
    }


def get_l4_status_summary() -> Dict[str, Any]:
    """获取 L4 状态摘要（轻量级，适合频繁调用）"""
    status = get_l4_status()
    # 精简版本，去掉详细分布
    return {
        "timestamp": status["timestamp"],
        "cases_total": status["pipeline"]["cases"]["total"],
        "reviews_total": status["pipeline"]["reviews"]["total"],
        "distills_total": status["pipeline"]["distills"]["total"],
        "stats_total": status["pipeline"]["stats"]["total"],
        "qmm_snapshots": status["pipeline"]["qmm"]["snapshots"],
        "health": status["health"],
        "evolution": status["evolution"],
    }


if __name__ == "__main__":
    import sys
    status = get_l4_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))
