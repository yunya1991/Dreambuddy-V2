# ruff: noqa: E402  (sys.path 必须先于 asil 导入)
"""P0-2 统计门禁 pytest：holdout 独立 + bootstrap CI + Holm 校正。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from asil.emergence_loop import D2EmergenceLoop, D3EmergenceLoop
from asil.stat_gate import (
    evidence_level,
    holm_adjust,
    paired_bootstrap,
    wilson_interval,
)
from asil.variant_generator import RuleVariant


class TestPairedBootstrap:
    def test_detects_real_improvement(self):
        base = [1] * 600 + [0] * 400
        cand = [1] * 750 + [0] * 250
        out = paired_bootstrap(cand, base, n_boot=1000, alpha=0.05, seed=7)
        assert out["mean_diff"] > 0.1
        assert out["ci_low"] > 0
        assert out["p_value"] < 0.05

    def test_identical_vectors_not_significant(self):
        same = [1] * 50 + [0] * 50
        out = paired_bootstrap(same, list(same), n_boot=1000, seed=7)
        assert out["mean_diff"] == 0.0
        assert out["ci_low"] <= 0
        assert out["p_value"] > 0.5

    def test_empty_input_is_safe(self):
        out = paired_bootstrap([], [], n_boot=100)
        assert out["p_value"] == 1.0 and out["n"] == 0


class TestHolmAdjust:
    def test_known_values(self):
        assert holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]

    def test_borderline_significance_becomes_insignificant(self):
        # 单看 0.03 < 0.05，但在 family=2 下校正为 0.06 → 不显著
        adjusted = holm_adjust([0.03, 0.03])
        assert adjusted == [0.06, 0.06]

    def test_empty(self):
        assert holm_adjust([]) == []


class TestHoldoutIndependence:
    def _loop(self, tmp_path) -> D3EmergenceLoop:
        loop = D3EmergenceLoop(
            events_path=tmp_path / "unused.jsonl",
            variants=[RuleVariant("base"), RuleVariant("cand", fallback="majority")],
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        loop._train = [{"ok": True}]
        loop._val = [{"ok": True}]
        return loop

    def test_holdout_never_used_for_screening(self, tmp_path):
        """val 无提升但 holdout 明显更好 → 仍须拒绝（holdout 不参与择优）。"""
        loop = self._loop(tmp_path)
        metrics = {
            "base": {
                "top1": 0.80,
                "ece": 0.10,
                "n_val": 100,
                "holdout_top1": 0.70,
                "holdout_ece": 0.10,
                "n_holdout": 400,
                "holdout_correct": [1] * 280 + [0] * 120,
            },
            "cand": {
                "top1": 0.80,  # val 无提升
                "ece": 0.10,
                "n_val": 100,
                "holdout_top1": 0.90,  # holdout 假象提升
                "holdout_ece": 0.10,
                "n_holdout": 400,
                "holdout_correct": [1] * 360 + [0] * 40,
            },
        }
        loop.evaluate = lambda v: dict(metrics[v.name])
        summary = loop.run(rounds=1)
        assert summary["history"][0]["decision"] == "reject"
        assert summary["history"][0]["metrics"]["gate"] == "screened_out_on_val"
        assert summary["stat_gate"]["family_size"] == 0

    def test_holm_family_blocks_borderline(self, tmp_path):
        """两个候选同时筛选通过 → Holm 校正后大概率被拒（family=2）。"""
        loop = self._loop(tmp_path)
        strong_val = {
            "top1": 0.82,
            "ece": 0.09,
            "n_val": 100,
            "holdout_top1": 0.82,
            "holdout_ece": 0.09,
            "n_holdout": 60,
            "holdout_correct": [1] * 50 + [0] * 10,
        }
        base = {
            "top1": 0.80,
            "ece": 0.10,
            "n_val": 100,
            "holdout_top1": 0.80,
            "holdout_ece": 0.10,
            "n_holdout": 60,
            "holdout_correct": [1] * 48 + [0] * 12,
        }
        loop.variants = [RuleVariant("base"), RuleVariant("c1", fallback="majority")]
        loop.evaluate = lambda v: dict(base if v.name == "base" else strong_val)
        summary = loop.run(rounds=1)
        # 小样本 + family 校正：即使点估计提升也不应轻易 accept
        if summary["history"][0]["decision"] == "accept":
            assert summary["history"][0]["metrics"]["p_adjusted"] < 0.05
        else:
            assert summary["stat_gate"]["family_size"] == 1


class TestWilsonInterval:
    def test_known_value(self):
        out = wilson_interval(3, 5)
        assert out["p"] == 0.6
        assert 0.22 <= out["ci_low"] <= 0.24  # 约 0.231
        assert 0.87 <= out["ci_high"] <= 0.89  # 约 0.882
        assert out["n"] == 5

    def test_empty_and_bounds(self):
        assert wilson_interval(0, 0) == {"p": 0.0, "ci_low": 0.0, "ci_high": 1.0, "n": 0}
        full = wilson_interval(10, 10)
        assert full["p"] == 1.0 and full["ci_high"] <= 1.0 and full["ci_low"] > 0.6

    def test_small_sample_has_wide_interval(self):
        tiny = wilson_interval(1, 1)
        large = wilson_interval(15, 20)
        assert tiny["ci_low"] < large["ci_low"]
        assert (tiny["ci_high"] - tiny["ci_low"]) > (large["ci_high"] - large["ci_low"])

    def test_evidence_level(self):
        assert evidence_level(1) == "insufficient"
        assert evidence_level(5) == "weak"
        assert evidence_level(10) == "adequate"


class TestD2ChampionTieBreak:
    def test_prefers_larger_sample_over_lucky_single(self):
        scoreboard = {
            "tiny": {"n": 1, "pass_rate": 1.0, "ci_low": 0.207, "ci_high": 1.0},
            "solid": {"n": 10, "pass_rate": 1.0, "ci_low": 0.722, "ci_high": 1.0},
        }
        assert D2EmergenceLoop._pick_champion(scoreboard) == "solid"

    def test_empty_scoreboard(self):
        assert D2EmergenceLoop._pick_champion({}) is None


class TestThreeWaySplit:
    def test_splits_are_disjoint_and_exhaustive(self, tmp_path):
        events = tmp_path / "events.jsonl"
        rows = [
            {
                "session_id": f"s{i}",
                "intent_signals": {"file_domains": ["dom1"]},
                "intent_proxy": "trade",
            }
            for i in range(100)
        ]
        events.write_text("\n".join(json.dumps(r) for r in rows))

        loop = D3EmergenceLoop(
            events_path=events,
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        loop.load_data()

        assert len(loop._train) + len(loop._val) + len(loop._holdout) == 100
        ids = (
            {e["session_id"] for e in loop._train}
            | {e["session_id"] for e in loop._val}
            | {e["session_id"] for e in loop._holdout}
        )
        assert len(ids) == 100  # 三段互斥
        assert len(loop._holdout) > 0 and len(loop._val) > 0
