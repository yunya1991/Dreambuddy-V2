"""P1 T5: StatAggregator — BMA + KL散度加权聚合

SPEC §2.3.1 核心算法：
  1. 每个算法独立产出参数建议 θ_i
  2. KL散度权重（与当前后验差异越大权重越高，纠正群体保守偏差）
  3. 贝叶斯模型平均：θ_post = Σ w_i * θ_i / Σ w_i
  4. 硬约束兜底：SL≥4%, TP≥12%, RR≥2:1

设计要点：
  - KL散度近似：用参数向量的欧氏距离 ||θ_i - θ_prior|| 作为差异度量
  - 权重 = softmax(diff_i / temperature)，temperature 控制差异敏感度
  - 硬约束兜底：聚合后若违规，逐项拉到下限
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 硬约束常量
# ============================================================================
SL_FLOOR = 0.04       # SL 下限 4%
TP_FLOOR = 0.12       # TP 下限 12%
RR_FLOOR = 2.0        # RR 比下限 2:1
ATR_MULT_DEFAULT = 4.5  # ATR 倍数默认值

# 默认参数（空输入或异常时回退）
_DEFAULT_PARAMS = {
    "sl_floor": SL_FLOOR,
    "tp_floor": TP_FLOOR,
    "atr_mult": ATR_MULT_DEFAULT,
}

# KL散度加权的温度参数（小 temperature → 差异大的权重更高）
_DEFAULT_TEMPERATURE = 0.02


# ============================================================================
# 数据结构
# ============================================================================
@dataclass
class AlgoObservation:
    """单个算法的观察输出"""
    algo_name: str
    params: Dict[str, float]      # sl_floor, tp_floor, atr_mult
    confidence: float             # [0, 1]
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ParamProposal:
    """聚合后的参数建议"""
    params: Dict[str, float]              # sl_floor, tp_floor, atr_mult
    confidence: float                     # [0, 1]
    weights: Dict[str, float] = field(default_factory=dict)  # 各算法权重


# ============================================================================
# StatAggregator
# ============================================================================
class StatAggregator:
    """统计观察归总器：BMA + KL散度加权。

    Args:
        temperature: KL散度加权温度参数（默认 0.02）
    """

    def __init__(self, temperature: float = _DEFAULT_TEMPERATURE) -> None:
        self.temperature = max(temperature, 1e-6)

    def aggregate(
        self,
        observations: List[AlgoObservation],
        prior: Optional[ParamProposal] = None,
    ) -> ParamProposal:
        """聚合多算法输出为单一参数建议。

        Args:
            observations: 算法观察列表
            prior: 当前后验（用于计算 KL散度权重），None 时用观察均值

        Returns:
            ParamProposal: 聚合后的参数 + 置信度 + 各算法权重
        """
        # 空输入回退默认值
        if not observations:
            return ParamProposal(
                params=dict(_DEFAULT_PARAMS),
                confidence=0.0,
                weights={},
            )

        # 单算法直接返回（权重=1）
        if len(observations) == 1:
            obs = observations[0]
            params = self._enforce_hard_constraints(obs.params)
            return ParamProposal(
                params=params,
                confidence=obs.confidence,
                weights={obs.algo_name: 1.0},
            )

        # 计算 prior（如果未提供，用观察均值）
        if prior is None:
            prior_params = self._mean_params(observations)
        else:
            prior_params = prior.params

        # 1. 计算每个算法与 prior 的差异（KL散度近似：欧氏距离）
        diffs = []
        for obs in observations:
            d = self._param_distance(obs.params, prior_params)
            diffs.append(d)

        # 2. softmax(diff_i / temperature) 作为权重
        weights = self._softmax_weighted(diffs)

        # 3. 贝叶斯模型平均：θ_post = Σ w_i * θ_i
        theta_post = {}
        for key in _DEFAULT_PARAMS:
            theta_post[key] = sum(
                w * obs.params.get(key, _DEFAULT_PARAMS[key])
                for w, obs in zip(weights, observations)
            )

        # 置信度按权重传播
        confidence = sum(
            w * obs.confidence for w, obs in zip(weights, observations)
        )

        # 4. 硬约束兜底
        theta_post = self._enforce_hard_constraints(theta_post)

        # 组装权重 dict
        weights_dict = {
            obs.algo_name: w for obs, w in zip(observations, weights)
        }

        return ParamProposal(
            params=theta_post,
            confidence=confidence,
            weights=weights_dict,
        )

    # ----------------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------------
    @staticmethod
    def _mean_params(observations: List[AlgoObservation]) -> Dict[str, float]:
        """计算观察的参数均值（作为默认 prior）"""
        if not observations:
            return dict(_DEFAULT_PARAMS)
        result = {}
        for key in _DEFAULT_PARAMS:
            vals = [o.params.get(key, _DEFAULT_PARAMS[key]) for o in observations]
            result[key] = sum(vals) / len(vals)
        return result

    @staticmethod
    def _param_distance(
        params_a: Dict[str, float],
        params_b: Dict[str, float],
    ) -> float:
        """计算参数距离（KL散度近似：欧氏距离）。

        KL散度大的算法权重越高，纠正群体保守偏差（PolySwarm 思路）。
        """
        sq_sum = 0.0
        for key in _DEFAULT_PARAMS:
            a = params_a.get(key, _DEFAULT_PARAMS[key])
            b = params_b.get(key, _DEFAULT_PARAMS[key])
            sq_sum += (a - b) ** 2
        return math.sqrt(sq_sum)

    def _softmax_weighted(self, diffs: List[float]) -> List[float]:
        """softmax(d_i / temperature) — 差异大的权重高"""
        if not diffs:
            return []
        # 防止数值溢出：减最大值
        scaled = [d / self.temperature for d in diffs]
        max_scaled = max(scaled)
        exps = [math.exp(s - max_scaled) for s in scaled]
        total = sum(exps)
        return [e / total for e in exps]

    @staticmethod
    def _enforce_hard_constraints(params: Dict[str, float]) -> Dict[str, float]:
        """硬约束兜底：SL≥4%, TP≥12%, RR≥2:1"""
        result = dict(params)

        # SL 下限
        result["sl_floor"] = max(result.get("sl_floor", SL_FLOOR), SL_FLOOR)
        # TP 下限
        result["tp_floor"] = max(result.get("tp_floor", TP_FLOOR), TP_FLOOR)
        # RR 比：TP/SL ≥ 2:1，违例时拉高 TP
        if result["tp_floor"] / result["sl_floor"] < RR_FLOOR:
            result["tp_floor"] = result["sl_floor"] * RR_FLOOR
        # atr_mult 兜底
        if result.get("atr_mult", 0) <= 0:
            result["atr_mult"] = ATR_MULT_DEFAULT

        return result


# ============================================================================
# T8: trigger_recompute 触发机制
# ============================================================================
def trigger_recompute(
    trigger_type: str = "scheduled",
    symbols: Optional[List[str]] = None,
    market_data_map: Optional[Dict[str, dict]] = None,
    adapters: Optional[List] = None,
    aggregator: Optional[StatAggregator] = None,
) -> Dict[str, ParamProposal]:
    """触发重新归总（定时或事件驱动）。

    Args:
        trigger_type: "scheduled" (定时) | "cusum_event" (事件驱动)
        symbols: 待归总的币种列表，None 时用默认列表
        market_data_map: {symbol: market_data} 各币种的市场数据
        adapters: 适配器列表，None 时用 get_all_adapters()
        aggregator: StatAggregator 实例，None 时新建

    Returns:
        {symbol: ParamProposal}

    触发源：
        - 定时：每日 00:00 UTC 全量归总（HMM/Hurst/Bagua 重新拟合）
        - 事件：CUSUM 检测到结构性突变 → 立即触发增量归总
    """
    if symbols is None:
        symbols = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "PEPE"]
    if market_data_map is None:
        market_data_map = {}
    if adapters is None:
        # 延迟导入避免循环依赖
        from .adapters import get_all_adapters
        adapters = get_all_adapters()
    if aggregator is None:
        aggregator = StatAggregator()

    logger.info(
        "trigger_recompute: type=%s symbols=%d adapters=%d",
        trigger_type, len(symbols), len(adapters),
    )

    results: Dict[str, ParamProposal] = {}
    for symbol in symbols:
        market_data = market_data_map.get(symbol, {})
        # 收集所有适配器的 observation（None 自动跳过）
        observations = []
        for adapter in adapters:
            obs = adapter.observe(symbol, market_data)
            if obs is not None:
                observations.append(obs)

        # 聚合
        proposal = aggregator.aggregate(observations)
        results[symbol] = proposal

        logger.info(
            "trigger_recompute[%s]: %d adapters observed, "
            "SL=%.4f TP=%.4f conf=%.3f",
            symbol, len(observations),
            proposal.params["sl_floor"],
            proposal.params["tp_floor"],
            proposal.confidence,
        )

    return results
