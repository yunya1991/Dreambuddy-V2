"""ASIL verdict 路由 + feedback 写回。

SPEC v0.2 §4.3 接口定义 + §5.2 FAIL-OPEN 降级。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Phase 1 events 输出目录
ASIL_EVENTS_DIR = Path(__file__).resolve().parent.parent / "events" / "asil"


@dataclass
class VerdictResult:
    """Pipeline verdict 结果。"""

    verdict: str  # candidate / verified / rejected / falsified / inconclusive / dead
    oracle_confidence: float = 0.0
    test_coverage: float = 0.0
    survival_passed: bool = True
    violations: List[str] = field(default_factory=list)
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "oracle_confidence": self.oracle_confidence,
            "test_coverage": self.test_coverage,
            "survival_passed": self.survival_passed,
            "violations": self.violations,
            "trace_id": self.trace_id,
        }


class VerdictRouter:
    """Verdict 路由 — 根据 verdict 类型决定后续行为。"""

    def route(self, verdict: str) -> str:
        """返回 verdict 对应的后续路由名。"""
        if verdict == "dead":
            return "REPORT_ONLY"
        if verdict == "inconclusive":
            return "FEEDBACK_SKIP_DISTILL"
        if verdict in ("candidate", "verified"):
            return "FEEDBACK_VERIFY_DISTILL"
        if verdict in ("rejected", "falsified"):
            return "FEEDBACK_RECORD_FAILURE"
        return "FEEDBACK_SKIP_DISTILL"  # fallback


class FeedbackWriter:
    """Feedback + verify 回写器。Phase 1 写入 events/asil/*.jsonl。"""

    def __init__(self, events_dir: Optional[Path] = None):
        self.events_dir = events_dir or ASIL_EVENTS_DIR
        self.events_dir.mkdir(parents=True, exist_ok=True)

    def write_verdict(self, verdict: VerdictResult, pipeline_id: str) -> Path:
        """写入 verdict 事件。"""
        path = self.events_dir / f"{pipeline_id}_verdict.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(verdict.to_dict(), ensure_ascii=False) + "\n")
        return path

    def write_pipeline_complete(self, pipeline_id: str, result: Dict[str, Any]) -> Path:
        """写入 Pipeline 完成事件。"""
        path = self.events_dir / f"{pipeline_id}_complete.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        return path
