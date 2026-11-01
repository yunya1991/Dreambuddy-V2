# -*- coding: utf-8 -*-
"""
test_api.py — P0-6 API + CLI 契约测试
======================================
验收（PLAN P0-6 / SPEC §13）：
- submit：Idempotency-Key 强制；202 回执；幂等重放同一 eval_id；非法请求 400
- get：§13.2 字段齐备（verdict/score/n/ci/evidence_uri/block_reasons/sla/run_spec_hash）
- list：submitter/category/verdict/from/to 过滤；非法参数 400
- delete：仅 queued/running 可取消（200）；其余 409；未知 404
- evalctl gate：退出码 0=PASS / 2=BLOCK / 3=INCONCLUSIVE / 4=ERROR（§13.4）
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.cli import EXIT_BLOCK, EXIT_ERROR, EXIT_INCONCLUSIVE, EXIT_PASS, main  # noqa: E402
from api.routes import create_app  # noqa: E402
from core.gateway import CategoriesConfig, Gateway, spec_hash_placeholder  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.reporter import Reporter  # noqa: E402
from core.runner import Runner  # noqa: E402
from storage.repo import EvalItemRecord, EvalRunRecord, InMemoryRepo  # noqa: E402

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
SPEC_HASH = spec_hash_placeholder("EVS-20261101-0001")

VALID_ENV_MANIFEST = {
    "runtime": "python3.11",
    "endpoints": ["https://object.local/health"],
}


def make_payload(
    category: str = "finance",
    object_type: str = "strategy",
    submitter: str = "trader-01",
) -> dict:
    return {
        "object_ref": "git://repo/strategy@abc123",
        "category": category,
        "object_type": object_type,
        "submitter": submitter,
        "purpose": "l0_settle",
        "priority": "normal",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": dict(VALID_ENV_MANIFEST),
    }


def make_run(eval_id: str, tag: str = "01") -> EvalRunRecord:
    return EvalRunRecord(
        run_id=f"RUN-{eval_id.removeprefix('EV-')}-{tag}",
        eval_id=eval_id,
        evaluator_id="EV-test.stub",
        evaluator_version="1.0.0",
        scorer_versions=None,
        attempt=1,
        spec_hash=SPEC_HASH,
        code_commit="abc123",
        env_snapshot=None,
        budget_ms=60_000,
        degraded=False,
        started_at=NOW,
        ended_at=NOW,
        status="succeeded",
    )


def make_item(
    run_id: str,
    kind: str = "weighted",
    status: str = "PASS",
    item_id: str = "IT-01",
) -> EvalItemRecord:
    return EvalItemRecord(
        item_id=item_id,
        run_id=run_id,
        name=f"item-{kind}-{status}",
        kind=kind,
        score=0.85 if kind == "weighted" else None,
        n=150 if kind == "weighted" else None,
        ci_lower=0.80,
        ci_upper=0.90,
        weight=1.0 if kind == "weighted" else None,
        status=status,
        evidence_id=None,
        detail=None,
    )


@pytest.fixture()
def stack():
    """内存装配：repo + gateway + reporter + TestClient（固定时钟）。"""
    repo = InMemoryRepo()
    categories = CategoriesConfig.load()
    gateway = Gateway(store=repo, categories=categories, clock=lambda: NOW)
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: NOW)
    client = TestClient(create_app(repo=repo, gateway=gateway, reporter=reporter))
    return repo, gateway, reporter, client


def submit(client: TestClient, key: str = "key-001", payload: dict | None = None):
    return client.post(
        "/api/v1/eval/submit",
        json=payload or make_payload(),
        headers={"Idempotency-Key": key},
    )


# ---------- submit（§13.1） ----------


def test_submit_accepted_202(stack):
    _, _, _, client = stack
    resp = submit(client)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["eval_id"].startswith("EV-20261101-")
    assert body["spec_hash"] == SPEC_HASH


def test_submit_enqueues_when_runner_attached(stack):
    """P1-2 接线：装配 runner 时受理成功即入队（默认不装配，避免隐式跑评测）。"""
    repo, gateway, reporter, _ = stack
    runner = Runner(repo=repo, reporter=reporter)
    client = TestClient(create_app(repo=repo, gateway=gateway, reporter=reporter, runner=runner))
    resp = submit(client)
    assert resp.status_code == 202
    assert len(runner.queue) == 1


def test_submit_idempotent_replay_same_eval_id(stack):
    _, _, _, client = stack
    first = submit(client, key="dup-1").json()
    replay = submit(client, key="dup-1").json()
    assert replay["eval_id"] == first["eval_id"]
    assert replay["spec_hash"] == first["spec_hash"]


def test_submit_missing_idempotency_key_400(stack):
    _, _, _, client = stack
    resp = client.post("/api/v1/eval/submit", json=make_payload())
    assert resp.status_code == 400
    assert "Idempotency-Key" in resp.json()["detail"]


def test_submit_blank_idempotency_key_400(stack):
    _, _, _, client = stack
    resp = client.post(
        "/api/v1/eval/submit", json=make_payload(), headers={"Idempotency-Key": "  "}
    )
    assert resp.status_code == 400


def test_submit_schema_invalid_400(stack):
    _, _, _, client = stack
    payload = make_payload()
    del payload["object_ref"]
    resp = submit(client, payload=payload)
    assert resp.status_code == 400
    assert "object_ref" in resp.json()["detail"]


def test_submit_category_mismatch_400(stack):
    _, _, _, client = stack
    resp = submit(client, payload=make_payload(category="finance", object_type="model"))
    assert resp.status_code == 400
    assert "不匹配" in resp.json()["detail"]


# ---------- get（§13.2） ----------


def test_get_unknown_404(stack):
    _, _, _, client = stack
    assert client.get("/api/v1/eval/EV-20990101-000001").status_code == 404


def test_get_queued_without_report(stack):
    _, _, _, client = stack
    eval_id = submit(client).json()["eval_id"]
    body = client.get(f"/api/v1/eval/{eval_id}").json()
    assert body["status"] == "queued"
    assert body["verdict"] is None
    assert body["score"] is None
    assert body["block_reasons"] == []
    assert body["run_spec_hash"] == SPEC_HASH


def test_get_after_finalize_report_fields(stack):
    _, _, reporter, client = stack
    eval_id = submit(client).json()["eval_id"]
    reporter.finalize_empty(eval_id)  # 空评测 → INCONCLUSIVE（fail-closed）
    body = client.get(f"/api/v1/eval/{eval_id}").json()
    assert body["status"] == "succeeded"
    assert body["verdict"] == "INCONCLUSIVE"
    assert body["block_reasons"]
    assert body["evidence_uri"].startswith("local://evidence/")
    assert body["run_spec_hash"] == SPEC_HASH


# ---------- list（§13.2） ----------


def test_list_filters(stack):
    _, _, reporter, client = stack
    id_a = submit(client, key="k-a").json()["eval_id"]  # finance strategy trader-01
    submit(client, key="k-b", payload=make_payload(submitter="trader-02"))
    reporter.finalize_empty(id_a)  # id_a → INCONCLUSIVE

    all_items = client.get("/api/v1/eval").json()
    assert all_items["count"] == 2

    by_submitter = client.get("/api/v1/eval", params={"submitter": "trader-02"}).json()
    assert by_submitter["count"] == 1
    assert by_submitter["items"][0]["submitter"] == "trader-02"

    by_verdict = client.get("/api/v1/eval", params={"verdict": "INCONCLUSIVE"}).json()
    assert by_verdict["count"] == 1
    assert by_verdict["items"][0]["eval_id"] == id_a

    by_time = client.get(
        "/api/v1/eval",
        params={"from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z"},
    ).json()
    assert by_time["count"] == 2
    out_of_range = client.get("/api/v1/eval", params={"from": "2027-01-01T00:00:00Z"}).json()
    assert out_of_range["count"] == 0


def test_list_invalid_params_400(stack):
    _, _, _, client = stack
    assert client.get("/api/v1/eval", params={"category": "crypto"}).status_code == 400
    assert client.get("/api/v1/eval", params={"verdict": "MAYBE"}).status_code == 400
    assert client.get("/api/v1/eval", params={"from": "not-a-date"}).status_code == 400


# ---------- delete（§13.2） ----------


def test_delete_queued_200(stack):
    _, _, _, client = stack
    eval_id = submit(client).json()["eval_id"]
    resp = client.delete(f"/api/v1/eval/{eval_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert client.get(f"/api/v1/eval/{eval_id}").json()["status"] == "cancelled"


def test_delete_unknown_404(stack):
    _, _, _, client = stack
    assert client.delete("/api/v1/eval/EV-20990101-000001").status_code == 404


def test_delete_already_judged_409(stack):
    _, _, reporter, client = stack
    eval_id = submit(client).json()["eval_id"]
    reporter.finalize_empty(eval_id)  # → succeeded
    assert client.delete(f"/api/v1/eval/{eval_id}").status_code == 409


def test_delete_already_cancelled_409(stack):
    _, _, _, client = stack
    eval_id = submit(client).json()["eval_id"]
    client.delete(f"/api/v1/eval/{eval_id}")
    assert client.delete(f"/api/v1/eval/{eval_id}").status_code == 409


# ---------- evalctl gate（§13.4） ----------


def _finalize(stack_repo, reporter, eval_id, kind, status, tag):
    run = make_run(eval_id, tag=tag)
    reporter.finalize(eval_id, run, [make_item(run.run_id, kind=kind, status=status)])


def test_cli_gate_exit_codes(stack):
    repo, _, reporter, client = stack
    out = io.StringIO()

    id_pass = submit(client, key="g-pass").json()["eval_id"]
    _finalize(repo, reporter, id_pass, "weighted", "PASS", "p1")
    assert main(["gate", "--eval-id", id_pass], repo=repo, out=out) == EXIT_PASS

    id_block = submit(client, key="g-block").json()["eval_id"]
    _finalize(repo, reporter, id_block, "hard", "BLOCK", "b1")
    assert main(["gate", "--eval-id", id_block], repo=repo, out=out) == EXIT_BLOCK

    id_inc = submit(client, key="g-inc").json()["eval_id"]
    reporter.finalize_empty(id_inc)
    assert main(["gate", "--eval-id", id_inc], repo=repo, out=out) == EXIT_INCONCLUSIVE


def test_cli_gate_unknown_eval_id_error(stack):
    repo, _, _, _ = stack
    out = io.StringIO()
    code = main(["gate", "--eval-id", "EV-20990101-000001"], repo=repo, out=out)
    assert code == EXIT_ERROR
    assert "未知 eval_id" in out.getvalue()


def test_cli_gate_not_decided_without_wait_error(stack):
    repo, _, _, client = stack
    eval_id = submit(client).json()["eval_id"]
    out = io.StringIO()
    code = main(["gate", "--eval-id", eval_id], repo=repo, out=out)
    assert code == EXIT_ERROR
    assert "尚未出分" in out.getvalue()


def test_cli_gate_wait_timeout_error(stack):
    repo, _, _, client = stack
    eval_id = submit(client).json()["eval_id"]
    out = io.StringIO()
    code = main(
        ["gate", "--eval-id", eval_id, "--wait", "--timeout", "0.01", "--poll-interval", "0.005"],
        repo=repo,
        sleeper=lambda _s: None,
        out=out,
    )
    assert code == EXIT_ERROR
    assert "超时" in out.getvalue()


def test_cli_gate_wait_until_report_ready(stack):
    """--wait 轮询：前两次未出分，第三次出分 → 退出码取报告判定。"""

    class DelayedRepo(InMemoryRepo):
        def __init__(self, inner: InMemoryRepo, delay_calls: int) -> None:
            super().__init__()
            self._inner = inner
            self._remaining = delay_calls

        def get_report(self, eval_id):  # type: ignore[override]
            if self._remaining > 0:
                self._remaining -= 1
                return None
            return self._inner.get_report(eval_id)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    repo, _, reporter, client = stack
    eval_id = submit(client).json()["eval_id"]
    run = make_run(eval_id, tag="w1")
    reporter.finalize(eval_id, run, [make_item(run.run_id)])

    delayed = DelayedRepo(repo, delay_calls=2)
    code = main(
        ["gate", "--eval-id", eval_id, "--wait", "--timeout", "10", "--poll-interval", "0.001"],
        repo=delayed,
        sleeper=lambda _s: None,
        out=io.StringIO(),
    )
    assert code == EXIT_PASS
