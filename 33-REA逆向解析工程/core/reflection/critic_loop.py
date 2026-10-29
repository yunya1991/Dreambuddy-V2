"""P5 批评自循环：发现矛盾 → 提出假说 → 回放验证 → 观察期 → 采纳/回滚。

SPEC-33-反思层 v0.3 §6.2：
- 批评可信度 = A8 式自评 + 独立验证加成（最高 +40%）
- 观察期：改进建议观察 3 个分析任务周期，期内仅记录不部署
- 客观回滚条件：poe_score 下降 >15 分 24h 内回滚；
  证据链完整度下降立即回滚；分析成本上升 >50% 48h 内回滚
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .replay_simulator import ReplayPool

# 观察期长度（分析任务周期数）
OBSERVATION_PERIOD = 3
# 客观回滚阈值
POE_DROP_ROLLBACK = 15.0
COST_RISE_ROLLBACK = 0.5
# 独立验证加成上限
INDEPENDENT_BONUS_MAX = 0.4


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class CriticProposal:
    """一条改进建议（批评自循环的工作单元）。"""

    proposal_id: str
    hypothesis: str
    contradiction: str
    self_score: float = 0.5
    independently_verified: bool = False
    status: str = "proposed"  # proposed / observing / adopted / rolled_back
    observed_tasks: int = 0
    baseline: Dict[str, float] = field(default_factory=dict)
    created_at: int = field(default_factory=_now_ms)

    @property
    def credibility(self) -> float:
        """批评可信度 = 自评 + 独立验证加成（最高 +40%）。"""
        bonus = INDEPENDENT_BONUS_MAX if self.independently_verified else 0.0
        return min(1.0, self.self_score + bonus)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "hypothesis": self.hypothesis,
            "contradiction": self.contradiction,
            "self_score": self.self_score,
            "independently_verified": self.independently_verified,
            "credibility": self.credibility,
            "status": self.status,
            "observed_tasks": self.observed_tasks,
            "baseline": self.baseline,
            "created_at": self.created_at,
        }


class CriticLoop:
    """批评自循环：矛盾驱动的改进建议生命周期管理。"""

    def __init__(self, pool: Optional[ReplayPool] = None):
        self.pool = pool
        self.proposals: List[CriticProposal] = []

    def propose(self, contradiction: str, hypothesis: str,
                self_score: float = 0.5) -> CriticProposal:
        """发现矛盾 → 提出假说（进入回放验证）。"""
        proposal = CriticProposal(
            proposal_id=f"cp_{len(self.proposals):04d}",
            hypothesis=hypothesis,
            contradiction=contradiction,
            self_score=max(0.0, min(1.0, self_score)),
        )
        proposal.status = self._replay_verify(proposal)
        self.proposals.append(proposal)
        return proposal

    def _replay_verify(self, proposal: CriticProposal) -> str:
        """回放模拟器验证：池可用且可评估时进入观察期，否则保持 proposed。"""
        if self.pool is None or not self.pool.eval_ready():
            return "proposed"
        proposal.independently_verified = True
        return "observing"

    def record_task(self, proposal_id: str, poe_score: float,
                    evidence_completeness: float, cost_calls: int) -> Dict[str, Any]:
        """观察期内记录一个分析任务周期的指标，并执行客观回滚判定。

        返回 {status, rolled_back, reason}。
        """
        proposal = self._get(proposal_id)
        if proposal.status != "observing":
            return {"status": proposal.status, "rolled_back": False, "reason": "not observing"}
        if not proposal.baseline:
            proposal.baseline = {
                "poe_score": poe_score,
                "evidence_completeness": evidence_completeness,
                "cost_calls": float(cost_calls),
            }
        # 客观回滚条件
        if evidence_completeness < proposal.baseline["evidence_completeness"]:
            proposal.status = "rolled_back"
            return {"status": "rolled_back", "rolled_back": True,
                    "reason": "evidence completeness dropped"}
        if proposal.baseline["poe_score"] - poe_score > POE_DROP_ROLLBACK:
            proposal.status = "rolled_back"
            return {"status": "rolled_back", "rolled_back": True,
                    "reason": "poe_score dropped over threshold"}
        base_cost = proposal.baseline["cost_calls"]
        if base_cost > 0 and (cost_calls - base_cost) / base_cost > COST_RISE_ROLLBACK:
            proposal.status = "rolled_back"
            return {"status": "rolled_back", "rolled_back": True,
                    "reason": "cost rose over threshold"}
        # 观察期推进
        proposal.observed_tasks += 1
        if proposal.observed_tasks >= OBSERVATION_PERIOD:
            proposal.status = "adopted"
            return {"status": "adopted", "rolled_back": False, "reason": "observation passed"}
        return {"status": "observing", "rolled_back": False, "reason": "within observation"}

    def _get(self, proposal_id: str) -> CriticProposal:
        for p in self.proposals:
            if p.proposal_id == proposal_id:
                return p
        raise KeyError(f"proposal not found: {proposal_id}")

    def summary(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        for p in self.proposals:
            by_status[p.status] = by_status.get(p.status, 0) + 1
        return {
            "total": len(self.proposals),
            "by_status": by_status,
            "proposals": [p.to_dict() for p in self.proposals],
        }
