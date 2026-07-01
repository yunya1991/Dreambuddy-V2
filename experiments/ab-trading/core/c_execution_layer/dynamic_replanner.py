#!/usr/bin/env python3
"""
C层 - 动态重规划器

位置: experiments/ab-trading/core/c_execution_layer/dynamic_replanner.py

职责：
1. 当决策器判断需要重规划时，重新生成执行蓝图
2. 支持两种重规划模式：
   - 增量调整：在当前蓝图基础上调整
   - 完全重规划：调用S层意图识别引擎重新生成
3. 管理重规划历史，避免无限重规划
4. 支持重规划次数限制

重规划触发条件：
- 节点执行失败且无法重试
- 结果质量严重不达标
- 发现当前路径与目标偏离
- 上下文发生重大变化
"""

import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ============================================================
# 重规划结果
# ============================================================

@dataclass
class ReplanningResult:
    """重规划结果"""
    replan_id: str = field(default_factory=lambda: _gen_id("replan"))
    success: bool = False
    reason: str = ""

    # 新蓝图（可选）
    new_blueprint: Optional[Any] = None  # ExecutionBlueprint
    blueprint_delta: Optional[Dict] = None  # 增量变更

    # 变更说明
    added_nodes: List[str] = field(default_factory=list)
    removed_nodes: List[str] = field(default_factory=list)
    reordered: bool = False

    # 重规划统计
    replan_count: int = 0
    max_replans_reached: bool = False

    def to_dict(self) -> Dict:
        return {
            "replan_id": self.replan_id,
            "success": self.success,
            "reason": self.reason,
            "added_nodes": self.added_nodes,
            "removed_nodes": self.removed_nodes,
            "reordered": self.reordered,
            "replan_count": self.replan_count,
            "max_replans_reached": self.max_replans_reached,
        }


# ============================================================
# 动态重规划器
# ============================================================

class DynamicReplanner:
    """动态重规划器

    当执行路径出现问题时，动态重新规划执行蓝图
    """

    def __init__(
        self,
        max_replans: int = 3,
        use_llm: bool = True,
        llm_purpose: str = "chain_fusion_replan",
    ):
        """
        Args:
            max_replans: 最大重规划次数（防止无限循环）
            use_llm: 是否使用LLM进行重规划
            llm_purpose: LLM调用用途
        """
        self.max_replans = max_replans
        self.use_llm = use_llm
        self.llm_purpose = llm_purpose

        # 重规划历史
        self.replan_history: List[ReplanningResult] = []

    def reset(self):
        """重置重规划状态"""
        self.replan_history = []

    @property
    def replan_count(self) -> int:
        """已重规划次数"""
        return len(self.replan_history)

    @property
    def can_replan(self) -> bool:
        """是否还可以重规划"""
        return self.replan_count < self.max_replans

    def replan(
        self,
        current_blueprint: Any,  # ExecutionBlueprint
        failed_node_id: str,
        reason: str,
        execution_history: List[Any],  # List[NodeExecutionResult]
        context: Optional[Dict] = None,
    ) -> ReplanningResult:
        """
        执行重规划

        Args:
            current_blueprint: 当前执行蓝图
            failed_node_id: 失败的节点ID
            reason: 重规划原因
            execution_history: 执行历史
            context: 执行上下文

        Returns:
            ReplanningResult - 重规划结果
        """
        result = ReplanningResult()
        result.reason = reason
        result.replan_count = self.replan_count

        # 检查是否达到重规划上限
        if not self.can_replan:
            result.success = False
            result.max_replans_reached = True
            result.reason = f"已达到最大重规划次数({self.max_replans})"
            self.replan_history.append(result)
            return result

        # 执行重规划
        try:
            if self.use_llm:
                result = self._replan_with_llm(
                    current_blueprint, failed_node_id, reason,
                    execution_history, context
                )
            else:
                result = self._replan_with_rules(
                    current_blueprint, failed_node_id, reason,
                    execution_history, context
                )

            result.replan_count = self.replan_count + 1

        except Exception as e:
            result.success = False
            result.reason = f"重规划异常: {e}"

        # 记录历史
        self.replan_history.append(result)

        return result

    def _replan_with_llm(
        self,
        current_blueprint: Any,
        failed_node_id: str,
        reason: str,
        execution_history: List[Any],
        context: Optional[Dict],
    ) -> ReplanningResult:
        """使用LLM重规划"""
        try:
            from ..llm_client import llm_chat
        except ImportError:
            return self._replan_with_rules(
                current_blueprint, failed_node_id, reason,
                execution_history, context
            )

        # 构建提示词
        prompt = self._build_replan_prompt(
            current_blueprint, failed_node_id, reason,
            execution_history, context
        )

        system_prompt = """你是专业的交易系统执行规划师。你的任务是根据执行过程中出现的问题，
重新规划执行路径。

请分析当前的执行情况，决定如何调整执行蓝图。你可以：
1. 跳过有问题的节点，继续后续节点
2. 替换问题节点为备选节点
3. 添加新的节点来补充缺失的信息
4. 完全重新规划路径

请严格按照以下JSON格式输出（不要输出任何其他内容）：
{
  "success": true,
  "new_node_sequence": ["node1", "node2", "node3"],
  "added_nodes": ["new_node"],
  "removed_nodes": ["bad_node"],
  "reordered": false,
  "reason": "调整原因说明",
  "execution_mode": "sequential"
}
"""

        # 调用LLM
        try:
            llm_output = llm_chat(
                prompt=prompt,
                system=system_prompt,
                max_tokens=500,
                purpose=self.llm_purpose,
            )

            if llm_output:
                return self._parse_replan_output(llm_output, current_blueprint)
        except Exception:
            pass

        # LLM失败，降级到规则
        return self._replan_with_rules(
            current_blueprint, failed_node_id, reason,
            execution_history, context
        )

    def _build_replan_prompt(
        self,
        current_blueprint: Any,
        failed_node_id: str,
        reason: str,
        execution_history: List[Any],
        context: Optional[Dict],
    ) -> str:
        """构建重规划提示词"""
        parts = []

        parts.append("## 当前蓝图")
        parts.append(f"- 蓝图ID: {current_blueprint.blueprint_id}")
        parts.append(f"- 目标ID: {current_blueprint.objective_id}")
        parts.append(f"- 执行模式: {current_blueprint.execution_mode}")
        parts.append(f"- 节点序列: {current_blueprint.node_sequence}")
        parts.append("")

        parts.append("## 问题节点")
        parts.append(f"- 节点ID: {failed_node_id}")
        parts.append(f"- 问题原因: {reason}")
        parts.append("")

        parts.append("## 已完成节点")
        completed = [
            r.node_id for r in execution_history
            if hasattr(r, 'is_success') and r.is_success
        ]
        parts.append(f"- 已完成: {completed}")
        parts.append("")

        if context:
            parts.append("## 上下文")
            obj_info = context.get("objective_info", {})
            if obj_info:
                parts.append(f"- 目标类型: {obj_info.get('type', 'unknown')}")
                parts.append(f"- 复杂度: {obj_info.get('complexity', 'standard')}")
            parts.append("")

        parts.append("请根据以上信息，重新规划执行路径。")

        return "\n".join(parts)

    def _parse_replan_output(
        self,
        llm_output: str,
        current_blueprint: Any,
    ) -> ReplanningResult:
        """解析LLM重规划输出"""
        import json

        result = ReplanningResult()

        try:
            json_str = llm_output
            start = llm_output.find("{")
            end = llm_output.rfind("}")
            if start >= 0 and end >= 0:
                json_str = llm_output[start:end + 1]

            data = json.loads(json_str)

            result.success = bool(data.get("success", False))
            result.added_nodes = list(data.get("added_nodes", []))
            result.removed_nodes = list(data.get("removed_nodes", []))
            result.reordered = bool(data.get("reordered", False))
            result.reason = data.get("reason", "")

            # 如果有新的节点序列，创建增量蓝图
            new_sequence = data.get("new_node_sequence")
            if new_sequence and result.success:
                # 复制当前蓝图并修改
                new_blueprint = self._clone_blueprint(current_blueprint)
                new_blueprint.node_sequence = new_sequence
                new_mode = data.get("execution_mode")
                if new_mode:
                    new_blueprint.execution_mode = new_mode
                result.new_blueprint = new_blueprint

        except Exception as e:
            result.success = False
            result.reason = f"解析重规划结果失败: {e}"

        return result

    def _replan_with_rules(
        self,
        current_blueprint: Any,
        failed_node_id: str,
        reason: str,
        execution_history: List[Any],
        context: Optional[Dict],
    ) -> ReplanningResult:
        """基于规则的重规划（降级用）"""
        result = ReplanningResult()
        result.success = False
        result.reason = reason

        # 规则1：如果是可选节点失败，跳过它
        if current_blueprint and hasattr(current_blueprint, 'node_sequence'):
            node_seq = current_blueprint.node_sequence

            # 找到失败节点的位置
            if failed_node_id in node_seq:
                idx = node_seq.index(failed_node_id)

                # 简单策略：跳过失败节点，继续后续节点
                new_blueprint = self._clone_blueprint(current_blueprint)
                new_sequence = node_seq[:idx] + node_seq[idx + 1:]
                new_blueprint.node_sequence = new_sequence

                result.success = True
                result.new_blueprint = new_blueprint
                result.removed_nodes = [failed_node_id]
                result.reason = f"跳过失败节点 {failed_node_id}: {reason}"

        return result

    def _clone_blueprint(self, blueprint: Any) -> Any:
        """克隆蓝图"""
        import copy
        return copy.deepcopy(blueprint)
