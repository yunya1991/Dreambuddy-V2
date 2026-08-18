#!/usr/bin/env python3
"""
意图识别引擎主入口 (Intent Recognition Engine)

位置: experiments/ab-trading/core/intent_engine/engine.py

S链核心：意图识别引擎
三层价值转换：
- Layer 1: 收敛（混沌 → 单点目标）
- Layer 2: 展开（单点 → 线/网 OKR）
- Layer 3: 落地（线/网 → 可执行蓝图）
"""

from typing import Dict, List, Optional, Any

from .types import (
    Objective,
    KeyResult,
    OKRSet,
    ExecutionBlueprint,
    IntentRecognitionResult,
)
from .layer1_intent.objective_extractor import ObjectiveExtractor
from .layer2_okr.okr_builder import OKRBuilder
from .layer3_blueprint.blueprint_builder import BlueprintBuilder


class IntentRecognitionEngine:
    """
    意图识别引擎 (S链核心)

    三层价值转换：
    Layer 1: 收敛（混沌 → 单点）
    Layer 2: 展开（单点 → 线/网）
    Layer 3: 落地（线/网 → 可执行图）
    """

    def __init__(self, registry=None):
        self.objective_extractor = ObjectiveExtractor()
        self.okr_builder = OKRBuilder()
        self.blueprint_builder = BlueprintBuilder(registry=registry)

        self._sessions: Dict[str, IntentRecognitionResult] = {}

    def recognize(
        self,
        user_message: Optional[str] = None,
        mkt_data: Optional[Dict] = None,
        signals: Optional[List[Dict]] = None,
        session_id: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> IntentRecognitionResult:
        """
        完整的意图识别流程（三层贯通）

        Phase 1: 收敛 —— 目标提取（Layer 1）
        Phase 2: 展开 —— OKR分解（Layer 2）
        Phase 3: 落地 —— 蓝图构建（Layer 3）

        Args:
            user_message: 用户自然语言输入
            mkt_data: 市场数据
            signals: 信号列表
            session_id: 会话ID
            context: 上下文信息

        Returns:
            IntentRecognitionResult（三层完整输出）
        """
        result = IntentRecognitionResult()

        try:
            objective = self._extract_objective(
                user_message, mkt_data, signals, context
            )
            result.objective = objective

            if objective.clarify_needed:
                result.state = 'clarifying'
                result.confidence = objective.confidence
                result.clarify_question = objective.clarify_question
                result.clarify_options = objective.clarify_options
                result.rationale = f'需要澄清目标：{objective.clarify_question}'

                if session_id:
                    self._sessions[session_id] = result

                return result

            okr_set = self._build_okr_set(objective)
            result.okr_set = okr_set

            blueprint = self._build_blueprint(okr_set)
            result.blueprint = blueprint

            state = 'confirmed' if blueprint.confidence >= 0.3 else 'clarifying'
            result.state = state
            result.confidence = blueprint.confidence
            result.rationale = (
                f'[Layer1] 收敛: {objective.title} (置信度:{objective.confidence:.2f}) → '
                f'[Layer2] 展开: {okr_set.mode}模式, {len(okr_set.key_results)}个KR → '
                f'[Layer3] 落地: {blueprint.execution_mode}模式, {len(blueprint.node_sequence)}个节点'
            )

            if session_id:
                self._sessions[session_id] = result

            return result

        except Exception as e:
            result.state = 'error'
            result.confidence = 0.0
            result.rationale = f'意图识别失败: {str(e)}'
            return result

    def _extract_objective(
        self,
        user_message: Optional[str],
        mkt_data: Optional[Dict],
        signals: Optional[List[Dict]],
        context: Optional[Dict],
    ) -> Objective:
        """Phase 1: 收敛 —— 从混沌到单点"""
        return self.objective_extractor.extract(
            user_message=user_message,
            mkt_data=mkt_data,
            signals=signals,
            context=context,
        )

    def _build_okr_set(self, objective: Objective) -> OKRSet:
        """Phase 2: 展开 —— 从单点到线/网"""
        return self.okr_builder.build(objective)

    def _build_blueprint(self, okr_set: OKRSet) -> ExecutionBlueprint:
        """Phase 3: 落地 —— 从线/网到可执行图"""
        return self.blueprint_builder.build(okr_set)

    def clarify(
        self,
        answer: str,
        session_id: str,
    ) -> IntentRecognitionResult:
        """
        处理澄清回答

        Args:
            answer: 用户的澄清回答
            session_id: 会话ID

        Returns:
            更新后的意图识别结果
        """
        if session_id not in self._sessions:
            result = IntentRecognitionResult()
            result.state = 'error'
            result.rationale = '会话不存在'
            return result

        prev_result = self._sessions[session_id]

        if prev_result.state != 'clarifying':
            return prev_result

        if answer in ['confirm', '是的', '是', '对', 'yes']:
            objective = prev_result.objective
            objective.clarify_needed = False

            okr_set = self._build_okr_set(objective)
            blueprint = self._build_blueprint(okr_set)

            result = IntentRecognitionResult(
                objective=objective,
                okr_set=okr_set,
                blueprint=blueprint,
                state='confirmed',
                confidence=blueprint.confidence,
                rationale=(
                    f'确认目标：{objective.title} → '
                    f'{okr_set.mode}模式 → {blueprint.execution_mode}执行'
                ),
            )
            self._sessions[session_id] = result
            return result
        elif answer in ['reject', '不是', '否', '不对', 'no']:
            result = IntentRecognitionResult(
                objective=prev_result.objective,
                state='rejected',
                confidence=0.0,
                rationale='用户拒绝目标识别结果',
            )
            self._sessions[session_id] = result
            return result
        else:
            return self.recognize(
                user_message=answer,
                session_id=session_id,
            )

    def register_objective_type(self, definition: dict) -> bool:
        """注册新的目标类型（可扩展）"""
        from .layer1_intent.objective_types import OBJECTIVE_TYPES

        if not definition or 'id' not in definition:
            return False

        obj_id = definition['id']
        OBJECTIVE_TYPES[obj_id] = definition
        return True

    def get_supported_objectives(self) -> List[str]:
        """获取支持的目标类型列表"""
        from .layer1_intent.objective_types import list_objective_types
        return list_objective_types()

    def get_session_result(self, session_id: str) -> Optional[IntentRecognitionResult]:
        """获取会话的意图识别结果"""
        return self._sessions.get(session_id)

    def clear_session(self, session_id: str) -> bool:
        """清除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False
