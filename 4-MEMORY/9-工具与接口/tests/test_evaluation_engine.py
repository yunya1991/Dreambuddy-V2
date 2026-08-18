"""evaluation_engine 单测：EvaluationSample + compute_path_advantage + decide_learning_action（设计节 7.3/7.4/7.5）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from evaluation_engine import (
    EvaluationSample, compute_path_advantage, decide_learning_action,
    LEARNING_THRESHOLD_UP, LEARNING_THRESHOLD_DOWN, record_evaluation,
)


def _make_sample(success=True, gate_violations=0, rework=1, duration=30.0, follow=0.7) -> EvaluationSample:
    return EvaluationSample(
        session_id="S-test",
        task_summary="test task",
        skill_ids_injected=["test-driven-development"],
        thought_chain_compressed=["step1", "step2"],
        action_chain_compressed=["step1", "step2"],
        hard_gate_violations=["gate"] * gate_violations,
        outcome_metrics={
            "task_completion_success": 1.0 if success else 0.0,
            "hard_gate_violation_count": float(gate_violations),
            "rework_count": float(rework),
            "tool_call_efficiency": 0.6,
            "duration_minutes": duration,
            "follow_score": follow,
        },
        timestamp=1785510000,
    )


def test_evaluation_sample_dataclass():
    s = _make_sample()
    assert s.session_id == "S-test"
    assert s.skill_ids_injected == ["test-driven-development"]
    assert len(s.thought_chain_compressed) == 2


def test_compute_path_advantage_positive_when_current_better():
    """设计节 7.4：current 比 baseline 好 → 正值。"""
    current = _make_sample(success=True, gate_violations=0, rework=1, duration=20.0, follow=0.8)
    baseline = _make_sample(success=False, gate_violations=2, rework=3, duration=40.0, follow=0.4)
    adv = compute_path_advantage(current, baseline)
    assert -1.0 <= adv <= 1.0
    assert adv > 0  # current 更好


def test_compute_path_advantage_negative_when_current_worse():
    """current 比 baseline 差 → 负值。"""
    current = _make_sample(success=False, gate_violations=3, rework=4, duration=50.0, follow=0.2)
    baseline = _make_sample(success=True, gate_violations=0, rework=1, duration=20.0, follow=0.8)
    adv = compute_path_advantage(current, baseline)
    assert adv < 0


def test_compute_path_advantage_bounded():
    """得分必须限制在 [-1.0, 1.0]。"""
    current = _make_sample(success=True, gate_violations=0, rework=0, duration=1.0, follow=1.0)
    baseline = _make_sample(success=False, gate_violations=100, rework=100, duration=1000.0, follow=0.0)
    adv = compute_path_advantage(current, baseline)
    assert adv <= 1.0
    assert adv >= -1.0


def test_decide_learning_action_upgrade():
    """设计节 7.5：path_advantage >= +0.2 → 升级。"""
    action = decide_learning_action(path_advantage=0.3, hard_gate_violation_count=0,
                                     consecutive_positive=2, consecutive_negative=0)
    assert action["decision"] == "upgrade"


def test_decide_learning_action_alert():
    """path_advantage <= -0.2 或 gate 违反 >= 2 → 告警。"""
    action = decide_learning_action(path_advantage=-0.3, hard_gate_violation_count=0,
                                     consecutive_positive=0, consecutive_negative=1)
    assert action["decision"] == "alert"
    action2 = decide_learning_action(path_advantage=0.0, hard_gate_violation_count=2,
                                      consecutive_positive=0, consecutive_negative=0)
    assert action2["decision"] == "alert"


def test_decide_learning_action_quarantine():
    """连续 3 次 path_advantage <= -0.2 → quarantined。"""
    action = decide_learning_action(path_advantage=-0.3, hard_gate_violation_count=1,
                                     consecutive_positive=0, consecutive_negative=3)
    assert action["decision"] == "quarantine"


def test_decide_learning_action_observe():
    """平庸 → observational。"""
    action = decide_learning_action(path_advantage=0.05, hard_gate_violation_count=0,
                                     consecutive_positive=0, consecutive_negative=0)
    assert action["decision"] == "observe"


def test_record_evaluation_appends_jsonl(tmp_path):
    """评测记录追加到 evaluation_history.jsonl。"""
    history_path = tmp_path / "evaluation_history.jsonl"
    s = _make_sample()
    record_evaluation(s, path_advantage=0.3, decision="upgrade", history_path=history_path)
    record_evaluation(s, path_advantage=-0.1, decision="observe", history_path=history_path)
    lines = history_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    import json
    first = json.loads(lines[0])
    assert first["path_advantage"] == 0.3
    assert first["decision"] == "upgrade"
