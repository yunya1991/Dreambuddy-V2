"""RED 测试 — PumpDumpReversalCaseLibrary (拉高出货做空案例库).

阶段2 新增 (纯新增):
  - 1-ARCHITECTURE/dreamos/evolution/pump_dump_reversal_case_library.py
      — 复用 WashoutCase + 独立案例库 + KNN

硬约束:
  - actual_label: reversal_short_success / reversal_short_fail
  - 案例库 <30 降级规则化
  - FAIL-OPEN: knn_search 异常 → 空列表
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"
for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreamos.evolution.pump_dump_reversal_case_library import (  # noqa: E402
    PumpDumpReversalCaseLibrary,
)
from dreamos.evolution.washout_case_library import WashoutCase  # noqa: E402


def _make_case(case_id="c1", label="reversal_short_success", pnl=0.05):
    return WashoutCase(
        case_id=case_id, coin="BTC",
        entry_time="2026-01-01T00:00:00+00:00",
        exit_time="2026-01-02T00:00:00+00:00",
        features_snapshot={"F1": 1.0}, actual_label=label,
        pnl_pct=pnl, reward=WashoutCase.compute_reward(pnl),
        timestamp="2026-01-02T00:00:00+00:00",
    )


class TestCaseLibrary:
    def test_add_and_get(self):
        lib = PumpDumpReversalCaseLibrary()
        lib.add(_make_case())
        assert len(lib) == 1
        assert lib.get("c1") is not None

    def test_knn_search(self):
        lib = PumpDumpReversalCaseLibrary()
        for i in range(5):
            lib.add(_make_case(case_id=f"c{i}", pnl=0.01 * i))
        results = lib.knn_search({"F1": 1.0}, k=3)
        assert len(results) == 3

    def test_label_short_success(self):
        lib = PumpDumpReversalCaseLibrary()
        lib.add(_make_case(label="reversal_short_success"))
        assert lib.get("c1").actual_label == "reversal_short_success"

    def test_label_short_fail(self):
        lib = PumpDumpReversalCaseLibrary()
        lib.add(_make_case(label="reversal_short_fail", pnl=-0.05))
        assert lib.get("c1").actual_label == "reversal_short_fail"

    def test_empty_knn(self):
        lib = PumpDumpReversalCaseLibrary()
        assert lib.knn_search({"F1": 1.0}, k=5) == []

    def test_fail_open_exception(self):
        lib = PumpDumpReversalCaseLibrary()
        lib.add(_make_case())
        assert lib.knn_search(None, k=5) == []  # type: ignore

    def test_min_cases_threshold(self):
        lib = PumpDumpReversalCaseLibrary()
        for i in range(10):
            lib.add(_make_case(case_id=f"c{i}"))
        assert len(lib) < 30
