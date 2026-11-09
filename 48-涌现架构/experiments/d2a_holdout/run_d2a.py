#!/usr/bin/env python3
"""D2-A 架构复原 holdout 编排器（SPEC-EMERGENCE-3D v0.4 §4.1）。

流程：载入统一图 → 选模块 → 逐模块建快照/exclusion_manifest → 四重泄漏审计
      → 跑基线（B0/B1）→（可选）跑系统预测器 → 评估 M-D2-EDGE-F1
      → 模块级配对聚类 bootstrap → 四态判定 → 落盘 8 件产物。

默认 run_class=exploratory：人工复核 3-5 个 holdout 模块前不得产出正式 candidate。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))  # 48-涌现架构 根

from experiments.d2a_holdout import baselines, evaluate, holdout, leak_audit  # noqa: E402

REPO_ROOT = HERE.parents[2]
DEFAULT_GRAPH = (
    REPO_ROOT / "48-涌现架构/baselines/artifacts/d2_architecture_graph/architecture_graph.json"
)
DEFAULT_OUT = HERE / "results"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _corpus_paths(root: Path, snapshot: dict) -> list[Path]:
    """输入语料 = 快照中保留的 python/markdown 文件（即检索可用范围）。"""
    out = []
    for n in snapshot.get("kept_nodes", []):
        if n["type"] in ("python_file", "markdown_doc"):
            p = root / n["id"]
            if p.is_file():
                out.append(p)
    return out


def run_module(
    root: Path, graph: dict, mod: holdout.HoldoutModule, out_dir: Path, system_cmd: str | None
) -> dict:
    built = holdout.build_snapshot(graph, mod, salt=_git_commit())
    snap, manifest = built["snapshot"], built["exclusion_manifest"]
    mod_dir = out_dir / mod.module.replace("/", "_")
    mod_dir.mkdir(parents=True, exist_ok=True)

    # 产物：快照 + 排除清单
    (mod_dir / "data_snapshot.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (mod_dir / "exclusion_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    # 四重泄漏审计（语料 + 派生文档）
    audit = leak_audit.audit(root, manifest, _corpus_paths(root, snap))
    leak_audit.write_audit(audit, mod_dir / "leak_audit.json")
    if audit["contaminated"]:
        return {"module": mod.module, "status": "leak_audit_failed", "audit": audit}

    truth = baselines.ground_truth_set(manifest)
    base_preds = {
        "B0_doc_knn": baselines.normalize_predictions(baselines.predict_b0_doc_knn(root, snap)),
        "B1_bm25": baselines.normalize_predictions(baselines.predict_b1_bm25(root, snap)),
    }

    system_pred = None
    system_status = "not_provided"
    if system_cmd:
        system_pred, system_status = _run_system(system_cmd, snap, manifest, mod_dir)

    scores = evaluate.evaluate_module(system_pred, base_preds, truth)
    return {
        "module": mod.module,
        "status": "ok",
        "canary": manifest["canary"],
        "ground_truth_count": len(truth),
        "predictions": {name: sorted(list(p) for p in preds) for name, preds in base_preds.items()},
        "system_status": system_status,
        "scores": scores,
        "audit_verdict": audit["verdict"],
    }


def _run_system(cmd: str, snap: dict, manifest: dict, mod_dir: Path):
    """调用外部系统预测器（33-REA 复原管道），约定 stdin 快照 / stdout 边 JSONL。"""
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            input=json.dumps(snap, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.SubprocessError as exc:
        return None, f"error: {type(exc).__name__}"
    if proc.returncode != 0:
        return None, f"nonzero_exit:{proc.returncode}"
    preds = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if {"src", "dst", "kind"} <= set(e):
            preds.add((e["src"], e["dst"], e["kind"]))
    (mod_dir / "system_predictions.jsonl").write_text(
        "".join(
            json.dumps({"src": s, "dst": d, "kind": k}, ensure_ascii=False) + "\n"
            for s, d, k in sorted(preds)
        ),
        encoding="utf-8",
    )
    return preds, "ok"


def run(
    graph_path: Path,
    out_root: Path,
    max_modules: int,
    run_class: str,
    system_cmd: str | None,
    root: Path = REPO_ROOT,
) -> dict:
    graph = holdout.load_graph(graph_path)
    candidates, rejected = holdout.select_modules(graph)
    run_id = holdout.new_run_id()
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # 泄漏审计不通过则顺延下一候选；最多尝试 max_modules*3 个
    results: list[dict] = []
    modules_run: list[holdout.HoldoutModule] = []
    skipped: list[dict] = []
    for cand in candidates:
        ok_count = sum(1 for r in results if r["status"] == "ok")
        if ok_count >= max_modules or len(results) + len(skipped) >= max_modules * 3:
            break
        r = run_module(root, graph, cand, out_dir, system_cmd)
        if r["status"] != "ok":
            skipped.append(
                {
                    "module": cand.module,
                    "reason": r["status"],
                    "audit_findings": len((r.get("audit") or {}).get("findings", [])),
                }
            )
            continue
        results.append(r)
        modules_run.append(cand)

    per_module: dict[str, dict] = {}
    for r in results:
        if r["status"] != "ok" or r["scores"]["system"] is None:
            continue
        per_module[r["module"]] = {
            f"{evaluate.PRIMARY_METRIC}_system": r["scores"]["system"]["f1"],
            f"{evaluate.PRIMARY_METRIC}_baseline": r["scores"]["best_baseline_f1"],
        }

    has_system = bool(per_module)
    deltas = evaluate.per_module_delta(per_module)
    ci = evaluate.cluster_bootstrap_ci(deltas)

    if has_system:
        decision = evaluate.decide(ci, len(per_module))
    else:
        decision = {
            "verdict": "not_run",
            "reason": "未提供系统预测器（--system-cmd），仅完成基线与泄漏审计",
        }
    # 探索性运行不得产出 candidate
    if run_class != "formal" and decision["verdict"] == "candidate":
        decision = {
            "verdict": "inconclusive",
            "reason": "run_class=exploratory：holdout 模块未经人工复核，禁止产出正式 candidate；"
            + decision["reason"],
        }

    evaluation = {
        "run_id": run_id,
        "run_class": run_class,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "graph": {
            "path": str(graph_path.relative_to(root)),
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
        },
        "primary_metric": evaluate.PRIMARY_METRIC,
        "modules_selected": [m.to_dict() for m in modules_run],
        "modules_skipped": skipped,
        "modules_rejected_sample": rejected[:20],
        "module_results": [
            {
                "module": r["module"],
                "status": r["status"],
                "system_status": r.get("system_status"),
                "audit_verdict": r.get("audit_verdict"),
                "ground_truth_count": r.get("ground_truth_count"),
                "scores": r.get("scores"),
            }
            for r in results
        ],
        "paired": {"per_module": per_module, "deltas": deltas},
        "bootstrap": ci,
        "decision": decision,
    }
    (out_dir / "evaluation.json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            if r["status"] != "ok":
                continue
            for name, preds in r["predictions"].items():
                for p in preds:
                    fh.write(
                        json.dumps(
                            {
                                "module": r["module"],
                                "predictor": name,
                                "src": p[0],
                                "dst": p[1],
                                "kind": p[2],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

    (out_dir / "limitation.md").write_text(
        _limitation(run_class, bool(system_cmd)), encoding="utf-8"
    )
    (out_dir / "prereg.json").write_text(
        json.dumps(_prereg(max_modules, run_class), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    return evaluation


def _prereg(max_modules: int, run_class: str) -> dict:
    return {
        "spec": "SPEC-EMERGENCE-3D v0.4 §4.1",
        "hypothesis": "H2A：扣留模块后从其余证据重建其接口/依赖，M-D2-EDGE-F1 显著高于最佳检索基线",
        "experiment_unit": "module",
        "min_modules": 5,
        "planned_modules": max_modules,
        "runs_per_module": 3,
        "primary_metric": evaluate.PRIMARY_METRIC,
        "baselines": ["B0_doc_knn", "B1_bm25"],
        "bootstrap": {"unit": "module", "iterations": 10_000, "alpha": 0.05, "seed": 42},
        "decision_rule": {
            "candidate": "CI_low > 0 且盲评 ≥4/5",
            "falsified": "CI_high ≤ 0 或 >80% 复述或盲评 <3/5",
            "inconclusive": "CI 跨 0",
            "insufficient_data": "模块数 < 5",
        },
        "run_class": run_class,
        "freeze": "参数与判定规则一经运行不得更改；改动须新 run_id",
    }


def _limitation(run_class: str, has_system: bool) -> str:
    lines = [
        "# D2-A 局限性说明",
        "",
        f"- `run_class` = {run_class}",
        "- 主指标 ground truth 只取模块级 **import** 边；call 边为函数名级解析"
        "（重名取路径首个），实测大量为重名假依赖，按 §4.1 口径公平性排除。",
        "- 其他文件的源码文本中仍保留对这些模块的 import 语句（合法线索），"
        "因此 import 边理论上可被 AST/文本解析复原；B0/B1 是不解析语法的检索基线，故分数偏低。",
        "- 基线 B0/B1 为确定性检索，3 次 seed 结果一致，seed 重复不提供额外方差信息。",
    ]
    if not has_system:
        lines.append("- **未提供系统预测器**：本轮仅产出基线与泄漏审计，判定为 `not_run`。")
    if run_class != "formal":
        lines.append("- **探索性运行**：holdout 模块未经人工复核 3-5 例，禁止产出正式 candidate。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D2-A 架构复原 holdout 实验")
    ap.add_argument("--graph", default=str(DEFAULT_GRAPH))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--max-modules", type=int, default=5)
    ap.add_argument("--run-class", choices=["exploratory", "formal"], default="exploratory")
    ap.add_argument("--system-cmd", default=None, help="外部系统预测器命令（stdin=快照 JSON）")
    args = ap.parse_args(argv)
    ev = run(Path(args.graph), Path(args.out), args.max_modules, args.run_class, args.system_cmd)
    print(
        f"[d2a] run_id={ev['run_id']} modules={len(ev['modules_selected'])} "
        f"verdict={ev['decision']['verdict']} "
        f"ci={ev['bootstrap']['ci_low']}..{ev['bootstrap']['ci_high']}"
    )
    return 0 if ev["decision"]["verdict"] not in ("leak_audit_failed",) else 1


if __name__ == "__main__":
    sys.exit(main())
