"""SPEC-54 R6：60s 结果缓存 + 按日聚合 / 分档 P95 观测验收。"""

from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_L1 = os.path.join(_REPO, "54-L1架构能力聚合层")
_SCRIPTS = os.path.join(_REPO, "3.1-FRONTEND", "scripts")
for _p in (_L1, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capability_resolve as cr  # noqa: E402
import resolve_metrics as rm  # noqa: E402

_DB_READY = os.path.exists(cr.DB_PATH)
_needs_db = pytest.mark.skipif(not _DB_READY, reason="dreambuddy_core.db 不存在")

_NOW = 1_760_000_000  # 2025-10-09T08:53:20Z，固定时间便于按日聚合断言


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VISUAL_METRICS_DB", str(tmp_path / "visual_metrics.db"))
    monkeypatch.setattr(cr, "_CACHE_TTL_S", 60.0)
    cr.clear_cache()
    yield
    cr.clear_cache()


def _seed(rows):
    for capability_id, code, elapsed_ms, tier, cache_hit, offset in rows:
        rm.record(
            capability_id=capability_id,
            code=code,
            elapsed_ms=elapsed_ms,
            n=10,
            tier=tier,
            cache_hit=cache_hit,
            now=_NOW + offset,
        )


def test_daily_aggregation_and_success_rate():
    _seed(
        [
            ("D-E10", "ok", 40, "single", False, 0),
            ("D-E10", "ok", 60, "single", False, 60),
            ("D-K02", "product_missing", 30, "single", False, 120),
        ]
    )
    report = rm.daily_report(days=1, now=_NOW + 3600)
    assert report["ok"] is True
    assert report["total"] == 3
    assert report["ok_count"] == 2
    assert report["success_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert len(report["daily"]) == 1
    day = report["daily"][0]
    assert day["codes"] == {"ok": 2, "product_missing": 1}
    assert day["tiers"]["single"]["count"] == 3


def test_p95_nearest_rank_and_tier_split():
    rows = [(f"D-{i:03d}", "ok", i * 10, "single", False, i) for i in range(1, 21)]
    rows.append(("D-J22", "ok", 900, "multi", False, 30))
    rows.append(("D-J22", "ok", 400, "multi", True, 40))
    _seed(rows)
    report = rm.daily_report(days=1, now=_NOW + 3600)
    # 20 个单资产样本：10..200，nearest-rank P95 = 190、P50 = 100
    assert report["tiers"]["single"]["p95_ms"] == 190
    assert report["tiers"]["single"]["p50_ms"] == 100
    # 缓存命中单独成档，不与多资产混算
    assert report["tiers"]["cache"]["count"] == 1
    assert report["tiers"]["cache"]["p95_ms"] == 400
    assert report["tiers"]["multi"]["p95_ms"] == 900


def test_tier_targets_and_breaches():
    _seed(
        [
            ("D-J22", "ok", 9000, "multi", False, 0),
            ("D-E10", "ok", 500, "single", False, 1),
        ]
    )
    report = rm.daily_report(days=1, now=_NOW + 3600)
    assert report["targets"] == {"single": 3000, "multi": 8000, "cache": 3000}
    assert [item["tier"] for item in report["breaches"]] == ["multi"]
    assert report["breaches"][0]["p95_ms"] == 9000


def test_failure_list_and_recent_alert():
    _seed(
        [
            ("D-K02", "product_missing", 20, "single", False, 0),
            ("D-K02", "product_missing", 21, "single", False, 10),
            ("D-K02", "product_missing", 22, "single", False, 20),
            ("D-K02", "product_missing", 23, "single", False, 25),
            ("D-K02", "product_missing", 24, "single", False, 26),
            ("D-E19", "product_missing", 25, "multi", False, 30),
            ("D-E10", "ok", 26, "single", False, 40),
            ("D-E10", "ok", 27, "single", False, 50),
        ]
    )
    report = rm.daily_report(days=1, now=_NOW + 100)
    assert report["failures"][0] == {
        "capability_id": "D-K02",
        "code": "product_missing",
        "count": 5,
    }
    alerts = {item["capability_id"]: item for item in report["alerts"]}
    assert alerts["D-K02"]["count"] == 5
    assert alerts["D-K02"]["failure_rate"] == 1.0
    assert "D-E10" not in alerts


def test_report_is_fail_open_when_db_unusable(tmp_path, monkeypatch):
    # 指向目录（而非文件）→ SQLite 无法打开；报表应降级而不是抛错
    monkeypatch.setenv("VISUAL_METRICS_DB", str(tmp_path))
    report = rm.daily_report(days=1, now=_NOW)
    assert report["ok"] is False
    assert report["code"] == "error"


@_needs_db
def test_result_cache_hit_and_ttl():
    first = cr.resolve("D-E10", {"symbol": "BTC", "days": 120})
    assert first["code"] == "ok"
    assert first["meta"]["cache"] == "miss"

    second = cr.resolve("D-E10", {"symbol": "BTC", "days": 120})
    assert second["meta"]["cache"] == "hit"
    assert second["quality"]["n"] == first["quality"]["n"]

    cr._CACHE_TTL_S = 0.0  # 过期后必须重跑
    third = cr.resolve("D-E10", {"symbol": "BTC", "days": 120})
    assert third["meta"]["cache"] == "miss"


@_needs_db
def test_result_cache_key_is_payload_sensitive():
    base = cr.resolve("D-E10", {"symbol": "BTC", "days": 120})
    assert base["code"] == "ok"
    other = cr.resolve("D-E10", {"symbol": "ETH", "days": 120})
    assert other["meta"]["cache"] == "miss"


def test_failed_resolution_is_not_cached(tmp_path, monkeypatch):
    # SPEC-54c：E19 会回退读取主览图落盘产物；此处固定指向缺失路径以验证失败不缓存
    monkeypatch.setattr(cr, "_lights_artifact_path", lambda: str(tmp_path / "missing.json"))
    first = cr.resolve("D-E19", {})
    second = cr.resolve("D-E19", {})
    assert first["code"] == "product_missing"
    assert second["code"] == "product_missing"
    assert second["meta"]["cache"] == "miss"


@_needs_db
def test_metrics_recorded_by_resolve():
    cr.resolve("D-E10", {"symbol": "BTC", "days": 60})
    report = rm.daily_report(days=1)
    assert report["total"] >= 1
    assert report["tiers"]["single"]["count"] >= 1
