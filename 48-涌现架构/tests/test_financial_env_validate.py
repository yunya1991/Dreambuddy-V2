"""P2-B 联合验证单测（SPEC §7.2）：四层结构 / 门禁接线 / 诚实降级。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import factor_gate
import financial_env_align as fea
import financial_env_validate as fev
import numpy as np
import pandas as pd
import pytest
from factor_gate import VERDICTS

SYMBOLS = ("BTC", "ETH", "SOL", "AVAX", "LINK")


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    """隔离 trial/verdict 记账目录，避免读到真实 runtime 里的历史试验。"""
    monkeypatch.setattr(factor_gate, "RUNTIME_DIR", tmp_path / "runtime")


def _days(n: int = 60) -> list[date]:
    out: list[date] = []
    d = date(2026, 6, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _build(planted: bool = True, days: int = 60):
    dates = _days(days)
    rng = np.random.default_rng(11)
    prices, sentiment, form = [], [], []
    for si, sym in enumerate(SYMBOLS):
        close = 100.0
        rets = rng.normal(0.0005, 0.01, size=len(dates))
        for i, d in enumerate(dates):
            prices.append({"symbol": sym, "date": d, "close": close})
            close *= 1.0 + rets[i]
        for i, d in enumerate(dates):
            if planted:
                # close[i+1]/close[i]-1 == rets[i] → 用当日收益符号构造可预测信号
                score = float(np.sign(rets[i])) + rng.normal(0, 0.05, size=1)[0]
            else:
                score = rng.normal(0, 1, size=1)[0]
            sentiment.append(
                {
                    "symbol": sym,
                    "date": d,
                    "score": score,
                    "available_at": f"{d.isoformat()}T10:00:00Z",
                }
            )
            form.append({"symbol": sym, "date": d, "rsi14": 50.0 + si + i % 7})
    regime = [
        {
            "as_of": d.isoformat(),
            "vix": {
                "level": 16.0 + i % 5,
                "slope": 0.02,
                "vvix": 88.0,
                "bucket": ["low", "normal", "elevated"][i % 3],
            },
            "label": ["risk_on", "neutral", "risk_off"][i % 3],
            "crypto_fng": {"value": 20 + (i * 7) % 60},
        }
        for i, d in enumerate(dates)
    ]
    return pd.DataFrame(prices), pd.DataFrame(sentiment), pd.DataFrame(regime), pd.DataFrame(form)


def _aligned(planted: bool = True):
    prices, sentiment, regime, form = _build(planted)
    return fea.align(events=None, sentiment=sentiment, regime=regime, form=form, prices=prices)


NO_PREREG = Path("/nonexistent/factor_preregistration.json")  # 测试一律不写 trials/verdicts


def _validate(aligned, **kwargs):
    kwargs.setdefault("prereg_path", NO_PREREG)
    return fev.validate(aligned, **kwargs)


# ── 结构契约 ─────────────────────────────────────────────────


def test_report_structure_and_verdict_vocab():
    report = _validate(_aligned(), horizon=1, bootstrap=20)
    assert report["data_status"] == "ok"
    assert report["lookahead_violations"] == 0
    assert report["n_symbols"] == len(SYMBOLS)
    assert report["n_obs"] >= 250
    for key in ("L_A", "L_B", "L_C", "L_D", "gate", "verdict", "version"):
        assert key in report
    assert report["verdict"] in VERDICTS
    for payload in report["L_A"]["factors"].values():
        assert payload["verdict"] in VERDICTS
        assert "reasons" in payload


def test_layer_a_covers_all_layers_and_combo():
    report = _validate(_aligned(), horizon=1, bootstrap=10)
    names = set(report["L_A"]["factors"])
    assert {"E_score", "S_score", "M_score", "P_score"}.issubset(names)
    assert "ALL_layers" in names


def test_layer_b_pairs_and_grouped_ic():
    report = _validate(_aligned(), horizon=1, bootstrap=10)
    pairs = report["L_B"]["pairs"]
    assert "S_scorexP_score" in pairs
    assert "interaction" in pairs["S_scorexP_score"]
    assert set(pairs["S_scorexP_score"]["grouped"]) == {"event", "no_event"}


def test_layer_c_ablation_is_incremental():
    report = _validate(_aligned(), horizon=1, bootstrap=10)
    steps = report["L_C"]["steps"]
    assert [s["added"] for s in steps][:2] == ["E_score", "S_score"]
    assert steps[0]["controls"] == []
    assert steps[1]["controls"] == ["E_score"]
    assert steps[1]["bootstrap"]["rounds"] == 10


def test_layer_d_bucket_ic_present():
    report = _validate(_aligned(), horizon=1, bootstrap=10)
    buckets = report["L_D"]["buckets"]
    assert any(k.startswith("label=") for k in buckets)
    assert any(k.startswith("vix_bucket=") for k in buckets)
    assert any(k.startswith("fng") for k in buckets)


def test_planted_signal_is_detected():
    report = _validate(_aligned(planted=True), horizon=1, bootstrap=10)
    ic = report["L_A"]["factors"]["S_score"]["ic"]
    assert ic is not None and ic > 0.5


def test_pure_noise_has_near_zero_ic():
    report = _validate(_aligned(planted=False), horizon=1, bootstrap=10)
    ic = report["L_A"]["factors"]["S_score"]["ic"]
    assert ic is not None and abs(ic) < 0.3


# ── 诚实降级 ─────────────────────────────────────────────────


def test_without_prices_reports_insufficient_data():
    prices, sentiment, regime, form = _build()
    aligned = fea.align(None, sentiment, regime, form, prices=None)
    report = _validate(aligned, horizon=1)
    assert report["data_status"] == "insufficient_data"
    assert report["reason"] == "no_forward_returns"
    assert report["L_A"]["factors"] == {}
    assert report["verdict"] == "insufficient_data"


def test_small_sample_stays_insufficient_data():
    prices, sentiment, regime, form = _build(days=10)
    aligned = fea.align(None, sentiment, regime, form, prices=prices)
    report = _validate(aligned, horizon=1, bootstrap=5)
    assert report["data_status"] == "insufficient_data"
    assert report["reason"].startswith("n_obs=")
    assert all(f["verdict"] == "insufficient_data" for f in report["L_A"]["factors"].values())


def test_lookahead_violation_marks_falsified():
    aligned = _aligned()
    aligned = aligned.copy()
    aligned.attrs["lookahead_violations"] = [{"symbol": "BTC", "date": "2026-06-01"}]
    report = _validate(aligned, horizon=1, bootstrap=5)
    assert report["data_status"] == "insufficient_data"
    assert report["reason"] == "lookahead_violation"
    assert report["verdict"] == "falsified"


def test_unregistered_factor_never_becomes_candidate():
    """无预注册文件 → E-1 闸门生效，只能是 insufficient_data（不得伪造候选）。"""
    report = _validate(_aligned(), horizon=1, bootstrap=5)
    assert report["verdict"] == "insufficient_data"
    assert all(f["verdict"] == "insufficient_data" for f in report["L_A"]["factors"].values())
    assert all("not_preregistered" in f["reasons"] for f in report["L_A"]["factors"].values())


# ── 统计基元 ─────────────────────────────────────────────────


def test_ic_stats_requires_cross_section():
    frame = pd.DataFrame([{"symbol": "BTC", "date": date(2026, 6, 1), "f": 1.0, "r": 0.01}])
    stats = fev.ic_stats(frame, "f", "r", min_xs=3)
    assert stats["n_dates"] == 0
    assert stats["ic"] is None


def test_bootstrap_ci_bounds_mean():
    ics = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
    out = fev._bootstrap_ci(ics, rounds=50, seed=3)
    assert out["lo"] <= out["mean"] <= out["hi"]
    assert out["rounds"] == 50


# ── 39 S 层适配器（缺口 3）────────────────────────────────────


def _semantic_file(tmp_path):
    p = tmp_path / "semantic_events.jsonl"
    rows = [
        {"symbol": "BTC", "timestamp": "2026-11-03T10:00:00Z", "sentiment": {"score": 0.2}},
        {"symbol": "BTC", "timestamp": "2026-11-03T23:00:00Z", "sentiment": {"score": 0.6}},
        {"symbol": "ETH", "timestamp": "2026-11-03T12:00:00Z", "sentiment": {"score": -0.4}},
        {"symbol": "SOL", "timestamp": "2026-11-03T12:00:00Z", "sentiment": None},
        {"symbol": "", "timestamp": "2026-11-03T12:00:00Z", "sentiment": {"score": 0.9}},
        {"symbol": "LINK", "timestamp": "2026-11-03T12:00:00Z", "sentiment": {"score": None}},
        {"symbol": "AVAX", "timestamp": "bad", "sentiment": {"score": 0.1}},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def test_load_semantic_sentiment_aggregates_and_skips(tmp_path):
    df = fev.load_semantic_sentiment(_semantic_file(tmp_path))
    assert list(df.columns) == ["symbol", "date", "score", "available_at"]
    assert sorted(df["symbol"]) == ["BTC", "ETH"]  # 无 sentiment / 空 symbol / 坏时间戳均跳过
    btc = df[df["symbol"] == "BTC"].iloc[0]
    assert btc["score"] == pytest.approx(0.4)  # 同日两条取均值
    assert btc["available_at"] == pd.Timestamp("2026-11-03T23:00:00Z")  # 取最晚可见时刻
    assert df[df["symbol"] == "ETH"].iloc[0]["score"] == pytest.approx(-0.4)


def test_load_semantic_sentiment_missing_file_is_empty(tmp_path):
    df = fev.load_semantic_sentiment(tmp_path / "absent.jsonl")
    assert df.empty
    assert list(df.columns) == ["symbol", "date", "score", "available_at"]


def test_semantic_events_restore_s_score(tmp_path):
    """39 事件流 → 适配器 → align：S_score 与 L-B 的 S×P 恢复（不再只剩 E×M）。"""
    prices, sentiment, regime, form = _build()
    sem_path = tmp_path / "sem.jsonl"
    sem_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "symbol": r["symbol"],
                    "timestamp": f"{r['date']}T10:00:00Z",
                    "sentiment": {"score": r["score"]},
                }
            )
            for r in sentiment.to_dict("records")
        ),
        encoding="utf-8",
    )
    sem = fev.load_semantic_sentiment(sem_path)
    aligned = fea.align(None, sem, regime, form, prices=prices)
    report = _validate(aligned, horizon=1, bootstrap=5)
    assert report["L_A"]["factors"]["S_score"]["n_obs"] >= 250
    assert report["L_B"]["pairs"]["S_scorexP_score"]["interaction"]["ic"] is not None


def test_cli_auto_loads_semantic_events(tmp_path):
    prices, sentiment, regime, form = _build()
    prices_path = tmp_path / "prices.csv"
    prices.to_csv(prices_path, index=False)
    form_path = tmp_path / "form.csv"
    form.to_csv(form_path, index=False)
    sem_path = tmp_path / "sem.jsonl"
    sem_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "symbol": r["symbol"],
                    "timestamp": f"{r['date']}T10:00:00Z",
                    "sentiment": {"score": r["score"]},
                }
            )
            for r in sentiment.to_dict("records")
        ),
        encoding="utf-8",
    )
    regime_dir = tmp_path / "regime"
    regime_dir.mkdir()
    for row in regime.to_dict("records"):
        (regime_dir / f"{row['as_of']}.json").write_text(json.dumps(row), encoding="utf-8")
    out = tmp_path / "report.json"

    code = fev.main(
        [
            "--prices",
            str(prices_path),
            "--semantic-events",
            str(sem_path),
            "--form",
            str(form_path),
            "--regime-dir",
            str(regime_dir),
            "--prereg",
            str(tmp_path / "none.json"),
            "--horizon",
            "1",
            "--bootstrap",
            "5",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["price_source"]["sentiment"] == "39_semantic_events"
    assert report["L_A"]["factors"]["S_score"]["ic"] is not None


def test_cli_writes_report(tmp_path):
    prices, sentiment, regime, form = _build()
    prices_path = tmp_path / "prices.csv"
    prices.to_csv(prices_path, index=False)
    sent_path = tmp_path / "sent.jsonl"
    sent_path.write_text(
        "\n".join(json.dumps(r, default=str) for r in sentiment.to_dict("records")),
        encoding="utf-8",
    )
    form_path = tmp_path / "form.csv"
    form.to_csv(form_path, index=False)
    regime_dir = tmp_path / "regime"
    regime_dir.mkdir()
    for row in regime.to_dict("records"):
        (regime_dir / f"{row['as_of']}.json").write_text(json.dumps(row), encoding="utf-8")
    out = tmp_path / "report.json"

    code = fev.main(
        [
            "--prices",
            str(prices_path),
            "--sentiment",
            str(sent_path),
            "--form",
            str(form_path),
            "--regime-dir",
            str(regime_dir),
            "--prereg",
            str(tmp_path / "none.json"),
            "--horizon",
            "1",
            "--bootstrap",
            "5",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["n_symbols"] == len(SYMBOLS)
    assert report["verdict"] in VERDICTS


# ── P2：9 域 trend_20d → P 层形态上下文 ─────────────────────


def _write_sentiment_history(root: Path, n: int):
    history_dir = root / "dimension_history"
    history_dir.mkdir(parents=True)
    start = date(2026, 1, 1)
    rows = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "module": "sentiment",
            "value": float(i),
            "value_scale": "index_0_100",
        }
        for i in range(n)
    ]
    (history_dir / "sentiment.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
    )


def test_trend_context_reuses_rolling_20_observation_spearman(tmp_path):
    _write_sentiment_history(tmp_path, 21)
    context = fev.trend_context_from_history("sentiment", base_dir=tmp_path)
    assert context.shape[0] == 2  # 前 19 个观测不插值、不填 0
    assert context["trend_20d"].tolist() == [1.0, 1.0]
    assert context["symbol"].tolist() == ["", ""]
    assert context["date"].tolist() == [date(2026, 1, 20), date(2026, 1, 21)]


def test_trend_context_missing_history_is_fail_open(tmp_path):
    context = fev.trend_context_from_history("sentiment", base_dir=tmp_path)
    assert context.empty
    assert list(context.columns) == ["symbol", "date", "trend_20d"]


def test_trend_context_is_broadcast_to_all_symbols(monkeypatch):
    prices, sentiment, regime, form = _build(days=20)
    last_day = max(prices["date"])
    context = pd.DataFrame([{"symbol": "", "date": last_day, "trend_20d": 0.75}])
    monkeypatch.setattr(fev, "trend_context_from_history", lambda *args, **kwargs: context)

    enriched = fev.add_trend_context(form)
    aligned = fea.align(None, sentiment, regime, enriched, prices=prices)
    assert "P_trend_20d" in aligned.columns
    latest = aligned.xs(last_day, level="date")["P_trend_20d"]
    assert latest.shape[0] == len(SYMBOLS)
    assert (latest == 0.75).all()


def test_add_trend_context_preserves_form_when_history_unavailable(tmp_path):
    _, _, _, form = _build(days=20)
    enriched = fev.add_trend_context(form, base_dir=tmp_path)
    pd.testing.assert_frame_equal(enriched, form)


def test_market_trend_context_uses_time_series_ic(monkeypatch):
    prices, sentiment, regime, form = _build(days=60)
    days = sorted(prices["date"].unique())
    context = pd.DataFrame(
        [
            {"symbol": "", "date": day, "trend_20d": index / len(days)}
            for index, day in enumerate(days)
        ]
    )
    monkeypatch.setattr(fev, "trend_context_from_history", lambda *args, **kwargs: context)

    aligned = fea.align(None, sentiment, regime, fev.add_trend_context(form), prices=prices)
    report = _validate(aligned, horizon=1, bootstrap=5)
    trend = report["L_A"]["factors"]["P_trend_20d"]
    assert trend["mode"] == "time_series"
    assert trend["n_dates"] >= 30
    assert trend["verdict"] == "insufficient_data"  # 未单独预注册，不伪报候选
