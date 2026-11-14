"""breadth.DeFi TVL 取源契约：只认 chains_summary（全链汇总），禁止 all_protocols。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dal_snapshot_provider import DalSnapshotProvider  # noqa: E402


class _StubRepo:
    def __init__(self, latest: dict):
        self.latest = latest

    def query_latest_metric(self, sub_category, metric_name):
        value = self.latest.get((sub_category, metric_name))
        return None if value is None else ("stub", value)

    def query_metric_by_time(self, sub_category, metric_name, start, end):
        return []


def _provider(latest: dict) -> DalSnapshotProvider:
    return DalSnapshotProvider(repo=_StubRepo(latest))


def test_breadth_uses_chains_summary_not_double_counted_protocols():
    out = _provider(
        {
            ("overview_market", "btc_dominance_pct"): 55.0,
            ("overview_market", "global_change24_pct"): 1.2,
            ("all_protocols", "total_tvl_bln"): 523.26,
            ("chains_summary", "total_tvl_bln"): 73.88,
        }
    ).collect_breadth()
    assert out["metrics"]["core"]["defi_tvl_bln"] == 73.88


def test_breadth_falls_back_to_usd_metric_and_never_all_protocols():
    out = _provider(
        {
            ("overview_market", "btc_dominance_pct"): 55.0,
            ("overview_market", "global_change24_pct"): 1.2,
            ("all_protocols", "total_tvl_bln"): 523.26,
            ("chains_summary", "total_tvl"): 73.88e9,
        }
    ).collect_breadth()
    assert out["metrics"]["core"]["defi_tvl_bln"] == 73.88
