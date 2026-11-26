"""main-nn chain_event 埋点单测（15 TD §14）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "42-神经网络交易协调层"))

from chain_events import SOURCE, emit_stage, new_trace_id  # noqa: E402


def test_emit_writes_source_trace_and_data(tmp_path: Path) -> None:
    trace = new_trace_id("BTC/USDT")
    emit_stage(
        "M6",
        "bus_reader.load_evidences",
        "BTC/USDT",
        "pass",
        trace_id=trace,
        decision_id="50-nn|abc",
        mode="shadow",
        data={"evidence_count": 3},
        runtime=tmp_path,
    )
    files = list(tmp_path.glob("chain_events-*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert rec["schema"] == "chain_event.v1"
    assert rec["source"] == SOURCE == "main-nn"
    assert rec["stage"] == "M6"
    assert rec["trace_id"] == trace
    assert rec["decision_id"] == "50-nn|abc"
    assert rec["mode"] == "shadow"
    assert rec["data"]["evidence_count"] == 3


def test_emit_fail_open_on_invalid_runtime() -> None:
    # 观测失败绝不影响调用方：非法路径只吞异常，不抛出
    emit_stage("M11", "decision.make_decision", "BTC", "pass", runtime="\0bad")
