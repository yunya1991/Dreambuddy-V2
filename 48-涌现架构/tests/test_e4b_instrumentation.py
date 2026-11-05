"""E4b 埋点测试（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E4b）。

三个埋点：
  - readout_rate：写→召回→改变行动 全链比例。recall 事件落盘 events/memory_readout/*.jsonl，
    与后续动作 join；仅有 recall 无动作不计。
  - cascade_sigma：跨模块事件级联，复用 E1 bus/resp shadow 日志；级联尺寸分布 + 分支系数 σ。
  - e4_self_correction_rate：反思→修复时序 join（suggestions.md → 后续 git_commit/file_change）。

数据源现实（2026-11-05）：
  - readout：.cognitive/sessions 883 个 session 有 recalled_memory_ids、64062 条 action，
    但生产交易链 recall 只有文本日志（polling_trader._inject_cognitive_recall 的 self._log）
    → trading domain 无结构化数据，如实 no_data，不伪造。
  - cascade：E1 shadow 当前仅 1 个点火事件/3 条响应 → 不足 20，如实 insufficient_data。
  - reflection：881 个 suggestions.md 可解析生成时间，可做时序 join 代理（非因果）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_METRICS = Path(__file__).resolve().parents[1] / "metrics"
if str(_METRICS) not in sys.path:
    sys.path.insert(0, str(_METRICS))

import e4b_cascade as ec  # noqa: E402
import e4b_readout as er  # noqa: E402
import e4b_reflection as ef  # noqa: E402

# ---------------- readout ----------------


def test_record_recall_appends_and_is_idempotent(tmp_path):
    log = tmp_path / "recall_events.jsonl"
    ev = er.record_recall(
        trace_id="readout-S1",
        session_id="S1",
        memory_ids=["VM-1", "VM-2"],
        ts="2026-11-05T10:00:00+00:00",
        query="q",
        path=log,
    )
    assert ev["event_id"].startswith("R-")
    assert ev["n_memory"] == 2
    assert log.exists()
    # 重复写入同一 trace 不重复追加
    er.record_recall(
        trace_id="readout-S1",
        session_id="S1",
        memory_ids=["VM-1", "VM-2"],
        ts="2026-11-05T10:00:00+00:00",
        path=log,
    )
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1


def test_record_recall_skips_empty_memory_ids(tmp_path):
    log = tmp_path / "r.jsonl"
    assert (
        er.record_recall(
            trace_id="readout-S9",
            session_id="S9",
            memory_ids=[],
            ts="2026-11-05T10:00:00+00:00",
            path=log,
        )
        is None
    )
    assert not log.exists() or not log.read_text(encoding="utf-8").strip()


def test_readout_rate_requires_action_after_recall(tmp_path):
    log = tmp_path / "r.jsonl"
    er.record_recall(
        trace_id="readout-A",
        session_id="A",
        memory_ids=["VM-1"],
        ts="2026-11-05T10:00:00+00:00",
        path=log,
    )
    er.record_recall(
        trace_id="readout-B",
        session_id="B",
        memory_ids=["VM-2"],
        ts="2026-11-05T10:00:00+00:00",
        path=log,
    )
    # A 有动作（改变决策），B 无
    er.record_action(
        trace_id="readout-A",
        session_id="A",
        ts="2026-11-05T10:05:00+00:00",
        action_type="git_commit",
        changed_decision=True,
        path=log,
    )
    res = er.compute_readout_rate(path=log, min_recalls=1)
    assert res["status"] == "ok"
    assert res["n_recalls"] == 2
    assert res["n_readout"] == 1
    assert res["value"] == pytest.approx(0.5)


def test_readout_action_before_recall_not_counted(tmp_path):
    log = tmp_path / "r.jsonl"
    er.record_recall(
        trace_id="readout-C",
        session_id="C",
        memory_ids=["VM-3"],
        ts="2026-11-05T10:10:00+00:00",
        path=log,
    )
    er.record_action(
        trace_id="readout-C",
        session_id="C",
        ts="2026-11-05T10:00:00+00:00",  # 早于召回
        action_type="file_change",
        changed_decision=True,
        path=log,
    )
    res = er.compute_readout_rate(path=log, min_recalls=1)
    assert res["n_readout"] == 0
    assert res["value"] == 0.0


def test_readout_no_data_when_no_recalls(tmp_path):
    res = er.compute_readout_rate(path=tmp_path / "missing.jsonl")
    assert res["status"] == "no_data"
    assert res["value"] is None


def _write_session(tmp_path: Path, sid: str, start: float, mem_ids, actions) -> None:
    d = tmp_path / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(
        json.dumps({"id": sid, "start_time": start, "recalled_memory_ids": mem_ids}),
        encoding="utf-8",
    )
    (d / "action_chain.jsonl").write_text(
        "\n".join(json.dumps(a) for a in actions) + "\n", encoding="utf-8"
    )


def test_backfill_from_sessions_is_idempotent(tmp_path):
    sess_root = tmp_path / "sessions"
    _write_session(
        sess_root,
        "S1",
        1000.0,
        ["VM-1", "VM-2"],
        [
            {"timestamp": 1010.0, "session_id": "S1", "action_type": "file_change", "detail": "x"},
            {
                "timestamp": 1020.0,
                "session_id": "S1",
                "action_type": "task_type_evolved",
                "detail": "y",
            },
        ],
    )
    _write_session(sess_root, "S2", 1000.0, [], [])
    log = tmp_path / "readout.jsonl"
    out1 = er.backfill_from_sessions(sessions_root=sess_root, path=log)
    assert out1["n_recalls"] == 1
    assert out1["n_actions"] == 1  # task_type_evolved 不算实际动作
    rate1 = er.compute_readout_rate(path=log, min_recalls=1)
    assert rate1["value"] == pytest.approx(1.0)
    # 二次回填不重复
    out2 = er.backfill_from_sessions(sessions_root=sess_root, path=log)
    assert out2["n_skipped"] >= 2
    assert len([ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]) == 2


# ---------------- cascade ----------------


def _write_bus(tmp_path: Path, n_events: int, n_resp: int, n_action: int) -> tuple[Path, Path]:
    bus = tmp_path / "bus.jsonl"
    resp = tmp_path / "resp.jsonl"
    blines, rlines = [], []
    for i in range(n_events):
        eid = f"EB-{i}"
        blines.append(
            json.dumps(
                {
                    "event_id": eid,
                    "trace_id": f"t{i}",
                    "ts": f"2026-11-05T10:00:0{i % 10}+00:00",
                    "source_domain": "data",
                    "metric": "psi",
                    "z_score": 4.0,
                    "ignited": True,
                }
            )
        )
        for j in range(n_resp):
            rlines.append(
                json.dumps(
                    {
                        "event_id": eid,
                        "trace_id": f"t{i}",
                        "subscriber": f"sub{j}",
                        "consumed": True,
                        "action": j < n_action,
                    }
                )
            )
    bus.write_text("\n".join(blines) + "\n", encoding="utf-8")
    resp.write_text("\n".join(rlines) + "\n", encoding="utf-8")
    return bus, resp


def test_cascade_sigma_insufficient_on_thin_data(tmp_path):
    bus, resp = _write_bus(tmp_path, n_events=3, n_resp=2, n_action=1)
    res = ec.compute_cascade(bus_paths=[bus], resp_paths=[resp], min_events=20)
    assert res["status"] == "insufficient_data"
    assert res["value"]["n_events"] == 3
    assert res["value"]["sigma"] == pytest.approx(2.0)  # 2 consumed / 1 ignited
    assert res["value"]["total_actions"] == 3


def test_cascade_ok_with_enough_events(tmp_path):
    bus, resp = _write_bus(tmp_path, n_events=25, n_resp=2, n_action=1)
    res = ec.compute_cascade(bus_paths=[bus], resp_paths=[resp], min_events=20)
    assert res["status"] == "ok"
    assert res["value"]["n_events"] == 25
    assert res["value"]["sigma"] == pytest.approx(2.0)
    assert res["value"]["cascade_sizes"]["mean"] == pytest.approx(2.0)
    assert res["value"]["near_sigma_1"] is False  # σ=2 不在临界带
    assert "powerlaw_slope" in res["value"]


def test_cascade_no_data_when_missing(tmp_path):
    res = ec.compute_cascade(bus_paths=[tmp_path / "nope.jsonl"], resp_paths=[])
    assert res["status"] == "no_data"


# ---------------- reflection ----------------


def _write_suggestion(tmp_path: Path, sid: str, gen_time: str, actions) -> None:
    d = tmp_path / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "suggestions.md").write_text(
        f"# 💡 认知系统建议\n# 生成时间: {gen_time}\n\n## 🎯 流程建议\n### 1. [a] x\n### 2. [b] y\n",
        encoding="utf-8",
    )
    (d / "action_chain.jsonl").write_text(
        "\n".join(json.dumps(a) for a in actions) + "\n", encoding="utf-8"
    )


def test_reflection_join_counts_fix_after_reflection(tmp_path):
    _write_suggestion(
        tmp_path,
        "S1",
        "2026-11-05 10:00:00",
        [
            {"timestamp": 1793892000.0, "action_type": "git_commit", "detail": "fix"},
        ],
    )
    _write_suggestion(
        tmp_path,
        "S2",
        "2026-11-05 10:00:00",
        [{"timestamp": 1793840000.0, "action_type": "file_change"}],
    )
    res = ef.compute_self_correction_rate(sessions_root=tmp_path, min_reflections=1)
    assert res["status"] == "ok"
    assert res["n_reflections"] == 2
    assert res["n_fixed"] == 1
    assert res["value"] == pytest.approx(0.5)
    assert res["note"].startswith("时序 join 代理")


def test_reflection_no_data_when_missing(tmp_path):
    res = ef.compute_self_correction_rate(sessions_root=tmp_path / "nope")
    assert res["status"] == "no_data"
    assert res["value"] is None


def test_reflection_insufficient_below_min(tmp_path):
    _write_suggestion(tmp_path, "S1", "2026-11-05 10:00:00", [])
    res = ef.compute_self_correction_rate(sessions_root=tmp_path, min_reflections=10)
    assert res["status"] == "insufficient_data"


# ---------------- metrics 接入 ----------------


def test_emergence_metrics_exposes_e4b_fields():
    import emergence_metrics as em

    snap = em.collect()
    for key in ("e4_readout_rate", "e4_cascade_sigma", "e4_self_correction_rate"):
        assert key in snap
        assert "value" in snap[key] and "status" in snap[key]
