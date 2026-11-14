# -*- coding: utf-8 -*-
"""S1.0-3 OKX 价格回填测试（全部离线，fetch 注入假数据）。"""

import datetime
import os
import sys
import time

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_SCRIPTS_DIR = os.path.join(_MODULE_ROOT, "scripts")
for _p in (_MODULE_ROOT, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backfill_okx_prices import backfill_anchor, run  # noqa: E402
from l1agg.asset_pool import load  # noqa: E402

_DAY_MS = 86_400_000
_BASE = 1_600_000_000_000  # 2020-09-13 UTC


def _candle(ts_ms, close, volume="1000", confirm="1"):
    return [str(ts_ms), "1", "1", "1", str(close), "10", "10", volume, confirm]


def _make_fetch(total_days, start_ms=_BASE, close_offset=0.0, confirm_last="1"):
    """按日期升序生成 total_days 天；返回 OKX 风格倒序分页。"""
    rows = [_candle(start_ms + i * _DAY_MS, 100 + i + close_offset) for i in range(total_days)]
    if confirm_last == "0" and rows:
        rows[-1][8] = "0"

    def _fetch(inst_id, bar, after_ms):
        pool = list(reversed(rows))  # 最新在前
        if after_ms:
            pool = [r for r in pool if int(r[0]) < int(after_ms)]
        return pool[:100]

    return _fetch


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, source, sub_category, metric_name, value, ts):
        self.calls.append((source, sub_category, metric_name, value, ts))
        return True


@pytest.fixture(scope="module")
def pool():
    return load()


@pytest.fixture()
def btc(pool):
    return pool.resolve("BTC")


@pytest.fixture()
def xau(pool):
    return pool.resolve("XAU")


class TestBackfillSingleAsset:
    def test_pagination_and_writes(self, btc):
        rec = Recorder()
        stats = backfill_anchor(btc, _make_fetch(250), _BASE, rec, sleep_s=0)
        assert stats["pages"] == 3  # 100 + 100 + 50
        assert stats["fetched"] == 250
        assert stats["written"] == 250
        assert stats["gaps"] == 0
        assert stats["first_ts"] == _BASE
        assert stats["last_ts"] == _BASE + 249 * _DAY_MS
        # 收盘价 + 成交量两列
        assert len(rec.calls) == 500
        assert {c[2] for c in rec.calls} == {"close_usd", "volume_usd"}
        assert all(c[0] == "okx" and c[1] == "BTC" for c in rec.calls)

    def test_cutoff_filters_old_rows(self, btc):
        rec = Recorder()
        cutoff = _BASE + 200 * _DAY_MS
        stats = backfill_anchor(btc, _make_fetch(250), cutoff, rec, sleep_s=0)
        # 首页倒序覆盖 day249..day150，最老一条已越界 → 提前终止
        assert stats["pages"] == 1
        assert stats["written"] == 50
        assert stats["skipped_out_of_range"] == 50
        assert min(c[4] for c in rec.calls).date() == datetime.date(2021, 4, 1)

    def test_unconfirmed_bar_skipped(self, btc):
        rec = Recorder()
        stats = backfill_anchor(btc, _make_fetch(10, confirm_last="0"), _BASE, rec, sleep_s=0)
        assert stats["skipped_unconfirmed"] == 1
        assert stats["written"] == 9

    def test_dry_run_does_not_write(self, btc):
        rec = Recorder()
        stats = backfill_anchor(btc, _make_fetch(30), _BASE, rec, dry_run=True, sleep_s=0)
        assert stats["written"] == 30
        assert rec.calls == []

    def test_gap_detection(self, btc):
        rows = [_candle(_BASE + i * _DAY_MS, 100) for i in range(20) if i != 5]

        def _fetch(inst_id, bar, after_ms):
            pool = list(reversed(rows))
            if after_ms:
                pool = [r for r in pool if int(r[0]) < int(after_ms)]
            return pool[:100]

        stats = backfill_anchor(btc, _fetch, _BASE, Recorder(), sleep_s=0)
        assert stats["written"] == 19
        assert stats["gaps"] == 1

    def test_fetch_error_recorded_partial_kept(self, btc):
        good = _make_fetch(150)

        def _fetch(inst_id, bar, after_ms):
            if after_ms:
                raise RuntimeError("network down")
            return good(inst_id, bar, after_ms)

        stats = backfill_anchor(btc, _fetch, _BASE, Recorder(), sleep_s=0)
        assert stats["written"] == 100
        assert stats["errors"]
        assert "network down" in stats["errors"][0]

    def test_storage_key_from_pool(self, xau):
        rec = Recorder()
        backfill_anchor(xau, _make_fetch(5), _BASE, rec, sleep_s=0)
        assert {c[1] for c in rec.calls} == {"XAU"}
        assert all(c[0] == "okx" for c in rec.calls)


class TestRun:
    def _recent(self, days=5):
        start = int(time.time() * 1000) - days * _DAY_MS
        return _make_fetch(days, start_ms=start)

    def test_only_okx_anchors_by_default(self, pool):
        rec = Recorder()
        result = run(pool, rec, fetch=self._recent(5), dry_run=True)
        assert {a["id"] for a in result["assets"]} == {"BTC", "ETH", "SOL", "XAU"}
        assert result["total_written"] == 4 * 5

    def test_only_filter(self, pool):
        result = run(pool, Recorder(), fetch=self._recent(5), dry_run=True, only=["BTC", "eth"])
        assert {a["id"] for a in result["assets"]} == {"BTC", "ETH"}

    def test_ok_flag_false_on_error(self, pool):
        def _boom(inst_id, bar, after_ms):
            raise RuntimeError("boom")

        result = run(pool, Recorder(), fetch=_boom, dry_run=True, only=["BTC"])
        assert result["ok"] is False
        assert result["total_written"] == 0
