"""
动态编排器 — 整合 L4 粗筛 + 回测精调

职责：
1. Level 1 (L4 粗筛)：从 L4 案例库获取各子系统在不同场景下的历史表现
2. Level 2 (回测精调)：用回测引擎验证子系统节点在各场景的实际贡献
3. 整合：生成最终的 scenario_id → [subsystem_nodes] 动态映射
4. 更新 ChainSpec.scenario_nodes，替换硬编码映射

整合策略：
- L4 粗筛提供先验权重（基于真实交易历史）
- 回测精调提供实际贡献（基于回测模拟）
- 两者一致 → 高置信度启用
- 仅一方支持 → 中等置信度
- 都不支持 → 不启用
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("dynamic_orchestrator")

# 确保项目路径
_PROJECT_ROOT = Path(__file__).resolve()
while _PROJECT_ROOT.name != "1-ARCHITECTURE":
    _PROJECT_ROOT = _PROJECT_ROOT.parent
    if _PROJECT_ROOT == _PROJECT_ROOT.parent:
        break
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# 数据类型
# ============================================================

@dataclass
class SubsystemRecommendation:
    """单个场景的子系统推荐"""
    scenario_id: str
    recommended_nodes: List[str] = field(default_factory=list)
    l4_best: Optional[str] = None        # L4 粗筛最优子系统
    l4_confidence: float = 0.0           # L4 置信度
    bt_effective: bool = False           # 回测精调是否有效
    bt_score: float = 0.0                # 回测有效性评分
    final_confidence: float = 0.0        # 最终置信度
    source: str = ""                     # "l4+bt" / "l4_only" / "bt_only" / "default"

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "recommended_nodes": self.recommended_nodes,
            "l4_best": self.l4_best,
            "l4_confidence": round(self.l4_confidence, 4),
            "bt_effective": self.bt_effective,
            "bt_score": round(self.bt_score, 4),
            "final_confidence": round(self.final_confidence, 4),
            "source": self.source,
        }


# ============================================================
# 动态编排器
# ============================================================

class DynamicOrchestrator:
    """动态编排器 — L4 粗筛 + 回测精调两级优化

    用法：
        orchestrator = DynamicOrchestrator()
        orchestrator.optimize(run_backtest=True)  # 执行两级优化
        orchestrator.update_chain_spec()           # 更新 ChainSpec
        orchestrator.save_report()                 # 保存报告
    """

    # 子系统节点列表
    SUBSYSTEM_NODES = ["C_S3_TREND", "C_MARTIN_V15", "A_YJ_INFER"]

    # 36 个标准场景
    STANDARD_SCENARIOS: List[str] = []
    for _t in ("BULL", "BEAR", "NEUTRAL"):
        for _v in ("HIGH", "NORMAL", "LOW"):
            for _p in ("ACCELERATING", "DECELERATING", "EXHAUSTION"):
                STANDARD_SCENARIOS.append(f"{_t}_{_v}_{_p}")

    # 默认映射（硬编码的 fallback）
    DEFAULT_MAPPING: Dict[str, List[str]] = {
        # 趋势场景 → 三屏趋势
        **{s: ["C_S3_TREND"] for s in STANDARD_SCENARIOS if s.startswith("BULL")},
        **{s: ["C_S3_TREND"] for s in STANDARD_SCENARIOS if s.startswith("BEAR")},
        # 震荡场景 → 马丁
        **{s: ["C_MARTIN_V15"] for s in STANDARD_SCENARIOS if s.startswith("NEUTRAL") and "EXHAUSTION" not in s},
        # 衰竭场景 → 易经
        **{s: ["A_YJ_INFER"] for s in STANDARD_SCENARIOS if "EXHAUSTION" in s},
    }

    def __init__(self, l4_adapter=None, fine_tuner=None):
        if l4_adapter is not None:
            self.l4_adapter = l4_adapter
        else:
            from dreamos.capabilities.trading.evaluators.l4_stats_adapter import L4StatsAdapter
            self.l4_adapter = L4StatsAdapter()

        if fine_tuner is not None:
            self.fine_tuner = fine_tuner
        else:
            from dreamos.capabilities.trading.evaluators.backtest_fine_tuner import BacktestFineTuner
            self.fine_tuner = fine_tuner  # 延迟初始化

        self._recommendations: Optional[Dict[str, SubsystemRecommendation]] = None

    def optimize(self, run_backtest: bool = True,
                 symbols: str = "BTC", interval: str = "1h") -> Dict[str, SubsystemRecommendation]:
        """执行两级优化

        Args:
            run_backtest: 是否运行回测精调（Level 2）。如果 False，仅用 L4 粗筛。
            symbols: 回测币种
            interval: 回测周期

        Returns:
            Dict[scenario_id, SubsystemRecommendation]
        """
        logger.info("=== 动态编排器启动 ===")

        # ── Level 1: L4 粗筛 ──────────────────
        logger.info("Level 1: L4 粗筛...")
        l4_stats = self.l4_adapter.get_stats()

        # 为每个场景获取 L4 推荐
        l4_recommendations: Dict[str, Tuple[Optional[str], float]] = {}
        for scenario_id in self.STANDARD_SCENARIOS:
            best = self.l4_adapter.get_best_subsystem(scenario_id)
            weights = self.l4_adapter.get_subsystem_weights(scenario_id)
            # L4 置信度：基于最优子系统的样本量
            stats = self.l4_adapter.get_stats_for_scenario(scenario_id)
            if best and best in stats:
                l4_conf = stats[best].confidence
            else:
                l4_conf = 0.0
            l4_recommendations[scenario_id] = (best, l4_conf)

        logger.info(f"L4 粗筛完成：{sum(1 for b, c in l4_recommendations.values() if b and c > 0)} 个场景有有效推荐")

        # ── Level 2: 回测精调 ──────────────────
        bt_comparisons = {}
        if run_backtest:
            logger.info("Level 2: 回测精调...")
            if self.fine_tuner is None:
                from dreamos.capabilities.trading.evaluators.backtest_fine_tuner import BacktestFineTuner
                self.fine_tuner = BacktestFineTuner(symbols=symbols, interval=interval)

            bt_comparisons = self.fine_tuner.fine_tune()
            logger.info(f"回测精调完成：{sum(1 for c in bt_comparisons.values() if c.subsystem_effective)} 个场景有效")
        else:
            logger.info("跳过回测精调（run_backtest=False）")

        # ── 整合两级结果 ──────────────────
        recommendations: Dict[str, SubsystemRecommendation] = {}
        for scenario_id in self.STANDARD_SCENARIOS:
            rec = self._merge_results(
                scenario_id,
                l4_recommendations.get(scenario_id, (None, 0.0)),
                bt_comparisons.get(scenario_id),
            )
            recommendations[scenario_id] = rec

        self._recommendations = recommendations
        logger.info(f"动态编排完成：{len(recommendations)} 个场景已优化")
        return recommendations

    def _merge_results(self, scenario_id: str,
                       l4_result: Tuple[Optional[str], float],
                       bt_comp) -> SubsystemRecommendation:
        """整合 L4 粗筛和回测精调结果

        整合策略：
        - L4 有推荐 + 回测有效 → 用 L4 推荐的子系统，高置信度
        - L4 有推荐 + 回测无数据 → 用 L4 推荐的子系统，中等置信度
        - L4 无推荐 + 回测有效 → 用默认映射，中等置信度
        - L4 无推荐 + 回测无效 → 用默认映射，低置信度
        """
        l4_best, l4_conf = l4_result
        bt_effective = bt_comp.subsystem_effective if bt_comp else False
        bt_score = bt_comp.effectiveness_score if bt_comp else 0.0

        default_nodes = self.DEFAULT_MAPPING.get(scenario_id, [])

        if l4_best and l4_conf > 0:
            # L4 有有效推荐
            if bt_effective:
                # 回测也有效 → 高置信度
                nodes = [l4_best] if l4_best not in default_nodes else default_nodes
                confidence = min(0.5 + l4_conf * 0.3 + bt_score * 0.2, 0.95)
                source = "l4+bt"
            else:
                # 回测无数据或无效 → 中等置信度
                nodes = [l4_best] if l4_best not in default_nodes else default_nodes
                confidence = min(0.3 + l4_conf * 0.3, 0.7)
                source = "l4_only"
        else:
            # L4 无推荐
            if bt_effective:
                # 回测有效 → 用默认映射，中等置信度
                nodes = default_nodes
                confidence = min(0.4 + bt_score * 0.2, 0.7)
                source = "bt_only"
            else:
                # 都不支持 → 用默认映射
                nodes = default_nodes
                confidence = 0.3
                source = "default"

        return SubsystemRecommendation(
            scenario_id=scenario_id,
            recommended_nodes=nodes,
            l4_best=l4_best,
            l4_confidence=l4_conf,
            bt_effective=bt_effective,
            bt_score=bt_score,
            final_confidence=confidence,
            source=source,
        )

    def get_scenario_nodes_mapping(self) -> Dict[str, List[str]]:
        """获取 scenario_id → [subsystem_nodes] 映射

        用于更新 ChainSpec.scenario_nodes
        """
        if self._recommendations is None:
            self.optimize(run_backtest=False)  # 快速模式，不跑回测

        mapping: Dict[str, List[str]] = {}
        for sid, rec in self._recommendations.items():
            mapping[sid] = rec.recommended_nodes
        return mapping

    def update_chain_spec(self, chain_id: str = "A") -> int:
        """更新 ChainSpec.scenario_nodes

        将动态计算的映射写入 STANDARD_CHAINS[chain_id].scenario_nodes

        Returns:
            更新的场景数量
        """
        from dreamos.core.arrange.types import STANDARD_CHAINS

        if chain_id not in STANDARD_CHAINS:
            logger.error(f"链 {chain_id} 不存在于 STANDARD_CHAINS")
            return 0

        mapping = self.get_scenario_nodes_mapping()
        chain_spec = STANDARD_CHAINS[chain_id]

        # 备份原映射
        if not hasattr(chain_spec, '_original_scenario_nodes'):
            chain_spec._original_scenario_nodes = dict(chain_spec.scenario_nodes)

        # 更新映射
        chain_spec.scenario_nodes = mapping
        logger.info(f"ChainSpec[{chain_id}].scenario_nodes 已更新：{len(mapping)} 个场景")
        return len(mapping)

    def restore_chain_spec(self, chain_id: str = "A") -> None:
        """恢复原始 ChainSpec.scenario_nodes"""
        from dreamos.core.arrange.types import STANDARD_CHAINS

        if chain_id not in STANDARD_CHAINS:
            return

        chain_spec = STANDARD_CHAINS[chain_id]
        if hasattr(chain_spec, '_original_scenario_nodes'):
            chain_spec.scenario_nodes = chain_spec._original_scenario_nodes
            logger.info(f"ChainSpec[{chain_id}].scenario_nodes 已恢复原始映射")

    def save_report(self, path: Optional[str] = None) -> str:
        """保存优化报告"""
        if self._recommendations is None:
            return "未运行优化，请先调用 optimize()"

        if path is None:
            reports_dir = Path(__file__).parent.parent / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(reports_dir / f"dynamic_orchestration_{ts}.json")

        report = {
            "generated_at": str(__import__("datetime").datetime.now()),
            "total_scenarios": len(self._recommendations),
            "source_distribution": {},
            "recommendations": {},
        }

        for sid, rec in self._recommendations.items():
            report["recommendations"][sid] = rec.to_dict()
            report["source_distribution"][rec.source] = \
                report["source_distribution"].get(rec.source, 0) + 1

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"优化报告已保存: {path}")
        return path

    def load_cached_report(self, max_age_hours: int = 24) -> bool:
        """加载缓存的回测精调报告

        在定期运行的回测精调后，报告会保存到 reports/ 目录。
        系统启动时加载缓存报告，用回测精调结果补充 L4 粗筛。

        Args:
            max_age_hours: 缓存最大有效期（小时），超过则不加载

        Returns:
            是否成功加载
        """
        from datetime import datetime, timedelta
        reports_dir = Path(__file__).parent.parent / "reports"

        if not reports_dir.exists():
            return False

        # 找最新的动态编排报告
        reports = sorted(reports_dir.glob("dynamic_orchestration_*.json"), reverse=True)
        if not reports:
            return False

        latest = reports[0]
        try:
            with open(latest) as f:
                report = json.load(f)

            # 检查报告时效性
            generated_str = report.get("generated_at", "")
            if generated_str:
                generated = datetime.fromisoformat(generated_str.replace("Z", "+00:00"))
                if datetime.now(generated.tzinfo) - generated > timedelta(hours=max_age_hours):
                    logger.info(f"缓存报告已过期（>{max_age_hours}h），跳过加载")
                    return False

            # 用缓存报告中的回测精调结果更新推荐
            cached_recs = report.get("recommendations", {})
            if not cached_recs:
                return False

            if self._recommendations is None:
                self.optimize(run_backtest=False)

            updated = 0
            for sid, cached in cached_recs.items():
                if sid not in self._recommendations:
                    continue
                rec = self._recommendations[sid]
                # 只更新有回测数据的场景
                if cached.get("source") in ("l4+bt", "bt_only") or cached.get("bt_effective"):
                    rec.bt_effective = cached.get("bt_effective", False)
                    rec.bt_score = cached.get("bt_score", 0.0)
                    rec.recommended_nodes = cached.get("recommended_nodes", rec.recommended_nodes)
                    rec.final_confidence = cached.get("final_confidence", rec.final_confidence)
                    rec.source = cached.get("source", rec.source)
                    updated += 1

            if updated > 0:
                logger.info(f"已加载缓存报告: {latest.name}（更新 {updated} 个场景）")
                return True
            else:
                return False

        except Exception as e:
            logger.warning(f"加载缓存报告失败: {e}")
            return False

    def summary(self) -> str:
        """生成摘要"""
        if self._recommendations is None:
            return "未运行优化，请先调用 optimize()"

        lines = ["动态编排器摘要（L4 粗筛 + 回测精调）", "=" * 70]

        source_counts: Dict[str, int] = {}
        for rec in self._recommendations.values():
            source_counts[rec.source] = source_counts.get(rec.source, 0) + 1

        lines.append(f"\n来源分布:")
        for source, count in sorted(source_counts.items()):
            lines.append(f"  {source}: {count} 个场景")

        # 展示有变化的场景
        changed = [r for r in self._recommendations.values()
                    if r.source in ("l4+bt", "l4_only", "bt_only")]
        if changed:
            lines.append(f"\n动态调整的场景 ({len(changed)} 个):")
            lines.append(f"{'场景':<35} {'推荐节点':<20} {'L4最优':<15} {'L4置信':>8} {'BT有效':>8} {'来源':<10}")
            lines.append("-" * 100)
            for rec in sorted(changed, key=lambda r: r.final_confidence, reverse=True):
                nodes_str = ",".join(rec.recommended_nodes)
                l4_str = rec.l4_best or "-"
                lines.append(
                    f"{rec.scenario_id:<35} {nodes_str:<20} {l4_str:<15} "
                    f"{rec.l4_confidence:>7.0%} {'✓' if rec.bt_effective else '✗':>8} {rec.source:<10}"
                )
        else:
            lines.append("\n所有场景使用默认映射（L4 和回测均无有效数据）")

        return "\n".join(lines)
