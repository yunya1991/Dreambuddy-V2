"""
交易知识图谱查询与推理引擎

支持：
1. 精确查询（SPO三元组）
2. 全文搜索（FTS5）
3. 图遍历（邻居查询、路径搜索）
4. 推理规则（基于关系传递、反向推理）
5. 策略推荐（基于历史案例的策略适配）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

from scripts.memory_l4.kg_store import Entity, KGStore, Triple


@dataclass
class KGQueryResult:
    """知识图谱查询结果。"""
    triples: List[Triple]
    entities: List[Entity]
    paths: List[List[Triple]] = field(default_factory=list)
    score: float = 0.0


class KGQueryEngine:
    """交易知识图谱查询引擎。"""

    def __init__(self, kg_store: Optional[KGStore] = None):
        self.kg = kg_store or KGStore()

    # ── 基础查询 ──────────────────────────────

    def query_spo(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        obj: Optional[str] = None,
    ) -> List[Triple]:
        """SPO 三元组查询。"""
        conditions = []
        params = []
        if subject:
            conditions.append("subject = ?")
            params.append(subject)
        if predicate:
            conditions.append("predicate = ?")
            params.append(predicate)
        if obj:
            conditions.append("object = ?")
            params.append(obj)
        if not conditions:
            return []
        conditions.append("(invalid_at IS NULL OR invalid_at > CURRENT_TIMESTAMP)")
        query = "SELECT * FROM triples WHERE " + " AND ".join(conditions)
        rows = self.kg.db.execute(query, params).fetchall()
        return [self.kg._row_to_triple(r) for r in rows]

    def get_entity_by_name(self, name: str) -> Optional[Entity]:
        """按名称获取实体。"""
        return self.kg.get_entity(name)

    def list_entities(self, entity_type: Optional[str] = None) -> List[Entity]:
        """列出实体。"""
        if entity_type:
            return self.kg.list_entities_by_type(entity_type)
        rows = self.kg.db.execute("SELECT * FROM entities").fetchall()
        import json
        return [
            Entity(name=r[0], type=r[1], properties=json.loads(r[2]) if r[2] else {})
            for r in rows
        ]

    def search(self, query: str, limit: int = 20) -> KGQueryResult:
        """全文搜索。"""
        triples = self.kg.search_triples(query, limit)
        entities = []
        seen = set()
        for t in triples:
            for name in [t.subject, t.object]:
                if name and name not in seen:
                    ent = self.kg.get_entity(name)
                    if ent:
                        entities.append(ent)
                        seen.add(name)
        return KGQueryResult(triples=triples, entities=entities)

    # ── 图遍历 ──────────────────────────────

    def get_neighbors(self, entity_name: str, max_hops: int = 2) -> List[Triple]:
        """获取实体的邻居（1-N 跳）。"""
        entity = self.kg.get_entity(entity_name)
        if not entity:
            return []
        canonical = entity.name

        visited = {canonical}
        results = []
        current_nodes = [canonical]

        for _ in range(max_hops):
            next_nodes = []
            for node in current_nodes:
                # 出边
                out_triples = self.query_spo(subject=node)
                for t in out_triples:
                    if t not in results:
                        results.append(t)
                    if t.object not in visited:
                        visited.add(t.object)
                        next_nodes.append(t.object)
                # 入边
                in_triples = self.query_spo(obj=node)
                for t in in_triples:
                    if t not in results:
                        results.append(t)
                    if t.subject not in visited:
                        visited.add(t.subject)
                        next_nodes.append(t.subject)
            current_nodes = next_nodes

        return results

    def find_path(
        self,
        start: str,
        end: str,
        max_length: int = 4,
    ) -> List[List[Triple]]:
        """查找两实体间的路径。"""
        start_ent = self.kg.get_entity(start)
        end_ent = self.kg.get_entity(end)
        if not start_ent or not end_ent:
            return []

        paths: List[List[Triple]] = []
        visited = {start_ent.name}
        stack = [(start_ent.name, [])]

        while stack:
            current, path = stack.pop()
            if current == end_ent.name:
                paths.append(path)
                continue
            if len(path) >= max_length:
                continue

            triples = self.query_spo(subject=current)
            for t in triples:
                if t.object not in visited:
                    visited.add(t.object)
                    stack.append((t.object, path + [t]))

        return paths

    # ── 推理规则 ──────────────────────────────

    def infer_by_regime(self, regime: str) -> KGQueryResult:
        """基于市态推理：获取该市区下的所有案例和策略。"""
        triples = self.query_spo(predicate="has_regime", obj=regime)
        case_ids = {t.subject for t in triples}

        all_triples = []
        all_entities = []
        seen = set()

        for case_id in case_ids:
            case_triples = self.kg.get_entity_triples(case_id)
            all_triples.extend(case_triples)
            for t in case_triples:
                for name in [t.subject, t.object]:
                    if name and name not in seen:
                        ent = self.kg.get_entity(name)
                        if ent:
                            all_entities.append(ent)
                            seen.add(name)

        return KGQueryResult(triples=all_triples, entities=all_entities)

    def infer_strategy_effectiveness(self, strategy: str) -> Dict[str, Any]:
        """推理策略有效性：计算该策略的胜率和平均收益。"""
        triples = self.query_spo(predicate="uses_strategy", obj=strategy)
        case_ids = {t.subject for t in triples}

        total = 0
        profit = 0
        pnls = []

        for case_id in case_ids:
            case_ent = self.kg.get_entity(case_id)
            if case_ent and case_ent.type == "TradeCase":
                pnl_pct = case_ent.properties.get("pnl_pct")
                if pnl_pct is not None:
                    total += 1
                    if pnl_pct > 0:
                        profit += 1
                    pnls.append(pnl_pct)

        return {
            "strategy": strategy,
            "total_cases": total,
            "profit_cases": profit,
            "win_rate": round(profit / total, 3) if total > 0 else 0.0,
            "avg_pnl": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
            "max_pnl": max(pnls) if pnls else 0.0,
            "min_pnl": min(pnls) if pnls else 0.0,
        }

    def infer_best_strategy(self, regime: str) -> List[Dict[str, Any]]:
        """推理某市区下的最佳策略。"""
        regime_triples = self.query_spo(predicate="has_regime", obj=regime)
        case_ids = {t.subject for t in regime_triples}

        strategies: Dict[str, List[float]] = {}
        for case_id in case_ids:
            case_ent = self.kg.get_entity(case_id)
            if case_ent and case_ent.type == "TradeCase":
                pnl_pct = case_ent.properties.get("pnl_pct")
                sys_src = case_ent.properties.get("system_source")
                if pnl_pct is not None and sys_src:
                    if sys_src not in strategies:
                        strategies[sys_src] = []
                    strategies[sys_src].append(pnl_pct)

        results = []
        for strategy, pnls in strategies.items():
            win_rate = sum(1 for p in pnls if p > 0) / len(pnls)
            results.append({
                "strategy": strategy,
                "total_cases": len(pnls),
                "win_rate": round(win_rate, 3),
                "avg_pnl": round(sum(pnls) / len(pnls), 4),
                "regime": regime,
            })

        results.sort(key=lambda x: x["win_rate"], reverse=True)
        return results

    # ── 策略推荐 ──────────────────────────────

    def recommend_strategy(
        self,
        inst_id: Optional[str] = None,
        regime: Optional[str] = None,
        hexagram: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """基于当前条件推荐策略。

        支持模糊匹配和降级查询：
        - 优先精确匹配所有条件
        - 无结果时逐步放宽条件（先放宽hexagram，再放宽regime）
        - regime支持同义词映射（uptrend→trend_up, downtrend→trend_down等）
        """
        # regime同义词映射
        regime_aliases = {
            "uptrend": "trend_up",
            "downtrend": "trend_down",
            "trend_up": "trend_up",
            "trend_down": "trend_down",
            "ranging": "ranging",
            "neutral": "ranging",
            "breakout_up": "trend_up",
            "breakout_down": "trend_down",
            "breakout": "trend_up",
            "recovery": "recovery|sprout",
            "sprout": "recovery|sprout",
            "recovery|sprout": "recovery|sprout",
        }

        # 规范化regime
        normalized_regime = regime_aliases.get(regime.lower() if regime else "", regime)

        def _query_with_conditions(conditions: list) -> set:
            """根据条件列表查询匹配的案例集合"""
            matching_cases = None
            for pred, obj in conditions:
                triples = self.query_spo(predicate=pred, obj=obj)
                case_set = {t.subject for t in triples}
                if matching_cases is None:
                    matching_cases = case_set
                else:
                    matching_cases = matching_cases & case_set
            return matching_cases or set()

        def _build_recommendations(matching_cases: set) -> List[Dict[str, Any]]:
            """从匹配案例构建推荐结果"""
            strategies: Dict[str, Dict[str, Any]] = {}
            for case_id in matching_cases:
                case_ent = self.kg.get_entity(case_id)
                if case_ent and case_ent.type == "TradeCase":
                    sys_src = case_ent.properties.get("system_source") or "unknown"
                    pnl_pct = case_ent.properties.get("pnl_pct")
                    if pnl_pct is not None:
                        if sys_src not in strategies:
                            strategies[sys_src] = {
                                "total": 0,
                                "profit": 0,
                                "pnls": [],
                            }
                        strategies[sys_src]["total"] += 1
                        if pnl_pct > 0:
                            strategies[sys_src]["profit"] += 1
                        strategies[sys_src]["pnls"].append(pnl_pct)

            recommendations = []
            for strategy, data in strategies.items():
                win_rate = data["profit"] / data["total"] if data["total"] > 0 else 0.0
                avg_pnl = sum(data["pnls"]) / len(data["pnls"]) if data["pnls"] else 0.0
                recommendations.append({
                    "strategy": strategy,
                    "total_cases": data["total"],
                    "win_rate": round(win_rate, 3),
                    "avg_pnl": round(avg_pnl, 4),
                    "conditions": {
                        "inst_id": inst_id,
                        "regime": regime,
                        "hexagram": hexagram,
                    },
                })

            recommendations.sort(key=lambda x: x["win_rate"], reverse=True)
            return recommendations

        # 构建查询条件列表（从严格到宽松）
        query_plans = []

        # Plan 1: 全部条件精确匹配
        conditions_full = []
        if inst_id:
            conditions_full.append(("has_instrument", inst_id))
        if normalized_regime:
            conditions_full.append(("has_regime", normalized_regime))
        if hexagram:
            conditions_full.append(("has_hexagram", hexagram))
        if conditions_full:
            query_plans.append(conditions_full)

        # Plan 2: 放宽hexagram，只匹配inst_id + regime
        conditions_no_hex = []
        if inst_id:
            conditions_no_hex.append(("has_instrument", inst_id))
        if normalized_regime:
            conditions_no_hex.append(("has_regime", normalized_regime))
        if len(conditions_no_hex) >= 1 and conditions_no_hex != conditions_full:
            query_plans.append(conditions_no_hex)

        # Plan 3: 只匹配regime（放宽inst_id）
        if normalized_regime:
            query_plans.append([("has_regime", normalized_regime)])

        # Plan 4: 只匹配inst_id
        if inst_id:
            query_plans.append([("has_instrument", inst_id)])

        # Plan 5: 原始regime值重试（未映射的值）
        if regime and regime != normalized_regime:
            query_plans.append([("has_regime", regime)])

        # 依次尝试查询计划
        for plan in query_plans:
            matching_cases = _query_with_conditions(plan)
            if matching_cases:
                recommendations = _build_recommendations(matching_cases)
                if recommendations:
                    return recommendations

        return []

    def get_knowledge_summary(self) -> Dict[str, Any]:
        """获取知识图谱摘要。"""
        stats = self.kg.get_stats()

        # 获取各类型实体数量
        entity_types = ["Instrument", "Strategy", "Regime", "Hexagram", "TradeCase", "Distill", "Constraint"]
        entity_counts = {}
        for etype in entity_types:
            ents = self.kg.list_entities_by_type(etype)
            entity_counts[etype] = len(ents)

        # 获取热门策略
        strategies = self.kg.list_entities_by_type("Strategy")
        strategy_effectiveness = []
        for s in strategies:
            eff = self.infer_strategy_effectiveness(s.name)
            if eff["total_cases"] > 0:
                strategy_effectiveness.append(eff)
        strategy_effectiveness.sort(key=lambda x: x["win_rate"], reverse=True)

        return {
            "triple_count": stats["triple_count"],
            "entity_count": stats["entity_count"],
            "entity_by_type": entity_counts,
            "predicate_distribution": stats["predicate_distribution"],
            "top_strategies": strategy_effectiveness[:5],
        }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="交易知识图谱查询引擎")
    parser.add_argument("--mode", default="summary", choices=[
        "summary", "search", "neighbors", "strategy", "recommend", "regime"
    ])
    parser.add_argument("--query", default="", help="搜索查询")
    parser.add_argument("--entity", default="", help="实体名称")
    parser.add_argument("--regime", default="", help="市态")
    parser.add_argument("--strategy", default="", help="策略")
    args = parser.parse_args()

    engine = KGQueryEngine()

    if args.mode == "summary":
        summary = engine.get_knowledge_summary()
        import json
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    elif args.mode == "search":
        if not args.query:
            print("请提供 --query 参数")
            return
        result = engine.search(args.query)
        print(f"搜索结果: {len(result.triples)} 条三元组, {len(result.entities)} 个实体")
        for t in result.triples[:10]:
            print(f"  [{t.kind}] {t.subject} -[{t.predicate}]-> {t.object}")

    elif args.mode == "neighbors":
        if not args.entity:
            print("请提供 --entity 参数")
            return
        triples = engine.get_neighbors(args.entity, max_hops=2)
        print(f"{args.entity} 的邻居 ({len(triples)} 条):")
        for t in triples[:15]:
            print(f"  {t.subject} -[{t.predicate}]-> {t.object}")

    elif args.mode == "strategy":
        if not args.strategy:
            print("请提供 --strategy 参数")
            return
        eff = engine.infer_strategy_effectiveness(args.strategy)
        import json
        print(json.dumps(eff, ensure_ascii=False, indent=2))

    elif args.mode == "recommend":
        result = engine.recommend_strategy(
            inst_id=args.entity if args.entity else None,
            regime=args.regime if args.regime else None,
        )
        print(f"策略推荐 ({len(result)} 条):")
        for r in result[:5]:
            print(f"  {r['strategy']}: 胜率={r['win_rate']:.1%}, 平均收益={r['avg_pnl']:.2%}, 案例数={r['total_cases']}")

    elif args.mode == "regime":
        if not args.regime:
            print("请提供 --regime 参数")
            return
        best = engine.infer_best_strategy(args.regime)
        print(f"市态 {args.regime} 下的最佳策略:")
        for r in best[:5]:
            print(f"  {r['strategy']}: 胜率={r['win_rate']:.1%}, 平均收益={r['avg_pnl']:.2%}")


if __name__ == "__main__":
    main()
