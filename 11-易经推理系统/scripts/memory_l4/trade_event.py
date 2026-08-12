"""
TradeEvent — 全局交易事件统一数据结构

用于监听和记录所有交易系统（易经推理、马丁策略、三屏趋势、Agent A/B、Dream OS）
的交易闭环，作为 L4 TradeCase 的标准化输入。

系统来源标识：
- yijing_inference: 易经推理模型
- three_screen: 三屏趋势模型  
- martin_v15: 马丁策略 V15
- agent_a: Agent A
- agent_b: Agent B
- dream_os: Dream OS 调控

数据流转：TradeEvent → UnifiedCaseRegistry → TradeCase v0.3 → L4 案例库
"""
import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TradeEvent:
    """统一交易事件数据结构"""
    
    event_id: str
    system_source: str
    trade_id: str
    ts_entry: str
    symbol: str
    direction: str
    entry_price: float
    
    ts_exit: Optional[str] = None
    exit_price: Optional[float] = None
    position_size: float = 0.0
    
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    exit_reason: Optional[str] = None
    
    decision_context: Dict[str, Any] = field(default_factory=dict)
    market_snapshot: Dict[str, Any] = field(default_factory=dict)
    risk_events: List[Dict[str, Any]] = field(default_factory=list)
    
    leverage: float = 1.0
    margin_usdt: float = 0.0
    
    @classmethod
    def generate_event_id(cls) -> str:
        return f"evt_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}"
    
    @classmethod
    def _normalize_yijing_source(cls, src: str) -> str:
        """将易经推理子系统来源统一归一化为 yijing_inference

        历史/现状兼容:
        - bcrm / yijing_live / yijing_engine / liangyi / 易经子模块标识
          统一归入 yijing_inference（易经推理系统主类）。
        其他来源（martin_v15/agent_a 等）原样返回。
        """
        _YIJING_ALIASES = frozenset({
            "bcrm", "yijing_live", "yijing_engine", "yijing_inference",
            "liangyi", "scale", "bagua", "yijing", "yijing_force",
        })
        if not src:
            return "yijing_inference"
        normalized = str(src).strip().lower()
        if normalized in _YIJING_ALIASES or normalized.startswith("yijing") or normalized.startswith("bcrm"):
            return "yijing_inference"
        return normalized

    @classmethod
    def from_trade_record(cls, record) -> "TradeEvent":
        """从易经推理系统的 TradeRecord 创建 TradeEvent"""
        raw_source = record.strategy_source or "yijing_inference"
        return cls(
            event_id=cls.generate_event_id(),
            system_source=cls._normalize_yijing_source(raw_source),
            trade_id=record.trade_id,
            ts_entry=record.entry_time,
            ts_exit=record.exit_time,
            symbol=record.inst_id,
            direction=record.direction,
            entry_price=record.entry_price,
            exit_price=record.exit_price,
            position_size=0.0,
            pnl=record.pnl,
            pnl_pct=record.pnl_pct,
            exit_reason=record.exit_reason,
            decision_context={
                "hexagram": record.hexagram,
                "confidence": record.confidence,
                "liangyi_state": record.liangyi_state or {},
                "scale_params": record.scale_params or {},
                "contradiction_list": record.contradiction_list or [],
                "enhance_info": record.enhance_info or {},
            },
            market_snapshot=record.market_snapshot or {},
            risk_events=[],
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str, indent=2)