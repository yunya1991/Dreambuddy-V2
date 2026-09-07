"""
ftc_combiner — FTC 步骤自由组合（基因重组 + gmax 变异）

生物类比:
  - 基因重组: 从两条 FTC 中各取部分步骤组合成新 FTC
  - 基因突变: 以 gmax 概率随机添加/删除/替换步骤

组合策略:
  1. 随机选两条父代 FTC
  2. 交叉: 按 gmax 概率从父代 A 取 condition，从父代 B 取 inference+action
  3. 变异: 以 gmax 概率添加随机 condition，或替换 action
  4. 新 FTC 必须有 condition + action（可执行链）

gmax 范围 [0.1, 0.5]，来自 ReflectionEngine 的 gmax 值。
"""
from __future__ import annotations

import random
import logging
from typing import Optional

from .ftc_schema import FTC, FTCStep, gen_ftc_id, gen_step_id

logger = logging.getLogger(__name__)


# 可用于变异的 condition 基因池（从经验路径拆解得到的基因类型）
MUTATION_CONDITION_POOL = [
    {"gene_ref": "CD-VOL-SURGE", "description": "成交量放大", "data_required": ["vol_5", "vol_20"], "threshold": 1.3},
    {"gene_ref": "CD-PRICE-BREAKOUT", "description": "价格站上MA20", "data_required": ["close"], "threshold": True},
    {"gene_ref": "CD-ADX-STRONG", "description": "趋势强度ADX>20", "data_required": ["adx"], "threshold": 20},
    {"gene_ref": "CD-CAPITAL-ROTATION", "description": "资金轮动信号", "data_required": ["capital_rotation"], "threshold": 0.1},
    {"gene_ref": "CD-CAPITAL-INFLOW", "description": "资金流入", "data_required": ["capital_flow"], "threshold": 0.0},
    {"gene_ref": "CD-OI-DIVERGENCE", "description": "OI与价格背离", "data_required": ["oi_change_pct"], "threshold": 0.05},
    {"gene_ref": "CD-FUNDING-EXTREME", "description": "费率极端", "data_required": ["funding_rate"], "threshold": 0.001},
    {"gene_ref": "CD-ZSCORE-EXTREME", "description": "z_score偏离均值", "data_required": ["close", "ma20"], "threshold": 2.0},
    {"gene_ref": "CD-REGIME-RANGING", "description": "震荡市", "data_required": ["regime"]},
    {"gene_ref": "CD-REGIME-TREND", "description": "趋势市", "data_required": ["regime"]},
]

MUTATION_ACTION_POOL = [
    {"gene_ref": "AC-LONG", "description": "做多"},
    {"gene_ref": "AC-SHORT", "description": "做空"},
    {"gene_ref": "AC-FOLLOW-STRONG", "description": "跟随强势"},
    {"gene_ref": "AC-CONTRARIAN", "description": "反向交易"},
    {"gene_ref": "AC-SECTOR-ROTATION", "description": "板块轮动"},
]


def combine_ftcs(
    parent_a: FTC,
    parent_b: FTC,
    gmax: float = 0.3,
) -> Optional[FTC]:
    """
    两条 FTC 交叉 + 变异生成新 FTC。

    Args:
        parent_a, parent_b: 父代 FTC
        gmax: 变异概率 [0.1, 0.5]

    Returns:
        新 FTC 或 None（如果无法形成可执行链）
    """
    gmax = max(0.1, min(0.5, gmax))

    # 交叉: 从 A 取 conditions，从 B 取 inferences + action
    conditions = list(parent_a.condition_steps)
    inferences = list(parent_b.inference_steps)
    actions = list(parent_b.action_steps)

    # 变异: 以 gmax 概率添加随机 condition
    if random.random() < gmax:
        mut = random.choice(MUTATION_CONDITION_POOL)
        new_cond = FTCStep(
            step_id=gen_step_id(),
            type="condition",
            description=mut["description"],
            gene_ref=mut["gene_ref"],
            data_required=mut.get("data_required", []),
            threshold=mut.get("threshold"),
            depends_on=[conditions[-1].step_id] if conditions else [],
        )
        conditions.append(new_cond)

    # 变异: 以 gmax 概率替换 action
    if random.random() < gmax:
        mut = random.choice(MUTATION_ACTION_POOL)
        actions = [FTCStep(
            step_id=gen_step_id(),
            type="action",
            description=mut["description"],
            gene_ref=mut["gene_ref"],
            depends_on=[inferences[-1].step_id] if inferences else (
                [conditions[-1].step_id] if conditions else []
            ),
        )]

    # 变异: 以 gmax/2 概率删除一个 condition（避免组合过长）
    if len(conditions) > 2 and random.random() < gmax / 2:
        conditions.pop(random.randint(0, len(conditions) - 1))

    # 重组步骤并重建依赖链
    steps = _rebuild_steps(conditions, inferences, actions)

    if not steps:
        return None

    # 必须有 condition + action
    has_cond = any(s.type == "condition" for s in steps)
    has_action = any(s.type == "action" for s in steps)
    if not has_cond or not has_action:
        return None

    new_ftc = FTC(
        ftc_id=gen_ftc_id("FTC-NEW"),
        name=f"组合({parent_a.name[:6]}+{parent_b.name[:6]})",
        steps=steps,
        source="exploration",
    )
    return new_ftc


def _rebuild_steps(
    conditions: list[FTCStep],
    inferences: list[FTCStep],
    actions: list[FTCStep],
) -> list[FTCStep]:
    """重组步骤并重建线性依赖链"""
    steps: list[FTCStep] = []
    prev_id: Optional[str] = None

    for cond in conditions:
        cond.depends_on = [prev_id] if prev_id else []
        steps.append(cond)
        prev_id = cond.step_id

    for inf in inferences:
        inf.depends_on = [prev_id] if prev_id else []
        steps.append(inf)
        prev_id = inf.step_id

    for act in actions:
        act.depends_on = [prev_id] if prev_id else []
        steps.append(act)
        prev_id = act.step_id

    return steps


def generate_combinations(
    ftc_pool: list[FTC],
    n_combinations: int = 10,
    gmax: float = 0.3,
) -> list[FTC]:
    """
    从 FTC 池中随机选取父代，生成 n 条组合 FTC。

    优先从利用轨道和混合轨道选父代（好基因重组）。
    """
    if len(ftc_pool) < 2:
        return []

    # 按轨道优先级排序: exploit > mixed > explore
    track_order = {"exploit": 0, "mixed": 1, "explore": 2}
    sorted_pool = sorted(ftc_pool, key=lambda f: track_order.get(f.track, 3))

    results: list[FTC] = []
    attempts = 0
    max_attempts = n_combinations * 5

    while len(results) < n_combinations and attempts < max_attempts:
        attempts += 1
        # 随机选两条（前 50% 优先）
        n = len(sorted_pool)
        a_idx = random.randint(0, min(n - 1, n // 2 + 1))
        b_idx = random.randint(0, n - 1)
        if a_idx == b_idx:
            continue

        parent_a = sorted_pool[a_idx]
        parent_b = sorted_pool[b_idx]

        new_ftc = combine_ftcs(parent_a, parent_b, gmax)
        if new_ftc and new_ftc.has_executable_chain():
            results.append(new_ftc)

    return results
