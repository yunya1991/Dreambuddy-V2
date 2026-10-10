#!/usr/bin/env python3
"""C-Drive-Agent — C 层四步循环驱动器

Spec §3.4 C-Drive-Agent 四步循环:
  Step 1: recall 认知查询 (检索历史相似场景经验)
  Step 2: 反思推理 + Bull/Bear 辩论 (置信度 < 0.65 触发)
  Step 3: jeval 判断 (仅 CONTINUE 时, noul >= 0.85 放行, < 0.50 阻止)
  Step 4: subagent 补充 (仅 SUPPLEMENT 时, 路由到 macro/flow/technical/sentiment)

硬约束:
  - HC-2: 分级触发 (>0.75跳过, 0.65-0.75只recall, 0.50-0.65加辩论, <0.50全链路)
  - HC-3: 认知系统调用 FAIL-OPEN (无 adapter / 异常 → 不阻塞)
  - HC-4: jeval 调用 FAIL-OPEN (无 fn / 异常 → 不阻塞)
  - HC-8: Bull/Bear 辩论仅置信度 < 0.65 触发, 用 ThreadPoolExecutor 并行调用

设计原则:
  - CDriveAgent 是独立编排器, 不修改 DreamOS Reflector (HC-1a)
  - llm_fn / jev_judge_fn / cognitive_adapter / reflector 均可注入, 便于测试
  - 无 llm_fn 时用规则提取 Bull/Bear (FAIL-OPEN)
"""
from __future__ import annotations

import importlib
import re
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


def _load_cognitive_adapter():
    """加载认知闭环适配器（CognitiveLoopAdapter），注入 MCP 函数。

    优先从 1-ARCHITECTURE/dream-harness-bridge/integration/ 加载；
    失败时返回 None（FAIL-OPEN，C-Drive recall 降级跳过）。
    """
    try:
        from cognitive_loop_adapter import CognitiveLoopAdapter
    except ImportError:
        try:
            import os as _os
            import sys as _sys
            here = _os.path.dirname(_os.path.abspath(__file__))
            # python-server/ → dream-harness-bridge/ → 1-ARCHITECTURE/ → dreambuddy-v2/
            repo_root = _os.path.abspath(
                _os.path.join(here, "..", "..", "..", ".."))
            integration_dir = _os.path.join(
                repo_root, "1-ARCHITECTURE", "dream-harness-bridge",
                "integration",
            )
            if _os.path.isdir(integration_dir) and integration_dir not in _sys.path:
                _sys.path.insert(0, integration_dir)
            from cognitive_loop_adapter import CognitiveLoopAdapter
        except ImportError:
            return None

    # 注入真实 MCP 函数（如可用）
    try:
        from mcp_cognitive import recall, record, verify
        return CognitiveLoopAdapter(
            mcp_recall_fn=recall,
            mcp_record_fn=record,
            mcp_verify_fn=verify,
        )
    except ImportError:
        return CognitiveLoopAdapter()


def _load_jev_judge_fn():
    """加载 Jev 判断函数，作为 jev_judge_fn 注入 CDriveAgent。

    优先加载同目录 jev_judge.py 的 judge 函数；
    失败时返回 None（FAIL-OPEN，C-Drive jeval 降级跳过）。
    """
    try:
        from jev_judge import judge
        return judge
    except ImportError:
        return None


# ============================================================
# 动作枚举 (独立于 Reflector.ReflectAction, 不修改 dreamos core)
# ============================================================

class CDriveAction(str, Enum):
    """C-Drive-Agent 决策动作"""
    CONTINUE = "continue"
    REDO = "redo"
    JUMP = "jump"
    SUPPLEMENT = "supplement"
    DEBATE = "debate"


# ============================================================
# 决策结果
# ============================================================

@dataclass
class CDriveDecision:
    """C-Drive-Agent 四步循环决策结果"""
    action: CDriveAction = CDriveAction.CONTINUE
    reason: str = ""
    confidence: float = 0.0
    suggestions: List[str] = field(default_factory=list)
    # Bull/Bear 辩论结果 (HC-8)
    bull_argument: Optional[str] = None
    bear_argument: Optional[str] = None
    bull_confidence: Optional[float] = None
    bear_confidence: Optional[float] = None
    # JUMP 目标
    jump_to: Optional[str] = None
    # SUPPLEMENT 路由目标
    supplement_module: Optional[str] = None
    # jeval 结果
    jeval_noul: Optional[float] = None
    # 执行步骤追踪
    steps_executed: List[str] = field(default_factory=list)
    # D2: 分级 effort 级别 (light/standard/deep), 根据 confidence 动态决定
    effort_level: str = "light"
    # D2: Bull/Bear 多轮辩论轮次 (1=单轮, 2=多轮)
    debate_rounds: int = 0
    # LLM 综合卡片 (IPC handler 层注入, 不在 run() 内部生成)
    # 结构: List[SynthesizedCard.to_dict()] 或空列表
    synthesized_cards: List[Dict[str, Any]] = field(default_factory=list)
    # SKILL 增强提示 (synthesizer 产出后由触发层检测)
    enhancement_hints: List[Dict[str, Any]] = field(default_factory=list)
    # subagent 产出的图表 (ChartSpec.to_dict() 列表, 供前端渲染)
    charts: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "confidence": self.confidence,
            "suggestions": self.suggestions,
            "bull_argument": self.bull_argument,
            "bear_argument": self.bear_argument,
            "bull_confidence": self.bull_confidence,
            "bear_confidence": self.bear_confidence,
            "jump_to": self.jump_to,
            "supplement_module": self.supplement_module,
            "jeval_noul": self.jeval_noul,
            "steps_executed": self.steps_executed,
            "effort_level": self.effort_level,
            "debate_rounds": self.debate_rounds,
            "synthesized_cards": self.synthesized_cards,
            "enhancement_hints": self.enhancement_hints,
            "charts": self.charts,
        }


# ============================================================
# C-Drive-Agent
# ============================================================

class CDriveAgent:
    """C 层四步循环驱动器

    用法:
        agent = CDriveAgent(
            llm_fn=my_llm,
            jev_judge_fn=my_jeval,
            cognitive_adapter=cognitive_loop_adapter,
        )
        decision = agent.run(node_id="C1", result=node_result, state=state)
    """

    # HC-2: 分级触发阈值
    CONF_SKIP = 0.75           # > 0.75: 跳过四步循环
    CONF_RECALL_ONLY = 0.65    # 0.65-0.75: 只 recall + reflect
    CONF_FULL_LOOP = 0.50      # < 0.50: 全链路 (含 jeval + supplement)

    # 辩论后决策阈值
    CONF_REDO = 0.20           # 置信度极低 → REDO
    CONF_SUPPLEMENT = 0.30     # Bull/Bear 均弱 → SUPPLEMENT

    # D2: Bull/Bear 多轮辩论阈值
    DEBATE_CLOSE_GAP = 0.15    # |bull-bear| < 0.15 → 触发第二轮辩论
    MAX_DEBATE_ROUNDS = 2      # 最多 2 轮辩论 (避免无限循环)

    # jeval 门控
    JEV_PASS = 0.85            # noul >= 0.85: 放行
    JEV_BLOCK = 0.50           # noul < 0.50: 阻止

    # 节点→subagent 路由映射
    _NODE_MODULE_MAP = {
        "F1": "sentiment",
        "F2": "flow",
        "F3": "valuation",
        "F4": "onchain",
        "F5": "macro",
        "C1": "technical",
        "C2": "technical",
        "C3": "technical",
    }

    def __init__(
        self,
        llm_fn: Optional[Callable[[str], str]] = None,
        jev_judge_fn: Optional[Callable[[Any, Dict], Dict]] = None,
        cognitive_adapter: Optional[Any] = None,
        reflector: Optional[Any] = None,
        config: Optional[Dict] = None,
    ):
        """初始化 C-Drive-Agent

        Args:
            llm_fn: LLM 调用函数 (prompt: str) -> str, 用于 Bull/Bear 辩论.
                None 时用规则提取 (FAIL-OPEN).
            jev_judge_fn: jeval 判断函数 (state, questions) -> dict.
                None 时跳过 jeval (FAIL-OPEN).
            cognitive_adapter: 认知适配器, 需有 recall(context, top_k, min_quality).
                None 时跳过 recall (FAIL-OPEN).
            reflector: DreamOS Reflector 实例 (可选, 当前预留).
            config: 配置字典 (SPEC v2.0-rc3 第 6.7 节):
                - debate_engine: "v1" | "v2" (默认 "v1")
        """
        self._llm_fn = llm_fn
        self._jev_fn = jev_judge_fn
        self._cognitive = cognitive_adapter
        self._reflector = reflector
        # SPEC v2.0-rc3 第 6.7 节: feature flag + 回滚
        cfg = config or {}
        self._debate_engine_version = cfg.get("debate_engine", "v1")
        self._debate_error_count = 0
        self._debate_max_errors = cfg.get("debate_max_consecutive_errors", 3)

    # ── 主入口 ──────────────────────────────────────────

    def run(
        self,
        node_id: str,
        result: Any,
        state: Any,
        signals: Optional[List[Dict]] = None,
        graph: Any = None,
        executed_count: int = 1,
        max_nodes: int = 5,
        budget_remaining_ratio: Optional[float] = None,
        intent_type: Optional[str] = None,
        steer: Optional[Dict[str, Any]] = None,
    ) -> CDriveDecision:
        """执行四步循环 (含分级触发 + 用户实时干预)

        Args:
            steer: 用户实时干预指令 (F7.4)，支持:
                - skip_steps: List[str] 跳过指定步骤 (recall/debate/jeval/supplement)
                - force_direction: "LONG"|"SHORT"|"NEUTRAL" 强制方向约束
                - override_confidence: float 覆盖置信度阈值判断

        Returns:
            CDriveDecision: 决策结果
        """
        steer = steer or {}
        confidence = float(getattr(result, "confidence", 0.5))
        # F7.4: 用户覆盖置信度
        if "override_confidence" in steer:
            try:
                confidence = float(steer["override_confidence"])
            except (TypeError, ValueError):
                pass
        direction = getattr(result, "direction", None) or "NEUTRAL"
        # F7.4: 用户强制方向
        if steer.get("force_direction") in ("LONG", "SHORT", "NEUTRAL"):
            direction = steer["force_direction"]
        skip_steps = set(steer.get("skip_steps", []) or [])
        steps: List[str] = []
        suggestions: List[str] = []
        steer_log: List[str] = []

        # D5: 自适应阈值 — 根据信号复杂度动态调整
        # 复杂度高 → 降低阈值 (更严格审查, 更容易触发循环)
        complexity = self._compute_complexity(signals)
        dyn_skip = self.CONF_SKIP - 0.10 * complexity
        dyn_recall = self.CONF_RECALL_ONLY - 0.10 * complexity
        dyn_full = self.CONF_FULL_LOOP - 0.10 * complexity

        # D2: 分级 effort 级别 (根据 confidence + 动态阈值决定)
        if confidence > dyn_skip:
            effort_level = "skip"
        elif confidence >= dyn_recall:
            effort_level = "light"
        elif confidence >= dyn_full:
            effort_level = "standard"
        else:
            effort_level = "deep"

        # HC-2: 置信度 > 动态阈值 → 跳过四步循环
        if confidence > dyn_skip:
            return CDriveDecision(
                action=CDriveAction.CONTINUE,
                reason=f"高置信度({confidence:.2f}>={dyn_skip:.2f})跳过四步循环",
                confidence=confidence,
                steps_executed=["skip"],
                effort_level="skip",
            )

        # Step 1: recall 认知查询 (HC-3 FAIL-OPEN)
        if "recall" in skip_steps:
            steer_log.append("steer:skip_recall")
        else:
            memories = self._recall(node_id, direction, result, state)
            for m in memories[:5]:
                content = m.get("content") if isinstance(m, dict) else str(m)
                if content:
                    suggestions.append(str(content)[:200])
        steps.append("recall")

        # Step 2: 反思推理 + Bull/Bear 辩论
        if confidence >= dyn_recall:
            # 动态阈值以上: 只 recall + reflect, 无辩论
            decision = self._reflect_simple(node_id, confidence, suggestions)
        else:
            # < 0.65: 触发 Bull/Bear 辩论 (HC-8)
            if "debate" in skip_steps:
                steer_log.append("steer:skip_debate")
                decision = CDriveDecision(
                    action=CDriveAction.CONTINUE,
                    reason=f"steer跳过辩论,直接放行(conf={confidence:.2f})",
                    confidence=confidence,
                )
            else:
                # D2: Bull/Bear 多轮辩论 — 第一轮接近时触发第二轮
                debate = self._bull_bear_debate(signals, direction)
                debate_rounds = 1
                gap = abs(debate["bull_confidence"] - debate["bear_confidence"])
                if gap < self.DEBATE_CLOSE_GAP:
                    # 第一轮接近, 触发第二轮更深入辩论
                    debate2 = self._bull_bear_debate(signals, direction, round_num=2)
                    debate_rounds = 2
                    # 取两轮中更极端的结果 (放大差异, 避免僵局)
                    debate = debate2 if abs(
                        debate2["bull_confidence"] - debate2["bear_confidence"]
                    ) > gap else debate
                steps.append("debate")
                decision = self._reflect_after_debate(
                    node_id, confidence, suggestions, debate)
                decision.debate_rounds = debate_rounds

            # 动态阈值以下: jeval 判断 (仅 CONTINUE 时)
            if (confidence < dyn_full
                    and decision.action == CDriveAction.CONTINUE):
                if "jeval" in skip_steps:
                    steer_log.append("steer:skip_jeval")
                else:
                    # Step 3: jeval 判断 (HC-4 FAIL-OPEN)
                    noul = self._jeval(node_id, result, state, confidence)
                    steps.append("jeval")
                    if noul is not None:
                        decision.jeval_noul = noul
                        if noul < self.JEV_BLOCK:
                            decision.action = CDriveAction.REDO
                            decision.reason += (
                                f"; jeval noul={noul:.2f}"
                                f"<{self.JEV_BLOCK} 阻止放行"
                            )

            # Step 4: SUPPLEMENT 路由
            if decision.action == CDriveAction.SUPPLEMENT:
                if "supplement" in skip_steps:
                    steer_log.append("steer:skip_supplement→CONTINUE")
                    decision.action = CDriveAction.CONTINUE
                    decision.reason += "; steer跳过补充"
                else:
                    module = self._route_supplement(
                        intent_type, node_id, direction)
                    decision.supplement_module = module
                    steps.append("supplement")

        decision.steps_executed = steps
        decision.effort_level = effort_level
        if steer_log:
            decision.reason = (decision.reason or "") + " | " + "; ".join(steer_log)

        # D4: 将 signals 索引到知识图谱 (FAIL-OPEN)
        if graph is not None and hasattr(graph, "add_node"):
            self._index_signals_to_graph(signals, graph)

        return decision

    # ── Step 1: recall (HC-3 FAIL-OPEN) ─────────────────

    # ── D5: 信号复杂度 + 自适应阈值 ────────────

    def _compute_complexity(self, signals: Optional[List[Dict]]) -> float:
        """计算信号复杂度 (0.0 ~ 1.0)

        维度:
        - 信号数量: 0-3 → 0.0, 4-6 → 0.3, 7+ → 0.5
        - 方向冲突: 同时存在 long/short → +0.3
        - 置信度离散度: std > 0.2 → +0.2
        """
        sigs = signals or []
        if not sigs:
            return 0.0

        # 1. 信号数量
        n = len(sigs)
        if n <= 3:
            score_count = 0.0
        elif n <= 6:
            score_count = 0.3
        else:
            score_count = 0.5

        # 2. 方向冲突
        has_long = any(s.get("direction") == "long" for s in sigs)
        has_short = any(s.get("direction") == "short" for s in sigs)
        score_conflict = 0.3 if (has_long and has_short) else 0.0

        # 3. 置信度离散度
        confs = [s.get("confidence", 0.5) for s in sigs]
        if len(confs) >= 2:
            mean = sum(confs) / len(confs)
            variance = sum((c - mean) ** 2 for c in confs) / len(confs)
            std = variance ** 0.5
            score_dispersion = 0.2 if std > 0.2 else 0.0
        else:
            score_dispersion = 0.0

        return min(1.0, score_count + score_conflict + score_dispersion)

    # ── D4: 知识图谱索引 ────────────────────────

    def _index_signals_to_graph(self, signals: Optional[List[Dict]],
                                graph: Any) -> None:
        """将 signals 索引到知识图谱 (HC FAIL-OPEN)

        为每个 signal 创建节点, 并建立 signal → indicator 关系。
        """
        if not signals:
            return
        try:
            from dreamos.core.graph_store.types import GraphNode, GraphEdge
            for sig in signals:
                sig_name = sig.get("name", "unknown")
                sig_id = f"signal:{sig_name}"
                ind_id = f"indicator:{sig_name}"
                # signal 节点
                graph.add_node(GraphNode(
                    node_id=sig_id,
                    node_type="signal",
                    label=sig_name,
                    properties={"direction": sig.get("direction"),
                                "confidence": sig.get("confidence")},
                ))
                # indicator 节点
                graph.add_node(GraphNode(
                    node_id=ind_id,
                    node_type="indicator",
                    label=sig_name,
                ))
                # signal → indicator 关系
                graph.add_edge(GraphEdge(
                    from_node=sig_id,
                    to_node=ind_id,
                    relation="derived_from",
                    weight=float(sig.get("confidence", 0.5)),
                ))
        except Exception:  # noqa: BLE001 FAIL-OPEN
            pass

    def _recall(
        self,
        node_id: str,
        direction: str,
        result: Any,
        state: Any,
    ) -> List[Dict[str, Any]]:
        """检索认知记忆库历史相似场景经验

        HC-3 FAIL-OPEN: 无 adapter / 异常 → 返回 []
        """
        if self._cognitive is None:
            return []
        try:
            context = f"node={node_id},direction={direction}"
            return self._cognitive.recall(
                context=context, top_k=5, min_quality="C"
            )
        except Exception:  # noqa: BLE001 FAIL-OPEN
            return []

    # ── Step 2: 反思推理 ─────────────────────────────────

    def _reflect_simple(
        self,
        node_id: str,
        confidence: float,
        suggestions: List[str],
    ) -> CDriveDecision:
        """反思推理 (无辩论, 0.65-0.75 区间)"""
        if confidence < self.CONF_REDO:
            return CDriveDecision(
                action=CDriveAction.REDO,
                reason=f"置信度极低({confidence:.2f}),重做节点 {node_id}",
                confidence=confidence,
                suggestions=suggestions,
            )
        return CDriveDecision(
            action=CDriveAction.CONTINUE,
            reason=f"节点 {node_id} 正常,置信度={confidence:.2f}",
            confidence=confidence,
            suggestions=suggestions,
        )

    def _reflect_after_debate(
        self,
        node_id: str,
        confidence: float,
        suggestions: List[str],
        debate: Dict[str, Any],
    ) -> CDriveDecision:
        """反思推理 + Bull/Bear 辩论结果"""
        bull_conf = debate.get("bull_confidence", 0.0)
        bear_conf = debate.get("bear_confidence", 0.0)

        decision = CDriveDecision(
            confidence=confidence,
            suggestions=suggestions,
            bull_argument=debate.get("bull_argument"),
            bear_argument=debate.get("bear_argument"),
            bull_confidence=bull_conf,
            bear_confidence=bear_conf,
        )

        if confidence < self.CONF_REDO:
            decision.action = CDriveAction.REDO
            decision.reason = (
                f"置信度极低({confidence:.2f}),重做节点 {node_id}")
        elif max(bull_conf, bear_conf) < self.CONF_SUPPLEMENT:
            decision.action = CDriveAction.SUPPLEMENT
            decision.reason = (
                f"Bull/Bear 均弱(bull={bull_conf:.2f},"
                f"bear={bear_conf:.2f}),需 subagent 补充")
        else:
            decision.action = CDriveAction.CONTINUE
            decision.reason = (
                f"辩论后继续(bull={bull_conf:.2f},"
                f"bear={bear_conf:.2f}),置信度={confidence:.2f}")

        return decision

    # ── Bull/Bear 辩论 (HC-8) ────────────────────────────

    def _bull_bear_debate(
        self,
        signals: Optional[List[Dict]],
        direction: str,
        round_num: int = 1,
    ) -> Dict[str, Any]:
        """Bull/Bear 对抗辩论 (TradingAgents 启发)

        HC-8: 并行调用, 置信度 < 0.65 时触发.
        无 llm_fn 时用规则提取 (FAIL-OPEN).
        D2: round_num=2 时进行更深入的第二轮辩论.
        SPEC v2.0-rc3 第 6.7 节: feature flag v1/v2 + 回滚.
        """
        sigs = signals or []
        bull_signals = [s for s in sigs if s.get("direction") == "long"]
        bear_signals = [s for s in sigs if s.get("direction") == "short"]

        if self._llm_fn is None:
            return self._rule_based_debate(bull_signals, bear_signals, round_num)

        # SPEC v2.0-rc3 第 6.7 节: v2 feature flag
        if self._debate_engine_version == "v2" and \
                self._debate_error_count < self._debate_max_errors:
            try:
                return self._v2_debate(sigs, direction)
            except Exception as e:
                self._debate_error_count += 1
                import logging
                logging.getLogger("cdrive.debate").warning(
                    "v2 辩论异常 #%d: %s, fallback to v1", self._debate_error_count, e)
                if self._debate_error_count >= self._debate_max_errors:
                    self._debate_engine_version = "v1"
                    logging.getLogger("cdrive.debate").error(
                        "v2 连续 %d 次异常, 切回 v1",
                        self._debate_error_count)
                # fallback to v1
                return self._llm_based_debate(
                    bull_signals, bear_signals, direction, round_num)

        return self._llm_based_debate(bull_signals, bear_signals, direction, round_num)

    def _v2_debate(self, signals: List[Dict], direction: str) -> Dict[str, Any]:
        """v2 辩论：调用 DebateEngine.run_fast()。

        将 DebateEngine 的输出映射到 v1 兼容格式：
        - bull_thesis → bull_argument
        - bear_thesis → bear_argument
        - bull/bear_confidence 保持不变
        """
        import asyncio
        from debate_engine import DebateEngine

        # 构建 topic（从 signals 提取关键信息）
        sig_names = [s.get("name", "?") for s in signals[:3]]
        topic = f"{'、'.join(sig_names)} 信号 {direction} 方向判断"

        engine = DebateEngine(
            llm_fn=self._llm_fn,
            config={},
            cognitive_adapter=self._cognitive,
        )
        result = asyncio.run(engine.run_fast(topic))

        # v2 成功 → 重置错误计数
        self._debate_error_count = 0

        return {
            "bull_argument": result.get("bull_thesis", ""),
            "bear_argument": result.get("bear_thesis", ""),
            "bull_confidence": result.get("bull_confidence", 0.5),
            "bear_confidence": result.get("bear_confidence", 0.5),
        }

    def _rule_based_debate(
        self,
        bull_signals: List[Dict],
        bear_signals: List[Dict],
        round_num: int = 1,
    ) -> Dict[str, Any]:
        """规则提取 Bull/Bear (无 LLM 时降级)

        D2: round_num=2 时放大置信度差异 (打破僵局).
        """
        bull_names = [s.get("name", "?") for s in bull_signals]
        bear_names = [s.get("name", "?") for s in bear_signals]
        bull_arg = "; ".join(bull_names) if bull_names else "无利好信号"
        bear_arg = "; ".join(bear_names) if bear_names else "无利空信号"
        bull_conf = (
            sum(s.get("confidence", 0.5) for s in bull_signals) / len(bull_signals)
            if bull_signals else 0.2
        )
        bear_conf = (
            sum(s.get("confidence", 0.5) for s in bear_signals) / len(bear_signals)
            if bear_signals else 0.2
        )
        # D2: 第二轮放大差异 (±0.1), 避免僵局
        if round_num >= 2:
            if bull_conf >= bear_conf:
                bull_conf = min(0.95, bull_conf + 0.1)
                bear_conf = max(0.05, bear_conf - 0.1)
            else:
                bear_conf = min(0.95, bear_conf + 0.1)
                bull_conf = max(0.05, bull_conf - 0.1)
        return {
            "bull_argument": bull_arg,
            "bear_argument": bear_arg,
            "bull_confidence": bull_conf,
            "bear_confidence": bear_conf,
        }

    def _llm_based_debate(
        self,
        bull_signals: List[Dict],
        bear_signals: List[Dict],
        direction: str,
        round_num: int = 1,
    ) -> Dict[str, Any]:
        """LLM 并行 Bull/Bear 辩论 (HC-8: ThreadPoolExecutor)

        D2: round_num=2 时使用更深入的分析 prompt.
        """
        depth_hint = "深入分析, 考虑多时间周期和交叉验证" if round_num >= 2 else ""

        def _call(role: str, signals: List[Dict]) -> Dict[str, Any]:
            try:
                prompt = (
                    f"{role}分析(第{round_num}轮): {depth_hint} "
                    f"从以下信号提取"
                    f"{'利好(多头)' if role == 'Bull' else '利空(空头)'}论据. "
                    f"信号: {signals}. 当前方向: {direction}"
                )
                resp = self._llm_fn(prompt)  # type: ignore[misc]
                conf = self._parse_confidence(resp, default=0.5)
                return {"argument": resp, "confidence": conf}
            except Exception:  # noqa: BLE001 FAIL-OPEN
                return {"argument": f"{role}分析降级(异常)", "confidence": 0.3}

        with ThreadPoolExecutor(max_workers=2) as pool:
            bull_future = pool.submit(_call, "Bull", bull_signals)
            bear_future = pool.submit(_call, "Bear", bear_signals)
            bull_result = bull_future.result()
            bear_result = bear_future.result()

        return {
            "bull_argument": bull_result["argument"],
            "bear_argument": bear_result["argument"],
            "bull_confidence": bull_result["confidence"],
            "bear_confidence": bear_result["confidence"],
        }

    @staticmethod
    def _parse_confidence(text: str, default: float = 0.5) -> float:
        """从文本中解析 confidence=X.YY"""
        match = re.search(r"confidence[=:]\s*(0\.\d+)", text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return default

    # ── Step 3: jeval (HC-4 FAIL-OPEN) ───────────────────

    def _jeval(
        self,
        node_id: str,
        result: Any,
        state: Any,
        confidence: float,
    ) -> Optional[float]:
        """调用 jeval 判断决策质量

        HC-4 FAIL-OPEN: 无 fn / 异常 → 返回 None
        """
        if self._jev_fn is None:
            return None
        try:
            state_desc = f"node={node_id},confidence={confidence:.2f}"
            questions = {
                "q1": {
                    "type": "noul",
                    "instructions": "判断当前节点决策是否充分",
                }
            }
            resp = self._jev_fn(state_desc, questions)
            answers = resp.get("answers", {})
            for v in answers.values():
                if isinstance(v, dict) and "noul" in v:
                    return float(v["noul"])
            return None
        except Exception:  # noqa: BLE001 FAIL-OPEN
            return None

    # ── Step 4: SUPPLEMENT 路由 ──────────────────────────

    def _route_supplement(
        self,
        intent_type: Optional[str],
        node_id: str,
        direction: str,
    ) -> str:
        """路由到 subagent module"""
        module = self._NODE_MODULE_MAP.get(node_id)
        if module:
            return module
        if intent_type == "deep_analysis":
            return "macro"
        return "technical"


# ============================================================
# SUPPLEMENT → subagent → aggregate → synthesize 链路
# ============================================================

# module → (import_path, handler_name) 映射
_MODULE_HANDLER_MAP: Dict[str, tuple] = {
    "sentiment": ("sentiment_agent", "handle_sentiment_agent"),
    "flow": ("flow_agent", "handle_flow_agent"),
    "valuation": ("valuation_agent", "handle_valuation_agent"),
    "onchain": ("onchain_agent", "handle_onchain_agent"),
    "macro": ("macro_agent", "handle_macro_agent"),
    "technical": ("technical_agent", "handle_technical_agent"),
    "risk": ("risk_agent", "handle_risk_agent"),
    "portfolio": ("portfolio_agent", "handle_portfolio_agent"),
}

# module → 数据源节点 ID 列表 (D 链: C1-C3 技术 + F1-F5 基本面)
_MODULE_NODE_MAP: Dict[str, List[str]] = {
    "technical": ["C1", "C2", "C3"],
    "sentiment": ["F1"],
    "flow": ["F2"],
    "valuation": ["F3"],
    "onchain": ["F4"],
    "macro": ["F5"],
    "risk": [],
    "portfolio": [],
}


def _extract_module_node_output(full_results: dict, module: str) -> dict:
    """从完整节点结果中提取指定模块对应的节点输出.

    full_results 结构: {node_id: node_output_dict, ...}
    若模块对应多个节点, 合并为一个 dict (后者覆盖前者同 key).
    若节点不存在, 返回空 dict (subagent 内部会处理数据不足).
    """
    node_ids = _MODULE_NODE_MAP.get(module, [])
    merged: dict = {}
    for nid in node_ids:
        out = full_results.get(nid)
        if isinstance(out, dict):
            merged.update(out)
    return merged


def _make_synthesizer_llm_fn():
    """创建 synthesizer 用的 llm_fn 包装器 (FAIL-OPEN)

    尝试从 dreamos.shared.llm_client 获取默认 LLM 客户端.
    无 API key 或导入失败时返回 None, synthesizer 自动降级到规则综合.
    """
    try:
        from dreamos.shared.llm_client import (
            get_default_client, LLMMessage, NoOpLLMClient,
        )
        client = get_default_client()
        if isinstance(client, NoOpLLMClient):
            return None

        def llm_fn(prompt: str) -> str:
            resp = client.chat([LLMMessage(role="user", content=prompt)])
            return resp.content or ""

        return llm_fn
    except Exception:
        return None


def _resolve_supplement_modules(
    decision: CDriveDecision,
    params: dict,
) -> List[str]:
    """根据 intent_type 决定要调度的 subagent 模块列表

    - deep_analysis: 多维度并行调度 (技术+情绪+链上+估值+资金流)
    - 其他: 仅调度 decision.supplement_module (单模块)
    """
    intent_type = params.get("intent_type")
    intent_lower = (intent_type or "").lower()
    primary = decision.supplement_module

    if intent_lower == "deep_analysis":
        # 深度分析: 并行拉取技术面 + 基本面 + 情绪面
        modules = ["technical", "sentiment", "onchain", "valuation", "flow"]
        # 确保主模块在列(去重, 保持主模块优先)
        if primary and primary not in modules:
            modules.insert(0, primary)
        # 只保留已注册的模块
        return [m for m in modules if m in _MODULE_HANDLER_MAP]

    # 非深度分析: 单模块
    if primary and primary in _MODULE_HANDLER_MAP:
        return [primary]
    return []


def _run_single_subagent(module: str, node_output: dict) -> Optional[SubagentOutput]:
    """执行单个 subagent, 返回 SubagentOutput 或 None (FAIL-OPEN)"""
    try:
        import_path, handler_name = _MODULE_HANDLER_MAP[module]
        mod = importlib.import_module(import_path)
        handler = getattr(mod, handler_name)
        sub_result = handler({"node_output": node_output})

        if not sub_result.get("ok"):
            return None

        from subagent_types import SubagentOutput, Signal, ChartSpec
        output_dict = sub_result.get("output", {})
        return SubagentOutput(
            module=output_dict.get("module", module),
            summary=output_dict.get("summary", ""),
            signals=[Signal(**s) for s in output_dict.get("signals", [])],
            charts=[ChartSpec(**c) for c in output_dict.get("charts", [])],
            raw_data=output_dict.get("raw_data"),
        )
    except Exception:  # noqa: BLE001 FAIL-OPEN
        return None


def _execute_supplement_and_synthesize(
    decision: CDriveDecision,
    params: dict,
) -> CDriveDecision:
    """SUPPLEMENT 决策后: 多 subagent 并行 → 聚合 → LLM 综合 → 注入 synthesized_cards

    链路:
      _resolve_supplement_modules() → 并行执行各 subagent
        → List[SubagentOutput]
        → aggregator.aggregate_subagent_outputs()
        → SynthesizerAgent.synthesize()
        → decision.synthesized_cards

    FAIL-OPEN: 任何环节异常 → 不阻塞, synthesized_cards 保持空列表
    """
    modules = _resolve_supplement_modules(decision, params)
    if not modules:
        return decision

    try:
        node_output = params.get("node_output", {})

        # Step 1: 并行执行多 subagent (ThreadPoolExecutor)
        # 每个模块只接收其对应节点的 output (e.g. onchain←F4, sentiment←F1)
        from concurrent.futures import ThreadPoolExecutor, as_completed

        outputs: List[SubagentOutput] = []
        with ThreadPoolExecutor(max_workers=min(len(modules), 5)) as pool:
            future_to_module = {
                pool.submit(_run_single_subagent, m, _extract_module_node_output(node_output, m)): m
                for m in modules
            }
            for future in as_completed(future_to_module):
                result = future.result()
                if result is not None:
                    outputs.append(result)

        if not outputs:
            return decision  # 全部失败 → FAIL-OPEN

        # Step 2: 聚合所有 subagent 输出
        from aggregator import aggregate_subagent_outputs
        aggregated = aggregate_subagent_outputs(outputs)

        # Step 3: LLM 综合 (无 llm_fn 时走规则降级, FAIL-OPEN)
        from synthesizer_agent import SynthesizerAgent
        llm_fn = _make_synthesizer_llm_fn()
        synthesizer = SynthesizerAgent(llm_fn=llm_fn)
        cards = synthesizer.synthesize(aggregated)

        # Step 4: 注入到决策结果
        card_dicts = [c.to_dict() for c in cards]
        decision.synthesized_cards = card_dicts

        # Step 4b: 收集 subagent 图表 (ChartSpec.to_dict()) 供前端渲染
        all_charts = []
        for out in outputs:
            for chart in out.charts:
                all_charts.append(chart.to_dict())
        decision.charts = all_charts

        # Step 5: SKILL 增强触发检测 (FAIL-OPEN, 不阻塞主流程)
        try:
            from skill_enhancement import detect_enhancement_triggers, enhancement_hints_to_dicts
            hints = detect_enhancement_triggers(
                card_dicts,
                overall_confidence=getattr(decision, "confidence", None),
            )
            decision.enhancement_hints = enhancement_hints_to_dicts(hints)
        except Exception:  # noqa: BLE001
            pass  # 触发层异常不影响报告输出

        return decision

    except Exception:  # noqa: BLE001 FAIL-OPEN
        traceback.print_exc()
        return decision  # 异常时不阻塞, 保持原决策


# ============================================================
# IPC handler (供 server.py 路由)
# ============================================================

def handle_c_drive_agent(params: dict) -> dict:
    """IPC handler: C-Drive-Agent 四步循环

    参数:
        node_id: 当前节点 ID
        confidence: 节点置信度
        direction: 方向
        signals: 信号列表 [{name, value, direction, confidence}]
        intent_type: 意图类型 (可选)
    """
    try:
        node_id = params.get("node_id", "unknown")
        confidence = float(params.get("confidence", 0.5))
        direction = params.get("direction", "NEUTRAL")
        signals = params.get("signals", [])
        intent_type = params.get("intent_type")
        intent_lower = (intent_type or "").lower()

        # 构建轻量 result 对象
        class _LightResult:
            def __init__(self, conf, d):
                self.confidence = conf
                self.direction = d
                self.status = "SUCCESS"
                self.outputs = {}
                self.error = None

        result = _LightResult(confidence, direction)
        # 注入认知适配器、Jev 判断器和 LLM（FAIL-OPEN 降级到规则）
        agent = CDriveAgent(
            llm_fn=_make_synthesizer_llm_fn(),
            jev_judge_fn=_load_jev_judge_fn(),
            cognitive_adapter=_load_cognitive_adapter(),
        )
        decision = agent.run(
            node_id=node_id,
            result=result,
            state=None,  # IPC 模式下无 state 对象
            signals=signals,
            intent_type=intent_type,
        )

        # A3 集成: SUPPLEMENT 决策 或 deep_analysis 意图 → 多 subagent 并行 → 聚合 → LLM 综合
        # deep_analysis 始终产出多维度卡片(含图表+基本面), 不依赖 SUPPLEMENT 触发
        if decision.action == CDriveAction.SUPPLEMENT or intent_lower == "deep_analysis":
            decision = _execute_supplement_and_synthesize(decision, params)

        return {"ok": True, "decision": decision.to_dict()}
    except Exception as e:
        stack = traceback.format_exc()
        return {"ok": False, "error": str(e), "stack": stack}


# ============================================================
# 辩论 IPC (SPEC v2.0-rc3 第 6.3 节)
# ============================================================

def handle_debate(params: dict) -> dict:
    """辩论 IPC 路由 (SPEC v2.0-rc3 第 6.3 节)

    对外暴露 4 个辩论相关 IPC 接口，供 Trae 和 32-bot 调用：
    - action=recall: 检索历史辩论记忆
    - action=record: 存储辩论经验
    - action=verify: 验证辩论预测
    - action=run: C-Drive 自驱动辩论 (fast/deep)

    FAIL-OPEN: 无 cognitive_adapter 时 recall 返回空列表，record/verify 跳过。
    """
    action = params.get("action")

    try:
        if action == "recall":
            cog = _load_cognitive_adapter()
            if cog is None:
                return {"ok": True, "memories": []}
            context = params.get("context", "")
            top_k = params.get("top_k", 5)
            result = cog.recall(
                context=context, top_k=top_k, min_quality="C",
            )
            # MCP recall 返回 {"memories": [...]} 格式
            if isinstance(result, dict) and "memories" in result:
                return {"ok": True, "memories": result["memories"]}
            if isinstance(result, list):
                return {"ok": True, "memories": result}
            return {"ok": True, "memories": []}

        elif action == "record":
            cog = _load_cognitive_adapter()
            if cog is None:
                return {"ok": True, "memory_id": None,
                        "warning": "cognitive_adapter unavailable"}
            content = params.get("content", "")
            quality = params.get("quality", "B")
            tags = params.get("tags", "debate")
            mid = cog.record(
                content=content, quality_level=quality, tags=tags,
            )
            return {"ok": True, "memory_id": mid}

        elif action == "verify":
            cog = _load_cognitive_adapter()
            if cog is None:
                return {"ok": True, "warning": "cognitive_adapter unavailable"}
            memory_id = params.get("memory_id", "")
            success = params.get("success", True)
            cog.verify(memory_id=memory_id, success=success)
            return {"ok": True}

        elif action == "run":
            topic = params.get("topic", "")
            mode = params.get("mode", "fast")
            background = params.get("background", "")
            llm_fn = _make_synthesizer_llm_fn()
            if llm_fn is None:
                return {"ok": False, "error": "LLM not available for debate"}
            cog = _load_cognitive_adapter()
            from debate_engine import DebateEngine
            engine = DebateEngine(llm_fn=llm_fn, config={}, cognitive_adapter=cog)
            import asyncio as _asyncio
            if mode == "deep":
                result = _asyncio.run(engine.run_deep(topic, background))
            else:
                result = _asyncio.run(engine.run_fast(topic, background))
            return {"ok": True, "result": result}

        else:
            return {"ok": False, "error": f"unknown action: {action}"}

    except Exception as e:
        stack = traceback.format_exc()
        return {"ok": False, "error": str(e), "stack": stack}
