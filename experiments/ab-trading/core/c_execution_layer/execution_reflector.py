#!/usr/bin/env python3
"""
C层 - 执行反思进化器

位置: experiments/ab-trading/core/c_execution_layer/execution_reflector.py

职责：
1. 执行完成后整体反思
2. 识别执行中的问题和优化点
3. 生成经验教训，用于进化
4. 持久化到记忆库
5. 支持后续执行时的经验复用

反思维度：
- 执行效率：耗时、成本、资源使用
- 结果质量：准确性、完整性、一致性
- 路径优化：是否有更优的执行路径
- 节点表现：哪些节点表现好/差
- 决策质量：动态决策是否正确
"""

import json
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ============================================================
# 反思结果数据结构
# ============================================================

@dataclass
class ReflectionInsight:
    """反思洞察"""
    insight_id: str = field(default_factory=lambda: _gen_id("insight"))
    category: str = ""  # efficiency / quality / path / node / decision
    level: str = "info"  # info / warning / error / improvement
    title: str = ""
    description: str = ""
    suggestion: str = ""
    confidence: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "insight_id": self.insight_id,
            "category": self.category,
            "level": self.level,
            "title": self.title,
            "description": self.description,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
        }


@dataclass
class ExecutionReflection:
    """执行反思结果"""
    reflection_id: str = field(default_factory=lambda: _gen_id("refl"))
    blueprint_id: str = ""
    objective_id: str = ""

    # 整体评估
    overall_score: float = 0.0  # 0-1 整体执行质量
    efficiency_score: float = 0.0
    quality_score: float = 0.0
    path_score: float = 0.0

    # 洞察列表
    insights: List[ReflectionInsight] = field(default_factory=list)

    # 经验教训
    lessons_learned: List[str] = field(default_factory=list)
    best_practices: List[str] = field(default_factory=list)

    # 改进建议
    improvement_suggestions: List[str] = field(default_factory=list)

    # 节点评分
    node_scores: Dict[str, float] = field(default_factory=dict)

    # 原始LLM输出
    raw_llm_output: str = ""

    # 元信息
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "reflection_id": self.reflection_id,
            "blueprint_id": self.blueprint_id,
            "objective_id": self.objective_id,
            "overall_score": self.overall_score,
            "efficiency_score": self.efficiency_score,
            "quality_score": self.quality_score,
            "path_score": self.path_score,
            "insights": [i.to_dict() for i in self.insights],
            "lessons_learned": self.lessons_learned,
            "best_practices": self.best_practices,
            "improvement_suggestions": self.improvement_suggestions,
            "node_scores": self.node_scores,
            "created_at": self.created_at,
        }


# ============================================================
# 记忆库（简单实现）
# ============================================================

class MemoryStore:
    """记忆库

    持久化反思结果和经验教训
    """

    def __init__(self, store_path: Optional[str] = None):
        """
        Args:
            store_path: 记忆库存储路径（可选，默认在项目data目录下）
        """
        if store_path:
            self.store_path = Path(store_path)
        else:
            self.store_path = Path(__file__).parent.parent.parent / "data" / "reflection_memory.json"

        self._cache: Optional[Dict] = None

    def save_reflection(self, reflection: ExecutionReflection):
        """保存反思结果"""
        data = self._load_data()

        if "reflections" not in data:
            data["reflections"] = []

        data["reflections"].append(reflection.to_dict())

        # 更新经验索引
        self._update_lessons_index(data, reflection)

        self._save_data(data)

    def get_relevant_lessons(
        self,
        objective_type: str,
        context: Optional[Dict] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """获取相关的经验教训"""
        data = self._load_data()

        lessons = data.get("lessons_index", {}).get(objective_type, [])

        # 简单返回最近的
        return lessons[:limit]

    def _load_data(self) -> Dict:
        """加载数据"""
        if self._cache is not None:
            return self._cache

        if self.store_path.exists():
            try:
                with open(self.store_path, 'r', encoding='utf-8') as f:
                    self._cache = json.load(f)
                    return self._cache
            except Exception:
                pass

        self._cache = {"reflections": [], "lessons_index": {}}
        return self._cache

    def _save_data(self, data: Dict):
        """保存数据"""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._cache = data

    def _update_lessons_index(self, data: Dict, reflection: ExecutionReflection):
        """更新经验索引"""
        if "lessons_index" not in data:
            data["lessons_index"] = {}

        # 按目标类型分类（这里简化处理）
        obj_type = reflection.objective_id.split('_')[0] if reflection.objective_id else "default"

        if obj_type not in data["lessons_index"]:
            data["lessons_index"][obj_type] = []

        for lesson in reflection.lessons_learned:
            data["lessons_index"][obj_type].append({
                "lesson": lesson,
                "reflection_id": reflection.reflection_id,
                "score": reflection.overall_score,
                "timestamp": reflection.created_at,
            })

        # 只保留最近100条
        data["lessons_index"][obj_type] = data["lessons_index"][obj_type][-100:]


# ============================================================
# 执行反思器
# ============================================================

class ExecutionReflector:
    """执行反思进化器

    对整个执行过程进行反思，生成经验教训
    """

    SYSTEM_PROMPT = """你是专业的交易系统执行反思分析师。你的任务是对整个执行过程进行深度反思，
识别问题、总结经验、提出改进建议。

反思维度：
1. 执行效率 - 耗时、成本、资源使用是否合理
2. 结果质量 - 输出准确性、完整性、一致性如何
3. 路径优化 - 执行路径是否最优，有无冗余或缺失
4. 节点表现 - 各节点表现如何，哪些好哪些差
5. 决策质量 - 动态决策是否正确及时

请严格按照以下JSON格式输出（不要输出任何其他内容）：
{
  "overall_score": 0.8,
  "efficiency_score": 0.75,
  "quality_score": 0.85,
  "path_score": 0.7,
  "insights": [
    {
      "category": "efficiency",
      "level": "warning",
      "title": "耗时较长",
      "description": "技术分析节点耗时超过预期",
      "suggestion": "考虑使用缓存或并行优化",
      "confidence": 0.8
    }
  ],
  "lessons_learned": ["经验教训1", "经验教训2"],
  "best_practices": ["最佳实践1", "最佳实践2"],
  "improvement_suggestions": ["改进建议1", "改进建议2"],
  "node_scores": {
    "node1": 0.9,
    "node2": 0.7
  }
}
"""

    def __init__(
        self,
        use_llm: bool = True,
        llm_purpose: str = "chain_fusion_reflection",
        memory_store: Optional[MemoryStore] = None,
        enable_persistence: bool = False,
    ):
        """
        Args:
            use_llm: 是否使用LLM进行反思
            llm_purpose: LLM调用用途
            memory_store: 记忆库实例
            enable_persistence: 是否启用持久化
        """
        self.use_llm = use_llm
        self.llm_purpose = llm_purpose
        self.memory_store = memory_store or MemoryStore()
        self.enable_persistence = enable_persistence

    def reflect(
        self,
        execution_history: List[Any],  # List[NodeExecutionResult]
        blueprint: Optional[Any] = None,  # ExecutionBlueprint
        context: Optional[Dict] = None,
    ) -> ExecutionReflection:
        """
        执行反思

        Args:
            execution_history: 执行历史
            blueprint: 执行蓝图
            context: 执行上下文

        Returns:
            ExecutionReflection - 反思结果
        """
        reflection = ExecutionReflection()

        if blueprint:
            reflection.blueprint_id = getattr(blueprint, 'blueprint_id', '')
            reflection.objective_id = getattr(blueprint, 'objective_id', '')

        # 执行反思
        try:
            if self.use_llm:
                reflection = self._reflect_with_llm(
                    execution_history, blueprint, context
                )
            else:
                reflection = self._reflect_with_rules(
                    execution_history, blueprint, context
                )
        except Exception as e:
            reflection = self._reflect_with_rules(execution_history, blueprint, context)
            reflection.insights.append(ReflectionInsight(
                category="quality",
                level="warning",
                title="LLM反思失败",
                description=f"LLM反思异常，使用规则反思: {e}",
                suggestion="检查LLM服务状态",
                confidence=0.5,
            ))

        # 持久化
        if self.enable_persistence:
            try:
                self.memory_store.save_reflection(reflection)
            except Exception:
                pass

        return reflection

    def _reflect_with_llm(
        self,
        execution_history: List[Any],
        blueprint: Optional[Any],
        context: Optional[Dict],
    ) -> ExecutionReflection:
        """使用LLM反思"""
        try:
            from ..llm_client import llm_chat
        except ImportError:
            return self._reflect_with_rules(execution_history, blueprint, context)

        # 构建提示词
        prompt = self._build_reflection_prompt(execution_history, blueprint, context)

        # 调用LLM
        try:
            llm_output = llm_chat(
                prompt=prompt,
                system=self.SYSTEM_PROMPT,
                max_tokens=800,
                purpose=self.llm_purpose,
            )

            if llm_output:
                reflection = self._parse_reflection_output(llm_output)
                if blueprint:
                    reflection.blueprint_id = getattr(blueprint, 'blueprint_id', '')
                    reflection.objective_id = getattr(blueprint, 'objective_id', '')
                return reflection
        except Exception:
            pass

        return self._reflect_with_rules(execution_history, blueprint, context)

    def _build_reflection_prompt(
        self,
        execution_history: List[Any],
        blueprint: Optional[Any],
        context: Optional[Dict],
    ) -> str:
        """构建反思提示词"""
        parts = []

        if blueprint:
            parts.append("## 执行蓝图")
            parts.append(f"- 蓝图ID: {getattr(blueprint, 'blueprint_id', '')}")
            parts.append(f"- 目标ID: {getattr(blueprint, 'objective_id', '')}")
            parts.append(f"- 执行模式: {getattr(blueprint, 'execution_mode', '')}")
            parts.append(f"- 节点序列: {getattr(blueprint, 'node_sequence', [])}")
            parts.append("")

        parts.append("## 执行历史")
        total_duration = 0
        for i, result in enumerate(execution_history):
            duration = getattr(result, 'duration_ms', 0)
            total_duration += duration
            confidence = getattr(result, 'confidence', 0)
            status = getattr(result, 'status', 'unknown')
            parts.append(f"### 节点 {i+1}: {result.node_id}")
            parts.append(f"- 状态: {status.value if hasattr(status, 'value') else status}")
            parts.append(f"- 耗时: {duration:.0f}ms")
            parts.append(f"- 置信度: {confidence:.2f}")
            error = getattr(result, 'error', None)
            if error:
                parts.append(f"- 错误: {error}")
            parts.append("")

        parts.append(f"**总耗时: {total_duration:.0f}ms**")
        parts.append("")

        if context:
            parts.append("## 上下文")
            parts.append(json.dumps(context, ensure_ascii=False, indent=2)[:500])
            parts.append("")

        parts.append("请对以上执行过程进行深度反思。")

        return "\n".join(parts)

    def _parse_reflection_output(self, llm_output: str) -> ExecutionReflection:
        """解析LLM反思输出"""
        reflection = ExecutionReflection()
        reflection.raw_llm_output = llm_output

        try:
            json_str = llm_output
            start = llm_output.find("{")
            end = llm_output.rfind("}")
            if start >= 0 and end >= 0:
                json_str = llm_output[start:end + 1]

            data = json.loads(json_str)

            reflection.overall_score = float(data.get("overall_score", 0.0))
            reflection.efficiency_score = float(data.get("efficiency_score", 0.0))
            reflection.quality_score = float(data.get("quality_score", 0.0))
            reflection.path_score = float(data.get("path_score", 0.0))
            reflection.lessons_learned = list(data.get("lessons_learned", []))
            reflection.best_practices = list(data.get("best_practices", []))
            reflection.improvement_suggestions = list(data.get("improvement_suggestions", []))
            reflection.node_scores = dict(data.get("node_scores", {}))

            # 解析洞察
            insights_data = data.get("insights", [])
            for ins_data in insights_data:
                insight = ReflectionInsight(
                    category=ins_data.get("category", ""),
                    level=ins_data.get("level", "info"),
                    title=ins_data.get("title", ""),
                    description=ins_data.get("description", ""),
                    suggestion=ins_data.get("suggestion", ""),
                    confidence=float(ins_data.get("confidence", 0.0)),
                )
                reflection.insights.append(insight)

        except Exception as e:
            reflection.insights.append(ReflectionInsight(
                category="quality",
                level="error",
                title="反思结果解析失败",
                description=str(e),
                suggestion="检查LLM输出格式",
                confidence=0.3,
            ))

        return reflection

    def _reflect_with_rules(
        self,
        execution_history: List[Any],
        blueprint: Optional[Any],
        context: Optional[Dict],
    ) -> ExecutionReflection:
        """基于规则的反思（降级用）"""
        reflection = ExecutionReflection()

        # 填充蓝图信息
        if blueprint:
            reflection.blueprint_id = getattr(blueprint, 'blueprint_id', '')
            reflection.objective_id = getattr(blueprint, 'objective_id', '')

        if not execution_history:
            reflection.overall_score = 0.0
            reflection.lessons_learned.append("没有执行历史可供反思")
            return reflection

        # 基础统计
        total = len(execution_history)
        successful = sum(
            1 for r in execution_history
            if hasattr(r, 'is_success') and r.is_success
        )
        failed = total - successful

        total_duration = sum(getattr(r, 'duration_ms', 0) for r in execution_history)
        avg_confidence = (
            sum(getattr(r, 'confidence', 0) for r in execution_history) / total
            if total > 0 else 0
        )

        # 计算各维度得分
        success_rate = successful / total if total > 0 else 0
        reflection.quality_score = success_rate * 0.5 + avg_confidence * 0.5
        reflection.efficiency_score = max(0, 1 - total_duration / 60000)  # 60秒以内满分
        reflection.path_score = 0.7  # 规则无法评估路径
        reflection.overall_score = (
            reflection.quality_score * 0.4
            + reflection.efficiency_score * 0.3
            + reflection.path_score * 0.3
        )

        # 节点评分
        for r in execution_history:
            if hasattr(r, 'is_success') and r.is_success:
                reflection.node_scores[r.node_id] = getattr(r, 'confidence', 0.5)
            else:
                reflection.node_scores[r.node_id] = 0.0

        # 生成洞察
        if failed > 0:
            reflection.insights.append(ReflectionInsight(
                category="quality",
                level="error",
                title=f"{failed}个节点失败",
                description=f"执行中有{failed}/{total}个节点失败",
                suggestion="检查失败节点的原因，考虑降级或替换",
                confidence=0.9,
            ))

        if avg_confidence < 0.5:
            reflection.insights.append(ReflectionInsight(
                category="quality",
                level="warning",
                title="整体置信度偏低",
                description=f"平均置信度仅{avg_confidence:.2f}",
                suggestion="考虑增加更多数据源或使用更高质量的模型",
                confidence=0.8,
            ))

        if total_duration > 30000:
            reflection.insights.append(ReflectionInsight(
                category="efficiency",
                level="warning",
                title="执行耗时较长",
                description=f"总耗时{total_duration:.0f}ms，超过30秒",
                suggestion="考虑并行执行或优化慢节点",
                confidence=0.7,
            ))

        # 经验教训
        if successful == total:
            reflection.lessons_learned.append("全部节点执行成功，路径规划合理")
            reflection.best_practices.append("按顺序执行所有节点，确保每个环节质量")
        else:
            reflection.lessons_learned.append(f"执行成功率 {success_rate:.0%}，有待提升")
            reflection.improvement_suggestions.append("提升失败节点的稳定性")

        return reflection
