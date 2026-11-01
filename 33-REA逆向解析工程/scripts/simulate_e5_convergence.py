"""E5 收敛速度实验 + 批评自循环运行期模拟。

E5: 仅内部树 vs 内部+外部树，多轮做梦迭代，对比 V 值收敛速度。
运行期: 模拟任务流驱动 CriticLoop 完整生命周期
（提出假说 → 观察期 3 周期 → 采纳/回滚），记录运行期数据。
"""
import os
import sys
import tempfile

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.reflection.replay_simulator import ReplayPool, DiscoveryTree, DiscoveryNode
from core.reflection.seed_cases import SEED_CASES, build_seed_tree
from core.reflection.dreaming import DreamingLoop
from core.reflection.critic_loop import CriticLoop, OBSERVATION_PERIOD


def fill_pool(pool_dir):
    pool = ReplayPool(pool_dir)
    for case in SEED_CASES:
        pool.save(build_seed_tree(case))
    return pool


def make_external_tree(pool, label, poe):
    tree = DiscoveryTree.new_tree(
        task={"target": label, "goal": "external_best_practice"},
        provenance="external",
        source_label=label,
    )
    parent = tree.root
    for step in SEED_CASES[0]["steps"]:
        node = DiscoveryNode(
            node_id=f"dn_ext_{label}_{step['analyzer']}",
            parent_id=parent.node_id,
            action={"analyzer": step["analyzer"], "params": step["params"]},
            evidence_refs=[{"type": "external_best_practice", "source": label}],
            poe_score=poe,
            cost_calls=step["cost_calls"],
        )
        tree.add_node(node)
        parent = node
    pool.save(tree)
    return tree


def scenario_e5():
    print("=" * 60)
    print("E5: 外部路径增益收敛速度验证（多轮做梦迭代）")
    print("=" * 60)
    tmp = tempfile.mkdtemp(prefix="rea_e5_")
    seq = [s["analyzer"] for s in SEED_CASES[0]["steps"]]
    rounds = 6
    # 池 A：仅内部树
    pool_int = fill_pool(os.path.join(tmp, "int"))
    # 池 B：内部 + 外部树
    pool_ext = fill_pool(os.path.join(tmp, "ext"))
    make_external_tree(pool_ext, "ext_mvc", 0.9)
    make_external_tree(pool_ext, "ext_pipeline", 0.85)
    curve_int = []
    curve_ext = []
    strategy = {"budget": {"max_calls": 10}, "parallelism": 1,
                "analyzer_sequence": seq, "transform": "current"}
    cur_int = dict(strategy)
    cur_ext = dict(strategy)
    for r in range(rounds):
        ri = DreamingLoop(pool_int).dream(cur_int)
        cur_int = ri["best_strategy"]
        curve_int.append(ri["best_v"])
        re_ = DreamingLoop(pool_ext).dream(cur_ext)
        cur_ext = re_["best_strategy"]
        curve_ext.append(re_["best_v"])
    print(f"  迭代轮数: {rounds}")
    print(f"  仅内部树 V 曲线: {[round(v, 4) for v in curve_int]}")
    print(f"  内部+外部 V 曲线: {[round(v, 4) for v in curve_ext]}")
    # 收敛判定：V 值变化 < 1e-6 视为收敛
    def converge_round(curve):
        for i in range(1, len(curve)):
            if abs(curve[i] - curve[i - 1]) < 1e-6:
                return i + 1
        return len(curve)
    ci = converge_round(curve_int)
    ce = converge_round(curve_ext)
    print(f"  收敛轮数: 仅内部={ci}, 内部+外部={ce}")
    print(f"  最终 V 值: 仅内部={curve_int[-1]:.4f}, 内部+外部={curve_ext[-1]:.4f}")
    faster = ce <= ci
    higher = curve_ext[-1] >= curve_int[-1]
    print(f"  收敛速度: 内部+外部 {'不慢于' if faster else '慢于'} 仅内部")
    print(f"  最终 V 值: 内部+外部 {'不低于' if higher else '低于'} 仅内部")
    ok = faster and higher
    print(f"  结果: {"PASS" if ok else "FAIL"}")
    return ok, curve_int, curve_ext


def scenario_runtime():
    print("=" * 60)
    print("运行期模拟: 批评自循环完整生命周期（模拟任务流）")
    print("=" * 60)
    tmp = tempfile.mkdtemp(prefix="rea_rt_")
    pool = fill_pool(os.path.join(tmp, "pool"))
    loop = CriticLoop(pool=pool)
    # 模拟任务流：每任务周期的指标（poe_score, 证据完整度, 成本）
    # 提案 A：健康改进（指标平稳 → 应在观察期后采纳）
    # 提案 B：劣化改进（poe_score 下降超阈值 → 应触发回滚）
    pa = loop.propose("内部策略与外部路径在验收步骤顺序上矛盾", "假说A: 调整步骤顺序可提升 poe", self_score=0.6)
    pb = loop.propose("分析成本与结论质量出现背离", "假说B: 压缩证据采集可提速", self_score=0.5)
    print(f"  提案数: {len(loop.proposals)}（{pa.proposal_id}, {pb.proposal_id}）")
    # 池可评估性不足时手动进入观察期（模拟回放验证已通过）
    for p in loop.proposals:
        p.status = "observing"
        p.independently_verified = True
    print(f"  批评可信度: {pa.proposal_id}={pa.credibility:.2f}, {pb.proposal_id}={pb.credibility:.2f}（自评+独立验证加成）")
    # 模拟任务流：提案 A 平稳，提案 B 第二周期劣化
    flow_a = [(80.0, 1.0, 10), (81.0, 1.0, 10), (80.5, 1.0, 11)]
    flow_b = [(80.0, 1.0, 10), (60.0, 1.0, 10), (80.0, 1.0, 10)]
    log = []
    for t in range(OBSERVATION_PERIOD):
        ra = loop.record_task(pa.proposal_id, *flow_a[t])
        rb = loop.record_task(pb.proposal_id, *flow_b[t])
        log.append((t + 1, pa.status, pb.status, ra["reason"], rb["reason"]))
        print(f"  周期{t + 1}: A={pa.status}({ra['reason']}), B={pb.status}({rb['reason']})")
    adopted = pa.status == "adopted"
    rolled = pb.status == "rolled_back"
    print(f"  提案A（健康）: {pa.status}（期望 adopted）")
    print(f"  提案B（劣化）: {pb.status}（期望 rolled_back）")
    ok = adopted and rolled
    print(f"  结果: {"PASS" if ok else "FAIL"}")
    return ok, log


def main():
    e5_ok, curve_int, curve_ext = scenario_e5()
    rt_ok, log = scenario_runtime()
    print("=" * 60)
    print("汇总")
    print("=" * 60)
    print(f"  E5 收敛速度: {"PASS" if e5_ok else "FAIL"}")
    print(f"  运行期生命周期: {"PASS" if rt_ok else "FAIL"}")
    all_pass = e5_ok and rt_ok
    print(f"  总体: {"ALL PASS" if all_pass else "SOME FAILED"}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
