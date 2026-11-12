"""Executor — T-G8 沙箱 / 影子 / 回滚执行器

SPEC-33-G：
  - §2.7 沙箱三组 + 隔离（禁写认知库 / 禁 git push / 禁外网）
  - §2.7.1 影子门槛（section ≥20 次且 ≥24h、held-out 不降、degraded 不高于基线、P95 ≤+20%）
  - §2.6 自动回滚 + 污染回滚；回滚 ≤60s
  - §2.11.4 L2-9 / §4 硬约束 8、10、21

工程约束：纯标准库；runner 注入可离线测试；隔离开关一旦打开直接拒绝。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from .pollution import PollutionRollback

ROLLBACK_BUDGET_SECONDS = 60.0
MIN_SHADOW_CALLS = 20
MIN_SHADOW_HOURS = 24.0
MAX_P95_INCREASE_PCT = 20.0
MIN_ATTRIBUTION_RATIO = 0.8
MIN_OUTCOMES = 30
MIN_OBSERVE_HOURS = 24.0


class SandboxIsolationError(RuntimeError):
    """沙箱隔离被破坏。"""


class RollbackBudgetExceeded(RuntimeError):
    """回滚超出 60s 预算。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- 沙箱


class SandboxRunner:
    """三组沙箱执行；A/B/C 缺一即 fail，隔离开关为 True 直接拒绝。"""

    def __init__(
        self,
        runners: Dict[str, Callable[[Dict[str, Any]], Any]],
        *,
        root: Optional[str | Path] = None,
        allow_cognition_write: bool = False,
        allow_git_push: bool = False,
        allow_network: bool = False,
    ):
        if allow_cognition_write:
            raise SandboxIsolationError("沙箱禁止写认知库")
        if allow_git_push:
            raise SandboxIsolationError("沙箱禁止 git push")
        if allow_network:
            raise SandboxIsolationError("沙箱禁止外网")
        self.runners = dict(runners)
        self.root = Path(root) if root is not None else None

    def run(self, change_id: str) -> Dict[str, Any]:
        workspace = None
        if self.root is not None:
            workspace = self.root / "sandbox" / change_id
            workspace.mkdir(parents=True, exist_ok=True)
        context = {
            "change_id": change_id,
            "workspace": str(workspace) if workspace is not None else None,
            "read_only": True,
        }
        groups: Dict[str, Dict[str, Any]] = {}
        for name in ("A", "B", "C"):
            runner = self.runners.get(name)
            if runner is None:
                groups[name] = {"status": "fail", "detail": "缺少沙箱组"}
                continue
            try:
                result = runner(context)
            except Exception as exc:  # noqa: BLE001 - 沙箱任何异常都视为该组失败
                groups[name] = {"status": "fail", "detail": f"{type(exc).__name__}: {exc}"}
                continue
            if isinstance(result, str):
                result = {"status": result}
            status = result.get("status") if isinstance(result, dict) else "fail"
            groups[name] = {
                "status": status if status in ("pass", "fail") else "fail",
                "detail": result.get("detail", "") if isinstance(result, dict) else "",
            }
        overall = "pass" if all(item["status"] == "pass" for item in groups.values()) else "fail"
        return {"change_id": change_id, "overall": overall, "groups": groups}


# ---------------------------------------------------------------- 影子


class ShadowEvaluator:
    """按 section 评估影子期；输出可直接喂给八门禁第 4 条。"""

    def evaluate(self, sections: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        statuses: Dict[str, str] = {}
        details: Dict[str, Dict[str, Any]] = {}
        for name, section in (sections or {}).items():
            status, reasons = self._evaluate_section(section or {})
            statuses[name] = status
            details[name] = {"status": status, "reasons": reasons}

        values = set(statuses.values())
        overall = "fail" if "fail" in values else ("hold" if "hold" in values else "pass")
        if not statuses:
            overall = "hold"
        return {"overall": overall, "sections": statuses, "details": details}

    @staticmethod
    def _evaluate_section(section: Dict[str, Any]) -> tuple[str, list]:
        status = "pass"
        reasons: list = []

        if int(section.get("calls") or 0) < MIN_SHADOW_CALLS:
            status = "hold"
            reasons.append(f"section 调用 {section.get('calls')} < {MIN_SHADOW_CALLS}")
        if float(section.get("duration_hours") or 0.0) < MIN_SHADOW_HOURS:
            status = "hold"
            reasons.append(f"影子时长 {section.get('duration_hours')}h < {MIN_SHADOW_HOURS}h")

        if float(section.get("heldout_after") or 0.0) < float(section.get("heldout_before") or 0.0):
            status = "fail"
            reasons.append("held-out 指标下降")

        degraded = float(section.get("degraded") or 0.0)
        baseline = float(section.get("degraded_baseline_7d") or 0.0)
        if degraded > baseline:
            status = "fail"
            reasons.append(f"degraded {degraded} 高于 7 天基线 {baseline}")

        p95_before = float(section.get("p95_before_ms") or 0.0)
        p95_after = float(section.get("p95_after_ms") or 0.0)
        if p95_before > 0:
            increase = (p95_after - p95_before) / p95_before * 100.0
            if increase > MAX_P95_INCREASE_PCT:
                status = "fail"
                reasons.append(f"P95 延迟增幅 {increase:.1f}% > {MAX_P95_INCREASE_PCT}%")

        diffs = list(section.get("diffs") or [])[:20]
        if any(not item.get("attributed") for item in diffs):
            status = "fail"
            reasons.append("出现 expected_effect 范围外差异")
        elif diffs:
            ratio = sum(1 for item in diffs if item.get("attributed")) / len(diffs)
            if ratio < MIN_ATTRIBUTION_RATIO:
                status = "fail"
                reasons.append(f"归因率 {ratio:.0%} < {MIN_ATTRIBUTION_RATIO:.0%}")

        return status, reasons


# ---------------------------------------------------------------- 自动回滚判定


def evaluate_observation(
    before: Dict[str, Any],
    after: Dict[str, Any],
    *,
    min_outcomes: int = MIN_OUTCOMES,
    min_hours: float = MIN_OBSERVE_HOURS,
) -> Dict[str, Any]:
    """观察期判定：样本不足 continue；指标劣化 rollback；否则 confirm。"""
    outcomes: Iterable[Dict[str, Any]] = after.get("outcomes") or []
    stamps = []
    for entry in outcomes:
        if not str(entry.get("change_id") or "").strip():
            continue
        if not str(entry.get("run_id") or "").strip():
            continue
        seq = entry.get("outcome_seq")
        if isinstance(seq, bool) or not isinstance(seq, int):
            continue
        parsed = _parse_ts(entry.get("created_at"))
        if parsed is not None:
            stamps.append(parsed)

    if len(stamps) < min_outcomes:
        return {"decision": "continue", "reason": f"有效 outcome {len(stamps)} < {min_outcomes}"}
    span_hours = (max(stamps) - min(stamps)).total_seconds() / 3600.0
    if span_hours < min_hours:
        return {"decision": "continue", "reason": f"观察期 {span_hours:.1f}h < {min_hours}h"}

    if float(after.get("heldout_recall") or 0.0) < float(before.get("heldout_recall") or 0.0):
        return {"decision": "rollback", "reason": "held-out 指标下降"}
    if float(after.get("error_rate") or 0.0) > float(before.get("error_rate") or 0.0):
        return {"decision": "rollback", "reason": "错误率上升"}
    return {"decision": "confirm", "reason": ""}


# ---------------------------------------------------------------- 回滚执行


class RollbackExecutor:
    """按 manifest 还原文件；stateful 必须提供状态恢复；污染回滚一并执行。"""

    def __init__(self, ledger: Any, *, clock: Callable[[], float] = time.monotonic):
        self.ledger = ledger
        self.clock = clock

    def rollback_policy(
        self,
        policy_id: str,
        *,
        workspace_root: str | Path,
        stateful: bool = False,
        state_restore: Any = None,
        pollution: Optional[PollutionRollback] = None,
        reason: str = "manual",
    ) -> Dict[str, Any]:
        start = self.clock()
        record = self.ledger.get(policy_id)
        if record is None:
            raise ValueError(f"policy not found: {policy_id}")

        verification = self.ledger.verify_backup(policy_id)
        if not verification.get("verified"):
            raise ValueError(f"备份不可用: {verification.get('reason')}")

        bundle = self.ledger.bundle_dir(policy_id)
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest.get("entries") or []:
            source = bundle / entry["backup_path"]
            target = Path(workspace_root) / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        if stateful:
            if state_restore is None:
                raise ValueError("stateful 变更缺少状态恢复脚本，不得回滚完成")
            if callable(state_restore):
                state_restore()
            else:
                subprocess.run([str(state_restore)], check=True)

        pollution_count = 0
        if pollution is not None:
            report = pollution.rollback(
                policy_id=policy_id, report_path=bundle / "pollution_report.json"
            )
            pollution_count = int(report.get("cases_tainted") or 0) + int(
                report.get("evidence_tainted") or 0
            )

        duration = self.clock() - start
        if duration > ROLLBACK_BUDGET_SECONDS:
            raise RollbackBudgetExceeded(
                f"回滚耗时 {duration:.1f}s 超过 {ROLLBACK_BUDGET_SECONDS}s 预算"
            )

        self.ledger.mark_rolled_back(
            policy_id,
            reason=reason,
            duration_s=duration,
            pollution_count=pollution_count,
        )
        event = {
            "policy_id": policy_id,
            "status": "rolled_back",
            "reason": reason,
            "duration_s": duration,
            "pollution_count": pollution_count,
            "created_at": _now(),
        }
        (bundle / "rollback_event.json").write_text(
            json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return event
