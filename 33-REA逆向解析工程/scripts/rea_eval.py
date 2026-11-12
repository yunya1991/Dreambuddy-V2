#!/usr/bin/env python3
"""SPEC-33-F T-F03 评测 harness：golden queries → recall@k / precision / 证据存活率 / 预算命中率。

用法：
    python3 scripts/rea_eval.py --target 3.1-FRONTEND --queries tests/eval/golden_queries.yaml

设计约束（SPEC-F §4）：
  - 纯本地确定性执行，不依赖网络与 LLM；
  - 直接调用 S33_rea_trace（与 MCP 同一实现），不复制排序逻辑；
  - 报告同时给出逐条明细与汇总，便于定位是哪条 query 退化了排序。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

DEFAULT_QUERIES = _REA_ROOT / "tests" / "eval" / "golden_queries.yaml"
DEFAULT_TARGET = _REA_ROOT.parent / "3.1-FRONTEND"
DEFAULT_BUDGET = 8192
DEFAULT_K = 10

RECALL_THRESHOLD = 0.80
BUDGET_HIT_THRESHOLD = 1.0


@dataclass
class QueryResult:
    id: str
    feature: str
    expected: list[str]
    ranked: list[str]
    recall: float
    precision: float
    evidence_survival: float
    budget_hit: bool
    output_bytes: int
    trimmed: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "feature": self.feature,
            "expected": self.expected,
            "ranked_top_k": self.ranked,
            "recall": round(self.recall, 4),
            "precision": round(self.precision, 4),
            "evidence_survival": round(self.evidence_survival, 4),
            "budget_hit": self.budget_hit,
            "output_bytes": self.output_bytes,
            "trimmed": self.trimmed,
        }


def load_golden(path: Path | str) -> list[dict[str, Any]]:
    """读取 golden_queries.yaml（失败时回退 JSON）。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except ImportError:  # pragma: no cover - 环境无 pyyaml 时走 JSON
        data = json.loads(text)
    queries = (data or {}).get("queries") or []
    return list(queries)


def _norm(path: str) -> str:
    return str(path).strip().replace("\\", "/").lstrip("./")


def compute_recall(expected: Iterable[str], ranked: Iterable[str], k: int) -> float:
    expected_set = {_norm(p) for p in expected}
    if not expected_set:
        return 1.0
    hit = expected_set & {_norm(p) for p in list(ranked)[:k]}
    return len(hit) / len(expected_set)


def compute_precision(expected: Iterable[str], ranked: Iterable[str], k: int) -> float:
    expected_set = {_norm(p) for p in expected}
    top = list(ranked)[:k]
    if not top:
        return 0.0
    hit = expected_set & {_norm(p) for p in top}
    return len(hit) / len(top)


def _evidence_survival(result: dict[str, Any]) -> float:
    kept = len(result.get("evidence") or [])
    trimmed = ((result.get("trimmed") or {}).get("evidence") or {}).get("total")
    total = int(trimmed) if trimmed else kept
    if total <= 0:
        return 1.0
    return kept / total


def evaluate(
    queries: list[dict[str, Any]],
    trace_fn: Callable[[dict[str, Any]], dict[str, Any]],
    budget_bytes: int = DEFAULT_BUDGET,
    k: int = DEFAULT_K,
    target: str | None = None,
) -> dict[str, Any]:
    """对每个 query 跑 trace 并汇总指标。trace_fn 便于测试注入。"""
    details: list[QueryResult] = []
    for query in queries:
        params: dict[str, Any] = {
            "feature": query["feature"],
            "budget_bytes": budget_bytes,
            "trace_id": f"eval-{query['id']}",
        }
        if target:
            params["target"] = target
        params.update(query.get("params") or {})
        out = trace_fn(params)
        if not out.get("ok"):
            raise RuntimeError(f"query {query['id']} trace failed: {out.get('error')}")
        result = out.get("result") or {}
        ranked = [item["module"] for item in (result.get("ranked_nodes") or [])]
        expected = list(query.get("expected") or [])
        output_bytes = len(json.dumps(out, ensure_ascii=False).encode("utf-8"))
        details.append(
            QueryResult(
                id=str(query["id"]),
                feature=str(query["feature"]),
                expected=expected,
                ranked=ranked[:k],
                recall=compute_recall(expected, ranked, k),
                precision=compute_precision(expected, ranked, k),
                evidence_survival=_evidence_survival(result),
                budget_hit=output_bytes <= budget_bytes,
                output_bytes=output_bytes,
                trimmed=result.get("trimmed") or {},
            )
        )

    count = len(details) or 1
    summary = {
        "queries": len(details),
        "k": k,
        "budget_bytes": budget_bytes,
        "recall_at_k": round(sum(d.recall for d in details) / count, 4),
        "precision_at_k": round(sum(d.precision for d in details) / count, 4),
        "evidence_survival_rate": round(sum(d.evidence_survival for d in details) / count, 4),
        "evidence_min_ok": all(d.evidence_survival > 0.0 for d in details),
        "budget_hit_rate": round(sum(1.0 for d in details if d.budget_hit) / count, 4),
        "thresholds": {
            "recall_at_k": RECALL_THRESHOLD,
            "precision_at_k": "观测值（golden 只标注期望文件，不含上下文邻居，不做门禁）",
            "budget_hit_rate": BUDGET_HIT_THRESHOLD,
            "evidence_survival_rate": "观测值（不设门禁，但每条 query 至少保留 1 条 evidence）",
        },
    }
    summary["pass"] = bool(
        summary["recall_at_k"] >= RECALL_THRESHOLD
        and summary["evidence_min_ok"]
        and summary["budget_hit_rate"] >= BUDGET_HIT_THRESHOLD
    )
    return {"summary": summary, "details": [d.to_dict() for d in details]}


def _default_trace_fn(params: dict[str, Any]) -> dict[str, Any]:
    import dsh_nodes

    return dsh_nodes.S33_rea_trace(params)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REA golden query 评测 harness")
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--target", default=str(DEFAULT_TARGET))
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试用）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON，不打印摘要")
    args = parser.parse_args(argv)

    queries = load_golden(args.queries)
    if args.limit > 0:
        queries = queries[: args.limit]
    if not queries:
        print("no golden queries found", file=sys.stderr)
        return 2

    report = evaluate(
        queries,
        _default_trace_fn,
        budget_bytes=args.budget,
        k=args.k,
        target=args.target,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.json:
        s = report["summary"]
        print(
            f"\nrecall@{s['k']}={s['recall_at_k']:.3f} "
            f"precision@{s['k']}={s['precision_at_k']:.3f} "
            f"evidence_survival={s['evidence_survival_rate']:.3f} "
            f"budget_hit={s['budget_hit_rate']:.3f} "
            f"pass={s['pass']}",
            file=sys.stderr,
        )
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
