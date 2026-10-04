#!/usr/bin/env python3
"""OrchestrationOptimizerAgent — A 层编排优化 subagent

当 IntentResult.confidence < OPTIMIZE_TRIGGER_THRESHOLD (0.70) 或
complexity_tier >= "T2" 时触发, 对执行计划进行动态优化:
    1. cognitive_adapter.recall() 检索编排模式历史
    2. LLM 根据意图复杂度动态扩展/裁剪 extend_nodes
    3. 根据 runtime_signals 调整执行深度

设计原则:
    - FAIL-OPEN: 无 llm_fn → 规则降级（原 plan 透传）; 异常 → 安全默认
    - 认知闭环: recall 检索历史 → record 记录新优化结果
    - 不替换 GraphPlanner 原有规划逻辑, 仅增强
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class PlanOptimization:
    """A 层编排优化结果

    Attributes:
        add_nodes: 需新增的节点 ID 列表
        remove_nodes: 需移除的节点 ID 列表
        reorder: 节点优先级重排 (node_id → new_priority)
        budget_adjustment: 预算调整 (node_id → delta)
        keep_static_fallback: 是否保留静态回退 (默认 True)
        reasoning: 优化推理过程 (用于 record)
    """
    add_nodes: List[str] = field(default_factory=list)
    remove_nodes: List[str] = field(default_factory=list)
    reorder: Optional[Dict[str, int]] = None
    budget_adjustment: Optional[dict] = None
    keep_static_fallback: bool = True
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "add_nodes": self.add_nodes,
            "remove_nodes": self.remove_nodes,
            "reorder": self.reorder,
            "budget_adjustment": self.budget_adjustment,
            "keep_static_fallback": self.keep_static_fallback,
            "reasoning": self.reasoning,
        }


# ============================================================
# OrchestrationOptimizerAgent
# ============================================================

class OrchestrationOptimizerAgent:
    """A 层编排优化 subagent

    用法:
        agent = OrchestrationOptimizerAgent(llm_fn=my_llm, cognitive_adapter=adapter)
        optimization = agent.optimize(plan, intent, runtime_signals)
    """

    # 优化触发阈值：confidence < 此值时触发 LLM 优化
    OPTIMIZE_TRIGGER_THRESHOLD = 0.70

    def __init__(
        self,
        llm_fn: Optional[Callable[[str], str]] = None,
        cognitive_adapter: Optional[Any] = None,
    ):
        """初始化编排优化器

        Args:
            llm_fn: LLM 调用函数 (prompt: str) -> str, 返回 JSON 字符串.
                None 时走 _rule_based_optimize 规则降级 (FAIL-OPEN).
            cognitive_adapter: 认知适配器, 需有 recall(context, top_k, min_quality)
                和 record(content, tags, quality_level). None 时跳过认知闭环.
        """
        self._llm_fn = llm_fn
        self._cognitive = cognitive_adapter

    # ── 主入口 ──────────────────────────────────────────

    def optimize(
        self,
        plan: Any,
        intent: Dict[str, Any],
        runtime_signals: Dict[str, Any],
    ) -> PlanOptimization:
        """优化执行计划

        Args:
            plan: ExecutionPlan 对象
            intent: 意图信息 (confidence, intent_type, complexity_tier 等)
            runtime_signals: 运行时信号 (data_quality 等)

        Returns:
            PlanOptimization: 优化建议
        """
        confidence = intent.get("confidence", 0.0)
        complexity = intent.get("complexity_tier", "T1")

        # 高置信度 + 简单意图 → 不触发优化
        if confidence >= self.OPTIMIZE_TRIGGER_THRESHOLD and complexity not in ("T2", "T3"):
            return PlanOptimization(
                keep_static_fallback=True,
                reasoning=f"confidence={confidence:.2f} >= {self.OPTIMIZE_TRIGGER_THRESHOLD}, skip optimization",
            )

        # 认知闭环 Step 1: recall 检索历史编排优化经验 (FAIL-OPEN)
        recalled = self._recall(intent, plan)

        # LLM 优化或规则降级
        if self._llm_fn is None:
            return self._rule_based_optimize(plan, intent, recalled)

        try:
            return self._llm_optimize(plan, intent, runtime_signals, recalled)
        except Exception:  # noqa: BLE001 FAIL-OPEN
            traceback.print_exc()
            return PlanOptimization(
                keep_static_fallback=True,
                reasoning="LLM optimization failed, FAIL-OPEN passthrough",
            )

    # ── LLM 路径 ────────────────────────────────────────

    def _llm_optimize(
        self,
        plan: Any,
        intent: Dict[str, Any],
        runtime_signals: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> PlanOptimization:
        """LLM 优化路径"""
        prompt = self._build_prompt(plan, intent, runtime_signals, recalled)
        resp = self._llm_fn(prompt)  # type: ignore[misc]
        parsed = self._parse_llm_response(resp)

        result = PlanOptimization(
            add_nodes=parsed.get("add_nodes", []),
            remove_nodes=parsed.get("remove_nodes", []),
            reorder=parsed.get("reorder"),
            budget_adjustment=parsed.get("budget_adjustment"),
            keep_static_fallback=False,
            reasoning=parsed.get("reasoning", ""),
        )

        # 认知闭环 Step 2: record 记录本次优化 (FAIL-OPEN)
        self._record_optimize(result, intent)

        return result

    def _build_prompt(
        self,
        plan: Any,
        intent: Dict[str, Any],
        runtime_signals: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> str:
        """构建 LLM 优化 prompt"""
        chain = getattr(plan, "planned_chain", "")
        rationale = getattr(plan, "rationale", "")
        selected = [getattr(n, "node_id", str(n)) for n in
                    getattr(plan, "selected_nodes", [])]
        confidence = intent.get("confidence", 0.0)
        complexity = intent.get("complexity_tier", "T1")

        recalled_str = ""
        if recalled:
            recalled_str = "\n".join(
                f"- {r.get('content', '')[:120]}" for r in recalled[:3]
            )

        return f"""你是 DreamOS 编排优化器。请优化以下执行计划。

## 当前执行计划
- chain: {chain}
- selected_nodes: {selected}
- rationale: {rationale}

## 意图信息
- confidence: {confidence:.2f}
- complexity_tier: {complexity}
- intent_type: {intent.get('intent_type', 'uncertain')}

## 运行时信号
{json.dumps(runtime_signals, ensure_ascii=False, default=str) or '{}'}

## 历史编排经验
{recalled_str or "(无)"}

## 任务
根据意图置信度和复杂度, 优化执行计划:
- 低置信度 → 增加验证/情报节点
- 高复杂度 → 增加深度分析节点
- 数据质量差 → 减少依赖高质量数据的节点

返回 JSON:
{{
    "add_nodes": ["节点ID"],
    "remove_nodes": ["节点ID"],
    "reorder": {{"node_id": priority}} 或 null,
    "budget_adjustment": {{"node_id": delta}} 或 null,
    "reasoning": "优化推理"
}}"""

    def _parse_llm_response(self, resp: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON"""
        resp = resp.strip()
        if resp.startswith("```"):
            lines = resp.split("\n")
            resp = "\n".join(lines[1:-1]) if len(lines) > 2 else resp
        return json.loads(resp)

    # ── 规则降级 ────────────────────────────────────────

    def _rule_based_optimize(
        self,
        plan: Any,
        intent: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> PlanOptimization:
        """规则降级优化 (FAIL-OPEN)

        无 LLM 时, 基于规则和历史经验做简单调整:
        - 低置信度 + 有历史命中 → 建议增加验证节点
        - 否则 → 透传
        """
        confidence = intent.get("confidence", 0.0)

        if confidence < 0.50 and recalled:
            return PlanOptimization(
                add_nodes=["A7"],  # 实践论门禁验证节点
                keep_static_fallback=True,
                reasoning=f"rule-based: low confidence + recalled, suggest A7 verification",
            )

        return PlanOptimization(
            keep_static_fallback=True,
            reasoning="rule-based: no optimization needed",
        )

    # ── 认知闭环 ────────────────────────────────────────

    def _recall(
        self,
        intent: Dict[str, Any],
        plan: Any,
    ) -> List[Dict[str, Any]]:
        """检索历史编排优化经验 (FAIL-OPEN)"""
        if self._cognitive is None:
            return []
        try:
            chain = getattr(plan, "planned_chain", "")
            conf = intent.get("confidence", 0.0)
            recall_ctx = f"A层 编排优化 chain={chain} confidence={conf:.2f}"
            return self._cognitive.recall(
                context=recall_ctx,
                top_k=5,
                min_quality="C",
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return []

    def _record_optimize(self, result: PlanOptimization, intent: Dict[str, Any]) -> None:
        """记录优化结果到认知系统 (FAIL-OPEN)"""
        if self._cognitive is None:
            return
        try:
            content = (
                f"[A层编排优化] intent={intent.get('intent_type', 'N/A')}, "
                f"add={result.add_nodes}, remove={result.remove_nodes}, "
                f"reasoning={result.reasoning[:100]}"
            )
            self._cognitive.record(
                content=content,
                tags="A层训练,编排优化,orchestration_optimizer",
                quality_level="B",
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
