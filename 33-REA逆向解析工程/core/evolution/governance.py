"""Governance — T-G16 权限切分与发布治理

SPEC-33-G §2.11.8：
  - 三权分立：编排器不得同时持有提案 / 合并 / 部署三类凭据
  - 合并：仅 CI 机器人且仅 `evo/* → main`；请求必须携带 change_id + proposal_id + 门禁结论摘要
  - 部署：发布系统独占；同环境同一时刻仅 1 个发布（分布式锁，TTL 可配）
  - 人工接管：环境必须登记 owner 与 RTO/RPO，未声明不得部署
  - 分支生命周期：未合并分支 14 天归档；落后 main 超阈值告警（阈值入配置）

工程约束：纯标准库；角色→权力映射集中声明；锁文件原子替换；缺一即拒绝。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

POWER_PROPOSE = "propose"
POWER_MERGE = "merge"
POWER_DEPLOY = "deploy"
POWER_APPROVE = "approve"
TRIPLE_POWERS = {POWER_PROPOSE, POWER_MERGE, POWER_DEPLOY}

ROLE_POWERS: Dict[str, Set[str]] = {
    "orchestrator": {POWER_PROPOSE},
    "ci_bot": {POWER_MERGE},
    "release_system": {POWER_DEPLOY},
    "operator": {POWER_PROPOSE, POWER_APPROVE},
}

POWER_LABELS = {POWER_PROPOSE: "提案", POWER_MERGE: "合并", POWER_DEPLOY: "部署"}


class GovernanceError(ValueError):
    """权限 / 发布治理契约违约（硬拒绝）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GovernanceError(message)


class Governance:
    """合并 / 部署请求的唯一入口：任何绕过它的操作都视为越权。"""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        lock_ttl_seconds: int = 900,
        branch_archive_days: int = 14,
        behind_main_threshold: int = 50,
    ):
        self.root = Path(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock_ttl_seconds = int(lock_ttl_seconds)
        self.branch_archive_days = int(branch_archive_days)
        self.behind_main_threshold = int(behind_main_threshold)

    # ---------------------------------------------------------------- 权限

    def assert_power(self, actor: str, power: str) -> None:
        powers = ROLE_POWERS.get(str(actor or "").strip(), set())
        _require(
            power in powers,
            f"{actor or '<unknown>'} 没有{POWER_LABELS.get(power, power)}权限",
        )

    def validate_credentials(self, actor: str, powers: Set[str]) -> None:
        """三权分立：任一主体不得同时持有提案 + 合并 + 部署。"""
        held = set(powers or set())
        if held & TRIPLE_POWERS == TRIPLE_POWERS:
            raise GovernanceError(f"{actor} 同时持有提案/合并/部署三类凭据，违反三权分立")
        if actor == "orchestrator":
            forbidden = held & {POWER_MERGE, POWER_DEPLOY}
            _require(
                not forbidden,
                f"orchestrator 不得持有合并/部署凭据，违反三权分立：{sorted(forbidden)}",
            )
        declared = ROLE_POWERS.get(str(actor or "").strip(), set())
        _require(
            held <= declared,
            f"{actor} 声明的权力超出角色白名单：{sorted(held - declared)}",
        )

    # ---------------------------------------------------------------- 合并

    def request_merge(
        self,
        *,
        actor: str,
        change_id: str,
        proposal_id: str,
        gate_summary: Dict[str, Any],
        branch: str,
    ) -> Dict[str, Any]:
        self.assert_power(actor, POWER_MERGE)
        change_id = str(change_id or "").strip()
        proposal_id = str(proposal_id or "").strip()
        _require(bool(change_id), "change_id is required")
        _require(bool(proposal_id), "proposal_id is required")
        self._require_gate_summary(gate_summary)
        _require(
            str(branch or "").startswith("evo/"),
            f"合并仅允许 evo/* → main（当前 {branch or '<empty>'}）",
        )
        return {
            "status": "merge_requested",
            "actor": actor,
            "change_id": change_id,
            "proposal_id": proposal_id,
            "branch": branch,
            "requested_at": self._now().isoformat(),
        }

    def branch_status(
        self, *, branch: str, days_since_update: int, behind_main: int = 0
    ) -> Dict[str, Any]:
        """未合并分支 14 天归档；落后 main 超阈值告警（阈值来自配置）。"""
        stale = int(days_since_update) > self.branch_archive_days
        return {
            "branch": branch,
            "state": "archive" if stale else "active",
            "alert": int(behind_main) > self.behind_main_threshold,
            "days_since_update": int(days_since_update),
            "behind_main": int(behind_main),
        }

    # ---------------------------------------------------------------- 部署

    def request_deploy(
        self,
        *,
        actor: str,
        change_id: str,
        proposal_id: str,
        gate_summary: Dict[str, Any],
        env: str,
        owner: str,
        rto: str,
        rpo: str,
    ) -> Dict[str, Any]:
        self.assert_power(actor, POWER_DEPLOY)
        change_id = str(change_id or "").strip()
        proposal_id = str(proposal_id or "").strip()
        env = str(env or "").strip()
        _require(bool(change_id), "change_id is required")
        _require(bool(proposal_id), "proposal_id is required")
        _require(bool(env), "env is required")
        self._require_gate_summary(gate_summary)
        _require(bool(str(owner or "").strip()), "环境 owner 未登记，不得开启自动部署")
        _require(bool(str(rto or "").strip()), "环境 RTO 未声明")
        _require(bool(str(rpo or "").strip()), "环境 RPO 未声明")

        lock = self._acquire_lock(env, change_id)
        return {
            "status": "deploy_requested",
            "actor": actor,
            "env": env,
            "change_id": change_id,
            "proposal_id": proposal_id,
            "owner": owner,
            "requested_at": self._now().isoformat(),
            "lock": lock,
        }

    def release_deploy(self, *, env: str, change_id: str) -> None:
        path = self._lock_path(env)
        lock = self.deploy_lock(env)
        _require(
            lock is not None and lock.get("change_id") == change_id,
            f"发布锁不存在或不属于 {change_id}，拒绝释放",
        )
        path.unlink()

    def deploy_lock(self, env: str) -> Optional[Dict[str, Any]]:
        path = self._lock_path(env)
        if not path.is_file():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return loaded if isinstance(loaded, dict) else None

    # ---------------------------------------------------------------- 内部

    def _require_gate_summary(self, gate_summary: Dict[str, Any]) -> None:
        summary = gate_summary or {}
        gates = summary.get("gates") or []
        _require(
            summary.get("overall") == "pass"
            and len(gates) == 8
            and all(item.get("status") == "pass" for item in gates),
            "门禁结论摘要必须为 8 项全 pass（缺一拒绝合并/部署）",
        )

    def _lock_path(self, env: str) -> Path:
        return self.root / "deploy_locks" / f"{env}.json"

    def _acquire_lock(self, env: str, change_id: str) -> Dict[str, Any]:
        now = self._now()
        existing = self.deploy_lock(env)
        if existing is not None:
            expires = self._parse(existing.get("expires_at"))
            if existing.get("change_id") == change_id:
                return existing
            if expires is not None and now < expires:
                raise GovernanceError(
                    f"同环境发布锁未释放：{env} 正由 {existing.get('change_id')} 占用"
                )
        lock = {
            "env": env,
            "change_id": change_id,
            "acquired_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.lock_ttl_seconds)).isoformat(),
            "ttl_seconds": self.lock_ttl_seconds,
        }
        path = self._lock_path(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return lock

    @staticmethod
    def _parse(value: Any) -> Optional[datetime]:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _now(self) -> datetime:
        return self.clock()
