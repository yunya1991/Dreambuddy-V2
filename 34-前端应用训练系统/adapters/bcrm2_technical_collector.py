# -*- coding: utf-8 -*-
"""BCRM2.0 技术指标采集器 — S 层 technical_analysis 意图训练数据源 (SPEC v0.9)。

技术分析维度：根据技术指标推理运算（卦象/方向/置信度）。
从 11-易经推理系统 bcrm2_hourly_summary.json 提取逐币种推理结果，
生成 (message, intent_type='technical_analysis') 训练案例。

FAIL-OPEN: 汇总文件缺失/解析失败返回空列表。
"""
import json
import os
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

_SUMMARY_PATH = os.path.join(
    _PROJECT_ROOT, "11-易经推理系统", "data", "bcrm2", "bcrm2_hourly_summary.json"
)

_DIR_DESC = {"UP": "看涨", "DOWN": "看跌", "NEUTRAL": "中性"}

_TEMPLATES = [
    "{sym}技术面方向是什么",
    "技术指标怎么算的{sym}",
    "{sym}卦象是什么",
    "{sym}技术面置信度多少",
    "技术面分析一下{sym}",
    "BCRM对{sym}的推理结论",
    "{sym}技术指标推理结果",
    "帮我看看{sym}的技术面",
]


class BCRM2TechnicalCollector(TrainingDataProvider):
    """从 BCRM2 汇总生成 technical_analysis 意图训练样本。"""

    def get_source_name(self) -> str:
        return "technical_analysis"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        if not os.path.exists(_SUMMARY_PATH):
            return []
        try:
            with open(_SUMMARY_PATH, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return []
        results = (d or {}).get("results") or {}
        if not isinstance(results, dict):
            return []

        cases: List[TrainingCase] = []
        for idx, (sym, info) in enumerate(results.items()):
            if len(cases) >= limit:
                break
            if not isinstance(info, dict):
                continue
            direction = info.get("direction", "NEUTRAL")
            confidence = info.get("confidence", 0.0)
            hexagram = info.get("hexagram", "")
            tpl = _TEMPLATES[idx % len(_TEMPLATES)]
            message = tpl.format(sym=sym)
            cases.append(TrainingCase(
                intent="technical_analysis",
                actions=[f"technical:{sym}", f"direction:{direction}"],
                outcome_text=message,
                learned=[f"技术推理: {sym} 方向{_DIR_DESC.get(direction, direction)} 置信度{confidence:.2f} 卦象{hexagram}"],
                layer_tags=["S"],
                quality="B",
                confidence=0.6,
                source="technical_analysis",
                metadata={
                    "symbol": sym,
                    "direction": direction,
                    "confidence": confidence,
                    "hexagram": hexagram,
                    "engine_hint": "11-易经推理系统/BCRM2.0",
                },
            ))
        # 样本不足时用第二套问法补充
        if len(cases) < limit:
            for idx, (sym, info) in enumerate(results.items()):
                if len(cases) >= limit:
                    break
                if not isinstance(info, dict):
                    continue
                tpl = _TEMPLATES[(idx + 3) % len(_TEMPLATES)]
                message = tpl.format(sym=sym)
                cases.append(TrainingCase(
                    intent="technical_analysis",
                    actions=[f"technical:{sym}"],
                    outcome_text=message,
                    learned=[f"技术推理: {sym} 技术指标运算结论"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.5,
                    source="technical_analysis",
                    metadata={"symbol": sym, "engine_hint": "11-易经推理系统/BCRM2.0"},
                ))
        return cases
