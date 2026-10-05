#!/usr/bin/env python3
"""IntentEvaluatorAgent — S 层意图评估 subagent

当 IntentResult.confidence < EVAL_TRIGGER_THRESHOLD (0.65) 时触发,
对低置信度意图进行二次评估:
    1. cognitive_adapter.recall() 检索相似意图历史
    2. jev (备用 laya) 意图重分类 + 正确性校验 (choice+noul 原语)
    3. LLM 二次澄清（多意图校验、路由优化建议）
    4. 返回 adjusted_confidence + clarified_intent

设计原则:
    - FAIL-OPEN: 无 jev_fn/llm_fn → 规则降级（原 confidence 透传）; 异常 → 安全默认
    - 认知闭环: recall 检索历史 → record 记录新评估结果
    - 不替换 IntentEngine 原有澄清逻辑, 仅增强
    - jev 优先, laya 备用: jev degraded 时 fallback 到 laya
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
class EvalResult:
    """S 层意图评估结果

    Attributes:
        adjusted_confidence: 调整后置信度
        clarified_intent: 二次澄清后的意图 (可选)
        route_suggestion: 路由优化建议 (可选)
        keep_static_fallback: 是否保留静态回退 (默认 True)
            - True: 保留 IntentEngine 原有澄清逻辑
            - False: 评估结果足够可信, 无需静态回退
        escalation_required: 是否需要升级到用户确认 (交易类意图强制 True)
        justification: 放行/升级理由 (escalation_required=True 时非空)
        reasoning: 评估推理过程 (用于 record)
    """
    adjusted_confidence: float
    clarified_intent: Optional[str] = None
    route_suggestion: Optional[str] = None
    keep_static_fallback: bool = True
    escalation_required: bool = False
    justification: str = ""
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adjusted_confidence": self.adjusted_confidence,
            "clarified_intent": self.clarified_intent,
            "route_suggestion": self.route_suggestion,
            "keep_static_fallback": self.keep_static_fallback,
            "escalation_required": self.escalation_required,
            "justification": self.justification,
            "reasoning": self.reasoning,
        }


# ============================================================
# IntentEvaluatorAgent
# ============================================================

class IntentEvaluatorAgent:
    """S 层意图评估 subagent

    用法:
        agent = IntentEvaluatorAgent(llm_fn=my_llm, cognitive_adapter=adapter)
        result = agent.evaluate(intent_result, context={})
    """

    # 评估触发阈值：confidence < 此值时触发 LLM 评估
    EVAL_TRIGGER_THRESHOLD = 0.65

    def __init__(
        self,
        llm_fn: Optional[Callable[[str], str]] = None,
        cognitive_adapter: Optional[Any] = None,
        jev_fn: Optional[Callable[[Any, Dict[str, Any]], Dict[str, Any]]] = None,
        laya_fn: Optional[Callable[[Any, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        """初始化意图评估器

        Args:
            llm_fn: LLM 调用函数 (prompt: str) -> str, 返回 JSON 字符串.
                None 时走 _rule_based_evaluate 规则降级 (FAIL-OPEN).
            cognitive_adapter: 认知适配器, 需有 recall(context, top_k, min_quality)
                和 record(content, tags, quality_level). None 时跳过认知闭环.
            jev_fn: Jev (TypeSafe System One) 调用函数.
                签名: (state, questions) -> {model, answers, usage, degraded}.
                用于意图重分类 (choice) + 正确性校验 (noul).
                None 时跳过 jev 评估.
            laya_fn: Laya (本地 System 1) 调用函数, 接口与 jev_fn 完全兼容.
                作为 jev 的备用: jev degraded 时 fallback 到 laya.
                None 时不启用 laya 备用.
        """
        self._llm_fn = llm_fn
        self._cognitive = cognitive_adapter
        self._jev_fn = jev_fn
        self._laya_fn = laya_fn

    # 交易类意图集合（需强制 escalation）
    TRADE_INTENT_TYPES = {"EXECUTE_TRADE"}

    # ── 主入口 ──────────────────────────────────────────

    def evaluate(self, intent_result: Any, context: Dict[str, Any]) -> EvalResult:
        """评估意图识别结果

        Args:
            intent_result: IntentResult 对象 (来自 dreamos.core.sense.types)
            context: 评估上下文 (user_message, market 等)

        Returns:
            EvalResult: 评估结果
        """
        original_conf = getattr(intent_result, "confidence", 0.0)
        intent_type = getattr(intent_result, "intent_type", "uncertain")

        # 高置信度 → 直接透传, 不触发评估
        if original_conf >= self.EVAL_TRIGGER_THRESHOLD:
            result = EvalResult(
                adjusted_confidence=original_conf,
                keep_static_fallback=True,
                reasoning=f"confidence={original_conf:.2f} >= {self.EVAL_TRIGGER_THRESHOLD}, skip evaluation",
            )
            return self._apply_escalation(result, intent_type)

        # 认知闭环 Step 1: recall 检索历史评估经验 (FAIL-OPEN)
        recalled = self._recall(intent_type, original_conf, context)

        # jev/laya 评估 (优先于 LLM, 校准质量更高)
        if self._jev_fn is not None or self._laya_fn is not None:
            try:
                result = self._jev_evaluate(intent_result, context, recalled)
                return self._apply_escalation(result, intent_type)
            except Exception:  # noqa: BLE001 FAIL-OPEN
                traceback.print_exc()
                # jev 评估异常 → 降级到 LLM/规则路径

        # LLM 评估或规则降级
        if self._llm_fn is None:
            result = self._rule_based_evaluate(intent_result, recalled)
            return self._apply_escalation(result, intent_type)

        try:
            result = self._llm_evaluate(intent_result, context, recalled)
            return self._apply_escalation(result, intent_type)
        except Exception:  # noqa: BLE001 FAIL-OPEN
            traceback.print_exc()
            result = EvalResult(
                adjusted_confidence=original_conf,
                keep_static_fallback=True,
                reasoning="LLM evaluation failed, FAIL-OPEN passthrough",
            )
            return self._apply_escalation(result, intent_type)

    # ── Escalation 机制 ─────────────────────────────────

    def _apply_escalation(self, result: EvalResult, intent_type: str) -> EvalResult:
        """根据意图类型应用 escalation 规则

        交易类意图（EXECUTE_TRADE）强制 escalation_required=True，
        并填充 justification。非交易类保持默认（escalation_required=False）。

        FAIL-OPEN：即使是规则降级路径，交易意图也必须 escalation。
        """
        if intent_type in self.TRADE_INTENT_TYPES:
            result.escalation_required = True
            if not result.justification:
                result.justification = (
                    f"交易操作({intent_type})需用户确认，已触发 escalation 守卫"
                )
        return result

    # ── jev/laya 评估路径 ──────────────────────────────

    def _jev_evaluate(
        self,
        intent_result: Any,
        context: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> EvalResult:
        """jev (备用 laya) 评估路径

        使用 jev choice 原语重新分类意图, noul 原语校验原识别是否正确.
        jev degraded 时 fallback 到 laya.

        综合逻辑:
            - jev choice == 原 intent → confidence 提升 (+0.1 * jev_confidence)
            - jev choice != 原 intent 且 jev_confidence >= 0.7 → confidence 降低 (-0.15),
              clarified_intent = jev choice
            - jev choice != 原 intent 且 jev_confidence < 0.7 → confidence 轻微降低 (-0.05)
            - noul < 0.5 → confidence 进一步降低 (-0.1)
            - jev/laya 均 degraded → 走规则降级
        """
        original_conf = getattr(intent_result, "confidence", 0.0)
        intent_type = getattr(intent_result, "intent_type", "uncertain")
        user_msg = context.get("user_message", "")
        rationale = getattr(intent_result, "rationale", "")

        # 构造 jev state 和 questions
        state = {
            "user_message": user_msg,
            "original_intent": intent_type,
            "original_confidence": original_conf,
            "rationale": rationale,
        }

        # 核心意图集 (精简版, 用于 choice criteria)
        intent_criteria = {
            "TREND_FOLLOWING": "趋势跟随，顺势操作",
            "MEAN_REVERSION": "均值回归，超买超卖逆向",
            "FUNDAMENTAL_PLAY": "基本面驱动，新闻/资金/链上",
            "BREAKOUT": "突破关键位",
            "KNOWLEDGE_MATCH": "知识库/历史模式匹配",
            "DEEP_ANALYSIS": "深度分析，A系列研究",
            "UNCERTAIN": "不确定，需要更多信息",
        }

        questions = {
            "intent_classify": {
                "type": "choice",
                "instructions": "根据用户消息，选择最匹配的意图类型",
                "criteria": intent_criteria,
            },
            "intent_correct": {
                "type": "noul",
                "instructions": "原意图识别结果是否正确？",
            },
        }

        # 调用 jev (优先), degraded 时 fallback 到 laya
        jev_resp = None
        used_model = "jev"
        if self._jev_fn is not None:
            try:
                jev_resp = self._jev_fn(state, questions)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                jev_resp = None

        # jev degraded 或异常 → 尝试 laya
        if jev_resp is None or jev_resp.get("degraded", True):
            if self._laya_fn is not None:
                try:
                    jev_resp = self._laya_fn(state, questions)
                    used_model = "laya"
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                    jev_resp = None

        # jev/laya 均不可用 → 规则降级
        if jev_resp is None or jev_resp.get("degraded", True):
            return self._rule_based_evaluate(intent_result, recalled)

        # 解析 jev 答案
        answers = jev_resp.get("answers", {})
        classify_ans = answers.get("intent_classify", {})
        correct_ans = answers.get("intent_correct", {})

        jev_choice = classify_ans.get("choice", intent_type)
        jev_choice_conf = classify_ans.get("confidence", classify_ans.get("noul", 0.5))
        noul = correct_ans.get("noul", correct_ans.get("confidence", 0.5))

        # 综合校准 confidence
        adjusted = original_conf
        clarified_intent = None

        if jev_choice == intent_type:
            # choice 匹配 → 提升 confidence
            adjusted = min(1.0, original_conf + 0.1 * jev_choice_conf)
        else:
            # choice 不匹配
            if jev_choice_conf >= 0.7:
                # 高置信不匹配 → 显著降低, 设置 clarified_intent
                adjusted = max(0.0, original_conf - 0.15)
                clarified_intent = jev_choice
            else:
                # 低置信不匹配 → 轻微降低
                adjusted = max(0.0, original_conf - 0.05)

        # noul 低 → 进一步降低
        if noul < 0.5:
            adjusted = max(0.0, adjusted - 0.1)

        # clamp 到 [0, 1]
        adjusted = max(0.0, min(1.0, adjusted))

        result = EvalResult(
            adjusted_confidence=adjusted,
            clarified_intent=clarified_intent,
            keep_static_fallback=(clarified_intent is None),
            reasoning=(
                f"jev({used_model}): choice={jev_choice}(conf={jev_choice_conf:.2f}), "
                f"noul={noul:.2f}, original={intent_type}(conf={original_conf:.2f}) "
                f"→ adjusted={adjusted:.2f}"
            ),
        )

        # 认知闭环 Step 2: record 记录本次评估 (FAIL-OPEN)
        self._record_eval(result, intent_type)

        return result

    # ── LLM 路径 ────────────────────────────────────────

    def _llm_evaluate(
        self,
        intent_result: Any,
        context: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> EvalResult:
        """LLM 评估路径: 构建 prompt → 调用 LLM → 解析 JSON → EvalResult"""
        prompt = self._build_prompt(intent_result, context, recalled)
        resp = self._llm_fn(prompt)  # type: ignore[misc]
        parsed = self._parse_llm_response(resp)

        adjusted = parsed.get("adjusted_confidence",
                             getattr(intent_result, "confidence", 0.0))
        # 确保在 [0, 1] 范围内
        adjusted = max(0.0, min(1.0, adjusted))

        result = EvalResult(
            adjusted_confidence=adjusted,
            clarified_intent=parsed.get("clarified_intent"),
            route_suggestion=parsed.get("route_suggestion"),
            keep_static_fallback=False,
            reasoning=parsed.get("reasoning", ""),
        )

        # 认知闭环 Step 2: record 记录本次评估 (FAIL-OPEN)
        self._record_eval(result, getattr(intent_result, "intent_type", "uncertain"))

        return result

    def _build_prompt(
        self,
        intent_result: Any,
        context: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> str:
        """构建 LLM 评估 prompt"""
        intent_type = getattr(intent_result, "intent_type", "uncertain")
        confidence = getattr(intent_result, "confidence", 0.0)
        user_msg = context.get("user_message", "")
        rationale = getattr(intent_result, "rationale", "")

        recalled_str = ""
        if recalled:
            recalled_str = "\n".join(
                f"- {r.get('content', '')[:120]}" for r in recalled[:3]
            )

        return f"""你是 DreamOS 意图评估器。请评估以下意图识别结果的准确性。

## 意图识别结果
- intent_type: {intent_type}
- confidence: {confidence:.2f}
- rationale: {rationale}
- user_message: {user_msg}

## 历史相似经验
{recalled_str or "(无)"}

## 任务
评估 confidence 是否合理, 是否需要调整。如有多意图可能, 请澄清。
返回 JSON 格式:
{{
    "adjusted_confidence": 0.0-1.0,
    "clarified_intent": "主意图类型或 null",
    "route_suggestion": "路由建议或 null",
    "reasoning": "评估推理过程"
}}"""

    def _parse_llm_response(self, resp: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON"""
        # 尝试提取 JSON
        resp = resp.strip()
        if resp.startswith("```"):
            # 去掉 markdown 代码块
            lines = resp.split("\n")
            resp = "\n".join(lines[1:-1]) if len(lines) > 2 else resp
        return json.loads(resp)

    # ── 规则降级 ────────────────────────────────────────

    def _rule_based_evaluate(
        self,
        intent_result: Any,
        recalled: List[Dict[str, Any]],
    ) -> EvalResult:
        """规则降级评估 (FAIL-OPEN)

        无 LLM 时, 基于历史经验做轻微调整:
        - 有历史命中 → 略微提升 confidence (+0.05, 上限 0.65)
        - 无历史命中 → 透传原值
        """
        original_conf = getattr(intent_result, "confidence", 0.0)

        if recalled:
            adjusted = min(0.65, original_conf + 0.05)
        else:
            adjusted = original_conf

        return EvalResult(
            adjusted_confidence=adjusted,
            keep_static_fallback=True,
            reasoning=f"rule-based: recalled={len(recalled)}, adjusted {original_conf:.2f} -> {adjusted:.2f}",
        )

    # ── 认知闭环 ────────────────────────────────────────

    def _recall(
        self,
        intent_type: str,
        confidence: float,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """检索历史意图评估经验 (FAIL-OPEN)"""
        if self._cognitive is None:
            return []
        try:
            recall_ctx = f"S层 意图评估 intent={intent_type} confidence={confidence:.2f}"
            return self._cognitive.recall(
                context=recall_ctx,
                top_k=5,
                min_quality="C",
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return []

    def _record_eval(self, result: EvalResult, intent_type: str) -> None:
        """记录评估结果到认知系统 (FAIL-OPEN)"""
        if self._cognitive is None:
            return
        try:
            content = (
                f"[S层意图评估] intent={intent_type}, "
                f"adjusted_conf={result.adjusted_confidence:.2f}, "
                f"clarified={result.clarified_intent or 'N/A'}, "
                f"reasoning={result.reasoning[:100]}"
            )
            self._cognitive.record(
                content=content,
                tags="S层训练,意图评估,intent_evaluator",
                quality_level="B",
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
