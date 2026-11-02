# -*- coding: utf-8 -*-
"""
test_e2e_full_chain.py — 完整链路端到端测试
===========================================
链路（SPEC §4/§13/§14）：
受理（Gateway）→ 排队（Runner）→ 执行（评测项产出）→ 报告（Reporter）
→ 门禁判定（三态合成）→ 凭证签发（Gate）→ 强制卡点（Enforcer：deploy/l0_settle）

覆盖：
- 正向：全硬性项通过 + 加权项达标 → PASS → 凭证签发 → 部署/沉淀放行
- 反向1：硬性项失败 → BLOCK → 不签发凭证 → 部署被拒
- 反向2：评测未完成（无报告）→ 部署被拒（fail-closed）
- 反向3：未注册 spec → 受理即拒
- 反向4：27 双凭证缺失 → 策略上线被拒
- 幂等：同 Idempotency-Key 重放返回同一 eval_id
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest  # noqa: E402

from core.enforcement import Enforcer  # noqa: E402
from core.gateway import CategoriesConfig, Gateway  # noqa: E402
from core.gate import Gate  # noqa: E402
from core.reporter import Reporter  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.runner import Runner  # noqa: E402
from core.spec_registry import SpecRegistry, SpecRegistryError  # noqa: E402
from storage.repo import EvalItemRecord, EvalRunRecord, InMemoryRepo  # noqa: E402

NOW = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)


def make_spec(**overrides) -> dict:
    spec = {
        "spec_id": "EVS-20261102-0001",
        "version": "1.0.0",
        "category": "engineering",
        "object_type": "code_artifact",
        "evaluator_ref": "EV-engineering.scan@1.0.0",
        "scorers": [{"id": "SC-code@1.0.0", "role": "primary"}],
        "thresholds_ref": "TH-2026Q4@1",
        "created_by": "e2e",
    }
    spec.update(overrides)
    return spec


def make_payload(spec_id="EVS-20261102-0001"):
    return {
        "object_ref": "git://repo/service@abc123",
        "category": "engineering",
        "object_type": "code_artifact",
        "submitter": "e2e-test",
        "purpose": "deploy",
        "spec_id": spec_id,
        "env_manifest": {
            "runtime": "docker",
            "endpoints": ["http://127.0.0.1:9000/health"],
            "resources": [],
        },
    }


class Chain:
    """端到端链路组装：受理→排队→执行→报告→凭证→卡点（同一 repo 贯穿）。"""

    def __init__(self, shadow=False, approvals=None):
        self.repo = InMemoryRepo()
        self.spec_registry = SpecRegistry()
        self.spec_registry.register(make_spec())
        self.gateway = Gateway(
            self.repo,
            CategoriesConfig.load(),
            clock=lambda: NOW,
            spec_registry=self.spec_registry,
        )
        self.reporter = Reporter(
            repo=self.repo, thresholds=ThresholdRegistry.load(), clock=lambda: NOW
        )
        self.runner = Runner(repo=self.repo, reporter=self.reporter)
        self.gate = Gate(repo=self.repo, clock=lambda: NOW)
        self.enforcer = Enforcer(
            gate=self.gate, shadow=shadow, approvals=approvals, clock=lambda: NOW
        )

    def submit(self, payload, key):
        return self.gateway.submit(payload, idempotency_key=key)

    def execute_with_items(self, eval_id, items_builder):
        """入队 → 出队执行：执行器产出评测项并走报告收尾。"""
        self.runner.enqueue(eval_id)

        def executor(eid):
            run, items = items_builder(eid)
            return self.reporter.finalize(eid, run, items)

        self.runner._executor = executor
        return self.runner.run_once(timeout=1.0)


def _run_record(eval_id, spec_hash):
    return EvalRunRecord(
        run_id=f"RUN-{eval_id}",
        eval_id=eval_id,
        evaluator_id="EV-engineering.scan",
        evaluator_version="1.0.0",
        scorer_versions=None,
        attempt=1,
        spec_hash=spec_hash,
        code_commit=None,
        env_snapshot=None,
        budget_ms=60000,
        degraded=False,
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=5),
        status="succeeded",
    )


def _item(eval_id, run_id, name, kind, score, status, n=None, ci=None, weight=None, detail=None):
    return EvalItemRecord(
        item_id=f"{eval_id}-{name}",
        run_id=run_id,
        name=name,
        kind=kind,
        score=score,
        n=n,
        ci_lower=ci[0] if ci else None,
        ci_upper=ci[1] if ci else None,
        weight=weight,
        status=status,
        evidence_id=f"EV-{eval_id}-{name}",
        detail=detail,
    )


def pass_items(eval_id, spec_hash):
    run = _run_record(eval_id, spec_hash)
    items = [
        _item(eval_id, run.run_id, "E-H1", "hard", 1.0, "PASS", n=1),
        _item(
            eval_id, run.run_id, "E-W1", "weighted", 0.97, "PASS",
            n=500, ci=(0.95, 0.98), weight=1.0,
        ),
    ]
    return run, items


def block_items(eval_id, spec_hash):
    run = _run_record(eval_id, spec_hash)
    items = [
        _item(eval_id, run.run_id, "E-H1", "hard", 0.0, "BLOCK", n=1, detail="secret scanning 命中"),
        _item(
            eval_id, run.run_id, "E-W1", "weighted", 0.97, "PASS",
            n=500, ci=(0.95, 0.98), weight=1.0,
        ),
    ]
    return run, items


class TestFullChainPass:
    def test_full_chain_pass_issues_credential_and_allows_deploy(self):
        chain = Chain()
        result = chain.submit(make_payload(), key="e2e-key-1")
        assert result.status == "accepted"
        eval_id = result.eval_id

        outcome = chain.execute_with_items(
            eval_id, lambda eid: pass_items(eid, result.spec_hash)
        )
        assert outcome is not None and outcome.status == "succeeded"

        report = chain.repo.get_report(eval_id)
        assert report["verdict"] == "PASS"
        assert report["score"] > 0

        # 部署放行：凭证用途与受理用途绑定（§4）
        cred_deploy = chain.gate.issue(eval_id, purpose="deploy")
        assert cred_deploy.eval_id == eval_id
        decision = chain.enforcer.enforce("deploy", eval_id, credential=cred_deploy)
        assert decision.allowed is True

        # 用途绑定校验：deploy 申请不可签发 l0_settle 凭证（fail-closed）
        with pytest.raises(Exception, match="purpose_mismatch"):
            chain.gate.issue(eval_id, purpose="l0_settle")

        # 沉淀放行：单独提交 l0_settle 用途的评测申请走完整链路
        payload_settle = make_payload()
        payload_settle["purpose"] = "l0_settle"
        r2 = chain.submit(payload_settle, key="e2e-key-1-settle")
        chain.execute_with_items(
            r2.eval_id, lambda eid: pass_items(eid, r2.spec_hash)
        )
        assert chain.repo.get_report(r2.eval_id)["verdict"] == "PASS"
        cred_settle = chain.gate.issue(r2.eval_id, purpose="l0_settle")
        settle = chain.enforcer.enforce("l0_settle", r2.eval_id, credential=cred_settle)
        assert settle.allowed is True


class TestFullChainBlock:
    def test_hard_fail_blocks_and_deploy_rejected(self):
        chain = Chain()
        result = chain.submit(make_payload(), key="e2e-key-2")
        eval_id = result.eval_id

        chain.execute_with_items(eval_id, lambda eid: block_items(eid, result.spec_hash))

        report = chain.repo.get_report(eval_id)
        assert report["verdict"] == "BLOCK"

        with pytest.raises(Exception, match="仅 PASS 可签发凭证"):
            chain.gate.issue(eval_id, purpose="deploy")

        decision = chain.enforcer.enforce("deploy", eval_id)
        assert decision.allowed is False


class TestFailClosed:
    def test_deploy_without_report_rejected(self):
        chain = Chain()
        result = chain.submit(make_payload(), key="e2e-key-3")
        # 只受理未执行：无报告 → 无凭证 → 部署被拒
        decision = chain.enforcer.enforce("deploy", result.eval_id)
        assert decision.allowed is False

    def test_unregistered_spec_rejected_at_gateway(self):
        chain = Chain()
        with pytest.raises(SpecRegistryError, match="spec 未注册"):
            chain.submit(make_payload(spec_id="EVS-20261102-9999"), key="e2e-key-4")

    def test_strategy_deploy_requires_27_approval(self):
        chain = Chain()
        payload = make_payload()
        payload["category"] = "finance"
        payload["object_type"] = "strategy"
        chain.spec_registry.register(
            make_spec(
                spec_id="EVS-20261102-0002",
                category="finance",
                object_type="strategy",
                evaluator_ref="EV-finance.backtest@1.2.0",
            )
        )
        payload["spec_id"] = "EVS-20261102-0002"
        result = chain.submit(payload, key="e2e-key-5")
        chain.execute_with_items(
            result.eval_id, lambda eid: pass_items(eid, result.spec_hash)
        )
        credential = chain.gate.issue(result.eval_id, purpose="deploy")
        decision = chain.enforcer.enforce(
            "deploy", result.eval_id, credential=credential, require_approval=True
        )
        assert decision.allowed is False
        assert any("27 审批凭证" in r for r in decision.reasons)


class TestIdempotency:
    def test_replay_returns_same_eval_id(self):
        chain = Chain()
        r1 = chain.submit(make_payload(), key="e2e-key-6")
        r2 = chain.submit(make_payload(), key="e2e-key-6")
        assert r1.eval_id == r2.eval_id
        assert r1.spec_hash == r2.spec_hash
