#!/usr/bin/env python3
"""实验 E-C2（外部路径注入前后 V 值对比）+ E-A1 静态部分（Spec 增强前后约束质量对比）。"""
import json
import sys

sys.path.insert(0, ".")
from core.reflection.replay_simulator import ReplayPool
from core.reflection.dreaming import DreamingLoop
from core.reflection.output_scenarios import SpecEnhancer

pool = ReplayPool("reflection_data/replay_pool")

# ---------- E-C2：外部路径注入前后 V 值对比 ----------
# E-C2 修正：策略 = 从外部树（dlt）挖掘的真实动作序列（确定性重放需路径匹配）
ext_trees = pool.list_trees("external")
assert ext_trees, "no external trees in pool"
src_tree = next((t for t in ext_trees if t.source_label == "dlt"), ext_trees[0])
seq_actions = [
    n.action.get("analyzer", "")
    for n in src_tree.nodes
    if n.parent_id is not None and n.action.get("analyzer")
][:10]
strategy = {
    "analyzer_sequence": seq_actions,
    "budget": {"max_calls": 10},
    "parallelism": 2,
}
# 分层评估（E-C2 修复）：内部树抽样 + 外部树全量纳入，避免外部树被均匀抽样排除
loop = DreamingLoop(pool, max_trees=200)
result = loop.evaluate_strategy(strategy)
per_tree = [t for t in result["per_tree"] if t.get("provenance") == "internal"]
for tree in pool.list_trees("external"):
    r = loop.sim.replay(tree, strategy, loop.max_rounds)
    r["parallelism"] = 2
    from core.reflection.dreaming import replay_objective
    v = replay_objective(r, 10, loop.lam)
    r["v"] = v
    r["v_weighted"] = v * tree.weight
    r["tree_weight"] = tree.weight
    r["provenance"] = tree.provenance
    per_tree.append(r)

internal = [t for t in per_tree if t.get("provenance") == "internal"]
external = [t for t in per_tree if t.get("provenance") == "external"]

def weighted_avg(rows):
    if not rows:
        return 0.0
    total_w = sum(r.get("tree_weight", 1.0) for r in rows) or 1.0
    return sum(r.get("v_weighted", 0.0) for r in rows) / total_w

v_internal_only = weighted_avg(internal)
v_full_pool = weighted_avg(per_tree)
delta = v_full_pool - v_internal_only
improve_pct = (delta / v_internal_only * 100) if v_internal_only > 0 else None

print("==== E-C2 外部路径注入前后 V 值对比 ====")
print(f"策略: {strategy['analyzer_sequence']}")
print(f"内部树数={len(internal)} 外部树数={len(external)}")
print(f"V(仅内部, 注入前基线) = {v_internal_only:.6f}")
print(f"V(全池, 注入后)        = {v_full_pool:.6f}")
print(f"Delta_V = {delta:+.6f}" + (f" ({improve_pct:+.2f}%)" if improve_pct is not None else ""))
if external:
    ext_v = [r.get("v", 0.0) for r in external]
    print(f"外部树 V 值: min={min(ext_v):.4f} max={max(ext_v):.4f} avg={sum(ext_v)/len(ext_v):.4f}")

# ---------- E-A1 静态：Spec 增强前后约束质量对比 ----------
spec_draft = "为训练系统实现数据 pipeline 与 checkpoint 管理，python 实现"

enh_no_pool = SpecEnhancer(None)
base = enh_no_pool.enhance(spec_draft)
base_gate = base["quality_gate"]
base_stats = base["evidence_pack_stats"]

enh_with_pool = SpecEnhancer(pool)
enhanced = enh_with_pool.enhance(spec_draft)
enh_gate = enhanced["quality_gate"]
enh_stats = enhanced["evidence_pack_stats"]

print("==== E-A1 静态 Spec 增强前后约束质量对比 ====")
print(f"基线(无池): 约束={base_gate['constraint_count']} 证据引用率={base_gate['poe_score']:.2f} 门禁通过={base_gate['passed']} matched_trees={base_stats['matched_trees']}")
print(f"增强(有池): 约束={enh_gate['constraint_count']} 证据引用率={enh_gate['poe_score']:.2f} 门禁通过={enh_gate['passed']} matched_trees={enh_stats['matched_trees']}")

report = {
    "experiment": "E-C2 + E-A1-static",
    "ec2": {
        "strategy": strategy,
        "internal_trees": len(internal),
        "external_trees": len(external),
        "v_internal_only": round(v_internal_only, 6),
        "v_full_pool": round(v_full_pool, 6),
        "delta": round(delta, 6),
        "improve_pct": round(improve_pct, 2) if improve_pct is not None else None,
    },
    "ea1_static": {
        "base_constraints": base_gate["constraint_count"],
        "base_poe": base_gate["poe_score"],
        "base_passed": base_gate["passed"],
        "enh_constraints": enh_gate["constraint_count"],
        "enh_poe": enh_gate["poe_score"],
        "enh_passed": enh_gate["passed"],
        "matched_trees": enh_stats["matched_trees"],
    },
}
with open("reflection_data/experiment_ec2_ea1.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("REPORT_SAVED reflection_data/experiment_ec2_ea1.json")
print("E_EXPERIMENTS_DONE")
