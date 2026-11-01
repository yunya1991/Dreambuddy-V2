# -*- coding: utf-8 -*-
"""做梦评估循环 — SPEC-33-反思层 v0.3 P2（对齐 Dream-RSI）

Dream-RSI 做梦阶段：候选策略在回放模拟器内确定性重放评估，
改进后的策略重新部署在线，形成递归自改进闭环。

回放目标函数（SPEC §4.3，对齐 Dream-RSI 式 1）：
    V(π, T) = 归一化 hypervolume(质量-成本点集) − λ × 并行度惩罚

  - 点集：一棵发现树多节点的 (poe_score, 累积成本) 二维点
  - 参考点：(0, 总预算 budget.max_calls)
  - 归一化：除以参考点矩形面积，V ∈ [0,1]
  - λ 初始 0.1，观察期调优

策略空间（SPEC §4.2）：策略 = 分析编排配置（JSON），
候选策略由配置变换生成（序列重排/深度参数/停止条件/并行度），
分析器代码不变（base agent 不变）。

不劣化保证（Dream-RSI 策略选择）：当前策略始终在候选集中，
π_{t+1} = argmax V^m，保证 V(π_{t+1}) ≥ V(π_t)。

关联：SPEC-33-反思层.md v0.3 §4.2-4.4；core/reflection/replay_simulator.py
"""
from __future__ import annotations

from itertools import permutations
from typing import Any, Dict, List, Optional, Tuple

from .replay_simulator import ReplayPool, ReplaySimulator

# λ 初始值（SPEC §4.3：观察期调优，记录调优依据）
DEFAULT_LAMBDA = 0.1
# 预算偏好参数（对齐 Dream-RSI：ρ ∈ {0, 0.25, 0.5, 0.75, 1}）
RHO_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


# ============================================================
# 回放目标函数
# ============================================================
def hypervolume(points: List[Tuple[float, float]], ref: Tuple[float, float]) -> float:
    """二维 hypervolume：点集支配区域面积（质量-成本 Pareto 前沿）。

    points: (score, cost) 点集，score 越大越好，cost 越小越好
    ref: 参考点 (ref_score, ref_cost)，支配区域为
         score ∈ [ref_score, s]、cost ∈ [c, ref_cost]
    """
    if not points:
        return 0.0
    rs, rc = ref
    # 过滤掉被参考点支配的点（无效点）
    valid = [(s, c) for s, c in points if s > rs and c < rc]
    if not valid:
        return 0.0
    # 按 cost 升序排，同 cost 取最大 score
    valid.sort(key=lambda p: (p[1], -p[0]))
    # 扫描非支配前沿，累加矩形面积
    area = 0.0
    best_score = rs
    prev_cost = rc
    for s, c in valid:
        if s > best_score:
            area += (s - best_score) * (prev_cost - c)
            best_score = s
        prev_cost = c
    return area


def replay_objective(
    replay_result: Dict[str, Any],
    budget_calls: int,
    lam: float = DEFAULT_LAMBDA,
) -> float:
    """回放目标函数 V（SPEC §4.3）。

    replay_result: ReplaySimulator.replay 的返回值（含 path/score/cost）
    budget_calls: 总预算（参考点成本维度）
    """
    if budget_calls <= 0:
        return 0.0
    # 质量归一化到 [0,1]（参考点 score 维度取 0）
    score = max(0.0, min(1.0, float(replay_result.get("total_score") or 0.0)))
    cost = max(0, int(replay_result.get("total_cost_calls") or 0))
    # 单点 hypervolume：score × (budget − cost) / budget
    hv = score * (budget_calls - cost) / float(budget_calls)
    # 并行度惩罚：串行轮数占比 × λ（无并行信息时轮数即串行）
    rounds = max(0, int(replay_result.get("rounds") or 0))
    parallelism = max(1, int(replay_result.get("parallelism") or 1))
    serial_ratio = (rounds / parallelism) / float(budget_calls) if budget_calls else 0.0
    penalty = lam * min(1.0, serial_ratio)
    return max(0.0, hv - penalty)


# ============================================================
# 策略空间：配置变换生成候选策略
# ============================================================
def generate_candidates(
    current: Dict[str, Any],
    max_candidates: int = 8,
    pool: Optional["ReplayPool"] = None,
) -> List[Dict[str, Any]]:
    """从当前策略配置变换生成候选策略集（含当前策略本身）。

    变换类型（SPEC §4.2）：
      - 序列重排（analyzer_sequence 的排列）
      - 深度参数（max_depth 调整）
      - 预算调整（max_calls 缩放）
      - 并行度调整（parallelism 变化）

    当前策略始终在候选集中（不劣化保证）。
    """
    candidates: List[Dict[str, Any]] = [dict(current)]  # 当前策略排第一
    # 0. 池序列挖掘（SPEC §9-1）：internal+external 树动作序列进入候选集，否则 V 贡献 0
    if pool is not None:
        budget0 = dict(current.get("budget") or {})
        max_calls0 = max(1, int(budget0.get("max_calls") or 10))
        seen_seqs = {tuple(current.get("analyzer_sequence") or [])}
        for tree in pool.list_trees():
            actions = [
                n.action.get("analyzer", "")
                for n in tree.nodes
                if n.parent_id is not None and n.action.get("analyzer")
            ]
            if not actions:
                continue
            actions = actions[:max_calls0]
            key = tuple(actions)
            if key in seen_seqs:
                continue
            seen_seqs.add(key)
            cand = dict(current)
            cand["analyzer_sequence"] = actions
            cand["transform"] = f"pool_{tree.provenance}_{tree.tree_id[:12]}"
            candidates.append(cand)
            if len(candidates) >= max_candidates:
                return candidates

    seq = list(current.get("analyzer_sequence") or [])
    budget = dict(current.get("budget") or {})
    max_calls = int(budget.get("max_calls") or 10)

    # 1. 序列重排（最多取前 3 个不同排列）
    if len(seq) >= 2:
        seen = {tuple(seq)}
        for perm in permutations(seq):
            key = tuple(perm)
            if key in seen:
                continue
            seen.add(key)
            cand = dict(current)
            cand["analyzer_sequence"] = list(perm)
            cand["transform"] = "sequence_permutation"
            candidates.append(cand)
            if len(candidates) >= max_candidates:
                return candidates

    # 2. 预算调整（0.5x / 1.5x）
    for factor, label in ((0.5, "budget_half"), (1.5, "budget_1_5x")):
        cand = dict(current)
        cand["budget"] = {**budget, "max_calls": max(1, int(max_calls * factor))}
        cand["transform"] = label
        candidates.append(cand)

    # 3. 并行度调整（2x）
    cand = dict(current)
    cand["parallelism"] = max(2, int(current.get("parallelism") or 1) * 2)
    cand["transform"] = "parallelism_2x"
    candidates.append(cand)

    # 4. 深度截断（保留序列前半）
    if len(seq) >= 2:
        cand = dict(current)
        cand["analyzer_sequence"] = seq[: len(seq) // 2 + 1]
        cand["transform"] = "depth_truncate"
        candidates.append(cand)

    return candidates[:max_candidates]


# ============================================================
# 做梦评估循环
# ============================================================
class DreamingLoop:
    """做梦评估循环（对齐 Dream-RSI 三阶段循环的做梦阶段）。

    1. 从回放池取全部发现树（内部 + 外部，外部树按动态权重）
    2. 对候选策略集（含当前策略）在预算偏好 ρ 网格下确定性重放
    3. 计算 V 值，选 π_{t+1} = argmax V（不劣化保证）
    """

    def __init__(
        self,
        pool: ReplayPool,
        lam: float = DEFAULT_LAMBDA,
        max_rounds: int = 10,
        max_trees: int = 200,
    ):
        self.pool = pool
        self.sim = ReplaySimulator(pool)
        self.lam = lam
        self.max_rounds = max_rounds
        # 抽样限制：回放池树数超过上限时均匀抽样，避免全量重放开销
        self.max_trees = max(1, int(max_trees))

    def evaluate_strategy(
        self,
        strategy: Dict[str, Any],
    ) -> Dict[str, Any]:
        """在回放池全部树上评估单个策略，返回各 ρ 偏好下的加权 V 值。"""
        budget = int((strategy.get("budget") or {}).get("max_calls") or 10)
        parallelism = max(1, int(strategy.get("parallelism") or 1))
        v_values: List[float] = []
        per_tree: List[Dict[str, Any]] = []
        trees = self.pool.list_trees()
        if len(trees) > self.max_trees:
            step = len(trees) / self.max_trees
            trees = [trees[int(i * step)] for i in range(self.max_trees)]
        for tree in trees:
            r = self.sim.replay(tree, strategy, self.max_rounds)
            r["parallelism"] = parallelism
            v = replay_objective(r, budget, self.lam)
            # 外部树按动态权重折算（SPEC §5.4）
            v_weighted = v * tree.weight
            r["v"] = v
            r["v_weighted"] = v_weighted
            r["tree_weight"] = tree.weight
            r["provenance"] = tree.provenance
            per_tree.append(r)
            v_values.append(v_weighted)
        total_weight = sum(t.get("tree_weight", 1.0) for t in per_tree) or 1.0
        return {
            "strategy": strategy,
            "avg_v": sum(v_values) / total_weight if total_weight else 0.0,
            "per_tree": per_tree,
            "tree_count": len(per_tree),
        }

    def dream(
        self,
        current: Dict[str, Any],
        max_candidates: int = 8,
    ) -> Dict[str, Any]:
        """做梦评估循环：候选策略评估 + 不劣化选择。

        返回：{best_strategy, best_v, current_v, improved, eval_ready,
               candidates: [{strategy, avg_v}], selection_rule}
        """
        eval_ready = self.pool.eval_ready()
        candidates = generate_candidates(current, max_candidates, pool=self.pool)
        evaluated = [self.evaluate_strategy(c) for c in candidates]
        # 不劣化保证：当前策略（candidates[0]）始终参与比较
        best = max(evaluated, key=lambda e: e["avg_v"])
        current_eval = evaluated[0]
        return {
            "best_strategy": best["strategy"],
            "best_v": best["avg_v"],
            "current_v": current_eval["avg_v"],
            "improved": best["avg_v"] > current_eval["avg_v"] + 1e-9,
            "eval_ready": eval_ready,
            "candidates": [
                {"strategy": e["strategy"], "avg_v": e["avg_v"],
                 "transform": e["strategy"].get("transform", "current")}
                for e in evaluated
            ],
            "selection_rule": "argmax_v_with_current_in_candidates",
            "lam": self.lam,
        }
