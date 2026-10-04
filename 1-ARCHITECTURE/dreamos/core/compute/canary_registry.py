"""
L3 自修复: 灰度与回滚 — 版本化节点注册表
=============================================
DreamOS Registry 支持版本化节点：node@1.2.3 + node@1.2.4-canary
流量按比例切分，指标对比后自动决定全量或回滚

用法:
    registry = VersionedNodeRegistry()
    registry.register_version("A1", "1.0.0", node_v1)
    registry.register_version("A1", "1.1.0-canary", node_v2, traffic_ratio=0.1)
    node = registry.select("A1")  # 90% 返回 v1, 10% 返回 v2
"""

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CanaryStatus(str, Enum):
    DRAFT = "draft"           # 未上线
    CANARY = "canary"         # 灰度中
    PROMOTED = "promoted"     # 全量上线
    ABORTED = "aborted"       # 回滚
    PENDING_DECISION = "pending_decision"  # 等待自动决策


@dataclass
class NodeVersion:
    """节点版本"""
    node_id: str
    version: str              # e.g. "1.0.0" or "1.1.0-canary"
    node: Any                 # 节点实例
    is_canary: bool = False
    traffic_ratio: float = 1.0  # 0.0~1.0
    status: CanaryStatus = CanaryStatus.PROMOTED

    # 指标收集
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0.0
    confidence_sum: float = 0.0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def record_call(self, success: bool, duration_ms: float, confidence: float = 0.0) -> None:
        with self._lock:
            self.total_calls += 1
            if success:
                self.success_count += 1
            else:
                self.failure_count += 1
            self.total_duration_ms += duration_ms
            self.confidence_sum += confidence

    @property
    def success_rate(self) -> float:
        with self._lock:
            return self.success_count / self.total_calls if self.total_calls > 0 else 0.0

    @property
    def avg_duration_ms(self) -> float:
        with self._lock:
            return self.total_duration_ms / self.total_calls if self.total_calls > 0 else 0.0

    @property
    def avg_confidence(self) -> float:
        with self._lock:
            return self.confidence_sum / self.total_calls if self.total_calls > 0 else 0.0

    @property
    def error_rate(self) -> float:
        with self._lock:
            return self.failure_count / self.total_calls if self.total_calls > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "node_id": self.node_id,
                "version": self.version,
                "is_canary": self.is_canary,
                "traffic_ratio": self.traffic_ratio,
                "status": self.status.value,
                "total_calls": self.total_calls,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "success_rate": round(self.success_rate, 4),
                "error_rate": round(self.error_rate, 4),
                "avg_duration_ms": round(self.avg_duration_ms, 2),
                "avg_confidence": round(self.avg_confidence, 4),
            }


@dataclass
class CanaryDecision:
    """灰度自动决策结果"""
    action: str  # "promote" | "rollback" | "continue" | "insufficient_data"
    reason: str
    stable_version: str
    canary_version: str
    stable_metrics: Dict[str, Any] = field(default_factory=dict)
    canary_metrics: Dict[str, Any] = field(default_factory=dict)
    decided_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "stable_version": self.stable_version,
            "canary_version": self.canary_version,
            "stable_metrics": self.stable_metrics,
            "canary_metrics": self.canary_metrics,
            "decided_at": self.decided_at,
        }


class VersionedNodeRegistry:
    """版本化节点注册表

    管理同一 node_id 的多个版本，支持灰度发布和自动回滚。

    用法:
        registry = VersionedNodeRegistry()
        # 注册稳定版
        registry.register_version("A1", "1.0.0", node_v1)
        # 注册灰度版（10% 流量）
        registry.register_version("A1", "1.1.0-canary", node_v2, traffic_ratio=0.1)
        # 选择节点（自动按流量比例分配）
        node = registry.select("A1")
        # 记录调用结果
        registry.record_result("A1", "1.1.0-canary", success=True, duration_ms=150)
        # 自动决策（灰度足够数据后）
        decision = registry.evaluate_canary("A1")
    """

    # 自动决策阈值
    MIN_SAMPLE_SIZE = 10           # 最少样本数
    MAX_ERROR_RATE_DELTA = 0.05    # 灰度版错误率不能比稳定版高 5%
    MIN_CONFIDENCE_DELTA = -0.05   # 灰度版置信度不能比稳定版低 5%
    MAX_DURATION_DELTA_RATIO = 0.2  # 灰度版耗时不能比稳定版高 20%

    def __init__(self):
        self._versions: Dict[str, Dict[str, NodeVersion]] = {}  # node_id → {version → NodeVersion}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------
    def register_version(
        self,
        node_id: str,
        version: str,
        node: Any,
        traffic_ratio: float = 1.0,
        is_canary: bool = False,
    ) -> NodeVersion:
        """注册一个节点版本"""
        with self._lock:
            if node_id not in self._versions:
                self._versions[node_id] = {}

            nv = NodeVersion(
                node_id=node_id,
                version=version,
                node=node,
                is_canary=is_canary,
                traffic_ratio=traffic_ratio,
                status=CanaryStatus.CANARY if is_canary else CanaryStatus.PROMOTED,
            )
            self._versions[node_id][version] = nv
            logger.info(f"[VersionedRegistry] 注册 {node_id}@{version} (canary={is_canary}, ratio={traffic_ratio})")
            return nv

    # ------------------------------------------------------------------
    # 选择节点（流量切分）
    # ------------------------------------------------------------------
    def select(self, node_id: str) -> Optional[Any]:
        """按流量比例选择一个版本的节点

        Returns:
            被选中版本的 node 实例，或 None 如果未注册
        """
        with self._lock:
            versions = self._versions.get(node_id)
            if not versions:
                return None

            # 过滤掉 aborted 的版本
            active = {
                v: nv for v, nv in versions.items()
                if nv.status != CanaryStatus.ABORTED
            }
            if not active:
                return None

            # 如果只有一个版本，直接返回
            if len(active) == 1:
                return list(active.values())[0].node

            # 按流量比例分配
            ratios = [nv.traffic_ratio for nv in active.values()]
            total_ratio = sum(ratios)
            if total_ratio <= 0:
                return list(active.values())[0].node

            # 归一化 + 加权随机
            r = random.random()
            cumulative = 0.0
            for nv in active.values():
                cumulative += nv.traffic_ratio / total_ratio
                if r <= cumulative:
                    return nv.node

            # 兜底
            return list(active.values())[-1].node

    # ------------------------------------------------------------------
    # 记录调用结果
    # ------------------------------------------------------------------
    def record_result(
        self,
        node_id: str,
        version: str,
        success: bool,
        duration_ms: float,
        confidence: float = 0.0,
    ) -> None:
        """记录一次节点调用的结果"""
        with self._lock:
            versions = self._versions.get(node_id)
            if not versions:
                return
            nv = versions.get(version)
            if nv:
                nv.record_call(success, duration_ms, confidence)

    # ------------------------------------------------------------------
    # 灰度评估与自动决策
    # ------------------------------------------------------------------
    def evaluate_canary(self, node_id: str) -> Optional[CanaryDecision]:
        """评估灰度版本，自动决策 promote/rollback/continue

        Returns:
            CanaryDecision 或 None（无灰度版本时）
        """
        with self._lock:
            versions = self._versions.get(node_id)
            if not versions:
                return None

            # 找到稳定版和灰度版
            stable = None
            canary = None
            for nv in versions.values():
                if nv.is_canary and nv.status == CanaryStatus.CANARY:
                    canary = nv
                elif not nv.is_canary and nv.status == CanaryStatus.PROMOTED:
                    stable = nv

            if not canary or not stable:
                return None

            # 检查样本量
            if canary.total_calls < self.MIN_SAMPLE_SIZE:
                return CanaryDecision(
                    action="insufficient_data",
                    reason=f"灰度样本不足: {canary.total_calls}/{self.MIN_SAMPLE_SIZE}",
                    stable_version=stable.version,
                    canary_version=canary.version,
                    stable_metrics=stable.to_dict(),
                    canary_metrics=canary.to_dict(),
                )

            # 比较指标
            reasons = []

            # 1. 错误率
            error_delta = canary.error_rate - stable.error_rate
            if error_delta > self.MAX_ERROR_RATE_DELTA:
                reasons.append(
                    f"错误率过高: canary={canary.error_rate:.1%} vs stable={stable.error_rate:.1%}"
                )

            # 2. 置信度
            confidence_delta = canary.avg_confidence - stable.avg_confidence
            if confidence_delta < self.MIN_CONFIDENCE_DELTA:
                reasons.append(
                    f"置信度下降: canary={canary.avg_confidence:.3f} vs stable={stable.avg_confidence:.3f}"
                )

            # 3. 耗时
            if stable.avg_duration_ms > 0:
                duration_ratio = (canary.avg_duration_ms - stable.avg_duration_ms) / stable.avg_duration_ms
                if duration_ratio > self.MAX_DURATION_DELTA_RATIO:
                    reasons.append(
                        f"耗时增加: canary={canary.avg_duration_ms:.0f}ms vs stable={stable.avg_duration_ms:.0f}ms (+{duration_ratio:.0%})"
                    )

            if reasons:
                # 回滚
                canary.status = CanaryStatus.ABORTED
                logger.warning(f"[VersionedRegistry] 回滚 {node_id}@{canary.version}: {'; '.join(reasons)}")
                return CanaryDecision(
                    action="rollback",
                    reason="; ".join(reasons),
                    stable_version=stable.version,
                    canary_version=canary.version,
                    stable_metrics=stable.to_dict(),
                    canary_metrics=canary.to_dict(),
                )
            else:
                # 全量
                canary.status = CanaryStatus.PROMOTED
                canary.is_canary = False
                canary.traffic_ratio = 1.0
                stable.status = CanaryStatus.ABORTED
                stable.traffic_ratio = 0.0
                logger.info(f"[VersionedRegistry] 全量上线 {node_id}@{canary.version}")
                return CanaryDecision(
                    action="promote",
                    reason=f"灰度指标达标: success_rate={canary.success_rate:.1%}, avg_confidence={canary.avg_confidence:.3f}",
                    stable_version=stable.version,
                    canary_version=canary.version,
                    stable_metrics=stable.to_dict(),
                    canary_metrics=canary.to_dict(),
                )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_versions(self, node_id: str) -> List[Dict[str, Any]]:
        """获取某节点的所有版本"""
        with self._lock:
            versions = self._versions.get(node_id, {})
            return [nv.to_dict() for nv in versions.values()]

    def status(self) -> Dict[str, Any]:
        """全部状态"""
        with self._lock:
            result = {}
            for node_id, versions in self._versions.items():
                result[node_id] = {
                    v: nv.to_dict() for v, nv in versions.items()
                }
            return result

    def reset_metrics(self, node_id: str, version: str = None) -> None:
        """重置指标"""
        with self._lock:
            versions = self._versions.get(node_id, {})
            if version:
                nv = versions.get(version)
                if nv:
                    nv.total_calls = 0
                    nv.success_count = 0
                    nv.failure_count = 0
                    nv.total_duration_ms = 0.0
                    nv.confidence_sum = 0.0
            else:
                for nv in versions.values():
                    nv.total_calls = 0
                    nv.success_count = 0
                    nv.failure_count = 0
                    nv.total_duration_ms = 0.0
                    nv.confidence_sum = 0.0
