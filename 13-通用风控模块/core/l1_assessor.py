"""
L1 价值-风险评估
================
复现经典离场系统的核心评估逻辑，包括：
    - hold_risk 加权计算（dd_risk 主导，10维因子）
    - MRD Score（最小阻力方向）概率评估
    - 风险预算序列回撤惩罚
    - L2 动作映射（滞回状态机 + 确认计数 + 死区）
    - Regime 分桶阈值偏移

计算链路：
    [基础指标] → hold_risk 加权
              → MRD 调整
              → 风险预算惩罚
              → clip[0,1] = final hold_risk
              → hold_value = 1 - hold_risk
              → Regime 偏移
              → L2 滞回状态机
              → 动作映射 (CLOSE / REDUCE / HOLD)
              → reduce_frac 线性插值
"""

import math
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone


class TrendShape(str, Enum):
    """趋势形态（5类）"""
    UP_STRONG = "up_strong"
    UP_REVERSAL = "up_reversal"
    DOWN_STRONG = "down_strong"
    DOWN_REVERSAL = "down_reversal"
    CHOP = "chop"


class L1Mode(str, Enum):
    """L1评估模式"""
    HEURISTIC = "heuristic"
    MRD = "mrd"
    ML = "ml"


@dataclass
class ExitFeatureSet:
    """离场特征集 — L1评估的输入"""
    # 持仓状态
    dd: float = 0.0
    mfe: float = 0.0

    # 基础技术指标
    rsi: float = 50.0
    macd_hist: float = 0.0
    adx: float = 25.0
    atr_pct: float = 0.02
    ema_short_dist: float = 0.0
    chop: float = 50.0

    # 时间纬度
    trend_shape: TrendShape = TrendShape.CHOP
    trend_w_dir: int = 0
    trend_d_dir: int = 0

    # 动能因子
    mom_dir: int = 0
    mom_chg_dir: int = 0
    mom_rsi_delta: float = 0.0
    mom_macdh_delta: float = 0.0

    # 量能因子
    vol_dir: int = 0
    vol_chg_dir: int = 0
    vol_z: float = 0.0
    vol_ratio_delta: float = 0.0

    # 势能因子
    pot_dir: int = 0
    pot_chg_dir: int = 0
    pot_adx_delta: float = 0.0
    pot_dist_to_ema50: float = 0.0

    # 资金流向
    flow_dir: int = 0
    macro_flow_dir: int = 0

    # ML 概率（外部注入）
    p_tail: Optional[float] = None
    p_move: Optional[float] = None

    # Regime
    regime: str = ""

    @classmethod
    def from_market_data(
        cls,
        rsi: float = 50.0,
        macd_hist: float = 0.0,
        adx: float = 25.0,
        atr_pct: float = 0.02,
        chop: float = 50.0,
        ema_short_dist: float = 0.0,
        dd: float = 0.0,
        mfe: float = 0.0,
        trend_shape: str = "chop",
        trend_w_dir: int = 0,
        trend_d_dir: int = 0,
        mom_dir: int = 0,
        mom_rsi_delta: float = 0.0,
        mom_macdh_delta: float = 0.0,
        vol_dir: int = 0,
        vol_z: float = 0.0,
        vol_ratio_delta: float = 0.0,
        pot_adx_delta: float = 0.0,
        pot_dist_to_ema50: float = 0.0,
        regime: str = "",
        p_tail: Optional[float] = None,
        p_move: Optional[float] = None,
    ) -> "ExitFeatureSet":
        """从市场数据构建特征集"""
        try:
            ts = TrendShape(trend_shape)
        except ValueError:
            ts = TrendShape.CHOP

        return cls(
            rsi=rsi, macd_hist=macd_hist, adx=adx, atr_pct=atr_pct,
            chop=chop, ema_short_dist=ema_short_dist,
            dd=dd, mfe=mfe,
            trend_shape=ts, trend_w_dir=trend_w_dir, trend_d_dir=trend_d_dir,
            mom_dir=mom_dir, mom_rsi_delta=mom_rsi_delta, mom_macdh_delta=mom_macdh_delta,
            vol_dir=vol_dir, vol_z=vol_z, vol_ratio_delta=vol_ratio_delta,
            pot_adx_delta=pot_adx_delta, pot_dist_to_ema50=pot_dist_to_ema50,
            regime=regime,
            p_tail=p_tail, p_move=p_move,
        )


@dataclass
class L2HysteresisState:
    """L2滞回状态机 — per-coin 持久化"""
    close_armed: bool = False
    close_confirm_count: int = 0
    reduce_armed: bool = False
    reduce_confirm_count: int = 0
    last_risk: float = 0.0
    last_update_ts: int = 0


@dataclass
class L1AssessmentResult:
    """L1评估结果"""
    hold_risk: float = 0.5
    hold_value: float = 0.5
    mrd_score: float = 0.0
    p_mrd: float = 0.5
    p_tail: Optional[float] = None
    p_move: Optional[float] = None
    model_conf: float = 0.0
    risk_budget_penalty: float = 0.0
    regime_shift: float = 0.0
    action: str = "hold"
    reduce_frac: float = 0.0
    confidence: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


class L1ValueRiskAssessor:
    """L1 价值-风险评估器

    复现经典离场系统的核心评估逻辑，提供完整的 hold_risk → 动作映射 链路。

    使用方式：
        assessor = L1ValueRiskAssessor(config)
        result = assessor.assess(position, features, l2_state)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def assess(
        self,
        position: Any,
        features: ExitFeatureSet,
        l2_state: Optional[L2HysteresisState] = None,
        l1_mode: L1Mode = L1Mode.HEURISTIC,
        snapshot_history: Optional[List[Dict[str, Any]]] = None,
    ) -> L1AssessmentResult:
        """执行完整的L1评估

        Args:
            position: 持仓状态（PositionState）
            features: 离场特征集
            l2_state: L2滞回状态（per-coin）
            l1_mode: 评估模式
            snapshot_history: dd快照历史（用于风险预算）

        Returns:
            L1AssessmentResult 评估结果
        """
        result = L1AssessmentResult()

        # 1. 计算 hold_risk（启发式基线）
        hold_risk = self._calc_hold_risk(position, features)
        result.hold_risk = hold_risk

        # 2. MRD Score 计算
        mrd_score = self._calc_mrd_score(features, position)
        result.mrd_score = mrd_score
        result.p_mrd = 1.0 / (1.0 + math.exp(-mrd_score * 3))

        # 3. MRD 模式调整
        if l1_mode == L1Mode.MRD:
            hold_risk = self._apply_mrd_adjustment(hold_risk, result.p_mrd, result)

        # 4. ML 模式调整
        if l1_mode == L1Mode.ML:
            hold_risk = self._apply_ml_adjustment(hold_risk, features, result)

        # 5. 风险预算惩罚
        rb_penalty = self._calc_risk_budget_penalty(
            position, features, snapshot_history or []
        )
        result.risk_budget_penalty = rb_penalty
        hold_risk = hold_risk + rb_penalty

        # 6. clip
        hold_risk = max(0.0, min(1.0, hold_risk))
        result.hold_risk = hold_risk
        result.hold_value = 1.0 - hold_risk

        # 7. Regime 偏移
        regime_shift = self._calc_regime_shift(features)
        result.regime_shift = regime_shift

        # 8. L2 动作映射
        if l2_state is None:
            l2_state = L2HysteresisState()

        action, reduce_frac, confidence = self._evaluate_value_risk(
            hold_risk, result.hold_value, position, l2_state, regime_shift
        )

        result.action = action
        result.reduce_frac = reduce_frac
        result.confidence = confidence
        result.p_tail = features.p_tail
        result.p_move = features.p_move

        return result

    def _calc_hold_risk(self, pos: Any, feats: ExitFeatureSet) -> float:
        """计算 hold_risk — 10维加权公式

        权重总和 = 1.00，dd_risk 主导（0.42）
        """
        is_long = getattr(pos, "is_long", True)

        def _clip(v, lo=0.0, hi=1.0):
            return max(lo, min(hi, v))

        # 各分项风险
        dd_risk = _clip(feats.dd / 0.3)

        adx_weak = _clip((20 - feats.adx) / 12) if feats.adx < 20 else 0.0
        chop_risk = _clip((feats.chop - 55) / 15) if feats.chop > 55 else 0.0
        atr_risk = _clip((feats.atr_pct - 0.010) / 0.020) if feats.atr_pct > 0 else 0.0

        # 多头口径（short 镜像）
        sign = 1.0 if is_long else -1.0

        mom_turn = _clip(-feats.mom_rsi_delta * sign / 5.0)
        macd_turn = _clip(-feats.mom_macdh_delta * sign / 0.004)
        stretch = _clip((feats.pot_dist_to_ema50 * sign - 0.03) / 0.05)
        rsi_risk = _clip((feats.rsi - 65) * sign / 15)
        trend_risk = _clip(-feats.ema_short_dist * sign / 0.010)
        macd_risk = _clip(-feats.macd_hist * sign / 0.020)

        vol_fade = 0.5 * _clip(-feats.vol_ratio_delta / 0.5) + 0.5 * _clip(-feats.vol_z / 2.0)
        adx_fade = _clip(-feats.pot_adx_delta / 5.0)

        # 加权求和
        risk = (
            0.42 * dd_risk
            + 0.13 * rsi_risk
            + 0.14 * trend_risk
            + 0.09 * macd_risk
            + 0.08 * adx_weak
            + 0.04 * max(chop_risk, atr_risk)
            + 0.04 * max(mom_turn, macd_turn)
            + 0.03 * vol_fade
            + 0.02 * adx_fade
            + 0.01 * stretch
        )

        return _clip(risk)

    def _calc_mrd_score(self, feats: ExitFeatureSet, pos: Any) -> float:
        """计算 MRD Score — 最小阻力方向"""
        is_long = getattr(pos, "is_long", True)
        sign = 1 if is_long else -1

        score = 0.0

        # 方向共振项
        if feats.trend_w_dir != 0:
            score += feats.trend_w_dir * sign * 0.2
        if feats.trend_d_dir != 0:
            score += feats.trend_d_dir * sign * 0.3
        if feats.mom_dir != 0:
            score += feats.mom_dir * sign * 0.2

        # 量价配合
        if feats.vol_dir != 0 and feats.mom_dir == feats.vol_dir:
            score += feats.vol_dir * sign * 0.15

        # 加速项
        mom_chg_dir = getattr(feats, "mom_chg_dir", 0)
        if mom_chg_dir != 0 and mom_chg_dir == feats.mom_dir:
            score += mom_chg_dir * sign * 0.1

        # ADX 强趋势加持
        if feats.adx > 25 and feats.trend_d_dir != 0:
            score += feats.trend_d_dir * sign * 0.1

        # 噪声惩罚
        if feats.trend_shape == TrendShape.CHOP:
            score *= 0.5

        # RSI 位置修正
        rsi = feats.rsi
        if is_long:
            if 40 <= rsi <= 60:
                score += 0.1
            elif rsi > 75:
                score -= 0.15
        else:
            if 40 <= rsi <= 60:
                score += 0.1
            elif rsi < 25:
                score -= 0.15

        return score

    def _apply_mrd_adjustment(
        self, hold_risk: float, p_mrd: float, result: L1AssessmentResult
    ) -> float:
        """MRD 模式调整"""
        mrd_min_conf = self.config.get("mrd_min_model_conf", 0.25)
        p_low = self.config.get("mrd_p_low", 0.40)
        p_high = self.config.get("mrd_p_high", 0.60)
        risk_up = self.config.get("mrd_risk_up", 0.10)
        risk_down = self.config.get("mrd_risk_down", 0.06)

        model_conf = max(0.0, min(1.0, abs(p_mrd - 0.5) * 2.0))
        result.model_conf = model_conf

        if model_conf >= mrd_min_conf:
            if p_mrd < p_low:
                boost = (p_low - p_mrd) / p_low
                hold_risk += risk_up * max(0.0, min(1.0, boost))
            elif p_mrd > p_high:
                relief = (p_mrd - p_high) / (1.0 - p_high)
                hold_risk -= risk_down * max(0.0, min(1.0, relief))

        return hold_risk

    def _apply_ml_adjustment(
        self, hold_risk: float, feats: ExitFeatureSet, result: L1AssessmentResult
    ) -> float:
        """ML 模式调整 — 融合 p_tail / p_move"""
        blend_h = self.config.get("ml_blend_h", 0.25)

        if feats.p_tail is not None:
            p_tail = max(0.0, min(1.0, feats.p_tail))
            result.model_conf = max(0.0, min(1.0, abs(p_tail - 0.5) * 2.0))
            hold_risk = blend_h * hold_risk + (1.0 - blend_h) * p_tail
        elif feats.p_move is not None:
            p_move = max(0.0, min(1.0, feats.p_move))
            result.model_conf = max(0.0, min(1.0, abs(p_move - 0.5) * 2.0))

        return hold_risk

    def _calc_risk_budget_penalty(
        self,
        pos: Any,
        feats: ExitFeatureSet,
        snapshot_history: List[Dict[str, Any]],
    ) -> float:
        """风险预算序列回撤惩罚

        只计 dd 上升增量，归一化后乘以上限。
        """
        if not self.config.get("risk_budget_enabled", True):
            return 0.0

        max_len = max(3, int(self.config.get("risk_budget_len", 12)))
        rb_dd = max(1e-6, self.config.get("risk_budget_dd", 0.35))
        rb_up = max(0.0, self.config.get("risk_budget_risk_up", 0.15))

        if len(snapshot_history) < 3:
            return 0.0

        dd_inc = 0.0
        prev_dd = None
        for item in snapshot_history[-max_len:]:
            d = float(item.get("dd", 0.0))
            d = max(0.0, min(1.0, d))
            if prev_dd is not None:
                dd_inc += max(0.0, d - prev_dd)
            prev_dd = d

        penalty = max(0.0, min(1.0, dd_inc / rb_dd)) * rb_up
        return float(penalty)

    def _calc_regime_shift(self, feats: ExitFeatureSet) -> float:
        """Regime 分桶阈值偏移"""
        shift = 0.0

        if feats.trend_shape == TrendShape.CHOP:
            shift += self.config.get("regime_chop_shift", 0.05)

        if feats.adx < 20:
            shift += self.config.get("regime_low_adx_shift", 0.03)

        # 从 regime 字段读取
        regime_shifts = self.config.get("regime_threshold_shifts", {})
        if feats.regime and feats.regime.lower() in regime_shifts:
            shift += regime_shifts[feats.regime.lower()]

        return float(shift)

    def _evaluate_value_risk(
        self,
        risk: float,
        value: float,
        pos: Any,
        l2_state: L2HysteresisState,
        regime_shift: float = 0.0,
    ) -> tuple:
        """L2 动作映射 — 滞回状态机

        返回 (action, reduce_frac, confidence)
        """
        close_thr = self.config.get("l2_close_threshold", 0.75) + regime_shift
        reduce_thr = self.config.get("l2_reduce_threshold", 0.55) + regime_shift
        deadband = self.config.get("l2_deadband", 0.03)
        confirm_n = max(1, int(self.config.get("l2_confirm_n", 1)))

        close_exit_thr = max(0.0, close_thr - deadband)
        reduce_exit_thr = max(0.0, reduce_thr - deadband)

        # 滞回状态更新
        if risk >= close_thr:
            l2_state.close_confirm_count += 1
            l2_state.close_armed = True
        elif risk <= close_exit_thr:
            l2_state.close_confirm_count = 0
            l2_state.close_armed = False

        if risk >= reduce_thr:
            l2_state.reduce_confirm_count += 1
            l2_state.reduce_armed = True
        elif risk <= reduce_exit_thr:
            l2_state.reduce_confirm_count = 0
            l2_state.reduce_armed = False

        l2_state.last_risk = risk
        l2_state.last_update_ts = int(datetime.now(timezone.utc).timestamp())

        # 动作触发
        action = "hold"
        reduce_frac = 0.0
        confidence = 0.0

        # CLOSE 判定
        if l2_state.close_armed and l2_state.close_confirm_count >= confirm_n:
            action = "close"
            confidence = min(1.0, risk)

        # REDUCE 判定
        if action != "close":
            reduce_min_profit = self.config.get("l2_reduce_min_profit_pct", 0.01)
            pnl_eff = getattr(pos, "pnl_eff", 0.0)

            if l2_state.reduce_armed and l2_state.reduce_confirm_count >= confirm_n:
                if pnl_eff >= reduce_min_profit:
                    base_rf = self.config.get("l2_reduce_base_frac", 0.30)
                    max_rf = self.config.get("l2_reduce_max_frac", 0.70)
                    span = max(1e-6, self.config.get("l2_reduce_risk_span", 0.20))

                    excess = max(0.0, risk - reduce_thr)
                    frac = base_rf + (excess / span) * (max_rf - base_rf)
                    reduce_frac = min(max_rf, max(base_rf, frac))

                    action = "reduce"
                    confidence = min(1.0, risk)

        # 低价值额外路径
        low_value_thr = self.config.get("l2_low_value_threshold", 0.30)
        if value <= low_value_thr and risk >= 0.50 and action == "hold":
            action = "reduce"
            reduce_frac = 0.4
            confidence = min(1.0, risk)

        return action, reduce_frac, confidence
