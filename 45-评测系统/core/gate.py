# -*- coding: utf-8 -*-
"""
gate.py — 凭证签发与校验（P3-1）
=================================
职责（PLAN P3-1 验收 / SPEC §4 / §13.3）：
- `issue`：仅 PASS 报告可签发凭证；BLOCK / INCONCLUSIVE 一律拒绝（§4「不得签发凭证」）
- 凭证绑定 `eval_id + run_id + spec_hash + verdict + thresholds_version + expires_at`，
  并记录评测器版本（P2-9 版本锁定的落地：凭证自带 evaluator_id@version 供复算）
- `verify`：以库内报告为唯一事实源重算绑定并校验新鲜度（fail-closed，§2.4）
  - 未知 eval_id / 无报告 / 判定非 PASS / 绑定字段漂移 / 过期 → 拒绝
- 有效期不可续期：过期后重签同样失败，必须重新评测（防止「过期凭证刷新」）

有效期语义：判定时刻 + CREDENTIAL_TTL_DAYS（默认 7 天，§4），边界闭区间
（`now == expires_at` 即视为过期）。

边界：本模块只签发与校验凭证，不执行拦截；部署 / L0 卡点属 P3-2 / P3-3。
签名属 P4-1（`storage/evidence.py`），此处不实现。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from storage.repo import CREDENTIAL_TTL_DAYS, EvalRepo, parse_zulu, zulu

PURPOSES = ("l0_settle", "deploy")


class GateError(Exception):
    """凭证相关错误基类。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class CredentialNotIssuableError(GateError):
    """不满足签发条件（非 PASS / 无报告 / 已过期等）。"""


class CredentialInvalidError(GateError):
    """凭证校验失败（绑定漂移 / 过期 / 非 PASS 等）。"""


@dataclass(frozen=True)
class Credential:
    """门禁凭证：下游（部署 / L0）凭此放行，绑定报告全部关键字段。"""

    eval_id: str
    run_id: str
    spec_hash: str
    verdict: str
    purpose: str
    thresholds_version: str
    evaluator_id: str
    evaluator_version: str
    evidence_sha256: str
    issued_at: str
    expires_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Gate:
    """凭证签发与校验（只读库内报告，不执行评测、不修改证据）。"""

    def __init__(
        self,
        repo: EvalRepo,
        clock: Callable[[], datetime] | None = None,
        ttl_days: int = CREDENTIAL_TTL_DAYS,
    ) -> None:
        self._repo = repo
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._ttl_days = ttl_days

    # ---------- 签发 ----------

    def issue(self, eval_id: str, purpose: str | None = None) -> Credential:
        request = self._repo.get_request(eval_id)
        if request is None:
            raise CredentialNotIssuableError("unknown_eval_id", f"未知 eval_id: {eval_id}")
        report = self._repo.get_report(eval_id)
        if report is None:
            raise CredentialNotIssuableError("no_report", f"eval_id {eval_id} 尚无判定报告")
        if report["verdict"] != "PASS":
            raise CredentialNotIssuableError(
                "verdict_not_pass",
                f"verdict={report['verdict']}，仅 PASS 可签发凭证（§4）；"
                f"block_reasons={report.get('block_reasons', [])}",
            )
        target_purpose = purpose or request.purpose
        if target_purpose != request.purpose:
            raise CredentialNotIssuableError(
                "purpose_mismatch",
                f"申请 purpose={request.purpose}，请求签发 purpose={target_purpose}",
            )

        expires_at = report.get("expires_at") or zulu(
            parse_zulu(report["evaluated_at"]) + timedelta(days=self._ttl_days)
        )
        now = self._clock()
        if now >= parse_zulu(expires_at):
            raise CredentialNotIssuableError(
                "expired",
                f"报告已于 {expires_at} 过期，重签无效，需重新评测（§4）",
            )

        run = self._repo.latest_run_for_eval(eval_id)
        if run is None:
            raise CredentialNotIssuableError("no_run", f"eval_id {eval_id} 缺执行记录")

        return Credential(
            eval_id=eval_id,
            run_id=report["run_id"],
            spec_hash=report["spec_hash"],
            verdict=report["verdict"],
            purpose=target_purpose,
            thresholds_version=report["thresholds_version"],
            evaluator_id=run.evaluator_id,
            evaluator_version=run.evaluator_version,
            evidence_sha256=report["evidence"]["sha256"],
            issued_at=zulu(now),
            expires_at=expires_at,
        )

    # ---------- 校验 ----------

    def verify(self, credential: Credential, purpose: str | None = None) -> Credential:
        """以库内报告重算绑定；任一处不一致或过期即拒绝（fail-closed）。"""
        eval_id = credential.eval_id
        request = self._repo.get_request(eval_id)
        if request is None:
            raise CredentialInvalidError("unknown_eval_id", f"未知 eval_id: {eval_id}")
        report = self._repo.get_report(eval_id)
        if report is None:
            raise CredentialInvalidError("no_report", f"eval_id {eval_id} 无判定报告")
        if report["verdict"] != "PASS":
            raise CredentialInvalidError(
                "verdict_not_pass",
                f"报告 verdict={report['verdict']}，凭证无效（§4）",
            )
        if purpose is not None and purpose != request.purpose:
            raise CredentialInvalidError(
                "purpose_mismatch",
                f"申请 purpose={request.purpose}，校验 purpose={purpose}",
            )
        if credential.purpose != request.purpose:
            raise CredentialInvalidError(
                "purpose_mismatch",
                f"凭证 purpose={credential.purpose}，申请 purpose={request.purpose}",
            )

        run = self._repo.get_run(report["run_id"])
        if run is None:
            raise CredentialInvalidError("binding_mismatch", "run 记录缺失，无法校验版本绑定")

        expected = {
            "run_id": report["run_id"],
            "spec_hash": report["spec_hash"],
            "verdict": report["verdict"],
            "thresholds_version": report["thresholds_version"],
            "evidence_sha256": report["evidence"]["sha256"],
            "evaluator_id": run.evaluator_id,
            "evaluator_version": run.evaluator_version,
            "expires_at": report["expires_at"],
        }
        for field, value in expected.items():
            if getattr(credential, field) != value:
                raise CredentialInvalidError(
                    "binding_mismatch",
                    f"{field} 漂移：凭证={getattr(credential, field)!r} 报告={value!r}",
                )

        now = self._clock()
        if now >= parse_zulu(credential.expires_at):
            raise CredentialInvalidError(
                "expired",
                f"凭证已于 {credential.expires_at} 过期（now={zulu(now)}）",
            )
        return credential

    def is_valid(self, credential: Credential, purpose: str | None = None) -> bool:
        """布尔封装：校验失败返回 False（不吞异常细节，调用方可再调 verify 取 code）。"""
        try:
            self.verify(credential, purpose)
        except CredentialInvalidError:
            return False
        return True
