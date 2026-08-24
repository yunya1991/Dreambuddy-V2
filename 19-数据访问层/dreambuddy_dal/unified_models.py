"""
dreambuddy_dal.unified_models — 唯一数据模型 SSoT（Single Source of Truth）

⚠️ 经验 698940 教训：TradeRecord 曾 5 处独立定义导致字段漂移。
✅ 修复：全系统任何模块如要使用 TradeRecord / PositionState / DailyStats / RiskState
   必须 from dreambuddy_dal.unified_models import X，禁止独立定义。
   5 处历史定义保留 DeprecationWarning 兼容导入到 2026-09-30。

字段严格对齐 SCHEMA_DESIGN.md：
- TradeRecord → tr_trades 表（35+ 列 + extra_payload JSON）
- PositionState → po_positions 表
- DailyStats → tr_daily_stats 表
- RiskState → rs_state 表（CHECK(id=1) + 乐观锁 version）
- RiskCaseRecord → rs_cases 表
- CloseInfo → trade_repo.close_position(...) 返回值（辅助结构，无独立表）
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# 枚举（与表的 CHECK 约束一一对应）
# ---------------------------------------------------------------------------

class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIAL = "PARTIAL"


class ExitReason(str, Enum):
    """TECHNICAL_DESIGN §2.2 close_position 7 种离场原因"""
    SL_HIT = "SL_HIT"
    TP_HIT = "TP_HIT"
    TS_HIT = "TS_HIT"
    TIMEOUT = "TIMEOUT"
    COST_DIVERGENCE = "COST_DIVERGENCE"
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TrialStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    TICKING = "TICKING"
    EVAL_PENDING = "EVAL_PENDING"
    EVAL_PASS = "EVAL_PASS"
    EVAL_FAIL = "EVAL_FAIL"
    CANCELLED = "CANCELLED"


class PositionStyle(str, Enum):
    SWING_TREND = "SWING_TREND"
    INTRADAY_SCALP = "INTRADAY_SCALP"


# ---------------------------------------------------------------------------
# 序列化/反序列化公共 mixin（Decimal / datetime 类型安全）
# ---------------------------------------------------------------------------

class _JsonSerdeMixin:
    """
    to_jsonable_dict() → 所有值 JSON 可序列化（Decimal→str，datetime→ISO8601 UTC）
    from_dict(d) → 重建，自动恢复 Decimal / datetime / Enum
    """

    def to_jsonable_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in asdict(self).items():
            if isinstance(v, Decimal):
                out[k] = str(v)
            elif isinstance(v, datetime):
                # 强制 UTC ISO，后缀 Z 对齐 Postgres ISO
                if v.tzinfo is None:
                    v = v.replace(tzinfo=timezone.utc)
                out[k] = v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            elif isinstance(v, Enum):
                out[k] = v.value
            elif isinstance(v, dict):
                # extra_payload 已是 JSON 可序列化
                out[k] = v
            else:
                out[k] = v
        return out

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "_JsonSerdeMixin":
        import dataclasses

        fields_info = {f.name: f.type for f in dataclasses.fields(cls)}
        kwargs: Dict[str, Any] = {}
        for f_name, f_type in fields_info.items():
            if f_name not in d or d[f_name] is None:
                continue
            raw = d[f_name]
            # 解析 Decimal
            f_type_str = str(f_type)
            if "Decimal" in f_type_str and isinstance(raw, str):
                try:
                    kwargs[f_name] = Decimal(raw)
                except InvalidOperation:
                    kwargs[f_name] = raw
            # 解析 datetime
            elif "datetime" in f_type_str and isinstance(raw, str):
                kwargs[f_name] = _parse_iso_datetime(raw)
            # 解析枚举：Optional[Xxx] → str 形式 type 包着 Union
            elif f_name in _ENUM_FIELD_MAP and isinstance(raw, str):
                enum_cls = _ENUM_FIELD_MAP[f_name]
                try:
                    kwargs[f_name] = enum_cls(raw)
                except ValueError:
                    kwargs[f_name] = raw
            else:
                kwargs[f_name] = raw
        return cls(**kwargs)


def _parse_iso_datetime(s: str) -> datetime:
    """宽松解析 ISO8601，支持 Z/带时区/不带时区→ 一律 UTC aware"""
    s2 = s.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        # 兼容 2026-08-24 10:00:00 无 T 形式
        dt = datetime.strptime(s.split(".")[0], "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# 字段名 → 枚举类映射（for from_dict 自动重建）
_ENUM_FIELD_MAP: Dict[str, type] = {}


# ---------------------------------------------------------------------------
# CloseInfo：离场结果（trade_repo.close_position 返回值）
# ---------------------------------------------------------------------------

@dataclass
class CloseInfo(_JsonSerdeMixin):
    exit_reason: ExitReason
    exit_price: Decimal
    close_ts: datetime
    realized_pnl: Decimal
    slippage_bps: int = 0
    execution_id: Optional[str] = None


_ENUM_FIELD_MAP["exit_reason"] = ExitReason


# ---------------------------------------------------------------------------
# TradeRecord：tr_trades（DAL 唯一出口，所有消费方必须用这个）
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord(_JsonSerdeMixin):
    """交易记录主模型。字段严格按 SCHEMA_DESIGN.md §3.1 tr_trades 字段字典。"""
    # ---- 主键 + 来源系统（必填）----
    trade_id: str
    sub_system: str  # YIJING / V15 / CLASSIC / MANUAL
    strategy_name: str

    # ---- 入场核心（必填）----
    symbol: str
    direction: TradeDirection
    entry_price: Decimal
    quantity: Decimal
    entry_ts: datetime
    stop_loss: Decimal
    take_profit: Decimal

    # ---- 风控评级（必填，对齐 13-通用风控 pre_trade_gate 产出）----
    risk_level_cn: str  # "低风险"/"中风险"/"高风险"/"极高风险"

    # ---- 有默认值的可选列（SCHEMA_DESIGN DEFAULT）----
    status: TradeStatus = TradeStatus.OPEN
    position_style: PositionStyle = PositionStyle.SWING_TREND
    entry_basis: str = "MARKET_ORDER"
    position_side: str = "BOTH"
    entry_slippage_bps: int = 0
    entry_execution_id: Optional[str] = None
    trailing_stop: Optional[Decimal] = None
    close_info: Optional[CloseInfo] = None
    notes: Optional[str] = None
    cbr_case_id: Optional[str] = None
    extra_payload: Dict[str, Any] = field(default_factory=dict)

    # ---- 轻仓试错专用（对齐 project memory XAG 轻仓 SL 下限保护）----
    is_trial: bool = False
    trial_status: TrialStatus = TrialStatus.NOT_APPLICABLE
    trial_open_ts: Optional[datetime] = None
    trial_eval_ts: Optional[datetime] = None
    trial_eval_done: bool = False
    trial_eval_result: Optional[str] = None

    # ---- DB 自动写入，代码层不填（None 表示未持久化）----
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


_ENUM_FIELD_MAP.update({
    "direction": TradeDirection,
    "status": TradeStatus,
    "position_style": PositionStyle,
    "trial_status": TrialStatus,
})

# CloseInfo 字段是嵌套结构，from_dict 需要单独处理
_orig_trade_from_dict = TradeRecord.from_dict


@classmethod
def _trade_from_dict(cls, d: Dict[str, Any]) -> TradeRecord:
    close_info_d = d.pop("close_info", None)
    obj: TradeRecord = _orig_trade_from_dict(d)
    if close_info_d and isinstance(close_info_d, dict):
        obj.close_info = CloseInfo.from_dict(close_info_d)
    return obj


TradeRecord.from_dict = _trade_from_dict  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# PositionState：po_positions
# ---------------------------------------------------------------------------

@dataclass
class PositionState(_JsonSerdeMixin):
    """当前净持仓状态（SCHEMA_DESIGN §4.1 po_positions 字段字典）"""
    symbol: str
    sub_system: str
    direction: TradeDirection
    avg_entry_price: Decimal
    open_quantity: Decimal
    unrealized_pnl: Decimal  # Decimal(18,8)

    # ---- 自动生成（不填时根据 symbol:dir:sub_sys 生成稳定 ID）----
    position_id: str = field(default="")

    # ---- 有默认值列 ----
    cost_basis: Optional[Decimal] = None
    leverage: int = 1
    margin_used: Optional[Decimal] = None
    mark_price: Optional[Decimal] = None
    liquidation_price: Optional[Decimal] = None
    last_price_refresh_ts: Optional[datetime] = None
    source_trade_ids: str = ""  # JSON array → 可直接存 TEXT
    is_trial: bool = False
    extra_payload: Dict[str, Any] = field(default_factory=dict)

    # ---- DB 自动写入 ----
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.position_id:
            self.position_id = f"{self.symbol}:{self.direction.value}:{self.sub_system}"
        if self.cost_basis is None:
            self.cost_basis = self.avg_entry_price


_ENUM_FIELD_MAP["direction"] = TradeDirection  # 同名 OK


# ---------------------------------------------------------------------------
# DailyStats：tr_daily_stats
# ---------------------------------------------------------------------------

@dataclass
class DailyStats(_JsonSerdeMixin):
    """策略每日统计快照（SCHEMA_DESIGN §3.2）"""
    stat_date: str  # YYYY-MM-DD（主键前缀）
    symbol: str
    sub_system: str
    strategy_name: str
    start_equity: Decimal
    end_equity: Decimal
    net_pnl: Decimal
    max_drawdown: Decimal
    win_count: int
    loss_count: int
    trading_volume: Decimal  # 当日双边成交额

    overrides_applied: bool = False
    manual_override_note: Optional[str] = None
    extra_payload: Dict[str, Any] = field(default_factory=dict)

    # ---- DB 自动写入 ----
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# RiskState：rs_state（CHECK(id=1) 单行表 + 乐观锁 version）
# ---------------------------------------------------------------------------

@dataclass
class RiskState(_JsonSerdeMixin):
    """
    全系统风险快照（单行）。SCHEMA_DESIGN §6.1：
    - id=1 唯一（DB CHECK 强制）
    - version 由 DB UPDATE 触发器自动 +1
    - updated_at 由 DB UPDATE 触发器自动刷当前时间
    """
    id: int  # 永远 1
    total_equity_usd: Decimal
    gross_exposure_usd: Decimal
    net_exposure_usd: Decimal
    gross_leverage: Decimal
    max_position_pct_usd: Decimal
    win_rate_7d: Decimal
    max_drawdown_active: Decimal
    equity_curve_avg: Decimal
    equity_curve_std: Decimal
    active_symbols_count: int
    overall_risk: RiskLevel

    # ---- 可选列 ----
    next_allowed_trade_ts: Optional[datetime] = None
    active_alert_ids: str = ""  # JSON array TEXT
    # ---- 易经推理系统专用 3 列（对齐 project_memory 五计庙算硬约束）----
    war_state: Optional[str] = None
    strategy_mask: Optional[int] = None
    style_exposure: Optional[str] = None  # JSON TEXT
    extra_payload: Dict[str, Any] = field(default_factory=dict)

    # ---- DB 触发器维护（Python 层只读不改）----
    version: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


_ENUM_FIELD_MAP["overall_risk"] = RiskLevel


# ---------------------------------------------------------------------------
# RiskCaseRecord：rs_cases
# ---------------------------------------------------------------------------

@dataclass
class RiskCaseRecord(_JsonSerdeMixin):
    """风控案例记录（SCHEMA_DESIGN §6.2 rs_cases）"""
    case_id: str
    detected_at: datetime
    risk_level: RiskLevel
    rule_id: str
    rule_name: str
    action_taken: str

    symbol: Optional[str] = None
    direction: Optional[TradeDirection] = None
    severity_score: Optional[int] = None  # 0-100
    trade_id: Optional[str] = None
    evidence_json: Optional[str] = None  # TEXT
    resolution_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None
    extra_payload: Dict[str, Any] = field(default_factory=dict)

    # ---- DB 自动写入 ----
    created_at: Optional[datetime] = None


_ENUM_FIELD_MAP["risk_level"] = RiskLevel
# direction 已注册在 TradeDirection


# ---------------------------------------------------------------------------
# 对外公开（统一导入出口）
# ---------------------------------------------------------------------------
__all__ = [
    # 枚举
    "TradeDirection", "TradeStatus", "ExitReason", "RiskLevel",
    "TrialStatus", "PositionStyle",
    # 数据模型
    "TradeRecord", "CloseInfo", "PositionState", "DailyStats",
    "RiskState", "RiskCaseRecord",
]
