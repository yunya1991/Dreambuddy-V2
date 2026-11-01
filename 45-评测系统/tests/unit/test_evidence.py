# -*- coding: utf-8 -*-
"""
test_evidence.py — P4-1 证据签名与 Merkle 根
=============================================
验收（PLAN P4-1 / SPEC §12/§13.4/§14.4）：
- 哈希链 append 自动链接 prev_hash；verify 检出篡改/断链/乱序
- RFC 6962 思路 Merkle 根：空树 = SHA256("")，单叶 = SHA256(0x00||leaf)，
  奇数叶按「最大 2 的幂切分」（非 promote）
- 证据包可离线验证：哈希链 + 签名 + 报告 JSON；任一篡改可检出
- CLI `evalctl evidence --eval-id/--verify` 退出码语义（§13.4）
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.gateway import CategoriesConfig, Gateway  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.reporter import Reporter  # noqa: E402
from storage.repo import (  # noqa: E402
    EvalItemRecord,
    EvalRunRecord,
    EvidenceRow,
    InMemoryRepo,
    canonical_json,
    sha256_hex,
)

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
SPEC_HASH = sha256_hex("spec-placeholder")
KEY = "evidence-test-key"
SIGNER = "45-evidence"


def make_payload() -> dict:
    return {
        "object_ref": "git://repo/strategy@abc123",
        "category": "finance",
        "object_type": "strategy",
        "submitter": "trader-01",
        "purpose": "l0_settle",
        "priority": "normal",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": {
            "runtime": "python3.11",
            "endpoints": ["https://object.local/health"],
        },
    }


def make_run(eval_id: str, attempt: int = 1) -> EvalRunRecord:
    return EvalRunRecord(
        run_id=f"RUN-{eval_id.removeprefix('EV-')}-{attempt:02d}",
        eval_id=eval_id,
        evaluator_id="EV-finance.backtest",
        evaluator_version="1.0.0",
        scorer_versions=None,
        attempt=attempt,
        spec_hash=SPEC_HASH,
        code_commit=None,
        env_snapshot=None,
        budget_ms=None,
        degraded=False,
        started_at=NOW,
        ended_at=NOW,
        status="succeeded",
    )


def make_item(run_id: str, name: str, status: str) -> EvalItemRecord:
    return EvalItemRecord(
        item_id=f"IT-{run_id}-{name}",
        run_id=run_id,
        name=name,
        kind="hard",
        score=None,
        n=None,
        ci_lower=None,
        ci_upper=None,
        weight=None,
        status=status,
        evidence_id=None,
        detail=None,
    )


@pytest.fixture
def repo() -> InMemoryRepo:
    return InMemoryRepo()


@pytest.fixture
def eval_id(repo: InMemoryRepo) -> str:
    categories = CategoriesConfig.load(MODULE_ROOT / "config" / "categories.yaml")
    gw = Gateway(store=repo, categories=categories, clock=lambda: NOW)
    return gw.submit(make_payload(), idempotency_key="evd-fixture").eval_id


@pytest.fixture
def reporter(repo: InMemoryRepo) -> Reporter:
    registry = ThresholdRegistry.load(MODULE_ROOT / "config" / "thresholds.yaml")
    return Reporter(repo=repo, thresholds=registry, clock=lambda: NOW, signed_by=SIGNER)


# ---------- 哈希链 ----------


def test_chain_hash_matches_reporter_formula():
    """链哈希与既有 reporter 公式一致：sha256(prev|sha256|uri)，首条 prev 为 null。"""
    from storage.evidence import chain_hash

    sha = "a" * 64
    assert chain_hash(None, sha, "local://evidence/EVD-1") == sha256_hex(
        f"null|{sha}|local://evidence/EVD-1"
    )
    assert chain_hash("b" * 64, sha, "local://evidence/EVD-2") == sha256_hex(
        f"{'b' * 64}|{sha}|local://evidence/EVD-2"
    )


def test_append_entry_links_prev_hash(repo: InMemoryRepo, eval_id: str):
    from storage.evidence import append_entry

    repo.insert_run(make_run(eval_id))
    first = append_entry(repo, make_run(eval_id).run_id, {"k": 1}, clock=lambda: NOW)
    second = append_entry(repo, first.run_id, {"k": 2}, clock=lambda: NOW)

    assert first.prev_hash is None
    assert second.prev_hash == first.hash
    assert second.evidence_id.endswith("-02")
    assert repo.list_evidence(first.run_id) == [first, second]


def test_append_entry_hash_covers_content_and_uri(repo: InMemoryRepo, eval_id: str):
    from storage.evidence import append_entry, chain_hash

    run = make_run(eval_id)
    repo.insert_run(run)
    content = {"run_id": run.run_id, "payload": {"k": 1}}
    entry = append_entry(repo, run.run_id, content, clock=lambda: NOW)

    assert entry.sha256 == sha256_hex(canonical_json(content))
    assert entry.hash == chain_hash(None, entry.sha256, entry.uri)


def test_verify_chain_ok(repo: InMemoryRepo, eval_id: str):
    from storage.evidence import append_entry, verify_chain

    run = make_run(eval_id)
    repo.insert_run(run)
    append_entry(repo, run.run_id, {"k": 1}, clock=lambda: NOW)
    append_entry(repo, run.run_id, {"k": 2}, clock=lambda: NOW)
    append_entry(repo, run.run_id, {"k": 3}, clock=lambda: NOW)

    result = verify_chain(repo.list_evidence(run.run_id))
    assert result.ok is True
    assert result.reasons == []
    assert result.head == repo.list_evidence(run.run_id)[-1].hash
    assert result.count == 3


@pytest.mark.parametrize("field", ["sha256", "uri", "hash"])
def test_verify_chain_detects_field_tamper(repo: InMemoryRepo, eval_id: str, field: str):
    from storage.evidence import append_entry, verify_chain

    run = make_run(eval_id)
    repo.insert_run(run)
    entry = append_entry(repo, run.run_id, {"k": 1}, clock=lambda: NOW)
    tampered = EvidenceRow(
        evidence_id=entry.evidence_id,
        run_id=entry.run_id,
        sha256="0" * 64 if field == "sha256" else entry.sha256,
        uri="local://evil" if field == "uri" else entry.uri,
        prev_hash=entry.prev_hash,
        hash="0" * 64 if field == "hash" else entry.hash,
        signed_by=entry.signed_by,
        created_at=entry.created_at,
    )

    result = verify_chain([tampered])
    assert result.ok is False
    assert any("hash_mismatch" in r for r in result.reasons)


def test_verify_chain_detects_broken_link_and_reorder(repo: InMemoryRepo, eval_id: str):
    from storage.evidence import append_entry, verify_chain

    run = make_run(eval_id)
    repo.insert_run(run)
    first = append_entry(repo, run.run_id, {"k": 1}, clock=lambda: NOW)
    second = append_entry(repo, first.run_id, {"k": 2}, clock=lambda: NOW)

    reordered = verify_chain([second, first])
    assert reordered.ok is False
    assert any("prev_hash_mismatch" in r for r in reordered.reasons)


def test_verify_chain_empty_is_ok():
    from storage.evidence import verify_chain

    result = verify_chain([])
    assert result.ok is True
    assert result.count == 0
    assert result.head is None


# ---------- Merkle 根（RFC 6962 思路） ----------


def _leaf(data: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + data).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def test_merkle_root_empty_tree():
    from storage.evidence import merkle_root

    assert merkle_root([]) == hashlib.sha256(b"").hexdigest()


def test_merkle_root_single_leaf():
    from storage.evidence import merkle_root

    leaf = "a" * 64
    assert merkle_root([leaf]) == _leaf(bytes.fromhex(leaf)).hex()


def test_merkle_root_two_leaves():
    from storage.evidence import merkle_root

    a, b = "a" * 64, "b" * 64
    expected = _node(_leaf(bytes.fromhex(a)), _leaf(bytes.fromhex(b))).hex()
    assert merkle_root([a, b]) == expected


def test_merkle_root_odd_split_at_largest_power_of_two():
    """3 叶：k=2 → 根 = H(0x01 || MTH(a,b) || MTH(c))；5 叶同理 k=4。"""
    from storage.evidence import merkle_root

    a, b, c = "a" * 64, "b" * 64, "c" * 64
    left = _node(_leaf(bytes.fromhex(a)), _leaf(bytes.fromhex(b)))
    expected = _node(left, _leaf(bytes.fromhex(c)))
    assert merkle_root([a, b, c]) == expected.hex()

    d, e = "d" * 64, "e" * 64
    four = _node(
        _node(_leaf(bytes.fromhex(a)), _leaf(bytes.fromhex(b))),
        _node(_leaf(bytes.fromhex(c)), _leaf(bytes.fromhex(d))),
    )
    expected5 = _node(four, _leaf(bytes.fromhex(e)))
    assert merkle_root([a, b, c, d, e]) == expected5.hex()


def test_merkle_root_order_sensitive():
    from storage.evidence import merkle_root

    a, b = "a" * 64, "b" * 64
    assert merkle_root([a, b]) != merkle_root([b, a])


# ---------- 证据包离线验证（哈希链 + 签名 + 报告 JSON） ----------


def test_build_bundle_and_offline_verify(repo: InMemoryRepo, eval_id: str, reporter: Reporter):
    from storage.evidence import build_bundle, verify_bundle

    report = reporter.finalize_empty(eval_id)
    bundle = build_bundle(repo, eval_id, key=KEY, signer=SIGNER, clock=lambda: NOW)

    assert bundle["eval_id"] == eval_id
    assert bundle["run_id"] == report["run_id"]
    assert len(bundle["chain"]) == 1
    assert bundle["chain_head"] == bundle["chain"][0]["hash"]
    assert bundle["merkle_root"] == merkle_root_of(bundle["chain"])
    assert bundle["report_sha256"] == sha256_hex(canonical_json(report))
    assert bundle["signature"]["alg"] == "HMAC-SHA256"
    assert bundle["signature"]["signed_by"] == SIGNER
    assert repo.list_evidence(report["run_id"])[0].signed_by == SIGNER

    result = verify_bundle(bundle, key=KEY)
    assert result.ok is True
    assert result.signed is True
    assert result.reasons == []


def merkle_root_of(chain: list[dict]) -> str:
    from storage.evidence import merkle_root

    return merkle_root([e["hash"] for e in chain])


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda b: b["chain"][0].__setitem__("sha256", "0" * 64), "chain"),
        (lambda b: b.__setitem__("merkle_root", "0" * 64), "merkle"),
        (lambda b: b["report"].__setitem__("verdict", "PASS"), "report"),
        (lambda b: b["signature"].__setitem__("value", "0" * 64), "signature"),
    ],
)
def test_verify_bundle_detects_tamper(
    repo: InMemoryRepo, eval_id: str, reporter: Reporter, mutate, reason: str
):
    from storage.evidence import build_bundle, verify_bundle

    reporter.finalize_empty(eval_id)
    bundle = build_bundle(repo, eval_id, key=KEY, signer=SIGNER, clock=lambda: NOW)
    mutate(bundle)

    result = verify_bundle(bundle, key=KEY)
    assert result.ok is False
    assert any(reason in r for r in result.reasons)


def test_verify_bundle_wrong_key_rejected(repo: InMemoryRepo, eval_id: str, reporter: Reporter):
    from storage.evidence import build_bundle, verify_bundle

    reporter.finalize_empty(eval_id)
    bundle = build_bundle(repo, eval_id, key=KEY, signer=SIGNER, clock=lambda: NOW)

    result = verify_bundle(bundle, key="wrong-key")
    assert result.ok is False
    assert any("signature_mismatch" in r for r in result.reasons)


def test_verify_bundle_requires_key_when_signed(
    repo: InMemoryRepo, eval_id: str, reporter: Reporter
):
    from storage.evidence import build_bundle, verify_bundle

    reporter.finalize_empty(eval_id)
    bundle = build_bundle(repo, eval_id, key=KEY, signer=SIGNER, clock=lambda: NOW)

    result = verify_bundle(bundle, key=None, require_signature=True)
    assert result.ok is False
    assert any("missing_key" in r for r in result.reasons)


def test_build_bundle_unknown_eval_rejected(repo: InMemoryRepo):
    from storage.evidence import EvidenceError, build_bundle

    with pytest.raises(EvidenceError):
        build_bundle(repo, "EV-20990101-999999", key=KEY)


# ---------- CLI：构建 / 离线验证（§13.4 退出码） ----------


def test_cli_evidence_build_and_verify(
    repo: InMemoryRepo, eval_id: str, reporter: Reporter, tmp_path: Path, monkeypatch
):
    from api.cli import EXIT_PASS, main

    monkeypatch.setenv("EVAL_EVIDENCE_KEY", KEY)
    monkeypatch.setenv("EVAL_EVIDENCE_SIGNER", SIGNER)
    reporter.finalize_empty(eval_id)

    bundle_path = tmp_path / "bundle.json"
    out = io.StringIO()
    assert (
        main(["evidence", "--eval-id", eval_id, "--out", str(bundle_path)], repo=repo, out=out)
        == EXIT_PASS
    )
    assert bundle_path.exists()
    assert json.loads(bundle_path.read_text("utf-8"))["eval_id"] == eval_id

    verify_out = io.StringIO()
    assert main(["evidence", "--verify", str(bundle_path)], repo=repo, out=verify_out) == EXIT_PASS
    assert json.loads(verify_out.getvalue())["ok"] is True


def test_cli_evidence_verify_tampered_bundle_fails(
    repo: InMemoryRepo, eval_id: str, reporter: Reporter, tmp_path: Path, monkeypatch
):
    from api.cli import EXIT_ERROR, main

    monkeypatch.setenv("EVAL_EVIDENCE_KEY", KEY)
    reporter.finalize_empty(eval_id)

    bundle_path = tmp_path / "bundle.json"
    assert (
        main(
            ["evidence", "--eval-id", eval_id, "--out", str(bundle_path)],
            repo=repo,
            out=io.StringIO(),
        )
        == 0
    )
    bundle = json.loads(bundle_path.read_text("utf-8"))
    bundle["merkle_root"] = "0" * 64
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    out = io.StringIO()
    assert main(["evidence", "--verify", str(bundle_path)], repo=repo, out=out) == EXIT_ERROR
    assert json.loads(out.getvalue())["ok"] is False


def test_cli_evidence_unknown_eval_is_error(repo: InMemoryRepo, tmp_path: Path):
    from api.cli import EXIT_ERROR, main

    out = io.StringIO()
    code = main(
        ["evidence", "--eval-id", "EV-20990101-999999", "--out", str(tmp_path / "x.json")],
        repo=repo,
        out=out,
    )
    assert code == EXIT_ERROR
    assert "error" in json.loads(out.getvalue())


def test_cli_evidence_missing_bundle_file_is_error(repo: InMemoryRepo, tmp_path: Path):
    from api.cli import EXIT_ERROR, main

    out = io.StringIO()
    code = main(["evidence", "--verify", str(tmp_path / "absent.json")], repo=repo, out=out)
    assert code == EXIT_ERROR
    assert "error" in json.loads(out.getvalue())
