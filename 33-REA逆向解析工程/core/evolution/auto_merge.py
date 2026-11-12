"""Auto Merge — L2-7 自动合入（`evo/*` → main，CI 机器人执行）

SPEC-33-G §2.11.4 L2-7 / §2.11.8 / §2.11.9：
  - 编排器只发合并请求；执行权在 CI 机器人（三权分立）
  - main 保护规则不放松；合入不得触发部署
  - 前置：CI 全绿 + 回滚演练通过 + 断路器关闭 + ≥30 条有效 outcome 且 ≥24h
          + held-out 对应桶 ≥20 条 + 八门禁全 pass
  - stateful 禁止自动（L2-9）；新增依赖 → L3（L2-3）；改契约/schema → L3（L2-4）

工程约束：纯标准库；复用 Governance 的角色校验，outcome 有效性复用 Policy 账本口径。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from .governance import Governance
from .policy_ledger import _is_valid_outcome, _parse_ts


class AutoMergeBlocked(ValueError):
    """自动合入前置条件不满足（硬拒绝）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AutoMergeBlocked(message)


class AutoMergeCoordinator:
    def __init__(
        self,
        governance: Governance,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        min_valid_outcomes: int = 30,
        min_observation_hours: int = 24,
        min_heldout: int = 20,
        max_files: int = 3,
        max_lines: int = 200,
    ):
        self.governance = governance
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.min_valid_outcomes = int(min_valid_outcomes)
        self.min_observation_hours = int(min_observation_hours)
        self.min_heldout = int(min_heldout)
        self.max_files = int(max_files)
        self.max_lines = int(max_lines)

    # ---------------------------------------------------------------- 请求

    def request(
        self,
        *,
        change_id: str,
        proposal_id: str,
        level: str,
        force_break_glass: bool = False,
        stateful: bool = False,
        files: Iterable[str] = (),
        lines_changed: int = 0,
        branch: str = "",
        ci_status: str = "",
        rollback_drill: Any = None,
        breaker: Optional[Dict[str, Any]] = None,
        gate_summary: Optional[Dict[str, Any]] = None,
        outcomes: Iterable[Dict[str, Any]] = (),
        heldout_bucket: int = 0,
        adds_dependency: bool = False,
        changes_contract: bool = False,
        changes_schema: bool = False,
    ) -> Dict[str, Any]:
        change_id = str(change_id or "").strip()
        proposal_id = str(proposal_id or "").strip()
        branch = str(branch or "").strip()
        _require(bool(change_id), "change_id is required")
        _require(bool(proposal_id), "proposal_id is required")
        _require(
            str(level or "").strip() == "L2",
            f"仅 L2 可自动合入（当前 {level or '<empty>'}）；L3 只出 ADR/SPEC，不进入合入通道",
        )
        _require(not stateful, "stateful 变更禁止自动合入（L2-9），须人工 + 状态恢复演练")
        _require(
            not adds_dependency,
            "新增外部依赖禁止自动合入（L2-3），须降级 L3",
        )
        _require(
            not changes_contract,
            "改公共契约禁止自动合入（L2-4），须降级 L3",
        )
        _require(
            not changes_schema,
            "改 schema 禁止自动合入（L2-4），须降级 L3",
        )

        paths = [str(path).strip() for path in (files or []) if str(path).strip()]
        _require(
            len(paths) <= self.max_files,
            f"文件数超 L2 上限（{len(paths)} > {self.max_files}）",
        )
        _require(
            int(lines_changed or 0) <= self.max_lines,
            f"改动行数超 L2 上限（{int(lines_changed or 0)} > {self.max_lines}）",
        )
        _require(
            branch.startswith("evo/"),
            f"自动合入仅允许 evo/* 分支（当前 {branch or '<empty>'}）",
        )
        _require(
            str(ci_status or "").strip() == "success",
            f"CI 未全绿（{ci_status or '<empty>'}），禁止合入",
        )
        _require(
            _drill_passed(rollback_drill),
            "回滚演练未通过（L2-5），禁止自动合入",
        )
        _require(
            not _breaker_open(breaker),
            "断路器打开/冻结，禁止自动合入",
        )
        _require(
            not force_break_glass,
            "禁止绕过门禁强制合入（force_break_glass 不被支持）",
        )
        self._require_gate_summary(gate_summary)
        self._require_observation(outcomes, change_id)
        _require(
            int(heldout_bucket or 0) >= self.min_heldout,
            f"held-out 对应桶不足 {self.min_heldout} 条（当前 {int(heldout_bucket or 0)}）",
        )

        return {
            "status": "merge_requested",
            "change_id": change_id,
            "proposal_id": proposal_id,
            "branch": branch,
            "executor": "ci_bot",
            "deploy_triggered": False,
            "main_protection": "unchanged",
            "gate_summary": gate_summary,
            "requested_at": self._now().isoformat(),
        }

    # ---------------------------------------------------------------- 执行

    def complete(
        self,
        request: Dict[str, Any],
        *,
        actor: str = "ci_bot",
        ci_status: str = "success",
    ) -> Dict[str, Any]:
        payload = dict(request or {})
        _require(
            payload.get("status") == "merge_requested",
            "合并请求无效（status != merge_requested）",
        )
        _require(
            str(ci_status or "").strip() == "success",
            f"CI 未全绿（{ci_status or '<empty>'}），禁止合入",
        )
        _require(
            not payload.get("deploy_triggered", False),
            "合并请求携带部署语义，拒绝执行（合入 ≠ 上线）",
        )
        result = self.governance.request_merge(
            actor=actor,
            change_id=payload.get("change_id"),
            proposal_id=payload.get("proposal_id"),
            gate_summary=payload.get("gate_summary") or {},
            branch=payload.get("branch"),
        )
        return {
            "status": "merged",
            "change_id": result["change_id"],
            "proposal_id": result["proposal_id"],
            "branch": result["branch"],
            "executor": actor,
            "branch_deleted": True,
            "deploy_triggered": False,
            "merged_at": self._now().isoformat(),
        }

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _require_gate_summary(gate_summary: Optional[Dict[str, Any]]) -> None:
        summary = gate_summary or {}
        gates = list(summary.get("gates") or [])
        _require(
            summary.get("overall") == "pass"
            and len(gates) >= 8
            and all(item.get("status") == "pass" for item in gates),
            "八门禁未全绿，禁止自动合入",
        )

    def _require_observation(self, outcomes: Iterable[Dict[str, Any]], change_id: str) -> None:
        valid: List[datetime] = []
        for entry in outcomes or []:
            if not _is_valid_outcome(entry):
                continue
            if str(entry.get("change_id") or "").strip() != change_id:
                continue
            parsed = _parse_ts(entry.get("created_at"))
            if parsed is not None:
                valid.append(parsed)
        _require(
            len(valid) >= self.min_valid_outcomes,
            f"有效 outcome 不足（{len(valid)}/{self.min_valid_outcomes}），禁止自动合入",
        )
        span = max(valid) - min(valid)
        _require(
            span >= timedelta(hours=self.min_observation_hours),
            f"观察期不足 {self.min_observation_hours}h（当前 {span.total_seconds() / 3600:.1f}h）",
        )

    def _now(self) -> datetime:
        return self.clock()


def _drill_passed(drill: Any) -> bool:
    if isinstance(drill, str):
        return drill == "pass"
    if isinstance(drill, dict):
        return drill.get("overall") == "pass"
    return False


def _breaker_open(breaker: Optional[Dict[str, Any]]) -> bool:
    state = str((breaker or {}).get("state") or "").strip().lower()
    return state in {"open", "frozen"} or bool((breaker or {}).get("is_auto_frozen"))
