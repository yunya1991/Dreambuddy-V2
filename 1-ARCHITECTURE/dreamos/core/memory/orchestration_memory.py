"""
编排记忆存储 — 场景-编排映射表

存储每种市场场景的最优编排模式，支持三级降级查询:
    L0: 精确匹配全维度 (36场景)
    L1: 降维 趋势×波动率 (12场景)
    L2: 降维 仅趋势 (3场景)
    L3: 默认 c_chain (C1→C2→C3)
"""

from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class OrchestrationChoice:
    """编排选择结果"""
    pattern: str           # "c_f_chain"
    nodes: List[str]       # ["C1", "C2", "F1", "F3"]
    score: float           # 0.78
    confidence: str        # "high" / "medium" / "low" / "default"
    fallback_level: str    # "L0" / "L1" / "L2" / "L3"
    source_scenario: str   # 实际命中的场景ID

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OrchestrationMemory:
    """编排记忆表

    用法:
        memory = OrchestrationMemory()
        memory.load()
        choice = memory.select("BULL_NORMAL_ACCELERATING")
        print(choice.pattern, choice.nodes, choice.fallback_level)
    """

    # 5种编排模式（来自 stress_test.py 第90-96行）
    # 注意: 所有 pattern 必须包含 A4(风控门禁)→A5(战术执行)→A9(离场策略),
    # 否则 A5 无法生成 trade_order, auto_trader 走降级 fallback 绕过门禁。
    # A2(策略合成) 提供策略参数, 一并加入。
    GRAPH_PATTERNS = {
        "c_chain":     ["C1", "C2", "C3", "A2", "A4", "A5", "A9"],
        "c_f_chain":   ["C1", "C2", "F1", "F3", "A2", "A4", "A5", "A9"],
        "full_chain":  ["C1", "C2", "F2", "G1", "A2", "A4", "A5", "A9"],
        "f_chain":     ["F1", "F2", "F3", "F4", "A2", "A4", "A5", "A9"],
        "c_g_chain":   ["C1", "C3", "G1", "A2", "A4", "A5", "A9"],
    }

    DEFAULT_PATTERN = "c_chain"
    DEFAULT_NODES = ["C1", "C2", "C3", "A2", "A4", "A5", "A9"]

    def __init__(self, path: Optional[str] = None):
        self.path = path or self._default_path()
        self._data = self._empty_structure()

    def _default_path(self) -> str:
        return str(Path(__file__).parent / "orchestration_memory.json")

    def _empty_structure(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "created_at": datetime.now().isoformat(),
            "last_backtest": None,
            "backtest_period": None,
            "scenarios": {},
            "fallback_chain": ["L0_exact", "L1_trend_vol", "L2_trend", "L3_default"],
            "default_pattern": self.DEFAULT_PATTERN,
            "default_nodes": self.DEFAULT_NODES,
        }

    def load(self) -> bool:
        """加载JSON记忆表

        Returns:
            True 如果文件存在并成功加载，False 如果文件不存在
        """
        if not os.path.exists(self.path):
            logger.info(f"编排记忆表不存在: {self.path}，使用空结构（运行时走L3默认）")
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            logger.info(f"编排记忆表已加载: {len(self._data.get('scenarios', {}))} 场景")
            return True
        except Exception as e:
            logger.warning(f"加载编排记忆表失败: {e}，使用空结构")
            self._data = self._empty_structure()
            return False

    def save(self) -> None:
        """写入JSON记忆表"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        logger.info(f"编排记忆表已保存: {self.path}")

    def select(self, scenario_id: str) -> OrchestrationChoice:
        """三级降级查询

        Args:
            scenario_id: 场景ID，如 "BULL_NORMAL_ACCELERATING"

        Returns:
            OrchestrationChoice: 编排选择结果

        查询策略（从精确到模糊）:
            L0: 精确匹配全维度 — 有 best_pattern 且非推断即命中
            L1: 降维 趋势×波动率 — 同趋势同波动率的最优场景
            L2: 降维 仅趋势 — 同趋势的最优场景
            L3: 默认 c_chain (C1→C2→C3)
        """
        parts = scenario_id.split("_")
        scenarios = self._data.get("scenarios", {})

        def _usable(entry: dict) -> bool:
            """判断条目是否可用于选择（有实际 best_pattern 且非纯推断）"""
            if not entry or not entry.get("best_pattern"):
                return False
            # P0-2: score=0 的模板假数据不可用（无有效回测评分）
            if entry.get("score", 0) <= 0:
                return False
            # 推断的场景（无真实回测数据）降低优先级但仍可用
            if entry.get("inferred") and entry.get("sample_count", 0) == 0:
                return False
            return True

        # L0: 精确匹配
        entry = scenarios.get(scenario_id)
        if _usable(entry):
            return OrchestrationChoice(
                pattern=entry["best_pattern"],
                nodes=self._ensure_execution_nodes(entry["nodes"]),
                score=entry.get("score", 0),
                confidence=entry.get("confidence", "low"),
                fallback_level="L0",
                source_scenario=scenario_id,
            )

        # L1: 趋势×波动率 (前两段)
        if len(parts) >= 2:
            prefix = f"{parts[0]}_{parts[1]}_"
            best_sid = None
            best_score = -1
            for sid, entry in scenarios.items():
                if sid.startswith(prefix) and _usable(entry):
                    s = entry.get("score", 0)
                    if s > best_score:
                        best_score = s
                        best_sid = sid
            if best_sid:
                entry = scenarios[best_sid]
                return OrchestrationChoice(
                    pattern=entry["best_pattern"],
                    nodes=self._ensure_execution_nodes(entry["nodes"]),
                    score=entry.get("score", 0),
                    confidence=entry.get("confidence", "low"),
                    fallback_level="L1",
                    source_scenario=best_sid,
                )

        # L2: 仅趋势 (第一段)
        if len(parts) >= 1:
            prefix = f"{parts[0]}_"
            best_sid = None
            best_score = -1
            for sid, entry in scenarios.items():
                if sid.startswith(prefix) and _usable(entry):
                    s = entry.get("score", 0)
                    if s > best_score:
                        best_score = s
                        best_sid = sid
            if best_sid:
                entry = scenarios[best_sid]
                return OrchestrationChoice(
                    pattern=entry["best_pattern"],
                    nodes=self._ensure_execution_nodes(entry["nodes"]),
                    score=entry.get("score", 0),
                    confidence=entry.get("confidence", "low"),
                    fallback_level="L2",
                    source_scenario=best_sid,
                )

        # L3: 默认
        return OrchestrationChoice(
            pattern=self.DEFAULT_PATTERN,
            nodes=list(self.DEFAULT_NODES),
            score=0.0,
            confidence="default",
            fallback_level="L3",
            source_scenario="DEFAULT",
        )

    # 执行链必备节点: A2(策略)→A4(门禁)→A5(战术执行)→A9(离场)
    # 缺失任一节点会导致无法生成 trade_order 或止损止盈记录
    EXECUTION_NODES = ["A2", "A4", "A5", "A9"]

    def _ensure_execution_nodes(self, nodes: List[str]) -> List[str]:
        """确保返回的节点列表包含执行链必备节点 (A2/A4/A5/A9)

        旧版 orchestration_memory.json 缓存了不含 A5/A9 的节点列表,
        此方法在返回前补齐, 避免每次回测后都要重新生成 JSON。
        """
        result = list(nodes)
        for nid in self.EXECUTION_NODES:
            if nid not in result:
                result.append(nid)
        return result

    def update_from_backtest(self, results: Dict[str, Any]) -> None:
        """回测结果批量更新记忆表

        Args:
            results: {scenario_id: {pattern: {score, sharpe, return, max_dd, win_rate, trades, sample_count}}}
                     以及每个scenario的最优 best_pattern
        """
        scenarios = self._data.setdefault("scenarios", {})

        for scenario_id, patterns in results.items():
            if not patterns:
                continue

            # 选得分最高的模式
            best_pattern = max(patterns.keys(), key=lambda p: patterns[p].get("score", 0))
            best = patterns[best_pattern]
            sample_count = best.get("sample_count", 0)
            score = best.get("score", 0)

            # confidence 分级
            if sample_count >= 30 and score >= 0.6:
                confidence = "high"
            elif sample_count >= 10 and score >= 0.4:
                confidence = "medium"
            else:
                confidence = "low"

            scenarios[scenario_id] = {
                "best_pattern": best_pattern,
                "nodes": self.GRAPH_PATTERNS.get(best_pattern, self.DEFAULT_NODES),
                "score": round(score, 4),
                "metrics": {
                    "sharpe": round(best.get("sharpe", 0), 4),
                    "return": round(best.get("return", 0), 4),
                    "max_dd": round(best.get("max_dd", 0), 4),
                    "win_rate": round(best.get("win_rate", 0), 4),
                },
                "sample_count": sample_count,
                "confidence": confidence,
                "sparse": sample_count < 10,
            }

        self._data["last_backtest"] = datetime.now().isoformat()
        logger.info(f"编排记忆表更新完成: {len(scenarios)} 场景")

        # 补全未覆盖场景（EXTREME 等极端场景用相似 HIGH 场景推断）
        self._fill_missing_scenarios(scenarios)
        logger.info(f"编排记忆表补全完成: {len(scenarios)} 场景")

    def _fill_missing_scenarios(self, scenarios: Dict[str, Any]) -> None:
        """为未覆盖场景用相似场景推断补全

        策略：EXTREME 场景降级参考同趋势的 HIGH 场景；
        若 HIGH 也无，降级到 NORMAL；最终兜底用 c_g_chain（含风控）。
        """
        all_sids = [
            f"{t}_{v}_{m}"
            for t in ["BULL", "BEAR", "NEUTRAL"]
            for v in ["LOW", "NORMAL", "HIGH", "EXTREME"]
            for m in ["ACCELERATING", "DECELERATING", "EXHAUSTION"]
        ]

        vol_fallback = {"EXTREME": "HIGH", "HIGH": "NORMAL", "NORMAL": "LOW", "LOW": "LOW"}

        for sid in all_sids:
            if sid in scenarios:
                continue

            # 解析场景ID: BULL_EXTREME_ACCELERATING
            parts = sid.split("_")
            trend, vol, mom = parts[0], parts[1], parts[2]

            # 逐级降级查找相似场景
            ref = None
            cur_vol = vol
            for _ in range(3):
                cur_vol = vol_fallback.get(cur_vol, "LOW")
                ref_sid = f"{trend}_{cur_vol}_{mom}"
                if ref_sid in scenarios and scenarios[ref_sid].get("sample_count", 0) > 0:
                    ref = scenarios[ref_sid]
                    break

            if ref:
                # 基于相似场景，但降低置信度并加上风控
                ref_pattern = ref.get("best_pattern", "c_g_chain")
                # EXTREME 场景强制加风控：若不含 G 节点则切换到 c_g_chain
                new_pattern = ref_pattern if "G" in ref_pattern or ref_pattern == "c_g_chain" else "c_g_chain"
                scenarios[sid] = {
                    "best_pattern": new_pattern,
                    "nodes": self.GRAPH_PATTERNS.get(new_pattern, self.GRAPH_PATTERNS["c_g_chain"]),
                    "score": round(ref.get("score", 0.5) * 0.8, 4),  # 降权
                    "metrics": ref.get("metrics", {"sharpe": 0.3, "return": 0, "max_dd": 0.2, "win_rate": 0.4}),
                    "sample_count": 0,
                    "confidence": "low",
                    "sparse": True,
                    "inferred": True,  # 标记为推断数据
                    "inferred_from": ref_sid if ref else None,
                }
            else:
                # 兜底：c_g_chain 含风控
                scenarios[sid] = {
                    "best_pattern": "c_g_chain",
                    "nodes": self.GRAPH_PATTERNS["c_g_chain"],
                    "score": 0.3,
                    "metrics": {"sharpe": 0.2, "return": 0, "max_dd": 0.3, "win_rate": 0.35},
                    "sample_count": 0,
                    "confidence": "low",
                    "sparse": True,
                    "inferred": True,
                    "inferred_from": None,
                }

    def update_from_evolution(self, scenario_id: str, new_pattern: str,
                              nodes: List[str], score: float, evidence: Dict[str, Any]) -> None:
        """进化引擎单场景更新

        Args:
            scenario_id: 场景ID
            new_pattern: 新编排模式名
            nodes: 节点列表
            score: 新评分
            evidence: 证据（回测数据等）
        """
        scenarios = self._data.setdefault("scenarios", {})
        existing = scenarios.get(scenario_id, {})

        sample_count = evidence.get("sample_count", existing.get("sample_count", 0))
        # sparse 根据样本量判断，而非硬编码 False
        is_sparse = sample_count < 10

        scenarios[scenario_id] = {
            "best_pattern": new_pattern,
            "nodes": nodes,
            "score": round(score, 4),
            "metrics": evidence.get("metrics", existing.get("metrics", {})),
            "sample_count": sample_count,
            "confidence": evidence.get("confidence", "medium"),
            "sparse": is_sparse,
            "evolved_at": datetime.now().isoformat(),
        }
        logger.info(f"场景 {scenario_id} 编排已进化更新: {new_pattern} (score={score:.4f})")

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆表统计信息"""
        scenarios = self._data.get("scenarios", {})
        total = len(scenarios)
        sparse = sum(1 for s in scenarios.values() if s.get("sparse", True))
        high_conf = sum(1 for s in scenarios.values() if s.get("confidence") == "high")
        medium_conf = sum(1 for s in scenarios.values() if s.get("confidence") == "medium")

        return {
            "total_scenarios": total,
            "covered_scenarios": total,
            "sparse_scenarios": sparse,
            "high_confidence": high_conf,
            "medium_confidence": medium_conf,
            "coverage_rate": round(total / 36, 2) if total <= 36 else 1.0,
            "sparse_rate": round(sparse / max(total, 1), 2),
            "last_backtest": self._data.get("last_backtest"),
        }

    def list_scenarios(self) -> List[Dict[str, Any]]:
        """列出所有场景"""
        scenarios = self._data.get("scenarios", {})
        return [
            {"scenario_id": sid, **info}
            for sid, info in sorted(scenarios.items())
        ]

    def get_scenario(self, scenario_id: str) -> Optional[Dict[str, Any]]:
        """获取单个场景详情"""
        return self._data.get("scenarios", {}).get(scenario_id)

    def mark_unverified(self, verified_scenario_ids: set) -> int:
        """P2-1: 将未在反馈数据中出现的场景标注为 unverified

        未验证场景的编排选择仍可用于交易（降级查询），
        但不参与进化引擎的编排优化（避免基于未验证数据修改编排）。

        Args:
            verified_scenario_ids: 已通过实验验证的场景ID集合

        Returns:
            被标注为 unverified 的场景数量
        """
        scenarios = self._data.get("scenarios", {})
        count = 0
        for sid, entry in scenarios.items():
            if sid not in verified_scenario_ids:
                old_conf = entry.get("confidence", "")
                if old_conf != "unverified":
                    entry["confidence"] = "unverified"
                    entry["verified"] = False
                    count += 1
            else:
                entry["verified"] = True

        if count > 0:
            self.save()
            logger.info(f"P2-1: {count} 个场景标注为 unverified (已验证: {len(verified_scenario_ids)})")
        return count

    def is_verified(self, scenario_id: str) -> bool:
        """P2-1: 检查场景是否已通过实验验证"""
        entry = self.get_scenario(scenario_id)
        if not entry:
            return False
        return entry.get("verified", False) and entry.get("confidence") != "unverified"

    def purge_template_data(self) -> Dict[str, int]:
        """P0-2: 清除模板填充的假数据

        识别特征:
            1. inferred=True（推断生成的，无真实回测数据）
            2. score=0（无有效回测评分，包含空模板和未评分模板）
        这些是初始化脚本批量生成的模板值，不是真实回测数据。
        清除后这些场景将走 L1/L2/L3 降级查询，比"精准命中假数据"更安全。

        Returns:
            {"purged": 被清除数量, "kept": 保留数量}
        """
        scenarios = self._data.get("scenarios", {})
        to_remove = []
        for sid, entry in scenarios.items():
            is_template = entry.get("inferred", False) or entry.get("score", 0) <= 0
            if is_template:
                to_remove.append(sid)

        for sid in to_remove:
            del scenarios[sid]

        kept = len(scenarios)
        if to_remove:
            self.save()
            logger.info(
                f"P0-2: 清除 {len(to_remove)} 条模板假数据, 保留 {kept} 条真实数据"
            )
        return {"purged": len(to_remove), "kept": kept}
