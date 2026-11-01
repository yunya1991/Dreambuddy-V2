# -*- coding: utf-8 -*-
"""test_ai_judge.py — P2-5 AI 裁判：Cohen's κ / Krippendorff's α / 顺序对调。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluators.ai.judge import JudgeCalibrationEvaluator  # noqa: E402
from scorers.model.calibration import (  # noqa: E402
    CalibrationError,
    cohen_kappa,
    krippendorff_alpha,
)
from scorers.model.position_swap import (  # noqa: E402
    PositionSwapJudge,
    SwapJudgement,
    winner_from_pair,
)

# ---------- κ / α 计算 ----------


def test_kappa_perfect_agreement():
    assert cohen_kappa(["A", "B", "C"], ["A", "B", "C"]) == pytest.approx(1.0)


def test_kappa_reference_example():
    # 6 条：一致 5 条，po=5/6，pe=0.5 → κ=0.666667
    human = ["A", "A", "A", "A", "B", "B"]
    judge = ["A", "A", "A", "B", "B", "B"]
    assert cohen_kappa(human, judge) == pytest.approx(0.666667, abs=1e-6)


def test_alpha_reference_example():
    # D_o=1/6，D_e=1-(7/12)^2-(5/12)^2 → α≈0.657143
    human = ["A", "A", "A", "A", "B", "B"]
    judge = ["A", "A", "A", "B", "B", "B"]
    assert krippendorff_alpha([human, judge]) == pytest.approx(0.657143, abs=1e-5)


def test_alpha_full_agreement_is_one():
    assert krippendorff_alpha([["A", "B"], ["A", "B"]]) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "human,judge",
    [
        ([], []),
        (["A", "B"], ["A"]),
        (["A", "B"], ["A", ""]),
    ],
)
def test_calibration_rejects_bad_input(human, judge):
    with pytest.raises(CalibrationError):
        cohen_kappa(human, judge)
    with pytest.raises(CalibrationError):
        krippendorff_alpha([human, judge])


# ---------- 顺序对调 ----------


def test_position_swap_consistent_prefers_longer():
    def longer_first(_prompt, first, second):
        return "first" if len(first) >= len(second) else "second"

    result = PositionSwapJudge(longer_first).judge("i-1", "q", "long answer", "short")
    assert result.consistent is True
    assert result.winner == "A"


def test_position_swap_detects_first_position_bias():
    def always_first(_prompt, _first, _second):
        return "first"

    result = PositionSwapJudge(always_first).judge("i-1", "q", "alpha", "beta")
    assert result.consistent is False
    assert result.winner is None
    assert result.flipped is True
    assert result.first_pass == "A" and result.second_pass == "B"


def test_position_swap_tie_is_consistent():
    result = PositionSwapJudge(lambda *_args: "tie").judge("i-1", "q", "alpha", "beta")
    assert result.consistent is True
    assert result.winner == "tie"


def test_swap_judgement_maps_second_position_back():
    judgement = SwapJudgement(
        item_id="i-1", prompt="q", first_pass="B", second_pass="A", winner="A", consistent=False
    )
    assert judgement.flipped is True


def test_winner_from_pair():
    assert winner_from_pair("first", swapped=False) == "A"
    assert winner_from_pair("second", swapped=False) == "B"
    assert winner_from_pair("first", swapped=True) == "B"
    assert winner_from_pair("second", swapped=True) == "A"
    assert winner_from_pair("tie", swapped=True) == "tie"


# ---------- A-H4 判定 ----------


def build_labels(n: int, agreements: int) -> tuple[list[str], list[str]]:
    human = ["A", "B"] * (n // 2)
    judge = list(human)
    for index in range(n - agreements):
        judge[index] = "B" if human[index] == "A" else "A"
    return human, judge


def test_calibration_pass_at_200_samples():
    human, judge = build_labels(200, 195)
    item = JudgeCalibrationEvaluator().evaluate(human, judge, run_id="RUN-1")[0]
    assert item.name == "A-H4-calibration"
    assert item.kind == "hard"
    assert item.status == "PASS"
    assert item.detail is None


def test_calibration_samples_below_200():
    human, judge = build_labels(150, 150)
    item = JudgeCalibrationEvaluator().evaluate(human, judge, run_id="RUN-1")[0]
    assert item.status == "INCONCLUSIVE"
    assert item.detail == "A-H4_samples_low:150"


def test_calibration_kappa_below_threshold():
    human, judge = build_labels(200, 150)  # κ≈0.5，低于 0.60
    item = JudgeCalibrationEvaluator().evaluate(human, judge, run_id="RUN-1")[0]
    assert item.status == "INCONCLUSIVE"
    assert "A-H4_kappa_low:" in (item.detail or "")


def test_calibration_alpha_below_threshold():
    human = ["A", "B"] * 100
    judge = ["A"] * 200  # 一致 100/200，α≈0
    item = JudgeCalibrationEvaluator().evaluate(human, judge, run_id="RUN-1")[0]
    assert item.status == "INCONCLUSIVE"
    assert "A-H4_alpha_low:" in (item.detail or "")
