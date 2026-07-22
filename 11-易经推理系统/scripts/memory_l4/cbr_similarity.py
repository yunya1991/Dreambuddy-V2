"""
CBR 相似度计算模块

参考 cbrkit (wi2trier/cbrkit, ICCBR 2024 Best Student Paper) 的
属性-值相似度模型 + 加权聚合器设计。

为交易场景定制：
- 数值特征: 价格、波动率、置信度、杠杆等
- 离散特征: 卦象、市态、方向、币种
- 结构特征: evidence_chain、quadrant、thinking_chain
"""

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple


type SimFunc = Callable[[Any, Any], float]


# ─────────────────────────────────────────────
# 数值相似度
# ─────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class LinearSimilarity:
    """线性相似度：距离越近越相似，max_dist 处为 0。"""
    max_dist: float
    min_dist: float = 0.0

    def __call__(self, x: float, y: float) -> float:
        dist = abs(x - y)
        if dist <= self.min_dist:
            return 1.0
        if dist >= self.max_dist:
            return 0.0
        return (self.max_dist - dist) / (self.max_dist - self.min_dist)


@dataclass(slots=True, frozen=True)
class ExponentialSimilarity:
    """指数衰减相似度：对距离敏感，适合波动率等特征。"""
    decay: float = 1.0

    def __call__(self, x: float, y: float) -> float:
        dist = abs(x - y)
        return math.exp(-self.decay * dist)


@dataclass(slots=True, frozen=True)
class ThresholdSimilarity:
    """阈值相似度：在阈值内完全相似，之外完全不相似。"""
    threshold: float

    def __call__(self, x: float, y: float) -> float:
        return 1.0 if abs(x - y) <= self.threshold else 0.0


@dataclass(slots=True, frozen=True)
class IntervalSimilarity:
    """区间归一化相似度：值在 [min_val, max_val] 区间内。"""
    min_val: float
    max_val: float

    def __call__(self, x: float, y: float) -> float:
        if x < self.min_val or x > self.max_val or y < self.min_val or y > self.max_val:
            return 0.0
        return 1.0 - abs(x - y) / (self.max_val - self.min_val)


# ─────────────────────────────────────────────
# 离散 / 分类相似度
# ─────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class CategoricalSimilarity:
    """分类相似度：精确匹配得 1.0，不匹配得 0.0。
    可配置同义词映射（如卦象的五行关联）。"""
    synonyms: Optional[Dict[str, List[str]]] = None

    def __call__(self, x: str, y: str) -> float:
        xs = str(x).strip()
        ys = str(y).strip()
        if xs == ys:
            return 1.0
        if self.synonyms:
            for group in self.synonyms.values():
                if xs in group and ys in group:
                    return 0.5  # 同义词组内部分相似
        return 0.0


# 八卦五行同义词映射（用于卦象相似度）
BAGUA_SYNONYMS: Dict[str, List[str]] = {
    "metal": ["乾", "兑", "天", "泽"],
    "wood": ["震", "巽", "雷", "风"],
    "water": ["坎", "水"],
    "fire": ["离", "火"],
    "earth": ["艮", "坤", "山", "地"],
}


# ─────────────────────────────────────────────
# 复合相似度
# ─────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class QuadrantSimilarity:
    """象限空间欧氏距离相似度。
    x 轴: benefit/harm (性能), y 轴: certainty (确定性)。"""
    max_dist: float = math.sqrt(2.0)

    def __call__(self, q1: Dict[str, float], q2: Dict[str, float]) -> float:
        x1 = q1.get("x", 0.0)
        y1 = q1.get("y", 0.0)
        x2 = q2.get("x", 0.0)
        y2 = q2.get("y", 0.0)
        dist = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
        return max(0.0, 1.0 - dist / self.max_dist)


@dataclass(slots=True, frozen=True)
class EvidenceChainSimilarity:
    """evidence_chain 相似度：按引用类型分别计算后加权聚合。"""
    type_weights: Dict[str, float] = field(default_factory=lambda: {
        "market_data_refs": 0.25,
        "signal_refs": 0.30,
        "strategy_refs": 0.15,
        "historical_refs": 0.15,
        "constraint_refs": 0.10,
        "analyst_refs": 0.05,
    })

    def __call__(self, ec1: Dict[str, List[Dict]], ec2: Dict[str, List[Dict]]) -> float:
        if not ec1 or not ec2:
            return 0.0

        scores: List[float] = []
        weights: List[float] = []

        for key, weight in self.type_weights.items():
            refs1 = ec1.get(key) or []
            refs2 = ec2.get(key) or []
            if not refs1 or not refs2:
                continue
            # Jaccard 相似度计算引用集合的交集
            set1 = {self._ref_key(r) for r in refs1}
            set2 = {self._ref_key(r) for r in refs2}
            inter = len(set1 & set2)
            union = len(set1 | set2)
            jaccard = inter / union if union > 0 else 0.0
            scores.append(jaccard)
            weights.append(weight)

        if not scores:
            return 0.0
        # 加权平均
        return sum(s * w for s, w in zip(scores, weights)) / sum(weights)

    @staticmethod
    def _ref_key(ref: Dict[str, Any]) -> str:
        return f"{ref.get('type', '')}={ref.get('ref', '')}"


# ─────────────────────────────────────────────
# 聚合器（Aggregator）
# ─────────────────────────────────────────────

type PoolingName = str


@dataclass(slots=True, frozen=True)
class SimilarityAggregator:
    """将多个局部相似度聚合为全局相似度。

    参考 cbrkit.sim.aggregator 设计，支持加权聚合。
    """
    pooling: PoolingName = "weighted_mean"
    weights: Optional[Dict[str, float]] = None
    default_weight: float = 1.0

    def __call__(self, similarities: Dict[str, float]) -> float:
        if not similarities:
            return 0.0

        if self.pooling == "mean":
            return sum(similarities.values()) / len(similarities)

        if self.pooling == "weighted_mean":
            if not self.weights:
                return sum(similarities.values()) / len(similarities)
            total_weight = 0.0
            weighted_sum = 0.0
            for key, sim in similarities.items():
                w = self.weights.get(key, self.default_weight)
                weighted_sum += sim * w
                total_weight += w
            return weighted_sum / total_weight if total_weight > 0 else 0.0

        if self.pooling == "min":
            return min(similarities.values())

        if self.pooling == "max":
            return max(similarities.values())

        if self.pooling == "geometric_mean":
            prod = 1.0
            for v in similarities.values():
                prod *= max(v, 1e-10)
            return prod ** (1.0 / len(similarities))

        # 默认 fallback
        return sum(similarities.values()) / len(similarities)


# ─────────────────────────────────────────────
# 交易案例特征相似度配置
# ─────────────────────────────────────────────

DEFAULT_CASE_SIM_WEIGHTS: Dict[str, float] = {
    "inst_id": 0.05,          # 币种
    "regime": 0.15,           # 市态
    "decision": 0.10,         # 方向
    "confidence": 0.15,       # 置信度
    "volatility": 0.10,       # 波动率
    "entry_price": 0.10,      # 入场价（区间归一化）
    "quadrant": 0.10,         # 象限
    "evidence_chain": 0.15,   # 证据链
    "pnl_pct": 0.05,          # 收益（用于结果过滤，通常不直接用于相似度）
}


def build_default_case_retriever(
    price_range: Tuple[float, float] = (1000.0, 100000.0),
    volatility_range: Tuple[float, float] = (0.01, 1.0),
    confidence_range: Tuple[float, float] = (0.0, 1.0),
) -> "CaseRetriever":
    """构建默认的交易案例检索器（属性-值模型）。"""
    from dataclasses import dataclass

    @dataclass
    class _CaseRetriever:
        sim_funcs: Dict[str, SimFunc]
        aggregator: SimilarityAggregator

        def __call__(self, query: Dict[str, Any], case: Dict[str, Any]) -> float:
            similarities: Dict[str, float] = {}
            for key, sim_func in self.sim_funcs.items():
                qv = query.get(key)
                cv = case.get(key)
                if qv is not None and cv is not None:
                    try:
                        similarities[key] = sim_func(qv, cv)
                    except Exception:
                        similarities[key] = 0.0
                elif qv is None and cv is None:
                    similarities[key] = 0.5
                else:
                    similarities[key] = 0.2
            return self.aggregator(similarities)

    return _CaseRetriever(
        sim_funcs={
            "inst_id": CategoricalSimilarity(),
            "regime": CategoricalSimilarity(),
            "decision": CategoricalSimilarity(),
            "confidence": IntervalSimilarity(
                min_val=confidence_range[0], max_val=confidence_range[1]
            ),
            "volatility": IntervalSimilarity(
                min_val=volatility_range[0], max_val=volatility_range[1]
            ),
            "entry_price": IntervalSimilarity(
                min_val=price_range[0], max_val=price_range[1]
            ),
            "quadrant": QuadrantSimilarity(),
            "evidence_chain": EvidenceChainSimilarity(),
        },
        aggregator=SimilarityAggregator(
            pooling="weighted_mean",
            weights=DEFAULT_CASE_SIM_WEIGHTS,
        ),
    )
