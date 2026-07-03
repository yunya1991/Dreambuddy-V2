"""
DreamOS S层 — IntentEngine 意图引擎主入口

S 层的核心对外接口，职责:
    1. 接收多源输入（市场数据/自然语言/信号/记忆）
    2. 组合多个 recognizer 进行意图识别
    3. 管理 Token 预算，决定是否调用 LLM
    4. 融合多个识别器的结果
    5. 输出最终 IntentResult

执行流程:
    规则识别（零 Token）
        ↓ 置信度 >= threshold ?
    ┌───┴───┐
    是       否
    ↓        ↓
  直接返回   Token 预算充足 ?
             ┌───┴───┐
             是       否
             ↓        ↓
          LLM识别   降级返回
             ↓
         结果融合
             ↓
         最终输出
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .types import IntentInput, IntentResult, RecognizerResult, IntentType, get_intent_definition
from .recognizers.base import BaseRecognizer
from .recognizers.rule_based import RuleBasedRecognizer
from .recognizers.llm_based import LLMBasedRecognizer
from .recognizers.dynamic import DynamicIntentRecognizer
from .token_budget import TokenBudgetManager, BudgetLevel
from dreamos.shared.llm_client import LLMClient
from dreamos.shared.utils import Timer


# 默认阈值
DEFAULT_LLM_TRIGGER_THRESHOLD = 0.55      # 规则置信度低于此值时触发 LLM
DEFAULT_CLARIFY_THRESHOLD = 0.35          # 置信度低于此值时需要澄清


class IntentEngine:
    """S 层意图引擎 — 感知与意图识别

    用法:
        engine = IntentEngine(budget_mode="standard")

        result = engine.recognize(
            user_message="分析BTC趋势",
            market={"price": 50000, "rsi14": 45, "change_24h": 2.5},
        )

        print(result.intent_type)     # TREND_FOLLOWING
        print(result.confidence)      # 0.72
        print(result.base_chain)      # ["A1", "A2", "A3", "A4"]
    """

    def __init__(self,
                 budget_mode: str = "standard",
                 llm_trigger_threshold: float = DEFAULT_LLM_TRIGGER_THRESHOLD,
                 clarify_threshold: float = DEFAULT_CLARIFY_THRESHOLD,
                 llm: Optional[LLMClient] = None,
                 use_rule_based: bool = True,
                 use_llm_based: bool = True,
                 use_dynamic: bool = True):
        # 预算管理
        self.budget = TokenBudgetManager(mode=budget_mode)
        self._llm_trigger_threshold = llm_trigger_threshold
        self._clarify_threshold = clarify_threshold

        # 识别器
        self._recognizers: List[BaseRecognizer] = []
        self._dynamic_recognizer: Optional[DynamicIntentRecognizer] = None

        if use_rule_based:
            self._recognizers.append(RuleBasedRecognizer())
        if use_llm_based:
            self._recognizers.append(LLMBasedRecognizer(llm=llm))
        if use_dynamic:
            self._dynamic_recognizer = DynamicIntentRecognizer()
            self._recognizers.append(self._dynamic_recognizer)

    # ── 动态识别器快捷方法 ────────────────────────

    @property
    def dynamic(self) -> Optional[DynamicIntentRecognizer]:
        """获取动态识别器（用于注册自定义意图/策略）"""
        return self._dynamic_recognizer

    def register_custom_intent(self, type_id: str, definition: Dict[str, Any]) -> bool:
        """注册自定义意图类型"""
        if self._dynamic_recognizer:
            return self._dynamic_recognizer.register_intent_type(type_id, definition)
        return False

    def register_strategy(self, name: str, fn) -> bool:
        """注册自定义识别策略"""
        if self._dynamic_recognizer:
            return self._dynamic_recognizer.register_strategy(name, fn)
        return False

    # ── 核心识别方法 ───────────────────────────────

    def recognize(self,
                  user_message: Optional[str] = None,
                  market: Optional[Dict[str, Any]] = None,
                  signals: Optional[List[Dict[str, Any]]] = None,
                  memory: Optional[Dict[str, Any]] = None,
                  knowledge_hits: Optional[List[Dict[str, Any]]] = None,
                  context: Optional[Dict[str, Any]] = None,
                  symbol: str = "BTC-USDT") -> IntentResult:
        """执行意图识别（主入口）

        Args:
            user_message: 用户自然语言输入
            market: 市场数据
            signals: 外部信号
            memory: 记忆/历史
            knowledge_hits: 知识库命中
            context: 额外上下文
            symbol: 交易对

        Returns:
            IntentResult: 意图识别结果
        """
        total_timer = Timer("intent_engine")
        _input = IntentInput(
            user_message=user_message,
            market=market,
            signals=signals,
            memory=memory,
            knowledge_hits=knowledge_hits,
            context=context or {},
            symbol=symbol,
        )

        all_results: List[RecognizerResult] = []
        recognizers_used: List[str] = []
        total_tokens = 0

        # ── 第1步：零成本识别（规则 + 动态） ─────────
        for rec in self._recognizers:
            if rec.level == "local":
                try:
                    result = rec.recognize(_input)
                    all_results.append(result)
                    recognizers_used.append(rec.name)
                except Exception as e:
                    all_results.append(RecognizerResult(
                        recognizer=rec.name,
                        intent_type=IntentType.UNCERTAIN.value,
                        confidence=0.0,
                        rationale=f"识别器异常: {e}",
                    ))

        # 取最佳本地结果
        best_local = self._pick_best(all_results) if all_results else None

        # ── 第2步：判断是否需要 LLM ─────────────────

        need_llm = self._should_use_llm(best_local)

        if need_llm:
            llm_rec = self._find_recognizer("llm_based")
            if llm_rec and self.budget.can_afford_layer("sense", llm_rec.estimated_tokens):
                try:
                    result = llm_rec.recognize(_input)
                    all_results.append(result)
                    recognizers_used.append(llm_rec.name)
                    total_tokens += result.tokens_used
                    self.budget.consume(result.tokens_used, layer="sense")
                except Exception as e:
                    all_results.append(RecognizerResult(
                        recognizer=llm_rec.name,
                        intent_type=IntentType.UNCERTAIN.value,
                        confidence=0.0,
                        rationale=f"LLM 识别异常: {e}",
                    ))

        # ── 第3步：融合结果 ─────────────────────────

        final = self._fuse_results(all_results, best_local)
        final.recognizers_used = recognizers_used
        final.total_tokens = total_tokens

        with total_timer:
            pass
        final.total_latency_ms = total_timer.elapsed_ms

        # ── 第4步：是否需要澄清 ────────────────────

        if final.confidence < self._clarify_threshold and not final.clarify_needed:
            final.clarify_needed = True
            final.clarify_question = (
                f"当前对「{get_intent_definition(final.intent_type).get('name', final.intent_type)}」"
                f"的置信度为 {final.confidence:.0%}，是否需要进一步确认？"
            )
            final.clarify_options = [
                {"label": "确认", "value": "confirm"},
                {"label": "重新识别", "value": "retry"},
            ]

        return final

    # ── 内部方法 ───────────────────────────────────

    def _should_use_llm(self, best_local: Optional[RecognizerResult]) -> bool:
        """判断是否需要调用 LLM"""
        # 预算不足 → 不调用
        if self.budget.should_degrade_llm():
            return False
        # 本地结果置信度低 → 调用 LLM
        if best_local and best_local.confidence < self._llm_trigger_threshold:
            return True
        # 没有本地结果 → 调用 LLM
        if best_local is None:
            return True
        return False

    def _find_recognizer(self, name: str) -> Optional[BaseRecognizer]:
        """按名称查找识别器"""
        for rec in self._recognizers:
            if rec.name == name:
                return rec
        return None

    def _pick_best(self, results: List[RecognizerResult]) -> Optional[RecognizerResult]:
        """选出置信度最高的有效结果"""
        valid = [r for r in results if r.intent_type != IntentType.UNCERTAIN.value]
        if not valid:
            return None
        return max(valid, key=lambda r: r.confidence)

    def _fuse_results(self, all_results: List[RecognizerResult],
                      best_local: Optional[RecognizerResult]) -> IntentResult:
        """融合多个识别器的结果

        融合策略:
            1. 取置信度最高的结果作为主结果
            2. 如果有 LLM 结果且置信度 > 本地，则以 LLM 为准
            3. 附加其他结果的上下文
        """
        if not all_results:
            return IntentResult(
                intent_type=IntentType.UNCERTAIN.value,
                confidence=0.0,
                rationale="无可用识别结果",
                level="fallback",
            )

        # 找最佳结果
        best = max(all_results, key=lambda r: r.confidence)

        # 如果有 LLM 结果且比本地好，信任 LLM
        llm_results = [r for r in all_results if r.level == "llm"]
        if llm_results:
            best_llm = max(llm_results, key=lambda r: r.confidence)
            if best_llm.confidence >= best.confidence * 0.9:
                best = best_llm

        definition = get_intent_definition(best.intent_type)
        recommended_chain = definition.get("chain", "A")

        # 构建最终结果
        result = IntentResult(
            intent_type=best.intent_type,
            confidence=round(best.confidence, 3),
            recommended_chain=recommended_chain,
            base_chain=list(best.base_chain),
            extend_nodes=list(best.extend_nodes),
            rationale=best.rationale,
            context={
                **best.context,
                "all_scores": {
                    r.recognizer: {
                        "intent": r.intent_type,
                        "confidence": r.confidence,
                        "level": r.level,
                    }
                    for r in all_results
                },
            },
            level=best.level,
        )

        return result

    # ── 配置 ───────────────────────────────────────

    def set_budget_mode(self, mode: str) -> None:
        """切换预算档位"""
        self.budget = TokenBudgetManager(mode=mode)

    def reset_budget(self) -> None:
        """重置预算"""
        self.budget.reset()

    def add_recognizer(self, recognizer: BaseRecognizer) -> None:
        """添加自定义识别器"""
        self._recognizers.append(recognizer)
