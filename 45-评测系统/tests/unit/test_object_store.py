# -*- coding: utf-8 -*-
"""
test_object_store.py — P4-2 WORM 对象存储
==========================================
验收（PLAN P4-2 / SPEC §14.4/§15）：
- 对象锁生效：保留期内禁止覆盖 / 删除，保留期结束后允许（版本化追加）
- 保留期策略可配：config/object_store.yaml + 环境变量覆盖；默认按证据/报告/审计分级
- 落盘对象只读 + 元数据含 sha256/version_id/retention_until（可审计）
- 证据包可归档为 WORM 对象并回填 uri/sha256
- MinIO 模式缺依赖时 fail-closed（不静默降级）
"""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from storage.object_store import (  # noqa: E402
    LocalWormStore,
    ObjectStoreError,
    RetentionPolicy,
    WormViolation,
    archive_bundle,
    build_store,
    load_retention_policy,
)
from storage.repo import InMemoryRepo  # noqa: E402

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> LocalWormStore:
    policy = RetentionPolicy({"evidence": 30, "report": 90, "audit": 30})
    return LocalWormStore(tmp_path / "worm", policy=policy, clock=clock)


def test_put_get_roundtrip_and_metadata(store: LocalWormStore):
    data = b'{"bundle":1}'
    obj = store.put("evidence/bundle.json", data, kind="evidence")

    assert store.get("evidence/bundle.json") == data
    head = store.head("evidence/bundle.json")
    assert head.sha256 == hashlib.sha256(data).hexdigest()
    assert head.size == len(data)
    assert head.mode == "compliance"
    assert head.version_id == obj.version_id
    assert head.retention_until == NOW + timedelta(days=30)
    assert head.uri.startswith("local://worm/evidence/bundle.json")


def test_object_file_is_read_only(store: LocalWormStore, tmp_path: Path):
    store.put("evidence/bundle.json", b"x", kind="evidence")
    path = tmp_path / "worm" / "evidence" / "bundle.json"
    assert path.stat().st_mode & stat.S_IWUSR == 0


def test_overwrite_in_retention_rejected(store: LocalWormStore):
    store.put("evidence/bundle.json", b"v1", kind="evidence")
    with pytest.raises(WormViolation) as exc:
        store.put("evidence/bundle.json", b"v2", kind="evidence")
    assert "object_locked" in str(exc.value)


def test_overwrite_after_retention_allowed(store: LocalWormStore, clock: Clock):
    first = store.put("evidence/bundle.json", b"v1", kind="evidence")
    clock.advance(days=31)
    second = store.put("evidence/bundle.json", b"v2", kind="evidence")

    assert store.get("evidence/bundle.json") == b"v2"
    assert second.version_id != first.version_id
    assert first.retention_until < second.retention_until


def test_delete_in_retention_rejected(store: LocalWormStore):
    store.put("evidence/bundle.json", b"v1", kind="evidence")
    with pytest.raises(WormViolation) as exc:
        store.delete("evidence/bundle.json")
    assert "object_locked" in str(exc.value)


def test_delete_after_retention_allowed(store: LocalWormStore, clock: Clock):
    store.put("evidence/bundle.json", b"v1", kind="evidence")
    clock.advance(days=31)
    store.delete("evidence/bundle.json")
    with pytest.raises(ObjectStoreError):
        store.head("evidence/bundle.json")


@pytest.mark.parametrize("key", ["../escape.json", "/etc/passwd", "evidence/../../x.json"])
def test_path_traversal_rejected(store: LocalWormStore, key: str):
    with pytest.raises(ObjectStoreError) as exc:
        store.put(key, b"x", kind="evidence")
    assert "invalid_key" in str(exc.value)


def test_unknown_kind_uses_default_retention(store: LocalWormStore):
    obj = store.put("misc/a.json", b"x", kind="misc")
    assert (obj.retention_until - NOW).days == RetentionPolicy.DEFAULT_DAYS


def test_missing_object_head_and_get(store: LocalWormStore):
    with pytest.raises(ObjectStoreError):
        store.head("evidence/absent.json")
    with pytest.raises(ObjectStoreError):
        store.get("evidence/absent.json")


# ---------- 保留期策略可配 ----------


def test_retention_policy_defaults_match_spec():
    policy = RetentionPolicy()
    assert policy.days_for("evidence") == 365
    assert policy.days_for("report") == 1095
    assert policy.days_for("audit") == 365


def test_retention_policy_override():
    policy = RetentionPolicy({"evidence": 730, "report": 1460})
    assert policy.days_for("evidence") == 730
    assert policy.days_for("report") == 1460
    assert policy.days_for("audit") == 365


def test_load_retention_policy_from_yaml(tmp_path: Path):
    config = tmp_path / "object_store.yaml"
    config.write_text(
        "mode: local\nroot: artifacts/worm\nretention_days:\n  evidence: 400\n  report: 1200\n",
        encoding="utf-8",
    )
    loaded = load_retention_policy(config)
    assert loaded.days_for("evidence") == 400
    assert loaded.days_for("report") == 1200


def test_load_retention_policy_missing_file_falls_back(tmp_path: Path):
    policy = load_retention_policy(tmp_path / "absent.yaml")
    assert policy.days_for("evidence") == 365


def test_build_store_local_default(tmp_path: Path, clock: Clock):
    store = build_store(root=tmp_path / "worm", env={"EVAL_WORM_MODE": "local"})
    assert isinstance(store, LocalWormStore)
    store.put("evidence/a.json", b"x", kind="evidence")
    assert (tmp_path / "worm" / "evidence" / "a.json").exists()


def test_build_store_custom_retention_config(tmp_path: Path, clock: Clock):
    config = tmp_path / "object_store.yaml"
    config.write_text(
        "mode: local\nroot: artifacts/worm\nretention_days:\n  evidence: 10\n",
        encoding="utf-8",
    )
    store = build_store(config_path=config, root=tmp_path / "worm", env={})
    assert store.policy.days_for("evidence") == 10


def test_build_store_minio_without_dependency_fails_closed(tmp_path: Path):
    with pytest.raises(ObjectStoreError) as exc:
        build_store(env={"EVAL_WORM_MODE": "minio", "EVAL_WORM_ENDPOINT": "minio:9000"})
    assert "minio_missing" in str(exc.value)


def test_build_store_unknown_mode_rejected():
    with pytest.raises(ObjectStoreError) as exc:
        build_store(env={"EVAL_WORM_MODE": "s3"})
    assert "unknown_mode" in str(exc.value)


# ---------- 证据包归档 ----------


def test_archive_bundle_writes_immutable_object(tmp_path: Path, clock: Clock):
    store = LocalWormStore(
        tmp_path / "worm",
        policy=RetentionPolicy({"evidence": 30}),
        clock=clock,
    )
    bundle = {"version": "evidence_bundle.v1", "eval_id": "EV-20261101-000001"}
    archived = archive_bundle(store, bundle, eval_id=bundle["eval_id"])

    assert archived["uri"].endswith("EV-20261101-000001.json")
    head = store.head(archived["uri"].removeprefix("local://worm/"))
    assert head.sha256 == archived["sha256"]
    stored = json.loads(store.get(head.key).decode("utf-8"))
    assert stored == bundle


def test_archive_bundle_key_includes_eval_id_and_is_locked(tmp_path: Path, clock: Clock):
    store = LocalWormStore(tmp_path / "worm", policy=RetentionPolicy({"evidence": 30}), clock=clock)
    bundle = {"eval_id": "EV-20261101-000001", "run_id": "RUN-01"}
    archive_bundle(store, bundle, eval_id=bundle["eval_id"])
    with pytest.raises(WormViolation):
        archive_bundle(store, bundle, eval_id=bundle["eval_id"])


# ---------- CLI 归档接线 ----------


def test_cli_evidence_archive_writes_worm_object(tmp_path: Path, monkeypatch):
    import io

    from api.cli import main
    from core.gateway import CategoriesConfig, Gateway
    from core.registry import ThresholdRegistry
    from core.reporter import Reporter

    repo = InMemoryRepo()
    gateway = Gateway(
        store=repo,
        categories=CategoriesConfig.load(MODULE_ROOT / "config" / "categories.yaml"),
        clock=lambda: NOW,
    )
    eval_id = gateway.submit(
        {
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
        },
        idempotency_key="worm-cli",
    ).eval_id
    Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: NOW).finalize_empty(
        eval_id
    )

    worm_root = tmp_path / "worm"
    monkeypatch.setenv("EVAL_WORM_MODE", "local")
    monkeypatch.setenv("EVAL_WORM_ROOT", str(worm_root))

    out = io.StringIO()
    assert main(["evidence", "--eval-id", eval_id, "--archive"], repo=repo, out=out) == 0
    summary = json.loads(out.getvalue())
    assert summary["archive"]["uri"] == f"local://worm/evidence/{eval_id}.json"
    assert (worm_root / "evidence" / f"{eval_id}.json").is_file()
