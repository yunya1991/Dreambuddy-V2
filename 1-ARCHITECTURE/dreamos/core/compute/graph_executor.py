"""
DreamOS C层 — 图执行器 (GraphExecutor)

C 层主入口，职责:
    1. 接收 A 层构建的 Graph 和 State
    2. 逐节点执行（通过 NodeRunner）
    3. 每步反射决策（通过 Reflector）
    4. 支持条件跳转、前插、提前终止
    5. 自动保存检查点（每节点后 / 反射前 / 关键节点）
    6. 执行完毕后聚合结果（通过 Aggregator）
    7. 输出 ExecutionReport

执行流程:
    Graph.get_entry()
        ↓
    检查点（反射前）
        ↓
    NodeRunner.run(node, state)
        ↓
    检查点（节点后）
        ↓
    Reflector.decide(result, state)
        ↓
    ┌──┴──────────────────────────┐
    CONTINUE  REDO  INSERT  JUMP  TERMINATE
    ↓         ↓     ↓        ↓       ↓
    next_node redo  insert  jump  aggregate
    ↓
    ...循环...
    ↓
    Aggregator.aggregate(state)
    ↓
    ExecutionReport
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Callable, Dict, List, Optional

from dreamos.shared.interfaces import Graph
from dreamos.shared.state import State
from dreamos.shared.utils import Timer

from .aggregator import Aggregator
from .node_runner import NodeRunner
from .reflector import Reflector
from .tripwire import (
    TRIPWIRE_MODES,
    VERDICT_BLOCK,
    TripwireRegistry,
    default_registry,
)
from .types import (
    PARKED_REASONS,
    ExecutionReport,
    ReflectAction,
)

logger = logging.getLogger(__name__)


GATE_NODES = {"A4", "A7", "G1"}

# trace_id / run_id 合法字符集（与 stop_reason.schema.json pattern 对齐）
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,64}$")


class GraphExecutor:
    """图执行器 — C 层主入口

    用法:
        executor = GraphExecutor()
        report = executor.execute(graph, state)
        print(report.final_action)
        print(report.final_confidence)
        print(report.success_rate)

    带 A 层计划:
        from dreamos.core.arrange import GraphPlanner
        planner = GraphPlanner()
        plan = planner.plan(state)
        graph = planner.build_graph(plan)
        report = executor.execute(graph, state, plan=plan)
    """

    def __init__(
        self,
        max_retries: int = 2,
        enable_reflect: bool = True,
        enable_early_terminate: bool = True,
        max_steps: int = 20,
        timeout_ms: int = 30000,
        enable_checkpoint: bool = True,
        graph_store: Optional[Any] = None,
        registry: Optional[Any] = None,
        tripwire_registry: Optional[TripwireRegistry] = None,
        tripwire_mode: str = "shadow",
        max_inserts: int = 5,
        enable_auto_compress: bool = True,
    ):
        self._runner = NodeRunner(
            max_retries=max_retries,
            timeout_ms=timeout_ms,
        )
        self._reflector = Reflector(
            max_retries_per_node=max_retries,
            enable_early_terminate=enable_early_terminate,
        )
        self._aggregator = Aggregator()
        self._enable_reflect = enable_reflect
        self._max_steps = max_steps
        self._enable_checkpoint = enable_checkpoint
        self._graph_store = graph_store
        self._registry = registry
        self._tripwire_registry = tripwire_registry or default_registry()
        self._tripwire_mode = tripwire_mode if tripwire_mode in TRIPWIRE_MODES else "shadow"
        self._max_inserts = max(0, max_inserts)
        self._enable_auto_compress = enable_auto_compress

    def execute(
        self,
        graph: Graph,
        state: State,
        plan: Optional[Any] = None,
        budget: Optional[Dict[str, int]] = None,
        total_budget: int = 0,
        graph_store: Optional[Any] = None,
        soft_budget: Optional[int] = None,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        resume_from: Optional[str] = None,
        cu_per_token: float = 0.0,
        should_interrupt: Optional[Callable[[], bool]] = None,
        tripwire_ids: Optional[List[str]] = None,
        tripwire_mode: Optional[str] = None,
    ) -> ExecutionReport:
        """执行图

        循环出口统一为 stop_reason（stop_reason.schema.json v1.1）:
            done / error / interrupted / parked / cost_limit / max_steps / no_next_context

        Args:
            graph: A 层构建的执行图
            state: 全局状态
            plan: A 层的执行计划（可选，用于预算分配）
            budget: 节点预算 {node_id: tokens}（可选）
            total_budget: 硬预算 tokens（触顶即 cost_limit，可续跑）
            graph_store: G 层存储实例（用于自动检查点，优先使用）
            soft_budget: 软预算 tokens（触顶即软收尾 done，不消耗剩余节点）
            trace_id: 全链路追踪 ID（缺省自动生成）
            run_id: 运行 ID（缺省取 state.cycle_id，再缺省自动生成）
            resume_from: 独立恢复入口（从指定节点开始，缺省从图入口开始）
            cu_per_token: token → cost_cu 换算系数（缺省 0.0，不做换算）
            should_interrupt: 外部中断检查回调（每步前调用，返回 True 即中断）

        Returns:
            ExecutionReport: 执行报告（report.stop_contract() 为唯一出口契约）
        """
        timer = Timer("graph_executor")
        report = ExecutionReport()
        report.trace_id = self._normalize_trace_id(trace_id)
        report.run_id = self._normalize_run_id(run_id, state)

        store = graph_store or self._graph_store

        budget = budget or {}
        if plan and hasattr(plan, "budget") and plan.budget:
            budget = plan.budget.allocated
            plan_total = getattr(plan.budget, "total_budget", None)
            if plan_total is None:
                plan_total = getattr(plan.budget, "total", None)
            if not total_budget and plan_total:
                total_budget = plan_total

        current = None
        if resume_from and hasattr(graph, "get_node"):
            current = graph.get_node(resume_from)
            if current is None:
                logger.warning(f"resume_from={resume_from} 未找到，回退到图入口")
        if current is None:
            current = graph.get_entry()
        if current is None:
            report.termination_reason = "图中无入口节点"
            report.stop_reason = "error"
            report.stop_detail = {"reason": report.termination_reason}
            return report

        all_node_ids = graph.topological_order()
        report.total_nodes = len(all_node_ids)

        executed_ids: List[str] = []
        redo_counts: Dict[str, int] = {}  # 跟踪每个节点的 REDO 次数
        step = 0
        used_budget = 0
        insert_count = 0
        active_tripwires = list(tripwire_ids or [])
        active_tripwire_mode = (
            tripwire_mode if tripwire_mode in TRIPWIRE_MODES else self._tripwire_mode
        )

        while current is not None and step < self._max_steps:
            # ── 外部中断（每步前检查，保留当前节点为恢复入口）──
            if should_interrupt is not None and should_interrupt():
                report.stop_reason = "interrupted"
                report.resume_from = current.node_id
                report.stop_detail = {"step": step, "next_node_id": current.node_id}
                break

            step += 1
            node_id = current.node_id

            if node_id in executed_ids:
                current = graph.get_next(node_id, state)
                continue

            is_gate = node_id in GATE_NODES

            # ── 检查点：门禁节点前（额外强制保存）─────────
            if is_gate and self._enable_checkpoint and store:
                store.checkpoint(
                    state,
                    node_id=node_id,
                    metadata={"phase": "pre_gate", "step": step, "is_gate": True},
                )

            # ── 检查点：反射前（节点执行前）─────────
            if self._enable_checkpoint and store:
                store.checkpoint(
                    state, node_id=node_id, metadata={"phase": "pre_reflect", "step": step}
                )

            # ── 执行节点 ──────────────────────────
            allocated = budget.get(node_id, 0)
            record = self._runner.run(current, state, allocated)
            report.add_record(record)
            executed_ids.append(node_id)
            used_budget += record.tokens_used

            # ── 检查点：节点执行后 ─────────────────
            if self._enable_checkpoint and store:
                store.checkpoint(
                    state,
                    node_id=node_id,
                    metadata={
                        "phase": "post_node",
                        "step": step,
                        "is_gate": is_gate,
                        "tokens_used": record.tokens_used,
                    },
                )

            # ── 检查点：门禁节点后（额外强制保存，供回滚）──
            if is_gate and self._enable_checkpoint and store:
                store.checkpoint(
                    state,
                    node_id=node_id,
                    metadata={
                        "phase": "post_gate",
                        "step": step,
                        "is_gate": True,
                        "status": (
                            record.status.value
                            if hasattr(record.status, "value")
                            else str(record.status)
                        ),
                    },
                )

            # ── 45 tripwire：门禁节点评估（shadow 记录 / hard 熔断）──
            if active_tripwires and node_id in GATE_NODES:
                if self._run_tripwires(
                    active_tripwires,
                    state,
                    report,
                    checkpoint="post_gate",
                    node_id=node_id,
                    mode=active_tripwire_mode,
                ):
                    break

            # ── 循环内自动压缩（GAP-26：不等检查点，按阈值触发）──
            if self._enable_auto_compress and store is not None:
                self._maybe_compress(store, state, report)

            # ── 挂起：节点等待外部输入（人工/异步工具/客户端）──
            if record.status == "parked":
                parked_reason = getattr(state.get_result(node_id), "parked_reason", None)
                if parked_reason not in PARKED_REASONS:
                    parked_reason = "waiting_for_human"
                report.stop_reason = "parked"
                report.parked_reason = parked_reason
                report.resume_from = node_id
                report.stop_detail = {"node_id": node_id, "step": step}
                break

            # ── 预算出口：硬停 cost_limit 优先于软收尾 done ──
            if total_budget > 0 and used_budget >= total_budget:
                nxt = graph.get_next(node_id, state)
                next_node_id = nxt.node_id if nxt else None
                report.stop_reason = "cost_limit"
                report.resume_from = next_node_id
                report.stop_detail = {
                    "hard_budget": total_budget,
                    "tokens_used": used_budget,
                    "next_node_id": next_node_id,
                }
                break
            if soft_budget and soft_budget > 0 and used_budget >= soft_budget:
                nxt = graph.get_next(node_id, state)
                report.stop_reason = "done"
                report.stop_detail = {
                    "soft_budget_reached": True,
                    "soft_budget": soft_budget,
                    "tokens_used": used_budget,
                    "next_node_id": nxt.node_id if nxt else None,
                }
                break

            # ── 反射决策 ──────────────────────────
            if self._enable_reflect:
                remaining_ratio = None
                if total_budget > 0:
                    remaining_ratio = max(0.0, 1.0 - used_budget / total_budget)

                decision = self._reflector.decide(
                    current_node_id=node_id,
                    result=state.get_result(node_id),
                    state=state,
                    graph=graph,
                    executed_count=report.executed_nodes,
                    max_nodes=report.total_nodes,
                    record=record,
                    budget_remaining_ratio=remaining_ratio,
                    total_budget=total_budget,
                    used_budget=used_budget,
                )

                report.reflect_history.append(
                    {
                        "node_id": node_id,
                        **decision.to_dict(),
                    }
                )

                action = decision.action
                if action == ReflectAction.EARLY_TERMINATE:
                    report.early_terminated = True
                    report.termination_reason = decision.reason
                    report.stop_reason = "done"
                    report.stop_detail = {
                        "early_terminated": True,
                        "reason": decision.reason,
                    }
                    break
                elif action == ReflectAction.JUMP_TO:
                    jump_node = (
                        graph.get_node(decision.jump_to) if hasattr(graph, "get_node") else None
                    )
                    if jump_node:
                        current = jump_node
                        continue
                elif action == ReflectAction.REDO:
                    redo_counts[node_id] = redo_counts.get(node_id, 0) + 1
                    # Reflector 的 record.retries 不可靠 (每次 REDO 创建新 record),
                    # 在此强制限制: 超过 max_retries 时跳到下一节点, 避免
                    # 低置信度节点无限 REDO 耗尽 max_steps 导致 A5/A9 永不执行
                    if redo_counts[node_id] > self._runner._max_retries:
                        logger.warning(
                            f"节点 {node_id} REDO 次数超限 "
                            f"({redo_counts[node_id]} > {self._runner._max_retries}), "
                            f"强制跳到下一节点"
                        )
                        current = graph.get_next(node_id, state)
                        continue
                    if node_id in executed_ids:
                        executed_ids.remove(node_id)
                    continue
                elif action == ReflectAction.INSERT_BEFORE:
                    insert_id = decision.insert_node_id
                    if insert_id:
                        if insert_count >= self._max_inserts:
                            logger.warning(
                                f"插入次数超限 ({insert_count} >= {self._max_inserts})，"
                                f"跳过插入 {insert_id}"
                            )
                            continue
                        insert_node = None
                        if self._registry and hasattr(self._registry, "get"):
                            insert_node = self._registry.get(insert_id)
                        if insert_node is None and hasattr(graph, "get_node"):
                            insert_node = graph.get_node(insert_id)
                        if insert_node and hasattr(graph, "insert_before"):
                            try:
                                ok = graph.insert_before(node_id, insert_node)
                                if ok:
                                    insert_count += 1
                                    report.total_nodes += 1
                                    current = insert_node
                                    continue
                            except Exception:
                                pass
                    continue
                elif action == ReflectAction.SKIP:
                    pass

            current = graph.get_next(node_id, state)

        self._aggregator.aggregate(state, executed_ids, report)
        self._aggregator.update_state(state, report)

        report.steps = step
        report.cost_cu = round(used_budget * cu_per_token, 6)

        # ── 出口收敛：loop 正常结束 / 步数上限 ────────────
        if report.stop_reason is None:
            if current is not None and step >= self._max_steps:
                report.stop_reason = "max_steps"
                report.resume_from = current.node_id
                report.stop_detail = {
                    "max_steps": self._max_steps,
                    "next_node_id": current.node_id,
                }
            else:
                report.stop_reason = "done"

        # ── 出口 tripwire：hard 模式 BLOCK 覆盖 done → error（fail-closed）──
        if active_tripwires and not report.stop_detail.get("tripwire"):
            self._run_tripwires(
                active_tripwires,
                state,
                report,
                checkpoint="end",
                node_id=None,
                mode=active_tripwire_mode,
            )

        with timer:
            pass

        return report

    # ── 内部方法 ──────────────────────────

    def _run_tripwires(
        self,
        tripwire_ids: List[str],
        state: State,
        report: ExecutionReport,
        checkpoint: str,
        node_id: Optional[str],
        mode: str,
    ) -> bool:
        """评估 tripwire；返回 True 表示 hard 模式已熔断（调用方需停止循环）"""
        results = self._tripwire_registry.evaluate_all(
            tripwire_ids,
            {"state": state, "report": report, "checkpoint": checkpoint},
            checkpoint=checkpoint,
            node_id=node_id,
        )
        report.tripwire_history.extend(r.to_dict() for r in results)

        blocking = [r for r in results if r.verdict == VERDICT_BLOCK]
        if not blocking:
            return False

        if mode != "hard":
            logger.warning(
                "tripwire BLOCK（shadow 放行）: "
                + ", ".join(f"{r.tripwire_id}@{checkpoint}" for r in blocking)
            )
            return False

        first = blocking[0]
        report.stop_reason = "error"
        report.resume_from = None
        report.stop_detail = {
            "tripwire": first.tripwire_id,
            "verdict": first.verdict,
            "checkpoint": checkpoint,
            "node_id": node_id,
            "detail": first.detail,
        }
        logger.error(f"tripwire 熔断: {first.tripwire_id}@{checkpoint} {first.detail}")
        return True

    def _maybe_compress(self, store: Any, state: State, report: ExecutionReport) -> None:
        """循环内按阈值自动压缩（FAIL-OPEN，异常不影响执行）"""
        try:
            compressor = getattr(store, "compressor", None)
            if compressor is None or not compressor.should_compress(state):
                return
            store.compress(state)
            report.compression_count += 1
        except Exception as exc:  # 压缩失败不阻塞主链路
            logger.debug(f"循环内压缩跳过: {exc}")

    def _normalize_trace_id(self, trace_id: Optional[str]) -> str:
        """trace_id 不合法时自动生成（满足 schema pattern）"""
        if trace_id and _ID_PATTERN.match(trace_id):
            return trace_id
        return f"exec-{uuid.uuid4().hex[:12]}"

    def _normalize_run_id(self, run_id: Optional[str], state: State) -> str:
        """run_id 优先显式入参，其次 state.cycle_id，最后自动生成"""
        for candidate in (run_id, getattr(state, "cycle_id", None)):
            if candidate and _ID_PATTERN.match(str(candidate)):
                return str(candidate)
        return f"run-{uuid.uuid4().hex[:12]}"
