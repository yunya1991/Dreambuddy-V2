# -*- coding: utf-8 -*-
"""MERS S3 内部计算内核：固定网格、门禁、状态机与幂等注册表。"""

import json
import math
import os
import random
import sqlite3
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.mers import (  # noqa: E402
    RelationshipRegistry,
    _refresh_gate,
    build_units,
    evaluate_grid,
    load_grid,
    make_eval_id,
    permutation_p_value,
    transition_state,
    wilson_lower_bound,
)


def _strong_relationship(n=320):
    """正例：信号与前瞻收益同相且收益零均值（基线≈0.5），避免高命中来自高基率。"""
    signal = [200.0 + 100.0 * math.sin(i / 7.0) for i in range(n + 1)]
    prices = [100.0]
    for i in range(n):
        prices.append(prices[-1] * (1.0 + 0.004 * math.sin(i / 7.0)))
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
        "time_range": ("2020-01-01", "2026-01-01"),
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
    assert positive["base_rate"] < 0.6
    assert positive["excess_hit"] >= 0.03
    assert positive["hit_rate_lb"] > positive["base_rate"]
    assert positive["holdout_agree"] == 1
    assert positive["holdout_used_at"] == "2026-11-02T00:00:00+00:00"
    assert positive["effect_bps"] > positive["cost_bps"]
    permuted = [row for row in first if row["perm_p"] is not None]
    assert permuted
    assert all(row["perm_p"] < 0.05 for row in permuted)
    assert len(permuted) <= 3 * 3  # 每期限 top3

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


def test_prune_drops_history_but_keeps_current_state(tmp_path):
    registry = RelationshipRegistry(tmp_path / "relationship_registry.db")
    signal, prices = _strong_relationship()
    first = evaluate_grid(
        registry=registry,
        dataset="market",
        metric="TEST",
        signal=signal,
        prices=prices,
        target="BTC",
        data_version="v1",
        run_id="run-v1",
        eval_at="2026-11-02T00:00:00+00:00",
        time_range=("2020-01-01", "2026-01-01"),
    )
    positive = _row(first)
    newer = registry.record(_new_version(positive, "v2"))
    assert registry.count_evals() == 181

    assert registry.prune_before("2026-11-03T00:00:00+00:00") == 180
    assert registry.count_evals() == 1
    assert registry.get_eval(positive["eval_id"]) is None
    state = registry.get_state(positive["unit_id"])
    assert state["status"] == newer["status"]
    assert state["pass_streak"] == 2
    # 幂等：同一 cutoff 再清理不会再删
    assert registry.prune_before("2026-11-03T00:00:00+00:00") == 0


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


_ADDED_COLUMNS = (
    "base_rate",
    "excess_hit",
    "hit_rate_lb",
    "n_eff",
    "holdout_base_rate",
    "holdout_hit_rate",
    "holdout_agree",
    "holdout_used_at",
    "effect_bps",
    "cost_bps",
    "scope_json",
    "perm_p",
)


def test_registry_migrates_legacy_schema_idempotently(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        # v0.7 之前的真实表结构（35 列），用于验证 ALTER TABLE 迁移
        conn.execute("""
            CREATE TABLE relationship_eval (
              eval_id TEXT PRIMARY KEY,
              unit_id TEXT NOT NULL,
              dataset TEXT, metric TEXT, method TEXT, params_json TEXT,
              transform TEXT, target TEXT, horizon INTEGER,
              n INTEGER, rank_ic REAL, icir REAL, hit_rate REAL, spread REAL,
              monotonicity REAL, stability REAL, coverage REAL,
              p_value REAL, p_adj REAL, rss REAL, status TEXT,
              data_version TEXT, grid_hash TEXT, eval_at TEXT, run_id TEXT,
              first_rank_ic REAL, second_rank_ic REAL, holdout_rank_ic REAL,
              half_same INTEGER, holdout_same INTEGER, gate_pass INTEGER,
              method_gate TEXT, pass_streak INTEGER, fail_streak INTEGER,
              error TEXT
            )
            """)
        conn.execute(
            "INSERT INTO relationship_eval "
            "(eval_id, unit_id, n, rank_ic, status, data_version, eval_at, "
            " target, horizon, half_same, holdout_same, gate_pass) "
            "VALUES ('old', 'u', 250, 0.1, 'candidate', 'v0', "
            "'2026-11-01T00:00:00+00:00', 'BTC', 1, 1, 1, 1)"
        )

    registry = RelationshipRegistry(path)
    old = registry.get_eval("old")
    assert old["eval_id"] == "old"
    for column in _ADDED_COLUMNS:
        assert column in old, f"{column} 未补列"
        assert old[column] is None, f"旧行 {column} 应为 NULL"

    RelationshipRegistry(path)  # 二次初始化必须幂等
    with sqlite3.connect(path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(relationship_eval)")]
    for column in _ADDED_COLUMNS:
        assert columns.count(column) == 1


def test_evaluation_writes_effective_sample_size(tmp_path):
    registry = RelationshipRegistry(tmp_path / "relationship_registry.db")
    signal, prices = _strong_relationship()
    records = evaluate_grid(
        registry=registry,
        dataset="market",
        metric="TEST",
        signal=signal,
        prices=prices,
        target="BTC",
        data_version="v1",
        run_id="run-v1",
        eval_at="2026-11-02T00:00:00+00:00",
    )
    horizon_one = _row(records, horizon=1)
    horizon_twenty = _row(records, horizon=20)
    assert horizon_one["n_eff"] == horizon_one["n"]
    assert horizon_twenty["n_eff"] == horizon_twenty["n"] // 20
    assert horizon_twenty["n_eff"] < horizon_one["n_eff"]


def test_wilson_lower_bound_reference_points():
    # n=250 / hit=0.60 → 0.538；n_eff=12 / hit=0.75 → ≈0.47（≠ 用 n=250 的 0.72）
    assert abs(wilson_lower_bound(150, 250) - 0.538) < 0.002
    effective = wilson_lower_bound(9, 12)
    assert 0.45 < effective < 0.48
    # 同一命中率 0.75，用 n=250 会得到 ~0.69：n_eff 修正必须显著更保守
    assert effective < wilson_lower_bound(round(0.75 * 250), 250)
    assert wilson_lower_bound(0, 0) is None
    assert wilson_lower_bound(0, 10) == 0.0
    assert wilson_lower_bound(10, 10) < 1.0


def test_evaluation_writes_wilson_bound_with_n_eff(tmp_path):
    registry = RelationshipRegistry(tmp_path / "relationship_registry.db")
    signal, prices = _strong_relationship()
    records = evaluate_grid(
        registry=registry,
        dataset="market",
        metric="TEST",
        signal=signal,
        prices=prices,
        target="BTC",
        data_version="v1",
        run_id="run-v1",
        eval_at="2026-11-02T00:00:00+00:00",
        time_range=("2020-01-01", "2026-01-01"),
    )
    for horizon in (1, 20):
        row = _row(records, horizon=horizon)
        assert row["hit_rate"] is not None
        assert row["n_eff"] is not None
        n_hit = json.loads(row["scope_json"])["sample"]["n_hit"]
        n_eff_hit = n_hit // horizon
        assert n_eff_hit > 0
        expected = wilson_lower_bound(round(float(row["hit_rate"]) * n_eff_hit), n_eff_hit)
        assert row["hit_rate_lb"] == expected
        assert row["hit_rate_lb"] < wilson_lower_bound(
            round(float(row["hit_rate"]) * int(row["n_eff"])), int(row["n_eff"])
        )


def test_permutation_p_value_separates_signal_from_null():
    flags = [1, -1] * 10
    ys = [0.01 if flag > 0 else -0.01 for flag in flags]
    strong = permutation_p_value(ys, flags, 1, 1.0, iterations=200)
    assert strong is not None and strong < 0.05

    null = permutation_p_value([0.01, -0.01] * 10, [1] * 20, 1, 0.5, iterations=200)
    assert null is not None and null > 0.1
    assert permutation_p_value(ys, flags, 0, 1.0) is None


def _gate_row(**overrides):
    row = {
        "n": 250,
        "coverage": 1.0,
        "n_eff": 250,
        "method_gate": "ok",
        "p_adj": 0.01,
        "hit_rate": 0.62,
        "base_rate": 0.50,
        "excess_hit": 0.12,
        "hit_rate_lb": 0.56,
        "holdout_hit_rate": 0.60,
        "holdout_base_rate": 0.52,
        "holdout_agree": 1,
        "effect_bps": 20.0,
        "cost_bps": 10.0,
        "scope_json": json.dumps(
            {
                "time_range": ["2020-01-01", "2026-01-01"],
                "markets": ["BTC"],
                "params": {"transform": "raw", "horizon": 1, "hit_extreme_z": 1.0},
                "sample": {"n": 250, "n_eff": 250, "n_hit": 80, "periods": 1},
            }
        ),
    }
    row.update(overrides)
    return row


def test_gate_requires_excess_over_base_rate():
    assert _refresh_gate(_gate_row()) is True
    # 基率 0.58 / 命中 0.60：超额只有 0.02，且下界不高于基线 → 不通过
    assert (
        _refresh_gate(_gate_row(base_rate=0.58, hit_rate=0.60, excess_hit=0.02, hit_rate_lb=0.55))
        is False
    )


def test_gate_rejects_low_effective_sample():
    assert _refresh_gate(_gate_row(n_eff=12)) is False
    assert _refresh_gate(_gate_row(n=249)) is False
    assert _refresh_gate(_gate_row(coverage=0.79)) is False


def test_gate_requires_holdout_and_effect_size():
    assert _refresh_gate(_gate_row(holdout_agree=0)) is False
    assert _refresh_gate(_gate_row(holdout_hit_rate=0.54)) is False
    assert _refresh_gate(_gate_row(holdout_base_rate=0.61)) is False
    assert _refresh_gate(_gate_row(effect_bps=10.0)) is False
    assert _refresh_gate(_gate_row(effect_bps=9.9)) is False


def test_gate_requires_scope_time_range():
    assert _refresh_gate(_gate_row(scope_json=None)) is False
    assert (
        _refresh_gate(
            _gate_row(
                scope_json=json.dumps(
                    {"time_range": ["", ""], "markets": ["BTC"], "params": {}, "sample": {}}
                )
            )
        )
        is False
    )
