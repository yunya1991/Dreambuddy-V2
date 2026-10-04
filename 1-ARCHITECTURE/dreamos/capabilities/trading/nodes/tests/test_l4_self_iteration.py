"""
L4 自迭代测试 — hermes 反思 + 参数优化 + 案例入库 + 文档同步
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROJECT_ROOT / "1-ARCHITECTURE"))

from dreamos.core.compute.hermes_reflector import (
    HermesReflector, TraceAnalysis, SkillDecision, ReflectionReport,
    TracePattern, ReflectionAction,
)
from dreamos.core.compute.param_optimizer import (
    ParamOptimizer, TrialResult, OptimizationResult, OptimizationStatus,
    ApplyDecision, CostAdaptiveScheduler,
)
from dreamos.core.compute.case_ingest_gate import (
    CaseIngestGate, LearningValue, IngestReport, IngestDecision,
)
from dreamos.core.compute.doc_sync_trigger import (
    DocSyncTrigger, ChangeReport, SyncReport, FileChange,
    ChangeType, SyncAction,
)


# ═══════════════════════════════════════════════════════════════
# L4.1 hermes 反思自动化
# ═══════════════════════════════════════════════════════════════

class TestHermesTraceAnalysis:
    """trace 分析测试"""

    def _make_events(self, tmpdir, events_data):
        """生成 JSONL 事件文件"""
        events_root = Path(tmpdir) / "events" / "dreamos"
        events_root.mkdir(parents=True, exist_ok=True)
        fpath = events_root / "2026-09-29.jsonl"
        with open(fpath, "w") as f:
            for ev in events_data:
                f.write(json.dumps(ev) + "\n")
        return events_root.parent

    def test_empty_events(self):
        """空事件 → 无模式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            reflector = HermesReflector(events_root=Path(tmpdir))
            analysis = reflector.analyze_traces(hours=24)
            assert analysis.total_events == 0
            assert TracePattern.SINGLE_OCCURRENCE in analysis.patterns

    def test_multi_step_trace(self):
        """多步编排检测"""
        with tempfile.TemporaryDirectory() as tmpdir:
            events = [
                {"trace_id": "t1", "system": "dreamos", "layer": "A", "node": "A1", "status": "ok"},
                {"trace_id": "t1", "system": "dreamos", "layer": "A", "node": "A2", "status": "ok"},
                {"trace_id": "t1", "system": "dreamos", "layer": "A", "node": "A3", "status": "ok"},
            ]
            root = self._make_events(tmpdir, events)
            reflector = HermesReflector(events_root=root)
            analysis = reflector.analyze_traces(hours=24)
            assert analysis.total_events == 3
            assert analysis.multi_step_traces == 1
            assert TracePattern.MULTI_STEP in analysis.patterns

    def test_error_fix_cycle(self):
        """错误-修复循环检测"""
        with tempfile.TemporaryDirectory() as tmpdir:
            events = [
                {"trace_id": "t1", "system": "dreamos", "node": "A1", "status": "fail"},
                {"trace_id": "t1", "system": "dreamos", "node": "A1", "event_type": "bugfix", "status": "ok"},
            ]
            root = self._make_events(tmpdir, events)
            reflector = HermesReflector(events_root=root)
            analysis = reflector.analyze_traces(hours=24)
            assert analysis.error_events == 1
            assert analysis.fix_events == 1
            assert analysis.error_fix_cycles == 1
            assert TracePattern.ERROR_FIX_CYCLE in analysis.patterns

    def test_bsk_automation(self):
        """bsk 自动化检测"""
        with tempfile.TemporaryDirectory() as tmpdir:
            events = [
                {"trace_id": "t1", "system": "dreamos", "node": "A1", "status": "ok",
                 "meta": {"bsk_automated": True}},
            ]
            root = self._make_events(tmpdir, events)
            reflector = HermesReflector(events_root=root)
            analysis = reflector.analyze_traces(hours=24)
            assert analysis.bsk_automated_traces == 1
            assert TracePattern.BSK_AUTOMATION in analysis.patterns

    def test_repeated_flow(self):
        """重复流程检测"""
        with tempfile.TemporaryDirectory() as tmpdir:
            events = [
                {"trace_id": "t1", "system": "dreamos", "layer": "A", "status": "ok"},
                {"trace_id": "t2", "system": "dreamos", "layer": "A", "status": "ok"},
                {"trace_id": "t3", "system": "dreamos", "layer": "A", "status": "ok"},
            ]
            root = self._make_events(tmpdir, events)
            reflector = HermesReflector(events_root=root)
            analysis = reflector.analyze_traces(hours=24)
            assert len(analysis.repeated_flows) > 0
            assert TracePattern.REPEATED_FLOW in analysis.patterns

    def test_to_dict(self):
        """to_dict 序列化"""
        analysis = TraceAnalysis(total_events=10, total_traces=2)
        d = analysis.to_dict()
        assert d["total_events"] == 10
        assert d["total_traces"] == 2


class TestHermesSkillDecision:
    """SKILL 创建决策测试"""

    def _make_reflector(self):
        return HermesReflector(events_root=Path("/nonexistent"))

    def test_no_events_no_action(self):
        """无事件 → NO_ACTION"""
        reflector = self._make_reflector()
        analysis = TraceAnalysis(total_events=0)
        decision = reflector.evaluate_skill_creation(analysis)
        assert decision.should_create is False
        assert decision.action == ReflectionAction.NO_ACTION

    def test_repeated_flow_creates_skill(self):
        """重复流程 → 创建 SKILL"""
        reflector = self._make_reflector()
        analysis = TraceAnalysis(
            total_events=10,
            total_traces=3,
            repeated_flows={"dreamos/A": 5},
        )
        decision = reflector.evaluate_skill_creation(analysis)
        assert decision.should_create is True
        assert decision.action == ReflectionAction.CREATE_SKILL
        assert decision.skill_name is not None

    def test_multi_step_creates_skill(self):
        """多步编排 → 创建 SKILL"""
        reflector = self._make_reflector()
        analysis = TraceAnalysis(
            total_events=10,
            multi_step_traces=2,
        )
        decision = reflector.evaluate_skill_creation(analysis)
        assert decision.should_create is True

    def test_bsk_creates_skill(self):
        """bsk 自动化 → 创建 SKILL"""
        reflector = self._make_reflector()
        analysis = TraceAnalysis(
            total_events=5,
            bsk_automated_traces=1,
        )
        decision = reflector.evaluate_skill_creation(analysis)
        assert decision.should_create is True

    def test_error_fix_cycles_creates_skill(self):
        """多次错误-修复循环 → 创建 SKILL"""
        reflector = self._make_reflector()
        analysis = TraceAnalysis(
            total_events=10,
            error_fix_cycles=3,
        )
        decision = reflector.evaluate_skill_creation(analysis)
        assert decision.should_create is True

    def test_single_occurrence_record_only(self):
        """单次发生 → 仅记录"""
        reflector = self._make_reflector()
        analysis = TraceAnalysis(
            total_events=1,
            patterns=[TracePattern.SINGLE_OCCURRENCE],
        )
        decision = reflector.evaluate_skill_creation(analysis)
        assert decision.should_create is False
        assert decision.action == ReflectionAction.RECORD_ONLY

    def test_to_dict(self):
        """SkillDecision to_dict"""
        d = SkillDecision(
            should_create=True,
            action=ReflectionAction.CREATE_SKILL,
            reason="test",
            matched_criteria=["criterion1"],
            skill_name="test-skill",
        )
        result = d.to_dict()
        assert result["should_create"] is True
        assert result["skill_name"] == "test-skill"


class TestHermesReflect:
    """反思主循环测试"""

    def test_reflect_with_empty_events(self):
        """空事件反思 → NO_ACTION"""
        reflector = HermesReflector(events_root=Path("/nonexistent"))
        report = reflector.reflect(hours=24)
        assert report.decision.action == ReflectionAction.NO_ACTION
        assert report.skill_created is False

    def test_reflect_records_to_cognitive(self):
        """反思结果记录到认知库"""
        mock_record = MagicMock(return_value="mem-123")
        with tempfile.TemporaryDirectory() as tmpdir:
            events = [
                {"trace_id": "t1", "system": "dreamos", "layer": "A", "status": "ok"},
                {"trace_id": "t1", "system": "dreamos", "layer": "A", "status": "ok"},
                {"trace_id": "t1", "system": "dreamos", "layer": "A", "status": "ok"},
            ]
            events_root = Path(tmpdir) / "events" / "dreamos"
            events_root.mkdir(parents=True)
            with open(events_root / "2026-09-29.jsonl", "w") as f:
                for ev in events:
                    f.write(json.dumps(ev) + "\n")

            reflector = HermesReflector(
                events_root=Path(tmpdir) / "events",
                record_fn=mock_record,
            )
            report = reflector.reflect(hours=24)
            assert report.decision.should_create is True
            assert report.recorded is True
            assert report.memory_id == "mem-123"

    def test_reflect_creates_skill(self):
        """反思触发 SKILL 创建"""
        mock_creator = MagicMock(return_value={"skill_id": "sk-1"})
        with tempfile.TemporaryDirectory() as tmpdir:
            events = [
                {"trace_id": f"t{i}", "system": "dreamos", "layer": "A", "status": "ok"}
                for i in range(5)
            ]
            events_root = Path(tmpdir) / "events" / "dreamos"
            events_root.mkdir(parents=True)
            with open(events_root / "2026-09-29.jsonl", "w") as f:
                for ev in events:
                    f.write(json.dumps(ev) + "\n")

            reflector = HermesReflector(
                events_root=Path(tmpdir) / "events",
                skill_creator_fn=mock_creator,
            )
            report = reflector.reflect(hours=24)
            assert report.skill_created is True
            assert report.skill_name is not None


# ═══════════════════════════════════════════════════════════════
# L4.2 参数自优化
# ═══════════════════════════════════════════════════════════════

class TestTrialResult:
    """试验结果测试"""

    def test_val_mean(self):
        t = TrialResult(params={"a": 1}, score=0.5, val_scores=[0.4, 0.6])
        assert t.val_mean == pytest.approx(0.5)

    def test_val_std(self):
        t = TrialResult(params={"a": 1}, score=0.5, val_scores=[0.4, 0.6])
        assert t.val_std == pytest.approx(0.1, abs=0.01)

    def test_stability_score(self):
        t = TrialResult(params={"a": 1}, score=0.5, val_scores=[0.4, 0.6])
        expected = 0.5 / (1 + 0.1)
        assert t.stability_score == pytest.approx(expected, abs=0.01)

    def test_empty_val_scores(self):
        t = TrialResult(params={"a": 1}, score=0.5)
        assert t.val_mean == 0.0
        assert t.val_std == 0.0
        assert t.stability_score == 0.5

    def test_to_dict(self):
        t = TrialResult(params={"a": 1}, score=0.5, val_scores=[0.4, 0.6])
        d = t.to_dict()
        assert d["score"] == 0.5
        assert len(d["val_scores"]) == 2


class TestParamOptimizer:
    """参数优化器测试"""

    def test_too_many_params_raises(self):
        """参数过多 → ValueError"""
        space = {f"p{i}": (0, 1) for i in range(6)}
        with pytest.raises(ValueError, match="超过上限"):
            ParamOptimizer(space)

    def test_skip_low_trials(self):
        """试验次数不足 → SKIPPED"""
        opt = ParamOptimizer({"a": (0, 1)})
        result = opt.optimize(
            objective_fn=lambda p: 0.5,
            n_trials=5,  # < MIN_TRIALS=10
        )
        assert result.status == OptimizationStatus.SKIPPED

    def test_optimize_completes(self):
        """优化完成 → COMPLETED"""
        opt = ParamOptimizer({"a": (0, 1), "b": (0, 1)})

        def objective(params):
            return params["a"] * 0.5 + params["b"] * 0.5

        result = opt.optimize(objective, n_trials=15)
        assert result.status == OptimizationStatus.COMPLETED
        assert result.best_trial is not None
        assert result.n_trials == 15

    def test_improvement_triggers_apply(self):
        """改进显著 → APPLY"""
        opt = ParamOptimizer({"a": (0, 1)})

        def objective(params):
            return 0.2 + params["a"] * 0.5

        result = opt.optimize(objective, baseline_score=0.2, n_trials=15)
        assert result.improvement > 0
        # best trial score should be > baseline
        assert result.best_trial.score > 0.2

    def test_no_improvement_holds(self):
        """无改进 → HOLD"""
        opt = ParamOptimizer({"a": (0, 1)})

        def objective(params):
            return 0.1  # 恒定低分

        result = opt.optimize(objective, baseline_score=0.5, n_trials=15)
        assert result.apply_decision == ApplyDecision.HOLD
        assert result.should_apply is False

    def test_walk_forward_validation(self):
        """walk-forward 验证"""
        opt = ParamOptimizer({"a": (0, 1)})

        def objective(params):
            return params["a"]

        def walk_forward(params):
            return [params["a"], params["a"] * 0.9, params["a"] * 1.1]

        result = opt.optimize(
            objective, baseline_score=0.2, n_trials=15,
            walk_forward_fn=walk_forward,
        )
        assert result.status == OptimizationStatus.COMPLETED
        if result.best_trial:
            assert len(result.best_trial.val_scores) == 3

    def test_to_dict(self):
        """OptimizationResult to_dict"""
        r = OptimizationResult(
            status=OptimizationStatus.COMPLETED,
            best_trial=TrialResult(params={"a": 1}, score=0.5),
            baseline_score=0.3,
            improvement=0.5,
            n_trials=15,
        )
        d = r.to_dict()
        assert d["status"] == "completed"
        assert d["improvement"] == 0.5


class TestCostAdaptiveScheduler:
    """cost_ms 自适应调度测试"""

    def test_default_interval(self):
        s = CostAdaptiveScheduler(default_interval_ms=5000)
        assert s.get_interval("A1") == 5000

    def test_high_cost_increases_interval(self):
        s = CostAdaptiveScheduler(default_interval_ms=5000, cost_threshold_ms=3000, adjust_window=3)
        for _ in range(5):
            s.record_cost("A1", 5000)  # > threshold
        interval = s.get_interval("A1")
        assert interval > 5000

    def test_low_cost_decreases_interval(self):
        s = CostAdaptiveScheduler(default_interval_ms=5000, cost_threshold_ms=3000, adjust_window=3)
        for _ in range(5):
            s.record_cost("A1", 100)  # < threshold * 0.5
        interval = s.get_interval("A1")
        assert interval < 5000

    def test_interval_clamped(self):
        s = CostAdaptiveScheduler(
            default_interval_ms=5000, min_interval_ms=1000, max_interval_ms=60000,
            cost_threshold_ms=100, adjust_window=3,
        )
        for _ in range(5):
            s.record_cost("A1", 10000)  # very high cost
        interval = s.get_interval("A1")
        assert interval <= 60000

    def test_status(self):
        s = CostAdaptiveScheduler(adjust_window=3)
        s.record_cost("A1", 200)
        st = s.status()
        assert "A1" in st


# ═══════════════════════════════════════════════════════════════
# L4.3 案例库自动 ingest
# ═══════════════════════════════════════════════════════════════

class TestLearningValue:
    """学习价值评估测试"""

    def test_to_dict(self):
        v = LearningValue(novelty=0.8, significance=0.6, anomaly=0.5, overall_score=0.7)
        d = v.to_dict()
        assert d["novelty"] == 0.8
        assert d["overall_score"] == 0.7


class TestCaseIngestGate:
    """案例入库门控测试"""

    def test_high_value_ingest(self):
        """高价值案例 → INGEST"""
        mock_recall = MagicMock(return_value=[])
        mock_ingest = MagicMock(return_value="case-001")
        gate = CaseIngestGate(recall_fn=mock_recall, ingest_fn=mock_ingest)

        result = gate.evaluate_and_ingest({
            "direction": "LONG",
            "pnl_pct": 0.08,
            "confidence": 0.9,
            "indicators": {"rsi14": 22, "volume_ratio": 2.5, "price_change_pct": 0.04},
        })
        assert result.decision == IngestDecision.INGEST
        assert result.ingested is True
        assert result.case_id == "case-001"

    def test_low_value_skip(self):
        """低价值案例 → SKIP"""
        mock_recall = MagicMock(return_value=[
            {"content": "LONG 历史记录"} for _ in range(10)
        ])
        gate = CaseIngestGate(recall_fn=mock_recall)

        result = gate.evaluate_and_ingest({
            "direction": "LONG",
            "pnl_pct": 0.001,
            "confidence": 0.3,
            "indicators": {"rsi14": 50, "volume_ratio": 1.0},
        })
        assert result.decision == IngestDecision.SKIP

    def test_medium_value_deferred(self):
        """中等价值 → DEFERRED"""
        mock_recall = MagicMock(return_value=[
            {"content": "LONG 历史记录"},
            {"content": "SHORT 另一条记录"},
            {"content": "NEUTRAL 第三条"},
        ])
        gate = CaseIngestGate(recall_fn=mock_recall)

        result = gate.evaluate_and_ingest({
            "direction": "LONG",
            "pnl_pct": 0.03,
            "confidence": 0.5,
            "indicators": {"rsi14": 30},
        })
        assert result.decision == IngestDecision.DEFERRED

    def test_anomaly_detection(self):
        """异常度检测"""
        gate = CaseIngestGate()
        value = gate.evaluate_learning_value({
            "direction": "LONG",
            "pnl_pct": 0.05,
            "confidence": 0.8,
            "indicators": {"rsi14": 20, "volume_ratio": 3.0, "price_change_pct": 0.05},
        })
        assert value.anomaly > 0.5

    def test_no_recall_fn(self):
        """无 recall_fn → 全新 → 高新颖性"""
        gate = CaseIngestGate()
        value = gate.evaluate_learning_value({
            "direction": "LONG",
            "pnl_pct": 0.05,
            "confidence": 0.8,
            "indicators": {"rsi14": 25},
        })
        assert value.novelty == 1.0  # 无历史 → 全新

    def test_to_dict(self):
        """IngestReport to_dict"""
        r = IngestReport(
            decision=IngestDecision.INGEST,
            value=LearningValue(overall_score=0.7),
            ingested=True,
            case_id="c1",
            reason="test",
        )
        d = r.to_dict()
        assert d["decision"] == "ingest"
        assert d["case_id"] == "c1"


# ═══════════════════════════════════════════════════════════════
# L4.4 文档自同步
# ═══════════════════════════════════════════════════════════════

class TestFileChange:
    """文件变更测试"""

    def test_to_dict(self):
        c = FileChange(path="a.py", change_type=ChangeType.ADDED, impact_level="major")
        d = c.to_dict()
        assert d["path"] == "a.py"
        assert d["change_type"] == "added"


class TestChangeReport:
    """变更报告测试"""

    def test_major_changes(self):
        r = ChangeReport(changes=[
            FileChange("a.py", ChangeType.MODIFIED, impact_level="minor"),
            FileChange("b.py", ChangeType.ADDED, impact_level="major"),
        ])
        assert len(r.major_changes) == 1

    def test_to_dict(self):
        r = ChangeReport(needs_sync=True, impact_summary="+1")
        d = r.to_dict()
        assert d["needs_sync"] is True


class TestDocSyncTrigger:
    """文档自同步触发器测试"""

    def test_detect_added_file(self):
        """检测新增文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = DocSyncTrigger(project_root=Path(tmpdir))
            changes = trigger.detect_changes(
                before={},
                after={"src/api.py": "abc123"},
            )
            assert len(changes.changes) == 1
            assert changes.changes[0].change_type == ChangeType.ADDED
            assert changes.needs_sync is True  # api → major

    def test_detect_deleted_file(self):
        """检测删除文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = DocSyncTrigger(project_root=Path(tmpdir))
            changes = trigger.detect_changes(
                before={"src/handler.py": "abc123"},
                after={},
            )
            assert len(changes.changes) == 1
            assert changes.changes[0].change_type == ChangeType.DELETED

    def test_detect_modified_file(self):
        """检测修改文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = DocSyncTrigger(project_root=Path(tmpdir))
            changes = trigger.detect_changes(
                before={"src/utils.py": "abc123"},
                after={"src/utils.py": "def456"},
            )
            assert len(changes.changes) == 1
            assert changes.changes[0].change_type == ChangeType.MODIFIED

    def test_no_change_no_sync(self):
        """无变更 → 不需同步"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = DocSyncTrigger(project_root=Path(tmpdir))
            changes = trigger.detect_changes(
                before={"src/utils.py": "abc123"},
                after={"src/utils.py": "abc123"},
            )
            assert len(changes.changes) == 0
            assert changes.needs_sync is False

    def test_ignored_patterns(self):
        """忽略 __pycache__ 等目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = DocSyncTrigger(project_root=Path(tmpdir))
            changes = trigger.detect_changes(
                before={},
                after={"__pycache__/cache.py": "abc", "node_modules/x.js": "def"},
            )
            assert len(changes.changes) == 0

    def test_schema_change_critical(self):
        """Schema 变更 → critical"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = DocSyncTrigger(project_root=Path(tmpdir))
            changes = trigger.detect_changes(
                before={"schema.prisma": "abc"},
                after={"schema.prisma": "def"},
            )
            assert changes.changes[0].impact_level == "critical"

    def test_skip_when_no_major(self):
        """无 major 变更 → SKIP"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = DocSyncTrigger(project_root=Path(tmpdir))
            changes = ChangeReport(needs_sync=False)
            report = trigger.sync(changes)
            assert report.action == SyncAction.SKIP

    def test_sync_calls_fn(self):
        """同步调用 sync_fn"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_sync = MagicMock(return_value={
                "index_updated": True,
                "knowledge_updated": True,
                "lint_passed": True,
            })
            mock_record = MagicMock(return_value="mem-1")
            trigger = DocSyncTrigger(
                project_root=Path(tmpdir),
                record_fn=mock_record,
                sync_fn=mock_sync,
            )
            changes = ChangeReport(
                changes=[FileChange("api.py", ChangeType.ADDED, impact_level="major")],
                needs_sync=True,
            )
            report = trigger.sync(changes)
            assert report.action == SyncAction.SYNC
            assert report.index_updated is True
            assert report.recorded is True
            assert report.memory_id == "mem-1"

    def test_sync_failed(self):
        """同步失败 → FAILED"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_sync = MagicMock(side_effect=RuntimeError("boom"))
            trigger = DocSyncTrigger(
                project_root=Path(tmpdir),
                sync_fn=mock_sync,
            )
            changes = ChangeReport(needs_sync=True)
            report = trigger.sync(changes)
            assert report.action == SyncAction.FAILED
