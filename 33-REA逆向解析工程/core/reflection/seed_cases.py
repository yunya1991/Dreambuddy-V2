# -*- coding: utf-8 -*-
"""种子案例转换 — SPEC-33-反思层 v0.3 P1（冷启动路径）

将 acceptance_bundles 两个历史验收包转换为最小发现树（单链路径），
作为回放池种子案例：仅用于 Schema 验证与重放引擎冒烟测试，
不作为策略评估的充分历史（SPEC §4.1 冷启动路径第 2 条）。

转换规则（基于 wrapup_report.md 步骤执行矩阵）：
  - 根节点：初始状态（s_r=0）
  - 每个已执行步骤 → 一个发现树节点（action=步骤名，poe_score 按验收状态）
  - 验收 PASS → poe_score=0.8；跳过步骤不入树

用法：
  python3 scripts/seed_cases.py [--pool-dir reflection_data/replay_pool]
"""
from __future__ import annotations

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
for _p in (_PROJECT_ROOT,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.reflection import DiscoveryNode, DiscoveryTree, ReplayPool  # noqa: E402

# 默认回放池目录（工程内）
DEFAULT_POOL_DIR = os.path.join(
    _PROJECT_ROOT, "reflection_data", "replay_pool"
)

# 种子案例定义：验收包 → 最小发现树（单链路径，节点=关键步骤）
# poe_score 依据 wrapup_report 验收门禁结果（PASS=0.8）
SEED_CASES = [
    {
        "bundle": "20261011_poe_landing",
        "task": {
            "target": "33-REA逆向解析工程",
            "task_type": "acceptance",
            "feature": "PoE 机制全量落地（SPEC-工程实践复现器 v0.3）",
        },
        "source_label": "acceptance_bundle:20261011_poe_landing:16826f4eb1",
        "steps": [
            {"analyzer": "acceptance_gate", "params": {"skill": "dream-acceptance-verify"}, "poe_score": 0.8, "cost_calls": 1},
            {"analyzer": "code_commit", "params": {"commit": "16826f4eb1"}, "poe_score": 0.8, "cost_calls": 1},
            {"analyzer": "doc_sync", "params": {"scope": "README+INDEX"}, "poe_score": 0.8, "cost_calls": 1},
            {"analyzer": "cognitive_record", "params": {"vm": "VM-1791723832736"}, "poe_score": 0.8, "cost_calls": 1},
        ],
    },
    {
        "bundle": "20261012_checkpoint_persistence",
        "task": {
            "target": "34-前端应用训练系统",
            "task_type": "acceptance",
            "feature": "ModelCheckpoint 文件持久化 + 5层训练循环启动恢复",
        },
        "source_label": "acceptance_bundle:20261012_checkpoint_persistence:886a53501b",
        "steps": [
            {"analyzer": "acceptance_gate", "params": {"skill": "dream-acceptance-verify"}, "poe_score": 0.8, "cost_calls": 1},
            {"analyzer": "code_commit", "params": {"commit": "886a53501b"}, "poe_score": 0.8, "cost_calls": 1},
            {"analyzer": "cognitive_record", "params": {"vm": "VM-1791737946287"}, "poe_score": 0.8, "cost_calls": 1},
            {"analyzer": "passive_training", "params": {"decision": "ingest"}, "poe_score": 0.8, "cost_calls": 1},
        ],
    },
]


def build_seed_tree(case: dict) -> DiscoveryTree:
    """将种子案例定义转换为最小发现树（单链路径）。"""
    tree = DiscoveryTree.new_tree(
        task=case["task"],
        provenance="internal",
        source_label=case["source_label"],
    )
    parent = tree.root
    for step in case["steps"]:
        node = DiscoveryNode(
            node_id=f"dn_seed_{case['bundle']}_{step['analyzer']}",
            parent_id=parent.node_id,
            action={"analyzer": step["analyzer"], "params": step["params"]},
            evidence_refs=[
                {
                    "source": f"acceptance_bundles/{case['bundle']}/wrapup_report.md",
                    "detail": f"步骤 {step['analyzer']} 验收 PASS",
                }
            ],
            poe_score=step["poe_score"],
            cost_calls=step["cost_calls"],
        )
        tree.add_node(node)
        parent = node
    return tree


def main(pool_dir: str = DEFAULT_POOL_DIR) -> int:
    pool = ReplayPool(pool_dir)
    created = []
    for case in SEED_CASES:
        # 幂等：已存在同 source_label 的树则跳过
        existing = {
            t.source_label for t in pool.list_trees("internal")
        }
        if case["source_label"] in existing:
            print(f"SKIP (exists): {case['bundle']}")
            continue
        tree = build_seed_tree(case)
        path = pool.save(tree)
        created.append(tree.tree_id)
        print(f"SEEDED: {case['bundle']} -> {path} ({len(tree.nodes)} nodes)")
    print(f"pool internal count = {pool.count('internal')}")
    return 0


if __name__ == "__main__":
    _dir = sys.argv[sys.argv.index("--pool-dir") + 1] if "--pool-dir" in sys.argv else DEFAULT_POOL_DIR
    sys.exit(main(_dir))
