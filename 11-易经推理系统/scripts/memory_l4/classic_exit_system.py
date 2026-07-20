#!/usr/bin/env python3
"""
经典指标离场系统 (Classic Exit System)
=======================================

统一封装的经典指标离场模块，作为单一真相源（Single Source of Truth)。

架构设计（与技术文档 11.y 完整对齐）：

四大优先级（由高到低，越靠前越硬）：
    P0 - L0 安全硬退出（永远一票否决）
         - 最大持仓时间 (max_hold_sec)
         - 最大未实现亏损 (max_loss_pct, 含杠杆口径)
         - 强平安全缓冲 (liquidation_buffer)
         - 周线反转 (weekly_reversal) - MACD趋势 + ADX + 确认周数
         - 风险闸门 (risk_gate) - armed + cooldown + confirm_n + N-of-M

    P1 - L1/L2 价值-风险评估（主体）
         - L1: hold_risk / hold_value / MRD Score / p_tail / p_move
         - L2: 动作映射 (close / reduce / hold) + reduce_frac
         - 滞回/确认机制 (deadband + armed + confirm_n)
         - Regime 分桶阈值偏移 (threshold_by_regime)
         - 风险预算 (Risk Budget) - 序列回撤超标时抬升阈值
         - Exit Gate 过滤 (低置信度动作过滤)

    P2 - Triple Barrier（三重屏障）
         - 止损屏障 (ATR 倍数，含 min_pct 底限)
         - 止盈屏障 (ATR 倍数，优先 reduce 而非 close)
         - 时间屏障 (time_barrier_sec，仅风险达标时触发)

    P3 - 执行层行为约束
         - TSTP 时间止盈（按时间衰减的 ATR 倍数，趋势/震荡两套）
         - 跟踪止损 (Trailing Stop) - arming + 回撤触发
         - 分批减仓 (Scale-out)
         - 冷却/滞回机制 (inflight cooldown / post-close freeze)
         - 成本缓冲 (fees + slippage + funding + safety_margin)

离场因子体系（技术文档 11.y.3）：
    - 时间纬度：周线/日线趋势形态（5 类：up_strong / up_reversal / down_strong / down_reversal / chop）
    - 动能/量能/势能：方向 / 变化方向 / 变化速度（mom/vol/pot 各三维）
    - 资金流向：宏观资金偏好 + 单币种相对强弱（flow_dir / macro_flow_dir）
    - 风险预算：序列回撤增量惩罚

杠杆口径统一：
    所有止盈/止损/时间止盈/移动止盈的触发判断统一使用 pnl_eff（含杠杆收益率）。
"""

import os
import sys
import math
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum


# ── 工具函数 ────────────────────────────────────────────────────────────────

def _clip(v: float, lo: float, hi: float) -> float:
    """数值裁剪"""
    return max(lo, min(hi, v))


def _sign(v: float, deadband: float = 0.0) -> int:
    """带死区的符号函数"""
    if v > deadband:
        return 1
    if v < -deadband:
        return -1
    return 0


# ── 类型定义 ────────────────────────────────────────────────────────────────

class ExitAction(str, Enum):
    """离场动作"""
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    RAISE_TP = "raise_tp"    # 提高止盈价（强反弹时让利润奔跑）


class ExitPriority(str, Enum):
    """优先级"""
    P0_L0_HARD = "p0_l0"
    P1_VALUE_RISK = "p1"
    P2_TRIPLE_BARRIER = "p2"
    P3_BEHAVIORAL = "p3"


class TrendShape(str, Enum):
    """趋势形态（5 类）"""
    UP_STRONG = "up_strong"
    UP_REVERSAL = "up_reversal"
    DOWN_STRONG = "down_strong"
    DOWN_REVERSAL = "down_reversal"
    CHOP = "chop"


class L1Mode(str, Enum):
    """L1 评估模式"""
    HEURISTIC = "heuristic"
    MRD = "mrd"
    ML = "ml"


@dataclass
class PositionState:
    """持仓状态（输入）"""
    coin: str = ""
    side: str = "long"
    entry_price: float = 0.0
    current_price: float = 0.0
    position_age_sec: float = 0.0
    unrealized_pnl_pct: float = 0.0
    leverage: float = 1.0
    atr_pct: float = 0.02
    mfe_pnl_pct: float = 0.0
    max_dd_pct: float = 0.0
    entry_ts: int = 0
    trailing_armed: bool = False
    trailing_stop_price: float = 0.0
    liq_price: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def pnl_eff(self) -> float:
        """含杠杆的有效收益率"""
        return self.unrealized_pnl_pct * self.leverage

    @property
    def is_long(self) -> bool:
        return self.side.lower() == "long"


@dataclass
class ExitFeatureSet:
    """离场特征集（中间计算结果）"""
    hold_risk: float = 0.5
    hold_value: float = 0.5
    mrd_score: float = 0.0
    p_mrd: float = 0.5
    p_tail: Optional[float] = None
    p_move: Optional[float] = None
    model_conf: float = 0.0

    dd: float = 0.0
    mfe: float = 0.0

    rsi: float = 50.0
    macd_hist: float = 0.0
    adx: float = 25.0
    atr_pct: float = 0.02
    ema_short_dist: float = 0.0
    chop: float = 50.0

    trend_shape: TrendShape = TrendShape.CHOP
    trend_w_dir: int = 0
    trend_d_dir: int = 0
    trend_w_slope: float = 0.0
    trend_d_slope: float = 0.0
    trend_rate_change_dw: float = 0.0

    mom_dir: int = 0
    mom_chg_dir: int = 0
    mom_chg_speed: float = 0.0
    mom_rsi_delta: float = 0.0
    mom_macdh_delta: float = 0.0

    vol_dir: int = 0
    vol_chg_dir: int = 0
    vol_chg_speed: float = 0.0
    vol_z: float = 0.0
    vol_ratio_delta: float = 0.0

    pot_dir: int = 0
    pot_chg_dir: int = 0
    pot_chg_speed: float = 0.0
    pot_adx_delta: float = 0.0
    pot_dist_to_ema50: float = 0.0

    flow_dir: int = 0
    flow_chg_dir: int = 0
    macro_flow_dir: int = 0

    risk_budget_penalty: float = 0.0
    regime_shift: float = 0.0

    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExitDecision:
    """离场决策（输出）"""
    action: ExitAction = ExitAction.HOLD
    priority: ExitPriority = ExitPriority.P3_BEHAVIORAL
    reason: str = ""
    confidence: float = 0.0
    reduce_frac: float = 0.0
    suggested_price: float = 0.0

    l0_triggered: bool = False
    l0_reason: str = ""

    l1_hold_risk: float = 0.5
    l1_hold_value: float = 0.5

    tb_sl_hit: bool = False
    tb_tp_hit: bool = False
    tb_time_hit: bool = False

    trailing_triggered: bool = False
    trailing_stop_price: float = 0.0
    new_trailing_stop: float = 0.0

    tstp_triggered: bool = False
    tstp_stage: int = 0

    # RAISE_TP 相关
    new_tp_price: float = 0.0
    new_tp_pct: float = 0.0

    gate_passed: bool = True
    gate_reason: str = ""

    features: Optional[ExitFeatureSet] = None
    source: str = "local"


@dataclass
class RiskGateState:
    """风险闸门状态（per-position）"""
    armed: bool = False
    trigger_ts: float = 0.0
    confirm_count: int = 0
    confirm_hist: List[int] = field(default_factory=list)
    last_hold_risk: float = 0.0


@dataclass
class L2ArmedState:
    """L2 滞回状态（per-position）"""
    reduce_armed: bool = False
    close_armed: bool = False
    reduce_confirm_count: int = 0
    close_confirm_count: int = 0


@dataclass
class ExitRuntimeState:
    """运行时状态（用于跨调用保持状态）"""
    risk_gate: Dict[str, RiskGateState] = field(default_factory=dict)
    l2_armed: Dict[str, L2ArmedState] = field(default_factory=dict)
    cooldown: Dict[str, Dict[str, float]] = field(default_factory=dict)
    snapshot_history: Dict[str, List[Dict]] = field(default_factory=dict)


# ── 配置默认值 ──────────────────────────────────────────────────────────────

@dataclass
class ExitConfig:
    """离场系统配置（均可通过环境变量覆盖）"""

    # ── 通用 ────────────────────────────────────────────────────────
    apply_leverage_to_thresholds: bool = True
    l1_mode: L1Mode = L1Mode.HEURISTIC

    # ── L0 硬退出 ────────────────────────────────────────────────────────
    l0_max_hold_sec: int = 86400
    l0_max_loss_pct: float = -0.05
    l0_liq_buffer_enabled: bool = True
    l0_liq_buffer_pct: float = 0.005
    l0_weekly_reversal_enabled: bool = True
    l0_weekly_reversal_confirm_weeks: int = 2
    l0_weekly_reversal_adx_min: float = 20.0
    l0_risk_gate_enabled: bool = True
    l0_risk_gate_cooldown_min: float = 30.0
    l0_risk_gate_long_thr: float = 0.50
    l0_risk_gate_short_thr: float = 0.40
    l0_risk_gate_min_hold_sec: float = 0.0
    l0_risk_gate_confirm_n: int = 2
    l0_risk_gate_confirm_window_m: int = 0
    l0_risk_gate_reduce_frac: float = 0.5
    l0_risk_gate_deadband: float = 0.05
    l0_risk_gate_close_enabled: bool = False
    l0_risk_gate_close_delay_min: float = 60.0
    l0_risk_gate_close_risk_boost: float = 0.10

    # ── L1/L2 价值风险 ──────────────────────────────────────────────────
    l1_enabled: bool = True
    l2_close_threshold: float = 0.75
    l2_reduce_threshold: float = 0.55
    l2_reduce_min_profit_pct: float = 0.01
    l2_reduce_base_frac: float = 0.30
    l2_reduce_max_frac: float = 0.70
    l2_reduce_risk_span: float = 0.20
    l2_deadband: float = 0.03
    l2_confirm_n: int = 1
    l2_low_value_threshold: float = 0.30

    # ── 风险预算 ────────────────────────────────────────────────────
    risk_budget_enabled: bool = True
    risk_budget_len: int = 12
    risk_budget_dd: float = 0.35
    risk_budget_risk_up: float = 0.15

    dd_mfe_enable_cost_mult: float = 1.5
    dd_mfe_enable_atr_mult: float = 0.5

    # ── MRD 模式 ───────────────────────────────────────────────────
    mrd_p_low: float = 0.40
    mrd_p_high: float = 0.60
    mrd_risk_up: float = 0.10
    mrd_risk_down: float = 0.06
    mrd_min_model_conf: float = 0.25

    # ── Exit Gate ──────────────────────────────────────────────────
    gate_enabled: bool = False
    gate_min_confidence: float = 0.30

    # ── Triple Barrier ─────────────────────────────────────────────────
    tb_enabled: bool = True
    tb_sl_atr_mult: float = 1.5
    tb_tp_atr_mult: float = 3.0
    tb_sl_min_pct: float = 0.02
    tb_tp_min_pct: float = 0.04
    tb_time_barrier_sec: int = 28800
    tb_time_reduce_frac: float = 0.30
    tb_tp_reduce_frac: float = 0.50

    # ── TSTP 时间止盈 ──────────────────────────────────────────────────
    tstp_enabled: bool = True
    tstp_trend_plan: Dict[int, Tuple[float, float, str]] = field(default_factory=lambda: {
        300:  (6.0, 0.25, "reduce"),
        1800: (5.0, 0.33, "reduce"),
        3600: (4.0, 0.40, "reduce"),
        14400: (3.0, 0.50, "reduce"),
        28800: (2.5, 0.50, "close_if_weak"),
    })
    tstp_chop_plan: Dict[int, Tuple[float, float, str]] = field(default_factory=lambda: {
        300:  (4.0, 0.40, "reduce"),
        1800: (3.0, 0.50, "reduce"),
        3600: (2.5, 0.60, "reduce"),
        14400: (2.0, 0.70, "reduce"),
        28800: (1.5, 0.70, "reduce"),
    })
    tstp_close_if_weak_value_thr: float = 0.40

    # ── RAISE_TP（提高止盈价）──────────────────────────────────────────
    tstp_raise_tp_enabled: bool = True
    tstp_raise_tp_value_thr: float = 0.65    # TSTP 未达衰减tp时，hold_value > 此值触发 RAISE_TP
    tstp_raise_tp_atr_mult: float = 4.0      # 新止盈 = ATR × 此倍数（高于默认 3.0）
    l2_raise_tp_enabled: bool = True
    l2_raise_tp_value_thr: float = 0.65     # L1/L2 hold_value > 此值且 hold_risk 低时触发 RAISE_TP
    l2_raise_tp_risk_thr: float = 0.30       # L1/L2 hold_risk < 此值才触发 RAISE_TP
    l2_raise_tp_atr_mult: float = 4.0       # 新止盈 ATR 倍数

    # ── 跟踪止损 ────────────────────────────────────────────────────────
    trailing_enabled: bool = True
    trailing_arm_profit_pct: float = 0.06
    trailing_retrace_pct: float = 0.03

    # ── 移动止盈 (Trailing Take Profit, P3.5) ──────────────────────────
    # 与 Trailing Stop 互补：激活更早(1.5%)，回撤更敏感(40%)
    # 锁定利润而非防亏损，填补 1-6% 盈利保护空白
    trailing_tp_enabled: bool = True
    trailing_tp_arm_pct: float = 0.015      # 盈利 ≥ 1.5% 激活
    trailing_tp_retrace_ratio: float = 0.40  # 从 MFE 回撤 ≥ 40% 触发
    trailing_tp_min_lock_pct: float = 0.003  # 至少锁定 0.3% 利润

    # ── 冷却/滞回 ──────────────────────────────────────────────────────
    inflight_cooldown_sec: int = 90
    cooldown_after_close_sec: int = 3600
    cooldown_after_reduce_sec: int = 1800
    post_close_freeze_hours: float = 2.0

    # ── 成本缓冲 ────────────────────────────────────────────────────────
    fee_roundtrip_pct: float = 0.001
    slippage_pct: float = 0.001
    safety_margin_pct: float = 0.0005
    funding_buffer_enabled: bool = True
    funding_buffer_period_hours: float = 8.0
    funding_buffer_safety_mult: float = 1.5
    funding_default_rate_abs: float = 0.0001

    @classmethod
    def from_env(cls) -> "ExitConfig":
        """从环境变量加载配置"""
        cfg = cls()
        env_map = {
            "EXIT_L0_MAX_HOLD_SEC": ("l0_max_hold_sec", int),
            "EXIT_L0_MAX_LOSS_PCT": ("l0_max_loss_pct", float),
            "EXIT_L0_WEEKLY_REVERSAL": ("l0_weekly_reversal_enabled", bool),
            "EXIT_L0_RISK_GATE_ENABLED": ("l0_risk_gate_enabled", bool),
            "EXIT_L0_RISK_GATE_COOLDOWN_MIN": ("l0_risk_gate_cooldown_min", float),
            "EXIT_L1_ENABLED": ("l1_enabled", bool),
            "EXIT_L2_CLOSE_THR": ("l2_close_threshold", float),
            "EXIT_L2_REDUCE_THR": ("l2_reduce_threshold", float),
            "EXIT_TB_ENABLED": ("tb_enabled", bool),
            "EXIT_TB_SL_ATR_MULT": ("tb_sl_atr_mult", float),
            "EXIT_TB_TP_ATR_MULT": ("tb_tp_atr_mult", float),
            "EXIT_TSTP_ENABLED": ("tstp_enabled", bool),
            "EXIT_TRAILING_ENABLED": ("trailing_enabled", bool),
            "EXIT_TRAILING_ARM_PCT": ("trailing_arm_profit_pct", float),
            "EXIT_TRAILING_RETRACE_PCT": ("trailing_retrace_pct", float),
            "EXIT_GATE_ENABLED": ("gate_enabled", bool),
            "EXIT_INFLIGHT_COOLDOWN_SEC": ("inflight_cooldown_sec", int),
            "EXIT_APPLY_LEVERAGE": ("apply_leverage_to_thresholds", bool),
            "EXIT_RISK_BUDGET_ENABLED": ("risk_budget_enabled", bool),
        }
        for env_key, (attr, typ) in env_map.items():
            val = os.environ.get(env_key)
            if val is not None:
                try:
                    if typ == bool:
                        setattr(cfg, attr, val.lower() in ("1", "true", "yes"))
                    else:
                        setattr(cfg, attr, typ(val))
                except (ValueError, TypeError):
                    pass
        mode = os.environ.get("EXIT_L1_MODE", "").strip().lower()
        if mode in ("heuristic", "mrd", "ml"):
            cfg.l1_mode = L1Mode(mode)
        return cfg


# ── 核心系统类 ──────────────────────────────────────────────────────────────

class ClassicExitSystem:
    """
    经典指标离场系统（单一真相源）

    完整实现技术文档 11.y 定义的四大优先级离场架构：
    P0 → P2 → P3 → P1，逐级评估，高优先级先触发。

    使用示例：
        system = ClassicExitSystem()
        pos = PositionState(coin="SOL", side="long", ...)
        decision = system.evaluate_full(pos, candles, regime="trend")
    """

    def __init__(
        self,
        config: Optional[ExitConfig] = None,
        api_base: str = "http://127.0.0.1:8092",
        api_timeout: float = 5.0,
    ):
        self.config = config or ExitConfig.from_env()
        self.api_base = api_base.rstrip("/")
        self.api_timeout = api_timeout
        self._session = None
        self.state = ExitRuntimeState()

    @property
    def session(self):
        """懒加载 HTTP Session"""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                self._session = None
        return self._session

    # ── 主入口：完整评估 ────────────────────────────────────────────────

    def evaluate_full(
        self,
        pos: PositionState,
        candles_1h: Optional[List[Dict]] = None,
        regime: str = "trend",
        now_ts: Optional[float] = None,
    ) -> ExitDecision:
        """
        完整离场评估（四大优先级逐级检查）

        执行顺序（技术文档 11.y.0 统一决策流程）：
        1. P0 - L0 硬退出检查（最高优先级，一票否决）
        2. P2 - Triple Barrier 检查（边界补充）
        3. P3 - 跟踪止损 / TSTP 检查（行为约束）
        4. P1 - L1/L2 价值-风险评估（主体决策）
        5. Exit Gate 过滤 + 执行约束
        """
        now = now_ts if now_ts is not None else time.time()

        decision = ExitDecision(
            action=ExitAction.HOLD,
            confidence=0.0,
            suggested_price=pos.current_price,
        )

        features = self._compute_features(pos, candles_1h, regime, now)
        decision.features = features

        # P0: L0 硬退出
        l0_decision = self._check_l0(pos, features, now)
        if l0_decision.action != ExitAction.HOLD:
            merged = self._merge_decision(decision, l0_decision, ExitPriority.P0_L0_HARD)
            return self._apply_behavioral_constraints(merged, pos, now)

        # P2: Triple Barrier
        tb_decision = self._check_triple_barrier(pos, features)
        if tb_decision.action != ExitAction.HOLD:
            merged = self._merge_decision(decision, tb_decision, ExitPriority.P2_TRIPLE_BARRIER)
            return self._apply_behavioral_constraints(merged, pos, now)

        # P3: 跟踪止损
        trailing_decision = self._check_trailing_stop(pos, features)
        if trailing_decision.action != ExitAction.HOLD:
            merged = self._merge_decision(decision, trailing_decision, ExitPriority.P3_BEHAVIORAL)
            return self._apply_behavioral_constraints(merged, pos, now)

        # P3.5: 移动止盈 (Trailing Take Profit)
        ttp_decision = self._check_trailing_tp(pos, features)
        if ttp_decision.action != ExitAction.HOLD:
            merged = self._merge_decision(decision, ttp_decision, ExitPriority.P3_BEHAVIORAL)
            return self._apply_behavioral_constraints(merged, pos, now)

        # P3: TSTP 时间止盈
        tstp_decision = self._check_tstp(pos, features, regime)
        if tstp_decision.action != ExitAction.HOLD:
            merged = self._merge_decision(decision, tstp_decision, ExitPriority.P3_BEHAVIORAL)
            return self._apply_behavioral_constraints(merged, pos, now)

        # P1: L1/L2 价值-风险评估
        if self.config.l1_enabled:
            l1_decision = self._evaluate_value_risk(pos, features, now)
            if l1_decision.action != ExitAction.HOLD:
                merged = self._merge_decision(decision, l1_decision, ExitPriority.P1_VALUE_RISK)
                return self._apply_behavioral_constraints(merged, pos, now)

        return self._apply_behavioral_constraints(decision, pos, now)

    # ── API 模式评估 ───────────────────────────────────────────────────

    def evaluate_api(
        self,
        coin: str,
        current_price: float,
        position_action: str,
        candles_1h: Optional[List[Dict]] = None,
    ) -> ExitDecision:
        """通过 API 评估离场（调用 ml_trade_service）"""
        if self.session is None:
            return self._fallback_local(coin, current_price, position_action, candles_1h)

        try:
            pair = f"{coin}-PERP"
            url = f"{self.api_base}/exit/features/latest"
            params = {"pairs": pair, "include_macro": "true"}

            resp = self.session.get(url, params=params, timeout=self.api_timeout)
            if resp.status_code != 200:
                return self._fallback_local(coin, current_price, position_action, candles_1h)

            data = resp.json()
            if not data.get("ok") or not data.get("items"):
                return self._fallback_local(coin, current_price, position_action, candles_1h)

            feats = data["items"][0]
            return self._decision_from_api_features(feats, coin, current_price, position_action)

        except Exception:
            return self._fallback_local(coin, current_price, position_action, candles_1h)

    def _decision_from_api_features(
        self,
        feats: Dict,
        coin: str,
        current_price: float,
        position_action: str,
    ) -> ExitDecision:
        """从 API 特征生成决策"""
        side = "long" if position_action.upper() in ("LONG", "BUY") else "short"
        features = ExitFeatureSet(
            hold_risk=float(feats.get("hold_risk_score", feats.get("hold_risk", 0.5))),
            hold_value=float(feats.get("hold_value_score", feats.get("hold_value", 0.5))),
            mrd_score=float(feats.get("mrd_score", feats.get("macro_mrd_score", 0.0))),
            p_mrd=float(feats.get("p_mrd", feats.get("macro_p_mrd", 0.5))),
            dd=float(feats.get("dd", feats.get("pos_max_drawdown_since_entry", 0.0))),
            rsi=float(feats.get("rsi") or feats.get("rsi_d") or 50.0),
            adx=float(feats.get("adx") or feats.get("adx_h") or 25.0),
            ema_short_dist=float(feats.get("ema_short_dist", 0.0)),
            raw=feats,
        )

        pos = PositionState(
            coin=coin,
            side=side,
            current_price=current_price,
        )

        decision = ExitDecision(
            action=ExitAction.HOLD,
            confidence=0.0,
            suggested_price=current_price,
            features=features,
            source="api",
            l1_hold_risk=features.hold_risk,
            l1_hold_value=features.hold_value,
        )

        if features.hold_risk >= self.config.l2_close_threshold:
            decision.action = ExitAction.CLOSE
            decision.confidence = min(1.0, features.hold_risk)
            decision.reason = f"API_HIGH_RISK({features.hold_risk:.2f})"
        elif (features.hold_risk >= self.config.l2_reduce_threshold
              and pos.unrealized_pnl_pct >= self.config.l2_reduce_min_profit_pct):
            decision.action = ExitAction.REDUCE
            risk_span = self.config.l2_reduce_risk_span
            excess = features.hold_risk - self.config.l2_reduce_threshold
            frac = self.config.l2_reduce_base_frac + (excess / risk_span) * (
                self.config.l2_reduce_max_frac - self.config.l2_reduce_base_frac
            )
            decision.reduce_frac = min(self.config.l2_reduce_max_frac, max(0.0, frac))
            decision.confidence = features.hold_risk
            decision.reason = f"API_REDUCE_RISK({features.hold_risk:.2f})"

        if features.hold_value <= 0.25 and decision.action == ExitAction.HOLD:
            decision.action = ExitAction.REDUCE
            decision.reduce_frac = 0.4
            decision.confidence = 1.0 - features.hold_value
            decision.reason = f"API_LOW_VALUE({features.hold_value:.2f})"

        return decision

    def _fallback_local(
        self,
        coin: str,
        current_price: float,
        position_action: str,
        candles_1h: Optional[List[Dict]],
    ) -> ExitDecision:
        """API 不可用时回退到本地评估"""
        pos = PositionState(
            coin=coin,
            side="long" if position_action.upper() in ("LONG", "BUY") else "short",
            current_price=current_price,
        )
        decision = self.evaluate_full(pos, candles_1h or [])
        decision.source = "local"
        return decision

    # ══════════════════════════════════════════════════════════════════
    # P0: L0 硬退出
    # ══════════════════════════════════════════════════════════════════

    def _check_l0(self, pos: PositionState, features: ExitFeatureSet, now: float) -> ExitDecision:
        """P0: L0 安全硬退出（一票否决）"""
        decision = ExitDecision(
            action=ExitAction.HOLD,
            suggested_price=pos.current_price,
            features=features,
        )

        # 1. 最大持仓时间
        if self.config.l0_max_hold_sec > 0 and pos.position_age_sec >= self.config.l0_max_hold_sec:
            decision.action = ExitAction.CLOSE
            decision.l0_triggered = True
            decision.l0_reason = "max_hold_time"
            decision.reason = f"L0_MAX_HOLD({pos.position_age_sec/3600:.1f}h)"
            decision.confidence = 0.95
            return decision

        # 2. 最大未实现亏损（含杠杆口径）
        pnl_for_check = pos.pnl_eff if self.config.apply_leverage_to_thresholds else pos.unrealized_pnl_pct
        if self.config.l0_max_loss_pct < 0 and pnl_for_check <= self.config.l0_max_loss_pct:
            decision.action = ExitAction.CLOSE
            decision.l0_triggered = True
            decision.l0_reason = "stop_loss"
            decision.reason = f"L0_STOP_LOSS({pnl_for_check*100:+.1f}%)"
            decision.confidence = 0.99
            return decision

        # 3. 强平安全缓冲
        if self.config.l0_liq_buffer_enabled and pos.liq_price > 0:
            liq_buffer = self._calc_liquidation_buffer(pos)
            if liq_buffer <= self.config.l0_liq_buffer_pct:
                decision.action = ExitAction.CLOSE
                decision.l0_triggered = True
                decision.l0_reason = "liquidation_buffer"
                decision.reason = f"L0_LIQ_BUFFER({liq_buffer*100:.2f}%)"
                decision.confidence = 0.99
                return decision

        # 4. 周线反转
        if self.config.l0_weekly_reversal_enabled:
            weekly_reversal = self._check_weekly_reversal(pos, features)
            if weekly_reversal:
                decision.action = ExitAction.CLOSE
                decision.l0_triggered = True
                decision.l0_reason = "weekly_reversal"
                decision.reason = "L0_WEEKLY_REVERSAL"
                decision.confidence = 0.90
                return decision

        # 5. 风险闸门（armed + cooldown + confirm 状态机）
        if self.config.l0_risk_gate_enabled:
            rg_decision = self._check_risk_gate(pos, features, now)
            if rg_decision.action != ExitAction.HOLD:
                return self._merge_decision(decision, rg_decision, ExitPriority.P0_L0_HARD)

        return decision

    def _calc_liquidation_buffer(self, pos: PositionState) -> float:
        """计算距强平价的安全缓冲（百分比）"""
        if pos.liq_price <= 0 or pos.current_price <= 0:
            return 1.0
        if pos.is_long:
            if pos.current_price <= pos.liq_price:
                return 0.0
            return (pos.current_price - pos.liq_price) / pos.current_price
        else:
            if pos.current_price >= pos.liq_price:
                return 0.0
            return (pos.liq_price - pos.current_price) / pos.current_price

    def _check_weekly_reversal(self, pos: PositionState, features: ExitFeatureSet) -> bool:
        """检查周线反转（基于趋势形态 + ADX + 回撤）"""
        if features.adx < self.config.l0_weekly_reversal_adx_min:
            return False

        dd_thr = 0.15

        if pos.is_long:
            if features.trend_shape in (TrendShape.UP_REVERSAL, TrendShape.DOWN_STRONG):
                return features.dd > dd_thr
        else:
            if features.trend_shape in (TrendShape.DOWN_REVERSAL, TrendShape.UP_STRONG):
                return features.dd > dd_thr

        return False

    def _check_risk_gate(self, pos: PositionState, features: ExitFeatureSet, now: float) -> ExitDecision:
        """检查风险闸门（完整状态机：armed + cooldown + confirm_n + N-of-M + 两段式）"""
        decision = ExitDecision(
            action=ExitAction.HOLD,
            suggested_price=pos.current_price,
            features=features,
        )

        key = pos.coin or "default"
        rg = self.state.risk_gate.get(key, RiskGateState())
        rg.last_hold_risk = features.hold_risk

        thr = self.config.l0_risk_gate_long_thr if pos.is_long else self.config.l0_risk_gate_short_thr
        exit_thr = max(0.0, thr - self.config.l0_risk_gate_deadband)

        close_thr = thr + self.config.l0_risk_gate_close_risk_boost if self.config.l0_risk_gate_close_enabled else 1.0

        triggered = features.hold_risk >= thr
        close_triggered = features.hold_risk >= close_thr
        confirm_n = max(1, int(self.config.l0_risk_gate_confirm_n))
        confirm_m = max(0, int(self.config.l0_risk_gate_confirm_window_m))
        if confirm_m > 0 and confirm_m < confirm_n:
            confirm_m = confirm_n

        if confirm_m > 0:
            rg.confirm_hist.append(1 if triggered else 0)
            if len(rg.confirm_hist) > confirm_m:
                rg.confirm_hist = rg.confirm_hist[-confirm_m:]
            c = sum(1 for x in rg.confirm_hist if x != 0)
        else:
            if triggered:
                rg.confirm_count += 1
            else:
                rg.confirm_count = 0
            c = rg.confirm_count

        min_hold_ms = self.config.l0_risk_gate_min_hold_sec * 1000.0
        age_ms = pos.position_age_sec * 1000.0
        min_hold_ok = min_hold_ms <= 0 or age_ms >= min_hold_ms

        if triggered and c >= confirm_n and min_hold_ok:
            if not rg.armed:
                rg.armed = True
                rg.trigger_ts = now
        else:
            if features.hold_risk <= exit_thr:
                rg.armed = False
                rg.trigger_ts = 0.0
                if confirm_m == 0:
                    rg.confirm_count = 0

        self.state.risk_gate[key] = rg

        if rg.armed and rg.trigger_ts > 0:
            cooldown_sec = self.config.l0_risk_gate_cooldown_min * 60.0
            elapsed = now - rg.trigger_ts
            if elapsed >= cooldown_sec:
                if self.config.l0_risk_gate_close_enabled and close_triggered:
                    close_delay_sec = self.config.l0_risk_gate_close_delay_min * 60.0
                    if elapsed >= cooldown_sec + close_delay_sec:
                        decision.action = ExitAction.CLOSE
                        decision.l0_triggered = True
                        decision.l0_reason = "risk_gate_close"
                        decision.reason = f"L0_RISK_GATE_CLOSE(hr={features.hold_risk:.2f}, armed={elapsed/60:.0f}m)"
                        decision.confidence = min(1.0, features.hold_risk + 0.1)
                        return decision

                decision.action = ExitAction.REDUCE
                decision.l0_triggered = True
                decision.l0_reason = "risk_gate"
                decision.reduce_frac = self.config.l0_risk_gate_reduce_frac
                decision.reason = f"L0_RISK_GATE(hr={features.hold_risk:.2f}, armed={elapsed/60:.0f}m)"
                decision.confidence = features.hold_risk
                return decision

        return decision

    # ══════════════════════════════════════════════════════════════════
    # P2: Triple Barrier
    # ══════════════════════════════════════════════════════════════════

    def _check_triple_barrier(self, pos: PositionState, features: ExitFeatureSet) -> ExitDecision:
        """P2: Triple Barrier（三重屏障）"""
        decision = ExitDecision(
            action=ExitAction.HOLD,
            suggested_price=pos.current_price,
            features=features,
        )

        if not self.config.tb_enabled:
            return decision

        atr_pct = features.atr_pct if features.atr_pct > 0 else (pos.atr_pct if pos.atr_pct > 0 else 0.02)
        pnl_for_check = pos.pnl_eff if self.config.apply_leverage_to_thresholds else pos.unrealized_pnl_pct

        # 止损屏障
        sl_pct = max(self.config.tb_sl_min_pct, atr_pct * self.config.tb_sl_atr_mult)
        if self.config.apply_leverage_to_thresholds and pos.leverage > 0:
            sl_pct_check = sl_pct * pos.leverage
        else:
            sl_pct_check = sl_pct

        if pos.is_long:
            if pnl_for_check <= -sl_pct_check:
                decision.action = ExitAction.CLOSE
                decision.tb_sl_hit = True
                decision.reason = f"TB_STOP_LOSS({sl_pct*100:.1f}%)"
                decision.confidence = 0.95
                return decision
        else:
            if pnl_for_check <= -sl_pct_check:
                decision.action = ExitAction.CLOSE
                decision.tb_sl_hit = True
                decision.reason = f"TB_STOP_LOSS({sl_pct*100:.1f}%)"
                decision.confidence = 0.95
                return decision

        # 止盈屏障（优先 reduce）
        tp_pct = max(self.config.tb_tp_min_pct, atr_pct * self.config.tb_tp_atr_mult)
        if self.config.apply_leverage_to_thresholds and pos.leverage > 0:
            tp_pct_check = tp_pct * pos.leverage
        else:
            tp_pct_check = tp_pct

        if pos.is_long:
            if pnl_for_check >= tp_pct_check:
                decision.action = ExitAction.REDUCE
                decision.tb_tp_hit = True
                decision.reduce_frac = self.config.tb_tp_reduce_frac
                decision.reason = f"TB_TAKE_PROFIT({tp_pct*100:.1f}%)"
                decision.confidence = 0.85
                return decision
        else:
            if pnl_for_check >= tp_pct_check:
                decision.action = ExitAction.REDUCE
                decision.tb_tp_hit = True
                decision.reduce_frac = self.config.tb_tp_reduce_frac
                decision.reason = f"TB_TAKE_PROFIT({tp_pct*100:.1f}%)"
                decision.confidence = 0.85
                return decision

        # 时间屏障（仅当风险达标时触发）
        if (self.config.tb_time_barrier_sec > 0
                and pos.position_age_sec >= self.config.tb_time_barrier_sec
                and features.hold_risk >= self.config.l2_reduce_threshold):
            decision.action = ExitAction.REDUCE
            decision.tb_time_hit = True
            decision.reduce_frac = self.config.tb_time_reduce_frac
            decision.reason = f"TB_TIME_BARRIER({pos.position_age_sec/3600:.1f}h)"
            decision.confidence = 0.60
            return decision

        return decision

    # ══════════════════════════════════════════════════════════════════
    # P3: 跟踪止损
    # ══════════════════════════════════════════════════════════════════

    def _check_trailing_stop(self, pos: PositionState, features: ExitFeatureSet) -> ExitDecision:
        """P3: 跟踪止损（Trailing Stop）"""
        decision = ExitDecision(
            action=ExitAction.HOLD,
            suggested_price=pos.current_price,
            features=features,
            new_trailing_stop=pos.trailing_stop_price,
        )

        if not self.config.trailing_enabled:
            return decision

        arm_pct = self.config.trailing_arm_profit_pct
        retrace_pct = self.config.trailing_retrace_pct

        pnl_for_check = pos.pnl_eff if self.config.apply_leverage_to_thresholds else pos.unrealized_pnl_pct
        if self.config.apply_leverage_to_thresholds and pos.leverage > 0:
            arm_pct_eff = arm_pct * pos.leverage
            retrace_pct_eff = retrace_pct
        else:
            arm_pct_eff = arm_pct
            retrace_pct_eff = retrace_pct

        should_arm = pnl_for_check >= arm_pct_eff
        new_stop = 0.0

        if pos.is_long:
            if should_arm:
                calc_stop = pos.current_price * (1 - retrace_pct_eff)
                new_stop = max(pos.trailing_stop_price, calc_stop) if pos.trailing_armed else calc_stop

                if pos.trailing_armed and pos.current_price <= pos.trailing_stop_price:
                    decision.action = ExitAction.CLOSE
                    decision.trailing_triggered = True
                    decision.trailing_stop_price = pos.trailing_stop_price
                    decision.reason = f"TRAILING_STOP({retrace_pct*100:.1f}%)"
                    decision.confidence = 0.85
                    return decision
        else:
            if should_arm:
                calc_stop = pos.current_price * (1 + retrace_pct_eff)
                new_stop = min(pos.trailing_stop_price, calc_stop) if pos.trailing_armed else calc_stop

                if pos.trailing_armed and pos.current_price >= pos.trailing_stop_price:
                    decision.action = ExitAction.CLOSE
                    decision.trailing_triggered = True
                    decision.trailing_stop_price = pos.trailing_stop_price
                    decision.reason = f"TRAILING_STOP({retrace_pct*100:.1f}%)"
                    decision.confidence = 0.85
                    return decision

        decision.new_trailing_stop = new_stop
        return decision

    # ══════════════════════════════════════════════════════════════════
    # P3.5: 移动止盈 (Trailing Take Profit)
    # ══════════════════════════════════════════════════════════════════

    def _check_trailing_tp(self, pos: PositionState, features: ExitFeatureSet) -> ExitDecision:
        """
        P3.5: 移动止盈 — 基于 MFE 回撤锁定利润

        与 Trailing Stop (P3) 互补：
        - Trailing Stop：防亏损，激活晚(6%)，回撤3%
        - Trailing TP：锁定利润，激活早(1.5%)，回撤40%(相对MFE)

        触发条件：
        1. MFE ≥ arm_pct (1.5%) — 盈利够激活
        2. 回撤 = (MFE - 当前盈利) / MFE ≥ retrace_ratio (40%)
        3. 当前盈利 ≥ min_lock_pct (0.3%) — 确保离场仍有正收益
        """
        decision = ExitDecision(
            action=ExitAction.HOLD,
            suggested_price=pos.current_price,
            features=features,
        )

        if not self.config.trailing_tp_enabled:
            return decision

        # 含杠杆的有效盈利（与 Trailing Stop 口径一致）
        pnl_now = pos.pnl_eff if self.config.apply_leverage_to_thresholds else pos.unrealized_pnl_pct
        mfe = pos.mfe_pnl_pct
        if self.config.apply_leverage_to_thresholds and pos.leverage > 0:
            mfe_eff = mfe * pos.leverage
        else:
            mfe_eff = mfe

        arm_pct = self.config.trailing_tp_arm_pct
        retrace_ratio = self.config.trailing_tp_retrace_ratio
        min_lock = self.config.trailing_tp_min_lock_pct

        # 未达激活阈值
        if mfe_eff < arm_pct:
            return decision

        # 计算从 MFE 的回撤比例
        retrace = (mfe_eff - pnl_now) / max(mfe_eff, 1e-9)

        # 回撤不足 或 当前盈利低于最小锁定
        if retrace < retrace_ratio or pnl_now < min_lock:
            return decision

        # 触发移动止盈
        decision.action = ExitAction.CLOSE
        decision.reason = (
            f"TRAILING_TP(mfe={mfe_eff*100:.2f}%,retrace={retrace*100:.1f}%,"
            f"lock={pnl_now*100:.2f}%)"
        )
        decision.confidence = 0.75
        return decision

    # ══════════════════════════════════════════════════════════════════
    # P3: TSTP 时间止盈
    # ══════════════════════════════════════════════════════════════════

    def _check_tstp(
        self,
        pos: PositionState,
        features: ExitFeatureSet,
        regime: str,
    ) -> ExitDecision:
        """P3: TSTP 时间止盈（Time-Scaled Take Profit，含 close_if_weak）"""
        decision = ExitDecision(
            action=ExitAction.HOLD,
            suggested_price=pos.current_price,
            features=features,
        )

        if not self.config.tstp_enabled or pos.position_age_sec <= 0:
            return decision

        atr_pct = features.atr_pct if features.atr_pct > 0 else (pos.atr_pct if pos.atr_pct > 0 else 0.02)
        plan = self.config.tstp_trend_plan if regime.lower() in ("trend", "trending") else self.config.tstp_chop_plan
        age = pos.position_age_sec

        tp_mult = None
        reduce_frac = None
        action_type = "reduce"
        stage_idx = 0

        sorted_times = sorted(plan.keys())
        for i, t in enumerate(sorted_times):
            if age >= t:
                tp_mult, frac, act = plan[t]
                reduce_frac = frac
                action_type = act
                stage_idx = i + 1

        if tp_mult is None:
            return decision

        tp_pct = atr_pct * tp_mult
        if self.config.apply_leverage_to_thresholds and pos.leverage > 0:
            tp_pct_check = tp_pct * pos.leverage
        else:
            tp_pct_check = tp_pct

        cost_buffer = self._calc_cost_buffer(pos)
        cost_buffer_eff = cost_buffer * pos.leverage if self.config.apply_leverage_to_thresholds else cost_buffer
        pnl_for_check = pos.pnl_eff if self.config.apply_leverage_to_thresholds else pos.unrealized_pnl_pct

        if pnl_for_check < cost_buffer_eff:
            return decision

        regime_label = "TREND" if regime.lower() in ("trend", "trending") else "CHOP"

        if pos.is_long:
            tp_hit = pnl_for_check >= tp_pct_check
        else:
            tp_hit = pnl_for_check >= tp_pct_check

        if not tp_hit:
            # 未达TSTP衰减止盈但价值高 → 提高止盈价（让利润奔跑）
            if (self.config.tstp_raise_tp_enabled
                and features.hold_value > self.config.tstp_raise_tp_value_thr):
                raise_mult = self.config.tstp_raise_tp_atr_mult
                new_tp_pct = atr_pct * raise_mult
                if pos.is_long:
                    new_tp_price = pos.current_price * (1.0 + new_tp_pct)
                else:
                    new_tp_price = pos.current_price * (1.0 - new_tp_pct)
                decision.action = ExitAction.RAISE_TP
                decision.tstp_triggered = True
                decision.tstp_stage = stage_idx
                decision.new_tp_price = new_tp_price
                decision.new_tp_pct = new_tp_pct
                decision.reason = f"TSTP_{regime_label}_RAISE_TP({tp_mult:.1f}xATR,v={features.hold_value:.2f},new_tp={raise_mult:.1f}xATR)"
                decision.confidence = 0.65
                return decision
            return decision

        if action_type == "close_if_weak":
            if features.hold_value <= self.config.tstp_close_if_weak_value_thr:
                decision.action = ExitAction.CLOSE
                decision.tstp_triggered = True
                decision.tstp_stage = stage_idx
                decision.reason = f"TSTP_{regime_label}_CLOSE_WEAK({tp_mult:.1f}xATR,v={features.hold_value:.2f})"
                decision.confidence = 0.80
                return decision
            else:
                decision.action = ExitAction.REDUCE
                decision.tstp_triggered = True
                decision.tstp_stage = stage_idx
                decision.reduce_frac = reduce_frac
                decision.reason = f"TSTP_{regime_label}_REDUCE({tp_mult:.1f}xATR)"
                decision.confidence = 0.70
                return decision
        else:
            decision.action = ExitAction.REDUCE
            decision.tstp_triggered = True
            decision.tstp_stage = stage_idx
            decision.reduce_frac = reduce_frac
            decision.reason = f"TSTP_{regime_label}_{int(age/60)}m({tp_mult:.1f}xATR)"
            decision.confidence = 0.75
            return decision

    # ══════════════════════════════════════════════════════════════════
    # P1: L1/L2 价值-风险评估
    # ══════════════════════════════════════════════════════════════════

    def _evaluate_value_risk(self, pos: PositionState, features: ExitFeatureSet, now: float) -> ExitDecision:
        """P1: L1/L2 价值-风险评估（含滞回/确认机制）"""
        decision = ExitDecision(
            action=ExitAction.HOLD,
            suggested_price=pos.current_price,
            features=features,
            l1_hold_risk=features.hold_risk,
            l1_hold_value=features.hold_value,
        )

        risk = features.hold_risk
        value = features.hold_value

        key = pos.coin or "default"
        l2 = self.state.l2_armed.get(key, L2ArmedState())

        close_thr = self.config.l2_close_threshold
        reduce_thr = self.config.l2_reduce_threshold
        deadband = self.config.l2_deadband
        close_exit_thr = max(0.0, close_thr - deadband)
        reduce_exit_thr = max(0.0, reduce_thr - deadband)
        confirm_n = max(1, int(self.config.l2_confirm_n))

        pnl_for_check = pos.pnl_eff if self.config.apply_leverage_to_thresholds else pos.unrealized_pnl_pct
        reduce_min_profit = self.config.l2_reduce_min_profit_pct
        if self.config.apply_leverage_to_thresholds and pos.leverage > 0:
            reduce_min_profit_eff = reduce_min_profit * pos.leverage
        else:
            reduce_min_profit_eff = reduce_min_profit

        if risk >= close_thr:
            l2.close_confirm_count += 1
            l2.close_armed = True
        elif risk <= close_exit_thr:
            l2.close_confirm_count = 0
            l2.close_armed = False

        if risk >= reduce_thr:
            l2.reduce_confirm_count += 1
            l2.reduce_armed = True
        elif risk <= reduce_exit_thr:
            l2.reduce_confirm_count = 0
            l2.reduce_armed = False

        self.state.l2_armed[key] = l2

        if l2.close_armed and l2.close_confirm_count >= confirm_n:
            decision.action = ExitAction.CLOSE
            decision.confidence = min(1.0, risk)
            decision.reason = f"L2_CLOSE(hold_risk={risk:.2f})"
            return decision

        if l2.reduce_armed and l2.reduce_confirm_count >= confirm_n:
            if pnl_for_check >= reduce_min_profit_eff:
                risk_span = self.config.l2_reduce_risk_span
                excess = risk - reduce_thr
                frac = self.config.l2_reduce_base_frac + (excess / risk_span) * (
                    self.config.l2_reduce_max_frac - self.config.l2_reduce_base_frac
                )
                decision.action = ExitAction.REDUCE
                decision.reduce_frac = min(self.config.l2_reduce_max_frac, max(0.0, frac))
                decision.confidence = risk
                decision.reason = f"L2_REDUCE(hold_risk={risk:.2f})"
                return decision

        if value <= self.config.l2_low_value_threshold and risk >= 0.50:
            if pnl_for_check >= -0.01 * (pos.leverage if self.config.apply_leverage_to_thresholds else 1.0):
                decision.action = ExitAction.REDUCE
                decision.reduce_frac = 0.4
                decision.confidence = 0.5 + (0.5 - value)
                decision.reason = f"L2_LOW_VALUE({value:.2f})"
                return decision

        # RAISE_TP: 价值高且风险低 → 提高止盈价（让利润奔跑）
        if (self.config.l2_raise_tp_enabled
            and value > self.config.l2_raise_tp_value_thr
            and risk < self.config.l2_raise_tp_risk_thr):
            atr_pct = features.atr_pct if features.atr_pct > 0 else (pos.atr_pct if pos.atr_pct > 0 else 0.02)
            raise_mult = self.config.l2_raise_tp_atr_mult
            new_tp_pct = atr_pct * raise_mult
            if pos.is_long:
                new_tp_price = pos.current_price * (1.0 + new_tp_pct)
            else:
                new_tp_price = pos.current_price * (1.0 - new_tp_pct)
            decision.action = ExitAction.RAISE_TP
            decision.new_tp_price = new_tp_price
            decision.new_tp_pct = new_tp_pct
            decision.confidence = 0.60 + (value - self.config.l2_raise_tp_value_thr)
            decision.reason = f"L2_RAISE_TP(v={value:.2f},risk={risk:.2f},new_tp={raise_mult:.1f}xATR)"
            return decision

        return decision

    # ══════════════════════════════════════════════════════════════════
    # 行为约束（冷却 / Gate 过滤）
    # ══════════════════════════════════════════════════════════════════

    def _apply_behavioral_constraints(
        self,
        decision: ExitDecision,
        pos: PositionState,
        now: float,
    ) -> ExitDecision:
        """应用执行层行为约束（inflight冷却、post-close冻结、gate过滤）"""
        if decision.action == ExitAction.HOLD:
            return decision

        key = pos.coin or "default"
        cd_map = self.state.cooldown.get(key, {})

        inflight_cd = cd_map.get("inflight", 0.0)
        if now - inflight_cd < self.config.inflight_cooldown_sec:
            decision.action = ExitAction.HOLD
            decision.gate_passed = False
            decision.gate_reason = "inflight_cooldown"
            decision.reason = f"BLOCKED_INFLIGHT({(now - inflight_cd):.0f}s)"
            return decision

        post_close_cd = cd_map.get("post_close", 0.0)
        post_close_sec = self.config.post_close_freeze_hours * 3600.0
        if now - post_close_cd < post_close_sec:
            if decision.action == ExitAction.CLOSE:
                decision.action = ExitAction.HOLD
                decision.gate_passed = False
                decision.gate_reason = "post_close_freeze"
                decision.reason = f"BLOCKED_POST_CLOSE({(now - post_close_cd)/3600:.1f}h)"
                return decision

        if self.config.gate_enabled and decision.confidence < self.config.gate_min_confidence:
            if decision.action != ExitAction.CLOSE or decision.priority != ExitPriority.P0_L0_HARD:
                decision.action = ExitAction.HOLD
                decision.gate_passed = False
                decision.gate_reason = "low_confidence"
                decision.reason = f"GATE_REJECTED(conf={decision.confidence:.2f})"
                return decision

        if decision.action == ExitAction.CLOSE:
            cd_map["post_close"] = now
            cd_map["inflight"] = now
        elif decision.action == ExitAction.REDUCE:
            cd_map["inflight"] = now

        self.state.cooldown[key] = cd_map
        decision.gate_passed = True
        return decision

    # ══════════════════════════════════════════════════════════════════
    # 特征计算
    # ══════════════════════════════════════════════════════════════════

    def _compute_features(
        self,
        pos: PositionState,
        candles: Optional[List[Dict]],
        regime: str,
        now: float,
    ) -> ExitFeatureSet:
        """计算离场特征集（技术文档 11.y.3 完整因子集）"""
        feats = ExitFeatureSet()

        if not candles or len(candles) < 20:
            feats.hold_risk = 0.5
            feats.hold_value = 0.5
            if pos.unrealized_pnl_pct < 0:
                feats.dd = min(1.0, max(0.0, -pos.unrealized_pnl_pct))
            else:
                feats.dd = 0.0
            feats.trend_shape = TrendShape.CHOP
            feats.atr_pct = pos.atr_pct if pos.atr_pct > 0 else 0.02
            return feats

        closes = []
        for c in candles:
            v = c.get("c", c.get("close", 0))
            if v:
                closes.append(float(v))

        if len(closes) < 20:
            feats.hold_risk = 0.5
            feats.hold_value = 0.5
            feats.atr_pct = pos.atr_pct if pos.atr_pct > 0 else 0.02
            return feats

        # 基础技术指标
        feats.rsi = self._calc_rsi(closes, 14)
        feats.macd_hist = self._calc_macd_hist(closes)
        feats.adx = self._calc_adx(candles, 14) if len(candles) >= 28 else 25.0
        feats.atr_pct = self._calc_atr_pct(candles, 14) if len(candles) >= 15 else pos.atr_pct

        # EMA 系列
        ema9 = self._ema(closes, 9)
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50) if len(closes) >= 50 else ema20
        feats.ema_short_dist = (closes[-1] - ema20) / ema20 if ema20 > 0 else 0.0
        feats.pot_dist_to_ema50 = (closes[-1] - ema50) / ema50 if ema50 > 0 else 0.0

        # 回撤（含 dd 启动门槛：mfe 覆盖成本或达到波动尺度后才启用 dd）
        lookback = min(50, len(closes))
        recent = closes[-lookback:]
        peak = max(recent)
        trough = min(recent)
        if pos.is_long:
            raw_dd = (peak - closes[-1]) / peak if peak > 0 else 0.0
            mfe_pct = (peak - closes[0]) / closes[0] if closes[0] > 0 else 0.0
        else:
            raw_dd = (closes[-1] - trough) / trough if trough > 0 else 0.0
            mfe_pct = (closes[0] - trough) / closes[0] if closes[0] > 0 else 0.0
        raw_dd = min(1.0, max(0.0, raw_dd))
        if pos.max_dd_pct > raw_dd:
            raw_dd = min(1.0, max(0.0, pos.max_dd_pct))

        cost_buffer = self._calc_cost_buffer(pos)
        mfe_cost_thr = cost_buffer * self.config.dd_mfe_enable_cost_mult
        atr_pct_val = feats.atr_pct if feats.atr_pct > 0 else pos.atr_pct
        mfe_atr_thr = atr_pct_val * self.config.dd_mfe_enable_atr_mult
        mfe_enable_thr = max(mfe_cost_thr, mfe_atr_thr)

        mfe_from_entry = max(0.0, pos.mfe_pnl_pct) if pos.mfe_pnl_pct > 0 else mfe_pct
        if mfe_from_entry >= mfe_enable_thr:
            feats.dd = raw_dd
        else:
            feats.dd = 0.0

        # 时间纬度形态（日线=EMA20斜率，周线=EMA50斜率）
        ema20_prev = self._ema(closes[:-1], 20) if len(closes) > 20 else ema20
        ema50_prev = self._ema(closes[:-1], 50) if len(closes) > 50 else ema50

        d_slope = (ema20 - ema20_prev) / ema20_prev if ema20_prev > 0 else 0.0
        w_slope = (ema50 - ema50_prev) / ema50_prev if ema50_prev > 0 else 0.0
        feats.trend_d_slope = d_slope
        feats.trend_w_slope = w_slope

        slope_deadband = 0.001
        d_trend = _sign(d_slope, slope_deadband)
        w_trend = _sign(w_slope, slope_deadband)
        feats.trend_d_dir = d_trend
        feats.trend_w_dir = w_trend
        feats.trend_shape = self._classify_trend_shape(w_trend, d_trend, feats.adx)

        if abs(w_slope) > 1e-9:
            feats.trend_rate_change_dw = _clip(d_slope / abs(w_slope), -5.0, 5.0)

        # 动能因子（mom: 方向 / 变化方向 / 变化速度）
        rsi_prev = self._calc_rsi(closes[:-1], 14) if len(closes) > 15 else feats.rsi
        feats.mom_rsi_delta = feats.rsi - rsi_prev
        feats.mom_dir = _sign(feats.mom_rsi_delta, 1.0)

        rsi_prev2 = self._calc_rsi(closes[:-2], 14) if len(closes) > 16 else rsi_prev
        prev_delta = rsi_prev - rsi_prev2
        feats.mom_chg_dir = _sign(feats.mom_rsi_delta - prev_delta, 0.5)

        if abs(prev_delta) > 1e-9:
            feats.mom_chg_speed = math.log(abs(feats.mom_rsi_delta) + 1e-9) - math.log(abs(prev_delta) + 1e-9)

        if len(closes) >= 35:
            macd_prev = self._calc_macd_hist(closes[:-1])
            feats.mom_macdh_delta = feats.macd_hist - macd_prev

        # 量能因子（vol: 方向 / 变化方向 / 变化速度）
        volumes = []
        for c in candles:
            v = c.get("v", c.get("volume", 0))
            if v:
                volumes.append(float(v))

        if len(volumes) >= 20:
            vol_ma20 = sum(volumes[-20:]) / 20
            vol_current = volumes[-1]
            vol_ratio = vol_current / vol_ma20 if vol_ma20 > 0 else 1.0

            vol_std = 0.0
            mean_v = vol_ma20
            var_v = sum((v - mean_v) ** 2 for v in volumes[-20:]) / 20
            vol_std = math.sqrt(var_v)
            feats.vol_z = (vol_current - vol_ma20) / vol_std if vol_std > 0 else 0.0

            feats.vol_dir = _sign(vol_ratio - 1.0, 0.1)

            vol_prev = volumes[-2] if len(volumes) >= 2 else vol_current
            vol_prev_ratio = vol_prev / vol_ma20 if vol_ma20 > 0 else 1.0
            feats.vol_ratio_delta = vol_ratio - vol_prev_ratio
            feats.vol_chg_dir = _sign(feats.vol_ratio_delta, 0.05)

            if len(volumes) >= 3:
                vol_prev2 = volumes[-3]
                vol_prev2_ratio = vol_prev2 / vol_ma20 if vol_ma20 > 0 else 1.0
                prev_delta = vol_prev_ratio - vol_prev2_ratio
                cur_delta = feats.vol_ratio_delta
                if abs(prev_delta) > 1e-9:
                    feats.vol_chg_speed = math.log(abs(cur_delta) + 1e-9) - math.log(abs(prev_delta) + 1e-9)

        # 势能因子（pot: 方向 / 变化方向 / 变化速度）
        feats.pot_dir = 1 if feats.adx > 30 else (-1 if feats.adx < 20 else 0)

        if len(candles) >= 40:
            adx_prev = self._calc_adx(candles[:-1], 14)
            feats.pot_adx_delta = feats.adx - adx_prev
            feats.pot_chg_dir = _sign(feats.pot_adx_delta, 1.0)

            if len(candles) >= 54:
                adx_prev2 = self._calc_adx(candles[:-2], 14)
                prev_delta = adx_prev - adx_prev2
                cur_delta = feats.pot_adx_delta
                if abs(prev_delta) > 1e-9:
                    feats.pot_chg_speed = math.log(abs(cur_delta) + 1e-9) - math.log(abs(prev_delta) + 1e-9)

        # 资金流向因子（flow: 方向 / 变化方向）
        # v1 代理变量：基于价格变动 + 成交量配合度（量价背离/共振）
        if len(volumes) >= 20 and len(closes) >= 20:
            ret_1d = (closes[-1] - closes[-min(24, len(closes))]) / closes[-min(24, len(closes))] if closes[-min(24, len(closes))] > 0 else 0.0
            vol_confirm = feats.vol_dir * _sign(ret_1d, 0.005)
            feats.flow_dir = vol_confirm

            if len(closes) >= 25:
                ret_prev = (closes[-2] - closes[-min(25, len(closes))]) / closes[-min(25, len(closes))] if closes[-min(25, len(closes))] > 0 else 0.0
                flow_prev = feats.vol_chg_dir * _sign(ret_prev, 0.005)
                feats.flow_chg_dir = _sign(feats.flow_dir - flow_prev, 0.5)

            if feats.trend_shape in (TrendShape.UP_STRONG, TrendShape.DOWN_STRONG):
                feats.macro_flow_dir = feats.trend_d_dir
            elif feats.trend_shape == TrendShape.CHOP:
                feats.macro_flow_dir = 0
            else:
                feats.macro_flow_dir = -feats.trend_d_dir

        # 风险预算（序列回撤增量惩罚）
        if self.config.risk_budget_enabled:
            rb_penalty = self._calc_risk_budget_penalty(pos, feats, now)
            feats.risk_budget_penalty = rb_penalty
        else:
            feats.risk_budget_penalty = 0.0

        # Regime 偏移
        feats.regime_shift = self._calc_regime_shift(feats)

        # MRD 评分
        feats.mrd_score = self._calc_mrd_score(pos, feats)
        feats.p_mrd = 1.0 / (1.0 + math.exp(-feats.mrd_score * 3))

        # hold_risk 主计算
        feats.hold_risk = self._calc_hold_risk(pos, feats)

        # MRD 模式下的风险调整
        if self.config.l1_mode == L1Mode.MRD:
            p_mrd = feats.p_mrd
            model_conf = _clip(abs(p_mrd - 0.5) * 2.0, 0.0, 1.0)
            feats.model_conf = model_conf

            if model_conf >= self.config.mrd_min_model_conf:
                if p_mrd < self.config.mrd_p_low:
                    boost = (self.config.mrd_p_low - p_mrd) / max(1e-9, self.config.mrd_p_low)
                    feats.hold_risk += self.config.mrd_risk_up * _clip(boost, 0.0, 1.0)
                elif p_mrd > self.config.mrd_p_high:
                    relief = (p_mrd - self.config.mrd_p_high) / max(1e-9, 1.0 - self.config.mrd_p_high)
                    feats.hold_risk -= self.config.mrd_risk_down * _clip(relief, 0.0, 1.0)

        # 风险预算惩罚
        feats.hold_risk += feats.risk_budget_penalty
        feats.hold_risk = float(_clip(feats.hold_risk, 0.0, 1.0))

        # hold_value = 1 - hold_risk（v1 简化）
        feats.hold_value = 1.0 - feats.hold_risk

        return feats

    def _calc_hold_risk(self, pos: PositionState, feats: ExitFeatureSet) -> float:
        """计算持有风险分（对齐 ml_trade_service.py 权重与因子）"""
        # 参考 _exit_hold_risk_score 的权重结构
        dd_risk = _clip(feats.dd / 0.3, 0.0, 1.0)

        adx_weak = _clip((20.0 - feats.adx) / 12.0, 0.0, 1.0) if feats.adx < 20 else 0.0
        chop_risk = _clip((feats.chop - 55.0) / 15.0, 0.0, 1.0) if feats.chop > 55 else 0.0
        atr_risk = _clip((feats.atr_pct - 0.010) / 0.020, 0.0, 1.0) if feats.atr_pct > 0 else 0.0

        # 动能反转风险
        if pos.is_long:
            mom_turn = _clip(-feats.mom_rsi_delta / 5.0, 0.0, 1.0)
            macd_turn = _clip(-feats.mom_macdh_delta / 0.004, 0.0, 1.0) if feats.mom_macdh_delta else 0.0
            stretch = _clip((feats.pot_dist_to_ema50 - 0.03) / 0.05, 0.0, 1.0)
        else:
            mom_turn = _clip(feats.mom_rsi_delta / 5.0, 0.0, 1.0)
            macd_turn = _clip(feats.mom_macdh_delta / 0.004, 0.0, 1.0) if feats.mom_macdh_delta else 0.0
            stretch = _clip((-feats.pot_dist_to_ema50 - 0.03) / 0.05, 0.0, 1.0)

        vol_fade = 0.5 * _clip(-feats.vol_ratio_delta / 0.5, 0.0, 1.0) + 0.5 * _clip(-feats.vol_z / 2.0, 0.0, 1.0)
        adx_fade = _clip(-feats.pot_adx_delta / 5.0, 0.0, 1.0) if feats.pot_adx_delta else 0.0

        if pos.is_long:
            rsi_risk = _clip((feats.rsi - 65.0) / 15.0, 0.0, 1.0) if feats.rsi > 0 else 0.0
            trend_risk = _clip(-feats.ema_short_dist / 0.010, 0.0, 1.0)
            macd_risk = _clip(-feats.macd_hist / 0.020, 0.0, 1.0)
        else:
            rsi_risk = _clip((35.0 - feats.rsi) / 15.0, 0.0, 1.0) if feats.rsi > 0 else 0.0
            trend_risk = _clip(feats.ema_short_dist / 0.010, 0.0, 1.0)
            macd_risk = _clip(feats.macd_hist / 0.020, 0.0, 1.0)

        risk = (
            (0.42 * dd_risk)
            + (0.13 * rsi_risk)
            + (0.14 * trend_risk)
            + (0.09 * macd_risk)
            + (0.08 * adx_weak)
            + (0.04 * max(chop_risk, atr_risk))
            + (0.04 * max(mom_turn, macd_turn))
            + (0.03 * vol_fade)
            + (0.02 * adx_fade)
            + (0.01 * stretch)
        )

        return float(_clip(risk, 0.0, 1.0))

    def _calc_mrd_score(self, pos: PositionState, feats: ExitFeatureSet) -> float:
        """计算 MRD（最小阻力方向）评分（技术文档传统金融基线）"""
        score = 0.0

        # 方向共振项
        if feats.trend_w_dir != 0:
            score += feats.trend_w_dir * 0.2
        if feats.trend_d_dir != 0:
            score += feats.trend_d_dir * 0.3
        if feats.mom_dir != 0:
            score += feats.mom_dir * 0.2

        # 量价配合
        if feats.vol_dir != 0 and feats.mom_dir == feats.vol_dir:
            score += feats.vol_dir * 0.15

        # 加速项
        if feats.mom_chg_dir != 0 and feats.mom_chg_dir == feats.mom_dir:
            score += feats.mom_chg_dir * 0.1

        # 趋势强度（ADX 强趋势加持）
        if feats.adx > 25 and feats.trend_d_dir != 0:
            score += feats.trend_d_dir * 0.1

        # 噪声惩罚
        if feats.trend_shape == TrendShape.CHOP:
            score *= 0.5

        # RSI 位置修正
        if pos.is_long:
            if 40 <= feats.rsi <= 60:
                score += 0.1
            elif feats.rsi > 75:
                score -= 0.15
        else:
            if 40 <= feats.rsi <= 60:
                score -= 0.1
            elif feats.rsi < 25:
                score += 0.15

        return score

    def _calc_risk_budget_penalty(self, pos: PositionState, feats: ExitFeatureSet, now: float) -> float:
        """风险预算惩罚（序列回撤增量超标时抬升风险）"""
        key = pos.coin or "default"
        hist = self.state.snapshot_history.get(key, [])

        hist.append({"ts": now, "dd": feats.dd})
        max_len = max(3, int(self.config.risk_budget_len))
        if len(hist) > max_len:
            hist = hist[-max_len:]
        self.state.snapshot_history[key] = hist

        if len(hist) < 3:
            return 0.0

        dd_inc = 0.0
        prev_dd = None
        for it in hist:
            d = float(it.get("dd", 0.0))
            if prev_dd is not None:
                dd_inc += max(0.0, d - prev_dd)
            prev_dd = d

        rb_dd = max(1e-6, self.config.risk_budget_dd)
        penalty = _clip(dd_inc / rb_dd, 0.0, 1.0) * self.config.risk_budget_risk_up
        return float(penalty)

    def _calc_regime_shift(self, feats: ExitFeatureSet) -> float:
        """Regime 分桶阈值偏移（简化版）"""
        shift = 0.0
        if feats.trend_shape == TrendShape.CHOP:
            shift += 0.05
        if feats.adx < 20:
            shift += 0.03
        return float(shift)

    def _classify_trend_shape(self, w_dir: int, d_dir: int, adx: float) -> TrendShape:
        """分类趋势形态（5 类）"""
        if adx < 20 and w_dir == 0 and d_dir == 0:
            return TrendShape.CHOP

        if w_dir > 0 and d_dir > 0:
            return TrendShape.UP_STRONG
        elif w_dir > 0 and d_dir < 0:
            return TrendShape.UP_REVERSAL
        elif w_dir < 0 and d_dir < 0:
            return TrendShape.DOWN_STRONG
        elif w_dir < 0 and d_dir > 0:
            return TrendShape.DOWN_REVERSAL
        else:
            if adx < 25:
                return TrendShape.CHOP
            return TrendShape.UP_STRONG if d_dir > 0 else (TrendShape.DOWN_STRONG if d_dir < 0 else TrendShape.CHOP)

    # ══════════════════════════════════════════════════════════════════
    # 技术指标计算
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _ema(prices: List[float], n: int) -> float:
        """指数移动平均"""
        if not prices:
            return 0.0
        if len(prices) < n:
            return prices[-1]
        k = 2.0 / (n + 1)
        ema = sum(prices[:n]) / n
        for p in prices[n:]:
            ema = p * k + ema * (1 - k)
        return ema

    @staticmethod
    def _calc_rsi(prices: List[float], n: int = 14) -> float:
        """RSI（取最近 n+1 根计算）"""
        if len(prices) < n + 1:
            return 50.0
        start = max(0, len(prices) - (n + 1))
        deltas = [prices[i] - prices[i - 1] for i in range(start + 1, len(prices))]
        if not deltas:
            return 50.0
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        avg_g = sum(gains) / n
        avg_l = sum(losses) / n
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - 100 / (1 + rs)

    @staticmethod
    def _calc_macd_hist(prices: List[float]) -> float:
        """MACD 柱状图（取最近 26 根）"""
        if len(prices) < 26:
            return 0.0
        start = max(0, len(prices) - 35)
        recent = prices[start:]
        ema12 = ClassicExitSystem._ema(recent, 12)
        ema26 = ClassicExitSystem._ema(recent, 26)
        return ema12 - ema26

    @staticmethod
    def _calc_atr_pct(candles: List[Dict], n: int = 14) -> float:
        """ATR%（取最近 n+1 根）"""
        if len(candles) < n + 1:
            return 0.02
        start = max(0, len(candles) - (n + 1))
        closes_prev = []
        for c in candles[start:]:
            v = c.get("c", c.get("close", 0))
            closes_prev.append(float(v) if v else 0.0)

        trs = []
        for i in range(1, min(n + 1, len(candles) - start)):
            idx = start + i
            h = float(candles[idx].get("h", candles[idx].get("high", 0)))
            l = float(candles[idx].get("l", candles[idx].get("low", 0)))
            pc = closes_prev[i - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = sum(trs) / len(trs) if trs else 0
        last_close = closes_prev[-1] if closes_prev else 1
        return atr / last_close if last_close > 0 else 0.02

    @staticmethod
    def _calc_adx(candles: List[Dict], n: int = 14) -> float:
        """ADX（取最近 2n 根，简化版）"""
        if len(candles) < n * 2:
            return 25.0
        try:
            start = max(0, len(candles) - (n * 2))
            highs = []
            lows = []
            for c in candles[start:]:
                highs.append(float(c.get("h", c.get("high", 0))))
                lows.append(float(c.get("l", c.get("low", 0))))
            plus_dm = []
            minus_dm = []
            trs = []
            for i in range(1, min(n + 1, len(highs))):
                up = highs[i] - highs[i - 1]
                down = lows[i - 1] - lows[i]
                plus_dm.append(max(up, 0) if up > down else 0)
                minus_dm.append(max(down, 0) if down > up else 0)
                tr = max(highs[i] - lows[i],
                         abs(highs[i] - highs[i - 1]),
                         abs(lows[i] - lows[i - 1]))
                trs.append(tr)
            atr_val = sum(trs) / n if trs else 0
            plus_di = 100 * (sum(plus_dm) / n) / atr_val if atr_val > 0 else 0
            minus_di = 100 * (sum(minus_dm) / n) / atr_val if atr_val > 0 else 0
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
            return dx
        except Exception:
            return 25.0

    # ══════════════════════════════════════════════════════════════════
    # 辅助方法
    # ══════════════════════════════════════════════════════════════════

    def _calc_cost_buffer(self, pos: PositionState) -> float:
        """计算成本缓冲（手续费 + 滑点 + 安全边际 + 资金费率）"""
        buffer = self.config.fee_roundtrip_pct + self.config.slippage_pct + self.config.safety_margin_pct
        if self.config.funding_buffer_enabled and pos.position_age_sec > 0:
            hours = pos.position_age_sec / 3600.0
            period = max(1.0, self.config.funding_buffer_period_hours)
            periods = math.ceil(hours / period)
            funding = abs(self.config.funding_default_rate_abs) * periods * self.config.funding_buffer_safety_mult
            buffer += funding
        return buffer

    def _merge_decision(
        self,
        base: ExitDecision,
        new: ExitDecision,
        priority: ExitPriority,
    ) -> ExitDecision:
        """合并决策（高优先级覆盖低优先级）"""
        if new.action == ExitAction.HOLD:
            return base
        merged = ExitDecision(
            action=new.action,
            priority=priority,
            reason=new.reason,
            confidence=new.confidence,
            reduce_frac=new.reduce_frac,
            suggested_price=new.suggested_price,
            l0_triggered=new.l0_triggered or base.l0_triggered,
            l0_reason=new.l0_reason or base.l0_reason,
            l1_hold_risk=new.l1_hold_risk if new.l1_hold_risk != 0.5 else base.l1_hold_risk,
            l1_hold_value=new.l1_hold_value if new.l1_hold_value != 0.5 else base.l1_hold_value,
            tb_sl_hit=new.tb_sl_hit or base.tb_sl_hit,
            tb_tp_hit=new.tb_tp_hit or base.tb_tp_hit,
            tb_time_hit=new.tb_time_hit or base.tb_time_hit,
            trailing_triggered=new.trailing_triggered or base.trailing_triggered,
            trailing_stop_price=new.trailing_stop_price or base.trailing_stop_price,
            new_trailing_stop=new.new_trailing_stop or base.new_trailing_stop,
            tstp_triggered=new.tstp_triggered or base.tstp_triggered,
            tstp_stage=new.tstp_stage or base.tstp_stage,
            new_tp_price=new.new_tp_price or base.new_tp_price,
            new_tp_pct=new.new_tp_pct or base.new_tp_pct,
            gate_passed=new.gate_passed if not base.gate_passed else base.gate_passed,
            gate_reason=new.gate_reason or base.gate_reason,
            features=new.features or base.features,
            source=new.source,
        )
        return merged

    # ── 便捷接口（向后兼容） ──────────────────────────────────────────

    def evaluate(
        self,
        coin: str,
        current_price: float,
        position_action: str,
        candles_1h: Optional[List[Dict]] = None,
    ) -> ExitDecision:
        """主评估接口（优先 API，失败回退本地）"""
        return self.evaluate_api(coin, current_price, position_action, candles_1h)

    def batch_evaluate(
        self,
        positions: List[Dict],
        candles_map: Optional[Dict[str, List[Dict]]] = None,
    ) -> Dict[str, ExitDecision]:
        """批量评估"""
        results = {}
        for pos_info in positions:
            coin = pos_info.get("coin", "")
            price = pos_info.get("price", 0)
            action = pos_info.get("action", "LONG")
            candles = candles_map.get(coin) if candles_map else None
            results[coin] = self.evaluate(coin, price, action, candles)
        return results

    def is_api_available(self) -> bool:
        """检查 API 是否可用"""
        if self.session is None:
            return False
        try:
            resp = self.session.get(f"{self.api_base}/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def reset_state(self, coin: Optional[str] = None) -> None:
        """重置运行时状态"""
        if coin:
            for d in (self.state.risk_gate, self.state.l2_armed, self.state.cooldown, self.state.snapshot_history):
                d.pop(coin, None)
        else:
            self.state = ExitRuntimeState()


# ── 便捷函数 ────────────────────────────────────────────────────────────────

_default_system: Optional[ClassicExitSystem] = None


def get_default_system() -> ClassicExitSystem:
    """获取全局默认实例"""
    global _default_system
    if _default_system is None:
        _default_system = ClassicExitSystem()
    return _default_system


def evaluate_exit(
    coin: str,
    current_price: float,
    position_action: str,
    candles_1h: Optional[List[Dict]] = None,
) -> ExitDecision:
    """便捷函数：评估离场条件"""
    return get_default_system().evaluate(coin, current_price, position_action, candles_1h)


def evaluate_exit_full(
    pos: PositionState,
    candles_1h: Optional[List[Dict]] = None,
    regime: str = "trend",
) -> ExitDecision:
    """便捷函数：完整离场评估"""
    return get_default_system().evaluate_full(pos, candles_1h, regime)


def batch_evaluate_exit(
    positions: List[Dict],
    candles_map: Optional[Dict[str, List[Dict]]] = None,
) -> Dict[str, ExitDecision]:
    """便捷函数：批量评估"""
    return get_default_system().batch_evaluate(positions, candles_map)


# ── 入口测试 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("经典指标离场系统 · 完整自检")
    print("=" * 70)

    system = ClassicExitSystem()
    cfg = system.config

    api_ok = system.is_api_available()
    print(f"\nAPI 可用性: {'✅' if api_ok else '❌ (Local 模式)'}")
    print(f"L1 模式: {cfg.l1_mode.value}")
    print(f"杠杆口径: {'启用' if cfg.apply_leverage_to_thresholds else '禁用'}")
    print(f"风险预算: {'启用' if cfg.risk_budget_enabled else '禁用'}")
    print(f"Exit Gate: {'启用' if cfg.gate_enabled else '禁用'}")

    test_candles = []
    base_price = 100.0
    for i in range(100):
        if i < 30:
            base_price += 0.5
        elif i < 60:
            base_price += 0.1
        else:
            base_price -= 0.6
        test_candles.append({
            "c": base_price,
            "h": base_price + 0.5,
            "l": base_price - 0.5,
            "v": 1000 + i * 10,
        })

    print(f"\n测试 K 线: {len(test_candles)} 根, 当前价: {base_price:.2f}")

    # 测试 1: 多头浮亏 + 下跌趋势 → L0 最大亏损
    print("\n" + "-" * 60)
    print("测试 1: 多头 + 深度浮亏 → L0 止损")
    pos1 = PositionState(
        coin="TEST", side="long",
        entry_price=120.0, current_price=base_price,
        position_age_sec=7200,
        unrealized_pnl_pct=(base_price - 120.0) / 120.0,
        leverage=3.0, atr_pct=0.025,
    )
    d1 = system.evaluate_full(pos1, test_candles, regime="trend")
    print(f"  PnL: {pos1.unrealized_pnl_pct*100:+.2f}% (eff: {pos1.pnl_eff*100:+.2f}%)")
    print(f"  动作: {d1.action.value:8s}  原因: {d1.reason}")
    print(f"  优先级: {d1.priority.value:8s}  hold_risk: {d1.l1_hold_risk:.2f}")

    # 测试 2: 多头大幅盈利 + 跟踪止损已激活
    system.reset_state("TEST2")
    print("\n" + "-" * 60)
    print("测试 2: 多头 + 大幅盈利 + 跟踪止损已激活")
    pos2 = PositionState(
        coin="TEST2", side="long",
        entry_price=60.0, current_price=base_price,
        position_age_sec=14400,
        unrealized_pnl_pct=(base_price - 60.0) / 60.0,
        leverage=3.0, atr_pct=0.025,
        trailing_armed=True, trailing_stop_price=85.0,
    )
    d2 = system.evaluate_full(pos2, test_candles, regime="trend")
    print(f"  PnL: {pos2.unrealized_pnl_pct*100:+.2f}% (eff: {pos2.pnl_eff*100:+.2f}%)")
    print(f"  动作: {d2.action.value:8s}  原因: {d2.reason}")
    print(f"  新跟踪止损价: {d2.new_trailing_stop:.2f}")

    # 测试 3: TSTP 8h close_if_weak
    system.reset_state("TEST3")
    print("\n" + "-" * 60)
    print("测试 3: 多头 + 8h 持仓 + TSTP close_if_weak")
    pos3 = PositionState(
        coin="TEST3", side="long",
        entry_price=80.0, current_price=95.0,
        position_age_sec=28800,
        unrealized_pnl_pct=0.1875,
        leverage=2.0, atr_pct=0.03,
    )
    d3 = system.evaluate_full(pos3, test_candles, regime="trend")
    print(f"  PnL: {pos3.unrealized_pnl_pct*100:+.2f}% (eff: {pos3.pnl_eff*100:+.2f}%)")
    print(f"  动作: {d3.action.value:8s}  原因: {d3.reason}")
    print(f"  hold_value: {d3.l1_hold_value:.2f}  hold_risk: {d3.l1_hold_risk:.2f}")

    # 测试 4: 风险闸门状态机（第一次不触发，需确认+冷却）
    system.reset_state("TEST4")
    print("\n" + "-" * 60)
    print("测试 4: 风险闸门状态机（首次 armed 不立即触发）")
    pos4 = PositionState(
        coin="TEST4", side="long",
        entry_price=90.0, current_price=base_price,
        position_age_sec=3600,
        unrealized_pnl_pct=(base_price - 90.0) / 90.0,
        leverage=2.0, atr_pct=0.03,
    )
    d4 = system.evaluate_full(pos4, test_candles, regime="trend")
    rg_state = system.state.risk_gate.get("TEST4", RiskGateState())
    print(f"  hold_risk: {d4.l1_hold_risk:.2f}")
    print(f"  风险闸门 armed: {rg_state.armed}, 确认计数: {rg_state.confirm_count}")
    print(f"  动作: {d4.action.value:8s}  原因: {d4.reason or '(hold)'}")

    # 测试 5: Triple Barrier 止盈
    system.reset_state("TEST5")
    print("\n" + "-" * 60)
    print("测试 5: Triple Barrier 止盈触发")
    pos5 = PositionState(
        coin="TEST5", side="long",
        entry_price=70.0, current_price=base_price,
        position_age_sec=1800,
        unrealized_pnl_pct=(base_price - 70.0) / 70.0,
        leverage=1.0, atr_pct=0.025,
    )
    d5 = system.evaluate_full(pos5, test_candles, regime="trend")
    print(f"  PnL: {pos5.unrealized_pnl_pct*100:+.2f}%")
    print(f"  动作: {d5.action.value:8s}  原因: {d5.reason}")
    print(f"  TB SL: {d5.tb_sl_hit}, TB TP: {d5.tb_tp_hit}, TB Time: {d5.tb_time_hit}")

    # 测试 6: L2 reduce + 滞回确认
    system.reset_state("TEST6")
    print("\n" + "-" * 60)
    print("测试 6: L2 价值-风险 reduce（含滞回确认）")
    pos6 = PositionState(
        coin="TEST6", side="long",
        entry_price=105.0, current_price=base_price,
        position_age_sec=5400,
        unrealized_pnl_pct=(base_price - 105.0) / 105.0,
        leverage=2.0, atr_pct=0.025,
    )
    d6_1 = system.evaluate_full(pos6, test_candles, regime="trend")
    print(f"  第 1 次: 动作={d6_1.action.value:8s} reason={d6_1.reason or '(hold)'}")
    d6_2 = system.evaluate_full(pos6, test_candles, regime="trend")
    print(f"  第 2 次: 动作={d6_2.action.value:8s} reason={d6_2.reason or '(hold)'}")

    # 测试 7: 强平缓冲
    system.reset_state("TEST7")
    print("\n" + "-" * 60)
    print("测试 7: L0 强平安全缓冲")
    pos7 = PositionState(
        coin="TEST7", side="long",
        entry_price=100.0, current_price=92.0,
        position_age_sec=1800,
        unrealized_pnl_pct=-0.08,
        leverage=10.0, atr_pct=0.03,
        liq_price=91.5,
    )
    d7 = system.evaluate_full(pos7, test_candles, regime="trend")
    buffer_pct = (pos7.current_price - pos7.liq_price) / pos7.current_price * 100
    print(f"  距强平价: {buffer_pct:.2f}%")
    print(f"  动作: {d7.action.value:8s}  原因: {d7.reason}")

    # 测试 8: 特征完整性检查
    print("\n" + "-" * 60)
    print("测试 8: 特征集完整性检查")
    pos8 = PositionState(coin="FULL", side="long", entry_price=100.0, current_price=base_price)
    feats = system._compute_features(pos8, test_candles, "trend", time.time())
    feat_checks = [
        ("hold_risk", feats.hold_risk),
        ("hold_value", feats.hold_value),
        ("mrd_score", feats.mrd_score),
        ("p_mrd", feats.p_mrd),
        ("dd", feats.dd),
        ("rsi", feats.rsi),
        ("adx", feats.adx),
        ("atr_pct", feats.atr_pct),
        ("trend_shape", feats.trend_shape.value),
        ("trend_w_dir", feats.trend_w_dir),
        ("trend_d_dir", feats.trend_d_dir),
        ("mom_dir", feats.mom_dir),
        ("mom_chg_dir", feats.mom_chg_dir),
        ("mom_rsi_delta", feats.mom_rsi_delta),
        ("vol_dir", feats.vol_dir),
        ("vol_z", feats.vol_z),
        ("pot_dir", feats.pot_dir),
        ("pot_adx_delta", feats.pot_adx_delta),
        ("pot_dist_to_ema50", feats.pot_dist_to_ema50),
        ("risk_budget_penalty", feats.risk_budget_penalty),
    ]
    for name, val in feat_checks:
        print(f"  {name:24s}: {val}")

    flow_checks = [
        ("flow_dir", feats.flow_dir),
        ("flow_chg_dir", feats.flow_chg_dir),
        ("macro_flow_dir", feats.macro_flow_dir),
        ("vol_chg_speed", feats.vol_chg_speed),
        ("pot_chg_speed", feats.pot_chg_speed),
        ("mom_chg_speed", feats.mom_chg_speed),
    ]
    print("\n  资金流向 & 变化速度因子:")
    for name, val in flow_checks:
        print(f"    {name:22s}: {val}")

    # 测试 9: dd 启动门槛（mfe不足时dd为0）
    system.reset_state("TEST9")
    print("\n" + "-" * 60)
    print("测试 9: dd 启动门槛（小盈利时 dd 被抑制）")
    pos9 = PositionState(
        coin="TEST9", side="long",
        entry_price=100.0, current_price=100.5,
        position_age_sec=600,
        unrealized_pnl_pct=0.005,
        leverage=1.0, atr_pct=0.02,
        mfe_pnl_pct=0.003,
    )
    feats9 = system._compute_features(pos9, test_candles, "trend", time.time())
    print(f"  mfe: {pos9.mfe_pnl_pct*100:.2f}%, 成本缓冲: {system._calc_cost_buffer(pos9)*100:.3f}%")
    print(f"  dd: {feats9.dd:.4f} (小盈利时应为0)")

    pos9b = PositionState(
        coin="TEST9b", side="long",
        entry_price=90.0, current_price=base_price,
        position_age_sec=7200,
        unrealized_pnl_pct=(base_price - 90.0) / 90.0,
        leverage=1.0, atr_pct=0.025,
        mfe_pnl_pct=0.15,
    )
    feats9b = system._compute_features(pos9b, test_candles, "trend", time.time())
    print(f"  大盈利 mfe: {pos9b.mfe_pnl_pct*100:.1f}%, dd: {feats9b.dd:.4f} (应 > 0)")

    # 测试 10: Risk Gate 两段式
    system.reset_state("TEST10")
    print("\n" + "-" * 60)
    print("测试 10: Risk Gate 两段式（先 reduce 后 close）")
    cfg10 = ExitConfig()
    cfg10.l0_risk_gate_close_enabled = True
    cfg10.l0_risk_gate_close_delay_min = 10.0
    cfg10.l0_risk_gate_cooldown_min = 5.0
    cfg10.l0_risk_gate_confirm_n = 1
    cfg10.l0_risk_gate_close_risk_boost = 0.05
    system10 = ClassicExitSystem(config=cfg10)
    pos10 = PositionState(
        coin="TEST10", side="long",
        entry_price=90.0, current_price=base_price,
        position_age_sec=7200,
        unrealized_pnl_pct=(base_price - 90.0) / 90.0,
        leverage=5.0, atr_pct=0.03,
    )
    feats_high_risk = ExitFeatureSet(hold_risk=0.75, hold_value=0.25, dd=0.3, adx=30.0)
    now0 = time.time()
    d10_1 = system10._check_risk_gate(pos10, feats_high_risk, now0)
    print(f"  T+0min: 动作={d10_1.action.value:8s} (首次 armed, 应 hold)")

    d10_2 = system10._check_risk_gate(pos10, feats_high_risk, now0 + 6 * 60)
    print(f"  T+6min: 动作={d10_2.action.value:8s} (冷却过, 应 reduce)")

    d10_3 = system10._check_risk_gate(pos10, feats_high_risk, now0 + 20 * 60)
    print(f"  T+20min: 动作={d10_3.action.value:8s} (close_delay 过, 风险高应 close)")

    print("\n" + "=" * 70)
    print("自检完成")
    print("=" * 70)
