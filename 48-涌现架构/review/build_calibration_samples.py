"""P1-6 校准集构建：从 D2-A 预测与 D3-A 意图事件中分层抽样 ≥200 条。

冻结样本集 + manifest（sha256），供两位独立标注员（Agent A/B）双盲标注。

分层策略：
  - D2（架构缺口预测边）：按「是否在架构图中」+ 模块对类型分层
  - D3（意图预测）：按 intent_label_confidence 三分位分层（high/medium/low）

输出：
  - review/samples_to_annotate.jsonl  （冻结样本，仅含 input/ai_output/stratum，不含标注）
  - review/samples_manifest.json       （sha256 + 抽样参数 + 计数）
"""

from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
D2_GLOB = str(ROOT / "experiments/d2a_holdout/results/D2A-*/predictions.jsonl")
D3_PATH = ROOT / "baselines/artifacts/d3_intent_events/intent_events.jsonl"
GRAPH_PATH = ROOT / "baselines/artifacts/d2_architecture_graph/architecture_graph.json"
OUT_JSONL = Path(__file__).resolve().parent / "samples_to_annotate.jsonl"
OUT_MANIFEST = Path(__file__).resolve().parent / "samples_manifest.json"

D2_TARGET = 120
D3_TARGET = 120


def _load_graph_edges() -> set:
    """加载架构图中已存在的 import 边集合 (src, dst)。"""
    if not GRAPH_PATH.exists():
        return set()
    g = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    edges = set()
    for e in g.get("edges", []):
        if e.get("kind") == "import":
            edges.add((e.get("src"), e.get("dst")))
    return edges


def build_d2_samples(graph_edges: set) -> List[Dict[str, Any]]:
    """D2 分层抽样：按 edge_in_graph / cross_module 分层。"""
    raw: List[Dict[str, Any]] = []
    for path in glob.glob(D2_GLOB):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            raw.append(rec)
    # 去重 (src, dst)
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for r in raw:
        key = (r["src"], r["dst"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    # 分层
    in_graph = [r for r in uniq if (r["src"], r["dst"]) in graph_edges]
    cross_module = [
        r
        for r in uniq
        if (r["src"], r["dst"]) not in graph_edges
        and r["src"].split("/")[0] != r["dst"].split("/")[0]
    ]
    same_module = [
        r
        for r in uniq
        if (r["src"], r["dst"]) not in graph_edges
        and r["src"].split("/")[0] == r["dst"].split("/")[0]
    ]

    # 好=在图中, 中=同模块未在图, 差=跨模块未在图；各取 40
    def take(pool: List[Dict[str, Any]], n: int, stratum: str) -> List[Dict[str, Any]]:
        out = []
        for i, r in enumerate(pool[:n]):
            out.append(
                {
                    "sample_id": f"D2-{stratum[:1].upper()}{i+1:03d}",
                    "experiment": "D2-A",
                    "stratum": stratum,
                    "input": f"模块 {r['dst']} 的架构缺口检测输入",
                    "ai_output": (
                        f"预测依赖边: {r['src']} -> {r['dst']} (kind={r['kind']}, "
                        f"predictor={r.get('predictor','?')})"
                    ),
                    "context": {
                        "src": r["src"],
                        "dst": r["dst"],
                        "kind": r["kind"],
                        "in_graph": (r["src"], r["dst"]) in graph_edges,
                        "cross_module": r["src"].split("/")[0] != r["dst"].split("/")[0],
                    },
                }
            )
        return out

    samples = (
        take(in_graph, 40, "good")
        + take(same_module, 40, "medium")
        + take(cross_module, 40, "poor")
    )
    # 若某层不足，从其他层补足
    if len(samples) < D2_TARGET:
        extra_pool = [r for r in uniq if (r["src"], r["dst"]) not in graph_edges]
        existing_ids = {s["sample_id"] for s in samples}
        i = 0
        while len(samples) < D2_TARGET and i < len(extra_pool):
            r = extra_pool[i]
            sid = f"D2-X{i+1:03d}"
            if sid not in existing_ids:
                samples.append(
                    {
                        "sample_id": sid,
                        "experiment": "D2-A",
                        "stratum": "medium",
                        "input": f"模块 {r['dst']} 的架构缺口检测输入",
                        "ai_output": f"预测依赖边: {r['src']} -> {r['dst']} (kind={r['kind']})",
                        "context": {"src": r["src"], "dst": r["dst"], "kind": r["kind"]},
                    }
                )
            i += 1
    return samples[:D2_TARGET]


def build_d3_samples() -> List[Dict[str, Any]]:
    """D3 分层抽样：按 intent_label_confidence 三分位。"""
    recs = [json.loads(line) for line in open(D3_PATH, encoding="utf-8") if line.strip()]
    recs.sort(key=lambda r: r.get("intent_label_confidence", 0))
    n = len(recs)
    # 三分位
    lo = recs[: n // 3]
    mid = recs[n // 3 : 2 * n // 3]
    hi = recs[2 * n // 3 :]

    def take(pool: List[Dict[str, Any]], n_take: int, stratum: str) -> List[Dict[str, Any]]:
        out = []
        for i, r in enumerate(pool[:n_take]):
            label = r.get("intent_label", "?")
            traj = r.get("intent_trajectory", [])
            traj_str = " -> ".join(str(t) for t in traj[:5]) if traj else "n/a"
            out.append(
                {
                    "sample_id": f"D3-{stratum[:1].upper()}{i+1:03d}",
                    "experiment": "D3-A",
                    "stratum": stratum,
                    "input": (
                        f"会话 task_type={r.get('task_type_transitions', [{}])[0].get('from','?') if r.get('task_type_transitions') else '?'}, "
                        f"action_count={r.get('action_count',0)}"
                    ),
                    "ai_output": (
                        f"预测意图: {label} (confidence={r.get('intent_label_confidence',0):.3f}, "
                        f"stable={r.get('intent_stable')}, trajectory=[{traj_str}])"
                    ),
                    "context": {
                        "intent_label": label,
                        "confidence": r.get("intent_label_confidence", 0),
                        "stable": r.get("intent_stable"),
                        "trajectory_len": len(r.get("intent_trajectory", [])),
                    },
                }
            )
        return out

    return take(lo, 40, "poor") + take(mid, 40, "medium") + take(hi, 40, "good")


def main() -> None:
    graph_edges = _load_graph_edges()
    d2 = build_d2_samples(graph_edges)
    d3 = build_d3_samples()
    all_samples = d2 + d3
    # 打乱顺序（消除分层聚集偏差），但保持 D2/D3 内部结构
    import random

    random.seed(42)
    shuffled = all_samples.copy()
    random.shuffle(shuffled)

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for s in shuffled:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # manifest with sha256 of the jsonl
    h = hashlib.sha256()
    with open(OUT_JSONL, "rb") as f:
        h.update(f.read())
    manifest = {
        "generated_at": "2026-11-09",
        "sample_count": len(shuffled),
        "d2_count": len(d2),
        "d3_count": len(d3),
        "stratum_counts": {
            "good": sum(1 for s in shuffled if s["stratum"] == "good"),
            "medium": sum(1 for s in shuffled if s["stratum"] == "medium"),
            "poor": sum(1 for s in shuffled if s["stratum"] == "poor"),
        },
        "sha256": h.hexdigest(),
        "stratification": {
            "D2": "edge_in_graph(good)/same_module_not_in_graph(medium)/cross_module_not_in_graph(poor)",
            "D3": "intent_label_confidence terciles: hi(good)/mid(medium)/lo(poor)",
        },
        "seed": 42,
    }
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[samples] wrote {len(shuffled)} samples to {OUT_JSONL.name}")
    print(f"[samples] D2={len(d2)}, D3={len(d3)}")
    print(f"[samples] strata: {manifest['stratum_counts']}")
    print(f"[samples] sha256: {h.hexdigest()[:16]}...")


if __name__ == "__main__":
    main()
