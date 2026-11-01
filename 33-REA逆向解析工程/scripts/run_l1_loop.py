# L1 无大模型闭环运行 — SPEC-33 输出场景全链路（零 LLM）
# 链路: spec_draft → Spec增强(Q1/Q2) → 节点执行记录回流 → 最优路径评估(Q3/Q4)
#       → 训练案例入库(Q6) → 做梦评估(P2)
import json
import os
import sys
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.reflection.recorder import AnalysisRecorder
from core.reflection.replay_simulator import ReplayPool
from core.reflection.training_cases import TrainingCaseGenerator, TrainingCaseStore
from core.reflection.dreaming import DreamingLoop
from dsh_nodes import DSH_NODE_REGISTRY

POOL_DIR = os.path.join(_PROJECT_ROOT, "reflection_data", "replay_pool")
STORE_PATH = os.path.join(_PROJECT_ROOT, "reflection_data", "training_cases.jsonl")


def log(stage, msg):
    print("[L1][%s] %s" % (stage, msg), flush=True)


def main():
    t0 = time.time()
    log("BOOT", "L1 闭环启动 pool=%s" % POOL_DIR)

    # ---- 阶段1: Spec 增强 (Q1/Q2) ----
    spec_draft = (
        "# Spec 草案: L1 闭环自检模块\n"
        "## 目标\n"
        "验证无大模型闭环全链路: Spec增强→节点执行→路径评估→案例入库→做梦评估。\n"
        "## 验收标准\n"
        "1. 全链路零 LLM 调用\n"
        "2. 每阶段产物带证据引用\n"
    )
    out1 = DSH_NODE_REGISTRY["s33_rea_spec_enhance"]({"spec_draft": spec_draft})
    r1 = out1.get("result") or {}
    stats1 = r1.get("evidence_pack_stats") or {}
    qg = r1.get("quality_gate") or {}
    log("SPEC_ENHANCE", "ok=%s matched_trees=%s design_decisions=%s arch_patterns=%s llm_calls=%s" % (
        out1.get("ok"), stats1.get("matched_trees"), stats1.get("design_decisions"),
        stats1.get("architecture_patterns"), stats1.get("llm_calls_segment1")))
    log("SPEC_ENHANCE", "quality_gate passed=%s poe_score=%s constraints=%s" % (
        qg.get("passed"), qg.get("poe_score"), qg.get("constraint_count")))
    if stats1.get("matched_trees", 0) == 0:
        log("SPEC_ENHANCE", "external 池为空 → FAIL-OPEN 降级(不阻断), 符合冷启动预期")

    # ---- 阶段2: 节点执行 + 记录器回流 ----
    recorder = AnalysisRecorder(pool_dir=POOL_DIR)
    ok = recorder.begin({"target": "33-REA逆向解析工程", "task_type": "l1_loop",
                         "feature": "L1 无大模型闭环自检"})
    log("RECORD", "begin=%s" % ok)
    steps = [
        ("acceptance_gate", {"skill": "dream-acceptance-verify"}, 0.8),
        ("code_commit", {"commit": "l1loop001"}, 0.8),
        ("doc_sync", {"scope": "README+INDEX"}, 0.8),
        ("cognitive_record", {"vm": "L1-LOOP"}, 0.8),
    ]
    for analyzer, params, poe in steps:
        rok = recorder.record(analyzer, params=params, poe_score=poe, cost_calls=1,
                              evidence_refs=[{"source": "l1_loop/self_check",
                                              "detail": "步骤 %s 自检 PASS" % analyzer}])
        log("RECORD", "record %s ok=%s poe=%.2f" % (analyzer, rok, poe))
    tree_id = recorder.commit()
    log("RECORD", "commit tree_id=%s → 回放池回流" % tree_id)

    pool = ReplayPool(POOL_DIR)
    log("POOL", "trees=%s" % pool.count())

    # ---- 阶段3: 最优路径评估 (Q3/Q4) ----
    completed_node = {"analyzer": "code_commit",
                      "acceptance": {"passed": True, "confidence": 0.85}}
    t2 = time.time()
    out2 = DSH_NODE_REGISTRY["s33_rea_optimal_path"]({"completed_node": completed_node})
    lat2 = (time.time() - t2) * 1000
    r2 = out2.get("result") or {}
    log("OPTIMAL_PATH", "light: layer=%s degraded=%s decision=%s candidates=%s latency=%.1fms budget=%sms" % (
        r2.get("layer"), r2.get("degraded"), r2.get("expected_decision"),
        len(r2.get("candidates") or []), lat2, r2.get("budget_ms")))
    for c in (r2.get("candidates") or [])[:3]:
        log("OPTIMAL_PATH", "cand: %s <- %s conf=%s" % (
            (c.get("strategy") or {}).get("action"),
            (c.get("evidence_ref") or {}).get("source"), c.get("confidence")))

    completed_node3 = {"analyzer": "doc_sync",
                       "acceptance": {"passed": False, "confidence": 0.4}}
    t3 = time.time()
    out3 = DSH_NODE_REGISTRY["s33_rea_optimal_path"](
        {"completed_node": completed_node3, "force_heavy": True})
    lat3 = (time.time() - t3) * 1000
    r3 = out3.get("result") or {}
    log("OPTIMAL_PATH", "heavy: layer=%s degraded=%s decision=%s candidates=%s latency=%.1fms" % (
        r3.get("layer"), r3.get("degraded"), r3.get("expected_decision"),
        len(r3.get("candidates") or []), lat3))

    # ---- 阶段4: 训练案例入库 (Q6) ----
    gen = TrainingCaseGenerator()
    store = TrainingCaseStore(STORE_PATH)
    before = len(store.load_all())
    case1 = gen.spec_enhance_case(
        spec_draft=spec_draft,
        enhanced_spec=json.dumps((r1.get("enhanced_spec") or {}).get("engineering_constraints") or [],
                                 ensure_ascii=False),
        okr_acceptance={"passed": bool(qg.get("passed")), "intent": "spec_enhance"},
        poe_score=float(qg.get("poe_score") or 0.0),
        evidence_refs=[{"source": "l1_loop/spec_enhance", "detail": "闭环自检"}],
    )
    id1 = store.save(case1)
    log("TRAIN_CASE", "spec_enhance case label=%s saved=%s gate_pass=%s" % (
        case1.label, id1, case1.passes_gate()))
    case2 = gen.optimal_path_case(
        node_context={"analyzer": "code_commit", "intent": "optimal_path"},
        candidate_strategies=r2.get("candidates") or [],
        chosen_decision={"expected_decision": r2.get("expected_decision")},
        execution_outcome={"as_expected": True, "poe_score": 0.8},
        v_value=0.0,
        evidence_refs=[{"source": "l1_loop/optimal_path", "detail": "闭环自检"}],
    )
    id2 = store.save(case2)
    log("TRAIN_CASE", "optimal_path case label=%s saved=%s gate_pass=%s" % (
        case2.label, id2, case2.passes_gate()))
    after = len(store.load_all())
    log("TRAIN_CASE", "store %s → %s (+%s)" % (before, after, after - before))
    log("TRAIN_CASE", "stats=%s" % json.dumps(store.stats(), ensure_ascii=False))

    # ---- 阶段5: 做梦评估 (P2) ----
    loop = DreamingLoop(pool)
    seq = [s[0] for s in steps]
    current = {"budget": {"max_calls": 10}, "parallelism": 1,
               "analyzer_sequence": seq, "transform": "current"}
    dream = loop.dream(current)
    log("DREAM", "current_v=%.4f best_v=%.4f improved=%s candidates=%s" % (
        dream.get("current_v", 0), dream.get("best_v", 0),
        dream.get("improved"), len(dream.get("candidates") or [])))

    # ---- 汇总 + 零 LLM 断言 ----
    elapsed = time.time() - t0
    assert stats1.get("llm_calls_segment1") == 0, "L1 违反零 LLM 不变量"
    assert out1.get("ok") and out2.get("ok") and out3.get("ok")
    assert tree_id, "记录器未回流回放池"
    assert after > before, "训练案例未入库"
    log("DONE", "L1 闭环完成 elapsed=%.1fs 零LLM=OK" % elapsed)
    print("L1_LOOP_OK")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="L1 loop (daemon supported)")
    ap.add_argument("--daemon", action="store_true", help="run as daemon")
    ap.add_argument("--interval", type=int, default=60, help="seconds between rounds")
    args = ap.parse_args()
    if args.daemon:
        log("DAEMON", "L1 daemon start interval=%ss" % args.interval)
        while True:
            try:
                main()
            except Exception as e:
                log("DAEMON", "round failed (keep alive): %s" % e)
            time.sleep(args.interval)
    else:
        sys.exit(main())
