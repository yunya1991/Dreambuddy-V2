"""B-06: D2 OI / 清算叠加测试（临时 SQLite + 19-DAL schema）."""
from __future__ import annotations

import sqlite3
import time

import pytest

from dreambuddy_evolution.core.dimension_force_evaluator import (
    DimensionForceEvaluator,
)

NOW = int(time.time())


def _make_db(tmp_path, *, with_derivatives=True):
    db_path = tmp_path / "d2.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE mm_metrics ("
        "sub_category TEXT, metric_name TEXT, metric_value REAL, timestamp INTEGER)"
    )
    if with_derivatives:
        conn.execute(
            "CREATE TABLE mm_open_interest ("
            "symbol TEXT, timestamp INTEGER, open_interest REAL, oi_change_pct_24h REAL)"
        )
        conn.execute(
            "CREATE TABLE mm_liquidation ("
            "symbol TEXT, timestamp INTEGER, liq_long_usdt REAL, "
            "liq_short_usdt REAL, liq_total_usdt REAL)"
        )
    conn.commit()
    return db_path, conn


def _insert_ls_history(conn, latest=1.3, count=30):
    for index in range(count - 1):
        conn.execute(
            "INSERT INTO mm_metrics VALUES (?,?,?,?)",
            (
                "long_short_ratio",
                "long_short_ratio",
                0.9 if index % 2 == 0 else 1.1,
                NOW - (count - index) * 60,
            ),
        )
    conn.execute(
        "INSERT INTO mm_metrics VALUES (?,?,?,?)",
        ("long_short_ratio", "long_short_ratio", latest, NOW),
    )
    conn.commit()


def _insert_funding(conn, rate=0.0001):
    conn.execute(
        "INSERT INTO mm_metrics VALUES (?,?,?,?)",
        ("funding_rate", "funding_rate", rate, NOW),
    )
    conn.commit()


def _insert_oi(conn, symbol="BTC", oi=1000.0, change=0.10, ts=None):
    conn.execute(
        "INSERT INTO mm_open_interest VALUES (?,?,?,?)",
        (symbol, ts if ts is not None else NOW, oi, change),
    )
    conn.commit()


def _insert_liq(conn, symbol="BTC", long_usdt=800.0, short_usdt=200.0, ts=None):
    conn.execute(
        "INSERT INTO mm_liquidation VALUES (?,?,?,?,?)",
        (
            symbol,
            ts if ts is not None else NOW - 3600,
            long_usdt,
            short_usdt,
            long_usdt + short_usdt,
        ),
    )
    conn.commit()


@pytest.fixture
def d2_on():
    from dreambuddy_evolution.agi_config import reset_switches, set_switch

    reset_switches()
    set_switch("enable_d2_oi_liq", True)
    yield
    reset_switches()


class TestD2OiLiq:
    def test_empty_db_fail_open(self, tmp_path):
        db_path, conn = _make_db(tmp_path)
        conn.close()
        out = DimensionForceEvaluator(str(db_path)).evaluate_d2()
        assert out["direction"] == "neutral"
        assert out["coverage"] == 0.0
        assert out["components"] == {}

    def test_switch_off_ignores_oi_liq(self, tmp_path):
        db_path, conn = _make_db(tmp_path)
        _insert_oi(conn)
        _insert_liq(conn)
        conn.close()
        out = DimensionForceEvaluator(str(db_path)).evaluate_d2()
        assert out["direction"] == "neutral"
        assert out["coverage"] == 0.5
        assert "open_interest" in out["components"]
        assert "liquidation" in out["components"]

    def test_switch_on_long_liquidation_pressure(self, tmp_path, d2_on):
        db_path, conn = _make_db(tmp_path)
        _insert_liq(conn, long_usdt=800.0, short_usdt=200.0)
        conn.close()
        out = DimensionForceEvaluator(str(db_path)).evaluate_d2()
        assert out["direction"] == "short"
        assert out["strength"] == pytest.approx(0.6, abs=1e-6)
        assert out["coverage"] == 0.25

    def test_switch_on_short_liquidation_pressure(self, tmp_path, d2_on):
        db_path, conn = _make_db(tmp_path)
        _insert_liq(conn, long_usdt=200.0, short_usdt=800.0)
        conn.close()
        out = DimensionForceEvaluator(str(db_path)).evaluate_d2()
        assert out["direction"] == "long"
        assert out["strength"] == pytest.approx(0.6, abs=1e-6)

    def test_full_coverage(self, tmp_path, d2_on):
        db_path, conn = _make_db(tmp_path)
        _insert_ls_history(conn)
        _insert_funding(conn)
        _insert_oi(conn)
        _insert_liq(conn)
        conn.close()
        out = DimensionForceEvaluator(str(db_path)).evaluate_d2()
        assert out["coverage"] == 1.0
        assert set(out["components"]) == {
            "long_short_ratio",
            "funding_rate",
            "open_interest",
            "liquidation",
        }
        assert out["direction"] == "short"

    def test_legacy_coverage_without_derivatives(self, tmp_path):
        db_path, conn = _make_db(tmp_path, with_derivatives=False)
        _insert_ls_history(conn)
        _insert_funding(conn)
        conn.close()
        out = DimensionForceEvaluator(str(db_path)).evaluate_d2()
        assert out["coverage"] == 0.5
        assert set(out["components"]) == {"long_short_ratio", "funding_rate"}

    def test_oi_change_from_two_rows(self, tmp_path, d2_on):
        db_path, conn = _make_db(tmp_path)
        _insert_ls_history(conn)
        _insert_oi(conn, oi=1000.0, change=None, ts=NOW - 86400)
        _insert_oi(conn, oi=1100.0, change=None, ts=NOW)
        conn.close()
        out = DimensionForceEvaluator(str(db_path)).evaluate_d2()
        oi = out["components"]["open_interest"]
        assert oi["change_pct_24h"] == pytest.approx(0.1, rel=1e-3)
        assert oi["part"] == pytest.approx(0.5, abs=1e-6)

    def test_stale_oi_is_ignored(self, tmp_path, d2_on):
        db_path, conn = _make_db(tmp_path)
        _insert_ls_history(conn)
        _insert_oi(conn, ts=NOW - 8 * 86400)
        conn.close()
        out = DimensionForceEvaluator(str(db_path)).evaluate_d2()
        assert "open_interest" not in out["components"]
        assert out["coverage"] == 0.25

    def test_symbol_parameter(self, tmp_path, d2_on):
        db_path, conn = _make_db(tmp_path)
        _insert_liq(conn, symbol="BTC", long_usdt=800.0, short_usdt=200.0)
        _insert_liq(conn, symbol="ETH", long_usdt=200.0, short_usdt=800.0)
        conn.close()
        evaluator = DimensionForceEvaluator(str(db_path))
        btc = evaluator.evaluate_d2("BTC")
        eth = evaluator.evaluate_d2("ETH")
        assert btc["direction"] == "short"
        assert eth["direction"] == "long"
        assert btc["symbol"] == "BTC"
        assert eth["symbol"] == "ETH"

    def test_d2_coverage_method(self, tmp_path, d2_on):
        db_path, conn = _make_db(tmp_path)
        _insert_ls_history(conn)
        _insert_funding(conn)
        _insert_oi(conn)
        _insert_liq(conn)
        conn.close()
        coverage = DimensionForceEvaluator(str(db_path)).d2_coverage()
        assert coverage["symbol"] == "BTC"
        assert coverage["coverage"] == 1.0
        assert len(coverage["components"]) == 4

    def test_switch_default_off(self):
        from dreambuddy_evolution.agi_config import get_switch

        assert get_switch("enable_d2_oi_liq", False) is False