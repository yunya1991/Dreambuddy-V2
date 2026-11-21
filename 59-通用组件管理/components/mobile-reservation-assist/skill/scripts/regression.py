"""回归任务集：把「适配器基线 + 录制快照」固化为可批量执行的兼容性回归用例。

用例 = (case_id, baseline_name, exploration_id, expect_compatible, tags)。
执行 = 对每个用例跑 `explore.check_compatibility`，与期望比对：
- 期望兼容且实际兼容 / 期望不兼容且实际不兼容 → pass；
- 其余 → fail；基线或快照缺失 → error。

产物 `regression.v1` 并落库 `regression_runs`，便于按次追溯。
"""

from __future__ import annotations

import time

import explore

SCHEMA = "regression.v1"


def _tag_match(tags: str, tag: str) -> bool:
    if not tag:
        return True
    return tag in [item.strip() for item in str(tags or "").split(",") if item.strip()]


def add_case(
    db, case_id: str, baseline: str, exploration_id: int, expect: bool = True, tags: str = ""
) -> dict:
    db.add_regression_case(case_id, baseline, exploration_id, expect, tags)
    return {
        "schema": SCHEMA + ".case",
        "case_id": case_id,
        "baseline": baseline,
        "exploration_id": int(exploration_id),
        "expect_compatible": bool(expect),
        "tags": tags,
    }


def run_suite(db, tag: str = "", threshold: float = explore.DEFAULT_THRESHOLD) -> dict:
    started = time.monotonic()
    cases = [case for case in db.list_regression_cases() if _tag_match(case["tags"], tag)]
    rows: list[dict] = []
    passed = failed = errors = 0

    for case in cases:
        row = {
            "case_id": case["case_id"],
            "baseline": case["baseline_name"],
            "exploration_id": case["exploration_id"],
            "expect_compatible": bool(case["expect_compatible"]),
            "tags": case["tags"],
        }
        baseline = db.get_baseline(case["baseline_name"])
        snapshots = db.list_snapshots(case["exploration_id"])
        if baseline is None:
            row.update(verdict="error", reason="baseline_missing", compatible=None, coverage=0.0, step_misses=[])
            errors += 1
        elif not snapshots:
            row.update(verdict="error", reason="snapshots_missing", compatible=None, coverage=0.0, step_misses=[])
            errors += 1
        else:
            result = explore.check_compatibility(baseline, snapshots, threshold)
            compatible = bool(result["compatible"])
            ok = compatible == bool(case["expect_compatible"])
            row.update(
                verdict="pass" if ok else "fail",
                reason="",
                compatible=compatible,
                coverage=result["coverage"],
                missing=len(result["missing"]),
                step_misses=result["step_misses"],
            )
            passed += 1 if ok else 0
            failed += 0 if ok else 1
        rows.append(row)

    report = {
        "schema": SCHEMA,
        "tag": tag,
        "threshold": threshold,
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "cases": rows,
        "ok": bool(rows) and failed == 0 and errors == 0,
    }
    report["run_id"] = db.save_regression_run(report)
    return report
