"""
L4 案例库统计适配器 — Level 1 粗筛

职责：
1. 从 L4 案例库读取交易案例（UnifiedCaseRegistry）
2. 按 regime × system_source 统计胜率、PnL
3. 桥接 L4 regime (6类) → Dream OS scenario_id (36类)
4. 提供场景→子系统推荐

数据来源：~/.workbuddy/memory_l4/cases/*.json
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("l4_stats_adapter")


# ============================================================
# 数据类型
# ============================================================

@dataclass
class SubsystemStats:
    """子系统在某个 regime 下的统计"""
    subsystem_id: str           # C_S3_TREND / C_MARTIN_V15 / A_YJ_INFER
    system_source: str         # three_screen / martin_v15 / yijing_inference
    regime: str                # trend_up / trend_down / ranging_up / ...
    total_trades: int = 0
    winning_trades: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    confidence: float = 0.0    # 基于样本量的置信度 (0-1)

    def to_dict(self) -> dict:
        return {
            "subsystem_id": self.subsystem_id,
            "system_source": self.system_source,
            "regime": self.regime,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_pnl": round(self.avg_pnl, 4),
            "total_pnl": round(self.total_pnl, 4),
            "confidence": round(self.confidence, 4),
        }


# ============================================================
# 映射表
# ============================================================

# L4 regime → Dream OS scenario_id 的 TREND 前缀
REGIME_TO_TREND: Dict[str, str] = {
    "trend_up": "BULL",
    "trend_down": "BEAR",
    "ranging_up": "NEUTRAL",
    "ranging_down": "NEUTRAL",
    "sideways": "NEUTRAL",
}

# Dream OS 子系统节点 → L4 system_source
NODE_TO_SOURCE: Dict[str, str] = {
    "C_S3_TREND": "three_screen",
    "C_MARTIN_V15": "martin_v15",
    "A_YJ_INFER": "yijing_inference",
}

# 反向映射
SOURCE_TO_NODE: Dict[str, str] = {v: k for k, v in NODE_TO_SOURCE.items()}

# 36 个标准 scenario_id
STANDARD_SCENARIOS: List[str] = []
for trend in ("BULL", "BEAR", "NEUTRAL"):
    for vol in ("HIGH", "NORMAL", "LOW"):
        for phase in ("ACCELERATING", "DECELERATING", "EXHAUSTION"):
            STANDARD_SCENARIOS.append(f"{trend}_{vol}_{phase}")


# ============================================================
# L4 案例库统计适配器
# ============================================================

class L4StatsAdapter:
    """L4 案例库统计适配器 — Level 1 粗筛

    从 L4 案例库读取真实交易案例，统计各子系统在不同场景下的表现。
    用于为 DynamicOrchestrator 提供先验权重。
    """

    # 最小样本量：低于此值的统计不可靠
    MIN_SAMPLES = 3
    # 样本量置信度饱和点：达到此样本量时置信度为 1.0
    CONFIDENCE_SATURATION = 20

    def __init__(self, cases_dir: Optional[Path] = None):
        if cases_dir is None:
            # 默认路径：<仓库根>/11-易经推理系统/.workbuddy/memory_l4/cases/
            # 以标记目录「11-易经推理系统」向上定位仓库根，兼容 Dreambuddy-V2-main 等
            # 带大小写/后缀的目录名（旧逻辑固定匹配小写 dreambuddy-v2 失败后爬到根目录）
            project_root = Path(__file__).resolve().parent
            while not (project_root / "11-易经推理系统").exists():
                if project_root.parent == project_root:
                    break
                project_root = project_root.parent
            cases_dir = project_root / "11-易经推理系统" / ".workbuddy" / "memory_l4" / "cases"
        self.cases_dir = cases_dir
        self._cache: Optional[Dict[str, Dict[str, SubsystemStats]]] = None
        self._cache_ts: float = 0

    def _load_cases(self) -> List[dict]:
        """加载所有交易案例"""
        cases = []
        if not self.cases_dir.exists():
            logger.warning(f"L4 案例库目录不存在: {self.cases_dir}")
            return cases

        for f in sorted(self.cases_dir.glob("*.json")):
            try:
                with open(f) as fp:
                    case = json.load(fp)
                # 只关心有 system_source 的交易案例
                src = case.get("system_source", "")
                if src in NODE_TO_SOURCE.values():
                    cases.append(case)
            except Exception:
                continue

        logger.info(f"L4 案例库加载: {len(cases)} 条交易案例（来自 {self.cases_dir}）")
        return cases

    def _compute_stats(self) -> Dict[str, Dict[str, SubsystemStats]]:
        """计算 regime × subsystem 统计

        Returns:
            Dict[regime, Dict[subsystem_id, SubsystemStats]]
        """
        cases = self._load_cases()
        # 按 (regime, system_source) 分组
        groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)

        for case in cases:
            src = case.get("system_source", "")
            env = case.get("environment_snapshot", {})
            regime = env.get("regime", "unknown")

            # 提取交易结果
            outcome = case.get("decision_outcome", {})
            pnl_pct = outcome.get("pnl_pct")
            is_correct = outcome.get("is_correct")

            # 也尝试 actual_outcome
            if pnl_pct is None:
                actual = case.get("actual_outcome", {})
                pnl_pct = actual.get("pnl_pct")
            if is_correct is None:
                actual = case.get("actual_outcome", {})
                is_correct = actual.get("is_correct")

            if pnl_pct is None:
                continue

            groups[(regime, src)].append({
                "pnl_pct": float(pnl_pct),
                "is_correct": bool(is_correct) if is_correct is not None else (float(pnl_pct) > 0),
            })

        # 计算统计
        result: Dict[str, Dict[str, SubsystemStats]] = defaultdict(dict)
        for (regime, source), trades in groups.items():
            subsystem_id = SOURCE_TO_NODE.get(source, source)
            total = len(trades)
            wins = sum(1 for t in trades if t["is_correct"])
            win_rate = wins / total if total > 0 else 0
            avg_pnl = sum(t["pnl_pct"] for t in trades) / total if total > 0 else 0
            total_pnl = sum(t["pnl_pct"] for t in trades)
            # 置信度：基于样本量，饱和曲线
            confidence = min(total / self.CONFIDENCE_SATURATION, 1.0)

            stats = SubsystemStats(
                subsystem_id=subsystem_id,
                system_source=source,
                regime=regime,
                total_trades=total,
                winning_trades=wins,
                win_rate=win_rate,
                avg_pnl=avg_pnl,
                total_pnl=total_pnl,
                confidence=confidence,
            )
            result[regime][subsystem_id] = stats

        # 确保所有 regime 都有所有子系统的条目（即使没有数据）
        for regime in list(REGIME_TO_TREND.keys()) + ["unknown"]:
            if regime not in result:
                result[regime] = {}
            for node_id in NODE_TO_SOURCE:
                if node_id not in result[regime]:
                    source = NODE_TO_SOURCE[node_id]
                    result[regime][node_id] = SubsystemStats(
                        subsystem_id=node_id,
                        system_source=source,
                        regime=regime,
                    )

        return dict(result)

    def get_stats(self, force_refresh: bool = False) -> Dict[str, Dict[str, SubsystemStats]]:
        """获取 regime × subsystem 统计（带缓存）

        Returns:
            Dict[regime, Dict[subsystem_id, SubsystemStats]]
        """
        import time
        now = time.time()
        if self._cache is not None and not force_refresh and (now - self._cache_ts < 300):
            return self._cache

        self._cache = self._compute_stats()
        self._cache_ts = now
        return self._cache

    def get_stats_for_scenario(self, scenario_id: str) -> Dict[str, SubsystemStats]:
        """根据 Dream OS scenario_id 获取子系统统计

        将 scenario_id (如 BULL_NORMAL_ACCELERATING) 映射到 L4 regime (如 trend_up)，
        然后返回该 regime 下的子系统统计。
        """
        stats = self.get_stats()
        trend = self._scenario_to_trend(scenario_id)
        if trend is None:
            # 无法映射，返回 unknown
            return stats.get("unknown", {})

        # 找到对应的 L4 regime
        regimes = [r for r, t in REGIME_TO_TREND.items() if t == trend]
        # 合并所有匹配 regime 的统计
        merged: Dict[str, List[SubsystemStats]] = defaultdict(list)
        for regime in regimes:
            for node_id, s in stats.get(regime, {}).items():
                merged[node_id].append(s)

        # 如果有 unknown 统计也加入（作为先验补充）
        for node_id, s in stats.get("unknown", {}).items():
            if s.total_trades > 0:
                merged[node_id].append(s)

        # 合并统计
        result: Dict[str, SubsystemStats] = {}
        for node_id, stat_list in merged.items():
            if not stat_list:
                result[node_id] = SubsystemStats(
                    subsystem_id=node_id,
                    system_source=NODE_TO_SOURCE.get(node_id, node_id),
                    regime=trend,
                )
                continue

            total = sum(s.total_trades for s in stat_list)
            wins = sum(s.winning_trades for s in stat_list)
            all_pnls = [s.avg_pnl * s.total_trades for s in stat_list if s.total_trades > 0]
            total_pnl = sum(all_pnls)
            avg_pnl = total_pnl / total if total > 0 else 0

            result[node_id] = SubsystemStats(
                subsystem_id=node_id,
                system_source=NODE_TO_SOURCE.get(node_id, node_id),
                regime=trend,
                total_trades=total,
                winning_trades=wins,
                win_rate=wins / total if total > 0 else 0,
                avg_pnl=avg_pnl,
                total_pnl=total_pnl,
                confidence=min(total / self.CONFIDENCE_SATURATION, 1.0),
            )

        return result

    def get_best_subsystem(self, scenario_id: str) -> Optional[str]:
        """获取场景下的最优子系统（基于 L4 统计）

        Returns:
            subsystem_id 或 None（数据不足时返回 None）
        """
        stats = self.get_stats_for_scenario(scenario_id)
        best_node: Optional[str] = None
        best_score = -1.0

        for node_id, s in stats.items():
            if s.total_trades < self.MIN_SAMPLES:
                continue
            # 综合评分：胜率 * 0.5 + avg_pnl 归一化 * 0.3 + 样本置信度 * 0.2
            pnl_score = max(0, min(s.avg_pnl / 5.0, 1.0))  # avg_pnl 5% 饱和
            score = s.win_rate * 0.5 + pnl_score * 0.3 + s.confidence * 0.2
            if score > best_score:
                best_score = score
                best_node = node_id

        return best_node

    def get_subsystem_weights(self, scenario_id: str) -> Dict[str, float]:
        """获取场景下各子系统的权重（0-1，归一化）

        用于 A2 节点的维度权重调整或 ChainSpec 更新。
        """
        stats = self.get_stats_for_scenario(scenario_id)
        weights: Dict[str, float] = {}

        for node_id, s in stats.items():
            if s.total_trades < self.MIN_SAMPLES:
                weights[node_id] = 0.1  # 最低保底权重
                continue
            # 综合评分
            pnl_score = max(0, min(s.avg_pnl / 5.0, 1.0))
            score = s.win_rate * 0.5 + pnl_score * 0.3 + s.confidence * 0.2
            weights[node_id] = max(score, 0.1)  # 最低 0.1

        # 归一化
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    @staticmethod
    def _scenario_to_trend(scenario_id: str) -> Optional[str]:
        """将 Dream OS scenario_id 映射到 L4 regime 的 trend 前缀

        BULL_NORMAL_ACCELERATING → BULL → trend_up
        BEAR_HIGH_EXHAUSTION → BEAR → trend_down
        NEUTRAL_LOW_DECELERATING → NEUTRAL → sideways/ranging
        """
        if not scenario_id:
            return None
        parts = scenario_id.split("_")
        if len(parts) < 1:
            return None
        trend = parts[0]
        if trend in ("BULL", "BEAR", "NEUTRAL"):
            return trend
        return None

    def summary(self) -> str:
        """生成统计摘要"""
        stats = self.get_stats()
        lines = ["L4 案例库统计摘要（Level 1 粗筛）", "=" * 50]

        total_cases = 0
        for regime in sorted(stats.keys()):
            node_stats = stats[regime]
            lines.append(f"\n[{regime}]")
            for node_id, s in node_stats.items():
                if s.total_trades > 0:
                    lines.append(
                        f"  {node_id}: {s.total_trades}笔, 胜率={s.win_rate:.1%}, "
                        f"avg_pnl={s.avg_pnl:.2f}%, 置信度={s.confidence:.0%}"
                    )
                    total_cases += s.total_trades

        lines.append(f"\n总有效案例: {total_cases}")
        if total_cases == 0:
            lines.append("⚠️ L4 案例库无有效交易案例，粗筛结果不可靠")
            lines.append("   建议：等待各子系统上报交易事件到 L4 案例库")
        elif total_cases < 50:
            lines.append("⚠️ 样本量不足，粗筛结果仅供参考")

        return "\n".join(lines)
