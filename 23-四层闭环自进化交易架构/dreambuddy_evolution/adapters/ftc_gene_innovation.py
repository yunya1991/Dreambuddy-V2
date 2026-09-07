"""
ftc_gene_innovation — L2 基因创新引擎（基因突变机制）

生物学对应: 基因突变 — 创造现有基因库没有的全新因子

触发条件 (满足任一):
  1. 涟漪系统检测到现有 condition 基因无法解释的异常模式
  2. 反思引擎发现连续失败的共同模式（如"放量不涨"反复出现）
  3. FTC 组合空间饱和（所有组合 ESS 趋同，无差异）

流程:
  异常模式 → 生成新基因候选 → 探索轨道验证(5U, N≥100, ESS≥0.5)
  → 验证通过 → 写入 gene_data/strategy_genes/ → 所有 FTC 可复用

FAIL-OPEN: 异常检测失败时返回空列表，不抛异常。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# L2 验证门槛
L2_MIN_SAMPLES = 100
L2_MIN_ESS = 0.5


@dataclass
class GeneCandidate:
    """新基因候选"""
    gene_id: str
    gene_type: str  # "condition" or "action"
    category: str
    condition_type: str
    description: str
    expression: str
    parameters: dict
    source: str  # "ripple_anomaly" | "reflection_pattern" | "saturation"
    tags: list[str]


# 常见异常模式 → 新基因模板映射
# 注意: category 和 condition_type 必须符合 schema enum，不能自定义
ANOMALY_GENE_TEMPLATES = {
    "vol_price_divergence": {
        "gene_id": "CD-VOL-PRICE-DIVERGENCE",
        "category": "momentum",
        "condition_type": "indicator",
        "description": "放量不涨（量价背离）— Wyckoff 努力-结果不符",
        "expression": "vol_ratio > 1.3 AND price_change < 0.005",
        "parameters": {
            "vol_ratio_threshold": {"value": 1.3, "range": {"low": 1.1, "high": 3.0}},
            "price_change_threshold": {"value": 0.005, "range": {"low": 0.001, "high": 0.02}},
        },
        "tags": ["volume", "divergence", "wyckoff", "effort-result"],
    },
    "oi_price_divergence": {
        "gene_id": "CD-OI-PRICE-DIVERGENCE",
        "category": "momentum",
        "condition_type": "indicator",
        "description": "OI 上升但价格不涨（多头被套/派发）",
        "expression": "oi_change_pct > 0.05 AND price_change < 0.005",
        "parameters": {
            "oi_change_threshold": {"value": 0.05, "range": {"low": 0.02, "high": 0.15}},
        },
        "tags": ["oi", "divergence", "distribution"],
    },
    "funding_sentiment_extreme": {
        "gene_id": "CD-FUNDING-SENT-EXTREME",
        "category": "sentiment",
        "condition_type": "indicator",
        "description": "费率极端+情绪极端同向（拥挤交易，反身性反转）",
        "expression": "abs(funding_rate) > 0.001 AND abs(sentiment) > 0.7",
        "parameters": {
            "funding_threshold": {"value": 0.001, "range": {"low": 0.0003, "high": 0.005}},
            "sentiment_threshold": {"value": 0.7, "range": {"low": 0.5, "high": 0.95}},
        },
        "tags": ["funding", "sentiment", "reflexivity", "crowding"],
    },
    "capital_inflow_no_pump": {
        "gene_id": "CD-CAPITAL-INFLOW-NO-PUMP",
        "category": "momentum",
        "condition_type": "indicator",
        "description": "资金持续流入但价格未涨（吸筹阶段）",
        "expression": "capital_flow > 0.2 AND price_change < 0.01",
        "parameters": {
            "capital_flow_threshold": {"value": 0.2, "range": {"low": 0.1, "high": 0.5}},
        },
        "tags": ["flow", "accumulation", "smart-money"],
    },
}


class GeneInnovationEngine:
    """L2 基因创新引擎"""

    def __init__(self, gene_root: Optional[str | Path] = None):
        if gene_root is None:
            self._gene_root = Path(__file__).resolve().parent.parent / "gene_data"
        else:
            self._gene_root = Path(gene_root)
        self._candidates: dict[str, GeneCandidate] = {}
        self._validated_genes: set[str] = set()

    def detect_anomalies(
        self,
        ripple_signals: list[dict] | None = None,
        reflection_insights: list[dict] | None = None,
        ftc_ess_convergence: bool = False,
    ) -> list[GeneCandidate]:
        """
        检测异常模式，生成新基因候选。

        Args:
            ripple_signals: 涟漪系统检测到的信号列表
            reflection_insights: 反思引擎产出的失败模式洞察
            ftc_ess_convergence: FTC 组合空间是否饱和（ESS 趋同）

        Returns:
            新基因候选列表
        """
        candidates: list[GeneCandidate] = []

        # 1. 从涟漪信号检测异常
        if ripple_signals:
            for sig in ripple_signals:
                anomaly_type = self._classify_ripple_anomaly(sig)
                if anomaly_type and anomaly_type in ANOMALY_GENE_TEMPLATES:
                    cand = self._build_candidate(anomaly_type, source="ripple_anomaly")
                    if cand and cand.gene_id not in self._validated_genes:
                        candidates.append(cand)

        # 2. 从反思洞察检测失败模式
        if reflection_insights:
            for insight in reflection_insights:
                pattern = insight.get("failure_pattern", "")
                anomaly_type = self._classify_reflection_pattern(pattern)
                if anomaly_type and anomaly_type in ANOMALY_GENE_TEMPLATES:
                    cand = self._build_candidate(anomaly_type, source="reflection_pattern")
                    if cand and cand.gene_id not in self._validated_genes:
                        candidates.append(cand)

        # 3. 组合空间饱和 → 强制探索新基因
        if ftc_ess_convergence:
            for atype, template in ANOMALY_GENE_TEMPLATES.items():
                if template["gene_id"] not in self._validated_genes:
                    cand = self._build_candidate(atype, source="saturation")
                    if cand:
                        candidates.append(cand)

        # 去重
        seen = set()
        unique = []
        for c in candidates:
            if c.gene_id not in seen:
                seen.add(c.gene_id)
                unique.append(c)
                self._candidates[c.gene_id] = c

        logger.info(f"[L2-Gene] 检测到 {len(unique)} 个新基因候选")
        return unique

    def _classify_ripple_anomaly(self, signal: dict) -> Optional[str]:
        """将涟漪信号分类为异常模式"""
        try:
            vol_ratio = float(signal.get("vol_ratio", 0))
            price_change = float(signal.get("price_change_pct", 0))
            oi_change = float(signal.get("oi_change_pct", 0))
            funding = float(signal.get("funding_rate", 0))
            capital_flow = float(signal.get("capital_flow", 0))

            # 放量不涨
            if vol_ratio > 1.3 and abs(price_change) < 0.005:
                return "vol_price_divergence"
            # OI 上升但价格不涨
            if oi_change > 0.05 and abs(price_change) < 0.005:
                return "oi_price_divergence"
            # 费率+情绪极端
            if abs(funding) > 0.001:
                return "funding_sentiment_extreme"
            # 资金流入但不涨
            if capital_flow > 0.2 and abs(price_change) < 0.01:
                return "capital_inflow_no_pump"
        except (TypeError, ValueError):
            pass
        return None

    def _classify_reflection_pattern(self, pattern: str) -> Optional[str]:
        """将反思失败模式分类为异常模式"""
        p = pattern.lower()
        if "放量不涨" in p or "量价背离" in p or "vol" in p and "price" in p:
            return "vol_price_divergence"
        if "oi" in p and "背离" in p:
            return "oi_price_divergence"
        if "费率" in p or "funding" in p:
            return "funding_sentiment_extreme"
        if "资金流入" in p and "不涨" in p:
            return "capital_inflow_no_pump"
        return None

    def _build_candidate(self, anomaly_type: str, source: str) -> Optional[GeneCandidate]:
        """从模板构建基因候选"""
        template = ANOMALY_GENE_TEMPLATES.get(anomaly_type)
        if not template:
            return None
        return GeneCandidate(
            gene_id=template["gene_id"],
            gene_type="condition",
            category=template["category"],
            condition_type=template["condition_type"],
            description=template["description"],
            expression=template["expression"],
            parameters=template["parameters"],
            source=source,
            tags=template["tags"],
        )

    def validate_candidate(
        self,
        gene_id: str,
        n_samples: int,
        ess: float,
    ) -> bool:
        """
        验证基因候选是否通过 L2 门槛。

        门槛: N ≥ 100 且 ESS ≥ 0.5
        注意: 只验证不标记为已写入，写入由 write_gene_to_library 负责。
        """
        return n_samples >= L2_MIN_SAMPLES and ess >= L2_MIN_ESS

    def write_gene_to_library(self, candidate: GeneCandidate) -> bool:
        """
        将验证通过的基因写入 gene_data/strategy_genes/conditions/

        不修改冻结 API（load_gene_library 等），只写文件，
        下次 load_gene_library 会自动加载。
        """
        if candidate.gene_id in self._validated_genes:
            return False  # 已写入

        gene_data = {
            "gene_id": candidate.gene_id,
            "category": candidate.category,
            "condition_type": candidate.condition_type,
            "expression": candidate.expression,
            "parameters": candidate.parameters,
            "inverted": False,
            "weight": 1.0,
            "code_ref": {
                "file": "23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/ftc_gene_innovation.py",
                "lines": {"low": 1, "high": 1},
            },
            "tags": candidate.tags + ["l2-innovation", candidate.source],
            "version": "1.0",
            "notes": f"L2 基因创新产物，来源: {candidate.source}",
        }

        out_dir = self._gene_root / "strategy_genes" / "conditions"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{candidate.gene_id}.json"

        if out_path.exists():
            logger.info(f"[L2-Gene] {candidate.gene_id} 已存在，跳过")
            return False

        try:
            out_path.write_text(json.dumps(gene_data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._validated_genes.add(candidate.gene_id)
            logger.info(f"[L2-Gene] 新基因写入: {candidate.gene_id}")
            return True
        except Exception as e:
            logger.warning(f"[FO] L2 gene write failed: {e}")
            return False

    def get_candidates(self) -> list[GeneCandidate]:
        return list(self._candidates.values())

    def get_validated_genes(self) -> list[str]:
        return sorted(self._validated_genes)
