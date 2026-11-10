"""P0-3 因子先验适配器 — SPEC §2.10 A1。"""

from __future__ import annotations

import json

from data_center.processing.factor_prior import (
    MIN_N,
    PRIOR_VERSION,
    build_factor_prior,
    load_factor_prior,
)

ROWS = [
    # 有效：macro 负向、flow 正向、sentiment 正向（弱于前两个）
    {
        "factor_id": "macro.rate",
        "n": 100,
        "mean_excess_pre": -0.004,
        "mean_excess_post": -0.003,
        "eligible": True,
        "verdict": "positive",
        "direction": -1,
        "p_value": 0.01,
        "as_of": "2026-05-29",
    },
    {
        "factor_id": "flow.funding",
        "n": 80,
        "mean_excess_pre": 0.002,
        "mean_excess_post": 0.0025,
        "eligible": True,
        "verdict": "positive",
        "direction": 1,
        "p_value": 0.03,
        "as_of": "2026-05-29",
    },
    {
        "factor_id": "sentiment.cycle",
        "n": 60,
        "mean_excess_pre": 0.001,
        "mean_excess_post": 0.001,
        "eligible": True,
        "verdict": "positive",
        "direction": 1,
        "p_value": 0.04,
        "as_of": "2026-05-29",
    },
    # 样本不足
    {
        "factor_id": "technical.trend",
        "n": MIN_N - 1,
        "mean_excess_pre": 0.05,
        "mean_excess_post": 0.05,
        "eligible": True,
        "direction": 1,
    },
    # 反转：不得进入正向池
    {
        "factor_id": "onchain.tvl",
        "n": 50,
        "mean_excess_pre": 0.01,
        "mean_excess_post": -0.01,
        "eligible": False,
        "verdict": "reversal",
    },
    # 无方向
    {"factor_id": "macro.dollar", "n": 50, "eligible": True, "direction": 0},
]


def _write_rows(tmp_path, rows=ROWS):
    p = tmp_path / "factor_sensitivity.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def test_build_selects_eligible_sorts_by_abs_sens(tmp_path):
    src = _write_rows(tmp_path)
    out = tmp_path / "factor_prior.json"
    res = build_factor_prior(sensitivity_path=src, out_path=out, enabled=True)
    assert res["version"] == PRIOR_VERSION
    assert res["degraded"] is False
    ids = [x["factor_id"] for x in res["factors"]]
    assert ids == ["macro.rate", "flow.funding", "sentiment.cycle"]
    assert res["factors"][0]["sens_f"] < 0  # 方向保留
    assert res["dims"]["D1"] > 0


def test_missing_sensitivity_degrades_without_raise(tmp_path):
    out = tmp_path / "factor_prior.json"
    res = build_factor_prior(sensitivity_path=tmp_path / "nope.jsonl", out_path=out, enabled=True)
    assert res["degraded"] is True
    assert res["reason"] == "sensitivity_missing"
    assert res["factors"] == []
    assert load_factor_prior(out) is None


def test_bad_lines_and_unusable_rows_skipped(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        "not-json\n"
        + json.dumps({"factor_id": "", "n": 99, "eligible": True})
        + "\n"
        + json.dumps(
            {
                "factor_id": "flow.oi",
                "n": 40,
                "eligible": True,
                "direction": 1,
                "mean_excess_pre": 0.002,
                "mean_excess_post": 0.001,
            }
        ),
        encoding="utf-8",
    )
    res = build_factor_prior(sensitivity_path=p, out_path=tmp_path / "o.json", enabled=True)
    assert [x["factor_id"] for x in res["factors"]] == ["flow.oi"]


def test_dim_rows_expand_to_factor_ids(tmp_path):
    p = tmp_path / "dim.jsonl"
    p.write_text(
        json.dumps(
            {
                "unit": "dim",
                "key": "D1",
                "factor_ids": ["macro.rate", "macro.dollar"],
                "n_events": 100,
                "sens_f": 0.004,
                "eligible": True,
                "p_value": 0.01,
            }
        ),
        encoding="utf-8",
    )
    res = build_factor_prior(sensitivity_path=p, out_path=tmp_path / "o.json", enabled=True)
    assert [x["factor_id"] for x in res["factors"]] == ["macro.rate", "macro.dollar"]
    assert all(x["granularity"] == "dim" for x in res["factors"])


def test_roundtrip_load(tmp_path):
    src = _write_rows(tmp_path)
    out = tmp_path / "factor_prior.json"
    build_factor_prior(sensitivity_path=src, out_path=out, enabled=True)
    loaded = load_factor_prior(out, as_of="2026-06-01")
    assert loaded is not None
    assert loaded["n_factors"] == 3


def test_load_rejects_future_prior(tmp_path):
    src = _write_rows(tmp_path)
    out = tmp_path / "factor_prior.json"
    build_factor_prior(sensitivity_path=src, out_path=out, enabled=True)
    assert load_factor_prior(out, as_of="2026-05-01") is None


def test_load_rejects_version_mismatch_and_corruption(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps({"version": "old-v0", "factors": [{"factor_id": "x"}]}), encoding="utf-8"
    )
    assert load_factor_prior(p) is None
    p.write_text("{not json", encoding="utf-8")
    assert load_factor_prior(p) is None


def test_newsflash_prior_disabled_by_default(tmp_path, monkeypatch):
    """默认关闭：即使源里有 eligible 因子，也不产出先验（P3-c1/c1h 双证失败）。"""
    monkeypatch.delenv("DREAM_ENABLE_NEWSFLASH_PRIOR", raising=False)
    src = _write_rows(tmp_path)
    out = tmp_path / "factor_prior.json"
    res = build_factor_prior(sensitivity_path=src, out_path=out)
    assert res["degraded"] is True
    assert res["reason"] == "newsflash_prior_disabled_by_default"
    assert res["n_factors"] == 0
    assert load_factor_prior(out) is None


def test_newsflash_prior_env_switch_can_reenable(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAM_ENABLE_NEWSFLASH_PRIOR", "1")
    src = _write_rows(tmp_path)
    out = tmp_path / "factor_prior.json"
    res = build_factor_prior(sensitivity_path=src, out_path=out)
    assert res["degraded"] is False
    assert res["n_factors"] == 3
