"""PumpDumpReversalGenome — 拉高出货做空基因组 (编排层).

阶段2 新增 (纯新增):
  - PumpDumpReversalSignal: 做空信号输出契约
  - PumpDumpReversalGenome: 编排 WashoutDetector + PumpDumpEndingDetector + 案例库

设计原则 (硬约束):
  - HC-P1: 信号走 evolution probe 仓路径
  - HC-P2: WashoutDetector label=WEAKNESS + conf≥0.80 才进入结束信号判定
  - HC-P5: enable=False 时降级
  - HC-P6: 信号需 ≥ PROBE_THRESHOLD=0.55
  - confidence = weakness_verdict.confidence*0.6 + ending_signal.confidence*0.4

镜像 WashoutReversalGenome (做多), 方向相反.
"""
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd

from .pump_dump_ending_detector import PumpDumpEndingSignal, PumpDumpEndingDetector
from .pump_dump_reversal_case_library import PumpDumpReversalCaseLibrary
from .washout_bayesian_updater import BayesianUpdater
from .washout_case_library import WashoutCase

__all__ = ["PumpDumpReversalGenome", "PumpDumpReversalSignal"]

logger = logging.getLogger(__name__)

_WEAKNESS_CONFIDENCE_THRESHOLD = 0.80
_PROBE_THRESHOLD = 0.55
_CONF_WEIGHT = 0.6
_ENDING_WEIGHT = 0.4


@dataclass(frozen=True)
class PumpDumpReversalSignal:
    """拉高出货做空信号输出契约."""
    direction: str  # "SHORT" / "NONE"
    confidence: float
    washout_verdict: object
    ending_signal: PumpDumpEndingSignal
    reason: str
    timestamp: str

    def __post_init__(self):
        c = float(self.confidence)
        object.__setattr__(self, "confidence", max(0.0, min(1.0, c)))
        object.__setattr__(self, "direction", str(self.direction).upper())


class PumpDumpReversalGenome:
    """拉高出货做空基因组 (镜像 WashoutReversalGenome)."""

    def __init__(self, washout_detector, ending_detector: PumpDumpEndingDetector,
                 case_library: PumpDumpReversalCaseLibrary,
                 bayesian_updater: BayesianUpdater, enable: bool = False,
                 sandbox_validate_fn=None):
        self.washout_detector = washout_detector
        self.ending_detector = ending_detector
        self.case_library = case_library
        self.bayesian_updater = bayesian_updater
        self.enable = bool(enable)
        self.sandbox_validate_fn = sandbox_validate_fn

    def detect_signal(self, coin: str, df: pd.DataFrame,
                      macro_data: Dict) -> PumpDumpReversalSignal:
        ts = datetime.now(timezone.utc).isoformat()
        na = PumpDumpEndingSignal.not_activated("genome_disabled")

        if not self.enable:
            return PumpDumpReversalSignal(
                direction="NONE", confidence=0.0, washout_verdict=None,
                ending_signal=na, reason="genome_disabled", timestamp=ts)

        try:
            verdict = self.washout_detector.run(coin, df, macro_data)
            if verdict is None:
                return PumpDumpReversalSignal(
                    direction="NONE", confidence=0.0, washout_verdict=None,
                    ending_signal=na, reason="verdict_none", timestamp=ts)

            label_val = (verdict.label.value if hasattr(verdict.label, "value")
                         else str(verdict.label).lower())

            # HC-P2: 仅 WEAKNESS (拉高出货/真弱势) 才进入做空判定
            if label_val != "weakness":
                return PumpDumpReversalSignal(
                    direction="NONE", confidence=0.0, washout_verdict=verdict,
                    ending_signal=na, reason=f"label={label_val}", timestamp=ts)

            if verdict.confidence < _WEAKNESS_CONFIDENCE_THRESHOLD:
                return PumpDumpReversalSignal(
                    direction="NONE", confidence=0.0, washout_verdict=verdict,
                    ending_signal=na,
                    reason=f"conf_low={verdict.confidence:.3f}", timestamp=ts)

            ending = self.ending_detector.check(df, macro_data)
            if not ending.activated:
                return PumpDumpReversalSignal(
                    direction="NONE", confidence=0.0, washout_verdict=verdict,
                    ending_signal=ending,
                    reason=f"ending_not_activated:{ending.reason}", timestamp=ts)

            confidence = (verdict.confidence * _CONF_WEIGHT
                          + ending.confidence * _ENDING_WEIGHT)
            confidence = max(0.0, min(1.0, confidence))

            if confidence < _PROBE_THRESHOLD:
                return PumpDumpReversalSignal(
                    direction="NONE", confidence=confidence,
                    washout_verdict=verdict, ending_signal=ending,
                    reason=f"below_threshold={confidence:.3f}", timestamp=ts)

            return PumpDumpReversalSignal(
                direction="SHORT", confidence=confidence,
                washout_verdict=verdict, ending_signal=ending,
                reason=(f"weakness_conf={verdict.confidence:.3f}"
                        f"+ending_conf={ending.confidence:.3f}"
                        f"+combined={confidence:.3f}"),
                timestamp=ts)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("PumpDumpReversalGenome.detect_signal FAIL-OPEN err=%s\n%s", e, tb)
            return PumpDumpReversalSignal(
                direction="NONE", confidence=0.0, washout_verdict=None,
                ending_signal=PumpDumpEndingSignal.not_activated(
                    f"exception:{type(e).__name__}"),
                reason=f"exception:{type(e).__name__}", timestamp=ts)

    def record_case(self, case: WashoutCase) -> None:
        try:
            self.case_library.add(case)
        except Exception as e:
            logger.warning("PumpDumpReversalGenome.record_case FAIL-OPEN: %s", e)

    def evolve(self, proposal: Optional[Dict] = None) -> Dict:
        try:
            if self.sandbox_validate_fn is None:
                return {"accepted": False, "score": 0.0, "baseline_score": 0.0,
                        "reason": "no_sandbox_validate_fn"}
            if proposal is None:
                proposal = {"scenario_id": "pump_dump_default",
                            "new_pattern": "knn_bayesian",
                            "nodes": ["PumpDumpReversalGenome"], "score": 0.5}
            accepted = bool(self.sandbox_validate_fn(proposal))
            return {"accepted": accepted,
                    "score": float(proposal.get("score", 0.0)),
                    "baseline_score": float(proposal.get("baseline_score", 0.0)),
                    "reason": "sandbox_passed" if accepted else "sandbox_rejected"}
        except Exception as e:
            logger.warning("PumpDumpReversalGenome.evolve FAIL-OPEN: %s", e)
            return {"accepted": False, "score": 0.0, "baseline_score": 0.0,
                    "reason": f"exception:{type(e).__name__}"}
