# -*- coding: utf-8 -*-
"""
test_validators.py — P1-1 env_manifest 校验器测试
==================================================
验收（PLAN P1-1 / SPEC §13.1「受理即拒」/ §15）：
- 结构语义：endpoints 必须 URL 可解析、scheme ∈ {http,https}、去重
- 可达性：注入探针；探针返回 False → 实盘模式硬拒、影子模式只告警
- 密钥：secret_refs 只允许引用名，禁止明文密钥值（§15）
- 影子模式语义（P1-3）：gate.shadow=true 时校验失败不拦截受理
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.gateway import (  # noqa: E402
    CategoriesConfig,
    EnvManifestError,
    Gateway,
    InMemoryEvalRequestStore,
)
from core.validators import (  # noqa: E402
    EnvManifestValidator,
    HttpProber,
    looks_like_plaintext_secret,
)

VALID_MANIFEST = {
    "runtime": "python3.11",
    "endpoints": ["https://object.local/health"],
    "resources": ["pg://readonly"],
    "secret_refs": ["OBJ_READ_KEY"],
}

MAPPING = {
    "finance": ("strategy", "service"),
    "ai": ("model", "service"),
    "engineering": ("code_artifact", "dataset", "knowledge"),
}


def make_categories(shadow: bool) -> CategoriesConfig:
    return CategoriesConfig(version="CAT-TEST@1", mapping=MAPPING, gate_shadow=shadow)


def make_payload(**env_overrides):
    manifest = dict(VALID_MANIFEST)
    manifest.update(env_overrides)
    return {
        "object_ref": "git://repo/strategy@abc123",
        "category": "finance",
        "object_type": "strategy",
        "submitter": "trader-01",
        "purpose": "l0_settle",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": manifest,
    }


def ok_prober(_url: str) -> bool:
    return True


def dead_prober(_url: str) -> bool:
    return False


# ---------- 结构语义 ----------


def test_valid_manifest_has_no_findings():
    validator = EnvManifestValidator(strict=True, prober=ok_prober)
    assert validator.check(VALID_MANIFEST) == []


@pytest.mark.parametrize(
    "endpoint",
    ["not-a-url", "ftp://object.local/health", "http://", "://missing-scheme"],
)
def test_invalid_endpoint_rejected(endpoint):
    findings = EnvManifestValidator(strict=True, prober=ok_prober).check(
        {**VALID_MANIFEST, "endpoints": [endpoint]}
    )
    assert findings == [f"endpoint_invalid:{endpoint}"]


def test_duplicate_endpoints_reported():
    findings = EnvManifestValidator(strict=True, prober=ok_prober).check(
        {**VALID_MANIFEST, "endpoints": ["https://a.local/h", "https://a.local/h"]}
    )
    assert findings == ["endpoint_duplicate:https://a.local/h"]


def test_empty_endpoints_reported():
    findings = EnvManifestValidator(strict=True, prober=ok_prober).check(
        {**VALID_MANIFEST, "endpoints": []}
    )
    assert findings == ["endpoints_missing"]


def test_manifest_not_mapping_reported():
    findings = EnvManifestValidator(strict=True, prober=ok_prober).check(["https://a.local"])
    assert findings == ["env_manifest_not_object"]


def test_unreachable_endpoint_reported():
    findings = EnvManifestValidator(strict=True, prober=dead_prober).check(VALID_MANIFEST)
    assert findings == ["endpoint_unreachable:https://object.local/health"]


def test_prober_not_called_for_invalid_endpoint():
    calls: list[str] = []
    validator = EnvManifestValidator(strict=True, prober=lambda url: calls.append(url) or True)
    validator.check({**VALID_MANIFEST, "endpoints": ["ftp://x"]})
    assert calls == []


def test_no_prober_skips_reachability():
    validator = EnvManifestValidator(strict=True, prober=None)
    assert validator.check(VALID_MANIFEST) == []


# ---------- 密钥（§15） ----------


@pytest.mark.parametrize(
    "value",
    [
        "sk-live-4f9a8b7c6d5e4f3a2b1c",  # OpenAI 风格
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",  # secret-scan: allow — 造样例非法令牌
        "AKIAIOSFODNN7EXAMPLE",
        "dXNlcjpwYXNzd29yZEBob3N0",  # 裸 base64 令牌（20 位以上含数字）
    ],
)
def test_plaintext_secret_rejected(value):
    findings = EnvManifestValidator(strict=True, prober=ok_prober).check(
        {**VALID_MANIFEST, "secret_refs": [value]}
    )
    assert findings == [f"secret_ref_plaintext:{value}"]


def test_secret_ref_identifier_allowed():
    assert looks_like_plaintext_secret("OBJ_READ_KEY") is False
    assert looks_like_plaintext_secret("aws.prod.readonly") is False


def test_secret_ref_with_space_is_invalid():
    findings = EnvManifestValidator(strict=True, prober=ok_prober).check(
        {**VALID_MANIFEST, "secret_refs": ["my key here"]}
    )
    assert findings == ["secret_ref_invalid:my key here"]


# ---------- enforce：实盘硬拒 vs 影子告警 ----------


def test_enforce_strict_raises():
    validator = EnvManifestValidator(strict=True, prober=dead_prober)
    with pytest.raises(EnvManifestError):
        validator.enforce(VALID_MANIFEST)


def test_enforce_shadow_warns_only():
    warnings: list[str] = []
    validator = EnvManifestValidator(strict=False, prober=dead_prober, warn=warnings.append)
    findings = validator.enforce(VALID_MANIFEST)
    assert findings == ["endpoint_unreachable:https://object.local/health"]
    assert warnings == findings


# ---------- HttpProber ----------


def test_http_prober_true_on_2xx(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "core.validators.urllib.request.urlopen", lambda req, timeout: FakeResponse()
    )
    assert HttpProber()("https://a.local/h") is True


def test_http_prober_false_on_connection_error(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr("core.validators.urllib.request.urlopen", boom)
    assert HttpProber()("https://a.local/h") is False


def test_http_prober_true_on_client_error(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.HTTPError("https://a.local/h", 403, "forbidden", {}, None)

    monkeypatch.setattr("core.validators.urllib.request.urlopen", boom)
    assert HttpProber()("https://a.local/h") is True


def test_http_prober_false_on_server_error(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.HTTPError("https://a.local/h", 503, "unavailable", {}, None)

    monkeypatch.setattr("core.validators.urllib.request.urlopen", boom)
    assert HttpProber()("https://a.local/h") is False


# ---------- 接入 Gateway（P1-3 影子语义） ----------


def make_gateway(shadow: bool, prober=None) -> tuple[Gateway, InMemoryEvalRequestStore]:
    store = InMemoryEvalRequestStore()
    gateway = Gateway(
        store=store,
        categories=make_categories(shadow),
        prober=prober,
    )
    return gateway, store


def test_gateway_strict_rejects_unreachable_endpoint():
    gateway, store = make_gateway(shadow=False, prober=dead_prober)
    with pytest.raises(EnvManifestError):
        gateway.submit(make_payload(), idempotency_key="k-strict")
    assert store.all() == []


def test_gateway_shadow_accepts_unreachable_endpoint(caplog):
    gateway, store = make_gateway(shadow=True, prober=dead_prober)
    with caplog.at_level("WARNING", logger="core.validators"):
        result = gateway.submit(make_payload(), idempotency_key="k-shadow")
    assert result.status == "accepted"
    assert [r.eval_id for r in store.all()] == [result.eval_id]
    assert any("endpoint_unreachable" in rec.message for rec in caplog.records)


def test_gateway_strict_rejects_plaintext_secret():
    gateway, _ = make_gateway(shadow=False, prober=ok_prober)
    with pytest.raises(EnvManifestError):
        gateway.submit(
            make_payload(secret_refs=["sk-live-4f9a8b7c6d5e4f3a2b1c"]),
            idempotency_key="k-secret",
        )


def test_gateway_shadow_accepts_plaintext_secret():
    gateway, store = make_gateway(shadow=True, prober=ok_prober)
    result = gateway.submit(
        make_payload(secret_refs=["sk-live-4f9a8b7c6d5e4f3a2b1c"]),
        idempotency_key="k-secret-shadow",
    )
    assert len(store.all()) == 1
    assert result.status == "accepted"
