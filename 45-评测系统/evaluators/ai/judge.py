# -*- coding: utf-8 -*-
"""
judge.py — AI 裁判可信度判定（P2-5，SPEC §5.2 A-H4）
======================================================
校准集 ≥200 且 Cohen's κ≥0.60 且 Krippendorff's α≥0.67，方可作为硬性裁判；
任一不达标 → INCONCLUSIVE（该裁判只能进加权项）。
"""

from __future__ import annotations

from scorers.model.calibration import cohen_kappa, krippendorff_alpha
from storage.repo import EvalItemRecord

MIN_SAMPLES = 200
MIN_KAPPA = 0.60
MIN_ALPHA = 0.67


class JudgeCalibrationEvaluator:
    """A-H4：model scorer 是否足以硬性判定。"""

    def __init__(
        self,
        min_samples: int = MIN_SAMPLES,
        min_kappa: float = MIN_KAPPA,
        min_alpha: float = MIN_ALPHA,
    ) -> None:
        self._min_samples = min_samples
        self._min_kappa = min_kappa
        self._min_alpha = min_alpha

    def evaluate(self, human: list[str], judge: list[str], run_id: str) -> list[EvalItemRecord]:
        codes: list[str] = []
        if len(human) < self._min_samples:
            codes.append(f"A-H4_samples_low:{len(human)}")

        kappa = cohen_kappa(human, judge)
        if kappa < self._min_kappa:
            codes.append(f"A-H4_kappa_low:{kappa:.4f}")

        alpha = krippendorff_alpha([human, judge])
        if alpha < self._min_alpha:
            codes.append(f"A-H4_alpha_low:{alpha:.4f}")

        return [
            EvalItemRecord(
                item_id=f"{run_id}-A-H4",
                run_id=run_id,
                name="A-H4-calibration",
                kind="hard",
                score=None,
                n=len(human),
                ci_lower=None,
                ci_upper=None,
                weight=None,
                status="INCONCLUSIVE" if codes else "PASS",
                evidence_id=None,
                detail="; ".join(codes) or None,
            )
        ]
