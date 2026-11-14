# -*- coding: utf-8 -*-
"""方法评估 harness：把「评估」变成机器可判定，而不是人工逐个人审。

六类检查（每方法自动执行，缺失前提则 skip）：
  1. meta       登记元数据完整（id/group/layer/input_kind/min_n/schema）
  2. gate       空输入必须返回 insufficient_samples，禁止抛异常
  3. determinism 同输入两次运行结果完全一致
  4. synthetic  合成已知解命中（方法自带 `checks.synthetic`）
  5. null        随机白噪声负例（|ρ| 小且显著率 ≤20%）
  6. reference  可选与 scipy/statsmodels 交叉验证

产物：`audit()` 返回机器可读报告；`scripts/method_audit.py` 落 JSON。
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from l1agg.methods.registry import REGISTRY, MethodSpec, all_specs, get, run

_MISSING = object()


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    skipped: bool = False
    skip_kind: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "skipped": self.skipped,
            "skip_kind": self.skip_kind or None,
            "detail": self.detail,
        }


def _coverage(checks: Sequence[CheckResult]) -> Dict[str, Any]:
    executed = sum(not c.skipped for c in checks)
    not_applicable = sum(c.skipped and c.skip_kind == "not_applicable" for c in checks)
    missing = sum(c.skipped and c.skip_kind == "missing" for c in checks)
    applicable = executed + missing
    return {
        "total": len(checks),
        "executed": executed,
        "not_applicable": not_applicable,
        "missing": missing,
        "rate": round(executed / applicable, 6) if applicable else 1.0,
    }


@dataclass
class MethodReport:
    method_id: str
    name: str
    implemented: bool
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if not c.skipped)

    @property
    def coverage(self) -> Dict[str, Any]:
        return _coverage(self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method_id": self.method_id,
            "name": self.name,
            "implemented": self.implemented,
            "passed": self.passed,
            "coverage": self.coverage,
            "checks": [c.to_dict() for c in self.checks],
        }


def _resolve(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, Mapping):
            if part not in cur:
                return _MISSING
            cur = cur[part]
        elif isinstance(cur, Sequence) and not isinstance(cur, str):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
    return cur


def _close(actual: Any, expect: Any, tol: float = 1e-3) -> bool:
    if expect == "non_empty":
        return actual not in (None, [], {}, "")
    if isinstance(expect, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(actual), float(expect), rel_tol=tol, abs_tol=tol)
    return actual == expect


def _synthetic_case(spec: MethodSpec, seed: int) -> Optional[Dict[str, Any]]:
    if spec.checks.synthetic is not None:
        return spec.checks.synthetic()
    if spec.input_kind == "pairs" and spec.min_n > 0:
        rng = random.Random(seed)
        n = max(spec.min_n, 30)
        return {
            "data": {
                "x": [rng.gauss(0, 1) for _ in range(n)],
                "y": [rng.gauss(0, 1) for _ in range(n)],
            },
            "params": {},
        }
    return None


def _empty_data(spec: MethodSpec) -> Any:
    if spec.input_kind == "panel":
        return {"series": {}}
    if spec.input_kind == "pairs":
        return {"x": [], "y": []}
    return []


def _p_values(result: Mapping[str, Any]) -> Optional[List[float]]:
    p = result.get("p")
    if isinstance(p, (int, float)):
        return [float(p)]
    if isinstance(p, Sequence) and p:
        return [float(v) for v in p]
    return None


def _check_meta(spec: MethodSpec) -> CheckResult:
    problems = []
    if not spec.method_id:
        problems.append("empty id")
    if spec.layer not in ("D1", "D2", "D3"):
        problems.append(f"bad layer {spec.layer}")
    if spec.input_kind not in ("pairs", "series", "panel", "events"):
        problems.append(f"bad input_kind {spec.input_kind}")
    if spec.min_n < 0:
        problems.append("min_n<0")
    if spec.implemented and not spec.output_schema:
        problems.append("empty output_schema")
    if spec.implemented and spec.func is None:
        problems.append("implemented but func is None")
    return CheckResult("meta", not problems, "; ".join(problems) or "ok")


def _check_gate(spec: MethodSpec) -> CheckResult:
    if not spec.implemented or spec.min_n <= 0:
        return CheckResult("gate", True, "skip (min_n=0)", skipped=True, skip_kind="not_applicable")
    try:
        out = run(spec.method_id, _empty_data(spec))
    except Exception as exc:  # 空输入不应抛异常
        return CheckResult("gate", False, f"raised {type(exc).__name__}: {exc}")
    ok = out.get("gate") == "insufficient_samples"
    return CheckResult("gate", ok, f"gate={out.get('gate')}")


def _check_determinism(spec: MethodSpec, seed: int) -> CheckResult:
    case = _synthetic_case(spec, seed)
    if case is None:
        return CheckResult("determinism", True, "skip (no case)", skipped=True, skip_kind="missing")
    try:
        a = run(spec.method_id, case["data"], **case.get("params", {}))
        b = run(spec.method_id, case["data"], **case.get("params", {}))
    except Exception as exc:
        return CheckResult("determinism", False, f"raised {type(exc).__name__}: {exc}")
    same = json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    return CheckResult("determinism", same, "identical" if same else "diff between runs")


def _check_synthetic(spec: MethodSpec) -> CheckResult:
    if spec.checks.synthetic is None:
        return CheckResult("synthetic", True, "skip (none)", skipped=True, skip_kind="missing")
    case = spec.checks.synthetic()
    try:
        out = run(spec.method_id, case["data"], **case.get("params", {}))
    except Exception as exc:
        return CheckResult("synthetic", False, f"raised {type(exc).__name__}: {exc}")
    misses = []
    for path, expect in case.get("expect", {}).items():
        actual = _resolve(out, path)
        if actual is _MISSING or not _close(actual, expect):
            misses.append(f"{path}: expect={expect!r} actual={actual!r}")
    return CheckResult("synthetic", not misses, "; ".join(misses) or "all expectations hit")


def _check_null(spec: MethodSpec, seed: int, trials: int) -> CheckResult:
    if not spec.implemented or spec.checks.null != "no_correlation":
        return CheckResult(
            "null", True, "skip (no null test)", skipped=True, skip_kind="not_applicable"
        )
    rng = random.Random(seed)
    significant = 0
    abs_r_sum = 0.0
    used = 0
    for _ in range(trials):
        xs = [rng.gauss(0, 1) for _ in range(120)]
        ys = [rng.gauss(0, 1) for _ in range(120)]
        try:
            out = run(spec.method_id, {"x": xs, "y": ys})
        except Exception as exc:
            return CheckResult("null", False, f"raised {type(exc).__name__}: {exc}")
        res = out.get("result") or {}
        ps = _p_values(res)
        if ps is None:
            return CheckResult("null", True, "skip (no p value)", skipped=True, skip_kind="missing")
        used += 1
        if len(ps) == 1:
            significant += int(ps[0] <= 0.05)
            abs_r_sum += abs(float(res.get("r", 0.0)))
        else:
            significant += int(min(ps) <= 0.05 / len(ps))  # Bonferroni 粗判即可
    rate = significant / used if used else 0.0
    mean_abs_r = abs_r_sum / used if used and abs_r_sum else None
    ok = rate <= 0.20 and (mean_abs_r is None or mean_abs_r <= 0.15)
    return CheckResult(
        "null",
        ok,
        f"false_positive_rate={rate:.3f} mean_abs_r={mean_abs_r if mean_abs_r is None else round(mean_abs_r, 4)} trials={used}",
    )


def _check_reference(spec: MethodSpec) -> CheckResult:
    ref = spec.checks.reference
    if ref is None:
        return CheckResult(
            "reference", True, "skip (none)", skipped=True, skip_kind="not_applicable"
        )
    case = _synthetic_case(spec, seed=0)
    if case is None:
        return CheckResult("reference", True, "skip (no case)", skipped=True, skip_kind="missing")
    try:
        expected = ref(case["data"])
    except ImportError:
        return CheckResult(
            "reference",
            True,
            "skip (reference lib missing)",
            skipped=True,
            skip_kind="missing",
        )
    except Exception as exc:
        return CheckResult("reference", False, f"reference raised {type(exc).__name__}: {exc}")
    actual = run(spec.method_id, case["data"], **case.get("params", {}))
    misses = [
        f"{k}: expect={v} actual={_resolve(actual, k)}"
        for k, v in expected.items()
        if not _close(_resolve(actual, k), v)
    ]
    return CheckResult("reference", not misses, "; ".join(misses) or "matches reference")


def audit(
    method_ids: Optional[Sequence[str]] = None,
    *,
    seed: int = 20261114,
    null_trials: int = 100,
    scope: str = "core",
) -> Dict[str, Any]:
    """执行方法评估，返回机器可读报告。scope: core / research / all。"""
    specs = [get(m) for m in method_ids] if method_ids else all_specs(implemented=True, scope=scope)
    reports: List[MethodReport] = []
    for spec in specs:
        item = MethodReport(spec.method_id, spec.name, spec.implemented)
        item.checks = [
            _check_meta(spec),
            _check_gate(spec),
            _check_determinism(spec, seed),
            _check_synthetic(spec),
            _check_null(spec, seed, null_trials),
            _check_reference(spec),
        ]
        reports.append(item)

    implemented = [r for r in reports if r.implemented]
    passed = [r for r in implemented if r.passed]
    failed = [r for r in implemented if not r.passed]
    all_checks = [check for report in implemented for check in report.checks]
    check_names = ("meta", "gate", "determinism", "synthetic", "null", "reference")
    check_coverage = {
        name: _coverage([check for check in all_checks if check.name == name])
        for name in check_names
    }
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "seed": seed,
        "null_trials": null_trials,
        "summary": {
            "implemented": len(implemented),
            "passed": len(passed),
            "failed": len(failed),
            "catalog_total": len(all_specs(scope="core")),
            "research_catalog_total": len(all_specs(scope="research")),
            "registered_total": len(REGISTRY),
            "coverage": _coverage(all_checks),
            "checks": check_coverage,
        },
        "failed": [r.method_id for r in failed],
        "methods": [r.to_dict() for r in reports],
    }
