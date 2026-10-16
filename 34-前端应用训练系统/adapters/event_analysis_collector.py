# -*- coding: utf-8 -*-
"""金融事件分析采集器 — S 层 event_analysis 意图训练数据源 (v1.0)。

针对某一金融事件（FOMC/加息/降息等）进行分析。
数据来源（已验证）:
  ① 11-易经推理系统 data/event_driven_state.json — 实时事件驱动状态
     （surprise/priced_in/real_rate/resilience/cross_asset/news 六维评分、
      event_type/event_phase、confidence、reason、forward_guidance）
  ② 29-事件驱动策略系统 EventCaseLibrary — FOMC 历史案例
     （event_date/cycle_phase/decision/market_reaction/relief_or_reversal/pnl_30d）

生成 (message, intent_type='event_analysis') 训练案例。
FAIL-OPEN: 数据缺失/解析失败返回空列表。
"""
import glob
import json
import os
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# 实时事件驱动状态（11 系统）
_EVENT_STATE_PATH = os.path.join(
    _PROJECT_ROOT, "11-易经推理系统", "data", "event_driven_state.json"
)
# FOMC 事件案例库（29 系统，DREAMBUDDY_DATA 默认指向 11 系统 data）
_CASE_LIBRARY_PATHS = [
    os.path.join(_PROJECT_ROOT, "11-易经推理系统", "data", "event_case_library.json"),
    os.path.join(_PROJECT_ROOT, "29-事件驱动策略系统", "event_case_library.json"),
]

_DECISION_DESC = {"hike": "加息", "cut": "降息", "hold": "按兵不动"}

# 问法模板（事件分析类）
_TEMPLATES = [
    "这次FOMC事件怎么看",
    "当前事件驱动信号是什么",
    "市场对这次事件的反应如何",
    "事件超预期了吗",
    "这个事件被price in了吗",
    "事件驱动策略现在什么状态",
    "加息事件对市场影响是什么",
    "分析一下当前金融事件",
    "事件处于什么阶段",
    "事件后市场会怎么走",
]


class EventAnalysisCollector(TrainingDataProvider):
    """从事件驱动状态与 FOMC 案例库生成 event_analysis 意图训练样本。"""

    def get_source_name(self) -> str:
        return "event_analysis"

    def get_quality_threshold(self) -> str:
        return "B"

    def _load_json(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        cases: List[TrainingCase] = []

        # ---- 数据源 ①: 实时事件驱动状态 ----
        state = self._load_json(_EVENT_STATE_PATH) if os.path.exists(_EVENT_STATE_PATH) else None
        if isinstance(state, dict):
            sig = state.get("signal") or {}
            scores = sig.get("scores") or {}
            event_type = sig.get("event_type", "none")
            event_phase = sig.get("event_phase", "")
            confidence = sig.get("confidence", 0.0)
            reason = sig.get("reason", "")
            guidance = sig.get("forward_guidance", "")
            surprise = scores.get("surprise", 0.0)
            priced_in = scores.get("priced_in", 0.0)
            score_summary = "/".join(f"{k}:{v:.2f}" for k, v in scores.items())
            for idx, tpl in enumerate(_TEMPLATES):
                if len(cases) >= limit:
                    break
                message = tpl
                cases.append(TrainingCase(
                    intent="event_analysis",
                    actions=[f"event:{event_type}", f"phase:{event_phase}"],
                    outcome_text=message,
                    learned=[f"事件分析: 类型{event_type} 阶段{event_phase} 意外度{surprise:.2f} 定价度{priced_in:.2f} → {reason}"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.6,
                    source="event_analysis",
                    metadata={
                        "event_type": event_type,
                        "event_phase": event_phase,
                        "confidence": confidence,
                        "scores": scores,
                        "reason": reason,
                        "forward_guidance": guidance,
                        "engine_hint": "29-事件驱动策略系统",
                    },
                ))

        # ---- 数据源 ②: FOMC 历史案例库 ----
        lib = None
        for p in _CASE_LIBRARY_PATHS:
            if os.path.exists(p):
                lib = self._load_json(p)
                if lib is not None:
                    break
        if isinstance(lib, dict):
            items = lib.get("cases") or lib.get("_cases") or []
            if isinstance(items, list):
                for idx, c in enumerate(items):
                    if len(cases) >= limit:
                        break
                    if not isinstance(c, dict):
                        continue
                    date = c.get("event_date", "")
                    decision = c.get("decision", "hold")
                    phase = c.get("cycle_phase", "")
                    reaction = c.get("market_reaction") or {}
                    tag = c.get("relief_or_reversal", "")
                    pnl = c.get("pnl_30d")
                    dec_cn = _DECISION_DESC.get(decision, decision)
                    message = f"{date}美联储{dec_cn}事件怎么分析的"
                    reaction_summary = "/".join(f"{k}:{v}" for k, v in reaction.items())
                    cases.append(TrainingCase(
                        intent="event_analysis",
                        actions=[f"event_case:{date}", f"decision:{decision}"],
                        outcome_text=message,
                        learned=[f"事件案例: {date} {dec_cn} 阶段{phase} 市场反应{reaction_summary} → {tag or '无标签'}"],
                        layer_tags=["S"],
                        quality="B",
                        confidence=0.55,
                        source="event_analysis",
                        metadata={
                            "event_date": date,
                            "decision": decision,
                            "cycle_phase": phase,
                            "relief_or_reversal": tag,
                            "pnl_30d": pnl,
                            "engine_hint": "29-事件驱动策略系统/EventCaseLibrary",
                        },
                    ))

        return cases
