"""
L4 自迭代: hermes 反思自动化
=============================
每日 cron 分析 24h trace/bug/修复 → 决策树 → skill-creator 触发

决策树 (来自 CLAUDE.md hermes 反思决策树):
    本次流程是否值得形成/衍生 SKILL？
    ├── 是（满足以下任一）：
    │   ├── 流程被复用 ≥ 2 次
    │   ├── 涉及多步编排（≥ 3 步）
    │   ├── 涉及 bsk 自动化（≥ 1 步）
    │   └── 用户明确要求「形成 SKILL」
    │   → 调用 skill-creator 创建新 SKILL
    │   → record 经验，tags 含「SKILL,hermes反思」
    └── 否 → 仅 record 经验，tags 不含「SKILL」

用法:
    reflector = HermesReflector(
        events_root="/path/to/events",
        recall_fn=cognitive_recall,
        record_fn=cognitive_record,
    )
    report = reflector.reflect()  # 执行一次反思
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 决策阈值 (来自 CLAUDE.md) ────────────────────────────
SKILL_REUSE_THRESHOLD = 2       # 流程被复用 ≥ 2 次
SKILL_MULTI_STEP_THRESHOLD = 3  # 涉及多步编排 ≥ 3 步
SKILL_BSK_STEP_THRESHOLD = 1    # 涉及 bsk 自动化 ≥ 1 步


class ReflectionAction(str, Enum):
    """反思后执行的动作"""
    CREATE_SKILL = "create_skill"    # 创建新 SKILL
    RECORD_ONLY = "record_only"     # 仅记录经验
    NO_ACTION = "no_action"          # 无可记录内容


class TracePattern(str, Enum):
    """trace 分析识别的模式"""
    REPEATED_FLOW = "repeated_flow"          # 流程被复用
    MULTI_STEP = "multi_step"                # 多步编排
    BSK_AUTOMATION = "bsk_automation"        # bsk 自动化
    ERROR_FIX_CYCLE = "error_fix_cycle"      # 错误-修复循环
    SINGLE_OCCURRENCE = "single_occurrence"  # 单次发生


@dataclass
class TraceAnalysis:
    """24h trace 分析结果"""
    total_events: int = 0
    total_traces: int = 0
    error_events: int = 0
    fix_events: int = 0
    patterns: List[TracePattern] = field(default_factory=list)
    repeated_flows: Dict[str, int] = field(default_factory=dict)   # flow_name → count
    multi_step_traces: int = 0          # ≥3 步的 trace 数
    bsk_automated_traces: int = 0       # 涉及 bsk 的 trace 数
    error_fix_cycles: int = 0           # 错误-修复循环数
    top_error_nodes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_events": self.total_events,
            "total_traces": self.total_traces,
            "error_events": self.error_events,
            "fix_events": self.fix_events,
            "patterns": [p.value for p in self.patterns],
            "repeated_flows": self.repeated_flows,
            "multi_step_traces": self.multi_step_traces,
            "bsk_automated_traces": self.bsk_automated_traces,
            "error_fix_cycles": self.error_fix_cycles,
            "top_error_nodes": self.top_error_nodes,
        }


@dataclass
class SkillDecision:
    """SKILL 创建决策"""
    should_create: bool
    action: ReflectionAction
    reason: str
    matched_criteria: List[str] = field(default_factory=list)
    skill_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_create": self.should_create,
            "action": self.action.value,
            "reason": self.reason,
            "matched_criteria": self.matched_criteria,
            "skill_name": self.skill_name,
        }


@dataclass
class ReflectionReport:
    """反思报告"""
    analysis: TraceAnalysis
    decision: SkillDecision
    skill_created: bool = False
    skill_name: Optional[str] = None
    recorded: bool = False
    memory_id: Optional[str] = None
    reflected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis": self.analysis.to_dict(),
            "decision": self.decision.to_dict(),
            "skill_created": self.skill_created,
            "skill_name": self.skill_name,
            "recorded": self.recorded,
            "memory_id": self.memory_id,
            "reflected_at": self.reflected_at,
        }


class HermesReflector:
    """hermes 反思自动化引擎

    每日分析 24h trace/bug/修复，按决策树判断是否形成新 SKILL。

    用法:
        reflector = HermesReflector(
            events_root=Path("~/.workbuddy/events"),
            record_fn=cognitive_record,
        )
        report = reflector.reflect()
    """

    def __init__(
        self,
        events_root: Optional[Path] = None,
        recall_fn: Optional[Callable] = None,
        record_fn: Optional[Callable] = None,
        skill_creator_fn: Optional[Callable] = None,
        idle_threshold_minutes: int = 30,
    ):
        self._events_root = events_root or self._default_events_root()
        self._recall_fn = recall_fn
        self._record_fn = record_fn
        self._skill_creator_fn = skill_creator_fn
        self._idle_threshold = timedelta(minutes=idle_threshold_minutes)
        self._last_activity: Optional[datetime] = None  # Task 4: 空闲检测

    @staticmethod
    def _default_events_root() -> Path:
        """解析默认 events 根目录"""
        env = os.environ.get("WORKBUDDY_EVENTS_ROOT", "").strip()
        if env:
            return Path(env)
        # 回退到项目目录
        return Path.home() / ".workbuddy" / "events"

    # ── trace 分析 ──────────────────────────────────────

    def _load_jsonl_files(self, hours: int = 24) -> List[Dict[str, Any]]:
        """加载最近 N 小时的 JSONL 事件"""
        events: List[Dict[str, Any]] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        if not self._events_root.exists():
            logger.warning(f"events root 不存在: {self._events_root}")
            return events

        for jsonl_file in self._events_root.rglob("*.jsonl"):
            # 按文件修改时间过滤
            try:
                mtime = datetime.fromtimestamp(
                    jsonl_file.stat().st_mtime, tz=timezone.utc
                )
                if mtime < cutoff:
                    continue
            except OSError:
                continue

            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            events.append(event)
                        except json.JSONDecodeError:
                            continue
            except OSError as e:
                logger.warning(f"读取 JSONL 失败 {jsonl_file}: {e}")

        return events

    def analyze_traces(self, hours: int = 24) -> TraceAnalysis:
        """分析最近 N 小时的 trace 事件"""
        events = self._load_jsonl_files(hours)
        analysis = TraceAnalysis(total_events=len(events))

        if not events:
            analysis.patterns.append(TracePattern.SINGLE_OCCURRENCE)
            return analysis

        # 按 trace_id 分组
        traces: Dict[str, List[Dict]] = {}
        for ev in events:
            tid = ev.get("trace_id", "")
            if tid:
                traces.setdefault(tid, []).append(ev)

        analysis.total_traces = len(traces)

        # 统计错误和修复事件
        node_error_counts: Dict[str, int] = {}
        for ev in events:
            status = ev.get("status", "")
            event_type = ev.get("event_type", "")
            node = ev.get("node", "")

            if status == "fail":
                analysis.error_events += 1
                if node:
                    node_error_counts[node] = node_error_counts.get(node, 0) + 1

            if event_type in ("bugfix", "fix_applied", "auto_fix"):
                analysis.fix_events += 1

        # 识别模式
        # 1. 重复流程 (同一 trace_id 有多个事件 → 多步编排)
        flow_counts: Dict[str, int] = {}
        for tid, evs in traces.items():
            # 用 (system, layer) 组合作为 flow 标识
            for ev in evs:
                flow_key = f"{ev.get('system', '')}/{ev.get('layer', '')}"
                flow_counts[flow_key] = flow_counts.get(flow_key, 0) + 1

            # 多步编排: 一个 trace 内 ≥3 个事件
            if len(evs) >= SKILL_MULTI_STEP_THRESHOLD:
                analysis.multi_step_traces += 1

            # bsk 自动化: 事件 meta 中含 bsk 标记
            for ev in evs:
                meta = ev.get("meta", {})
                if isinstance(meta, dict) and meta.get("bsk_automated"):
                    analysis.bsk_automated_traces += 1
                    break

        # 重复流程: 同一 flow 出现 ≥2 次
        analysis.repeated_flows = {
            k: v for k, v in flow_counts.items()
            if v >= SKILL_REUSE_THRESHOLD
        }

        # 错误-修复循环: 同一 trace 内既有 fail 又有 fix
        for tid, evs in traces.items():
            has_fail = any(e.get("status") == "fail" for e in evs)
            has_fix = any(
                e.get("event_type") in ("bugfix", "fix_applied", "auto_fix")
                for e in evs
            )
            if has_fail and has_fix:
                analysis.error_fix_cycles += 1

        # top error nodes
        analysis.top_error_nodes = sorted(
            [{"node": k, "errors": v} for k, v in node_error_counts.items()],
            key=lambda x: x["errors"],
            reverse=True,
        )[:5]

        # 识别 patterns
        if analysis.repeated_flows:
            analysis.patterns.append(TracePattern.REPEATED_FLOW)
        if analysis.multi_step_traces > 0:
            analysis.patterns.append(TracePattern.MULTI_STEP)
        if analysis.bsk_automated_traces > 0:
            analysis.patterns.append(TracePattern.BSK_AUTOMATION)
        if analysis.error_fix_cycles > 0:
            analysis.patterns.append(TracePattern.ERROR_FIX_CYCLE)
        if not analysis.patterns:
            analysis.patterns.append(TracePattern.SINGLE_OCCURRENCE)

        return analysis

    # ── SKILL 创建决策 ───────────────────────────────────

    def evaluate_skill_creation(
        self, analysis: TraceAnalysis
    ) -> SkillDecision:
        """根据决策树评估是否创建 SKILL"""
        matched: List[str] = []

        # 判据 1: 流程被复用 ≥ 2 次
        if analysis.repeated_flows:
            matched.append(
                f"流程被复用 ≥ {SKILL_REUSE_THRESHOLD} 次 "
                f"(top: {list(analysis.repeated_flows.keys())[:3]})"
            )

        # 判据 2: 涉及多步编排 ≥ 3 步
        if analysis.multi_step_traces >= 1:
            matched.append(
                f"涉及多步编排(≥{SKILL_MULTI_STEP_THRESHOLD}步): "
                f"{analysis.multi_step_traces} 个 trace"
            )

        # 判据 3: 涉及 bsk 自动化 ≥ 1 步
        if analysis.bsk_automated_traces >= SKILL_BSK_STEP_THRESHOLD:
            matched.append(
                f"涉及 bsk 自动化: {analysis.bsk_automated_traces} 个 trace"
            )

        # 判据 4: 错误-修复循环 (衍生判据: 高频 bug 模式值得 SKILL)
        if analysis.error_fix_cycles >= 2:
            matched.append(
                f"错误-修复循环 {analysis.error_fix_cycles} 次 "
                f"(高频 bug 模式值得形成 SKILL)"
            )

        if matched:
            skill_name = self._propose_skill_name(analysis)
            return SkillDecision(
                should_create=True,
                action=ReflectionAction.CREATE_SKILL,
                reason="; ".join(matched),
                matched_criteria=matched,
                skill_name=skill_name,
            )

        # 无可记录内容
        if analysis.total_events == 0:
            return SkillDecision(
                should_create=False,
                action=ReflectionAction.NO_ACTION,
                reason="24h 内无 trace 事件",
            )

        # 仅记录经验
        return SkillDecision(
            should_create=False,
            action=ReflectionAction.RECORD_ONLY,
            reason="不满足 SKILL 创建判据，仅记录经验",
        )

    @staticmethod
    def _propose_skill_name(analysis: TraceAnalysis) -> str:
        """根据分析结果提议 SKILL 名称"""
        if analysis.repeated_flows:
            top_flow = list(analysis.repeated_flows.keys())[0]
            parts = top_flow.split("/")
            return f"dream-{parts[-1]}-workflow" if len(parts) > 1 else f"dream-{top_flow}-workflow"
        if analysis.error_fix_cycles >= 2:
            return "dream-bugfix-workflow"
        return "dream-auto-workflow"

    # ── 反思主循环 ───────────────────────────────────────

    def reflect(self, hours: int = 24) -> ReflectionReport:
        """执行一次完整反思循环

        流程:
            1. 分析 24h trace
            2. 评估 SKILL 创建
            3. 如需创建 → 调用 skill_creator
            4. 记录经验到认知库
        """
        # Step 1: 分析
        analysis = self.analyze_traces(hours)

        # Step 2: 决策
        decision = self.evaluate_skill_creation(analysis)

        report = ReflectionReport(analysis=analysis, decision=decision)

        # Step 3: 创建 SKILL
        if decision.should_create and self._skill_creator_fn:
            try:
                result = self._skill_creator_fn(
                    skill_name=decision.skill_name,
                    criteria=decision.matched_criteria,
                    analysis=analysis.to_dict(),
                )
                report.skill_created = True
                report.skill_name = decision.skill_name
                logger.info(
                    f"[hermes] SKILL 创建: {decision.skill_name} "
                    f"(criteria: {decision.matched_criteria})"
                )
            except Exception as e:  # noqa: BLE001 FAIL-OPEN
                logger.warning(f"[hermes] SKILL 创建失败: {e}")
                report.skill_created = False

        # Step 4: 记录到认知库
        if self._record_fn and decision.action != ReflectionAction.NO_ACTION:
            tags = "hermes反思,L4自迭代"
            if decision.should_create:
                tags += ",SKILL"
            if analysis.error_fix_cycles > 0:
                tags += ",bugfix"
            if analysis.bsk_automated_traces > 0:
                tags += ",bsk"

            content = (
                f"[hermes反思] 24h 分析: "
                f"events={analysis.total_events}, "
                f"traces={analysis.total_traces}, "
                f"errors={analysis.error_events}, "
                f"fixes={analysis.fix_events}, "
                f"patterns={[p.value for p in analysis.patterns]}, "
                f"decision={decision.action.value}, "
                f"reason={decision.reason}"
            )

            try:
                mem_id = self._record_fn(
                    content=content,
                    quality_level="B",
                    tags=tags,
                )
                if mem_id:
                    report.recorded = True
                    report.memory_id = str(mem_id)
            except Exception as e:  # noqa: BLE001 FAIL-OPEN
                logger.warning(f"[hermes] 认知库记录失败: {e}")

        return report

    # ── Task 4: 会话后自动审查 ──────────────────────────

    def mark_activity(self) -> None:
        """标记会话活动，更新最后活动时间戳。"""
        self._last_activity = datetime.now(timezone.utc)

    def auto_reflect_idle(self, hours: int = 24) -> Optional[ReflectionReport]:
        """会话空闲超过阈值时自动触发反思。

        触发条件：距最后活动时间超过 idle_threshold_minutes（默认 30 分钟）。
        FAIL-OPEN：任何异常返回 None，不阻塞主流程。

        Args:
            hours: 反思分析的时间窗口（小时）

        Returns:
            ReflectionReport（如果触发了反思）或 None（未触发或失败）
        """
        try:
            now = datetime.now(timezone.utc)
            # 无活动记录 → 视为需要审查
            if self._last_activity is None:
                logger.info("[hermes] 无活动记录，跳过自动反思")
                return None
            idle_duration = now - self._last_activity
            if idle_duration < self._idle_threshold:
                return None

            logger.info(
                f"[hermes] 空闲 {idle_duration.total_seconds() / 60:.1f} 分钟 "
                f">= 阈值 {self._idle_threshold.total_seconds() / 60:.0f} 分钟，触发自动反思"
            )
            report = self.reflect(hours=hours)
            # 反思后重置活动时间，避免短时间内重复触发
            self._last_activity = now
            return report
        except Exception as e:  # noqa: BLE001 FAIL-OPEN
            logger.warning(f"[hermes] 自动反思失败: {e}")
            return None


def create_default_hermes_reflector(
    record_fn: Optional[Callable] = None,
    recall_fn: Optional[Callable] = None,
) -> HermesReflector:
    """创建默认 hermes 反思器 (无 skill_creator, 仅分析+记录)"""
    return HermesReflector(
        events_root=None,  # 使用默认路径
        recall_fn=recall_fn,
        record_fn=record_fn,
        skill_creator_fn=None,
    )
