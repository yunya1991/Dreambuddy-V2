"""QMM 数据类型定义。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CleanedEvent:
    """清洗后的事件。"""
    event_id: str
    ts: str
    regime: str
    quadrant_x: float
    quadrant_y: float
    pnl_pct: Optional[float]
    is_profit: Optional[bool]
    severity: Optional[float]
    quality: float  # 0-1
    clean_flags: List[str] = field(default_factory=list)


@dataclass
class ScreenResult:
    """单屏趋势结果。"""
    timeframe: str  # "long" / "mid" / "short"
    direction: str  # "UP" / "DOWN" / "FLAT"
    confidence: float  # 0-1
    x_mean: float
    y_mean: float
    profit_rate: float
    case_count: int


@dataclass
class MDRResult:
    """阻力最小方向结果。"""
    direction: str  # "UP" / "DOWN" / "NEUTRAL"
    resistance_up: float  # 0-100
    resistance_down: float  # 0-100
    net: float
    confidence: float  # 0-1


@dataclass
class QMMOutput:
    """QMM 输出契约。"""
    version: str = "qmm-v1.0"
    snapshot_ts: str = ""

    # 版本三元组
    data_version: str = ""
    feature_def_version: str = ""
    qmm_version: str = "qmm-v1.0"

    # 核心信号
    trend_state: str = "UNKNOWN"
    trend_change_point: str = "UNKNOWN"
    mrd_vector: Dict[str, Any] = field(default_factory=dict)
    uncertainty: float = 1.0
    triple_screen: Dict[str, Any] = field(default_factory=dict)
    velocity: Dict[str, Any] = field(default_factory=dict)
    acceleration: Dict[str, Any] = field(default_factory=dict)

    # 元信息
    reason_codes: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
