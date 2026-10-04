"""TimeoutVoter 抽象基类 + VoteTicket 数据类

统一四方案 voter 接口：
  - evaluate(ctx) → Optional[VoteTicket]  评估并投票，异常返回 None（FAIL-OPEN）
  - required_fields() → list[str]          声明依赖的 context 字段
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class VoteTicket:
    """单 voter 的投票结果

    action:
      - "force_close"   投票强平
      - "hold"          投票继续持有
      - "adjust_sl_tp"  投票调整 SL/TP（如方案C将SL下移到支撑位）
    confidence: [0, 1] 方案自身置信度
    reason: "voter_a:vcp_break_below_swing_low" 等
    sl_px: adjust_sl_tp 时建议的 SL 价格
    tp_px: adjust_sl_tp 时建议的 TP 价格（0.0=不变）
    voter_id: "A" / "B" / "C" / "D"
    """

    action: str
    confidence: float
    reason: str
    voter_id: str
    sl_px: float = 0.0
    tp_px: float = 0.0

    def __post_init__(self):
        if self.action not in ("force_close", "hold", "adjust_sl_tp"):
            raise ValueError(f"VoteTicket.action 非法: {self.action}")


class TimeoutVoter(ABC):
    """超时强平软投票 voter 抽象基类

    四方案各自实现 evaluate()，对同一 context 投票。
    仲裁层收集四票后加权决策。
    """

    voter_id: str = ""  # 子类必须覆盖

    @abstractmethod
    def evaluate(self, ctx: Dict[str, Any]) -> Optional[VoteTicket]:
        """评估 context 返回投票。

        Returns:
            VoteTicket 或 None（FAIL-OPEN：字段缺失/异常时返回 None）
        """
        raise NotImplementedError

    @abstractmethod
    def required_fields(self) -> list[str]:
        """声明依赖的 context 字段列表（用于诊断缺失字段）"""
        raise NotImplementedError

    def _safe_get(self, ctx: Dict[str, Any], field: str, default: Any = None) -> Any:
        """安全读取字段，缺失返回 default"""
        return ctx.get(field, default)
