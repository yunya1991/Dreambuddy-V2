"""thought_tree.py — 思维树（G5）：多步展开 / 剪枝 / 回溯的束搜索做梦器。

在 DreamingLoop（单层候选生成 + argmax）之上实现真正的搜索树：
  - 展开（expansion）：以 generate_candidates 为算子，从束内节点生成子节点；
  - 评估（evaluation）：以 DreamingLoop.evaluate_strategy 为价值函数；
  - 剪枝（pruning）：每轮仅保留全局 top-K（束宽）；
  - 回溯（backtracking）：父链路完整保留，最优节点可回溯至根。

纪律：
  - 不劣化保证：根节点（当前策略）始终在束内参与比较；
  - 确定性：同输入同输出（无随机性）；
  - fail-open：展开/评估异常的节点丢弃，不中断搜索。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .dreaming import DreamingLoop, generate_candidates

logger = logging.getLogger(__name__)

THOUGHT_TREE_VERSION = "thought_tree.v0.1"


def strategy_signature(strategy: Dict[str, Any]) -> Tuple:
    """策略签名（去重键）：分析序列 + 预算 + 并行度。"""
    budget = strategy.get("budget") or {}
    return (
        tuple(strategy.get("analyzer_sequence") or []),
        int(budget.get("max_calls") or 10),
        max(1, int(strategy.get("parallelism") or 1)),
    )


@dataclass
class ThoughtNode:
    """思维树节点：策略 + 价值 + 深度 + 父链路。"""

    strategy: Dict[str, Any]
    v: float
    depth: int
    parent: Optional["ThoughtNode"] = None
    transform: str = "root"

    def backtrace(self) -> List["ThoughtNode"]:
        """回溯：从当前节点回溯到根（含自身），返回根→叶顺序。"""
        path: List["ThoughtNode"] = []
        node: Optional["ThoughtNode"] = self
        while node is not None:
            path.append(node)
            node = node.parent
        return list(reversed(path))


def beam_search_dream(
    loop: DreamingLoop,
    current: Dict[str, Any],
    depth: int = 3,
    beam_width: int = 4,
    max_candidates: int = 6,
) -> Dict[str, Any]:
    """思维树束搜索：多轮展开 → 评估 → 剪枝 top-K → 回溯最优路径。

    返回：{best_strategy, best_v, current_v, improved, eval_ready,
           version, depth, beam_width, nodes_expanded, nodes_evaluated,
           pruned_per_round, path: [{depth, transform, v, strategy}]}
    """
    root = ThoughtNode(strategy=dict(current), v=0.0, depth=0, transform="root")
    # 根节点先评估（不劣化基准）
    try:
        root.v = float(loop.evaluate_strategy(root.strategy).get("avg_v", 0.0))
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("思维树根节点评估失败（V 置 0 继续）: %s", exc)
        root.v = 0.0

    beam: List[ThoughtNode] = [root]
    seen = {strategy_signature(root.strategy)}
    nodes_expanded = 0
    nodes_evaluated = 1
    pruned_per_round: List[int] = []

    for round_no in range(1, max(1, int(depth)) + 1):
        frontier: List[ThoughtNode] = []
        for node in beam:
            try:
                children = generate_candidates(
                    node.strategy, max_candidates=max_candidates, pool=getattr(loop, "pool", None)
                )
            except Exception as exc:  # noqa: BLE001 — fail-open
                logger.warning("思维树展开失败（跳过该节点）: %s", exc)
                continue
            for cand in children:
                sig = strategy_signature(cand)
                if sig in seen:
                    continue
                seen.add(sig)
                child = ThoughtNode(
                    strategy=cand,
                    v=0.0,
                    depth=round_no,
                    parent=node,
                    transform=str(cand.get("transform") or "expand"),
                )
                nodes_expanded += 1
                try:
                    child.v = float(loop.evaluate_strategy(cand).get("avg_v", 0.0))
                except Exception as exc:  # noqa: BLE001 — fail-open
                    logger.warning("思维树节点评估失败（丢弃）: %s", exc)
                    continue
                nodes_evaluated += 1
                frontier.append(child)
        if not frontier:
            break
        # 剪枝：全局 top-K（束宽）；根节点始终保留（不劣化保证）
        frontier.sort(key=lambda n: n.v, reverse=True)
        kept = frontier[: max(1, int(beam_width))]
        pruned_per_round.append(len(frontier) - len(kept))
        beam = [root] + kept

    # 最优节点：束内 V 最大者（根参与比较 → 不劣化）
    best = max(beam, key=lambda n: n.v)
    path_nodes = best.backtrace()
    return {
        "version": THOUGHT_TREE_VERSION,
        "best_strategy": best.strategy,
        "best_v": best.v,
        "current_v": root.v,
        "improved": best.v > root.v + 1e-9,
        "eval_ready": bool(getattr(loop, "pool", None) is not None),
        "depth": depth,
        "beam_width": beam_width,
        "nodes_expanded": nodes_expanded,
        "nodes_evaluated": nodes_evaluated,
        "pruned_per_round": pruned_per_round,
        "path": [
            {
                "depth": n.depth,
                "transform": n.transform,
                "v": round(n.v, 6),
                "strategy": n.strategy,
            }
            for n in path_nodes
        ],
    }
