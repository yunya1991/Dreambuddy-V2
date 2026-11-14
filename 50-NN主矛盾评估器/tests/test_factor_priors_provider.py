"""factor_priors_provider 单测（SPEC-M4 M4-2：开关 + 适配层 + 审计块）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from adapters import factor_priors_provider as provider
from core.path_synthesis import Path


def _mk(direction="long", confidence=0.5, dimension="D3"):
    return Path(
        path_id=f"ev:11-bcrm-tactical:X:{dimension}:hours:trend",
        source="11-bcrm-tactical",
        symbol="BTC-USDT-SWAP",
        direction=direction,
        confidence=confidence,
        expected_return=0.0,
        resistance=0.0,
        continuation_score=0.5,
        dimension=dimension,
        horizon="hours",
        intent="trend",
        metadata={"weight": 0.35},
    )


def _write_priors(
    path,
    *,
    generated_at=None,
    n_samples=396,
    factors=None,
):
    payload = {
        "schema_version": "factor_contradiction_priors.v0.1",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "factor_direction_priors": {
            "n_samples": n_samples,
            "factors": (
                factors
                if factors is not None
                else {"technical.trend": {"dominant_direction": "bullish", "total_weight": 16.0}}
            ),
        },
        "contradiction_priors": {"n_events": 0, "by_contradiction_type": {}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_disabled_by_default_keeps_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("ENABLE_50_FACTOR_PRIORS_OVERLAY", raising=False)
    priors = _write_priors(tmp_path / "priors.json")
    paths = [_mk()]

    out, audit = provider.maybe_apply_factor_priors_overlay(paths, priors_path=priors)

    assert out[0].confidence == 0.5
    assert audit["enabled"] is False
    assert audit["degraded"] == []


def test_enabled_applies_overlay(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_50_FACTOR_PRIORS_OVERLAY", "1")
    monkeypatch.setenv("FACTOR_PRIORS_COEF", "0.2")
    priors = _write_priors(tmp_path / "priors.json")
    paths = [_mk()]

    out, audit = provider.maybe_apply_factor_priors_overlay(paths, priors_path=priors)

    assert out[0].confidence == pytest.approx(0.6)
    assert audit["enabled"] is True
    assert audit["coef"] == 0.2
    assert audit["coef_source"] == "candidate"
    assert audit["modulated_paths"] == 1
    assert audit["total_paths"] == 1
    assert audit["modulation_rate"] == 1.0
    assert audit["priors_schema_version"] == "factor_contradiction_priors.v0.1"
    assert audit["priors_data_version"] is None


def test_missing_priors_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_50_FACTOR_PRIORS_OVERLAY", "1")
    paths = [_mk()]

    out, audit = provider.maybe_apply_factor_priors_overlay(
        paths, priors_path=tmp_path / "absent.json"
    )

    assert out[0].confidence == 0.5
    assert "missing_priors" in audit["degraded"]


def test_stale_priors_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_50_FACTOR_PRIORS_OVERLAY", "1")
    stale = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    priors = _write_priors(tmp_path / "priors.json", generated_at=stale)
    paths = [_mk()]

    out, audit = provider.maybe_apply_factor_priors_overlay(paths, priors_path=priors)

    assert out[0].confidence == 0.5
    assert "stale_priors" in audit["degraded"]


def test_insufficient_samples_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_50_FACTOR_PRIORS_OVERLAY", "1")
    priors = _write_priors(tmp_path / "priors.json", n_samples=199)
    paths = [_mk()]

    out, audit = provider.maybe_apply_factor_priors_overlay(paths, priors_path=priors)

    assert out[0].confidence == 0.5
    assert "insufficient_samples" in audit["degraded"]


def test_empty_factors_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_50_FACTOR_PRIORS_OVERLAY", "1")
    priors = _write_priors(tmp_path / "priors.json", factors={})
    paths = [_mk()]

    out, audit = provider.maybe_apply_factor_priors_overlay(paths, priors_path=priors)

    assert out[0].confidence == 0.5
    assert "empty_factors" in audit["degraded"]


def test_invalid_coef_falls_back_to_default(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_50_FACTOR_PRIORS_OVERLAY", "1")
    monkeypatch.setenv("FACTOR_PRIORS_COEF", "0.99")
    priors = _write_priors(tmp_path / "priors.json")
    paths = [_mk()]

    out, audit = provider.maybe_apply_factor_priors_overlay(paths, priors_path=priors)

    assert audit["coef"] == 0.10
    assert audit["coef_source"] == "rejected"
    assert out[0].confidence == pytest.approx(0.55)


def test_overlay_exception_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_50_FACTOR_PRIORS_OVERLAY", "1")
    priors = _write_priors(tmp_path / "priors.json")
    paths = [_mk()]

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(provider, "apply_factor_priors_overlay", _boom)

    out, audit = provider.maybe_apply_factor_priors_overlay(paths, priors_path=priors)

    assert out[0].confidence == 0.5
    assert "overlay_error" in audit["degraded"]
