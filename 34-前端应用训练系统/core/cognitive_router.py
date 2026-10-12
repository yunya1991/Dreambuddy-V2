"""P5: 大认知系统匹配度+案例密度路由 — L3 层集成
=====================================================
recall 返回的 memories 数量和 score 作为路由依据，替代单维 confidence。
二维路由: (match_score, case_density) → Tier 1-4

路由规则:
  Tier 1: match_score >= 0.7 AND case_density >= 3 → L3 fast-path 直接推进
  Tier 2: match_score < 0.7 AND case_density >= 2  → L1 33-REA 反思（零 token）
  Tier 3: match_score < 0.4 AND case_density < 2   → L3 SKILL 调研 → L1 33-REA 路径
  Tier 4: multi_path=True                           → L4 Debate 选择

关联:
  - SPEC: 35-广义认知系统协作模块/SPEC-CDrive-CognitiveSystem-Integration.md §2.2
  - C-Drive Agent: 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py
  - 33-REA: 34-前端应用训练系统/core/rea_cdrive_adapter.py (P4)
"""
from typing import Any, Dict, List, Optional, Tuple, Union

# ============================================================
# 常量
# ============================================================

# Tier 标识
TIER1 = "TIER1"  # 高匹配 → 直接推进
TIER2 = "TIER2"  # 低匹配 → 33-REA 反思
TIER3 = "TIER3"  # 案例少+低匹配 → SKILL 调研
TIER4 = "TIER4"  # 多路径 → Debate

# 路由阈值（对齐 SPEC §2.2.2）
TIER1_MATCH_THRESHOLD = 0.7    # match_score >= 0.7
TIER1_DENSITY_THRESHOLD = 3    # case_density >= 3
TIER3_MATCH_THRESHOLD = 0.4    # match_score < 0.4
TIER3_DENSITY_THRESHOLD = 2    # case_density < 2
TIER2_DENSITY_THRESHOLD = 2    # case_density >= 2

# 加权系数
MAX_SCORE_WEIGHT = 0.6
AVG_SCORE_WEIGHT = 0.4


# ============================================================
# 数据结构
# ============================================================

class RouteResult:
    """路由结果"""

    def __init__(self, tier: str, description: str, token_cost: str = "0"):
        self.tier = tier
        self.description = description
        self.token_cost = token_cost

    def __repr__(self):
        return f"RouteResult(tier={self.tier}, desc={self.description}, token={self.token_cost})"


# ============================================================
# 匹配度评估
# ============================================================

def evaluate_match(memories: Optional[List[Any]]) -> Tuple[float, int]:
    """评估 recall 结果的匹配度和案例密度。

    Args:
        memories: recall 返回的记忆列表，每个元素需有 .score 属性或 "score" 键

    Returns:
        (match_score, case_density)
        match_score = max_score * 0.6 + avg_score * 0.4（加权）
        case_density = len(memories)
    """
    if not memories:
        return (0.0, 0)

    # 提取 scores（兼容对象和 dict）
    scores: List[float] = []
    for m in memories:
        if hasattr(m, "score"):
            scores.append(float(m.score))
        elif isinstance(m, dict) and "score" in m:
            scores.append(float(m["score"]))
        else:
            scores.append(0.0)

    if not scores:
        return (0.0, 0)

    max_score = max(scores)
    avg_score = sum(scores) / len(scores)
    match_score = max_score * MAX_SCORE_WEIGHT + avg_score * AVG_SCORE_WEIGHT
    case_density = len(memories)

    return (match_score, case_density)


# ============================================================
# 路由函数
# ============================================================

def route(
    match_score: float,
    case_density: int,
    multi_path: bool = False,
) -> RouteResult:
    """根据匹配度和案例密度路由到不同 Tier。

    路由优先级:
      1. multi_path=True → Tier 4 (Debate)  [最高优先级]
      2. match_score >= 0.7 AND density >= 3 → Tier 1 (fast-path)
      3. match_score < 0.4 AND density < 2 → Tier 3 (SKILL 调研)
      4. match_score < 0.7 AND density >= 2 → Tier 2 (33-REA 反思)
      5. 默认 → Tier 2 (安全降级)

    Args:
        match_score: 匹配度评分 (0.0-1.0)
        case_density: 案例密度 (recall 返回的记忆数量)
        multi_path: 是否检测到多路径（33-REA 或 Debate 检测）

    Returns:
        RouteResult: 包含 tier、description、token_cost
    """
    # 确保非负
    match_score = max(0.0, match_score)

    # 1. 多路径 → Tier 4 (Debate) — 最高优先级
    if multi_path:
        return RouteResult(
            tier=TIER4,
            description="L4 Debate 选择（多路径复杂场景）",
            token_cost="LLM",
        )

    # 2. 高匹配 + 高密度 → Tier 1 (fast-path)
    if match_score >= TIER1_MATCH_THRESHOLD and case_density >= TIER1_DENSITY_THRESHOLD:
        return RouteResult(
            tier=TIER1,
            description="L3 fast-path 直接推进（高匹配度+高密度）",
            token_cost="0",
        )

    # 3. 低匹配 + 低密度 → Tier 3 (SKILL 调研)
    if match_score < TIER3_MATCH_THRESHOLD and case_density < TIER3_DENSITY_THRESHOLD:
        return RouteResult(
            tier=TIER3,
            description="L3 SKILL 调研 → L1 33-REA 路径分析（案例少+低匹配）",
            token_cost="LLM",
        )

    # 4. 低匹配 + 有密度 → Tier 2 (33-REA 反思)
    if match_score < TIER1_MATCH_THRESHOLD and case_density >= TIER2_DENSITY_THRESHOLD:
        return RouteResult(
            tier=TIER2,
            description="L1 33-REA 反思推理（低匹配度，零 token）",
            token_cost="0",
        )

    # 5. 默认 → Tier 2 (安全降级)
    return RouteResult(
        tier=TIER2,
        description="L1 33-REA 反思推理（默认路由）",
        token_cost="0",
    )
