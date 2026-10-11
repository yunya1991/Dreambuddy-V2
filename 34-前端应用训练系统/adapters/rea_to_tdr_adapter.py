"""33-REA → TDR 数据转换适配器。

将 REAParseResult 转换为带 layer_tags 的 TrainingCase，
按照 SPEC §3.2 映射表将 33-REA 输出映射到 5 层训练数据。

映射规则:
  algorithm_patterns → layer_tags=DSH, C (solution_pattern)
  call_chain          → layer_tags=DSH (execution_path)
  dependency_graph    → layer_tags=G (graph)
  known_gaps          → layer_tags=C (reflection)
  observations        → layer_tags=LLM (learned)
"""
import os
import sys
from typing import List, Optional

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingCase
from interfaces.rea_parser import REAParseResult


def rea_to_training_cases(
    wrapup_case: dict,
    rea_result: Optional[REAParseResult],
) -> List[TrainingCase]:
    """将收尾案例 + 33-REA 解析结果转换为带 layer_tags 的 TrainingCase 列表。

    根据 REA 解析结果的不同维度，生成对应 layer_tags 的训练案例。
    如果 REA 解析失败（None），则生成一个仅含文本四元组的通用案例。

    Args:
        wrapup_case: 收尾案例数据（含 intent, actions, outcome_text, learned 等）
        rea_result: 33-REA 解析结果（可能为 None）

    Returns:
        带正确 layer_tags 的 TrainingCase 列表
    """
    if rea_result is None:
        # REA 不可用 → 降级为纯文本四元组
        return [_make_text_case(wrapup_case, layer_tags=["S", "DSH", "C", "G", "LLM"])]

    cases: List[TrainingCase] = []

    # 1. algorithm_patterns → DSH + C 层训练数据
    if rea_result.algorithm_patterns:
        cases.append(TrainingCase(
            intent=wrapup_case.get("intent", ""),
            actions=wrapup_case.get("actions", []),
            outcome_text=wrapup_case.get("outcome_text", ""),
            learned=rea_result.algorithm_patterns,
            layer_tags=["DSH", "C"],
            quality=_quality_from_evidence_level(rea_result.evidence_level),
            confidence=rea_result.confidence,
            source="rea_algorithm",
            metadata={"rea_field": "algorithm_patterns", "patterns": rea_result.algorithm_patterns},
        ))

    # 2. call_chain → DSH 层训练数据
    if rea_result.call_chain:
        cases.append(TrainingCase(
            intent=wrapup_case.get("intent", ""),
            actions=rea_result.call_chain,
            outcome_text=wrapup_case.get("outcome_text", ""),
            learned=wrapup_case.get("learned", []),
            layer_tags=["DSH"],
            quality=_quality_from_evidence_level(rea_result.evidence_level),
            confidence=rea_result.confidence,
            source="rea_call_chain",
            metadata={"rea_field": "call_chain", "chain_length": len(rea_result.call_chain)},
        ))

    # 3. dependency_graph → G 层训练数据
    if rea_result.dependency_graph:
        graph_learned = [
            f"{node} → {','.join(deps)}"
            for node, deps in rea_result.dependency_graph.items()
            if isinstance(deps, (list, dict))
        ] if isinstance(rea_result.dependency_graph, dict) else []
        cases.append(TrainingCase(
            intent=wrapup_case.get("intent", ""),
            actions=wrapup_case.get("actions", []),
            outcome_text=wrapup_case.get("outcome_text", ""),
            learned=graph_learned or ["dependency_graph_available"],
            layer_tags=["G"],
            quality=_quality_from_evidence_level(rea_result.evidence_level),
            confidence=rea_result.confidence,
            source="rea_dependency_graph",
            metadata={"rea_field": "dependency_graph", "node_count": len(rea_result.dependency_graph)},
        ))

    # 4. known_gaps → C 层训练数据（反思材料）
    if rea_result.known_gaps:
        cases.append(TrainingCase(
            intent=wrapup_case.get("intent", ""),
            actions=wrapup_case.get("actions", []),
            outcome_text=wrapup_case.get("outcome_text", ""),
            learned=rea_result.known_gaps,
            layer_tags=["C"],
            quality="C",  # known_gaps 是待解决项，质量标记为 C
            confidence=rea_result.confidence,
            source="rea_known_gaps",
            metadata={"rea_field": "known_gaps", "gap_count": len(rea_result.known_gaps)},
        ))

    # 5. observations → LLM 层训练数据（经验提取）
    if rea_result.observations:
        obs_learned = [
            obs.get("result", str(obs)) if isinstance(obs, dict) else str(obs)
            for obs in rea_result.observations
        ]
        cases.append(TrainingCase(
            intent=wrapup_case.get("intent", ""),
            actions=wrapup_case.get("actions", []),
            outcome_text=wrapup_case.get("outcome_text", ""),
            learned=obs_learned,
            layer_tags=["LLM"],
            quality=_quality_from_evidence_level(rea_result.evidence_level),
            confidence=rea_result.confidence,
            source="rea_observations",
            metadata={"rea_field": "observations", "obs_count": len(rea_result.observations)},
        ))

    # 如果 REA 有结果但没有生成任何 case（所有字段都空），降级为文本四元组
    if not cases:
        cases.append(_make_text_case(wrapup_case, layer_tags=["S", "DSH", "C", "G", "LLM"]))

    return cases


def _make_text_case(wrapup_case: dict, layer_tags: List[str]) -> TrainingCase:
    """从纯文本四元组创建通用训练案例。"""
    return TrainingCase(
        intent=wrapup_case.get("intent", ""),
        actions=wrapup_case.get("actions", []),
        outcome_text=wrapup_case.get("outcome_text", ""),
        learned=wrapup_case.get("learned", []),
        layer_tags=layer_tags,
        quality=wrapup_case.get("quality", "B"),
        confidence=wrapup_case.get("confidence", 0.4),
        source="wrapup_text",
    )


def _quality_from_evidence_level(level: str) -> str:
    """将 33-REA evidence_level (L1-L4) 映射为 TDR quality (S/A/B/C)。"""
    mapping = {"L1": "A", "L2": "B", "L3": "B", "L4": "C"}
    return mapping.get(level, "C")
