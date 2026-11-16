"""A2-2: L2 settle → 台账/案例回写 L0 + 周报（修复率/回归通过率/优化收益）

覆盖:
  - 只有 regression_passed 可 settle；回归失败/缺 run_ids/非法 state 一律拒绝
  - settle 后台账条目状态/历史/四分流/run_ids 正确，且经 56 官方校验器 0 violation
  - 案例回写 L0 案例库（l1_case_store.jsonl，case_type=l2_repair），case=skipped 时不写
  - 重复 settle 幂等（台账与案例都不重复）
  - 周报口径：修复率 = settled/(settled+abandoned)、回归通过率、优化收益 before/after/delta
  - 无样本时指标为 null（不按 0 记）
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent  # 34-前端应用训练系统/
REPO_ROOT = BASE.parent
sys.path.insert(0, str(BASE))

from core.l2_repair_ledger import load_ledger, validate_entry  # noqa: E402
from core.l2_settle import (  # noqa: E402
    SettleError,
    render_weekly_markdown,
    settle_task,
    weekly_report,
)

T = "2026-11-17T10:00:00+00:00"
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
WINDOW_SINCE = "2026-11-16T00:00:00+00:00"
WINDOW_UNTIL = "2026-11-18T00:00:00+00:00"


def _history(state: str) -> list:
    chain = [
        ("reported", "reproduced"),
        ("reproduced", "root_caused"),
        ("root_caused", "fixed"),
        ("fixed", "regression_passed"),
        ("regression_passed", "settled"),
    ]
    out = []
    for idx, (src, dst) in enumerate(chain):
        out.append({"from": src, "to": dst, "at": f"2026-11-17T09:0{idx}:00+00:00", "by": "agent"})
        if dst == state:
            return out
    return out


def _regression(passed: bool = True, ts: str = T) -> dict:
    return {
        "runner": "pytest",
        "cmd": "pytest tests/test_route_signal.py -q",
        "exit_code": 0 if passed else 1,
        "passed": passed,
        "ts": ts,
        "log_uri": "logs/pytest-a22.txt",
    }


def _entry(state: str = "regression_passed", kind: str = "bugfix", **overrides) -> dict:
    data = {
        "schema_version": "1.1",
        "task_id": "fix-20261117-001",
        "kind": kind,
        "trigger": {
            "source": "l1_finding",
            "resolver": "54.discovery_path",
            "ref": "reports/discovery/20261117-0001",
            "resolved_at": T,
        },
        "state": state,
        "history": _history(state),
        "attempts": 0,
        "symptom": "L1 语义路由在空候选集时 margin 恒为 0，导致直答误判",
        "reported": {"repo": "dreambuddy-v2", "base_commit": "a1b2c3d", "env": "py3.12/local"},
        "root_cause": "空候选集未走 early-return，margin 计算被跳过",
        "change_ref": {"type": "commit", "sha": "d4e5f6a1b2c3", "summary": "空集 early-return"},
        "evidence": {
            "repro": {
                "cmd": "pytest tests/test_route_signal.py -k empty",
                "fails_on_base": True,
                "artifact_hash": "sha256:" + "a" * 64,
            },
            "regression": _regression(),
        },
        "metrics": [],
        "created_at": "2026-11-17T09:00:00+00:00",
        "updated_at": "2026-11-17T09:04:00+00:00",
    }
    data.update(overrides)
    return data


def _write_ledger(path: Path, *entries: dict) -> None:
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8"
    )


def _splits(case: str = "done") -> dict:
    return {"case": case, "cognition": "done", "process": "skipped", "doc": "skipped"}


def test_settles_and_writes_case_to_l0(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    case_store = tmp_path / "l1_case_store.jsonl"
    _write_ledger(ledger, _entry())

    settled = settle_task(
        "fix-20261117-001",
        regression=_regression(),
        run_ids=["run-a22-001"],
        splits=_splits(),
        ledger_path=ledger,
        case_store_path=case_store,
        now=NOW,
    )

    assert settled["state"] == "settled"
    assert settled["history"][-1]["from"] == "regression_passed"
    assert settled["history"][-1]["to"] == "settled"
    assert settled["settled"] == _splits()
    assert settled["run_ids"] == ["run-a22-001"]
    validate_entry(settled)

    # 台账是替换而非追加（仍只有 1 行）
    rows = load_ledger(ledger)
    assert len(rows) == 1
    assert rows[0]["state"] == "settled"

    # 案例回写 L0 案例库
    cases = [json.loads(line) for line in case_store.read_text(encoding="utf-8").splitlines()]
    assert len(cases) == 1
    assert cases[0]["case_type"] == "l2_repair"
    assert cases[0]["task_id"] == "fix-20261117-001"
    assert cases[0]["payload"]["root_cause"] == settled["root_cause"]
    assert cases[0]["payload"]["regression"]["passed"] is True


def test_rejects_non_regression_passed_state(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    _write_ledger(ledger, _entry(state="fixed"))

    with pytest.raises(SettleError) as exc:
        settle_task(
            "fix-20261117-001",
            regression=_regression(),
            run_ids=["run-a22-001"],
            ledger_path=ledger,
            case_store_path=tmp_path / "cases.jsonl",
            now=NOW,
        )
    assert "regression_passed" in str(exc.value)
    assert load_ledger(ledger)[0]["state"] == "fixed"


def test_rejects_failed_regression(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    case_store = tmp_path / "l1_case_store.jsonl"
    _write_ledger(ledger, _entry())

    with pytest.raises(SettleError) as exc:
        settle_task(
            "fix-20261117-001",
            regression=_regression(passed=False),
            run_ids=["run-a22-001"],
            ledger_path=ledger,
            case_store_path=case_store,
            now=NOW,
        )
    assert "回归" in str(exc.value)
    assert load_ledger(ledger)[0]["state"] == "regression_passed"
    assert not case_store.exists()


def test_rejects_empty_run_ids(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    _write_ledger(ledger, _entry())

    with pytest.raises(SettleError) as exc:
        settle_task(
            "fix-20261117-001",
            regression=_regression(),
            run_ids=[],
            ledger_path=ledger,
            case_store_path=tmp_path / "cases.jsonl",
            now=NOW,
        )
    assert "run_ids" in str(exc.value)


def test_case_skipped_does_not_write_case_store(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    case_store = tmp_path / "l1_case_store.jsonl"
    _write_ledger(ledger, _entry())

    settled = settle_task(
        "fix-20261117-001",
        regression=_regression(),
        run_ids=["run-a22-001"],
        splits=_splits(case="skipped"),
        ledger_path=ledger,
        case_store_path=case_store,
        now=NOW,
    )
    assert settled["state"] == "settled"
    assert settled["settled"]["case"] == "skipped"
    assert not case_store.exists()


def test_resettle_is_idempotent(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    case_store = tmp_path / "l1_case_store.jsonl"
    _write_ledger(ledger, _entry())
    kwargs = {
        "regression": _regression(),
        "run_ids": ["run-a22-001"],
        "splits": _splits(),
        "ledger_path": ledger,
        "case_store_path": case_store,
        "now": NOW,
    }
    first = settle_task("fix-20261117-001", **kwargs)
    second = settle_task("fix-20261117-001", **kwargs)

    assert first["task_id"] == second["task_id"]
    assert len(load_ledger(ledger)) == 1
    lines = case_store.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_settled_ledger_passes_official_validator(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    _write_ledger(ledger, _entry())
    settle_task(
        "fix-20261117-001",
        regression=_regression(),
        run_ids=["run-a22-001"],
        splits=_splits(),
        ledger_path=ledger,
        case_store_path=tmp_path / "l1_case_store.jsonl",
        now=NOW,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "56-L2架构能力聚合层" / "scripts" / "validate_contracts.py"),
            "--ledger",
            str(ledger),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_weekly_report_metrics():
    settled = _entry()
    settled["history"] = _history("settled")
    settled["state"] = "settled"
    settled["settled"] = _splits()
    settled["run_ids"] = ["run-a22-001"]

    optimization = _entry(kind="optimization", task_id="opt-20261117-001")
    optimization["history"] = _history("settled")
    optimization["state"] = "settled"
    optimization["settled"] = _splits()
    optimization["run_ids"] = ["run-a22-002"]
    optimization["evidence"]["optimization"] = {"gate45": "PASS"}
    optimization["metrics"] = [
        {"name": "reject_rate", "unit": "%", "before": 10.0, "after": 7.5},
    ]

    abandoned = _entry(task_id="fix-20261117-002")
    abandoned["state"] = "abandoned"
    del abandoned["evidence"]["regression"]  # 放弃发生在回归之前，无回归证据
    abandoned["history"] = _history("fixed") + [
        {
            "from": "fixed",
            "to": "abandoned",
            "at": T,
            "by": "agent",
            "reason": "三次重开仍无法复现",
        }
    ]

    failed = _entry(task_id="fix-20261117-003", state="fixed")
    failed["evidence"]["regression"] = _regression(passed=False)

    report = weekly_report(
        [settled, optimization, abandoned, failed], WINDOW_SINCE, WINDOW_UNTIL, now=NOW
    )

    assert report["counts"]["settled"] == 2
    assert report["counts"]["abandoned"] == 1
    assert report["fix_rate"]["numerator"] == 2
    assert report["fix_rate"]["denominator"] == 3
    assert report["fix_rate"]["value"] == pytest.approx(2 / 3, rel=1e-3)

    assert report["regression_pass_rate"]["numerator"] == 2
    assert report["regression_pass_rate"]["denominator"] == 3
    assert report["regression_pass_rate"]["value"] == pytest.approx(2 / 3, rel=1e-3)

    assert len(report["optimizations"]) == 1
    metric = report["optimizations"][0]["metrics"][0]
    assert metric["before"] == 10.0
    assert metric["after"] == 7.5
    assert metric["delta"] == pytest.approx(-2.5)
    assert metric["delta_pct"] == pytest.approx(-25.0)


def test_weekly_report_empty_samples_are_null():
    report = weekly_report([], WINDOW_SINCE, WINDOW_UNTIL, now=NOW)

    assert report["fix_rate"]["value"] is None
    assert report["fix_rate"]["denominator"] == 0
    assert report["regression_pass_rate"]["value"] is None
    assert report["optimizations"] == []
    assert any("样本不足" in note for note in report["notes"])


def test_weekly_markdown_marks_missing_samples():
    markdown = render_weekly_markdown(weekly_report([], WINDOW_SINCE, WINDOW_UNTIL, now=NOW))

    assert "L2 开发端周报" in markdown
    assert "样本不足" in markdown
    assert "修复率" in markdown
    assert "回归通过率" in markdown
    assert "优化收益" in markdown
