#!/usr/bin/env python3
"""
dream-data-analysis/analyzer.py
核心分析引擎 - 趋势惯性 + 阻力分解 + 校准建议
"""

import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

import yaml

# ============== 配置路径 ==============
CONFIG_DIR = Path(__file__).parent / "config"
RESISTANCE_WEIGHTS_PATH = CONFIG_DIR / "resistance_weights.yaml"
CALIBRATION_LAG_PATH = CONFIG_DIR / "calibration_lag_policy.yaml"

# ============== Timeframe 默认窗口配置 ==============
TIMEFRAME_DEFAULTS = {
    "15m": {"ma_short": 4, "ma_medium": 16, "ma_long": 48, "ema_fast": 8, "ema_slow": 21},
    "1h": {"ma_short": 5, "ma_medium": 20, "ma_long": 60, "ema_fast": 8, "ema_slow": 21},
    "4h": {"ma_short": 6, "ma_medium": 24, "ma_long": 72, "ema_fast": 12, "ema_slow": 26},
    "1d": {"ma_short": 5, "ma_medium": 20, "ma_long": 60, "ema_fast": 12, "ema_slow": 26},
    "mixed": {"ma_short": 5, "ma_medium": 20, "ma_long": 60, "ema_fast": 8, "ema_slow": 21},
}

# ============== 数据类 ==============

@dataclass
class TrendAnalysis:
    """趋势分析结果"""
    direction: str  # "up" | "down" | "flat" | "unknown"
    velocity: Optional[float] = None  # 速度 (price/step)
    acceleration: Optional[float] = None  # 加速度
    trend_confidence: float = 0.0  # 0-1
    ma_values: Dict[str, List[float]] = field(default_factory=dict)
    ema_values: Dict[str, List[float]] = field(default_factory=dict)
    reason_codes: List[str] = field(default_factory=list)


@dataclass
class ResistanceAnalysis:
    """阻力分析结果"""
    resistance_score: float = 0.0  # 0-100
    components: Dict[str, float] = field(default_factory=dict)
    weighted_contribution: Dict[str, float] = field(default_factory=dict)
    normalized_weights: Dict[str, float] = field(default_factory=dict)
    threshold_level: str = "UNKNOWN"  # LOW/MEDIUM/HIGH/EXTREME
    notes: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)


@dataclass
class CalibrationSuggestion:
    """校准建议"""
    expected_return_mapping: Dict[str, Any] = field(default_factory=dict)
    lambda_risk: Dict[str, Any] = field(default_factory=dict)
    thresholds: Dict[str, Any] = field(default_factory=dict)
    overall_status: str = "keep"  # "keep" | "calibrate"
    confidence: float = 0.0


@dataclass
class AnalysisResult:
    """完整分析结果"""
    trace_id: str
    ts: str
    inst_id: str
    trend: TrendAnalysis
    resistance: ResistanceAnalysis
    timeseries_features: Dict[str, Any] = field(default_factory=dict)
    calibration_suggestions: Dict[str, Any] = field(default_factory=dict)
    reason_codes: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    charts: Dict[str, List[str]] = field(default_factory=dict)


# ============== 配置加载 ==============

def load_config(path: Path) -> Dict:
    """加载 YAML 配置文件"""
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


class Config:
    """配置管理器"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        self.resistance = load_config(RESISTANCE_WEIGHTS_PATH)
        self.calibration = load_config(CALIBRATION_LAG_PATH)

    def get_weights(self, profile: str = "balanced") -> Dict[str, float]:
        """获取阻力权重"""
        profiles = self.resistance.get("risk_profiles", {})
        return profiles.get(profile, profiles.get("balanced", {}))

    def get_calibration_policy(self, name: str = "standard") -> Dict:
        """获取校准策略"""
        policies = self.calibration.get("calibration_policies", {})
        return policies.get(name, policies.get("standard", {}))

    def get_resistance_thresholds(self) -> Dict:
        """获取阻力阈值"""
        return self.resistance.get("resistance_thresholds", {})


# ============== 工具函数 ==============

def calculate_ma(data: List[float], window: int) -> List[Optional[float]]:
    """计算移动平均"""
    if not data or window <= 0:
        return []
    result = []
    for i in range(len(data)):
        if i < window - 1 or data[i] is None:
            result.append(None)
        else:
            window_data = data[i-window+1:i+1]
            valid = [x for x in window_data if x is not None and not math.isnan(x)]
            if valid:
                result.append(sum(valid) / len(valid))
            else:
                result.append(None)
    return result


def calculate_ema(data: List[float], window: int) -> List[Optional[float]]:
    """计算指数移动平均"""
    if not data or window <= 0:
        return []
    k = 2 / (window + 1)
    result = [None] * len(data)

    # 找到第一个有效值作为 EMA 起点
    first_valid_idx = None
    for i, v in enumerate(data):
        if v is not None and not math.isnan(v):
            first_valid_idx = i
            result[i] = v
            break

    if first_valid_idx is None:
        return result

    # 计算后续 EMA
    for i in range(first_valid_idx + 1, len(data)):
        if data[i] is not None and not math.isnan(data[i]):
            if result[i-1] is not None:
                result[i] = data[i] * k + result[i-1] * (1 - k)
            else:
                result[i] = data[i]

    return result


def calculate_velocity(series: List[float], dt: float = 1.0) -> List[Optional[float]]:
    """计算速度 (Δx/Δt)"""
    if len(series) < 2:
        return [None] * len(series)

    velocity = [None]
    for i in range(1, len(series)):
        if series[i] is not None and series[i-1] is not None:
            velocity.append((series[i] - series[i-1]) / dt)
        else:
            velocity.append(None)
    return velocity


def calculate_acceleration(velocity: List[float], dt: float = 1.0) -> List[Optional[float]]:
    """计算加速度 (Δv/Δt)"""
    if len(velocity) < 2:
        return [None] * len(velocity)

    acceleration = [None]
    for i in range(1, len(velocity)):
        if velocity[i] is not None and velocity[i-1] is not None:
            acceleration.append((velocity[i] - velocity[i-1]) / dt)
        else:
            acceleration.append(None)
    return acceleration


def get_valid_values(series: List[Optional[float]]) -> List[float]:
    """获取有效值列表"""
    return [x for x in series if x is not None and not math.isnan(x)]


def calculate_correlation(x: List[float], y: List[float]) -> float:
    """计算皮尔逊相关系数"""
    if len(x) != len(y) or len(x) < 3:
        return 0.0

    valid_pairs = [(xi, yi) for xi, yi in zip(x, y)
                   if xi is not None and yi is not None
                   and not math.isnan(xi) and not math.isnan(yi)]

    if len(valid_pairs) < 3:
        return 0.0

    x_vals = [p[0] for p in valid_pairs]
    y_vals = [p[1] for p in valid_pairs]

    n = len(x_vals)
    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n

    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x_vals, y_vals))
    denom_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x_vals))
    denom_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y_vals))

    if denom_x * denom_y == 0:
        return 0.0

    return numerator / (denom_x * denom_y)


# ============== 趋势分析 ==============

class TrendAnalyzer:
    """趋势惯性分析器"""

    def __init__(self, timeframe: str = "1h", use_log_price: bool = True):
        self.timeframe = timeframe
        self.use_log_price = use_log_price
        self.config = TIMEFRAME_DEFAULTS.get(timeframe, TIMEFRAME_DEFAULTS["1h"])

    def analyze(self, episode_series: List[Dict]) -> TrendAnalysis:
        """执行趋势分析"""
        if len(episode_series) < 3:
            return TrendAnalysis(
                direction="unknown",
                trend_confidence=0.0,
                reason_codes=["INSUFFICIENT_DATA"]
            )

        # 提取价格序列
        prices = self._extract_prices(episode_series)
        if not prices:
            return TrendAnalysis(
                direction="unknown",
                trend_confidence=0.0,
                reason_codes=["NO_PRICE_DATA"]
            )

        # 计算 MA/EMA
        ma_short = calculate_ma(prices, self.config["ma_short"])
        ma_medium = calculate_ma(prices, self.config["ma_medium"])
        ma_long = calculate_ma(prices, self.config["ma_long"])
        ema_fast = calculate_ema(prices, self.config["ema_fast"])
        ema_slow = calculate_ema(prices, self.config["ema_slow"])

        ma_values = {
            f"ma_{self.config['ma_short']}": ma_short,
            f"ma_{self.config['ma_medium']}": ma_medium,
            f"ma_{self.config['ma_long']}": ma_long,
        }
        ema_values = {
            f"ema_{self.config['ema_fast']}": ema_fast,
            f"ema_{self.config['ema_slow']}": ema_slow,
        }

        # 计算速度与加速度
        velocity = calculate_velocity(ma_long)
        acceleration = calculate_acceleration(velocity)

        # 获取最新值
        valid_velocities = get_valid_values(velocity)
        valid_accelerations = get_valid_values(acceleration)

        current_velocity = valid_velocities[-1] if valid_velocities else None
        current_acceleration = valid_accelerations[-1] if valid_accelerations else None

        # 判断趋势方向
        direction, confidence, reason_codes = self._determine_direction(
            ma_short, ma_medium, ma_long, ema_fast, ema_slow
        )

        return TrendAnalysis(
            direction=direction,
            velocity=current_velocity,
            acceleration=current_acceleration,
            trend_confidence=confidence,
            ma_values=ma_values,
            ema_values=ema_values,
            reason_codes=reason_codes
        )

    def _extract_prices(self, episode_series: List[Dict]) -> List[Optional[float]]:
        """提取价格序列"""
        prices = []
        for ep in episode_series:
            price_ref = ep.get("price_ref")
            if price_ref and price_ref.get("close") is not None:
                close = price_ref["close"]
                if self.use_log_price and close > 0:
                    prices.append(math.log(close))
                else:
                    prices.append(close)
            else:
                prices.append(None)
        return prices

    def _determine_direction(self,
                            ma_short: List[Optional[float]],
                            ma_medium: List[Optional[float]],
                            ma_long: List[Optional[float]],
                            ema_fast: List[Optional[float]],
                            ema_slow: List[Optional[float]]) -> Tuple[str, float, List[str]]:
        """判断趋势方向"""
        n = len(ma_long)
        reason_codes = []

        # 获取最新有效值
        valid_short = get_valid_values(ma_short)
        valid_medium = get_valid_values(ma_medium)
        valid_long = get_valid_values(ma_long)
        valid_fast = get_valid_values(ema_fast)
        valid_slow = get_valid_values(ema_slow)

        if not valid_long:
            return "unknown", 0.0, ["NO_VALID_MA_LONG"]

        # 计算各周期方向
        long_trend = 0
        if len(valid_long) >= 2:
            long_diff = valid_long[-1] - valid_long[-2]
            if abs(long_diff) > 0.001:  # 忽略微小波动
                long_trend = 1 if long_diff > 0 else -1
                reason_codes.append(f"LONG_TREND:{'UP' if long_trend > 0 else 'DOWN'}")

        medium_trend = 0
        if len(valid_medium) >= 2:
            medium_diff = valid_medium[-1] - valid_medium[-2]
            if abs(medium_diff) > 0.001:
                medium_trend = 1 if medium_diff > 0 else -1

        # 计算均线排列 (多头/空头)
        if len(valid_short) >= 1 and len(valid_medium) >= 1 and len(valid_long) >= 1:
            latest_short = valid_short[-1]
            latest_medium = valid_medium[-1]
            latest_long = valid_long[-1]

            if latest_short > latest_medium > latest_long:
                reason_codes.append("BULLISH_ALIGNMENT")
            elif latest_short < latest_medium < latest_long:
                reason_codes.append("BEARISH_ALIGNMENT")

        # EMA 金叉/死叉
        if len(valid_fast) >= 1 and len(valid_slow) >= 1:
            if len(valid_fast) >= 2 and len(valid_slow) >= 2:
                prev_fast = valid_fast[-2]
                prev_slow = valid_slow[-2]
                curr_fast = valid_fast[-1]
                curr_slow = valid_slow[-1]

                # 金叉
                if prev_fast <= prev_slow and curr_fast > curr_slow:
                    reason_codes.append("EMA_GOLDEN_CROSS")
                # 死叉
                elif prev_fast >= prev_slow and curr_fast < curr_slow:
                    reason_codes.append("EMA_DEATH_CROSS")

        # 综合判断
        bullish_signals = sum(1 for c in reason_codes
                             if "BULLISH" in c or "UP" in c or "GOLDEN" in c)
        bearish_signals = sum(1 for c in reason_codes
                             if "BEARISH" in c or "DOWN" in c or "DEATH" in c)

        if long_trend > 0 and (bullish_signals > bearish_signals):
            direction = "up"
            confidence = min(0.5 + 0.1 * (bullish_signals - bearish_signals), 0.95)
        elif long_trend < 0 and (bearish_signals > bullish_signals):
            direction = "down"
            confidence = min(0.5 + 0.1 * (bearish_signals - bullish_signals), 0.95)
        elif abs(long_trend) < 0.001:
            direction = "flat"
            confidence = 0.3
        else:
            direction = "unknown"
            confidence = 0.1

        return direction, confidence, reason_codes


# ============== 阻力分析 ==============

class ResistanceAnalyzer:
    """阻力分解分析器"""

    def __init__(self, profile: str = "balanced"):
        self.profile = profile
        self.config = Config().resistance
        self.weights = Config().get_weights(profile)

    def analyze(self, episode_series: List[Dict]) -> ResistanceAnalysis:
        """执行阻力分析"""
        # 提取阻力分量
        components = self._extract_components(episode_series)

        if not components:
            return ResistanceAnalysis(
                resistance_score=50.0,
                components={"error": "NO_COMPONENT_DATA"},
                reason_codes=["INSUFFICIENT_COMPONENT_DATA"]
            )

        # 计算加权阻力
        result = self._calculate_weighted_resistance(components)

        # 判定阈值等级
        thresholds = Config().get_resistance_thresholds()
        result.threshold_level = self._get_threshold_level(result.resistance_score, thresholds)

        return result

    def _extract_components(self, episode_series: List[Dict]) -> Dict[str, List[float]]:
        """从 episode 提取阻力分量"""
        components = {
            "cost_friction": [],
            "liquidity_friction": [],
            "crowding_friction": [],
            "vol_friction": []
        }

        for ep in episode_series:
            # 成本摩擦
            costs = ep.get("costs", {})
            total_cost = costs.get("total_cost_bps_est", 0)
            worst_slippage = costs.get("worst_case_slippage_bps", 0)
            cost_fric = min((total_cost + worst_slippage) / 2 * 10, 100)  # 缩放到 0-100
            components["cost_friction"].append(cost_fric)

            # 流动性摩擦
            ms = ep.get("microstructure", {})
            spread = ms.get("spread_bps", 0)
            depth = ms.get("depth_1pct_usdt", 0)
            imbalance = ms.get("orderbook_imbalance", 0.5)

            # 深度不足增加摩擦
            depth_factor = max(0, (10000 - depth) / 100) if depth > 0 else 50
            liq_fric = min((spread * 10 + depth_factor + abs(0.5 - imbalance) * 50) / 3, 100)
            components["liquidity_friction"].append(liq_fric)

            # 拥挤度摩擦
            regime = ep.get("regime", {})
            funding_rate = regime.get("funding_rate", 0)
            oi_change = regime.get("oi_change_pct", 0)
            crowding_fric = min((abs(funding_rate) * 100 + abs(oi_change) * 10) / 2, 100)
            components["crowding_friction"].append(crowding_fric)

            # 波动率摩擦
            vol_regime = regime.get("vol_regime", "medium")
            atr_ratio = regime.get("atr_ratio", 1.0)

            vol_map = {"low": 20, "medium": 50, "high": 80, "extreme": 100}
            vol_base = vol_map.get(vol_regime, 50)
            vol_fric = min((vol_base + (atr_ratio - 1) * 30) if atr_ratio else vol_base, 100)
            components["vol_friction"].append(vol_fric)

        return components

    def _calculate_weighted_resistance(self, components: Dict[str, List[float]]) -> ResistanceAnalysis:
        """计算加权阻力"""
        # 过滤掉非数值字段 (如 description)
        numeric_weights = {k: v for k, v in self.weights.items()
                         if isinstance(v, (int, float))}

        # 归一化权重
        total_weight = sum(numeric_weights.values())
        normalized = {k: v / total_weight for k, v in numeric_weights.items()}

        # 计算各分量平均值
        avg_components = {}
        for k, vals in components.items():
            valid = get_valid_values(vals)
            avg_components[k] = statistics.mean(valid) if valid else 50.0

        # 加权求和
        resistance_score = sum(
            avg_components.get(k, 50) * normalized.get(k, 0)
            for k in normalized
        )

        # 各分量贡献
        weighted_contribution = {
            k: avg_components.get(k, 50) * normalized.get(k, 0)
            for k in normalized
        }

        # 生成 notes
        notes = []
        for k, v in avg_components.items():
            if v > 70:
                notes.append(f"HIGH_{k.upper()}")
            elif v < 30:
                notes.append(f"LOW_{k.upper()}")

        return ResistanceAnalysis(
            resistance_score=resistance_score,
            components=avg_components,
            weighted_contribution=weighted_contribution,
            normalized_weights=normalized,
            notes=notes,
            reason_codes=[f"RESISTANCE_SCORE:{resistance_score:.1f}"]
        )

    def _get_threshold_level(self, score: float, thresholds: Dict) -> str:
        """判定阻力阈值等级"""
        if score >= thresholds.get("EXTREME", 85):
            return "EXTREME"
        elif score >= thresholds.get("HIGH", 70):
            return "HIGH"
        elif score >= thresholds.get("MEDIUM", 50):
            return "MEDIUM"
        else:
            return "LOW"


# ============== 校准建议 ==============

class CalibrationAdvisor:
    """校准建议生成器"""

    def __init__(self, policy: str = "standard"):
        self.policy = policy
        self.config = Config().calibration
        self.policy_config = Config().get_calibration_policy(policy)

    def generate(self, episode_series: List[Dict],
                trend: TrendAnalysis,
                resistance: ResistanceAnalysis) -> CalibrationSuggestion:
        """生成校准建议"""
        if len(episode_series) < self.policy_config.get("min_rounds", 5):
            return CalibrationSuggestion(
                expected_return_mapping={"status": "unknown", "reason": "INSUFFICIENT_DATA"},
                lambda_risk={"status": "keep"},
                thresholds={"status": "keep"},
                overall_status="keep",
                confidence=0.0
            )

        # 计算 E[R] 映射
        er_mapping = self._analyze_expected_return(episode_series)

        # λ 风险建议
        lambda_risk = self._analyze_lambda_risk(episode_series, trend, resistance)

        # 阈值建议
        thresholds = self._analyze_thresholds(episode_series, resistance)

        # 综合状态
        overall_status = "calibrate" if (
            er_mapping.get("status") in ["tighten", "loosen", "rebuild"] or
            lambda_risk.get("status") != "keep"
        ) else "keep"

        # 计算置信度
        evidence_count = len(er_mapping.get("evidence_refs", [])) + \
                        len(lambda_risk.get("evidence_refs", []))
        confidence = min(evidence_count / 5.0, 0.95) if evidence_count > 0 else 0.3

        return CalibrationSuggestion(
            expected_return_mapping=er_mapping,
            lambda_risk=lambda_risk,
            thresholds=thresholds,
            overall_status=overall_status,
            confidence=confidence
        )

    def _analyze_expected_return(self, episode_series: List[Dict]) -> Dict:
        """分析 E[R] 映射"""
        # 提取评分和收益
        scores = []
        pnl_pcts = []

        for ep in episode_series:
            score = ep.get("scores", {}).get("total")
            if score is not None:
                scores.append(score)

            # 计算 PnL 百分比 (如果有)
            edge_bps = ep.get("edge_eval", {}).get("edge_bps", 0)
            if edge_bps:
                pnl_pcts.append(edge_bps / 100)  # bps -> %

        if len(scores) < 5:
            return {"status": "unknown", "reason": "INSUFFICIENT_SAMPLES"}

        # 计算相关性
        if len(scores) == len(pnl_pcts) and len(scores) >= 3:
            correlation = calculate_correlation(scores, pnl_pcts)
        else:
            correlation = 0.5  # 默认

        # 分桶分析
        buckets = self._bucket_analysis(scores, pnl_pcts)

        # 判断状态
        er_config = self.config.get("expected_return_mapping", {})
        mismatch_thresholds = er_config.get("mismatch_thresholds", {})

        status = "keep"
        if correlation < mismatch_thresholds.get("min_correlation", 0.4):
            status = "rebuild"
        elif buckets.get("gap") < mismatch_thresholds.get("er_gap_high_low", 2.0):
            status = "tighten"
        elif buckets.get("gap") > mismatch_thresholds.get("er_gap_high_low", 2.0) * 2:
            status = "loosen"

        return {
            "status": status,
            "correlation": correlation,
            "buckets": buckets,
            "evidence_refs": [f"ER_CORR:{correlation:.3f}", f"ER_STATUS:{status}"]
        }

    def _bucket_analysis(self, scores: List[float], pnl_pcts: List[float]) -> Dict:
        """分桶分析"""
        if not scores:
            return {"high_er": 0, "low_er": 0, "gap": 0}

        high_score_threshold = 70
        low_score_threshold = 50

        high_scores = [s for s in scores if s >= high_score_threshold]
        low_scores = [s for s in scores if s < low_score_threshold]

        high_pnl = [p for s, p in zip(scores, pnl_pcts) if s >= high_score_threshold] if pnl_pcts else []
        low_pnl = [p for s, p in zip(scores, pnl_pcts) if s < low_score_threshold] if pnl_pcts else []

        high_er = statistics.mean(high_pnl) if high_pnl else 0
        low_er = statistics.mean(low_pnl) if low_pnl else 0

        return {
            "high_er": high_er,
            "low_er": low_er,
            "gap": high_er - low_er,
            "sample_count": len(scores)
        }

    def _analyze_lambda_risk(self, episode_series: List[Dict],
                            trend: TrendAnalysis,
                            resistance: ResistanceAnalysis) -> Dict:
        """分析 λ 风险建议"""
        # 检测市场状态
        conditions = []

        # 高波动
        if resistance.threshold_level in ["HIGH", "EXTREME"]:
            conditions.append("high_volatility_regime")

        # 连续亏损
        recent_pnls = [ep.get("edge_eval", {}).get("edge_bps", 0)
                      for ep in episode_series[-5:]]
        if len([p for p in recent_pnls if p < 0]) >= 3:
            conditions.append("consecutive_losses")

        # 趋势明确
        if trend.direction in ["up", "down"]:
            conditions.append("stable_trend")

        # λ 建议
        lambda_config = self.config.get("lambda_risk", {})

        if "high_volatility_regime" in conditions or "consecutive_losses" in conditions:
            status = "up"
        elif "stable_trend" in conditions and "high_volatility_regime" not in conditions:
            status = "down"
        else:
            status = "keep"

        return {
            "status": status,
            "conditions": conditions,
            "evidence_refs": [f"LAMBDA_STATUS:{status}"] + conditions
        }

    def _analyze_thresholds(self, episode_series: List[Dict],
                           resistance: ResistanceAnalysis) -> Dict:
        """分析阈值建议"""
        threshold_config = self.config.get("threshold_suggestions", {})

        # edge_min_bps 建议
        edge_suggestion = "keep"
        if resistance.threshold_level in ["HIGH", "EXTREME"]:
            edge_suggestion = "tighten"
        elif resistance.threshold_level == "LOW":
            edge_suggestion = "loosen"

        # max_worst_slippage_bps 建议
        slippage_suggestion = "keep"
        if resistance.threshold_level in ["HIGH", "EXTREME"]:
            slippage_suggestion = "tighten"

        return {
            "edge_min_bps": {
                "suggestion": edge_suggestion,
                "current": threshold_config.get("edge_min_bps", {}).get("default", 20)
            },
            "max_worst_slippage_bps": {
                "suggestion": slippage_suggestion,
                "current": threshold_config.get("max_worst_slippage_bps", {}).get("default", 30)
            },
            "blackout_windows": {
                "suggestion": "add" if resistance.threshold_level == "EXTREME" else "none",
                "candidates": threshold_config.get("blackout_windows", {}).get("candidates", [])
            }
        }


# ============== 主分析器 ==============

class DataAnalyzer:
    """数据分析主入口"""

    def __init__(self,
                 timeframe: str = "1h",
                 resistance_profile: str = "balanced",
                 calibration_policy: str = "standard",
                 generate_charts: bool = True):
        self.timeframe = timeframe
        self.resistance_profile = resistance_profile
        self.calibration_policy = calibration_policy
        self.generate_charts = generate_charts

        # 初始化子分析器
        self.trend_analyzer = TrendAnalyzer(timeframe)
        self.resistance_analyzer = ResistanceAnalyzer(resistance_profile)
        self.calibration_advisor = CalibrationAdvisor(calibration_policy)

    def analyze(self, episode_series: List[Dict],
                trace_id: str = "",
                ts: str = "",
                inst_id: str = "") -> AnalysisResult:
        """执行完整分析"""

        # 提取元信息
        if not trace_id and episode_series:
            trace_id = episode_series[0].get("trace_id", "unknown")
        if not ts and episode_series:
            ts = episode_series[-1].get("ts", datetime.now().isoformat())
        if not inst_id and episode_series:
            inst_id = episode_series[0].get("inst_id", "UNKNOWN")

        # 1. 趋势分析
        trend = self.trend_analyzer.analyze(episode_series)

        # 2. 阻力分析
        resistance = self.resistance_analyzer.analyze(episode_series)

        # 3. 校准建议
        calibration = self.calibration_advisor.generate(episode_series, trend, resistance)

        # 4. 时间序列特征
        timeseries_features = self._extract_features(episode_series, trend, resistance)

        # 5. 图表清单
        charts = self._generate_chart_list()

        # 6. 证据引用
        evidence_refs = self._collect_evidence_refs(episode_series, trend, resistance, calibration)

        return AnalysisResult(
            trace_id=trace_id,
            ts=ts,
            inst_id=inst_id,
            trend=trend,
            resistance=resistance,
            timeseries_features=timeseries_features,
            calibration_suggestions=asdict(calibration),
            charts=charts,
            evidence_refs=evidence_refs,
            reason_codes=trend.reason_codes + resistance.reason_codes
        )

    def _extract_features(self, episode_series: List[Dict],
                          trend: TrendAnalysis,
                          resistance: ResistanceAnalysis) -> Dict:
        """提取时间序列特征"""
        # 提取所有可用特征名
        feature_names = []

        for ep in episode_series:
            # 评分特征
            if "scores" in ep:
                for k in ep["scores"].keys():
                    if k not in feature_names:
                        feature_names.append(f"scores.{k}")

            # 成本特征
            if "costs" in ep:
                for k in ep["costs"].keys():
                    if k not in feature_names:
                        feature_names.append(f"costs.{k}")

            # 微结构特征
            if "microstructure" in ep:
                for k in ep["microstructure"].keys():
                    if k not in feature_names:
                        feature_names.append(f"microstructure.{k}")

        # 趋势特征
        feature_names.extend([
            "trend.velocity",
            "trend.acceleration",
            "trend.confidence",
            "resistance.score",
            "resistance.cost_friction",
            "resistance.liquidity_friction",
            "resistance.crowding_friction",
            "resistance.vol_friction"
        ])

        return {
            "feature_names": feature_names,
            "feature_series_refs": [f"episodes.{f}" for f in feature_names[:10]]
        }

    def _generate_chart_list(self) -> Dict:
        """生成图表清单"""
        return {
            "subplots": [
                "price_ma_ema",           # 价格 + MA/EMA
                "trend_strength",          # 趋势强度
                "edge_bps_gate",           # edge_bps 与门禁决策
                "execution_costs",         # 执行成本
                "regime_labels",           # 市场状态标签
                "resistance_breakdown"     # 阻力分解
            ],
            "overview_plots": [
                "radar_snapshot",          # 评分雷达图
                "trend_vs_resistance",     # 趋势 vs 阻力
                "calibration_dashboard"    # 校准仪表盘
            ]
        }

    def _collect_evidence_refs(self,
                               episode_series: List[Dict],
                               trend: TrendAnalysis,
                               resistance: ResistanceAnalysis,
                               calibration: CalibrationSuggestion) -> List[str]:
        """收集证据引用"""
        refs = []

        # Episode 引用
        if episode_series:
            refs.append(f"episodes[{len(episode_series)}]")

        # 趋势引用
        refs.extend([
            f"trend:{trend.direction}",
            f"velocity:{trend.velocity:.4f}" if trend.velocity else "velocity:null",
            f"confidence:{trend.trend_confidence:.2f}"
        ])

        # 阻力引用
        refs.append(f"resistance:{resistance.resistance_score:.1f}")
        refs.append(f"threshold_level:{resistance.threshold_level}")

        # 校准引用
        refs.append(f"calibration:{calibration.overall_status}")

        return refs

    def to_dict(self, result: AnalysisResult) -> Dict:
        """转换为字典"""
        return asdict(result)

    def to_json(self, result: AnalysisResult, indent: int = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(asdict(result), indent=indent, ensure_ascii=False)


# ============== 便捷函数 ==============

def analyze_episodes(episode_series: List[Dict],
                    timeframe: str = "1h",
                    resistance_profile: str = "balanced",
                    calibration_policy: str = "standard",
                    generate_charts: bool = True) -> Dict:
    """
    便捷分析函数

    用法示例:
    >>> episodes = [...]  # episode_series
    >>> result = analyze_episodes(episodes, timeframe="1h")
    >>> print(result["trend"]["direction"])
    >>> print(result["resistance"]["resistance_score"])
    """
    analyzer = DataAnalyzer(
        timeframe=timeframe,
        resistance_profile=resistance_profile,
        calibration_policy=calibration_policy,
        generate_charts=generate_charts
    )

    result = analyzer.analyze(episode_series)
    return analyzer.to_dict(result)


# ============== CLI 测试 ==============

if __name__ == "__main__":
    # 生成测试数据
    import random

    def generate_mock_episode(i: int) -> Dict:
        """生成模拟 episode"""
        base_price = 50000 + i * 10 + random.uniform(-100, 100)
        return {
            "trace_id": f"test_{i}",
            "ts": f"2026-04-18T{10 + i % 14}:00:00",
            "inst_id": "BTC-USDT-SWAP",
            "price_ref": {"close": base_price},
            "scores": {
                "total": 60 + random.uniform(-20, 30),
                "technical": {"total": 65},
                "macro": {"total": 55}
            },
            "edge_eval": {"edge_bps": random.uniform(-50, 100)},
            "costs": {
                "total_cost_bps_est": random.uniform(5, 20),
                "worst_case_slippage_bps": random.uniform(10, 40)
            },
            "microstructure": {
                "spread_bps": random.uniform(1, 5),
                "depth_1pct_usdt": random.uniform(5000, 15000),
                "orderbook_imbalance": random.uniform(0.3, 0.7)
            },
            "regime": {
                "funding_rate": random.uniform(-0.01, 0.01),
                "oi_change_pct": random.uniform(-5, 10),
                "vol_regime": random.choice(["low", "medium", "high"])
            }
        }

    # 生成 20 个 mock episodes
    mock_episodes = [generate_mock_episode(i) for i in range(20)]

    print("=" * 60)
    print("Dream-Data-Analysis Analyzer Test")
    print("=" * 60)

    # 执行分析
    result = analyze_episodes(
        mock_episodes,
        timeframe="1h",
        resistance_profile="balanced",
        calibration_policy="standard"
    )

    # 打印结果
    print(f"\n📊 Trend Analysis:")
    print(f"   Direction: {result['trend']['direction']}")
    print(f"   Velocity: {result['trend'].get('velocity', 'N/A')}")
    print(f"   Confidence: {result['trend']['trend_confidence']:.2f}")
    print(f"   Reason Codes: {result['trend']['reason_codes']}")

    print(f"\n⚡ Resistance Analysis:")
    print(f"   Score: {result['resistance']['resistance_score']:.1f}")
    print(f"   Level: {result['resistance']['threshold_level']}")
    print(f"   Components: {result['resistance']['components']}")

    print(f"\n🎯 Calibration Suggestions:")
    print(f"   E[R] Mapping: {result['calibration_suggestions']['expected_return_mapping']['status']}")
    print(f"   Lambda Risk: {result['calibration_suggestions']['lambda_risk']['status']}")
    print(f"   Overall: {result['calibration_suggestions']['overall_status']}")

    print(f"\n📈 Chart List:")
    for chart_type, charts in result['charts'].items():
        print(f"   {chart_type}: {charts}")

    print(f"\n🔗 Evidence Refs:")
    for ref in result['evidence_refs']:
        print(f"   - {ref}")

    print("\n" + "=" * 60)
    print("Test completed!")
