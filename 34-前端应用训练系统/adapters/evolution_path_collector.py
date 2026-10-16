# -*- coding: utf-8 -*-
"""路径意图采集器 — S 层 path_insight 意图训练数据源 (SPEC v0.8 链路 B)。

矛盾 Transformer（cross_attention + hjb_solver）在多矛盾维度交汇后求解最小阻力路径。
从 23-自进化系统 evolution_snapshots.json 提取币种的维度预测交汇与动作决策，
生成 (message, intent_type='path_insight') 训练案例。

设计（SPEC-v0.8-evolution-dual-intent.md §4.2）:
  - 数据来源: evolution_snapshots.json 的 dimension_predictions / action / level0_dstar
  - FAIL-OPEN: 快照缺失/解析失败返回空列表
"""
import json
import os
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

_SNAPSHOT_PATH = os.path.join(
    _PROJECT_ROOT, "23-四层闭环自进化交易架构",
    "dreambuddy_evolution", "gene_data", "evolution_snapshots.json",
)

_DIR_DESC = {"long": "看多", "short": "看空", "neutral": "中性"}

# 问法模板（{sym} 为币种）
_TEMPLATES = [
    "多维度综合看{sym}该往哪走",
    "{sym}的最小阻力路径是什么方向",
    "各维度交汇后{sym}的结论是什么",
    "综合判断现在{sym}该多还是空",
    "多数据动态交汇看{sym}怎么走",
    "矛盾Transformer对{sym}的综合判断是什么",
    "{sym}多维度数据交汇后的方向",
    "帮我看看{sym}的最优路径",
]


class EvolutionPathCollector(TrainingDataProvider):
    """从 23 系统快照生成 path_insight 意图训练样本。"""

    def get_source_name(self) -> str:
        return "path_insight"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        if not os.path.exists(_SNAPSHOT_PATH):
            return []
        try:
            with open(_SNAPSHOT_PATH, encoding="utf-8") as f:
                snap = json.load(f)
        except Exception:
            return []
        if not isinstance(snap, dict):
            return []

        cases: List[TrainingCase] = []
        for idx, (sym, info) in enumerate(snap.items()):
            if len(cases) >= limit:
                break
            if not isinstance(info, dict):
                continue
            dim_pred = info.get("dimension_predictions") or {}
            action = info.get("action", "neutral")
            dstar = info.get("level0_dstar", "neutral")
            if not dim_pred:
                continue
            tpl = _TEMPLATES[idx % len(_TEMPLATES)]
            message = tpl.format(sym=sym)
            # 维度交汇摘要
            votes = list(dim_pred.values())
            agree = sum(1 for v in votes if v == action)
            summary = "/".join(f"{k}:{_DIR_DESC.get(v, v)}" for k, v in dim_pred.items())
            cases.append(TrainingCase(
                intent="path_insight",
                actions=[f"path:{sym}", f"action:{action}"],
                outcome_text=message,
                learned=[f"路径交汇: {sym} {summary} → 最小阻力路径 {action}（{agree}/{len(votes)} 维度一致）"],
                layer_tags=["S"],
                quality="B",
                confidence=0.6,
                source="path_insight",
                metadata={
                    "symbol": sym,
                    "dimension_predictions": dim_pred,
                    "action": action,
                    "level0_dstar": dstar,
                    "agree_ratio": f"{agree}/{len(votes)}",
                    "engine_hint": "23-自进化系统/矛盾Transformer",
                },
            ))
        return cases
