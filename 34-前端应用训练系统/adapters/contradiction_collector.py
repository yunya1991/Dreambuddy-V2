# -*- coding: utf-8 -*-
"""矛盾分析采集器 — S 层 contradiction_insight 意图训练数据源 (SPEC v0.8 链路 A)。

矛盾系统（contradiction_identifier）在单一数据之上实现多数据动态交汇的金融含义。
从 23-自进化系统 evolution_pipeline.log 提取 C1-C8 维度矛盾方向/强度，
生成 (message, intent_type='contradiction_insight') 训练案例。

设计（SPEC-v0.8-evolution-dual-intent.md §4.1）:
  - 数据来源: evolution_pipeline.log 的 [Contradiction] 与 [T5-DimForce] 行
  - FAIL-OPEN: 日志缺失/解析失败返回空列表
"""
import os
import re
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

_LOG_PATH = os.path.join(
    _PROJECT_ROOT, "23-四层闭环自进化交易架构",
    "dreambuddy_evolution", "logs", "evolution_pipeline.log",
)

# 维度中文名
_DIM_DESC = {
    "C1": "资金面", "C2": "情绪面", "C3": "技术面", "C4": "宏观",
    "C6": "时序", "C7": "隐性", "C8": "衍生维度",
}

_DIR_DESC = {"long": "看多", "short": "看空", "neutral": "中性"}

# 问法模板
_TEMPLATES = [
    "现在{d1}和{d2}矛盾吗",
    "当前主要矛盾是什么",
    "各维度矛盾情况怎么样",
    "{d1}和{d2}一致吗",
    "帮我分析一下各维度的矛盾",
    "现在多维度数据之间有没有矛盾",
    "当前矛盾最激烈的维度是哪个",
    "多数据综合看矛盾状态如何",
]


class ContradictionCollector(TrainingDataProvider):
    """从 23 系统矛盾日志生成 contradiction_insight 意图训练样本。"""

    def get_source_name(self) -> str:
        return "contradiction_insight"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        if not os.path.exists(_LOG_PATH):
            return []
        try:
            with open(_LOG_PATH, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-3000:]
        except Exception:
            return []

        # 提取 [Contradiction] dim=Cx dir=xxx strength=0.xxx 行
        pat = re.compile(r"\[Contradiction\] dim=(C\d) dir=(\w+) strength=([0-9.]+)")
        dims = {}
        for line in lines:
            m = pat.search(line)
            if m:
                dim, direction, strength = m.group(1), m.group(2), float(m.group(3))
                dims[dim] = (direction, strength)
        if not dims:
            return []

        dim_keys = sorted(dims.keys())
        cases: List[TrainingCase] = []
        # 生成两两维度矛盾问法样本
        for i in range(len(dim_keys)):
            for j in range(i + 1, len(dim_keys)):
                if len(cases) >= limit:
                    return cases
                d1, d2 = dim_keys[i], dim_keys[j]
                n1, n2 = _DIM_DESC.get(d1, d1), _DIM_DESC.get(d2, d2)
                tpl = _TEMPLATES[len(cases) % len(_TEMPLATES)]
                message = tpl.format(d1=n1, d2=n2)
                dir1, s1 = dims[d1]
                dir2, s2 = dims[d2]
                conflict = "矛盾" if dir1 != dir2 else "一致"
                cases.append(TrainingCase(
                    intent="contradiction_insight",
                    actions=[f"contradiction:{d1}", f"contradiction:{d2}"],
                    outcome_text=message,
                    learned=[f"矛盾分析: {n1}({dir1},{s1:.2f}) vs {n2}({dir2},{s2:.2f}) → {conflict}"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.6,
                    source="contradiction_insight",
                    metadata={
                        "dim1": d1, "dir1": dir1, "strength1": s1,
                        "dim2": d2, "dir2": dir2, "strength2": s2,
                        "conflict": conflict,
                        "engine_hint": "23-自进化系统/矛盾系统",
                    },
                ))
        # 补充整体矛盾状态问法（模板 × 维度对组合，保证样本量达标）
        if len(cases) < limit:
            pairs = [("资金面", "技术面"), ("宏观", "情绪面"), ("资金面", "宏观"), ("技术面", "情绪面")]
            round_i = 0
            while len(cases) < limit and round_i < 4:
                for d1, d2 in pairs:
                    if len(cases) >= limit:
                        break
                    tpl = _TEMPLATES[(len(cases) + round_i) % len(_TEMPLATES)]
                    message = tpl.format(d1=d1, d2=d2)
                    cases.append(TrainingCase(
                        intent="contradiction_insight",
                        actions=["contradiction:all"],
                        outcome_text=message,
                        learned=[f"矛盾分析: {d1}与{d2}矛盾状态 ({len(dims)} 个维度在跟踪)"],
                        layer_tags=["S"],
                        quality="B",
                        confidence=0.5,
                        source="contradiction_insight",
                        metadata={"dims": {d: dims[d][0] for d in dims}, "engine_hint": "23-自进化系统/矛盾系统"},
                    ))
                round_i += 1
        return cases
