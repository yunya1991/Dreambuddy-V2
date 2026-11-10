"""P0-5 验证独立性判定 — SPEC §2.10 A3。"""

from __future__ import annotations

from data_center.processing.validation_independence import (
    SourceProfile,
    classify_independence,
    stamp_validation,
)

PRIMARY = SourceProfile("yfinance-btc-daily", "1d", "yfinance", 0.0)


def test_identical_source_is_same_source_review():
    r = classify_independence(PRIMARY, SourceProfile("same", "1d", "yfinance", 0.0))
    assert r["validation_type"] == "same_source_review"
    assert r["rules"] == []


def test_different_supplier_is_independent():
    r = classify_independence(PRIMARY, SourceProfile("binance-1d", "1d", "binance", 0.0))
    assert r["validation_type"] == "independent"
    assert "supplier" in r["rules"]


def test_different_frequency_is_independent():
    r = classify_independence(PRIMARY, SourceProfile("yf-1h", "1h", "yfinance", 0.0))
    assert r["validation_type"] == "independent"
    assert "frequency" in r["rules"]


def test_close_frequency_is_not_enough():
    # 1d vs 2h 比值 12 才算独立；1d vs 12h 比值 2 不够
    r = classify_independence(PRIMARY, SourceProfile("yf-12h", "12h", "yfinance", 0.0))
    assert r["validation_type"] == "same_source_review"


def test_lag_24h_is_independent():
    ok = classify_independence(PRIMARY, SourceProfile("snap", "1d", "yfinance", 24.0))
    assert ok["validation_type"] == "independent"
    assert "lag_24h" in ok["rules"]
    bad = classify_independence(PRIMARY, SourceProfile("snap", "1d", "yfinance", 23.9))
    assert bad["validation_type"] == "same_source_review"


def test_unknown_frequency_cannot_claim_independence():
    r = classify_independence(PRIMARY, SourceProfile("x", "weird", "yfinance", 0.0))
    assert r["validation_type"] == "same_source_review"


def test_stamp_does_not_mutate_and_fail_open():
    row = {"factor_id": "macro.rate", "sens_f": -0.003}
    out = stamp_validation(row, PRIMARY, SourceProfile("binance-1d", "1d", "binance", 0.0))
    assert row == {"factor_id": "macro.rate", "sens_f": -0.003}
    assert out["validation_type"] == "independent"
    assert out["validator_source"] == "binance-1d"

    bad = stamp_validation(row, PRIMARY, object())
    assert bad["validation_type"] == "same_source_review"
    assert bad["independence_rules"] == []
