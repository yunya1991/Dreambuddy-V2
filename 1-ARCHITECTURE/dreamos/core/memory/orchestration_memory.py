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
    GRAPH_PATTERNS = {
        "c_chain":     ["C1", "C2", "C3"],
        "c_f_chain":   ["C1", "C2", "F1", "F3"],
        "full_chain":  ["C1", "C2", "F2", "G1"],
        "f_chain":     ["F1", "F2", "F3", "F4"],
        "c_g_chain":   ["C1", "C3", "G1"],
    }

    DEFAULT_PATTERN = "c_chain"
    DEFAULT_NODES = ["C1", "C2", "C3"]

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
        """
        parts = scenario_id.split("_")
        scenarios = self._data.get("scenarios", {})

        # L0: 精确匹配
        entry = scenarios.get(scenario_id)
        if entry and not entry.get("sparse", True) and entry.get("confidence") in ("high", "medium"):
            return OrchestrationChoice(
                pattern=entry["best_pattern"],
                nodes=entry["nodes"],
                score=entry.get("score", 0),
                confidence=entry.get("confidence", "low"),
                fallback_level="L0",
                source_scenario=scenario_id,
            )

        # L1: 趋势×波动率 (前两段)
        if len(parts) >= 2:
            prefix = f"{parts[0]}_{parts[1]}_"
            for sid, entry in scenarios.items():
                if sid.startswith(prefix) and not entry.get("sparse", True) and \
                   entry.get("confidence") in ("high", "medium"):
                    return OrchestrationChoice(
                        pattern=entry["best_pattern"],
                        nodes=entry["nodes"],
                        score=entry.get("score", 0),
                        confidence=entry.get("confidence", "low"),
                        fallback_level="L1",
                        source_scenario=sid,
                    )

        # L2: 仅趋势 (第一段)
        if len(parts) >= 1:
            prefix = f"{parts[0]}_"
            for sid, entry in scenarios.items():
                if sid.startswith(prefix) and not entry.get("sparse", True):
                    return OrchestrationChoice(
                        pattern=entry["best_pattern"],
                        nodes=entry["nodes"],
                        score=entry.get("score", 0),
                        confidence=entry.get("confidence", "low"),
                        fallback_level="L2",
                        source_scenario=sid,
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

        scenarios[scenario_id] = {
            "best_pattern": new_pattern,
            "nodes": nodes,
            "score": round(score, 4),
            "metrics": evidence.get("metrics", existing.get("metrics", {})),
            "sample_count": evidence.get("sample_count", existing.get("sample_count", 0)),
            "confidence": evidence.get("confidence", "medium"),
            "sparse": False,
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
