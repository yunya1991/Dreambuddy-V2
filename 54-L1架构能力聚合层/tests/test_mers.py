# -*- coding: utf-8 -*-
"""MERS S3 内部计算内核：固定网格、门禁、状态机与幂等注册表。"""

import os
import random
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.mers import (  # noqa: E402
    RelationshipRegistry,
    build_units,
    evaluate_grid,
    load_grid,
    make_eval_id,
    transition_state,
)


def _strong_relationship(n=320):
    signal = [float(i) for i in range(n + 1)]
    prices = [100.0]
    for i in range(n):
        forward = (signal[i] - (n - 1) / 2) * 0.00005
        prices.append(prices[-1] * (1.0 + forward))
    return signal, prices


def _random_relationship(n=300, seed=42):
    rng = random.Random(seed)
    signal = [rng.gauss(0.0, 1.0) for _ in range(n + 1)]
    prices = [100.0]
    for _ in range(n):
        prices.append(prices[-1] * (1.0 + rng.gauss(0.0, 0.01)))
    return signal, prices


def _row(records, transform="raw", method="B14", horizon=1):
    return next(
        row
        for row in records
        if row["transform"] == transform and row["method"] == method and row["horizon"] == horizon
    )


def _new_version(row, version):
    out = dict(row)
    out["data_version"] = version
    out["run_id"] = f"run-{version}"
    out["eval_at"] = f"2026-11-{int(version[1:]) + 1:02d}T00:00:00+00:00"
    out["eval_id"] = make_eval_id(out)
    return out


def test_fixed_grid_enumerates_180_deterministic_units():
    grid = load_grid()
    assert grid["transforms"] == ["raw", "diff", "pct", "zscore60", "ts_rank60", "quintile5"]
    assert grid["methods"] == ["M01", "M02", "M11", "B11", "B13", "B14", "R01", "R03", "R04", "F19"]
    assert grid["horizons"] == [1, 5, 20]
    assert load_grid()["grid_hash"] == grid["grid_hash"]

    units = build_units("market", "TEST", "BTC", "v1", grid)
    assert len(units) == 180
    assert len({row["eval_id"] for row in units}) == 180
    assert units == build_units("market", "TEST", "BTC", "v1", load_grid())


def test_positive_relationship_fdr_idempotency_and_state_progression(tmp_path):
    registry = RelationshipRegistry(tmp_path / "relationship_registry.db")
    signal, prices = _strong_relationship()
    kwargs = {
        "dataset": "market",
        "metric": "TEST",
        "signal": signal,
        "prices": prices,
        "target": "BTC",
        "data_version": "v1",
        "run_id": "run-v1",
        "eval_at": "2026-11-02T00:00:00+00:00",
    }
    first = evaluate_grid(registry=registry, **kwargs)
    positive = _row(first)
    assert positive["gate_pass"] is True
    assert positive["status"] == "candidate"
    assert positive["p_adj"] < 0.05
    assert positive["half_same"] is True
    assert positive["holdout_same"] is True
    assert positive["coverage"] == 1.0
    assert positive["method_gate"] == "ok"

    second = evaluate_grid(registry=registry, **kwargs)
    assert second == first
    assert registry.count_evals() == 180

    second_version = registry.record(_new_version(positive, "v2"))
    third_version = registry.record(_new_version(positive, "v3"))
    assert second_version["status"] == "candidate"
    assert third_version["status"] == "stable"
    assert third_version["pass_streak"] == 3

    fourth_version = registry.record(_new_version(positive, "v4"))
    assert fourth_version["status"] == "candidate"
    assert fourth_version["pass_streak"] == 1
    assert registry.count_evals() == 183


def test_state_machine_failure_transitions():
    state = {"status": "stable", "data_version": "v1", "pass_streak": 3, "fail_streak": 0}
    first_failure = transition_state(state, gate_pass=False, data_version="v1")
    second_failure = transition_state(first_failure, gate_pass=False, data_version="v1")
    assert first_failure["status"] == "stable"
    assert second_failure["status"] == "decayed"

    state = second_failure
    for expected_failures in (1, 2, 3):
        state = transition_state(state, gate_pass=False, data_version="v1")
        assert state["status"] == "decayed"
        assert state["fail_streak"] == expected_failures + 2
    retired = transition_state(state, gate_pass=False, data_version="v1")
    assert retired["status"] == "retired"
    assert retired["fail_streak"] == 6


def test_random_relationship_never_becomes_stable(tmp_path):
    registry = RelationshipRegistry(tmp_path / "relationship_registry.db")
    signal, prices = _random_relationship()
    records = []
    for version in ("v1", "v2", "v3"):
        records = evaluate_grid(
            registry=registry,
            dataset="market",
            metric="RANDOM",
            signal=signal,
            prices=prices,
            target="BTC",
            data_version=version,
            run_id=f"random-{version}",
            eval_at="2026-11-02T00:00:00+00:00",
        )
    assert sum(row["status"] == "stable" for row in records) == 0
    assert registry.count_evals() == 540
