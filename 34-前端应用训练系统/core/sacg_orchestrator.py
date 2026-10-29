# -*- coding: utf-8 -*-
"""P3.1: SACG 编排骨架 — C-drive 驱动的 S→A→C→G 全程调度入口。

依据:
  - SPEC-v1.2-SACG-orchestration.md §3（C-drive 作为 L2 全程调度者）
  - PLAN-L0L1L2-implementation.md P3.1

职责边界（P3.1 只落骨架与流转）:
  请求入口 → route_confidence 门控（复用 core.route_confidence，阈值唯一）
    · L1_DIRECT → 不编排，直接返回（L1 零 token 直答已在 l1_route_signal 层完成）
    · L2_HANDOFF → 进入 S→A→C→G:
      S 规划入口（l1_intent_hint 先验；实质认知接入属 P3.2）
      → A OKR 节点分解（实质验收体系属 P3.3）
      → C 逐节点执行，节点决策委托 CDriveV3Router.run_v3（节点级五步反思门）；
        执行结果回传 A（实质回传验收属 P3.4）
      → G 图压缩 + 收尾钩子（实质四分流沉淀属 P3.5）

FAIL-OPEN: 每层异常被隔离记录（errors），不抛出；信号自身 degraded 由 route_signal
字段表达，与编排层 degraded（阶段异常）分离。
"""
from __future__ import annotations
import json
import os

from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from core.c_drive_v3_router import CDriveV3Router
from core.cognitive_loop import close_loop
from core.okr_acceptance import VERDICT_PASS, evaluate_nodes
from core.okr_nodes import decompose_okr_nodes
from core.route_confidence import L1_DIRECT, L2_HANDOFF, evaluate_route
from core.sufficiency import (
    EARLY_TERMINATE,
    NEED_CLARIFY,
    NEED_DEEPER,
    NEED_RESEARCH,
    SUFFICIENT_DIRECT,
    evaluate_entry_sufficiency,
    evaluate_plan_sufficiency,
)

STAGE_S = "S"
STAGE_A = "A"
STAGE_C = "C"
STAGE_G = "G"
SACG_STAGES = [STAGE_S, STAGE_A, STAGE_C, STAGE_G]

# 节点执行失败占位动作（与 CDriveV3Router 的 CONTINUE/REDO 等决策区分）
NODE_FAILED = "FAILED"

# ============================================================
# P3.5: G 层四分流沉淀（SPEC-v1.2 §2.4：案例/认知/流程/文档）
# 规则化路由，禁新阈值；sediments 为 async_stub 描述符打桩
# （与 S 层 kickoff_trigger 同款模式），真实触发归会话级收尾 Skill。
# 认知分流 verdict → close_loop outcome 映射:
#   pass → success / degraded → partial / fail → failure
# ============================================================
G_OUTCOME_MAP = {"pass": "success", "degraded": "partial", "fail": "failure"}
SEDIMENT_ASYNC_STUB = "async_stub"

# ============================================================
# P3.2: S 层意图档案 —— l1_intent_hint 深化消费
# 与 TS l1-intent-registry.ts v3 十意图对齐；驱动规划展开与 Spec 草案产出。
# depth 先验供后续 A 层 OKR 粒度 / C 层 effort_level 参考。
# ============================================================
S_LAYER_INTENT_PROFILES: Dict[str, Dict[str, Any]] = {
    "data_query": {
        "depth": "light",
        "plan": ["定位数据源", "执行数据查询", "结构化输出"],
    },
    "data_insight": {
        "depth": "light",
        "plan": ["获取指标数据", "变化归因解读", "影响分析"],
    },
    "price_query": {
        "depth": "light",
        "plan": ["获取实时行情", "结构化输出"],
    },
    "contradiction_insight": {
        "depth": "standard",
        "plan": ["采集多维度数据", "维度间矛盾识别", "主要矛盾判定"],
    },
    "path_insight": {
        "depth": "standard",
        "plan": ["多维度数据采集", "阻力路径推演", "综合方向判断"],
    },
    "technical_analysis": {
        "depth": "standard",
        "plan": ["技术指标计算", "形态/卦象解读", "置信度评估"],
    },
    "fundamental_valuation": {
        "depth": "standard",
        "plan": ["估值数据采集", "百分位计算", "估值结论"],
    },
    "asset_class_trend": {
        "depth": "deep",
        "plan": ["跨资产数据采集", "趋势对比分析", "轮动信号识别"],
    },
    "event_analysis": {
        "depth": "deep",
        "plan": ["事件背景梳理", "预期差分析", "市场影响推演"],
    },
    "risk_control": {
        "depth": "standard",
        "plan": ["持仓状态采集", "风控指标评估", "处置建议"],
    },
}


# ============================================================
# SPEC-v1.4 S-2/S-4: SLayerPlanner — 充分性状态机（S0→S1→S2）
# 替换 _default_s_planner 成为默认规划器；新契约:
#   {plan, sufficiency, action, clarification, research_request, kickoff_trigger}
# action: PROCEED / SUFFICIENT_DIRECT / NEED_CLARIFY / EARLY_TERMINATE
# ============================================================

DEPTH_ORDER = ["light", "standard", "deep"]

# 澄清选项词表（与 3.1-FRONTEND /api/task/stream clarificationPatterns 对齐）
DEFAULT_CLARIFICATION_OPTIONS = ["快速概览", "技术分析", "基本面分析", "深度报告"]

# 开工 Skill 触发（SPEC-v1.4 §3.4）
KICKOFF_SKILL = "dream-arch-research-orchestrator"
GENERIC_DEEPENING_ITEM = "深化:多维度交叉验证"


class SLayerPlanner:
    """S 层充分性状态机规划器（C-Drive 充分性驱动，够用即停）。

    S0 入口评估 → S1 档案展开 → S2 充分性再评估；
    任何一步评估"够了"即停（SUFFICIENT_DIRECT/early TERMINATE），
    不确定区间（NEED_CLARIFY）产结构化选项问用户。
    """

    def __init__(self, *, profiles: Optional[Dict[str, Dict[str, Any]]] = None,
                 kickoff_keywords: Optional[tuple] = None,
                 clarification_options: Optional[List[str]] = None,
                 rea_fn: Optional[Callable] = None):
        self._profiles = profiles if profiles is not None else S_LAYER_INTENT_PROFILES
        self._kickoff_keywords = kickoff_keywords or ("开工",)
        self._clarification_options = (
            clarification_options or list(DEFAULT_CLARIFICATION_OPTIONS))
        # SPEC-v1.4 §3.5: REA 逆向解析工程（可选，FAIL-OPEN）
        self._rea_fn = rea_fn

    # -------- 内部 --------

    def _expand(self, message: str, hint: Optional[str],
                memories: List[Any], depth: Optional[str]) -> Dict[str, Any]:
        """S1 规划展开（意图档案驱动，P3.2 逻辑上移）。"""
        profile = self._profiles.get(hint or "")
        if profile is None:
            return {"intent_hint": hint, "spec": None, "plan_items": [message]}
        return {
            "intent_hint": hint,
            "spec": {
                "intent": hint,
                "depth": profile["depth"],
                "source": "l1_intent_hint",
                "version": "s-layer-v2",
                "recall_count": len(memories),
            },
            "plan_items": list(profile["plan"]),
        }

    @staticmethod
    def _escalate(depth: Optional[str]) -> str:
        idx = DEPTH_ORDER.index(depth) if depth in DEPTH_ORDER else -1
        return DEPTH_ORDER[min(idx + 1, len(DEPTH_ORDER) - 1)]

    def _kickoff(self, reason: str) -> Dict[str, Any]:
        return {
            "skill": KICKOFF_SKILL,
            "mode": "async_stub",
            "reason": reason,
            # SPEC-v1.4 §3.5: 调研确认后 REA 再拆解（为 A 层提供更好的工程架构拆解）
            "post_research_rea": self._rea_fn is not None,
        }

    # -------- SPEC-v1.4 §3.5: 能力调用链 --------

    @staticmethod
    def _top_experience(memories: List[Any], top_k: int = 3) -> List[str]:
        """广义认知系统经验注入：按 score 取 top_k 记忆要点（避免踩坑省去调研）。"""
        def _score(m: Any) -> float:
            if hasattr(m, "score"):
                return float(m.score)
            if isinstance(m, dict):
                return float(m.get("score", 0.0))
            return 0.0

        def _content(m: Any) -> str:
            if hasattr(m, "content"):
                return str(m.content)
            if isinstance(m, dict):
                return str(m.get("content", ""))
            return str(m)

        ranked = sorted(memories, key=_score, reverse=True)
        return [c for c in (_content(m) for m in ranked[:top_k]) if c]

    def _rea_breakdown(self, message: str,
                       hint: Optional[str]) -> tuple:
        """REA 逆向解析拆解 → engineering_okr（为 A 层提供明确工程 OKR）。

        Returns: (engineering_okr | None, degraded: bool) — 全程 FAIL-OPEN。
        """
        if self._rea_fn is None:
            return None, False
        try:
            report = self._rea_fn(hint or message, feature=message)
        except Exception:
            return None, True
        if not isinstance(report, dict):
            return None, True
        okr: List[Dict[str, Any]] = []
        for ev in report.get("evidence") or []:
            if isinstance(ev, dict):
                okr.append({
                    "okr": ev.get("statement") or str(ev),
                    "evidence_id": ev.get("evidence_id"),
                    "source": "rea_evidence",
                })
        for gap in report.get("known_gaps") or []:
            okr.append({"okr": f"补齐: {gap}", "source": "rea_known_gap"})
        return (okr or None), False

    # -------- 主入口 --------

    def __call__(self, message: str, l1_intent_hint: Optional[str],
                 memories: List[Any]) -> Dict[str, Any]:
        hint = l1_intent_hint
        memories = memories or []
        profile = self._profiles.get(hint or "")
        depth = profile["depth"] if profile else None
        explicit_kickoff = any(k in message for k in self._kickoff_keywords)

        # ── S0 入口充分性评估 ──
        entry = evaluate_entry_sufficiency(memories, depth=depth)
        out: Dict[str, Any] = {
            "sufficiency": entry.to_dict(),
            "clarification": None,
            "research_request": None,
            "kickoff_trigger": None,
        }

        if entry.state == SUFFICIENT_DIRECT:
            out["plan"] = {
                "intent_hint": hint,
                "spec": {"intent": hint, "depth": depth,
                         "source": "sufficient_direct",
                         "version": "s-layer-v2",
                         "recall_count": len(memories)},
                "plan_items": [message],
            }
            out["action"] = SUFFICIENT_DIRECT
            return out

        if entry.state == NEED_CLARIFY:
            out["plan"] = {"intent_hint": hint, "spec": None,
                           "plan_items": [message]}
            out["action"] = NEED_CLARIFY
            out["clarification"] = {
                "options": list(self._clarification_options),
                "reasons": entry.reasons,
            }
            return out

        if entry.state == NEED_RESEARCH:
            # 决策点 4：首版打桩（记录需求，不实际执行调研）
            out["research_request"] = {
                "message": message, "intent_hint": hint,
                "match_score": entry.match_score,
                "case_density": entry.case_density,
                "mode": "stub",
            }
            # 决策点 3：仅 depth=deep 或显式关键词触发开工 Skill
            if depth == "deep":
                out["kickoff_trigger"] = self._kickoff("deep_research")
            elif explicit_kickoff:
                out["kickoff_trigger"] = self._kickoff("explicit_keyword")
        elif explicit_kickoff:
            out["kickoff_trigger"] = self._kickoff("explicit_keyword")

        # ── S1 规划展开 ──
        plan = self._expand(message, hint, memories, depth)

        # ── S2 充分性再评估（NEED_DEEPER 时逐级升级到 deep）──
        current_depth = (plan.get("spec") or {}).get("depth") or depth
        exit_eval = evaluate_plan_sufficiency(plan, memories, depth=current_depth)
        while exit_eval.state == NEED_DEEPER and current_depth != "deep":
            current_depth = self._escalate(current_depth)
            plan["plan_items"].append(GENERIC_DEEPENING_ITEM)
            if plan.get("spec") is not None:
                plan["spec"]["depth"] = current_depth
            exit_eval = evaluate_plan_sufficiency(
                plan, memories, depth=current_depth)
        out["plan_sufficiency"] = exit_eval.to_dict()

        if exit_eval.state == EARLY_TERMINATE:
            out["plan"] = plan
            out["action"] = EARLY_TERMINATE
            return out
        if exit_eval.state == NEED_CLARIFY:
            out["plan"] = plan
            out["action"] = NEED_CLARIFY
            out["clarification"] = {
                "options": list(self._clarification_options),
                "reasons": exit_eval.reasons,
            }
            return out

        # ── SPEC-v1.4 §3.5 能力调用链：认知经验注入 + REA 工程拆解 ──
        plan["cognitive_experience"] = self._top_experience(memories)
        engineering_okr, rea_degraded = self._rea_breakdown(message, hint)
        if engineering_okr:
            plan["engineering_okr"] = engineering_okr
        out["rea_degraded"] = rea_degraded

        out["plan"] = plan
        out["action"] = "PROCEED"
        return out


class SACGOrchestrator:
    """C-drive 全程调度者：S→A→C→G 编排骨架。

    各层以可注入函数预留扩展点（P3.2-P3.5 接入实质实现）:
        s_planner(message, l1_intent_hint, memories) -> plan dict
        a_decomposer(plan) -> nodes: List[{"node_id","criteria"}]
        g_closer(plan, node_results) -> closure dict
    C 层节点决策固定委托 CDriveV3Router（可用 c_executor 覆盖测试）。
    """

    def __init__(
        self,
        *,
        router: Optional[Any] = None,
        recall_fn: Optional[Callable] = None,
        s_planner: Optional[Callable] = None,
        a_decomposer: Optional[Callable] = None,
        c_executor: Optional[Callable] = None,
        g_closer: Optional[Callable] = None,
        record_fn: Optional[Callable] = None,
        verify_fn: Optional[Callable] = None,
        limiter: Optional[Any] = None,
    ):
        self._router = router if router is not None else CDriveV3Router()
        self._recall_fn = recall_fn
        # SPEC-v1.4: 默认规划器实质化为 SLayerPlanner（充分性状态机）；
        # 注入旧契约 s_planner（返回裸 plan dict）仍兼容
        self._s_planner = s_planner or SLayerPlanner()
        self._a_decomposer = a_decomposer or self._default_a_decomposer
        self._c_executor = c_executor  # (router, node) -> node_result dict
        self._g_closer = g_closer or self._default_g_closer
        # P3.5: 认知分流注入点（测试用 fake，避免真实 MCP 调用；None 走默认）
        self._record_fn = record_fn
        self._verify_fn = verify_fn
        self._limiter = limiter

    # -------- 默认骨架实现（P3.2/P3.3/P3.5 替换） --------

    @staticmethod
    def _default_s_planner(message: str, l1_intent_hint: Optional[str],
                           memories: List[Any]) -> Dict[str, Any]:
        """S 层默认规划（P3.2 深化）：消费 l1_intent_hint 先验。

        hint 命中 S_LAYER_INTENT_PROFILES → 按意图档案展开 plan_items，
        并产出 Spec 草案 {intent, depth, source}；未命中/缺省 → 单条兜底。
        """
        profile = S_LAYER_INTENT_PROFILES.get(l1_intent_hint or "")
        if profile is None:
            return {
                "intent_hint": l1_intent_hint,
                "spec": None,
                "plan_items": [message],
            }
        return {
            "intent_hint": l1_intent_hint,
            "spec": {
                "intent": l1_intent_hint,
                "depth": profile["depth"],
                "source": "l1_intent_hint",
                "version": "s-layer-v1",
                "recall_count": len(memories),
            },
            "plan_items": list(profile["plan"]),
        }

    @staticmethod
    def _default_a_decomposer(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        # P3.3: A 层实质化为 OKR 节点验收体系（core/okr_nodes.py）
        # engineering_okr 存在时优先消费（更具体的 OKR 节点）
        return decompose_okr_nodes(plan)

    def _default_g_closer(self, plan: Dict[str, Any],
                          node_results: List[Dict[str, Any]],
                          acceptance: Optional[Dict[str, Any]] = None
                          ) -> Dict[str, Any]:
        """P3.5: G 层四分流沉淀路由（规则化，禁新阈值，全程 FAIL-OPEN）。

        消费 A 层验收结果:
          案例分流: verdict==pass 且有节点 → case 描述符（async_stub）
          流程分流: red_flags 非空 → skill 描述符（async_stub）
          文档分流: 存在 degraded 节点 → doc 描述符 pending=[node_ids]
          认知分流（必走）: 委托 cognitive_loop.close_loop，
            verdict → outcome（pass→success/degraded→partial/fail→failure）
        acceptance=None 时 FAIL-OPEN 退化为只走认知分流。
        sediments 均为打桩描述符，真实触发归会话级收尾 Skill。
        """
        sediments: List[Dict[str, Any]] = []
        verdict: Optional[str] = None
        try:
            if isinstance(acceptance, dict):
                verdict = acceptance.get("verdict")
                node_ids = [str(r.get("node_id")) for r in (node_results or [])
                            if isinstance(r, dict) and r.get("node_id")]
                # 案例分流
                if verdict == VERDICT_PASS and node_ids:
                    sediments.append({"type": "case", "mode": SEDIMENT_ASYNC_STUB,
                                      "nodes": node_ids})
                # 流程分流
                red_flags = [str(x) for x in (acceptance.get("red_flags") or [])]
                if red_flags:
                    sediments.append({"type": "skill", "mode": SEDIMENT_ASYNC_STUB,
                                      "red_flags": red_flags})
                # 文档分流
                pending = [str(v.get("node_id"))
                           for v in (acceptance.get("node_verdicts") or [])
                           if isinstance(v, dict) and v.get("verdict") == "degraded"]
                if pending:
                    sediments.append({"type": "doc", "mode": SEDIMENT_ASYNC_STUB,
                                      "pending": pending})
        except Exception:
            # FAIL-OPEN: 分流路由异常不影响认知闭环
            sediments = []

        # 认知分流（必走；close_loop 自身 FAIL-OPEN）
        outcome = G_OUTCOME_MAP.get(str(verdict), "partial")
        cognitive = close_loop(
            decision="g_layer_closure",
            outcome=outcome,
            content=(f"G层收尾: verdict={verdict or 'none'} "
                     f"nodes={len(node_results or [])} "
                     f"sediments={[s['type'] for s in sediments]}"),
            tags="SACG,G层,四分流",
            record_fn=self._record_fn,
            verify_fn=self._verify_fn,
            limiter=self._limiter,
        )
        # P1.5 埋点（spec §9.1 SACG 域采集点）：编排收尾摘要写入案例库，FAIL-OPEN
        try:
            from datetime import datetime as _dt
            _case = {
                "ts": _dt.now().isoformat(timespec="seconds"),
                "schema_version": "v2",
                "case_type": "sacg_orchestration",
                "payload": {
                    "verdict": verdict,
                    "node_count": len(node_results or []),
                    "sediment_types": [s.get("type") for s in sediments],
                    "cognitive_outcome": (cognitive or {}).get("outcome"),
                },
            }
            _store = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "l1_case_store.jsonl")
            with open(_store, "a", encoding="utf-8") as _f:
                _f.write(json.dumps(_case, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return {"compressed": True, "settled": True,
                "sediments": sediments, "cognitive": cognitive}

    # -------- 召回 --------

    def _do_recall(self, message: str, hint: Optional[str]) -> List[Any]:
        if self._recall_fn is None:
            return []
        try:
            return self._recall_fn(
                context=f"{hint or ''}::{message}".strip(":"),
                top_k=5,
                min_quality="C",
            ) or []
        except Exception:
            return []

    # -------- C 层：节点执行（委托 C-drive 决策门） --------

    def _run_node(self, node: Dict[str, Any],
                  l1_intent_hint: Optional[str] = None) -> Dict[str, Any]:
        node_id = str(node.get("node_id") or "N?")
        node_result = SimpleNamespace(
            confidence=float(node.get("confidence", 0.5)),
            direction=node.get("direction", "NEUTRAL"),
        )
        if self._c_executor is not None:
            raw = self._c_executor(self._router, node)
        else:
            # P3.2: hint 透传节点决策门（run_v3 注入 recall context）
            raw = self._router.run_v3(
                node_id=node_id,
                result=node_result,
                state={},
                signals=None,
                l1_intent_hint=l1_intent_hint,
            )
        return {
            "node_id": node_id,
            "action": raw.get("action", "CONTINUE"),
            "tier": raw.get("tier"),
            "effort_level": raw.get("effort_level"),
            "detail": raw,
        }

    # -------- 主入口 --------

    def handle(
        self,
        message: str,
        l1_intent_hint: Optional[str] = None,
        memories: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """处理一个 L2 请求：门控 → S→A→C→G（全程 FAIL-OPEN）。"""
        if memories is None:
            memories = self._do_recall(message, l1_intent_hint)

        signal = evaluate_route(memories)
        signal_dict = signal.to_dict()

        if signal.decision == L1_DIRECT:
            return {
                "route": L1_DIRECT,
                "orchestrated": False,
                "stages": [],
                "route_signal": signal_dict,
                "plan": None,
                "nodes": [],
                "node_results": [],
                "closure": None,
                "acceptance": None,
                "degraded": False,
                "errors": [],
                "action": L1_DIRECT,
                "sufficiency": None,
                "clarification": None,
                "research_request": None,
                "kickoff_trigger": None,
            }

        errors: List[str] = []

        # ── S 层：认知驱动规划入口（SPEC-v1.4 充分性状态机） ──
        action = "PROCEED"
        sufficiency = None
        clarification = None
        research_request = None
        kickoff_trigger = None
        try:
            plan = self._s_planner(message, l1_intent_hint, memories)
        except Exception as e:
            errors.append(f"{STAGE_S}:{type(e).__name__}:{e}")
            plan = {"intent_hint": l1_intent_hint, "plan_items": []}

        # 新契约解包（SLayerPlanner）；旧契约裸 plan dict 直接透传
        if isinstance(plan, dict) and "plan" in plan and "action" in plan:
            meta = plan
            plan = meta.get("plan") or {"plan_items": []}
            action = meta.get("action", "PROCEED")
            sufficiency = meta.get("sufficiency")
            clarification = meta.get("clarification")
            research_request = meta.get("research_request")
            kickoff_trigger = meta.get("kickoff_trigger")

        # 充分性短路：问用户 / 提前终止 → 流程停在 S 层
        if action in (NEED_CLARIFY, EARLY_TERMINATE):
            return {
                "route": L2_HANDOFF,
                "orchestrated": True,
                "stages": [STAGE_S],
                "route_signal": signal_dict,
                "plan": plan,
                "nodes": [],
                "node_results": [],
                "closure": None,
                "acceptance": None,
                "degraded": bool(errors),
                "errors": errors,
                "action": action,
                "sufficiency": sufficiency,
                "clarification": clarification,
                "research_request": research_request,
                "kickoff_trigger": kickoff_trigger,
            }

        # ── A 层：OKR 节点分解 ──
        # research_request 存在时透传给 A 层做 domain 分流（金融调研四维验收）
        try:
            plan_for_a = plan
            if (research_request and isinstance(plan, dict)
                    and "research_request" not in plan):
                plan_for_a = {**plan, "research_request": research_request}
            nodes = self._a_decomposer(plan_for_a) or []
        except Exception as e:
            errors.append(f"{STAGE_A}:{type(e).__name__}:{e}")
            nodes = []

        # ── C 层：逐节点执行（节点级异常隔离，不阻断其余节点） ──
        # P3.2: S 层消费的 hint 透传到 C 层节点决策门
        node_results: List[Dict[str, Any]] = []
        for node in nodes:
            try:
                node_results.append(
                    self._run_node(node, l1_intent_hint=l1_intent_hint))
            except Exception as e:
                node_id = str(node.get("node_id") or "N?")
                errors.append(f"{STAGE_C}:{node_id}:{type(e).__name__}:{e}")
                node_results.append({
                    "node_id": node_id,
                    "action": NODE_FAILED,
                    "tier": None,
                    "effort_level": None,
                    "detail": None,
                    "error": str(e),
                })

        # ── A 层验收：C 层执行结果回传 OKR 节点验收（P3.4，对账式逐节点核对） ──
        try:
            acceptance = evaluate_nodes(nodes, node_results)
        except Exception as e:
            errors.append(f"{STAGE_A}:{type(e).__name__}:{e}")
            acceptance = None

        # ── G 层：图压缩 + 收尾钩子（P3.5: acceptance 消费四分流） ──
        try:
            try:
                closure = self._g_closer(plan, node_results, acceptance)
            except TypeError:
                # 兼容旧契约注入 g_closer(plan, node_results)
                closure = self._g_closer(plan, node_results)
        except Exception as e:
            errors.append(f"{STAGE_G}:{type(e).__name__}:{e}")
            closure = {"compressed": False, "settled": False}

        return {
            "route": L2_HANDOFF,
            "orchestrated": True,
            "stages": list(SACG_STAGES),
            "route_signal": signal_dict,
            "plan": plan,
            "nodes": nodes,
            "node_results": node_results,
            "closure": closure,
            "acceptance": acceptance,
            "degraded": bool(errors),
            "errors": errors,
            "action": action,
            "sufficiency": sufficiency,
            "clarification": clarification,
            "research_request": research_request,
            "kickoff_trigger": kickoff_trigger,
        }
