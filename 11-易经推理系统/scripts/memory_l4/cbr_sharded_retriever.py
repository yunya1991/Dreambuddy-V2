#!/usr/bin/env python3
"""
CBR 分片检索器 — 借鉴 Grok Build 的「子 Agent 窄 context 并行探」思想

将大案例库先按 inst_id/regime/quality 分片，各分片独立检索，再聚合排序。
支持 5 级降级检索，确保极端情况下也能返回结果。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.cbr_engine import CBRCase, CBRQuery, RetrievedCase
from scripts.memory_l4.cbr_similarity import SimilarityAggregator, build_default_case_retriever


@dataclass
class ShardSpec:
    inst_id: Optional[str] = None
    regime: Optional[str] = None
    quality: str = "high"


class ShardedCaseBase:
    def __init__(self, cases: List[CBRCase]):
        self._shards: Dict[str, List[CBRCase]] = {}
        self._build_shards(cases)

    def _build_shards(self, cases: List[CBRCase]):
        for case in cases:
            inst_id_key = case.inst_id or "_ALL_"
            regime_key = case.regime or "_ALL_"

            quality_key = "HIGH" if self._is_high_quality(case) else "LOW"

            key = f"{inst_id_key}__{regime_key}__{quality_key}"
            if key not in self._shards:
                self._shards[key] = []
            self._shards[key].append(case)

            key_inst_all = f"{inst_id_key}__ALL__ALL"
            if key_inst_all not in self._shards:
                self._shards[key_inst_all] = []
            self._shards[key_inst_all].append(case)

            key_regime_all = f"ALL__{regime_key}__ALL"
            if key_regime_all not in self._shards:
                self._shards[key_regime_all] = []
            self._shards[key_regime_all].append(case)

            key_all = "ALL__ALL__ALL"
            if key_all not in self._shards:
                self._shards[key_all] = []
            self._shards[key_all].append(case)

    @staticmethod
    def _is_high_quality(case: CBRCase) -> bool:
        return case.decision is not None and case.pnl_pct is not None

    def get_shard(self, spec: ShardSpec) -> List[CBRCase]:
        inst_key = spec.inst_id if spec.inst_id else "ALL"
        regime_key = spec.regime if spec.regime else "ALL"
        quality_key = "HIGH" if spec.quality == "high" else ("LOW" if spec.quality == "low" else "ALL")

        key = f"{inst_key}__{regime_key}__{quality_key}"
        return self._shards.get(key, [])

    def stats(self) -> Dict[str, int]:
        stats = {
            "total_cases": sum(len(cases) for cases in self._shards.values()) // 4,
            "total_shards": len(self._shards),
        }
        top_shards = sorted(
            self._shards.items(), key=lambda x: len(x[1]), reverse=True
        )[:10]
        for key, cases in top_shards:
            stats[f"shard_{key[:30]}"] = len(cases)
        return stats


class ShardedRetriever:
    REGIME_NEIGHBORS = {
        "trend_up": ["ranging_up", "sideways"],
        "trend_down": ["ranging_down", "sideways"],
        "ranging_up": ["trend_up", "sideways"],
        "ranging_down": ["trend_down", "sideways"],
        "sideways": ["trend_up", "trend_down", "ranging_up", "ranging_down"],
        "recovery|sprout": ["trend_up", "ranging_up"],
        "ranging_down": ["trend_down", "sideways"],
        "ranging_up": ["trend_up", "sideways"],
        "bull": ["trend_up", "ranging_up"],
        "bear": ["trend_down", "ranging_down"],
    }

    def __init__(
        self,
        sharded_base: ShardedCaseBase,
        retriever: Optional[SimilarityAggregator] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.1,
    ):
        self.sharded_base = sharded_base
        self.retriever = retriever or build_default_case_retriever()
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold

    def retrieve(self, query: CBRQuery) -> List[RetrievedCase]:
        qdict = query.to_feature_dict()
        all_results: List[Tuple[CBRCase, float]] = []

        plan_results = self._execute_plan_1(qdict, query)
        all_results.extend(plan_results)
        if len(all_results) >= self.top_k:
            return self._finalize_results(all_results)

        plan_results = self._execute_plan_2(qdict, query)
        all_results.extend(plan_results)
        if len(all_results) >= self.top_k:
            return self._finalize_results(all_results)

        plan_results = self._execute_plan_3(qdict, query)
        all_results.extend(plan_results)
        if len(all_results) >= self.top_k:
            return self._finalize_results(all_results)

        plan_results = self._execute_plan_4(qdict, query)
        all_results.extend(plan_results)
        if len(all_results) >= self.top_k:
            return self._finalize_results(all_results)

        plan_results = self._execute_plan_5(qdict)
        all_results.extend(plan_results)

        return self._finalize_results(all_results)

    def _execute_plan_1(self, qdict: Dict, query: CBRQuery) -> List[Tuple[CBRCase, float]]:
        spec = ShardSpec(inst_id=query.inst_id, regime=query.regime, quality="high")
        cases = self.sharded_base.get_shard(spec)
        return self._score_cases(qdict, cases)

    def _execute_plan_2(self, qdict: Dict, query: CBRQuery) -> List[Tuple[CBRCase, float]]:
        if not query.regime:
            return []
        neighbors = self.REGIME_NEIGHBORS.get(query.regime, [])
        results = []
        for neighbor in neighbors:
            spec = ShardSpec(inst_id=query.inst_id, regime=neighbor, quality="high")
            cases = self.sharded_base.get_shard(spec)
            results.extend(self._score_cases(qdict, cases))
        return results

    def _execute_plan_3(self, qdict: Dict, query: CBRQuery) -> List[Tuple[CBRCase, float]]:
        spec = ShardSpec(inst_id=None, regime=query.regime, quality="high")
        cases = self.sharded_base.get_shard(spec)
        return self._score_cases(qdict, cases)

    def _execute_plan_4(self, qdict: Dict, query: CBRQuery) -> List[Tuple[CBRCase, float]]:
        spec = ShardSpec(inst_id=query.inst_id, regime=query.regime, quality="any")
        cases = self.sharded_base.get_shard(spec)
        return self._score_cases(qdict, cases)

    def _execute_plan_5(self, qdict: Dict) -> List[Tuple[CBRCase, float]]:
        spec = ShardSpec(inst_id=None, regime=None, quality="any")
        cases = self.sharded_base.get_shard(spec)
        return self._score_cases(qdict, cases)

    def _score_cases(
        self, qdict: Dict, cases: List[CBRCase]
    ) -> List[Tuple[CBRCase, float]]:
        scored = []
        for case in cases:
            cdict = case.to_feature_dict()
            try:
                sim = self.retriever(qdict, cdict)
                if sim >= self.similarity_threshold:
                    scored.append((case, sim))
            except Exception:
                pass
        return scored

    def _finalize_results(self, all_results: List[Tuple[CBRCase, float]]) -> List[RetrievedCase]:
        case_ids = set()
        deduplicated = []
        for case, sim in all_results:
            if case.case_id not in case_ids:
                case_ids.add(case.case_id)
                deduplicated.append((case, sim))

        deduplicated.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (case, sim) in enumerate(deduplicated[: self.top_k], start=1):
            results.append(RetrievedCase(case=case, similarity=sim, rank=rank))

        return results
