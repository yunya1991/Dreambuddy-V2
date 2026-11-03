# -*- coding: utf-8 -*-
"""OKR→Ticket Mandate 契约翻译器(T-DSH-P0 B1)。

依据: SACG_A_SUPERAGENT_CONNECTION_SPEC v0.2 §4.2 + DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-5。
定位: A 层(契约与验收层)→ Super-agent Ticket 的桥。纯函数,无副作用,不加载即不存在。

字段映射(SPEC §4.2):
  node_id              → external_ref(Chain of Recall 锚点,回写验收结论用)
  objective            → mandate.goal
  criteria             → mandate.acceptance
  verify=evidence_backed → completion_policy: Worker 报告须含 evidence_id 匹配
  verify=gap_closed      → completion_policy: 缺口项关闭标记
  verify=c_action        → completion_policy: 决策动作非 REDO/EARLY_TERMINATE
  evidence_id          → mandate.evidence_refs[]
  domain=finance_research → route_hint(Worker 路由提示,金融域走研究角色)
  OKRSet.dependency_graph → dispatch 分派计划(并行线→多 Worker,顺序依赖→串行 Ticket)

输出为**建议性 Mandate 草案**(draft=True),经 bundle Policy 门与 S 层元认知
门控(双门)后才创建 Ticket。

硬约束:
  HC-1 FAIL-OPEN: 任何异常/空输入 → 返回 None,不抛错,行为等价「桥不存在」
  HC-2 开关 enable_superagent_bridge 默认 False,关断时调用方不得加载本模块
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .okr_nodes import VERIFY_C_ACTION, VERIFY_EVIDENCE, VERIFY_GAP, decompose_okr_nodes

# 模块化开关(HC-2,默认 False)
BRIDGE_SWITCH = "enable_superagent_bridge"

# verify → 完成判定策略映射(SPEC §4.2;未知 verify 一律降级 c_action)
_COMPLETION_POLICIES: Dict[str, Dict[str, Any]] = {
    VERIFY_EVIDENCE: {"kind": "evidence_backed", "requires": "evidence_id"},
    VERIFY_GAP: {"kind": "gap_closed", "requires": "gap_closed_flag"},
    VERIFY_C_ACTION: {"kind": "c_action", "forbid_actions": ["REDO", "EARLY_TERMINATE"]},
}

# domain → Worker 角色路由提示(ADR-4/DD2: 首批 研究/工程/验收 三类;
# 金融研究域走研究 Worker;交易分析后置——避交易热路径 H5)
_DOMAIN_ROLE_HINT: Dict[str, str] = {
    "finance_research": "research",
}


def is_bridge_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(HC-2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(BRIDGE_SWITCH, False))
    except Exception:
        return False


def translate_okr_node(node: Any) -> Optional[Dict[str, Any]]:
    """单个 OKR 节点 → 建议性 Ticket Mandate 草案。

    输入: decompose_okr_nodes() 的节点 {node_id, objective, criteria, source,
    verify, evidence_id?, domain?}。非法输入返回 None(FAIL-OPEN,不抛错)。
    """
    try:
        if not isinstance(node, dict):
            return None
        node_id = node.get("node_id")
        objective = node.get("objective")
        if not node_id or objective is None:
            return None

        verify = node.get("verify")
        policy = _COMPLETION_POLICIES.get(verify, _COMPLETION_POLICIES[VERIFY_C_ACTION])
        completion_policy = dict(policy)  # 拷贝,防共享可变状态

        evidence_refs: List[str] = []
        if node.get("evidence_id"):
            evidence_refs.append(str(node["evidence_id"]))

        domain = node.get("domain")
        return {
            "external_ref": str(node_id),
            "mandate": {
                "goal": str(objective),
                "acceptance": str(node.get("criteria", objective)),
                "completion_policy": completion_policy,
                "evidence_refs": evidence_refs,
            },
            "route_hint": {
                "domain": str(domain) if domain else None,
                "role": _DOMAIN_ROLE_HINT.get(str(domain)) if domain else None,
            },
        }
    except Exception:
        return None


def translate_plan_to_tickets(
    plan: Any,
    okr_set: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Plan → 建议性 Ticket 草案集 + 分派计划。

    输入: decompose_okr_nodes() 消费的 plan dict;okr_set 可选,携带
    parallel_line_count / dependency_graph(dict 或带同名属性的对象)。
    空 plan / 任何异常 → None(HC-1 FAIL-OPEN)。
    """
    try:
        nodes = decompose_okr_nodes(plan)
        if not nodes:
            return None

        tickets = [t for t in (translate_okr_node(n) for n in nodes) if t is not None]
        if not tickets:
            return None

        parallel_line_count = 1
        dependency_graph: Dict[str, Any] = {}
        if okr_set is not None:
            if isinstance(okr_set, dict):
                parallel_line_count = int(okr_set.get("parallel_line_count") or 1)
                dependency_graph = okr_set.get("dependency_graph") or {}
            else:
                parallel_line_count = int(getattr(okr_set, "parallel_line_count", 1) or 1)
                dependency_graph = getattr(okr_set, "dependency_graph", None) or {}

        # 依赖图只保留指向本次 Ticket 集内的边(外部锚点不进入分派计划)
        refs = {t["external_ref"] for t in tickets}
        depends_on: Dict[str, List[str]] = {}
        if isinstance(dependency_graph, dict):
            for ref, deps in dependency_graph.items():
                if ref in refs and isinstance(deps, (list, tuple)):
                    inner = [str(d) for d in deps if str(d) in refs]
                    if inner:
                        depends_on[str(ref)] = inner

        return {
            "draft": True,  # 建议性草案: 双门(Policy + S 层元认知)后才创建 Ticket
            "tickets": tickets,
            "dispatch": {
                "mode": "parallel" if parallel_line_count > 1 else "sequential",
                "depends_on": depends_on,
            },
        }
    except Exception:
        return None
