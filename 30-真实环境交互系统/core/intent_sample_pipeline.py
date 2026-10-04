"""IntentSample 数据结构 + Pipeline（落盘 + 分桶 + 触发训练）

对齐 SPEC-20261004 §3.2 / §3.3 + SPEC-20260929 §2.1 IntentSample 格式。
HC-1a：本模块在 30 系统内，不修改 dreamos/。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class IntentSample:
    """意图识别训练样本

    字段（对齐 spec §3.2）：
    - sample_id: UUID
    - input: {user_query, scenario_id, market_features, data_freshness?}
    - gold: {gold_chain, gold_intent}  # gold_chain: C|F|A 三大思维链
    - recognizer_output: {predicted_intent, confidence, level}
    - human_label: {confirmed, corrected_intent?}
    - dataset_split: train | eval
    - created_at: ISO8601
    """
    sample_id: str
    input: Dict[str, Any]
    gold: Dict[str, str]
    recognizer_output: Dict[str, Any]
    human_label: Dict[str, Any]
    dataset_split: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentSample":
        return cls(**data)
