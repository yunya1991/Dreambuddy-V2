"""SPEC-33-F T-F03 评测 harness 测试（RED）：golden 语料完整性 + 指标口径 + 端到端可跑。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

_EVAL_PATH = _REA_ROOT / "scripts" / "rea_eval.py"
_spec = importlib.util.spec_from_file_location("rea_eval", _EVAL_PATH)
assert _spec and _spec.loader
rea_eval = importlib.util.module_from_spec(_spec)
sys.modules["rea_eval"] = rea_eval
_spec.loader.exec_module(rea_eval)

GOLDEN = _REA_ROOT / "tests" / "eval" / "golden_queries.yaml"
FRONTEND = _REA_ROOT.parent / "3.1-FRONTEND"


def test_golden_queries_integrity() -> None:
    queries = rea_eval.load_golden(GOLDEN)
    assert len(queries) >= 30, len(queries)
    ids = [q["id"] for q in queries]
    assert len(ids) == len(set(ids)), "query id 必须唯一"
    for query in queries:
        assert query["feature"].strip()
        assert query["expected"], query
        for rel in query["expected"]:
            assert (FRONTEND / rel).is_file(), f"{query['id']} 期望文件不存在: {rel}"


def test_metric_math() -> None:
    assert rea_eval.compute_recall(["a.ts"], ["a.ts", "b.ts"], 10) == 1.0
    assert rea_eval.compute_recall(["a.ts"], ["x.ts", "b.ts"], 10) == 0.0
    assert rea_eval.compute_recall(["a.ts", "b.ts"], ["b.ts"], 10) == 0.5
    assert rea_eval.compute_recall([], [], 10) == 1.0
    assert rea_eval.compute_precision(["a.ts"], ["a.ts", "b.ts"], 10) == 0.5
    assert rea_eval.compute_precision(["a.ts"], [], 10) == 0.0


def _fake_trace(params):
    if params["feature"] == "good":
        return {
            "ok": True,
            "result": {
                "ranked_nodes": [{"module": "src/good.ts", "score": 1.0, "hop": 0}],
                "evidence": [{"result": "x", "level": "derivation"}],
            },
        }
    return {
        "ok": True,
        "result": {
            "ranked_nodes": [{"module": "src/other.ts", "score": 1.0, "hop": 0}],
            "evidence": [{"result": "x", "level": "derivation"}],
            "trimmed": {"evidence": {"kept": 1, "total": 2}},
        },
    }


def test_evaluate_summary() -> None:
    queries = [
        {"id": "A", "feature": "good", "expected": ["src/good.ts"]},
        {"id": "B", "feature": "bad", "expected": ["src/missing.ts"]},
    ]
    report = rea_eval.evaluate(queries, _fake_trace, budget_bytes=4096, k=10)
    summary = report["summary"]
    assert summary["queries"] == 2
    assert summary["recall_at_k"] == 0.5
    assert summary["budget_hit_rate"] == 1.0
    assert summary["evidence_survival_rate"] == 0.75
    assert summary["pass"] is False  # recall 0.5 < 0.8


def test_e2e_real_trace_limit_3() -> None:
    queries = rea_eval.load_golden(GOLDEN)[:3]
    report = rea_eval.evaluate(
        queries,
        rea_eval._default_trace_fn,
        budget_bytes=8192,
        k=10,
        target=str(FRONTEND),
    )
    assert report["summary"]["queries"] == 3
    assert report["summary"]["recall_at_k"] >= 0.8
    assert report["summary"]["budget_hit_rate"] == 1.0
    for detail in report["details"]:
        assert detail["output_bytes"] <= 8192
        assert json.dumps(detail, ensure_ascii=False)  # 可序列化
