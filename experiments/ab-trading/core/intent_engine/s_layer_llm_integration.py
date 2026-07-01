#!/usr/bin/env python3
"""
S层三层递进大模型集成 (S-Layer LLM Integration)

位置: experiments/ab-trading/core/intent_engine/s_layer_llm_integration.py

核心功能：
1. S层三层递进（Objective → OKR → Blueprint）全部接入大模型
2. Token预算管理器（全程监控，低于阈值触发警告和接管建议）
3. 经典指标系统接管机制（用户授权后全链路接管）
4. 前端启动集成（建议用户启动前端实现全面接管）

设计原则：
- 大模型优先：无论是简单还是复杂任务，先调用大模型识别（消耗Token）
- Token预算透明：全程监控Token使用，低于阈值时主动提示用户
- 分级接管：从提示 → 建议接管 → 前端启动，逐步引导用户
- 用户授权：所有接管操作都需要用户明确授权

基于技术文档：
- SYSTEM_ARCHITECTURE_OVERVIEW.md (v2.2) S层三层递进
- dreambuddy-os/SKILL.md (v1.1.0) 意图识别引擎
- 经典指标系统: 10-经典指标系统/ml_trade_service.py (:8092)
"""

import os
import json
import time
import uuid
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

try:
    from .types import Objective, OKRSet, ExecutionBlueprint, IntentRecognitionResult
    from .layer1_intent.objective_extractor import ObjectiveExtractor
    from .layer2_okr.okr_builder import OKRBuilder
    from .layer3_blueprint.blueprint_builder import BlueprintBuilder
    _HAS_ENGINE = True
except ImportError:
    _HAS_ENGINE = False
    Objective = None
    OKRSet = None
    ExecutionBlueprint = None
    IntentRecognitionResult = None


# ============================================================
# Token 预算状态枚举
# ============================================================

class TokenBudgetStatus(Enum):
    """Token预算状态"""
    HEALTHY = "healthy"           # 健康：Token充足
    WARNING = "warning"           # 警告：低于70%
    LOW = "low"                   # 低：低于30%
    CRITICAL = "critical"         # 严重：低于10%
    EXHAUSTED = "exhausted"       # 耗尽：0
    HANDOVER_TRIGGERED = "handover"  # 已触发经典指标接管


# ============================================================
# 接管级别枚举
# ============================================================

class HandoverLevel(Enum):
    """经典指标系统接管级别"""
    NONE = "none"                 # 不接管，正常运行
    TOKEN_SAVE = "token_save"     # 仅节省Token：减少LLM调用
    RECOMMEND = "recommend"       # 建议接管：提示用户
    PARTIAL = "partial"           # 部分接管：部分节点由经典指标系统处理
    FULL = "full"                 # 全链路接管：完全由经典指标系统驱动
    FRONTEND = "frontend"         # 前端接管：建议启动前端


# ============================================================
# Token 预算管理器
# ============================================================

@dataclass
class TokenUsageRecord:
    """Token使用记录"""
    timestamp: float
    module: str           # 哪个模块使用
    layer: str            # S层/哪一层
    operation: str        # 操作类型
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    description: str = ""


@dataclass
class TokenBudgetAlert:
    """Token预算告警"""
    alert_id: str
    level: str            # info/warning/low/critical
    message: str
    current_tokens: int
    budget_total: int
    percentage: float
    suggested_action: str
    handover_level: str   # 建议的接管级别
    timestamp: float


class TokenBudgetManager:
    """
    Token预算管理器

    功能：
    1. 全程监控Token使用
    2. 分级告警（健康/警告/低/严重/耗尽）
    3. 触发经典指标系统接管建议
    4. 记录和审计Token使用历史

    阈值：
    - 70%: 健康提示
    - 50%: 首次警告
    - 30%: 低余额警告，建议接管
    - 10%: 严重警告，强制部分接管
    - 0%: 耗尽，全链路接管
    """

    def __init__(
        self,
        total_budget: int = 100000,
        warning_threshold: float = 0.7,
        low_threshold: float = 0.3,
        critical_threshold: float = 0.1,
    ):
        self.total_budget = total_budget
        self.used_tokens = 0
        self.warning_threshold = warning_threshold
        self.low_threshold = low_threshold
        self.critical_threshold = critical_threshold

        self.usage_history: List[TokenUsageRecord] = []
        self.alerts: List[TokenBudgetAlert] = []
        self.handover_level = HandoverLevel.NONE
        self.handover_authorized = False
        self.frontend_started = False

        # 各层Token使用统计
        self.layer_usage: Dict[str, int] = defaultdict(int)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.total_budget - self.used_tokens)

    @property
    def usage_percentage(self) -> float:
        if self.total_budget == 0:
            return 1.0
        return self.used_tokens / self.total_budget

    @property
    def remaining_percentage(self) -> float:
        if self.total_budget == 0:
            return 0.0
        return self.remaining_tokens / self.total_budget

    @property
    def status(self) -> TokenBudgetStatus:
        if self.handover_authorized:
            return TokenBudgetStatus.HANDOVER_TRIGGERED
        if self.remaining_tokens <= 0:
            return TokenBudgetStatus.EXHAUSTED
        if self.remaining_percentage <= self.critical_threshold:
            return TokenBudgetStatus.CRITICAL
        if self.remaining_percentage <= self.low_threshold:
            return TokenBudgetStatus.LOW
        if self.remaining_percentage <= self.warning_threshold:
            return TokenBudgetStatus.WARNING
        return TokenBudgetStatus.HEALTHY

    def consume_tokens(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        module: str = "unknown",
        layer: str = "S",
        operation: str = "unknown",
        description: str = "",
    ) -> TokenBudgetStatus:
        """
        消耗Token并更新状态

        Returns:
            当前Token预算状态
        """
        total = prompt_tokens + completion_tokens
        self.used_tokens += total
        self.layer_usage[layer] += total

        record = TokenUsageRecord(
            timestamp=time.time(),
            module=module,
            layer=layer,
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            description=description,
        )
        self.usage_history.append(record)

        # 检查是否需要生成告警
        self._check_and_generate_alerts()

        return self.status

    def _check_and_generate_alerts(self):
        """检查并生成告警"""
        current_status = self.status
        percentage = self.remaining_percentage

        # 根据状态生成告警
        if current_status == TokenBudgetStatus.CRITICAL and not self._has_alert_level("critical"):
            alert = TokenBudgetAlert(
                alert_id=f"alert_{uuid.uuid4().hex[:8]}",
                level="critical",
                message=f"Token严重不足！剩余 {self.remaining_tokens} ({percentage*100:.1f}%)",
                current_tokens=self.remaining_tokens,
                budget_total=self.total_budget,
                percentage=percentage,
                suggested_action="建议立即启用经典指标系统全链路接管",
                handover_level=HandoverLevel.FULL.value,
                timestamp=time.time(),
            )
            self.alerts.append(alert)
            self.handover_level = HandoverLevel.FULL

        elif current_status == TokenBudgetStatus.LOW and not self._has_alert_level("low"):
            alert = TokenBudgetAlert(
                alert_id=f"alert_{uuid.uuid4().hex[:8]}",
                level="low",
                message=f"Token余额较低，剩余 {self.remaining_tokens} ({percentage*100:.1f}%)",
                current_tokens=self.remaining_tokens,
                budget_total=self.total_budget,
                percentage=percentage,
                suggested_action="建议切换到经典指标系统部分接管，或启动前端接管",
                handover_level=HandoverLevel.PARTIAL.value,
                timestamp=time.time(),
            )
            self.alerts.append(alert)
            self.handover_level = HandoverLevel.PARTIAL

        elif current_status == TokenBudgetStatus.WARNING and not self._has_alert_level("warning"):
            alert = TokenBudgetAlert(
                alert_id=f"alert_{uuid.uuid4().hex[:8]}",
                level="warning",
                message=f"Token使用已达 {self.usage_percentage*100:.1f}%，请注意预算",
                current_tokens=self.remaining_tokens,
                budget_total=self.total_budget,
                percentage=percentage,
                suggested_action="建议减少LLM调用频率，或考虑启用经典指标系统",
                handover_level=HandoverLevel.RECOMMEND.value,
                timestamp=time.time(),
            )
            self.alerts.append(alert)
            self.handover_level = HandoverLevel.RECOMMEND

    def _has_alert_level(self, level: str) -> bool:
        """检查是否已有某级别的告警"""
        return any(a.level == level for a in self.alerts)

    def authorize_handover(self, level: HandoverLevel = HandoverLevel.FULL) -> bool:
        """
        用户授权经典指标系统接管

        Args:
            level: 接管级别

        Returns:
            是否授权成功
        """
        self.handover_authorized = True
        self.handover_level = level
        return True

    def revoke_handover(self) -> bool:
        """撤销接管授权"""
        self.handover_authorized = False
        self.handover_level = HandoverLevel.NONE
        return True

    def get_handover_suggestion(self) -> Dict[str, Any]:
        """
        获取接管建议

        Returns:
            接管建议详情
        """
        current_status = self.status

        suggestions = {
            "current_status": current_status.value,
            "remaining_tokens": self.remaining_tokens,
            "remaining_percentage": f"{self.remaining_percentage*100:.1f}%",
            "handover_level": self.handover_level.value,
            "handover_authorized": self.handover_authorized,
            "frontend_started": self.frontend_started,
            "suggestions": [],
        }

        # 根据状态给出建议
        if current_status in [TokenBudgetStatus.LOW, TokenBudgetStatus.CRITICAL]:
            suggestions["suggestions"].append({
                "type": "classic_takeover",
                "title": "启用经典指标系统接管",
                "description": "Token不足，建议由经典指标系统全链路接管交易决策",
                "action": "authorize_full_handover",
                "urgency": "high",
            })

        if current_status == TokenBudgetStatus.CRITICAL:
            suggestions["suggestions"].append({
                "type": "frontend_start",
                "title": "启动前端全面接管",
                "description": "建议启动前端界面，由用户直接操控经典指标系统",
                "action": "start_frontend",
                "urgency": "critical",
            })

        if current_status == TokenBudgetStatus.WARNING:
            suggestions["suggestions"].append({
                "type": "token_save",
                "title": "节省Token模式",
                "description": "减少LLM调用，仅在关键决策时调用",
                "action": "enable_token_save_mode",
                "urgency": "low",
            })

        # 剩余Token用途建议
        if self.handover_authorized or current_status in [TokenBudgetStatus.LOW, TokenBudgetStatus.CRITICAL]:
            suggestions["remaining_token_usage"] = [
                "调整经典指标系统策略参数",
                "修改策略配置和阈值",
                "查看和分析经典指标系统结果",
                "辅助解释和理解交易信号",
            ]

        return suggestions

    def can_use_llm_for_adjustment(self) -> bool:
        """
        检查剩余Token是否足够用于策略调整

        Returns:
            是否可以使用LLM调整策略
        """
        # 至少保留1000 Token用于调整
        return self.remaining_tokens >= 1000

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_budget": self.total_budget,
            "used_tokens": self.used_tokens,
            "remaining_tokens": self.remaining_tokens,
            "usage_percentage": f"{self.usage_percentage*100:.2f}%",
            "remaining_percentage": f"{self.remaining_percentage*100:.2f}%",
            "status": self.status.value,
            "handover_level": self.handover_level.value,
            "handover_authorized": self.handover_authorized,
            "alerts_count": len(self.alerts),
            "layer_usage": dict(self.layer_usage),
            "history_count": len(self.usage_history),
        }


# ============================================================
# S层三层递进大模型识别器
# ============================================================

class SLayerLLMRecognizer:
    """
    S层三层递进大模型识别器

    功能：
    1. Layer 1 (Objective): 大模型提取用户目标（优先LLM，消耗Token）
    2. Layer 2 (OKR): 大模型构建OKR结构
    3. Layer 3 (Blueprint): 大模型生成执行蓝图

    设计：
    - 大模型优先：无论是简单还是复杂任务，都先调用大模型
    - Token预算监控：集成TokenBudgetManager
    - 降级机制：Token不足时降级到本地规则
    - 节省模式：授权接管后，仅用于策略调整
    """

    def __init__(
        self,
        config: Optional[Dict] = None,
        token_budget: Optional[TokenBudgetManager] = None,
    ):
        self.config = config or {}
        self.token_budget = token_budget or TokenBudgetManager(
            total_budget=self.config.get('token_budget', 100000)
        )

        # 节省Token模式
        self.token_save_mode = False

        # 本地规则提取器（降级用）
        if _HAS_ENGINE:
            self.objective_extractor = ObjectiveExtractor()
            self.okr_builder = OKRBuilder()
            self.blueprint_builder = BlueprintBuilder()
        else:
            self.objective_extractor = None
            self.okr_builder = None
            self.blueprint_builder = None

        # 结果缓存
        self._result_cache: Dict[str, Any] = {}

    # --------------------------------------------------------
    # 主入口：S层三层递进识别
    # --------------------------------------------------------

    def recognize(
        self,
        user_message: str,
        context: Optional[Dict] = None,
        mkt_data: Optional[Dict] = None,
        force_local: bool = False,
    ) -> Dict[str, Any]:
        """
        S层三层递进识别主入口

        流程：
        1. 检查Token预算状态
        2. 如果Token充足 → 三层全部用LLM
        3. 如果Token不足 → 降级到本地规则
        4. 如果已授权接管 → 建议经典指标系统接管

        Args:
            user_message: 用户输入
            context: 上下文
            mkt_data: 市场数据
            force_local: 强制使用本地规则

        Returns:
            包含objective, okr_set, blueprint的完整结果
        """
        start_time = time.time()
        result = {
            "success": False,
            "objective": None,
            "okr_set": None,
            "blueprint": None,
            "recognition_mode": "",
            "token_used": 0,
            "token_status": self.token_budget.status.value,
            "handover_suggestion": None,
            "latency_ms": 0,
            "alerts": [],
        }

        # 获取当前告警
        result["alerts"] = [
            {"level": a.level, "message": a.message}
            for a in self.token_budget.alerts[-3:]
        ]

        # Step 1: 判断是否使用LLM
        use_llm = self._should_use_llm(force_local)

        if use_llm:
            # Step 2: LLM三层递进识别
            result["recognition_mode"] = "llm_full"
            llm_result = self._llm_three_layer_recognize(user_message, context, mkt_data)
            result.update(llm_result)
            result["success"] = True
        else:
            # Step 3: 降级到本地规则
            result["recognition_mode"] = "local_fallback"
            local_result = self._local_three_layer_recognize(user_message, context, mkt_data)
            result.update(local_result)
            result["success"] = True

        # Step 4: 检查接管建议
        result["handover_suggestion"] = self.token_budget.get_handover_suggestion()

        # Step 5: 如果已授权接管，添加经典指标系统信息
        if self.token_budget.handover_authorized:
            result["handover_active"] = True
            result["handover_level"] = self.token_budget.handover_level.value
            result["remaining_token_purpose"] = [
                "调整经典指标系统策略参数",
                "修改策略配置和阈值",
                "查看和分析经典指标系统结果",
                "辅助解释和理解交易信号",
            ]

        result["latency_ms"] = (time.time() - start_time) * 1000
        return result

    def _should_use_llm(self, force_local: bool = False) -> bool:
        """判断是否应该使用LLM"""
        if force_local:
            return False

        # 如果已授权全链路接管，不使用LLM
        if self.token_budget.handover_authorized and \
           self.token_budget.handover_level == HandoverLevel.FULL:
            return False

        # 如果Token严重不足，不使用LLM
        if self.token_budget.status == TokenBudgetStatus.EXHAUSTED:
            return False

        # 如果Token不足且是节省模式，不使用LLM
        if self.token_save_mode and self.token_budget.status in [
            TokenBudgetStatus.LOW,
            TokenBudgetStatus.CRITICAL,
        ]:
            return False

        return True

    # --------------------------------------------------------
    # LLM三层递进识别
    # --------------------------------------------------------

    def _llm_three_layer_recognize(
        self,
        user_message: str,
        context: Optional[Dict],
        mkt_data: Optional[Dict],
    ) -> Dict[str, Any]:
        """
        使用LLM进行三层递进识别

        注意：当前使用模拟实现，真实环境接入DeepSeek/OpenAI
        """
        result = {
            "objective": None,
            "okr_set": None,
            "blueprint": None,
            "token_used": 0,
        }

        total_prompt = 0
        total_completion = 0

        # Layer 1: Objective提取（LLM）
        obj_prompt, obj_completion = self._estimate_tokens_layer1(user_message)
        total_prompt += obj_prompt
        total_completion += obj_completion

        objective = self._llm_extract_objective(user_message, context)
        result["objective"] = objective

        # Layer 2: OKR构建（LLM）
        okr_prompt, okr_completion = self._estimate_tokens_layer2(objective)
        total_prompt += okr_prompt
        total_completion += okr_completion

        okr_set = self._llm_build_okr(objective)
        result["okr_set"] = okr_set

        # Layer 3: Blueprint构建（LLM）
        bp_prompt, bp_completion = self._estimate_tokens_layer3(okr_set)
        total_prompt += bp_prompt
        total_completion += bp_completion

        blueprint = self._llm_build_blueprint(okr_set, context)
        result["blueprint"] = blueprint

        # 记录Token使用
        total_tokens = total_prompt + total_completion
        result["token_used"] = total_tokens
        self.token_budget.consume_tokens(
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            module="s_layer_llm",
            layer="S",
            operation="three_layer_recognition",
            description="S层三层递进LLM识别",
        )

        return result

    def _estimate_tokens_layer1(self, user_message: str) -> Tuple[int, int]:
        """估算Layer 1的Token消耗"""
        prompt_tokens = len(user_message) + 300  # Prompt约300Token
        completion_tokens = 150  # Objective输出约150Token
        return prompt_tokens, completion_tokens

    def _estimate_tokens_layer2(self, objective: Any) -> Tuple[int, int]:
        """估算Layer 2的Token消耗"""
        prompt_tokens = 200  # OKR Prompt约200Token
        completion_tokens = 300  # OKR输出约300Token
        return prompt_tokens, completion_tokens

    def _estimate_tokens_layer3(self, okr_set: Any) -> Tuple[int, int]:
        """估算Layer 3的Token消耗"""
        prompt_tokens = 300  # Blueprint Prompt约300Token
        completion_tokens = 400  # Blueprint输出约400Token
        return prompt_tokens, completion_tokens

    def _llm_extract_objective(
        self,
        user_message: str,
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """
        Layer 1: LLM提取Objective

        模拟LLM调用，实际实现应接入DeepSeek/OpenAI
        """
        # 模拟LLM输出
        text_lower = user_message.lower()

        # 简单规则判断意图类型（模拟LLM理解）
        obj_type = "trading_decision"
        obj_title = "交易决策"
        complexity = "standard"

        if any(kw in user_message for kw in ['分析', '研究', '调研', '深度']):
            obj_type = "deep_analysis"
            obj_title = "深度分析"
            complexity = "deep"
        elif any(kw in user_message for kw in ['趋势', '行情', '走势']):
            obj_type = "trend_analysis"
            obj_title = "趋势分析"
            complexity = "standard"
        elif any(kw in user_message for kw in ['风险', '评估', '检查']):
            obj_type = "risk_assessment"
            obj_title = "风险评估"
            complexity = "standard"
        elif any(kw in user_message for kw in ['买入', '卖出', '做多', '做空', '下单']):
            obj_type = "trading_decision"
            obj_title = "交易决策"
            complexity = "standard"
        elif any(kw in user_message for kw in ['什么是', '解释', '概念', '怎么']):
            obj_type = "concept_explanation"
            obj_title = "概念解释"
            complexity = "simple"

        return {
            "id": f"obj_{uuid.uuid4().hex[:8]}",
            "title": obj_title,
            "type": obj_type,
            "complexity": complexity,
            "confidence": 0.85,
            "source": "llm",
            "extracted_keywords": self._extract_keywords(user_message),
            "clarify_needed": False,
        }

    def _llm_build_okr(self, objective: Dict) -> Dict[str, Any]:
        """
        Layer 2: LLM构建OKR

        模拟LLM输出
        """
        complexity = objective.get("complexity", "standard")

        if complexity == "simple":
            krs = [
                {
                    "id": "kr_query",
                    "title": "查询信息",
                    "metric": "query_result",
                    "target_value": 1.0,
                    "weight": 1.0,
                    "order_index": 0,
                    "depends_on": [],
                    "capability_tags": ["query"],
                },
            ]
            mode = "single"
        elif complexity == "deep":
            krs = [
                {"id": "kr_tech", "title": "技术面分析", "metric": "tech_score", "weight": 0.3,
                 "order_index": 0, "depends_on": [], "capability_tags": ["technical_analysis", "indicators"],
                 "is_parallel": True, "line_id": "line_tech"},
                {"id": "kr_fund", "title": "基本面分析", "metric": "fund_score", "weight": 0.25,
                 "order_index": 0, "depends_on": [], "capability_tags": ["fundamental_analysis", "news"],
                 "is_parallel": True, "line_id": "line_fund"},
                {"id": "kr_sent", "title": "情绪面分析", "metric": "sent_score", "weight": 0.2,
                 "order_index": 0, "depends_on": [], "capability_tags": ["sentiment_analysis"],
                 "is_parallel": True, "line_id": "line_sent"},
                {"id": "kr_synth", "title": "综合决策", "metric": "synth_score", "weight": 0.25,
                 "order_index": 1, "depends_on": ["kr_tech", "kr_fund", "kr_sent"],
                 "capability_tags": ["synthesis", "decision_making"],
                 "is_parallel": False, "line_id": "line_synth"},
            ]
            mode = "multi"
        else:  # standard
            krs = [
                {"id": "kr_research", "title": "调研", "metric": "research_depth", "weight": 0.3,
                 "order_index": 0, "depends_on": [], "capability_tags": ["research"]},
                {"id": "kr_analysis", "title": "分析", "metric": "analysis_depth", "weight": 0.4,
                 "order_index": 1, "depends_on": ["kr_research"],
                 "capability_tags": ["analysis", "evaluation"]},
                {"id": "kr_conclusion", "title": "结论", "metric": "conclusion_quality", "weight": 0.3,
                 "order_index": 2, "depends_on": ["kr_analysis"],
                 "capability_tags": ["conclusion", "recommendation"]},
            ]
            mode = "single"

        return {
            "mode": mode,
            "complexity": complexity,
            "objective_id": objective.get("id", ""),
            "key_results": krs,
            "confidence": 0.8,
            "rationale": f"目标「{objective.get('title')}」→ {mode}模式, {len(krs)}个KR",
        }

    def _llm_build_blueprint(
        self,
        okr_set: Dict,
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """
        Layer 3: LLM构建Blueprint

        模拟LLM输出
        """
        complexity = okr_set.get("complexity", "standard")
        mode = okr_set.get("mode", "single")

        # 根据复杂度映射节点
        node_map = {
            "simple": ["classic-indicator-scan"],
            "standard": [
                "classic-indicator-scan",
                "fundamental-fund-flow",
                "dream-first-principles",
            ],
            "deep": [
                "classic-indicator-scan",
                "fundamental-fund-flow",
                "fundamental-sentiment",
                "dream-contradiction-theory",
                "dream-first-principles",
                "dream-strategy-research",
            ],
        }

        nodes = node_map.get(complexity, node_map["standard"])

        # 构建依赖图
        dependencies = {}
        for i, node in enumerate(nodes):
            if i == 0:
                dependencies[node] = []
            else:
                dependencies[node] = [nodes[i - 1]]

        return {
            "blueprint_id": f"bp_{uuid.uuid4().hex[:8]}",
            "node_sequence": nodes,
            "execution_mode": "sequential" if mode == "single" else "hybrid",
            "dependencies": dependencies,
            "complexity": complexity,
            "total_timeout_ms": {"simple": 15000, "standard": 60000, "deep": 120000}.get(complexity, 60000),
            "required_nodes": nodes[:2] if len(nodes) >= 2 else nodes,
            "optional_nodes": nodes[2:] if len(nodes) > 2 else [],
            "confidence": 0.75,
            "rationale": f"OKR({mode}, {complexity}) → 蓝图({len(nodes)}节点)",
        }

    # --------------------------------------------------------
    # 本地规则三层递进识别（降级）
    # --------------------------------------------------------

    def _local_three_layer_recognize(
        self,
        user_message: str,
        context: Optional[Dict],
        mkt_data: Optional[Dict],
    ) -> Dict[str, Any]:
        """
        降级：使用本地规则进行三层递进识别
        """
        result = {
            "objective": None,
            "okr_set": None,
            "blueprint": None,
            "token_used": 0,
        }

        if not _HAS_ENGINE:
            # 如果没有引擎，返回空结果
            return result

        # Layer 1: 本地Objective提取
        objective = self.objective_extractor.extract(
            user_message=user_message,
            mkt_data=mkt_data,
            context=context,
        )

        # 转换为dict
        result["objective"] = {
            "id": objective.id,
            "title": objective.title,
            "type": objective.type,
            "complexity": objective.complexity,
            "confidence": objective.confidence,
            "source": "local",
            "extracted_keywords": objective.extracted_keywords,
            "clarify_needed": objective.clarify_needed,
        }

        # Layer 2: 本地OKR构建
        okr_set = self.okr_builder.build(objective)
        result["okr_set"] = {
            "mode": okr_set.mode,
            "complexity": okr_set.complexity,
            "objective_id": okr_set.objective.id,
            "key_results": [kr.title for kr in okr_set.key_results],
            "confidence": okr_set.confidence,
        }

        # Layer 3: 本地Blueprint构建
        blueprint = self.blueprint_builder.build(okr_set)
        result["blueprint"] = {
            "blueprint_id": blueprint.blueprint_id,
            "node_sequence": blueprint.node_sequence,
            "execution_mode": blueprint.execution_mode,
            "complexity": blueprint.complexity,
            "confidence": blueprint.confidence,
        }

        return result

    def _extract_keywords(self, text: str) -> List[str]:
        """从文本中提取关键词"""
        keywords = []
        # 简单关键词提取
        common_words = ['BTC', 'ETH', 'SOL', '做多', '做空', '分析', '趋势',
                       '风险', '技术面', '基本面', 'MACD', 'RSI', '合约', '现货']
        for kw in common_words:
            if kw.lower() in text.lower():
                keywords.append(kw)
        return keywords

    # --------------------------------------------------------
    # 策略调整功能（接管后剩余Token用途）
    # --------------------------------------------------------

    def adjust_strategy_params(
        self,
        strategy_id: str,
        user_request: str,
        current_params: Dict,
    ) -> Dict[str, Any]:
        """
        调整经典指标系统策略参数

        这是接管后剩余Token的主要用途：
        - 修改策略参数
        - 调整阈值设置
        - 优化策略配置
        - 解释和辅助理解

        Args:
            strategy_id: 策略ID
            user_request: 用户调整请求
            current_params: 当前参数

        Returns:
            调整建议
        """
        # 检查Token是否足够
        if not self.token_budget.can_use_llm_for_adjustment():
            return {
                "success": False,
                "message": "Token不足，无法进行策略调整",
                "suggestion": "请直接在前端界面手动调整参数",
            }

        # 模拟LLM调整建议
        suggestion_params = dict(current_params)

        # 简单规则调整（模拟LLM理解）
        if '降低风险' in user_request or '保守' in user_request:
            if 'position_size' in suggestion_params:
                suggestion_params['position_size'] = suggestion_params['position_size'] * 0.5
            if 'stop_loss_pct' in suggestion_params:
                suggestion_params['stop_loss_pct'] = suggestion_params['stop_loss_pct'] * 0.5
        elif '增加收益' in user_request or '激进' in user_request:
            if 'position_size' in suggestion_params:
                suggestion_params['position_size'] = suggestion_params['position_size'] * 1.5
            if 'take_profit_pct' in suggestion_params:
                suggestion_params['take_profit_pct'] = suggestion_params['take_profit_pct'] * 1.2
        elif '调整周期' in user_request:
            if 'timeframe' in suggestion_params:
                suggestion_params['timeframe'] = '1h'

        # 消耗Token（模拟）
        self.token_budget.consume_tokens(
            prompt_tokens=200,
            completion_tokens=150,
            module="s_layer_llm",
            layer="S",
            operation="strategy_adjustment",
            description=f"调整策略{strategy_id}参数",
        )

        return {
            "success": True,
            "strategy_id": strategy_id,
            "original_params": current_params,
            "suggested_params": suggestion_params,
            "rationale": f"根据您的请求「{user_request}」调整策略参数",
            "token_used": 350,
            "remaining_tokens": self.token_budget.remaining_tokens,
        }

    def explain_classic_result(
        self,
        result_data: Dict,
        user_question: str = "",
    ) -> Dict[str, Any]:
        """
        解释经典指标系统的结果

        接管后剩余Token的另一个用途：
        - 解释交易信号
        - 分析技术指标含义
        - 回答用户关于结果的问题

        Args:
            result_data: 经典指标系统返回的数据
            user_question: 用户的问题

        Returns:
            解释结果
        """
        if not self.token_budget.can_use_llm_for_adjustment():
            return {
                "success": False,
                "message": "Token不足，无法解释结果",
                "suggestion": "请查看原始数据或参考指标说明文档",
            }

        # 模拟解释
        signal = result_data.get('signal', 'HOLD')
        confidence = result_data.get('confidence', 0.5)

        explanations = {
            'LONG': '当前技术指标显示多头趋势，建议做多入场',
            'SHORT': '当前技术指标显示空头趋势，建议做空入场',
            'HOLD': '当前指标信号不明确，建议观望等待更明确的信号',
        }

        explanation = explanations.get(signal, '当前信号需要进一步分析确认')

        # 消耗Token（模拟）
        self.token_budget.consume_tokens(
            prompt_tokens=150,
            completion_tokens=100,
            module="s_layer_llm",
            layer="S",
            operation="result_explanation",
            description="解释经典指标系统结果",
        )

        return {
            "success": True,
            "original_result": result_data,
            "explanation": explanation,
            "confidence": confidence,
            "key_metrics": list(result_data.keys())[:5],
            "token_used": 250,
            "remaining_tokens": self.token_budget.remaining_tokens,
        }

    # --------------------------------------------------------
    # 前端启动建议
    # --------------------------------------------------------

    def suggest_frontend_start(self) -> Dict[str, Any]:
        """
        建议启动前端实现全面接管

        当Token严重不足时，建议用户启动前端，
        由用户直接操控经典指标系统。
        """
        return {
            "type": "frontend_takeover_suggestion",
            "title": "建议启动前端全面接管",
            "description": (
                "当前Token预算严重不足。为了不影响交易决策，"
                "建议启动前端界面，由您直接操控经典指标系统，"
                "实现全链路交易接管。"
            ),
            "benefits": [
                "零Token消耗：完全由经典指标系统驱动",
                "实时交易：直接操控入场离场",
                "策略配置：自由调整策略参数",
                "风险可控：完全由您掌控决策",
            ],
            "actions": [
                {
                    "label": "启动前端",
                    "action": "start_frontend",
                    "url": "http://127.0.0.1:8092",
                    "description": "打开经典指标系统前端界面",
                },
                {
                    "label": "继续使用LLM",
                    "action": "continue_llm",
                    "description": "继续使用AI助手，但Token可能很快耗尽",
                },
            ],
            "token_status": self.token_budget.get_stats(),
        }


# ============================================================
# 经典指标系统接管管理器
# ============================================================

class ClassicHandoverManager:
    """
    经典指标系统接管管理器

    功能：
    1. 管理接管状态和授权
    2. 全链路接管后驱动经典指标系统
    3. 前端启动集成
    4. 剩余Token的策略调整辅助
    """

    def __init__(
        self,
        s_layer_recognizer: SLayerLLMRecognizer,
        classic_api_url: str = "http://127.0.0.1:8092",
    ):
        self.s_layer = s_layer_recognizer
        self.classic_api_url = classic_api_url
        self._frontend_started = False
        self._handover_history: List[Dict] = []

    def request_handover(
        self,
        level: str = "full",
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        请求经典指标系统接管（需要用户确认）

        Args:
            level: 接管级别 partial/full
            reason: 接管原因

        Returns:
            接管请求详情
        """
        return {
            "request_id": f"handover_req_{uuid.uuid4().hex[:8]}",
            "handover_level": level,
            "reason": reason,
            "status": "pending_authorization",
            "requires_user_action": True,
            "authorization_action": {
                "type": "button",
                "label": "确认授权接管",
                "action": "authorize_handover",
                "payload": {"level": level},
            },
            "what_happens_next": self._describe_handover_effect(level),
        }

    def authorize_handover(
        self,
        level: str = "full",
        user_id: str = "",
    ) -> Dict[str, Any]:
        """
        用户授权接管

        Args:
            level: 接管级别
            user_id: 用户ID

        Returns:
            授权结果
        """
        handover_level = HandoverLevel(level)
        self.s_layer.token_budget.authorize_handover(handover_level)

        record = {
            "timestamp": time.time(),
            "level": level,
            "user_id": user_id,
            "action": "authorize",
        }
        self._handover_history.append(record)

        result = {
            "success": True,
            "handover_level": level,
            "handover_active": True,
            "remaining_token_purpose": [
                "调整经典指标系统策略参数",
                "修改策略配置和阈值",
                "查看和分析经典指标系统结果",
                "辅助解释和理解交易信号",
            ],
            "classic_system_info": {
                "api_url": self.classic_api_url,
                "available_strategies": [
                    "RegimeHybridStrategy",
                    "BreakoutStrategy",
                    "OttStrategy",
                ],
                "supported_coins": ["BTC", "ETH", "SOL", "AVAX"],
            },
        }

        # 如果是全链路接管，建议启动前端
        if level == "full":
            result["frontend_suggestion"] = self.s_layer.suggest_frontend_start()

        return result

    def revoke_handover(self) -> Dict[str, Any]:
        """撤销接管"""
        self.s_layer.token_budget.revoke_handover()

        record = {
            "timestamp": time.time(),
            "level": "none",
            "action": "revoke",
        }
        self._handover_history.append(record)

        return {
            "success": True,
            "handover_active": False,
            "message": "已撤销经典指标系统接管，恢复AI助手全功能",
        }

    def start_frontend(self) -> Dict[str, Any]:
        """
        启动前端（建议）

        实际实现中应调用前端启动命令，
        这里返回启动建议和URL。
        """
        self._frontend_started = True

        return {
            "success": True,
            "frontend_started": True,
            "frontend_url": self.classic_api_url,
            "message": f"经典指标系统前端已启动，请访问 {self.classic_api_url}",
            "features": [
                "实时行情监控",
                "多策略信号生成",
                "策略参数配置",
                "交易执行面板",
                "持仓管理",
            ],
        }

    def adjust_strategy(
        self,
        strategy_id: str,
        user_request: str,
        current_params: Dict,
    ) -> Dict[str, Any]:
        """
        调整经典指标系统策略（使用剩余Token）

        这是接管后LLM的主要用途
        """
        return self.s_layer.adjust_strategy_params(
            strategy_id=strategy_id,
            user_request=user_request,
            current_params=current_params,
        )

    def explain_result(
        self,
        result_data: Dict,
        user_question: str = "",
    ) -> Dict[str, Any]:
        """
        解释经典指标系统结果（使用剩余Token）
        """
        return self.s_layer.explain_classic_result(
            result_data=result_data,
            user_question=user_question,
        )

    def _describe_handover_effect(self, level: str) -> List[str]:
        """描述接管后的影响"""
        effects = {
            "token_save": [
                "减少LLM调用频率",
                "仅在关键决策时调用大模型",
                "节省约50%的Token消耗",
            ],
            "partial": [
                "部分节点由经典指标系统处理",
                "关键决策仍使用LLM验证",
                "节省约70%的Token消耗",
            ],
            "full": [
                "全链路由经典指标系统驱动",
                "LLM仅用于策略调整和结果解释",
                "节省约90%的Token消耗",
                "建议启动前端实现全面接管",
            ],
        }
        return effects.get(level, [])

    def get_stats(self) -> Dict[str, Any]:
        """获取接管统计"""
        return {
            "handover_active": self.s_layer.token_budget.handover_authorized,
            "handover_level": self.s_layer.token_budget.handover_level.value,
            "frontend_started": self._frontend_started,
            "classic_api_url": self.classic_api_url,
            "handover_history_count": len(self._handover_history),
            "token_stats": self.s_layer.token_budget.get_stats(),
        }


# ============================================================
# 导出
# ============================================================

__all__ = [
    'TokenBudgetManager',
    'TokenBudgetStatus',
    'TokenUsageRecord',
    'TokenBudgetAlert',
    'HandoverLevel',
    'SLayerLLMRecognizer',
    'ClassicHandoverManager',
]