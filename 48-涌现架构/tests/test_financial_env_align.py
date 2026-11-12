"""P2-A 对齐器单测（SPEC §7.1）：列契约 / 索引 / 可交易时点 / 广播 / 前视审计。"""

from __future__ import annotations

from datetime import date

import financial_env_align as fea
import pandas as pd
import pytest

DAYS = [date(2026, 11, 2) + pd.Timedelta(days=i) for i in range(12)]
DAYS = [d.date() if hasattr(d, "date") else d for d in DAYS]
DAYS = [d for d in DAYS if d.weekday() < 5]  # 10 个工作日


def _prices(
    symbols=("BTC", "ETH"),
    closes=(100.0, 110.0, 121.0, 108.9, 120.0, 132.0, 120.0, 130.0, 143.0, 150.0),
):
    rows = []
    for sym in symbols:
        for i, d in enumerate(DAYS):
            rows.append({"symbol": sym, "date": d, "close": closes[i]})
    return pd.DataFrame(rows)


def _regime():
    return pd.DataFrame(
        [
            {
                "as_of": d.isoformat(),
                "vix": {"level": 18.0, "slope": 0.06, "vvix": 90.0, "bucket": "normal"},
                "label": "risk_on",
                "crypto_fng": {"value": 55},
            }
            for d in DAYS
        ]
    )


def _form(symbols=("BTC", "ETH")):
    rows = []
    for sym in symbols:
        for i, d in enumerate(DAYS):
            rows.append({"symbol": sym, "date": d, "rsi14": 50.0 + i, "ma_stack_perfect_bull": 1.0})
    return pd.DataFrame(rows)


def _sentiment(rows=None):
    if rows is not None:
        return pd.DataFrame(rows)
    return pd.DataFrame(
        [{"symbol": s, "date": d, "score": 0.3} for s in ("BTC", "ETH") for d in DAYS]
    )


def _events(rows=None):
    if rows is not None:
        return pd.DataFrame(rows)
    return pd.DataFrame(
        [
            {
                "symbol": "BTC",
                "available_at": f"{DAYS[2].isoformat()}T03:20:00Z",
                "direction": "bullish",
                "surprise": 0.8,
            }
        ]
    )


def _align(**overrides):
    kwargs = {
        "events": _events(),
        "sentiment": _sentiment(),
        "regime": _regime(),
        "form": _form(),
        "prices": _prices(),
        "asset_class": "crypto",
    }
    kwargs.update(overrides)
    return fea.align(**kwargs)


# ── 契约 ─────────────────────────────────────────────────────


def test_columns_and_index_contract():
    df = _align()
    assert df.index.names == ["symbol", "date"]
    assert list(df.index.get_level_values("symbol").unique()) == ["BTC", "ETH"]
    required = {
        "E_has_event",
        "E_event_count",
        "E_surprise",
        "E_direction",
        "S_score",
        "M_vix_level",
        "M_slope",
        "M_vix_bucket_code",
        "M_label",
        "M_fng",
        "P_rsi14",
        "P_ma_stack_perfect_bull",
        "in_event_window",
        "label",
        "feat_as_of",
    }
    assert required.issubset(df.columns)
    for h in fea.FORWARD_HORIZONS:
        assert f"forward_ret_{h}d" in df.columns
    assert df.index.is_monotonic_increasing


def test_empty_inputs_return_empty_frame():
    df = fea.align(None, None, None, None)
    assert df.empty
    assert df.index.names == ["symbol", "date"]
    assert df.attrs["lookahead_violations"] == []


def test_no_prices_still_aligns_but_returns_nan():
    df = _align(prices=None)
    assert not df.empty
    assert df["forward_ret_5d"].isna().all()
    assert df["label"].isna().all()


def test_forward_return_uses_next_day_close():
    df = _align()
    row = df.loc[("BTC", DAYS[0])]
    assert row["forward_ret_1d"] == pytest.approx(110.0 / 100.0 - 1)
    assert row["forward_ret_3d"] == pytest.approx(108.9 / 100.0 - 1)
    # 最后一天没有未来价格
    assert pd.isna(df.loc[("BTC", DAYS[-1]), "forward_ret_1d"])


def test_label_follows_main_horizon():
    df = _align(horizon=3)
    row = df.loc[("BTC", DAYS[0])]
    assert row["label"] == 1.0  # 3 日后 121 > 100
    df5 = _align()
    assert df5.attrs["horizon"] == 5


# ── 可交易时点 ───────────────────────────────────────────────


def test_next_tradable_date_crypto_is_next_hour():
    assert fea.next_tradable_date("2026-11-10T03:20:00Z", "crypto") == date(2026, 11, 10)
    # 23:30 → 次日 00:00
    assert fea.next_tradable_date("2026-11-10T23:30:00Z", "crypto") == date(2026, 11, 11)


def test_next_tradable_date_equity_skips_weekend():
    assert fea.next_tradable_date("2026-11-13T15:00:00Z", "us_equity") == date(2026, 11, 16)
    assert fea.next_tradable_date("2026-11-12T15:00:00Z", "us_equity") == date(2026, 11, 13)
    assert fea.next_tradable_date("not-a-date", "us_equity") is None


def test_event_lands_on_first_tradable_date():
    df = _align()
    hit = df.loc[("BTC", DAYS[2])]
    assert hit["E_has_event"] == 1.0
    assert hit["E_event_count"] == 1.0
    assert hit["E_direction"] == pytest.approx(1.0)
    assert hit["E_surprise"] == pytest.approx(0.8)
    assert df.loc[("BTC", DAYS[1]), "E_has_event"] == 0.0


def test_equity_event_pushed_to_next_business_day():
    events = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "available_at": "2026-11-13T21:00:00Z",
                "direction": "bearish",
                "surprise": -0.2,
            }
        ]
    )
    days = [*DAYS, date(2026, 11, 16), date(2026, 11, 17)]
    prices = pd.DataFrame(
        [{"symbol": "AAPL", "date": d, "close": 100.0 + i} for i, d in enumerate(days)]
    )
    df = fea.align(events, None, None, None, prices=prices, asset_class="us_equity")
    assert df.loc[("AAPL", date(2026, 11, 16)), "E_has_event"] == 1.0
    assert df.loc[("AAPL", date(2026, 11, 13)), "E_has_event"] == 0.0


# ── 市场级广播 ───────────────────────────────────────────────


def test_market_level_event_broadcast_to_all_symbols():
    events = pd.DataFrame(
        [{"symbol": "", "available_at": f"{DAYS[3].isoformat()}T14:00:00Z", "direction": "bearish"}]
    )
    df = _align(events=events)
    for sym in ("BTC", "ETH"):
        assert df.loc[(sym, DAYS[3]), "E_has_event"] == 1.0
        assert df.loc[(sym, DAYS[3]), "E_direction"] == pytest.approx(-1.0)
        assert df.loc[(sym, DAYS[2]), "E_has_event"] == 0.0


def test_market_sentiment_broadcast_keeps_symbol_values():
    sent = pd.DataFrame(
        [{"symbol": "", "date": d, "score": -0.5} for d in DAYS]
        + [{"symbol": "BTC", "date": DAYS[0], "score": 0.9}]
    )
    df = _align(sentiment=sent)
    assert df.loc[("BTC", DAYS[0]), "S_score"] == pytest.approx(0.9)
    assert df.loc[("ETH", DAYS[0]), "S_score"] == pytest.approx(-0.5)
    assert df.loc[("BTC", DAYS[1]), "S_score"] == pytest.approx(-0.5)


def test_market_form_broadcast():
    form = pd.DataFrame([{"symbol": "", "date": d, "rsi14": 20.0} for d in DAYS])
    df = _align(form=form)
    assert df["P_rsi14"].eq(20.0).all()


# ── 事件窗口 / 前视审计 ──────────────────────────────────────


def test_event_window_marks_plus_minus_one_day():
    df = _align()
    d = DAYS[2]
    assert bool(df.loc[("BTC", DAYS[1]), "in_event_window"])
    assert bool(df.loc[("BTC", d), "in_event_window"])
    assert bool(df.loc[("BTC", DAYS[3]), "in_event_window"])
    assert not bool(df.loc[("BTC", DAYS[4]), "in_event_window"])
    # 事件只属于 BTC，ETH 不在窗口内
    assert not bool(df.loc[("ETH", d), "in_event_window"])


def test_market_event_window_covers_all_symbols():
    events = pd.DataFrame([{"symbol": "", "available_at": f"{DAYS[3].isoformat()}T00:30:00Z"}])
    df = _align(events=events)
    assert bool(df.loc[("BTC", DAYS[2]), "in_event_window"])
    assert bool(df.loc[("ETH", DAYS[4]), "in_event_window"])


def test_align_has_zero_lookahead_violations():
    df = _align()
    assert df.attrs["lookahead_violations"] == []
    assert fea.audit_lookahead(df) == []


def test_feat_as_of_is_reported_per_row():
    df = _align()
    ts = df.loc[("BTC", DAYS[0]), "feat_as_of"]
    assert pd.Timestamp(ts) == pd.Timestamp("2026-11-02T23:59:00Z")


def test_audit_detects_future_feature():
    idx = pd.MultiIndex.from_tuples([("BTC", date(2026, 11, 2))], names=["symbol", "date"])
    df = pd.DataFrame({"feat_as_of": [pd.Timestamp("2026-11-03T00:00:00Z")]}, index=idx)
    violations = fea.audit_lookahead(df)
    assert len(violations) == 1
    assert violations[0]["symbol"] == "BTC"


def test_audit_skips_empty_frame():
    empty = pd.DataFrame(columns=["feat_as_of"])
    empty.index = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
    assert fea.audit_lookahead(empty) == []


# ── 层解析 ───────────────────────────────────────────────────


def test_regime_nested_and_flat_schema():
    flat = pd.DataFrame(
        [
            {
                "date": d.isoformat(),
                "vix_level": 22.0,
                "vix_slope": -0.02,
                "vix_bucket": "elevated",
                "fng": 80,
            }
            for d in DAYS
        ]
    )
    df = _align(regime=flat)
    assert df["M_vix_level"].eq(22.0).all()
    assert df["M_vix_bucket_code"].eq(2.0).all()
    assert df["M_fng"].eq(80.0).all()


def test_form_only_numeric_columns_are_copied():
    form = pd.DataFrame([{"symbol": "BTC", "date": DAYS[0], "rsi14": 55.0, "state": "bull"}])
    df = _align(
        form=form, prices=pd.DataFrame([{"symbol": "BTC", "date": DAYS[0], "close": 100.0}])
    )
    assert "P_rsi14" in df.columns
    assert not any(c.startswith("P_state") for c in df.columns)


def test_prices_requires_close_column():
    bad = pd.DataFrame([{"symbol": "BTC", "date": DAYS[0], "price": 1.0}])
    with pytest.raises(ValueError):
        fea.align(None, None, None, None, prices=bad)
