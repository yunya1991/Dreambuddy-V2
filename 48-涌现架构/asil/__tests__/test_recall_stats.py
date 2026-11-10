# ruff: noqa: E402  (sys.path 必须先于 asil 导入)
"""recall stats 接入 distill_effectiveness 的 pytest。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from asil.metrics_collector import MetricsCollector
from asil.recall_stats import RecallStatsProvider


def _write_events(path: Path) -> None:
    rows = [
        # memory_readout schema：命中
        {"event_id": "a", "kind": "recall", "memory_ids": ["m1"], "ts": "2026-11-01T00:00:00Z"},
        # memory_readout schema：未命中（01:00 正好是蒸馏点）
        {
            "event_id": "b",
            "kind": "recall",
            "memory_ids": [],
            "n_memory": 0,
            "ts": "2026-11-01T01:00:00Z",
        },
        # action 事件必须被忽略
        {"event_id": "c", "kind": "action", "memory_ids": ["m2"], "ts": "2026-11-01T02:00:00Z"},
        # observer 旧 schema（数字 ts）：命中（quality B）
        {
            "session_id": "s",
            "returned_ids": ["x"],
            "returned_scores": [0.5],
            "returned_qualities": ["B"],
            "ts": 1790000000.0,
        },
        # observer 旧 schema：有返回但质量 C → 不算命中
        {
            "session_id": "s2",
            "returned_ids": ["y"],
            "returned_scores": [0.2],
            "returned_qualities": ["C"],
            "ts": 1790003600.0,
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))


class TestParsing:
    def test_parse_ts_numeric_and_iso(self):
        assert RecallStatsProvider._parse_ts(1790000000.0) == 1790000000.0
        assert RecallStatsProvider._parse_ts("1790000000") == 1790000000.0
        assert RecallStatsProvider._parse_ts("2026-11-01T00:00:00Z") is not None
        assert RecallStatsProvider._parse_ts("2026-11-01T08:00:00+08:00") is not None
        assert RecallStatsProvider._parse_ts(None) is None
        assert RecallStatsProvider._parse_ts("not-a-time") is None

    def test_normalize_skips_action_and_supports_both_schemas(self, tmp_path):
        p = tmp_path / "recall_events.jsonl"
        _write_events(p)
        rows = RecallStatsProvider(events_path=p).load()
        assert len(rows) == 4  # action 被跳过
        assert sum(1 for r in rows if r["hit"]) == 2
        # quality 口径：C 级有返回但不算命中
        assert [r["hit"] for r in rows if r["hit_basis"] == "quality"] == [True, False]
        assert all(r["hit_basis"] == "count" for r in rows if r["hit_basis"] == "count")

    def test_missing_file_yields_empty(self, tmp_path):
        provider = RecallStatsProvider(events_path=tmp_path / "nope.jsonl")
        assert provider.load() == []
        assert provider.stats().n_recalls == 0


class TestStats:
    def test_window_and_hit_rate(self, tmp_path):
        p = tmp_path / "recall_events.jsonl"
        _write_events(p)
        provider = RecallStatsProvider(events_path=p)
        total = provider.stats()
        assert total.n_recalls == 4
        assert total.n_hits == 2
        assert total.hit_rate == 0.5
        assert total.avg_returned == 0.75

    def test_summary_reports_hit_basis(self, tmp_path):
        p = tmp_path / "recall_events.jsonl"
        _write_events(p)
        summary = RecallStatsProvider(events_path=p).summary()
        assert summary["hit_basis"] == {"count": 2, "quality": 2}

    def test_effectiveness_before_after(self, tmp_path):
        p = tmp_path / "recall_events.jsonl"
        _write_events(p)
        provider = RecallStatsProvider(events_path=p, window_seconds=3600)
        distill_ts = RecallStatsProvider._parse_ts("2026-11-01T01:00:00Z")
        eff = provider.effectiveness(distill_ts)
        assert eff["sufficient"] is True
        assert eff["before"]["hit_rate"] == 1.0  # 00:00 命中
        assert eff["after"]["hit_rate"] == 0.0  # 01:00 未命中
        assert eff["delta"] == -1.0

    def test_effectiveness_insufficient(self, tmp_path):
        p = tmp_path / "recall_events.jsonl"
        _write_events(p)
        provider = RecallStatsProvider(events_path=p, window_seconds=3600)
        eff = provider.effectiveness(RecallStatsProvider._parse_ts("2030-01-01T00:00:00Z"))
        assert eff["sufficient"] is False
        assert eff["delta"] == 0.0


class _StubProvider:
    def __init__(self, delta: float):
        self.delta = delta

    def effectiveness(self, distill_ts, window=None):
        return {"delta": self.delta, "sufficient": True, "distill_ts": distill_ts}

    def summary(self):
        return {"source": "stub", "n_recalls": 10, "hit_rate": 0.5}


class TestMetricsIntegration:
    def test_distill_effectiveness_uses_provider(self):
        m = MetricsCollector(recall_provider=_StubProvider(0.1))
        assert m.distill_effectiveness == 0.0  # 无蒸馏记录
        m.record_distill(ts=1790000000.0)
        assert m.distill_effectiveness == 0.1
        assert m.distill_effectiveness_detail["delta"] == 0.1

    def test_multiple_distills_averaged(self):
        m = MetricsCollector(recall_provider=_StubProvider(0.2))
        m.record_distill(ts=1.0)
        m.record_distill(ts=2.0)
        assert abs(m.distill_effectiveness - 0.2) < 1e-9
        assert m.distill_count == 2

    def test_snapshot_contains_recall_stats(self):
        m = MetricsCollector(recall_provider=_StubProvider(0.05))
        m.record_distill(ts=1790000000.0)
        snap = m.snapshot()
        assert snap["distill_effectiveness"] == 0.05
        assert snap["recall_stats"]["source"] == "stub"
        assert "distill_effectiveness_detail" in snap

    def test_snapshot_fail_open_when_provider_broken(self):
        class Broken:
            def effectiveness(self, ts, window=None):
                raise RuntimeError("db down")

            def summary(self):
                raise RuntimeError("db down")

        m = MetricsCollector(recall_provider=Broken())
        m.record_distill(ts=1790000000.0)
        snap = m.snapshot()
        assert snap["distill_effectiveness"] == 0.0
        assert snap["recall_stats"]["n_recalls"] == 0


class TestRealDataset:
    def test_default_source_smoke(self):
        provider = RecallStatsProvider()
        summary = provider.summary()
        assert summary["source"] is not None
        assert summary["n_recalls"] > 100  # 真实数据集中 kind=recall 约 885 条
        assert 0.0 <= summary["hit_rate"] <= 1.0
