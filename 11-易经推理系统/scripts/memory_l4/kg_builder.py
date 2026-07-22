"""
交易知识图谱构建器

从 L4 案例库中自动提取实体和关系，构建结构化交易知识图谱。

实体类型：
- Instrument: 交易币种（BTC, ETH, SOL, UNI）
- Strategy: 策略系统（yijing_inference, martin_v15, three_screen）
- Regime: 市场状态（recovery|sprout, FOMO, CONSOLIDATION）
- Hexagram: 易经卦象（水山蹇, 地水师, 天火同人）
- TradeCase: 交易案例
- Distill: 蒸馏知识
- Constraint: 约束规则

关系类型：
- has_regime: 案例处于某市态
- uses_strategy: 案例使用某策略
- has_hexagram: 案例对应某卦象
- resulted_in: 案例结果（盈利/亏损）
- learned_from: 蒸馏知识来源于案例
- confirms: 案例证实某约束
- contradicts: 案例违背某约束
- has_evidence: 案例有某证据
- recommends: 蒸馏知识推荐某策略
- warns_against: 蒸馏知识警告避免某行为
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from scripts.memory_l4.kg_store import Entity, KGStore, Triple


@dataclass
class KGExtractResult:
    """知识提取结果。"""
    entities: List[Entity]
    triples: List[Triple]
    case_count: int = 0


class KGBuilder:
    """交易知识图谱构建器。"""

    PREDICATES = {
        "has_regime": "处于市态",
        "uses_strategy": "使用策略",
        "has_hexagram": "对应卦象",
        "resulted_in": "结果为",
        "learned_from": "来源于",
        "confirms": "证实",
        "contradicts": "违背",
        "has_evidence": "有证据",
        "recommends": "推荐",
        "warns_against": "警告避免",
        "has_profit": "盈利",
        "has_loss": "亏损",
        "best_for": "最适合",
        "worst_for": "最不适合",
    }

    def __init__(self, kg_store: Optional[KGStore] = None):
        self.kg = kg_store or KGStore()

    def build_from_cases(self, case_base_path: Optional[Path] = None) -> KGExtractResult:
        """从 L4 cases 目录构建知识图谱。"""
        if case_base_path is None:
            from scripts.memory_l4.paths import memory_l4_cases_dir
            case_base_path = memory_l4_cases_dir()

        entities: List[Entity] = []
        triples: List[Triple] = []
        case_count = 0

        if not case_base_path.exists():
            return KGExtractResult(entities=entities, triples=triples)

        for p in sorted(case_base_path.glob("*.json")):
            if "_v02_backup" in p.name or not p.is_file():
                continue
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                case_ents, case_tris = self._extract_from_case(raw)
                entities.extend(case_ents)
                triples.extend(case_tris)
                case_count += 1
            except Exception:
                continue

        self._bulk_insert(entities, triples)
        return KGExtractResult(entities=entities, triples=triples, case_count=case_count)

    def build_from_distills(self, distill_path: Optional[Path] = None) -> KGExtractResult:
        """从 L4 distills 目录构建知识图谱。"""
        if distill_path is None:
            from scripts.memory_l4.paths import memory_l4_distills_dir
            distill_path = memory_l4_distills_dir()

        entities: List[Entity] = []
        triples: List[Triple] = []
        distill_count = 0

        if not distill_path.exists():
            return KGExtractResult(entities=entities, triples=triples)

        for p in sorted(distill_path.glob("*.json")):
            if not p.is_file():
                continue
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                dist_ents, dist_tris = self._extract_from_distill(raw)
                entities.extend(dist_ents)
                triples.extend(dist_tris)
                distill_count += 1
            except Exception:
                continue

        self._bulk_insert(entities, triples)
        return KGExtractResult(entities=entities, triples=triples, case_count=distill_count)

    def _extract_from_case(self, case: Dict[str, Any]) -> Tuple[List[Entity], List[Triple]]:
        """从单个案例提取实体和关系。"""
        entities: List[Entity] = []
        triples: List[Triple] = []

        case_id = case.get("case_id") or ""
        inst_id = case.get("inst_id") or ""
        decision = case.get("decision") or ""
        confidence = case.get("confidence") or 0.0
        regime = case.get("environment_snapshot", {}).get("regime") or ""
        system_source = case.get("system_source") or ""
        hexagram = case.get("hexagram") or ""
        pnl_pct = case.get("decision_outcome", {}).get("pnl_pct")
        leverage = case.get("decision_outcome", {}).get("leverage") or 1.0
        evidence_chain = case.get("evidence_chain") or {}

        # 1. 添加案例实体
        if case_id:
            entities.append(Entity(
                name=case_id,
                type="TradeCase",
                properties={
                    "inst_id": inst_id,
                    "decision": decision,
                    "confidence": confidence,
                    "regime": regime,
                    "system_source": system_source,
                    "hexagram": hexagram,
                    "pnl_pct": pnl_pct,
                    "leverage": leverage,
                },
            ))

        # 2. 添加币种实体
        if inst_id:
            entities.append(Entity(
                name=inst_id,
                type="Instrument",
                properties={"symbol": inst_id.split("-")[0] if "-" in inst_id else inst_id},
            ))

        # 3. 添加策略实体
        if system_source:
            entities.append(Entity(name=system_source, type="Strategy"))

        # 4. 添加市态实体
        if regime and regime != "unknown" and regime != "UNKNOWN":
            entities.append(Entity(name=regime, type="Regime"))

        # 5. 添加卦象实体
        if hexagram:
            entities.append(Entity(name=hexagram, type="Hexagram"))

        # 6. 添加关系三元组
        if case_id and inst_id:
            triples.append(Triple(
                subject=case_id,
                predicate="has_instrument",
                object=inst_id,
                statement=f"案例 {case_id} 交易 {inst_id}",
                kind="event",
            ))

        if case_id and system_source:
            triples.append(Triple(
                subject=case_id,
                predicate="uses_strategy",
                object=system_source,
                statement=f"案例 {case_id} 使用策略 {system_source}",
                kind="event",
            ))

        if case_id and regime and regime not in ("unknown", "UNKNOWN"):
            triples.append(Triple(
                subject=case_id,
                predicate="has_regime",
                object=regime,
                statement=f"案例 {case_id} 处于市态 {regime}",
                kind="event",
            ))

        if case_id and hexagram:
            triples.append(Triple(
                subject=case_id,
                predicate="has_hexagram",
                object=hexagram,
                statement=f"案例 {case_id} 对应卦象 {hexagram}",
                kind="event",
            ))

        # 7. 结果关系
        if case_id and pnl_pct is not None:
            result_type = "profit" if pnl_pct > 0 else "loss"
            triples.append(Triple(
                subject=case_id,
                predicate="resulted_in",
                object=result_type,
                statement=f"案例 {case_id} 结果为 {result_type} ({pnl_pct:.2%})",
                kind="event",
            ))

        # 8. evidence_chain 关系
        for ref_type, refs in evidence_chain.items():
            for ref in refs or []:
                ref_val = ref.get("ref")
                if ref_val and case_id:
                    triples.append(Triple(
                        subject=case_id,
                        predicate="has_evidence",
                        object=ref_val,
                        statement=f"案例 {case_id} 证据: {ref_type}={ref_val}",
                        kind="knowledge",
                    ))

        return entities, triples

    def _extract_from_distill(self, distill: Dict[str, Any]) -> Tuple[List[Entity], List[Triple]]:
        """从蒸馏知识提取实体和关系。"""
        entities: List[Entity] = []
        triples: List[Triple] = []

        distill_id = distill.get("distill_id") or ""
        case_id = distill.get("case_id") or ""
        summary = distill.get("summary") or ""
        lessons = distill.get("lessons") or []
        claims = distill.get("claims") or []

        # 1. 添加蒸馏实体
        if distill_id:
            entities.append(Entity(
                name=distill_id,
                type="Distill",
                properties={"summary": summary, "lessons": lessons},
            ))

        # 2. 来源于案例关系
        if distill_id and case_id:
            triples.append(Triple(
                subject=distill_id,
                predicate="learned_from",
                object=case_id,
                statement=f"蒸馏 {distill_id} 来源于案例 {case_id}",
                kind="knowledge",
            ))

        # 3. 从 lessons/claims 提取推荐和警告
        for lesson in lessons:
            lesson_str = str(lesson)
            if distill_id:
                triples.append(Triple(
                    subject=distill_id,
                    predicate="has_lesson",
                    object=lesson_str[:100],
                    statement=f"蒸馏 {distill_id} 经验: {lesson_str}",
                    kind="knowledge",
                ))

        for claim in claims:
            claim_str = str(claim.get("claim", claim)) if isinstance(claim, dict) else str(claim)
            if distill_id:
                triples.append(Triple(
                    subject=distill_id,
                    predicate="has_claim",
                    object=claim_str[:100],
                    statement=f"蒸馏 {distill_id} 主张: {claim_str}",
                    kind="knowledge",
                ))

        return entities, triples

    def _bulk_insert(self, entities: List[Entity], triples: List[Triple]) -> None:
        """批量插入实体和三元组。"""
        for ent in entities:
            self.kg.add_entity(ent)
        for tri in triples:
            self.kg.add_triple(tri)

    def build_from_constraints(self, constraints_path: Optional[Path] = None) -> KGExtractResult:
        """从 constraints 目录构建知识图谱。"""
        if constraints_path is None:
            constraints_path = Path("constraints")

        entities: List[Entity] = []
        triples: List[Triple] = []

        if not constraints_path.exists():
            return KGExtractResult(entities=entities, triples=triples)

        for p in sorted(constraints_path.rglob("*.json")):
            if not p.is_file():
                continue
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                cons_ents, cons_tris = self._extract_from_constraint(raw)
                entities.extend(cons_ents)
                triples.extend(cons_tris)
            except Exception:
                continue

        self._bulk_insert(entities, triples)
        return KGExtractResult(entities=entities, triples=triples)

    def _extract_from_constraint(self, constraint: Dict[str, Any]) -> Tuple[List[Entity], List[Triple]]:
        """从约束提取实体和关系。"""
        entities: List[Entity] = []
        triples: List[Triple] = []

        name = constraint.get("name") or ""
        constraint_type = constraint.get("type") or ""

        if name:
            entities.append(Entity(
                name=name,
                type="Constraint",
                properties={"type": constraint_type},
            ))

        return entities, triples

    def build_all(self) -> Dict[str, Any]:
        """构建完整知识图谱（cases + distills + constraints）。"""
        results = {}
        results["cases"] = self.build_from_cases()
        results["distills"] = self.build_from_distills()
        results["constraints"] = self.build_from_constraints()
        return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="交易知识图谱构建器")
    parser.add_argument("--mode", default="all", choices=["cases", "distills", "constraints", "all"])
    parser.add_argument("--rebuild", action="store_true", help="重新构建")
    args = parser.parse_args()

    builder = KGBuilder()

    if args.mode == "all":
        results = builder.build_all()
        print("构建完成:")
        for key, val in results.items():
            print(f"  {key}: {val.case_count} 个, {len(val.entities)} 实体, {len(val.triples)} 三元组")
    elif args.mode == "cases":
        result = builder.build_from_cases()
        print(f"从 cases 构建: {result.case_count} 案例, {len(result.entities)} 实体, {len(result.triples)} 三元组")
    elif args.mode == "distills":
        result = builder.build_from_distills()
        print(f"从 distills 构建: {result.case_count} 蒸馏, {len(result.entities)} 实体, {len(result.triples)} 三元组")
    elif args.mode == "constraints":
        result = builder.build_from_constraints()
        print(f"从 constraints 构建: {len(result.entities)} 实体, {len(result.triples)} 三元组")

    stats = builder.kg.get_stats()
    print(f"\n知识图谱统计:")
    print(f"  三元组总数: {stats['triple_count']}")
    print(f"  实体总数: {stats['entity_count']}")
    print(f"  类型分布: {stats['kind_distribution']}")
    print(f"  关系分布: {stats['predicate_distribution']}")


if __name__ == "__main__":
    main()
