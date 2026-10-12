"""P4: 33-REA 零 token 反思驱动 — C-Drive L1 层集成
=====================================================
33-REA 逆向解析产物直接驱动 C-Drive 反思，替代中置信度场景的 LLM 辩论。

推导逻辑（零 token，纯规则）：
  1. known_gaps 关键词 → 反射决策（从 rea_keyword_map.yaml 加载）
  2. call_chain 断裂 → INSERT_BEFORE（调用链不完整）
  3. dependency_graph 有环 → REDO（依赖循环）
  4. confidence < 0.3 → REDO（对齐 CDRIVE_CONF_REDO）
  5. evidence_level == UNKNOWN → EARLY_TERMINATE（事实不足）
  6. 无信号 → None（降级 P3/P2/P1）

集成链: P4(33-REA) → P3(Debate) → P2(C-Drive) → P1(语义)
P4 优先级最高，有信号时直接返回，无信号时降级到 P3。

关联：
  - 33-REA: 33-REA逆向解析工程/core/evidence.py
  - REAParseResult: 34-前端应用训练系统/interfaces/rea_parser.py
  - decision_deriver: 34-前端应用训练系统/core/decision_deriver.py
  - SPEC: 35-广义认知系统协作模块/SPEC-CDrive-CognitiveSystem-Integration.md §2.1
"""
import os
import re
from typing import Any, Dict, List, Optional, Set

# ============================================================
# 常量
# ============================================================

# 反射决策类型（对齐 decision_deriver.py）
CONTINUE = "CONTINUE"
REDO = "REDO"
INSERT_BEFORE = "INSERT_BEFORE"
JUMP_TO = "JUMP_TO"
EARLY_TERMINATE = "EARLY_TERMINATE"

# 33-REA confidence 阈值（对齐 CDRIVE_CONF_REDO=0.20 语义，取 0.3 留缓冲）
REA_CONF_THRESHOLD = 0.3

# evidence_level 无法确定时的标记
REA_UNKNOWN_LEVEL = "UNKNOWN"

# 配置文件路径
_KEYWORD_MAP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "rea_keyword_map.yaml",
)

# 默认关键词映射（YAML 配置不存在时的 fallback）
_DEFAULT_KEYWORD_MAP: Dict[str, Any] = {
    "known_gaps_map": [
        {"pattern": r"missing|缺失|未实现|absent|not.?implemented", "decision": INSERT_BEFORE},
        {"pattern": r"wrong|错误|bug|incorrect|flaw", "decision": REDO},
        {"pattern": r"dead|无用|冗余|redundant|unused|orphan", "decision": EARLY_TERMINATE},
        {"pattern": r"circular|循环依赖|cycle|cyclic", "decision": REDO},
    ],
    "call_chain_break_markers": ["???", "unknown", "broken", "缺失", "断裂"],
    "evidence_level_map": {"UNKNOWN": EARLY_TERMINATE},
}


# ============================================================
# 配置加载
# ============================================================

def _load_keyword_map(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载关键词映射配置（YAML），失败时 fallback 到默认映射。

    Args:
        config_path: YAML 配置路径。None 时使用默认路径。

    Returns:
        关键词映射字典，包含 known_gaps_map / call_chain_break_markers / evidence_level_map
    """
    path = config_path or _KEYWORD_MAP_PATH
    if not os.path.exists(path):
        return _DEFAULT_KEYWORD_MAP

    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict):
            # 确保必要字段存在
            data.setdefault("known_gaps_map", _DEFAULT_KEYWORD_MAP["known_gaps_map"])
            data.setdefault("call_chain_break_markers", _DEFAULT_KEYWORD_MAP["call_chain_break_markers"])
            data.setdefault("evidence_level_map", _DEFAULT_KEYWORD_MAP["evidence_level_map"])
            return data
    except Exception:
        # YAML 加载失败 → fallback
        pass

    return _DEFAULT_KEYWORD_MAP


# ============================================================
# 辅助函数
# ============================================================

def _detect_cycle(dependency_graph: Dict[str, Any]) -> bool:
    """检测 dependency_graph 中是否有环（DFS）。

    Args:
        dependency_graph: {节点: [依赖节点列表]}

    Returns:
        True 如果存在环
    """
    if not dependency_graph:
        return False

    # 确保是 dict 且值为 list
    graph: Dict[str, List[str]] = {}
    for k, v in dependency_graph.items():
        if isinstance(v, list):
            graph[str(k)] = [str(x) for x in v]
        elif isinstance(v, (str, int)):
            graph[str(k)] = [str(v)]
        elif isinstance(v, dict):
            # 嵌套结构，提取 keys 作为依赖
            graph[str(k)] = [str(x) for x in v.keys()]

    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {node: WHITE for node in graph}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in graph.get(node, []):
            if neighbor not in color:
                color[neighbor] = WHITE
            if color[neighbor] == GRAY:
                return True  # 回边 → 环
            if color[neighbor] == WHITE and dfs(neighbor):
                return True
        color[node] = BLACK
        return False

    for node in graph:
        if color[node] == WHITE:
            if dfs(node):
                return True
    return False


def _check_call_chain_break(call_chain: List[str], break_markers: List[str]) -> bool:
    """检测 call_chain 是否有断裂。

    Args:
        call_chain: 调用链列表
        break_markers: 断裂标记关键词

    Returns:
        True 如果检测到断裂
    """
    if not call_chain:
        return True  # 空调用链 = 断裂

    for segment in call_chain:
        segment_lower = str(segment).lower()
        for marker in break_markers:
            if marker.lower() in segment_lower:
                return True
    return False


# ============================================================
# 主函数
# ============================================================

def derive_decision_from_rea(rea_result) -> Optional[str]:
    """33-REA 零 token 驱动 C-Drive 反思。

    将 33-REA 解析结果映射为 C-Drive 反射决策，纯规则无 LLM token。

    Args:
        rea_result: REAParseResult 实例（来自 interfaces.rea_parser）

    Returns:
        反射决策字符串（CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE），
        或 None 表示无信号（降级到 P3/P2/P1）。

    推导优先级:
      1. known_gaps 关键词 → 决策（第一个匹配）
      2. call_chain 断裂 → INSERT_BEFORE
      3. dependency_graph 有环 → REDO
      4. confidence < REA_CONF_THRESHOLD → REDO
      5. evidence_level == UNKNOWN → EARLY_TERMINATE
      6. 无信号 → None
    """
    if rea_result is None:
        return None

    # 加载关键词配置
    keyword_map = _load_keyword_map()

    # 1. known_gaps 关键词 → 决策
    gaps_map = keyword_map.get("known_gaps_map", [])
    for gap in rea_result.known_gaps:
        for entry in gaps_map:
            pattern = entry.get("pattern", "")
            decision = entry.get("decision", "")
            if pattern and decision and re.search(pattern, str(gap), re.IGNORECASE):
                return decision

    # 2. call_chain 断裂 → INSERT_BEFORE
    break_markers = keyword_map.get("call_chain_break_markers", [])
    if _check_call_chain_break(rea_result.call_chain, break_markers):
        return INSERT_BEFORE

    # 3. dependency_graph 有环 → REDO
    if _detect_cycle(rea_result.dependency_graph):
        return REDO

    # 4. confidence < 阈值 → REDO
    if rea_result.confidence < REA_CONF_THRESHOLD:
        return REDO

    # 5. evidence_level == UNKNOWN → EARLY_TERMINATE
    evidence_map = keyword_map.get("evidence_level_map", {})
    decision = evidence_map.get(rea_result.evidence_level)
    if decision:
        return decision

    # 6. 无信号 → None（降级到 P3/P2/P1）
    return None
