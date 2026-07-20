"""
DreamOS S层 — LLM 识别器

当规则识别器置信度不足时，调用 LLM 做深度意图识别。

设计:
    - 零调用优先：只有当规则识别置信度 < threshold 时才触发
    - Token 预算：受 TokenBudgetManager 控制
    - 可配置 prompt：支持自定义系统提示和输出格式
    - 结构化输出：期望 LLM 返回 JSON 格式的意图结果
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import BaseRecognizer
from ..types import IntentInput, RecognizerResult, IntentType, get_intent_definition
from dreamos.shared.llm_client import (
    LLMClient, LLMMessage, get_default_client, make_messages,
)
from dreamos.shared.utils import Timer


SYSTEM_PROMPT = """你是 Dreambuddy OS 的意图识别引擎。
你的任务是根据用户输入和市场数据，识别用户的交易意图。

可用的意图类型（JSON 格式返回）:
  - TREND_FOLLOWING: 趋势跟随，顺势操作
  - MEAN_REVERSION: 均值回归，超买超卖逆向操作
  - FUNDAMENTAL_PLAY: 基本面驱动，新闻/资金流/链上数据
  - BREAKOUT: 突破策略，关键位突破
  - KNOWLEDGE_MATCH: 知识库匹配，历史模式
  - UNCERTAIN: 不确定，需要更多信息

输出严格的 JSON 格式:
{
  "intent_type": "TREND_FOLLOWING",
  "confidence": 0.75,
  "rationale": "简短说明理由",
  "recommended_chain": "A",
  "key_factors": ["因素1", "因素2"]
}
"""


class LLMBasedRecognizer(BaseRecognizer):
    """基于 LLM 的深度意图识别器

    只有当规则识别置信度不足时才调用，节省 Token。
    """

    name = "llm_based"
    level = "llm"
    estimated_tokens = 500

    def __init__(self, llm: Optional[LLMClient] = None,
                 model: Optional[str] = None,
                 system_prompt: str = SYSTEM_PROMPT,
                 temperature: float = 0.3,
                 **kwargs):
        super().__init__(**kwargs)
        self._llm = llm
        self._model = model
        self._system_prompt = system_prompt
        self._temperature = temperature

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = get_default_client()
        return self._llm

    def recognize(self, _input: IntentInput) -> RecognizerResult:
        timer = Timer(self.name)

        try:
            with timer:
                user_msg = self._build_user_prompt(_input)
                messages = make_messages(system=self._system_prompt, user=user_msg)

                resp = self.llm.chat(
                    messages,
                    model=self._model,
                    temperature=self._temperature,
                )

            result = self._parse_response(resp.content)
            result.latency_ms = timer.elapsed_ms
            result.tokens_used = resp.tokens_total
            result.level = self.level
            return result

        except Exception as e:
            return RecognizerResult(
                recognizer=self.name,
                intent_type=IntentType.UNCERTAIN.value,
                confidence=0.0,
                rationale=f"LLM 调用失败: {e}",
                latency_ms=timer.elapsed_ms,
                tokens_used=0,
                level=self.level,
            )

    def _build_user_prompt(self, _input: IntentInput) -> str:
        """构建用户提示词"""
        parts: List[str] = []

        if _input.user_message:
            parts.append(f"用户输入: {_input.user_message}")

        if _input.market:
            mkt = _input.market
            mkt_lines = [
                f"价格: {mkt.get('price', 'N/A')}",
                f"24H涨跌幅: {mkt.get('change_24h', 'N/A')}%",
                f"RSI14: {mkt.get('rsi14', 'N/A')}",
                f"成交量比: {mkt.get('vol_ratio', 'N/A')}",
                f"资金费率: {mkt.get('funding_rate', 'N/A')}",
                f"ADX: {mkt.get('adx', 'N/A')}",
                f"市场状态: {mkt.get('regime', 'UNKNOWN')}",
            ]
            parts.append("市场数据:\n" + "\n".join(f"  - {l}" for l in mkt_lines))

        if _input.signals:
            parts.append(f"外部信号: {len(_input.signals)} 条")

        if _input.knowledge_hits:
            parts.append(f"知识库命中: {len(_input.knowledge_hits)} 条")

        parts.append(f"标的: {_input.symbol}")
        parts.append("请识别意图并输出 JSON。")

        return "\n\n".join(parts)

    def _parse_response(self, content: str) -> RecognizerResult:
        """解析 LLM 返回的 JSON"""
        # 尝试提取 JSON
        text = content.strip()

        # 常见格式: ```json ... ```
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
            intent_type = str(data.get("intent_type", "UNCERTAIN")).upper()
            confidence = float(data.get("confidence", 0.0))
            rationale = str(data.get("rationale", ""))
            chain = str(data.get("recommended_chain", "A"))

            # 校验意图类型是否有效
            valid_types = IntentType.all_types() + ["UNCERTAIN"]
            if intent_type not in valid_types:
                intent_type = "UNCERTAIN"

            base_chain = self._chain_to_nodes(chain, intent_type)

            return RecognizerResult(
                recognizer=self.name,
                intent_type=intent_type,
                confidence=min(max(confidence, 0.0), 1.0),
                rationale=rationale,
                base_chain=base_chain,
                context={"key_factors": data.get("key_factors", [])},
                level=self.level,
            )
        except (json.JSONDecodeError, ValueError):
            return self._uncertain(f"无法解析 LLM 响应: {text[:100]}")

    def _chain_to_nodes(self, chain: str, intent_type: str) -> List[str]:
        """链标识 → 节点序列"""
        chain = chain.upper()
        if chain == "A":
            return ["A1", "A2", "A3", "A4"]
        elif chain == "F":
            return ["F1", "F2", "F3", "A2", "A3", "A4"]
        elif chain == "C":
            return ["C1", "C2", "A3", "A4"]
        elif chain == "MIXED":
            return ["A1", "F1", "C1", "A2", "A3", "A4"]
        # 默认按意图类型推断
        definition = get_intent_definition(intent_type)
        chain = definition.get("chain", "A")
        if chain == "A":
            return ["A1", "A2", "A3", "A4"]
        elif chain == "F":
            return ["F1", "F2", "F3", "A2", "A3", "A4"]
        return ["A1", "A2", "A3", "A4"]
