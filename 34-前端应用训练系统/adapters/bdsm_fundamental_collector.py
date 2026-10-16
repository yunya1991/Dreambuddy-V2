# -*- coding: utf-8 -*-
"""BDSM 基本面采集器 — S 层 fundamental_valuation 意图训练数据源 (SPEC v0.9)。

单币种基本面维度：聚焦单一币种估值等维度分析。
从 11-易经推理系统 .workbuddy/bdsm/ 最新快照提取逐币种估值结论，
生成 (message, intent_type='fundamental_valuation') 训练案例。

FAIL-OPEN: 快照目录缺失/解析失败返回空列表。
"""
import glob
import json
import os
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

_BDSM_DIR = os.path.join(
    _PROJECT_ROOT, "11-易经推理系统", ".workbuddy", "bdsm"
)

_TEMPLATES = [
    "{sym}估值怎么样",
    "{sym}基本面分析",
    "这个币{sym}估值高不高",
    "{sym}单币种基本面结论",
    "帮我分析下{sym}的估值",
    "BDSM对{sym}的评估",
    "{sym}现在处于什么阶段",
    "{sym}估值百分位是多少",
]


class BDSMFundamentalCollector(TrainingDataProvider):
    """从 BDSM 每日快照生成 fundamental_valuation 意图训练样本。"""

    def get_source_name(self) -> str:
        return "fundamental_valuation"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        if not os.path.isdir(_BDSM_DIR):
            return []
        files = sorted(glob.glob(os.path.join(_BDSM_DIR, "bdsm_snapshot_*.json")))
        if not files:
            return []
        try:
            with open(files[-1], encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return []
        coins = (d or {}).get("coins") or {}
        if not isinstance(coins, dict):
            return []

        cases: List[TrainingCase] = []
        for idx, (sym, info) in enumerate(coins.items()):
            if len(cases) >= limit:
                break
            if not isinstance(info, dict) or not info.get("available"):
                continue
            score = info.get("score", 0.0)
            rank = info.get("rank", "")
            phase = info.get("phase", "")
            pct = info.get("valuation_percentile", 0.0)
            tpl = _TEMPLATES[idx % len(_TEMPLATES)]
            message = tpl.format(sym=sym)
            cases.append(TrainingCase(
                intent="fundamental_valuation",
                actions=[f"valuation:{sym}", f"rank:{rank}"],
                outcome_text=message,
                learned=[f"估值分析: {sym} 评分{score:.2f} 等级{rank} 阶段{phase} 估值百分位{pct:.0f}"],
                layer_tags=["S"],
                quality="B",
                confidence=0.6,
                source="fundamental_valuation",
                metadata={
                    "symbol": sym,
                    "score": score,
                    "rank": rank,
                    "phase": phase,
                    "valuation_percentile": pct,
                    "direction_constraint": info.get("direction_constraint", ""),
                    "engine_hint": "11-易经推理系统/BDSM",
                },
            ))
        # 样本不足时用第二套问法补充
        if len(cases) < limit:
            for idx, (sym, info) in enumerate(coins.items()):
                if len(cases) >= limit:
                    break
                if not isinstance(info, dict) or not info.get("available"):
                    continue
                tpl = _TEMPLATES[(idx + 4) % len(_TEMPLATES)]
                message = tpl.format(sym=sym)
                cases.append(TrainingCase(
                    intent="fundamental_valuation",
                    actions=[f"valuation:{sym}"],
                    outcome_text=message,
                    learned=[f"估值分析: {sym} 单币种基本面维度结论"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.5,
                    source="fundamental_valuation",
                    metadata={"symbol": sym, "engine_hint": "11-易经推理系统/BDSM"},
                ))
        return cases
