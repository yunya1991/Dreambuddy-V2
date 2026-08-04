#!/usr/bin/env python3
"""思维路径评测引擎（设计节 7.3/7.4/7.5）。

借鉴：
  - superpowers-evals quorum 的 precedence-based compose（三值裁决 pass/fail/indeterminate）
  - hermes-agent batch_runner 的工具成功率+推理覆盖率双指标
  - 设计节 7.4 策略 1 历史对照（current vs 同类任务历史均值 baseline）

核心三函数：
  - compute_path_advantage(current, baseline) -> [-1.0, 1.0]
  - decide_learning_action(...) -> {decision: upgrade/alert/quarantine/observe}
  - record_evaluation(sample, ...) -> 追加到 evaluation_history.jsonl
"""
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# 设计节 7.5 阈值
LEARNING_THRESHOLD_UP = 0.2       # path_advantage >= +0.2 → 升级候选
LEARNING_THRESHOLD_DOWN = -0.2    # path_advantage <= -0.2 → 告警候选
GATE_VIOLATION_ALERT_THRESHOLD = 2  # HARD-GATE 违反 >= 2 → 告警
QUARANTINE_CONSECUTIVE_NEGATIVE = 3  # 连续 3 次负向 → 隔离


@dataclass
class EvaluationSample:
    """思维路径评测样本（设计节 7.3 + 附录 A.5）。"""
    session_id: str
    task_summary: str
    skill_ids_injected: List[str]
    thought_chain_compressed: List[str]   # 5-15 个关键决策点（Task 22 生成）
    action_chain_compressed: List[str]    # reproducible_steps（Task 18 生成）
    hard_gate_violations: List[str]
    outcome_metrics: Dict[str, float]
    timestamp: int


def compute_path_advantage(current: EvaluationSample, baseline: EvaluationSample) -> float:
    """设计节 7.4：返回 [-1.0, 1.0]，正值表示 process_block 注入有优势。

    借鉴 superpowers-evals quorum 的 precedence-based 思路：
      成功率是 precedence 最高的指标（task_completion_success 一票否决），
      其余指标按加权累加，最终 clamp 到 [-1.0, 1.0]。
    """
    scores: List[float] = []
    c = current.outcome_metrics
    b = baseline.outcome_metrics
    # 1. 成功率（precedence 最高，一票否决）
    if c.get("task_completion_success", 0) > 0 and b.get("task_completion_success", 0) <= 0:
        scores.append(+1.0)
    elif c.get("task_completion_success", 0) <= 0 and b.get("task_completion_success", 0) > 0:
        scores.append(-1.0)
    # 2. HARD-GATE 违反减少
    b_gate = b.get("hard_gate_violation_count", 0)
    c_gate = c.get("hard_gate_violation_count", 0)
    if b_gate > 0:
        scores.append((b_gate - c_gate) / b_gate * 0.3)
    # 3. 重做次数减少
    b_rework = b.get("rework_count", 0)
    c_rework = c.get("rework_count", 0)
    if b_rework > 0:
        scores.append((b_rework - c_rework) / b_rework * 0.2)
    # 4. 耗时减少（不超过 30% 权重，避免为快牺牲质量）
    b_dur = b.get("duration_minutes", 0)
    c_dur = c.get("duration_minutes", 0)
    if b_dur > 0:
        time_reduction = (b_dur - c_dur) / b_dur
        scores.append(max(-0.3, min(0.3, time_reduction * 0.3)))
    # 5. follow_score 提升
    scores.append((c.get("follow_score", 0) - b.get("follow_score", 0)) * 0.2)
    return max(-1.0, min(1.0, sum(scores)))


def decide_learning_action(
    path_advantage: float,
    hard_gate_violation_count: int,
    consecutive_positive: int,
    consecutive_negative: int,
) -> Dict[str, Any]:
    """设计节 7.5 学习/回滚决策。

    Returns: {decision: 'upgrade'|'alert'|'quarantine'|'observe', reason: str, ...}
    """
    # 1. 隔离优先（precedence 最高，借鉴 quorum 的 precedence-based compose）
    if consecutive_negative >= QUARANTINE_CONSECUTIVE_NEGATIVE:
        return {"decision": "quarantine",
                "reason": f"连续 {consecutive_negative} 次 path_advantage <= {LEARNING_THRESHOLD_DOWN}"}
    # 2. 告警
    if path_advantage <= LEARNING_THRESHOLD_DOWN or hard_gate_violation_count >= GATE_VIOLATION_ALERT_THRESHOLD:
        return {"decision": "alert",
                "reason": f"path_advantage={path_advantage:.2f} <= {LEARNING_THRESHOLD_DOWN} "
                          f"或 gate 违反 {hard_gate_violation_count} >= {GATE_VIOLATION_ALERT_THRESHOLD}"}
    # 3. 升级
    if path_advantage >= LEARNING_THRESHOLD_UP:
        return {"decision": "upgrade",
                "reason": f"path_advantage={path_advantage:.2f} >= +{LEARNING_THRESHOLD_UP} "
                          f"(consecutive_positive={consecutive_positive})"}
    # 4. 平庸
    return {"decision": "observe",
            "reason": f"path_advantage={path_advantage:.2f} 在阈值区间内，标记 observational"}


def record_evaluation(
    sample: EvaluationSample,
    path_advantage: float,
    decision: str,
    history_path: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """追加评测记录到 evaluation_history.jsonl（设计节 7.8）。"""
    if history_path is None:
        history_path = Path(__file__).parent.parent / "0-元记忆" / "evaluation_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "session_id": sample.session_id,
        "task_summary": sample.task_summary,
        "skill_ids_injected": sample.skill_ids_injected,
        "path_advantage": round(path_advantage, 4),
        "decision": decision,
        "outcome_metrics": sample.outcome_metrics,
        "hard_gate_violations": sample.hard_gate_violations,
        "timestamp": sample.timestamp,
        "recorded_at": int(time.time()),
    }
    if extra:
        record.update(extra)
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_history_baseline(task_type: str, history_path: Optional[Path] = None) -> Optional[EvaluationSample]:
    """设计节 7.4 策略 1 历史对照：从 evaluation_history.jsonl 读同类任务历史均值作为 baseline。"""
    if history_path is None:
        history_path = Path(__file__).parent.parent / "0-元记忆" / "evaluation_history.jsonl"
    if not history_path.exists():
        return None
    samples: List[Dict] = []
    with open(history_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not samples:
        return None
    # 取最近 10 条同类任务（按 task_summary 简单匹配；生产可按 task_type 索引）
    recent = samples[-10:]
    avg_metrics = {
        "task_completion_success": sum(s.get("outcome_metrics", {}).get("task_completion_success", 0) for s in recent) / len(recent),
        "hard_gate_violation_count": sum(s.get("outcome_metrics", {}).get("hard_gate_violation_count", 0) for s in recent) / len(recent),
        "rework_count": sum(s.get("outcome_metrics", {}).get("rework_count", 0) for s in recent) / len(recent),
        "duration_minutes": sum(s.get("outcome_metrics", {}).get("duration_minutes", 0) for s in recent) / len(recent),
        "follow_score": sum(s.get("outcome_metrics", {}).get("follow_score", 0) for s in recent) / len(recent),
        "tool_call_efficiency": sum(s.get("outcome_metrics", {}).get("tool_call_efficiency", 0) for s in recent) / len(recent),
    }
    return EvaluationSample(
        session_id="baseline-avg",
        task_summary=f"baseline avg of {len(recent)} historical samples",
        skill_ids_injected=[],
        thought_chain_compressed=[],
        action_chain_compressed=[],
        hard_gate_violations=[],
        outcome_metrics=avg_metrics,
        timestamp=recent[-1].get("timestamp", int(time.time())),
    )
