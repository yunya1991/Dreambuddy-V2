"""ExitDecision — 离场决策结果数据类

字段：
  - action: hold / adjust_sl_tp / trailing / force_close / partial_close
  - params: 动作参数（new_sl_px / new_tp_px / trailing_arm_pct / trailing_retrace_pct / partial_pct）
  - reason: 决策原因字符串（含 evolution_exit:{action}:{detail} 标签）
  - sl_px: 建议的止损价（0.0 表示不变）
  - tp_px: 建议的止盈价（0.0 表示不变）
  - confidence: 决策置信度 [0, 1]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ExitDecision:
    """EvolutionExitEngine.decide() 返回值"""

    action: str  # hold / adjust_sl_tp / trailing / force_close / partial_close
    params: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    sl_px: float = 0.0
    tp_px: float = 0.0
    confidence: float = 0.0

    def __post_init__(self):
        if self.action not in ("hold", "adjust_sl_tp", "trailing", "force_close", "partial_close"):
            raise ValueError(f"ExitDecision.action 非法: {self.action}")
