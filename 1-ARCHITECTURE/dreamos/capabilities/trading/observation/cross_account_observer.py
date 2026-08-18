#!/usr/bin/env python3
"""
跨账户持仓观察器 — 阶段1实现

职责:
1. 复用 16-调控系统 unified_position_query 聚合持仓
2. 计算跨账户总暴露（按币种聚合净敞口）
3. 接入 ScenarioClassifier 进行场景分类
4. 检测冲突（敞口超标 + 方向极度不一致）
5. 输出观察报告（日志/文件形式）

约束:
- 完全只读，不调用任何下单接口
- 不修改任何子系统的配置或状态
- 单次执行超时 60s
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("cross_account_observer")

# 项目路径
BASE_DIR = Path(__file__).parent
while BASE_DIR.name != "dreambuddy-v2":
    BASE_DIR = BASE_DIR.parent
REGULATION_DIR = BASE_DIR / "16-调控系统"

# 导入依赖
import sys

# 添加 16-调控系统/core 到路径
_reg_core_path = str(REGULATION_DIR / "core")
if _reg_core_path not in sys.path:
    sys.path.insert(0, _reg_core_path)

try:
    from unified_position_query import fetch_all_positions, get_position_summary
    HAS_UNIFIED_QUERY = True
except ImportError as e:
    HAS_UNIFIED_QUERY = False
    logger.error(f"Failed to import unified_position_query: {e}")

# 场景分类器
_sense_path = str(BASE_DIR / "1-ARCHITECTURE" / "dreamos" / "core" / "sense")
if _sense_path not in sys.path:
    sys.path.insert(0, _sense_path)

try:
    from scenario_classifier import ScenarioClassifier, ScenarioResult
    HAS_SCENARIO_CLASSIFIER = True
except ImportError as e:
    HAS_SCENARIO_CLASSIFIER = False
    logger.warning(f"ScenarioClassifier not available: {e}")


@dataclass
class ExposureMetrics:
    """单个币种的暴露指标"""
    symbol: str
    total_long_size: float        # 总做多数量
    total_short_size: float       # 总做空数量
    net_size: float               # 净敞口 (做多-做空)
    net_direction: str            # 净方向 LONG/SHORT/NEUTRAL
    long_systems: List[str]       # 做多的系统列表
    short_systems: List[str]      # 做空的系统列表
    system_count: int             # 参与系统数
    exposure_ratio: float         # 暴露比率 (|净敞口| / 总持仓)
    conflict_detected: bool       # 是否检测到冲突


@dataclass
class ObservationReport:
    """观察报告"""
    timestamp: str
    total_systems: int
    total_positions: int
    total_unrealized_pnl: float
    overall_status: str
    system_status: Dict[str, str]
    exposures: Dict[str, Dict]           # symbol -> ExposureMetrics
    conflicts: List[Dict]
    scenario_classification: Optional[Dict]  # 场景分类结果（如果可用）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_systems": self.total_systems,
            "total_positions": self.total_positions,
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "overall_status": self.overall_status,
            "system_status": self.system_status,
            "exposures": self.exposures,
            "conflicts": self.conflicts,
            "scenario_classification": self.scenario_classification,
        }


class CrossAccountObserver:
    """跨账户持仓观察器

    用法:
        observer = CrossAccountObserver()
        report = observer.observe()
        print(json.dumps(report.to_dict(), indent=2))
    """

    # 冲突检测阈值
    EXPOSURE_THRESHOLD = 0.6      # 暴露比率超过60%视为集中风险
    CONFLICT_THRESHOLD = 0.5      # 多空系统各占50%视为方向冲突

    def __init__(self, exposure_threshold: float = None, conflict_threshold: float = None):
        """初始化观察器

        Args:
            exposure_threshold: 暴露比率阈值，超过此值视为集中风险
            conflict_threshold: 方向冲突阈值，多空系统比例超过此值视为冲突
        """
        self.exposure_threshold = exposure_threshold or self.EXPOSURE_THRESHOLD
        self.conflict_threshold = conflict_threshold or self.CONFLICT_THRESHOLD
        self.scenario_classifier = ScenarioClassifier() if HAS_SCENARIO_CLASSIFIER else None

    def observe(self) -> ObservationReport:
        """执行观察，生成报告"""
        logger.info("开始跨账户持仓观察...")

        # 1. 获取持仓数据
        if not HAS_UNIFIED_QUERY:
            logger.error("unified_position_query 不可用，无法获取持仓数据")
            return ObservationReport(
                timestamp=datetime.now(timezone.utc).isoformat(),
                total_systems=0,
                total_positions=0,
                total_unrealized_pnl=0,
                overall_status="failed",
                system_status={},
                exposures={},
                conflicts=[{"type": "system_error", "severity": "critical", "description": "unified_position_query 不可用"}],
                scenario_classification=None,
            )

        try:
            positions_data = fetch_all_positions()
        except Exception as e:
            logger.error(f"获取持仓数据失败: {e}")
            positions_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_systems": 0,
                "total_positions": 0,
                "total_unrealized_pnl": 0,
                "overall_status": "failed",
                "system_status": {},
                "systems": {},
                "all_positions": [],
            }

        # 2. 计算跨账户暴露
        exposures = self._calculate_exposures(positions_data.get("all_positions", []))

        # 3. 检测冲突
        conflicts = self._detect_conflicts(exposures)

        # 4. 场景分类（如果可用）
        scenario_result = None
        if self.scenario_classifier and positions_data.get("all_positions"):
            scenario_result = self._classify_scenario(positions_data)

        # 5. 生成报告
        report = ObservationReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_systems=positions_data.get("total_systems", 0),
            total_positions=positions_data.get("total_positions", 0),
            total_unrealized_pnl=positions_data.get("total_unrealized_pnl", 0),
            overall_status=positions_data.get("overall_status", "unknown"),
            system_status=positions_data.get("system_status", {}),
            exposures={sym: asdict(exp) for sym, exp in exposures.items()},
            conflicts=conflicts,
            scenario_classification=scenario_result,
        )

        logger.info(f"观察完成: {report.total_positions}个持仓, {len(conflicts)}个冲突")

        return report

    def _calculate_exposures(self, all_positions: List[Dict]) -> Dict[str, ExposureMetrics]:
        """计算各币种的跨账户暴露"""
        # 按币种聚合
        symbol_data = defaultdict(lambda: {
            "long_size": 0.0,
            "short_size": 0.0,
            "long_systems": set(),
            "short_systems": set(),
        })

        for pos in all_positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue

            direction = pos.get("direction", "").upper()
            size = abs(float(pos.get("size", 0)))
            system = pos.get("system", "unknown")

            if direction == "LONG":
                symbol_data[symbol]["long_size"] += size
                symbol_data[symbol]["long_systems"].add(system)
            elif direction == "SHORT":
                symbol_data[symbol]["short_size"] += size
                symbol_data[symbol]["short_systems"].add(system)

        # 计算暴露指标
        exposures = {}
        for symbol, data in symbol_data.items():
            total_size = data["long_size"] + data["short_size"]
            if total_size == 0:
                continue

            net_size = data["long_size"] - data["short_size"]
            net_direction = "NEUTRAL"
            if net_size > 0:
                net_direction = "LONG"
            elif net_size < 0:
                net_direction = "SHORT"

            exposure_ratio = abs(net_size) / total_size if total_size > 0 else 0

            # 检测方向冲突
            all_systems = data["long_systems"] | data["short_systems"]
            long_ratio = len(data["long_systems"]) / len(all_systems) if all_systems else 0
            short_ratio = len(data["short_systems"]) / len(all_systems) if all_systems else 0

            # 多空系统各占50%左右视为冲突
            conflict_detected = (
                len(data["long_systems"]) > 0 and
                len(data["short_systems"]) > 0 and
                abs(long_ratio - short_ratio) < 0.3  # 比例接近
            )

            exposures[symbol] = ExposureMetrics(
                symbol=symbol,
                total_long_size=data["long_size"],
                total_short_size=data["short_size"],
                net_size=net_size,
                net_direction=net_direction,
                long_systems=list(data["long_systems"]),
                short_systems=list(data["short_systems"]),
                system_count=len(all_systems),
                exposure_ratio=exposure_ratio,
                conflict_detected=conflict_detected,
            )

        return exposures

    def _detect_conflicts(self, exposures: Dict[str, ExposureMetrics]) -> List[Dict]:
        """检测冲突"""
        conflicts = []

        for symbol, metrics in exposures.items():
            # 冲突1: 方向极度不一致（多空同时存在且比例接近）
            if metrics.conflict_detected:
                conflicts.append({
                    "type": "direction_conflict",
                    "symbol": symbol,
                    "severity": "high",
                    "description": f"方向冲突: {len(metrics.long_systems)}个系统做多, {len(metrics.short_systems)}个系统做空",
                    "long_systems": metrics.long_systems,
                    "short_systems": metrics.short_systems,
                    "net_direction": metrics.net_direction,
                })

            # 冲突2: 暴露过度集中
            if metrics.exposure_ratio > self.exposure_threshold and metrics.system_count >= 2:
                conflicts.append({
                    "type": "concentrated_exposure",
                    "symbol": symbol,
                    "severity": "medium",
                    "description": f"暴露集中: 净敞口占比{metrics.exposure_ratio:.1%}, 涉及{metrics.system_count}个系统",
                    "exposure_ratio": metrics.exposure_ratio,
                    "net_direction": metrics.net_direction,
                    "net_size": metrics.net_size,
                })

        return conflicts

    def _classify_scenario(self, positions_data: Dict) -> Optional[Dict]:
        """场景分类（基于第一个持仓币种的市场数据）"""
        # 从第一个持仓中提取市场数据
        all_positions = positions_data.get("all_positions", [])
        if not all_positions:
            return None

        # 尝试从持仓元数据中获取市场数据
        first_pos = all_positions[0]
        meta = first_pos.get("meta", {})

        # 如果没有完整的市场数据，跳过场景分类
        required_fields = ["price", "ema20", "ema50", "change_24h", "change_4h", "change_1h", "atr_pct"]
        if not all(field in meta or field in first_pos for field in required_fields):
            logger.debug("市场数据不完整，跳过场景分类")
            return None

        try:
            market_data = {
                "price": float(first_pos.get("price", meta.get("price", 0))),
                "ema20": float(first_pos.get("ema20", meta.get("ema20", 0))),
                "ema50": float(first_pos.get("ema50", meta.get("ema50", 0))),
                "ema200": float(first_pos.get("ema200", meta.get("ema200", 0))),
                "change_24h": float(first_pos.get("change_24h", meta.get("change_24h", 0))),
                "change_4h": float(first_pos.get("change_4h", meta.get("change_4h", 0))),
                "change_1h": float(first_pos.get("change_1h", meta.get("change_1h", 0))),
                "atr_pct": float(first_pos.get("atr_pct", meta.get("atr_pct", 0.02))),
                "rsi14": float(first_pos.get("rsi14", meta.get("rsi14", 50))),
            }

            result = self.scenario_classifier.classify(market_data)
            return result.to_dict()
        except Exception as e:
            logger.warning(f"场景分类失败: {e}")
            return None


def observe_and_report(output_file: Optional[str] = None) -> ObservationReport:
    """执行观察并可选输出到文件

    Args:
        output_file: 可选输出文件路径，不指定则不保存

    Returns:
        ObservationReport: 观察报告
    """
    observer = CrossAccountObserver()
    report = observer.observe()

    # 输出到文件
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"观察报告已保存: {output_path}")

    return report


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="跨账户持仓观察器")
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出文件路径（JSON格式）"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="仅输出摘要，不包含完整持仓列表"
    )

    args = parser.parse_args()

    report = observe_and_report(args.output)

    if args.summary:
        summary = {
            "timestamp": report.timestamp,
            "total_systems": report.total_systems,
            "total_positions": report.total_positions,
            "total_unrealized_pnl": report.total_unrealized_pnl,
            "overall_status": report.overall_status,
            "system_status": report.system_status,
            "conflict_count": len(report.conflicts),
            "top_conflicts": report.conflicts[:3] if report.conflicts else [],
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()