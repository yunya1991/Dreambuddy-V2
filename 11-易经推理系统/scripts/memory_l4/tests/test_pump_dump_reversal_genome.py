"""RED 测试 — PumpDumpReversalGenome (拉高出货做空基因组编排层).

阶段2 新增 (纯新增):
  - 1-ARCHITECTURE/dreamos/evolution/pump_dump_reversal_genome.py

硬约束:
  - HC-P1: 信号走 evolution probe 仓路径 (不增加总风险敞口)
  - HC-P2: WashoutDetector label=WEAKNESS + conf≥0.80 才进入结束信号判定
  - HC-P5: ENABLE_PUMP_DUMP_REVERSAL_GENOME=False 时降级
  - HC-P6: 信号需 ≥ PROBE_THRESHOLD=0.55
  - confidence = weakness_verdict.confidence*0.6 + ending_signal.confidence*0.4
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"
for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreamos.evolution.pump_dump_reversal_genome import (  # noqa: E402
    PumpDumpReversalGenome,
    PumpDumpReversalSignal,
)
from dreamos.evolution.pump_dump_ending_detector import (  # noqa: E402
    PumpDumpEndingSignal,
    PumpDumpEndingDetector,
)
from dreamos.evolution.pump_dump_reversal_case_library import (  # noqa: E402
    PumpDumpReversalCaseLibrary,
)
from dreamos.evolution.washout_case_library import WashoutCase  # noqa: E402
from dreamos.evolution.washout_bayesian_updater import BayesianUpdater  # noqa: E402
from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector,
    WashoutLabel,
    WashoutVerdict,
)


def _mock_detector(label=WashoutLabel.WEAKNESS, conf=0.85):
    det = MagicMock(spec=WashoutDetector)
    det.run.return_value = WashoutVerdict(
        label=label, confidence=conf, trigger_activated=True,
        feature_snapshot={"F1": 1.0}, reason=f"mock_{label.value}",
        timestamp="2026-01-01T00:00:00+00:00")
    return det


def _stub_ending(activated=True, conf=0.75):
    det = MagicMock(spec=PumpDumpEndingDetector)
    det.check.return_value = PumpDumpEndingSignal(
        activated=activated, confidence=conf, reason="stub",
        timestamp="2026-01-01T00:00:00+00:00")
    return det


class TestSignalDataclass:
    def test_fields(self):
        sig = PumpDumpReversalSignal(direction="SHORT", confidence=0.7,
                                     washout_verdict=WashoutVerdict.unknown(),
                                     ending_signal=PumpDumpEndingSignal.not_activated("t"),
                                     reason="r", timestamp="ts")
        assert sig.direction == "SHORT"


class TestDetectSignal:
    def test_weakness_high_conf_short(self):
        det = _mock_detector(WashoutLabel.WEAKNESS, 0.85)
        ending = _stub_ending(True, 0.75)
        g = PumpDumpReversalGenome(det, ending, PumpDumpReversalCaseLibrary(),
                                   BayesianUpdater(), enable=True)
        sig = g.detect_signal("BTC", pd.DataFrame(), {})
        assert sig.direction == "SHORT"
        ending.check.assert_called_once()

    def test_washout_skips(self):
        det = _mock_detector(WashoutLabel.WASHOUT, 0.90)
        ending = _stub_ending()
        g = PumpDumpReversalGenome(det, ending, PumpDumpReversalCaseLibrary(),
                                   BayesianUpdater(), enable=True)
        sig = g.detect_signal("BTC", pd.DataFrame(), {})
        assert sig.direction == "NONE"
        ending.check.assert_not_called()

    def test_low_confidence_skips(self):
        det = _mock_detector(WashoutLabel.WEAKNESS, 0.70)
        ending = _stub_ending()
        g = PumpDumpReversalGenome(det, ending, PumpDumpReversalCaseLibrary(),
                                   BayesianUpdater(), enable=True)
        sig = g.detect_signal("BTC", pd.DataFrame(), {})
        assert sig.direction == "NONE"

    def test_confidence_calc(self):
        det = _mock_detector(WashoutLabel.WEAKNESS, 0.90)
        ending = _stub_ending(True, 0.80)
        g = PumpDumpReversalGenome(det, ending, PumpDumpReversalCaseLibrary(),
                                   BayesianUpdater(), enable=True)
        sig = g.detect_signal("BTC", pd.DataFrame(), {})
        expected = 0.90 * 0.6 + 0.80 * 0.4
        assert sig.confidence == pytest.approx(expected, abs=1e-6)

    def test_enable_false(self):
        det = _mock_detector(WashoutLabel.WEAKNESS, 0.90)
        ending = _stub_ending()
        g = PumpDumpReversalGenome(det, ending, PumpDumpReversalCaseLibrary(),
                                   BayesianUpdater(), enable=False)
        sig = g.detect_signal("BTC", pd.DataFrame(), {})
        assert sig.direction == "NONE"

    def test_fail_open(self):
        det = MagicMock(spec=WashoutDetector)
        det.run.side_effect = RuntimeError("boom")
        ending = _stub_ending()
        g = PumpDumpReversalGenome(det, ending, PumpDumpReversalCaseLibrary(),
                                   BayesianUpdater(), enable=True)
        sig = g.detect_signal("BTC", pd.DataFrame(), {})
        assert sig.direction == "NONE"


class TestRecordCase:
    def test_record(self):
        lib = PumpDumpReversalCaseLibrary()
        det = _mock_detector()
        ending = _stub_ending()
        g = PumpDumpReversalGenome(det, ending, lib, BayesianUpdater(), enable=True)
        g.record_case(_make_case())
        assert len(lib) == 1


class TestEvolve:
    def test_evolve_with_sandbox(self):
        fn = MagicMock(return_value=True)
        g = PumpDumpReversalGenome(_mock_detector(), _stub_ending(),
                                   PumpDumpReversalCaseLibrary(),
                                   BayesianUpdater(), enable=True,
                                   sandbox_validate_fn=fn)
        r = g.evolve({"scenario_id": "t"})
        assert r["accepted"] is True

    def test_evolve_no_sandbox(self):
        g = PumpDumpReversalGenome(_mock_detector(), _stub_ending(),
                                   PumpDumpReversalCaseLibrary(),
                                   BayesianUpdater(), enable=True,
                                   sandbox_validate_fn=None)
        r = g.evolve()
        assert r["accepted"] is False


def _make_case():
    return WashoutCase(case_id="t1", coin="BTC",
                       entry_time="2026-01-01T00:00:00+00:00",
                       exit_time="2026-01-02T00:00:00+00:00",
                       features_snapshot={"F1": 1.0},
                       actual_label="reversal_short_success",
                       pnl_pct=0.05, reward=WashoutCase.compute_reward(0.05),
                       timestamp="2026-01-02T00:00:00+00:00")
