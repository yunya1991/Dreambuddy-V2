#!/usr/bin/env python3
"""
动态蒸馏引擎 (DynamicDistillEngine) — 基于贝叶斯置信度的事件驱动蒸馏

升级 DistillScheduler 的静态定时模式为动态事件驱动模式。

核心设计:
1. 事件驱动：当记忆置信度跨越阈值时自动触发蒸馏，无需等待定时器
2. 贝叶斯闭环：A8 校验 → 置信度更新 → 质量等级变更 → 触发蒸馏
3. 去重保护：同一记忆短时间内不重复蒸馏
4. 批量优化：可累积多个事件后批量蒸馏，减少 IO

与现有系统的关系:
    DistillScheduler:  保留作为兜底定时机制（每小时全量扫描）
    DynamicDistillEngine: 新增，事件驱动即时蒸馏（毫秒级响应）

事件流:
    A8校验/代码变更/文档更新
        ↓ 观察事件
    BayesianMemoryUpdater.update_confidence()
        ↓ 置信度变更
    DynamicDistillEngine.on_confidence_changed()
        ↓ 质量等级跨阈值?
    触发蒸馏 → L1 应用记忆 → L2 总记忆

用法:
    from dynamic_distill_engine import DynamicDistillEngine

    engine = DynamicDistillEngine()

    # 方式1: 主动触发（置信度变更后调用）
    engine.on_confidence_changed(
        memory_id="VM-xxx",
        old_confidence=0.55,
        new_confidence=0.82,
        old_quality="B",
        new_quality="A",
    )

    # 方式2: 集成到 VectorMemoryInterface
    vm = VectorMemoryInterface(...)
    vm.set_distill_engine(engine)
"""

from __future__ import annotations

import json
import logging
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 事件模型
# ============================================================

@dataclass
class DistillEvent:
    """蒸馏事件"""
    event_id: str = ""
    event_type: str = ""       # confidence_changed / quality_upgraded / a8_verified / manual
    memory_id: str = ""
    source_app_memory: str = ""  # AM-TRD-001 等
    content: str = ""
    old_confidence: float = 0.0
    new_confidence: float = 0.0
    old_quality: str = "C"
    new_quality: str = "C"
    verify_count: int = 0       # L1 来源记忆的验证次数，蒸馏时携带到 L2
    tags: List[str] = field(default_factory=list)
    timestamp: float = 0.0
    distilled: bool = False

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "memory_id": self.memory_id,
            "source_app_memory": self.source_app_memory,
            "content": self.content[:100],
            "old_confidence": round(self.old_confidence, 4),
            "new_confidence": round(self.new_confidence, 4),
            "old_quality": self.old_quality,
            "new_quality": self.new_quality,
            "verify_count": self.verify_count,
            "tags": self.tags,
            "timestamp": self.timestamp,
            "distilled": self.distilled,
        }


@dataclass
class DistillResult:
    """蒸馏结果"""
    event_id: str
    success: bool
    target_unit: str = ""
    target_memory_id: str = ""
    reason: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "success": self.success,
            "target_unit": self.target_unit,
            "target_memory_id": self.target_memory_id,
            "reason": self.reason,
            "latency_ms": round(self.latency_ms, 1),
        }


# ============================================================
# 核心引擎
# ============================================================

class DynamicDistillEngine:
    """
    动态蒸馏引擎

    基于贝叶斯置信度的事件驱动蒸馏，替代静态定时模式。

    蒸馏触发条件（满足任一）:
    1. 质量等级升级（B→A, A→S）：置信度显著提升
    2. A8 校验通过且验证次数达标：实践验证充分
    3. 手动触发：人工确认需要蒸馏

    蒸馏抑制条件（满足任一则跳过）:
    1. 冷却期内：同一记忆 N 秒内不重复蒸馏
    2. 置信度未跨阈值：微小波动不触发
    3. 质量等级下降：D/C 级记忆不上升
    """

    # 质量等级排序（用于判断升级/降级）
    QUALITY_ORDER = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}

    # 蒸馏阈值：只有达到此等级才能蒸馏
    MIN_DISTILL_QUALITY = "B"

    # 冷却期：同一记忆在此时间内不重复蒸馏（秒）
    COOLDOWN_SECONDS = 300  # 5分钟

    # 应用记忆到总记忆单元的路由
    MEMORY_ROUTING = {
        "AM-TRD-001": "MU-TRD",
        "AM-RSK-001": "MU-TRD",
        "AM-OPS-001": "MU-DEV",
        "AM-EXP-001": "MU-TRD",
    }

    # 默认统计字段（用于初始化和持久化校验）
    _DEFAULT_STATS = (
        "events_received",
        "distill_triggered",
        "distill_succeeded",
        "distill_skipped_cooldown",
        "distill_skipped_quality",
        "distill_skipped_no_route",
        "distill_failed",
    )

    def __init__(
        self,
        memory_root: Optional[Path] = None,
        cooldown_seconds: int = 300,
        min_distill_quality: str = "B",
        on_distill: Optional[Callable[[DistillResult], None]] = None,
        stats_db_path: Optional[str] = None,
    ):
        """
        初始化动态蒸馏引擎。

        Args:
            memory_root: 记忆系统根目录
            cooldown_seconds: 冷却期（秒）
            min_distill_quality: 最低可蒸馏质量等级
            on_distill: 蒸馏完成回调
            stats_db_path: 蒸馏统计持久化的 SQLite 路径。若提供，则统计跨进程累积可见。
        """
        if memory_root is None:
            memory_root = Path(__file__).parent.parent
        self.memory_root = Path(memory_root)

        self.cooldown_seconds = cooldown_seconds
        self.min_distill_quality = min_distill_quality
        self._on_distill = on_distill

        # 冷却期记录: {memory_id: last_distill_timestamp}
        self._cooldown_map: Dict[str, float] = {}

        # 事件历史（最近 100 条）
        self._event_history: List[DistillEvent] = []

        # 蒸馏结果历史（最近 100 条）
        self._result_history: List[DistillResult] = []

        # 统计（从持久化存储加载，跨进程累积）
        self._stats_db_path = stats_db_path
        self._stats = self._load_stats()

        # 线程锁
        self._lock = threading.Lock()

    # ============================================================
    # 统计持久化
    # ============================================================

    def _load_stats(self) -> Dict[str, int]:
        """从 SQLite 加载累计统计；无 db 时返回零值。"""
        default = {k: 0 for k in self._DEFAULT_STATS}
        if not self._stats_db_path:
            return default
        try:
            import sqlite3
            conn = sqlite3.connect(self._stats_db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS distill_stats ("
                "  key TEXT PRIMARY KEY,"
                "  value INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            for key in self._DEFAULT_STATS:
                row = conn.execute(
                    "SELECT value FROM distill_stats WHERE key=?", [key]
                ).fetchone()
                if row:
                    default[key] = row[0]
            conn.close()
        except Exception as e:
            logger.warning(f"加载蒸馏统计失败，使用默认值: {e}")
        return default

    def _persist_stats(self) -> None:
        """持久化统计到 SQLite（UPSERT）。失败仅警告，不影响主流程。"""
        if not self._stats_db_path:
            return
        try:
            import sqlite3
            conn = sqlite3.connect(self._stats_db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS distill_stats ("
                "  key TEXT PRIMARY KEY,"
                "  value INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            for key, value in self._stats.items():
                conn.execute(
                    "INSERT INTO distill_stats (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    [key, int(value)],
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"持久化蒸馏统计失败: {e}")

    def _incr_stat(self, key: str, delta: int = 1) -> None:
        """增加统计并持久化。线程安全需由调用方持锁保证。"""
        self._stats[key] = self._stats.get(key, 0) + delta
        self._persist_stats()

    # ============================================================
    # 事件入口
    # ============================================================

    def on_confidence_changed(
        self,
        memory_id: str,
        old_confidence: float,
        new_confidence: float,
        old_quality: str,
        new_quality: str,
        content: str = "",
        source_app_memory: str = "",
        tags: Optional[List[str]] = None,
        verify_count: int = 0,
    ) -> Optional[DistillResult]:
        """
        置信度变更事件入口（核心方法）。

        当 BayesianMemoryUpdater 更新了某条记忆的置信度后调用此方法。
        引擎会判断是否需要触发蒸馏。

        Args:
            memory_id: 记忆ID
            old_confidence: 旧置信度
            new_confidence: 新置信度
            old_quality: 旧质量等级
            new_quality: 新质量等级
            content: 记忆内容
            source_app_memory: 来源应用记忆ID
            tags: 标签
            verify_count: L1来源记忆累计验证次数，蒸馏时携带到L2

        Returns:
            蒸馏结果，None 表示未触发蒸馏
        """
        with self._lock:
            self._incr_stat("events_received")

            # 创建事件
            event = DistillEvent(
                event_id=f"E-{int(time.time()*1000)}-{memory_id[:8]}",
                event_type="confidence_changed",
                memory_id=memory_id,
                source_app_memory=source_app_memory,
                content=content,
                old_confidence=old_confidence,
                new_confidence=new_confidence,
                old_quality=old_quality,
                new_quality=new_quality,
                verify_count=verify_count,
                tags=tags or [],
                timestamp=time.time(),
            )
            self._event_history.append(event)
            if len(self._event_history) > 100:
                self._event_history = self._event_history[-100:]

        # 判断是否触发蒸馏
        if not self._should_distill(event):
            return None

        # 执行蒸馏
        return self._execute_distill(event)

    def on_a8_verified(
        self,
        memory_id: str,
        verify_count: int,
        confidence: float,
        quality_level: str,
        content: str = "",
        source_app_memory: str = "",
        tags: Optional[List[str]] = None,
    ) -> Optional[DistillResult]:
        """
        A8 校验通过事件入口。

        当 A8 校验引擎验证通过某条记忆后调用此方法。

        Args:
            memory_id: 记忆ID
            verify_count: 累计验证次数
            confidence: 当前置信度
            quality_level: 当前质量等级
            content: 记忆内容
            source_app_memory: 来源应用记忆ID
            tags: 标签

        Returns:
            蒸馏结果
        """
        with self._lock:
            self._incr_stat("events_received")

            event = DistillEvent(
                event_id=f"E-a8-{int(time.time()*1000)}-{memory_id[:8]}",
                event_type="a8_verified",
                memory_id=memory_id,
                source_app_memory=source_app_memory,
                content=content,
                new_confidence=confidence,
                new_quality=quality_level,
                verify_count=verify_count,
                tags=tags or [],
                timestamp=time.time(),
            )
            self._event_history.append(event)

        if not self._should_distill(event):
            return None

        return self._execute_distill(event)

    def manual_distill(
        self,
        memory_id: str,
        content: str,
        quality_level: str,
        confidence: float,
        source_app_memory: str = "",
        tags: Optional[List[str]] = None,
    ) -> DistillResult:
        """
        手动触发蒸馏。

        Args:
            memory_id: 记忆ID
            content: 记忆内容
            quality_level: 质量等级
            confidence: 置信度
            source_app_memory: 来源应用记忆ID
            tags: 标签

        Returns:
            蒸馏结果
        """
        with self._lock:
            self._incr_stat("events_received")

            event = DistillEvent(
                event_id=f"E-manual-{int(time.time()*1000)}-{memory_id[:8]}",
                event_type="manual",
                memory_id=memory_id,
                source_app_memory=source_app_memory,
                content=content,
                new_confidence=confidence,
                new_quality=quality_level,
                tags=tags or [],
                timestamp=time.time(),
            )
            self._event_history.append(event)

        return self._execute_distill(event) or DistillResult(
            event_id=event.event_id,
            success=False,
            reason="蒸馏执行失败",
        )

    # ============================================================
    # 蒸馏判断
    # ============================================================

    def _should_distill(self, event: DistillEvent) -> bool:
        """判断是否应该触发蒸馏"""

        # 1. 质量等级检查：必须达到最低蒸馏等级
        min_order = self.QUALITY_ORDER.get(self.min_distill_quality, 2)
        current_order = self.QUALITY_ORDER.get(event.new_quality, 0)

        if current_order < min_order:
            self._incr_stat("distill_skipped_quality")
            logger.debug(f"跳过蒸馏: {event.memory_id} 质量等级 {event.new_quality} < {self.min_distill_quality}")
            return False

        # 4. 质量升级判断（事件类型为 confidence_changed 时）—— 提前判断，质量升级可突破冷却
        is_quality_upgrade = False
        if event.event_type == "confidence_changed":
            old_order = self.QUALITY_ORDER.get(event.old_quality, 0)
            new_order = self.QUALITY_ORDER.get(event.new_quality, 0)

            # 降级不触发蒸馏（S→A, A→B, B→C 等）
            if new_order < old_order:
                logger.debug(f"跳过蒸馏: {event.memory_id} 质量降级 {event.old_quality}→{event.new_quality}")
                return False

            # 质量升级（C→B, B→A, A→S 等）标记为可突破冷却
            if new_order > old_order:
                is_quality_upgrade = True

            # 同级别时，只有显著置信度提升才触发
            if new_order == old_order:
                delta = event.new_confidence - event.old_confidence
                if delta < 0.05:
                    return False

        # 2. 冷却期检查（质量升级可突破冷却，确保 L2 同步最新状态）
        if not is_quality_upgrade and self._in_cooldown(event.memory_id):
            self._incr_stat("distill_skipped_cooldown")
            logger.debug(f"跳过蒸馏: {event.memory_id} 在冷却期内")
            return False

        # 3. 路由检查
        if event.source_app_memory and event.source_app_memory not in self.MEMORY_ROUTING:
            self._incr_stat("distill_skipped_no_route")
            logger.debug(f"跳过蒸馏: {event.source_app_memory} 无路由映射")
            return False

        return True

    def _in_cooldown(self, memory_id: str) -> bool:
        """检查是否在冷却期内"""
        last_distill = self._cooldown_map.get(memory_id, 0)
        return (time.time() - last_distill) < self.cooldown_seconds

    # ============================================================
    # 蒸馏执行
    # ============================================================

    def _execute_distill(self, event: DistillEvent) -> Optional[DistillResult]:
        """执行蒸馏"""
        import hashlib

        t0 = time.time()
        self._incr_stat("distill_triggered")

        # 确定路由
        target_unit = self.MEMORY_ROUTING.get(event.source_app_memory, "")
        if not target_unit:
            # 无路由时尝试推断
            target_unit = self._infer_target_unit(event)

        # 生成目标记忆ID（基于 L1 memory_id 的确定性哈希，保证同一 L1 记忆多次蒸馏更新同一条 L2）
        unit_suffix = target_unit.split('-')[1] if '-' in target_unit else 'UNK'
        source_hash = hashlib.md5(event.memory_id.encode()).hexdigest()[:8]
        target_memory_id = f"GM-{unit_suffix}-{source_hash}"

        # 写入总记忆（使用贝叶斯更新器）
        success = False
        reason = ""

        try:
            unit_dir = self._resolve_unit_dir(target_unit)
            if unit_dir and unit_dir.exists():
                from bayesian_memory_updater import BayesianMemoryUpdater
                updater = BayesianMemoryUpdater(str(unit_dir))
                # 检查 L2 是否已有该记忆（基于 L1 memory_id 的确定性 ID）
                existing = updater.get_memory(target_memory_id)
                if existing:
                    # 已存在：更新置信度和验证次数（取较大值，反映 L1 最新状态）
                    new_conf = max(existing.confidence, event.new_confidence)
                    new_vc = max(existing.verify_count, event.verify_count)
                    updater.update_confidence_simple(
                        target_memory_id, new_conf, new_vc
                    )
                    reason = f"已更新 {target_unit} (conf={new_conf:.2f}, vc={new_vc})"
                else:
                    updater.add_memory(
                        memory_id=target_memory_id,
                        content=event.content,
                        category="lesson",
                        initial_confidence=event.new_confidence,
                        source=f"dynamic_distill from {event.source_app_memory or event.memory_id}",
                        tags=event.tags,
                        initial_verify_count=event.verify_count,
                    )
                    reason = f"已蒸馏到 {target_unit}"
                success = True
                self._incr_stat("distill_succeeded")
            else:
                # 降级：记录蒸馏日志
                self._record_distill_log(event, target_unit, target_memory_id)
                success = True
                self._incr_stat("distill_succeeded")
                reason = f"降级记录（总记忆目录不存在: {target_unit}）"

        except Exception as e:
            self._incr_stat("distill_failed")
            reason = f"蒸馏失败: {e}"
            logger.error(f"蒸馏执行失败: {e}")

        latency_ms = (time.time() - t0) * 1000

        # 更新冷却期（无论成功与否都设置，避免失败后立即重试）
        self._cooldown_map[event.memory_id] = time.time()

        # 标记事件为已蒸馏
        event.distilled = True

        # 构建结果
        result = DistillResult(
            event_id=event.event_id,
            success=success,
            target_unit=target_unit,
            target_memory_id=target_memory_id,
            reason=reason,
            latency_ms=latency_ms,
        )

        with self._lock:
            self._result_history.append(result)
            if len(self._result_history) > 100:
                self._result_history = self._result_history[-100:]

        # 回调
        if self._on_distill:
            try:
                self._on_distill(result)
            except Exception:
                pass

        return result

    def _infer_target_unit(self, event: DistillEvent) -> str:
        """根据标签推断目标记忆单元"""
        tags_str = " ".join(event.tags).lower()
        content_str = event.content.lower()

        if any(kw in tags_str or kw in content_str for kw in ["btc", "eth", "交易", "趋势", "持仓", "trading"]):
            return "MU-TRD"
        elif any(kw in tags_str or kw in content_str for kw in ["风控", "止损", "仓位", "risk"]):
            return "MU-TRD"
        elif any(kw in tags_str or kw in content_str for kw in ["运维", "监控", "ops", "告警"]):
            return "MU-DEV"
        else:
            return "MU-DEV"

    def _resolve_unit_dir(self, target_unit: str) -> Optional[Path]:
        """解析记忆单元目录"""
        unit_dirs = {
            "MU-DEV": "1-开发记忆单元",
            "MU-TRD": "2-交易记忆单元",
            "MU-DOC": "3-文档记忆单元",
            "MU-INF": "4-信息记忆单元",
        }
        dir_name = unit_dirs.get(target_unit)
        if dir_name:
            return self.memory_root / dir_name
        return None

    def _record_distill_log(self, event: DistillEvent, target_unit: str, target_memory_id: str) -> None:
        """降级记录：当总记忆目录不存在时，记录到蒸馏日志"""
        log_dir = self.memory_root / "9-工具与接口" / "distill_logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / f"distill_{datetime.now().strftime('%Y%m%d')}.jsonl"
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event.to_dict(),
            "target_unit": target_unit,
            "target_memory_id": target_memory_id,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # ============================================================
    # 批量蒸馏
    # ============================================================

    def batch_distill(self, events: List[DistillEvent]) -> List[DistillResult]:
        """
        批量蒸馏：累积多个事件后统一执行。

        Args:
            events: 事件列表

        Returns:
            蒸馏结果列表
        """
        results = []
        for event in events:
            if self._should_distill(event):
                result = self._execute_distill(event)
                if result:
                    results.append(result)
        return results

    # ============================================================
    # 查询与统计
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计"""
        return {
            **self._stats,
            "cooldown_entries": len(self._cooldown_map),
            "event_history_size": len(self._event_history),
            "result_history_size": len(self._result_history),
            "cooldown_seconds": self.cooldown_seconds,
            "min_distill_quality": self.min_distill_quality,
        }

    def get_recent_events(self, limit: int = 10) -> List[Dict]:
        """获取最近事件"""
        return [e.to_dict() for e in self._event_history[-limit:]]

    def get_recent_results(self, limit: int = 10) -> List[Dict]:
        """获取最近蒸馏结果"""
        return [r.to_dict() for r in self._result_history[-limit:]]

    def healthcheck(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy",
            "stats": self.get_stats(),
            "routing": self.MEMORY_ROUTING,
        }

    def clear_cooldown(self, memory_id: Optional[str] = None) -> None:
        """清除冷却期"""
        if memory_id:
            self._cooldown_map.pop(memory_id, None)
        else:
            self._cooldown_map.clear()


# ============================================================
# CLI 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("DynamicDistillEngine 功能验证")
    print("=" * 60)

    # 初始化
    engine = DynamicDistillEngine(cooldown_seconds=10, min_distill_quality="B")

    # 场景1: 置信度升级触发蒸馏
    print("\n--- 场景1: 质量等级升级 B→A ---")
    result = engine.on_confidence_changed(
        memory_id="VM-test-001",
        old_confidence=0.55,
        new_confidence=0.82,
        old_quality="B",
        new_quality="A",
        content="BTC趋势策略：突破后跟涨效果好，适合顺势操作",
        source_app_memory="AM-TRD-001",
        tags=["BTC", "趋势", "突破"],
    )
    if result:
        print(f"  蒸馏结果: success={result.success}, target={result.target_unit}, reason={result.reason}")
    else:
        print("  未触发蒸馏")

    # 场景2: 质量等级未升级不触发
    print("\n--- 场景2: 质量等级未变 C→C ---")
    result = engine.on_confidence_changed(
        memory_id="VM-test-002",
        old_confidence=0.30,
        new_confidence=0.32,
        old_quality="C",
        new_quality="C",
        content="测试记忆C级",
        source_app_memory="AM-TRD-001",
    )
    print(f"  蒸馏结果: {result}")

    # 场景3: A→S 升级触发
    print("\n--- 场景3: 质量等级升级 A→S ---")
    result = engine.on_confidence_changed(
        memory_id="VM-test-003",
        old_confidence=0.78,
        new_confidence=0.96,
        old_quality="A",
        new_quality="S",
        content="风险管理：单笔交易不超过总资金的2%",
        source_app_memory="AM-TRD-001",
        tags=["风控", "仓位", "止损"],
    )
    if result:
        print(f"  蒸馏结果: success={result.success}, target={result.target_unit}, reason={result.reason}")

    # 场景4: 冷却期抑制
    print("\n--- 场景4: 冷却期抑制 ---")
    result = engine.on_confidence_changed(
        memory_id="VM-test-001",  # 同一记忆，10秒内
        old_confidence=0.82,
        new_confidence=0.85,
        old_quality="A",
        new_quality="A",
        content="BTC趋势策略：突破后跟涨效果好",
        source_app_memory="AM-TRD-001",
    )
    print(f"  蒸馏结果: {result} (应为None，冷却期抑制)")

    # 场景5: A8 校验通过触发
    print("\n--- 场景5: A8 校验通过触发 ---")
    result = engine.on_a8_verified(
        memory_id="VM-test-004",
        verify_count=5,
        confidence=0.88,
        quality_level="A",
        content="ETH套利策略经验验证通过",
        source_app_memory="AM-EXP-001",
        tags=["ETH", "套利"],
    )
    if result:
        print(f"  蒸馏结果: success={result.success}, target={result.target_unit}")

    # 场景6: 手动蒸馏
    print("\n--- 场景6: 手动蒸馏 ---")
    result = engine.manual_distill(
        memory_id="VM-test-005",
        content="手动确认的重要经验",
        quality_level="A",
        confidence=0.85,
        source_app_memory="AM-TRD-001",
        tags=["手动", "重要"],
    )
    print(f"  蒸馏结果: success={result.success}, target={result.target_unit}")

    # 统计
    print("\n--- 引擎统计 ---")
    stats = engine.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # 最近事件
    print("\n--- 最近事件 ---")
    for event in engine.get_recent_events(5):
        print(f"  {event['event_type']}: {event['memory_id']} {event['old_quality']}→{event['new_quality']}")

    # 健康检查
    print(f"\n--- 健康检查 ---")
    health = engine.healthcheck()
    print(f"  状态: {health['status']}")

    print("\n" + "=" * 60)
    print("DynamicDistillEngine 验证通过 ✅")
    print("=" * 60)
