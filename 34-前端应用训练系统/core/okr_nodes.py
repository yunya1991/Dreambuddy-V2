# -*- coding: utf-8 -*-
"""P3.3 A 层: OKR 节点验收体系 — Spec/Plan → OKR 节点 + 每节点验收标准。

依据: SPEC-v1.2-SACG-orchestration.md §2.2。
核心变化: A 层从「工具组合器」升级为「验收体系」——每个节点是带验收标准的
OKR 节点，而非工具调用。C 层执行结果回传比对由 P3.4 消费本模块的 verify 标记。

verify 验收方式（按节点来源分派，禁止新阈值）:
  - rea_evidence  → evidence_backed（证据满足即验收，P3.4 比对 evidence_id）
  - rea_known_gap → gap_closed（缺口补齐即验收）
  - plan_item     → c_action（C 层决策动作非 REDO/EARLY_TERMINATE 即验收）

节点契约（向后兼容）: {node_id, objective, criteria, source, verify, evidence_id?}
  - node_id/criteria 键保持（C 层 _run_node 与既有测试消费）
  - criteria 一律为字符串（禁止裸 dict 透传）
"""
from __future__ import annotations

from typing import Any, Dict, List

# verify 验收方式标记
VERIFY_EVIDENCE = "evidence_backed"
VERIFY_GAP = "gap_closed"
VERIFY_C_ACTION = "c_action"

# 来源 → verify 分派表
_SOURCE_VERIFY = {
    "rea_evidence": VERIFY_EVIDENCE,
    "rea_known_gap": VERIFY_GAP,
}


def decompose_okr_nodes(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Spec/Plan → OKR 节点集（每节点带验收标准）。

    engineering_okr（REA 逆向拆解，更具体）优先于 plan_items。

    domain 分流（P3.4 金融四维验收）: item 显式 > plan 级显式 > research_request
    推断为 finance_research；否则不带 domain（走代码开发验收规则）。
    """
    items = (plan or {}).get("engineering_okr") or (plan or {}).get("plan_items") or []
    plan_domain = (plan or {}).get("domain")
    if plan_domain is None and (plan or {}).get("research_request"):
        plan_domain = "finance_research"
    nodes: List[Dict[str, Any]] = []
    for i, item in enumerate(items):
        node_id = f"N{i + 1}"
        if isinstance(item, dict):
            statement = str(item.get("okr") or item)
            source = str(item.get("source") or "engineering_okr")
            node: Dict[str, Any] = {
                "node_id": node_id,
                "objective": statement,
                "criteria": statement,
                "source": source,
                "verify": _SOURCE_VERIFY.get(source, VERIFY_C_ACTION),
            }
            if item.get("evidence_id"):
                node["evidence_id"] = item["evidence_id"]
            domain = item.get("domain") or plan_domain
        else:
            statement = str(item)
            node = {
                "node_id": node_id,
                "objective": statement,
                "criteria": statement,
                "source": "plan_item",
                "verify": VERIFY_C_ACTION,
            }
            domain = plan_domain
        if domain:
            node["domain"] = str(domain)
        nodes.append(node)
    return nodes
