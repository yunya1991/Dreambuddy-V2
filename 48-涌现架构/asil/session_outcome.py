"""ASIL Session Outcome 结构化落盘。

Phase 2：扫描 .cognitive/sessions/ 结构化 session outcome，
产出 accept/edit/reject 弱监督信号供 verify 使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SessionOutcome:
    """结构化 session outcome（SPEC §3.6 schema）。"""

    session_id: str = ""
    timestamp: str = ""
    intent_predicted: str = ""
    intent_actual: str = ""
    outcome_success: bool = False
    outcome_correction: bool = False
    correction_type: str = ""  # accept / edit / reject
    recall_hit_rate: float = 0.0
    time_to_action_ms: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "intent": {
                "predicted": self.intent_predicted,
                "actual": self.intent_actual,
                "correction": self.correction_type,
            },
            "outcome": {
                "success": self.outcome_success,
                "correction": self.outcome_correction,
                "correction_type": self.correction_type,
            },
            "recall_effectiveness": {"hit_rate": self.recall_hit_rate},
            "time_to_action_ms": self.time_to_action_ms,
            "errors": self.errors,
        }


class SessionOutcomeCollector:
    """Session outcome 收集器 — 从 .cognitive/sessions/ 扫描。"""

    def __init__(self, sessions_dir: Optional[Path] = None):
        if sessions_dir is None:
            home = Path.home()
            self.sessions_dir = home / ".cognitive" / "sessions"
        else:
            self.sessions_dir = sessions_dir
        self.outcomes: List[SessionOutcome] = []

    def scan(self, max_sessions: int = 20) -> List[SessionOutcome]:
        """扫描 session 目录，结构化 outcome。Phase 2 stub：用已有 sessions 文件。"""
        self.outcomes = []
        if not self.sessions_dir.exists():
            return self.outcomes

        # 找最新的 session 文件
        files = sorted(
            self.sessions_dir.glob("*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:max_sessions]

        for f in files:
            outcome = self._parse_session_file(f)
            if outcome:
                self.outcomes.append(outcome)
        return self.outcomes

    def _parse_session_file(self, path: Path) -> Optional[SessionOutcome]:
        """Phase 2 stub：解析 session 文件。

        真实 session 格式未知，这里用启发式提取。
        """
        try:
            text = path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            return None

        outcome = SessionOutcome(session_id=path.name)
        outcome.timestamp = str(path.stat().st_mtime)

        # 启发式：session 含 "reject" / "edit" / "accept" 关键词
        text_lower = text.lower()
        if "reject" in text_lower:
            outcome.correction_type = "reject"
            outcome.outcome_correction = True
            outcome.outcome_success = False
        elif "edit" in text_lower or "修正" in text:
            outcome.correction_type = "edit"
            outcome.outcome_correction = True
            outcome.outcome_success = True
        else:
            outcome.correction_type = "accept"
            outcome.outcome_success = True

        return outcome

    def summary_stats(self) -> Dict[str, Any]:
        """汇总统计（供 trigger_scanner.active_reflection 使用）。"""
        if not self.outcomes:
            return {"n_total": 0, "n_fail": 0, "fail_ratio": 0.0}
        n_fail = sum(1 for o in self.outcomes if not o.outcome_success)
        return {
            "n_total": len(self.outcomes),
            "n_fail": n_fail,
            "fail_ratio": round(n_fail / len(self.outcomes), 3),
        }
