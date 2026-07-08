import json
from pathlib import Path


def test_render_dashboard_html(tmp_path: Path):
    from scripts.memory_l4.dashboard_renderer import render_dashboard_html

    stats = {
        "snapshot_ts": "2026-01-01T00:00:00+08:00",
        "points": [
            {
                "id": "TC_1",
                "kind": "case",
                "x": 0.5,
                "y": 0.6,
                "inst_id": "BTC-USDT-SWAP",
                "regime": "RANGE_BOUND",
                "tags": []
            },
            {
                "id": "D_1",
                "kind": "distill",
                "x": -0.4,
                "y": 0.7,
                "inst_id": None,
                "regime": None,
                "tags": []
            }
        ],
        "performance": {
            "win_rate": 0.66,
            "profit_factor": 1.8,
            "max_drawdown": 5.0,
            "avg_pnl_usdt": 3.2
        },
        "aggregations": {
            "cases_by_regime": {"RANGE_BOUND": 1}
        },
        "migration_trends": [
            {"id": "D_1", "kind": "distill", "series": [{"ts": "2026-01-01T00:00:00+08:00", "y": 0.7}]}
        ],
        "bandit_daily_rollup": {
            "total_updates": 3,
            "reason_counts": {
                "episode_close_realized": 2,
                "episode_ingest_estimated": 1
            },
            "threshold_meta": {
                "window_days": 7,
                "sample_size": 7,
                "percentile": 25,
                "raw_percentile": 41.25,
                "min_cap": 30,
                "max_cap": 70,
                "fallback_used": False
            }
        }
    }

    out = tmp_path / "dashboard.html"
    render_dashboard_html(stats, out)

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Memory L4 Dashboard" in content
    assert "Migration Trends" in content
    assert "Performance Facets" in content
    assert "Filter Kind" in content
    assert "Bandit Reason Trends" in content
    assert "episode_close_realized" in content
    assert "bandit_total_updates_7d" in content
    assert "bandit:realized_ratio_7d" in content
    assert "bandit:realized_ratio_alert" in content
    assert "Realized Ratio (%)" in content
    assert "Threshold Meta: P25\\u002f7d sample=7 cap=[30,70]" in content


def test_load_latest_bandit_rollup_collects_7d_reason_series(tmp_path: Path, monkeypatch):
    from scripts.memory_l4 import dashboard_renderer as mod

    bandit_root = tmp_path / "artifacts" / "memory_engine" / "bandit"
    d1 = bandit_root / "2026-05-09"
    d2 = bandit_root / "2026-05-10"
    d1.mkdir(parents=True, exist_ok=True)
    d2.mkdir(parents=True, exist_ok=True)
    (d1 / "summary.json").write_text(
        '{"total_updates":2,"reason_counts":{"episode_close_realized":1,"episode_ingest_estimated":1}}',
        encoding="utf-8",
    )
    (d2 / "summary.json").write_text(
        '{"total_updates":3,"reason_counts":{"episode_close_realized":2,"episode_ingest_estimated":1}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "_ROOT", tmp_path)
    out = mod._load_latest_bandit_rollup()

    assert out["total_updates"] == 3
    assert out["reason_counts"]["episode_close_realized"] == 2
    assert len(out["daily_reason_series"]) == 2
    assert out["daily_reason_series"][0]["date"] == "2026-05-09"


def test_render_dashboard_html_supports_custom_bandit_alert_threshold(tmp_path: Path):
    from scripts.memory_l4.dashboard_renderer import render_dashboard_html

    stats = {
        "points": [],
        "migration_trends": [],
        "bandit_alert_threshold_pct": 55,
        "bandit_daily_rollup": {
            "daily_reason_series": [
                {"date": "2026-05-09", "reason_counts": {"episode_close_realized": 3, "episode_ingest_estimated": 2}, "total_updates": 5}
            ],
            "reason_counts": {"episode_close_realized": 3, "episode_ingest_estimated": 2},
            "total_updates": 5,
        },
    }
    out = tmp_path / "dashboard_custom_threshold.html"
    render_dashboard_html(stats, out)
    content = out.read_text(encoding="utf-8")
    assert "Alert \\u003c55%" in content


def test_render_dashboard_html_uses_bandit_rollup_threshold_by_default(tmp_path: Path):
    from scripts.memory_l4.dashboard_renderer import render_dashboard_html

    stats = {
        "points": [],
        "migration_trends": [],
        "bandit_daily_rollup": {
            "recommended_alert_threshold_pct": 52,
            "daily_reason_series": [
                {"date": "2026-05-09", "reason_counts": {"episode_close_realized": 2, "episode_ingest_estimated": 2}, "total_updates": 4}
            ],
            "reason_counts": {"episode_close_realized": 2, "episode_ingest_estimated": 2},
            "total_updates": 4,
        },
    }
    out = tmp_path / "dashboard_rollup_threshold.html"
    render_dashboard_html(stats, out)
    content = out.read_text(encoding="utf-8")
    assert "Alert \\u003c52%" in content


def test_load_latest_bandit_rollup_includes_latest_ratio(tmp_path: Path, monkeypatch):
    from scripts.memory_l4 import dashboard_renderer as mod

    bandit_root = tmp_path / "artifacts" / "memory_engine" / "bandit"
    d = bandit_root / "2026-05-10"
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(
        json.dumps(
            {
                "total_updates": 4,
                "reason_counts": {"episode_close_realized": 3, "episode_ingest_estimated": 1},
                "recommended_alert_threshold_pct": 52,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_ROOT", tmp_path)
    out = mod._load_latest_bandit_rollup()
    assert out["latest_realized_ratio_pct"] == 75.0
