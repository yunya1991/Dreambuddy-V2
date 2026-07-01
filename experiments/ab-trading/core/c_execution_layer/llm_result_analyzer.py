#!/usr/bin/env python3
"""
C层 - LLM结果分析器

位置: experiments/ab-trading/core/c_execution_layer/llm_result_analyzer.py

职责：
1. 用大模型分析节点执行结果的质量
2. 评估置信度是否合理
3. 识别异常、矛盾、遗漏
4. 输出结构化分析结果

基于项目已有 llm_client.py 的 llm_chat() 函数
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from .types import NodeExecutionResult


# ============================================================
# 分析结果数据结构
# ============================================================

@dataclass
class ResultAnalysis:
    """结果分析

    LLM对节点执行结果的结构化分析
    """
    node_id: str

    # 质量评估
    quality_score: float = 0.0  # 0-1，结果质量
    completeness: float = 0.0   # 完整性
    consistency: float = 0.0    # 一致性
    relevance: float = 0.0      # 相关性

    # 问题识别
    issues: List[str] = field(default_factory=list)
    anomalies: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    missing_info: List[str] = field(default_factory=list)

    # 置信度校验
    confidence_appropriate: bool = True
    confidence_suggestion: Optional[float] = None

    # 总结
    summary: str = ""
    is_acceptable: bool = True

    # 原始LLM输出
    raw_llm_output: str = ""

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "quality_score": self.quality_score,
            "completeness": self.completeness,
            "consistency": self.consistency,
            "relevance": self.relevance,
            "issues": self.issues,
            "anomalies": self.anomalies,
            "contradictions": self.contradictions,
            "missing_info": self.missing_info,
            "confidence_appropriate": self.confidence_appropriate,
            "confidence_suggestion": self.confidence_suggestion,
            "summary": self.summary,
            "is_acceptable": self.is_acceptable,
        }


# ============================================================
# LLM结果分析器
# ============================================================

class LLMResultAnalyzer:
    """LLM结果分析器

    使用大模型分析节点执行结果的质量
    """

    SYSTEM_PROMPT = """你是专业的交易系统执行结果分析师。你的任务是分析节点执行结果的质量，
识别问题、异常和矛盾，并给出质量评估。

请严格按照以下JSON格式输出（不要输出任何其他内容）：
{
  "quality_score": 0.8,
  "completeness": 0.7,
  "consistency": 0.9,
  "relevance": 0.85,
  "issues": ["问题1", "问题2"],
  "anomalies": ["异常1"],
  "contradictions": ["矛盾1"],
  "missing_info": ["缺失信息1"],
  "confidence_appropriate": true,
  "confidence_suggestion": 0.75,
  "summary": "结果质量评估摘要",
  "is_acceptable": true
}

评估标准：
- quality_score: 整体质量，0-1
- completeness: 信息完整性，是否覆盖了所有必要维度
- consistency: 结果内部一致性，是否自相矛盾
- relevance: 与目标的相关性
- is_acceptable: 是否可以接受（质量>0.6且无致命问题）
"""

    def __init__(
        self,
        purpose: str = "chain_fusion_analysis",
        max_tokens: int = 500,
        use_llm: bool = True,
    ):
        """
        Args:
            purpose: LLM调用用途（用于配额管理）
            max_tokens: 最大token数
            use_llm: 是否使用LLM（false时用规则分析）
        """
        self.purpose = purpose
        self.max_tokens = max_tokens
        self.use_llm = use_llm

    def analyze(
        self,
        node_result: NodeExecutionResult,
        context: Optional[Dict] = None,
        objective_info: Optional[Dict] = None,
    ) -> ResultAnalysis:
        """
        分析节点执行结果

        Args:
            node_result: 节点执行结果
            context: 执行上下文
            objective_info: 目标信息

        Returns:
            ResultAnalysis - 分析结果
        """
        analysis = ResultAnalysis(node_id=node_result.node_id)

        # 如果节点失败，直接返回
        if not node_result.is_success:
            analysis.quality_score = 0.0
            analysis.is_acceptable = False
            analysis.summary = f"节点执行失败: {node_result.error}"
            analysis.issues = [node_result.error or "未知错误"]
            return analysis

        # 使用LLM分析或规则分析
        if self.use_llm:
            try:
                analysis = self._analyze_with_llm(node_result, context, objective_info)
            except Exception as e:
                # LLM失败，降级到规则分析
                analysis = self._analyze_with_rules(node_result, context, objective_info)
                analysis.raw_llm_output = f"LLM调用失败，使用规则分析: {e}"
        else:
            analysis = self._analyze_with_rules(node_result, context, objective_info)

        return analysis

    def _analyze_with_llm(
        self,
        node_result: NodeExecutionResult,
        context: Optional[Dict],
        objective_info: Optional[Dict],
    ) -> ResultAnalysis:
        """使用LLM分析"""
        # 延迟导入避免循环依赖
        try:
            from ..llm_client import llm_chat
        except ImportError:
            return self._analyze_with_rules(node_result, context, objective_info)

        # 构建提示词
        prompt = self._build_analysis_prompt(node_result, context, objective_info)

        # 调用LLM
        llm_output = llm_chat(
            prompt=prompt,
            system=self.SYSTEM_PROMPT,
            max_tokens=self.max_tokens,
            purpose=self.purpose,
        )

        if not llm_output:
            return self._analyze_with_rules(node_result, context, objective_info)

        # 解析结果
        analysis = self._parse_llm_output(llm_output, node_result.node_id)
        analysis.raw_llm_output = llm_output

        return analysis

    def _build_analysis_prompt(
        self,
        node_result: NodeExecutionResult,
        context: Optional[Dict],
        objective_info: Optional[Dict],
    ) -> str:
        """构建分析提示词"""
        parts = []

        parts.append("## 节点信息")
        parts.append(f"- 节点ID: {node_result.node_id}")
        parts.append(f"- 节点名称: {node_result.node_name or '未知'}")
        parts.append(f"- 执行耗时: {node_result.duration_ms:.0f}ms")
        parts.append(f"- 置信度: {node_result.confidence:.2f}")
        parts.append("")

        parts.append("## 节点输出")
        if node_result.outputs:
            parts.append(json.dumps(node_result.outputs, ensure_ascii=False, indent=2))
        else:
            parts.append("(无输出)")
        parts.append("")

        if objective_info:
            parts.append("## 目标信息")
            parts.append(json.dumps(objective_info, ensure_ascii=False, indent=2))
            parts.append("")

        if context and context.get("previous_results"):
            parts.append("## 前置节点结果")
            parts.append(json.dumps(context["previous_results"], ensure_ascii=False, indent=2))
            parts.append("")

        parts.append("请分析这个节点执行结果的质量。")

        return "\n".join(parts)

    def _parse_llm_output(self, llm_output: str, node_id: str) -> ResultAnalysis:
        """解析LLM输出"""
        analysis = ResultAnalysis(node_id=node_id)
        analysis.raw_llm_output = llm_output

        # 尝试提取JSON
        try:
            # 寻找JSON块
            json_str = llm_output
            start = llm_output.find("{")
            end = llm_output.rfind("}")
            if start >= 0 and end >= 0:
                json_str = llm_output[start:end + 1]

            data = json.loads(json_str)

            analysis.quality_score = float(data.get("quality_score", 0.0))
            analysis.completeness = float(data.get("completeness", 0.0))
            analysis.consistency = float(data.get("consistency", 0.0))
            analysis.relevance = float(data.get("relevance", 0.0))
            analysis.issues = list(data.get("issues", []))
            analysis.anomalies = list(data.get("anomalies", []))
            analysis.contradictions = list(data.get("contradictions", []))
            analysis.missing_info = list(data.get("missing_info", []))
            analysis.confidence_appropriate = bool(data.get("confidence_appropriate", True))
            analysis.confidence_suggestion = data.get("confidence_suggestion")
            analysis.summary = str(data.get("summary", ""))
            analysis.is_acceptable = bool(data.get("is_acceptable", True))

        except Exception as e:
            # 解析失败，使用默认值
            analysis.quality_score = 0.7
            analysis.completeness = 0.7
            analysis.consistency = 0.8
            analysis.relevance = 0.7
            analysis.is_acceptable = True
            analysis.summary = f"LLM输出解析失败: {e}"

        return analysis

    def _analyze_with_rules(
        self,
        node_result: NodeExecutionResult,
        context: Optional[Dict],
        objective_info: Optional[Dict],
    ) -> ResultAnalysis:
        """基于规则的简单分析（降级用）"""
        analysis = ResultAnalysis(node_id=node_result.node_id)

        # 默认值
        analysis.consistency = 0.8  # 默认一致性较好
        analysis.relevance = 0.7    # 默认相关性中等

        # 基础检查
        if not node_result.outputs:
            analysis.quality_score = 0.3
            analysis.completeness = 0.2
            analysis.is_acceptable = False
            analysis.issues = ["节点输出为空"]
            analysis.summary = "节点输出为空，结果不可接受"
            return analysis

        # 置信度检查
        if node_result.confidence < 0.3:
            analysis.issues.append("置信度过低")
            analysis.is_acceptable = False

        # 输出字段丰富度
        if isinstance(node_result.outputs, dict):
            field_count = len(node_result.outputs)
            if field_count == 0:
                analysis.completeness = 0.1
            elif field_count == 1:
                analysis.completeness = 0.4
            elif field_count <= 3:
                analysis.completeness = 0.7
            else:
                analysis.completeness = 0.9

            # 检查关键指标
            if "confidence" in node_result.outputs:
                conf = node_result.outputs["confidence"]
                if isinstance(conf, (int, float)):
                    analysis.confidence_appropriate = (
                        abs(conf - node_result.confidence) < 0.3
                    )
                    if not analysis.confidence_appropriate:
                        analysis.issues.append("内外置信度差异大")

        # 计算综合质量分
        analysis.quality_score = (
            analysis.completeness * 0.4
            + analysis.consistency * 0.3
            + analysis.relevance * 0.3
        )

        if not analysis.issues:
            analysis.summary = "规则分析：结果基本可接受"
            analysis.is_acceptable = analysis.quality_score >= 0.5
        else:
            analysis.summary = f"规则分析：发现 {len(analysis.issues)} 个问题"

        return analysis
