"""
L3 自修复: Trace Replay 引擎
=============================
任何 trace_id 可重放：POST /api/ops/replay {trace_id, target_env}

用途：
  - bug 复现：重放出错 trace，验证修复后是否通过
  - 修复验证：修改代码后重放，对比事件序列差异
  - 灰度对比：同 trace_id 在新旧版本各跑一次，对比指标
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class ReplayStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MISMATCH = "mismatch"  # 重放结果与原始不匹配


class ReplayComparison(str, Enum):
    MATCH = "match"           # 事件序列完全匹配
    PARTIAL = "partial"       # 部分匹配（节点数一致但某些字段不同）
    MISMATCH = "mismatch"     # 不匹配（节点数不同或关键字段差异）
    NO_ORIGINAL = "no_original"  # 无原始事件可比


@dataclass
class ReplayEvent:
    """重放过程中的单个事件"""
    original: Optional[Dict[str, Any]] = None
    replayed: Optional[Dict[str, Any]] = None
    match: bool = False
    diff_fields: List[str] = field(default_factory=list)


@dataclass
class ReplayResult:
    """重放结果"""
    trace_id: str
    status: ReplayStatus
    comparison: ReplayComparison
    events: List[ReplayEvent] = field(default_factory=list)
    original_event_count: int = 0
    replayed_event_count: int = 0
    matched_count: int = 0
    mismatched_count: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "status": self.status.value,
            "comparison": self.comparison.value,
            "original_event_count": self.original_event_count,
            "replayed_event_count": self.replayed_event_count,
            "matched_count": self.matched_count,
            "mismatched_count": self.mismatched_count,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "events": [
                {
                    "match": e.match,
                    "diff_fields": e.diff_fields,
                    "original": e.original,
                    "replayed": e.replayed,
                }
                for e in self.events
            ],
        }


class TraceReplayEngine:
    """Trace Replay 引擎

    用法:
        engine = TraceReplayEngine(events_reader=my_reader, replayer=my_replayer)
        result = engine.replay("20260929-143022-FE-a3f9k2m1")
        if result.comparison == ReplayComparison.MATCH:
            print("修复验证通过")
    """

    # 比较时忽略的字段（这些字段天然会变）
    IGNORE_FIELDS = {"ts", "id", "span_id", "duration_ms", "parent_span_id"}

    # 比较时关注的关键字段
    KEY_FIELDS = {"system", "layer", "node", "event_type", "status"}

    def __init__(
        self,
        events_reader: Optional[Callable[[str], List[Dict]]] = None,
        replayer: Optional[Callable[[Dict], Dict]] = None,
    ):
        """
        Args:
            events_reader: 读取原始 trace 事件的函数，输入 trace_id，返回事件列表
            replayer: 重放单个事件的函数，输入原始事件，返回重放事件
        """
        self._events_reader = events_reader or self._default_events_reader
        self._replayer = replayer or self._default_replayer

    # ------------------------------------------------------------------
    # 默认实现
    # ------------------------------------------------------------------
    @staticmethod
    def _default_events_reader(trace_id: str) -> List[Dict]:
        """从 JSONL 文件读取原始事件"""
        events_root = os.environ.get(
            "WORKBUDDY_EVENTS_ROOT",
            str(Path.cwd() / "events"),
        )
        results = []
        for system in ("frontend", "dreamos", "dsh", "hub"):
            events_dir = Path(events_root) / system
            if not events_dir.exists():
                continue
            for jsonl_file in sorted(events_dir.glob("*.jsonl")):
                try:
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                                if event.get("trace_id") == trace_id:
                                    results.append(event)
                            except json.JSONDecodeError:
                                continue
                except Exception as e:
                    logger.warning(f"读取 {jsonl_file} 失败: {e}")
        # 按 ts 排序
        results.sort(key=lambda e: e.get("ts", ""))
        return results

    @staticmethod
    def _default_replayer(event: Dict) -> Dict:
        """默认重放器：仅返回原始事件（占位实现）

        实际使用时应替换为真正的重放逻辑：
        - 前端事件：重发 HTTP 请求
        - DreamOS 事件：重跑 GraphExecutor
        - DSH 事件：重调 subagent
        """
        return {**event, "replayed": True, "ts": datetime.utcnow().isoformat() + "Z"}

    # ------------------------------------------------------------------
    # 核心：重放
    # ------------------------------------------------------------------
    def replay(self, trace_id: str) -> ReplayResult:
        """重放一个 trace

        Args:
            trace_id: 要重放的 trace_id

        Returns:
            ReplayResult 包含原始/重放事件对比
        """
        start_time = time.time()
        result = ReplayResult(
            trace_id=trace_id,
            status=ReplayStatus.RUNNING,
            comparison=ReplayComparison.NO_ORIGINAL,
        )

        try:
            # 1. 读取原始事件
            original_events = self._events_reader(trace_id)
            result.original_event_count = len(original_events)

            if not original_events:
                result.status = ReplayStatus.FAILED
                result.error = f"未找到 trace_id={trace_id} 的原始事件"
                result.duration_ms = (time.time() - start_time) * 1000
                result.completed_at = datetime.utcnow().isoformat() + "Z"
                return result

            # 2. 逐事件重放
            replayed_events: List[Dict] = []
            for orig_event in original_events:
                try:
                    replayed = self._replayer(orig_event)
                    replayed_events.append(replayed)
                except Exception as e:
                    logger.warning(f"重放事件失败: {e}")
                    replayed_events.append({
                        "trace_id": trace_id,
                        "status": "fail",
                        "error": str(e),
                        "ts": datetime.utcnow().isoformat() + "Z",
                    })

            result.replayed_event_count = len(replayed_events)

            # 3. 对比
            comparison, events = self._compare_events(original_events, replayed_events)
            result.comparison = comparison
            result.events = events
            result.matched_count = sum(1 for e in events if e.match)
            result.mismatched_count = len(events) - result.matched_count

            # 4. 判定最终状态
            if comparison == ReplayComparison.MATCH:
                result.status = ReplayStatus.COMPLETED
            elif comparison == ReplayComparison.PARTIAL:
                result.status = ReplayStatus.COMPLETED
            else:
                result.status = ReplayStatus.MISMATCH

        except Exception as e:
            result.status = ReplayStatus.FAILED
            result.error = str(e)

        result.duration_ms = (time.time() - start_time) * 1000
        result.completed_at = datetime.utcnow().isoformat() + "Z"
        return result

    # ------------------------------------------------------------------
    # 事件对比
    # ------------------------------------------------------------------
    def _compare_events(
        self,
        original: List[Dict],
        replayed: List[Dict],
    ) -> Tuple[ReplayComparison, List[ReplayEvent]]:
        """对比原始和重放事件序列

        Returns:
            (comparison, events)
        """
        events: List[ReplayEvent] = []
        max_len = max(len(original), len(replayed))

        for i in range(max_len):
            orig = original[i] if i < len(original) else None
            repl = replayed[i] if i < len(replayed) else None

            if orig is None or repl is None:
                events.append(ReplayEvent(
                    original=orig,
                    replayed=repl,
                    match=False,
                    diff_fields=["missing"],
                ))
                continue

            match, diff_fields = self._compare_single_event(orig, repl)
            events.append(ReplayEvent(
                original=orig,
                replayed=repl,
                match=match,
                diff_fields=diff_fields,
            ))

        # 整体对比判定
        total = len(events)
        matched = sum(1 for e in events if e.match)

        if total == 0:
            return ReplayComparison.NO_ORIGINAL, events
        elif matched == total:
            return ReplayComparison.MATCH, events
        elif len(original) == len(replayed) and matched > 0:
            return ReplayComparison.PARTIAL, events
        else:
            return ReplayComparison.MISMATCH, events

    @classmethod
    def _compare_single_event(
        cls,
        original: Dict,
        replayed: Dict,
    ) -> Tuple[bool, List[str]]:
        """对比单个事件

        Returns:
            (is_match, diff_fields)
        """
        diff_fields = []

        # ok 和 degraded 视为兼容状态
        COMPATIBLE_STATUSES = {"ok", "degraded"}

        # 比较关键字段
        for field_name in cls.KEY_FIELDS:
            orig_val = original.get(field_name)
            repl_val = replayed.get(field_name)
            if orig_val == repl_val:
                continue
            # status 特殊处理：ok↔degraded 视为匹配
            if field_name == "status":
                if orig_val in COMPATIBLE_STATUSES and repl_val in COMPATIBLE_STATUSES:
                    continue
            diff_fields.append(field_name)

        is_match = len(diff_fields) == 0
        return is_match, diff_fields
