"""M 层 RegimeSchema（SPEC §5.1 / P1-B）单测：分档 / 期限结构 / 标签 / null 纪律 / 连续性。"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, timedelta

import pytest
import regime


def _rows(n=40, start=date(2026, 8, 3), **overrides):
    """按工作日生成连续日频序列（默认 vix=18 / vix3m=19 / vvix=90）。"""
    rows: list[dict] = []
    day = start
    while len(rows) < n:
        if day.weekday() < 5:
            level = 18.0
            three_m = 19.0
            row = {
                "date": day.isoformat(),
                "vix": level,
                "vix3m": three_m,
                "vix_ratio": round(level / three_m, 6),
                "vvix": 90.0,
                "put_call_ratio": None,
                "source": "fred",
            }
            row.update({k: v for k, v in overrides.items() if not callable(v)})
            if callable(overrides.get("builder")):
                overrides["builder"](row, len(rows))
            rows.append(row)
        day += timedelta(days=1)
    return rows


# ── 分档 / 期限结构 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "level,expected",
    [
        (14.99, "low"),
        (15.0, "normal"),
        (19.99, "normal"),
        (20.0, "elevated"),
        (29.99, "elevated"),
        (30.0, "crisis"),
        (None, None),
    ],
)
def test_bucket_boundaries(level, expected):
    assert regime.bucket_of(level) == expected


@pytest.mark.parametrize(
    "slope,expected",
    [
        (0.1, "contango"),
        (-0.1, "backwardation"),
        (0.0, "flat"),
        (0.003, "flat"),
        (0.006, "contango"),
        (-0.006, "backwardation"),
        (None, None),
    ],
)
def test_term_structure(slope, expected):
    assert regime.term_structure_of(slope) == expected


@pytest.mark.parametrize(
    "bucket,slope,fng_value,expected",
    [
        ("crisis", 0.1, 50, "crisis"),
        ("normal", 0.1, 20, "crisis"),  # 极度恐惧 → crisis
        ("normal", 0.1, 25, "risk_neutral"),  # 边界不算极值
        ("normal", 0.1, 80, "risk_off"),  # 极度贪婪 → risk_off（不是 crisis）
        ("normal", 0.1, 75, "risk_neutral"),  # 边界不算极值
        ("elevated", 0.1, 50, "risk_off"),
        ("normal", -0.05, 50, "risk_off"),  # 倒挂 → risk_off
        ("normal", -0.003, 50, "risk_neutral"),  # 平水（|slope|<eps）不算 risk_off
        ("low", 0.1, 50, "risk_on"),
        ("normal", 0.1, 50, "risk_neutral"),
    ],
)
def test_classify(bucket, slope, fng_value, expected):
    assert regime.classify(bucket, slope, fng_value) == expected


# ── Schema 组装 ─────────────────────────────────────────────


def test_schema_full_components_confidence_one():
    schema = regime.build_regime_schema(_rows(), crypto_fng={"value": 40, "label": "neutral"})
    assert schema["as_of"] == "2026-09-25"
    assert schema["vix"]["level"] == 18.0
    assert schema["vix"]["bucket"] == "normal"
    assert schema["vix"]["vix3m"] == 19.0
    assert schema["vix"]["term_structure"] == "contango"
    assert schema["vix"]["put_call"] is None
    assert schema["vix"]["term_as_of"] == "2026-09-25"  # 末行自身完整
    assert 0.0 <= schema["vix"]["percentile_1y"] <= 1.0
    assert schema["label"] == "risk_neutral"
    assert schema["confidence"] == 1.0
    assert schema["source"] == "fred"


def test_schema_keeps_nulls_when_secondary_sources_missing():
    rows = _rows(
        builder=lambda row, i: row.update({"vix3m": None, "vix_ratio": None, "vvix": None})
    )
    schema = regime.build_regime_schema(rows)
    assert schema["vix"]["vix3m"] is None
    assert schema["vix"]["slope"] is None
    assert schema["vix"]["vvix"] is None
    assert schema["vix"]["put_call"] is None
    assert schema["vix"]["term_structure"] is None
    assert schema["crypto_fng"] is None
    assert schema["confidence"] == 0.4  # 仅 level 分量可得


def test_schema_fng_extremes_are_directional():
    fear = regime.build_regime_schema(_rows(), crypto_fng={"value": 20})
    assert fear["label"] == "crisis"
    greed = regime.build_regime_schema(_rows(), crypto_fng={"value": 82})
    assert greed["label"] == "risk_off"


def test_schema_reuses_last_complete_term_row_with_term_as_of():
    rows = _rows()
    rows.append(
        {
            "date": "2026-09-28",
            "vix": 21.0,
            "vix3m": None,
            "vix_ratio": None,
            "vvix": None,
            "put_call_ratio": None,
            "source": "yahoo",
        }
    )
    schema = regime.build_regime_schema(rows)
    assert schema["as_of"] == "2026-09-28"
    assert schema["vix"]["level"] == 21.0
    assert schema["vix"]["slope"] is not None
    assert schema["vix"]["term_structure"] == "contango"
    assert schema["vix"]["term_as_of"] == "2026-09-25"  # T-1 完整行复用
    assert schema["confidence"] == pytest.approx(0.8)  # level+term+vvix


def test_schema_skips_term_row_without_vix():
    """CBOE 单边行（有 vix3m 无 vix）不能算完整期限结构，需继续回退到更早的完整行。"""
    rows = _rows()
    rows.append(
        {
            "date": "2026-09-28",
            "vix": None,
            "vix3m": 22.0,
            "vix_ratio": None,
            "vvix": 99.0,
            "put_call_ratio": None,
            "source": "cboe",
        }
    )
    rows.append(
        {
            "date": "2026-09-29",
            "vix": 21.0,
            "vix3m": None,
            "vix_ratio": None,
            "vvix": None,
            "put_call_ratio": None,
            "source": "yahoo",
        }
    )
    schema = regime.build_regime_schema(rows)
    assert schema["as_of"] == "2026-09-29"
    assert schema["vix"]["level"] == 21.0
    assert schema["vix"]["term_as_of"] == "2026-09-25"
    assert schema["vix"]["vix3m"] == 19.0  # 不能用 09-28 的 22.0 配 09-29 的 21.0
    assert schema["vix"]["slope"] == pytest.approx(round(19.0 / 18.0 - 1, 6))


def test_schema_vix_crisis_bucket():
    schema = regime.build_regime_schema(_rows(builder=lambda row, i: row.update({"vix": 33.0})))
    assert schema["vix"]["bucket"] == "crisis"
    assert schema["label"] == "crisis"


def test_schema_rejects_empty_rows():
    with pytest.raises(ValueError):
        regime.build_regime_schema([])


# ── 30 天连续性 ─────────────────────────────────────────────


def test_gap_report_passes_on_continuous_month():
    report = regime.gap_report(_rows(), days=30)
    assert report["ok"] is True
    assert report["observed"] >= regime.MIN_OBSERVATIONS
    assert report["gaps"] == []


def test_gap_report_detects_hole():
    rows = [
        r
        for r in _rows()
        if r["date"]
        not in {"2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26"}
    ]
    report = regime.gap_report(rows, days=60)
    assert report["ok"] is False
    assert report["gaps"]
    assert report["gaps"][0]["days"] > regime.MAX_GAP_DAYS


def test_gap_report_without_data():
    report = regime.gap_report([])
    assert report["ok"] is False
    assert report["observed"] == 0


# ── crypto F&G 接入（缺口 2）─────────────────────────────────


def _fng_db(tmp_path, rows):
    db = tmp_path / "data_center.db"
    con = sqlite3.connect(db)
    con.execute(
        "create table records (id integer primary key, source text, category text, "
        "sub_category text, timestamp text, metrics text)"
    )
    con.executemany(
        "insert into records (source, category, sub_category, timestamp, metrics) "
        "values ('fear_greed', 'crypto', 'crypto_fear_greed', ?, ?)",
        [(ts, json.dumps(m)) for ts, m in rows],
    )
    con.commit()
    con.close()
    return db


def test_load_crypto_fng_history_keeps_latest_row_per_day(tmp_path):
    db = _fng_db(
        tmp_path,
        [
            ("2026-10-28T01:00:00Z", {"asset": "", "value": 40.0}),
            ("2026-10-28T19:00:00Z", {"asset": "", "value": 71.0}),  # 同日更晚 → 覆盖
            ("2026-10-29T09:00:00Z", {"asset": "", "value": 20.0}),
            ("2026-10-29T10:00:00Z", {"asset": "", "value": "bad"}),  # 坏行跳过
        ],
    )
    history = regime.load_crypto_fng_history(db)
    assert set(history) == {"2026-10-28", "2026-10-29"}
    assert history["2026-10-28"] == {"value": 71.0, "as_of": "2026-10-28"}
    assert history["2026-10-29"]["value"] == 20.0


def test_load_crypto_fng_history_missing_db_is_empty(tmp_path):
    assert regime.load_crypto_fng_history(tmp_path / "absent.db") == {}


def test_pick_crypto_fng_prefers_exact_then_fresh_fallback():
    history = {"2026-10-20": {"value": 30.0}, "2026-10-28": {"value": 71.0}}
    assert regime.pick_crypto_fng(history, "2026-10-28")["value"] == 71.0
    assert regime.pick_crypto_fng(history, "2026-10-31")["value"] == 71.0  # 3 天内回退
    assert regime.pick_crypto_fng(history, "2026-11-05") is None  # 超过容忍期 → 缺失，不冒充
    assert regime.pick_crypto_fng(history, "2026-10-01") is None
    assert regime.pick_crypto_fng({}, "2026-10-28") is None


def test_write_history_injects_crypto_fng(tmp_path, monkeypatch):
    monkeypatch.setattr(regime, "RUNTIME_DIR", tmp_path / "regime")
    monkeypatch.setattr(regime, "load_rows", lambda days=400: _rows(n=25))
    monkeypatch.setattr(
        regime,
        "load_crypto_fng_history",
        lambda path=None: {"2026-08-03": {"value": 12.0, "as_of": "2026-08-03"}},
    )
    monkeypatch.setattr(sys, "argv", ["regime.py", "--write-history"])
    assert regime.main() == 0

    first = json.loads((tmp_path / "regime" / "2026-08-03.json").read_text(encoding="utf-8"))
    assert first["crypto_fng"] == {"value": 12.0, "as_of": "2026-08-03"}
    assert first["label"] == "crisis"  # <25 → crisis
    second = json.loads((tmp_path / "regime" / "2026-08-04.json").read_text(encoding="utf-8"))
    assert second["crypto_fng"]["as_of"] == "2026-08-03"  # 当日无 F&G → 回退最近一条
    assert second["confidence"] == 1.0
