"""B-05: W6 样本持久化与监控测试."""
from __future__ import annotations

import json

from dreambuddy_evolution.core.contradiction_identifier import (
    ContradictionWeightLearner,
    PrimaryContradictionIdentifier,
)


def _learner(tmp_path):
    return ContradictionWeightLearner(storage_path=str(tmp_path / "samples.json"))


def _record(learner, index=0):
    learner.record_prediction(
        {"power": 0.4, "time": 0.2, "consistency": 0.3, "market_weight": 0.1},
        direction="long" if index % 2 == 0 else "short",
        confidence=0.7,
        timestamp=1000.0 + index,
    )


class TestW6Monitor:
    def test_status_empty(self, tmp_path):
        status = _learner(tmp_path).status()
        assert status["available"] is True
        assert status["exists"] is False
        assert status["total_samples"] == 0
        assert status["labeled_samples"] == 0
        assert status["learn_ready"] is False
        assert status["retention"] == 2000
        assert status["weights"] == [0.4, 0.15, 0.25, 0.2]

    def test_record_flush_and_status(self, tmp_path):
        learner = _learner(tmp_path)
        _record(learner, 0)
        _record(learner, 1)
        learner.flush()
        status = learner.status()
        assert status["exists"] is True
        assert status["bytes"] > 0
        assert status["total_samples"] == 2
        assert status["unlabeled_samples"] == 2
        with open(status["path"], encoding="utf-8") as f:
            payload = json.load(f)
        assert len(payload["samples"]) == 2

    def test_label_persists_and_reloads(self, tmp_path):
        learner = _learner(tmp_path)
        _record(learner, 0)
        learner.label_previous(0.012)
        reloaded = _learner(tmp_path)
        status = reloaded.status()
        assert status["total_samples"] == 1
        assert status["labeled_samples"] == 1

    def test_atomic_save_leaves_no_tmp(self, tmp_path):
        learner = _learner(tmp_path)
        _record(learner, 0)
        learner.flush()
        assert not (tmp_path / "samples.json.tmp").exists()

    def test_retention_2000(self, tmp_path):
        learner = _learner(tmp_path)
        learner._samples = [
            {
                "ts": float(index),
                "power": 0.4,
                "time": 0.2,
                "consistency": 0.3,
                "market_weight": 0.1,
                "direction": "long",
                "confidence": 0.7,
                "actual_return": 0.01,
            }
            for index in range(2005)
        ]
        learner.flush()
        reloaded = _learner(tmp_path)
        assert reloaded.status()["total_samples"] == 2000

    def test_corrupt_file_fail_open(self, tmp_path):
        path = tmp_path / "samples.json"
        path.write_text("{not-json", encoding="utf-8")
        learner = ContradictionWeightLearner(storage_path=str(path))
        status = learner.status()
        assert status["available"] is True
        assert status["total_samples"] == 0

    def test_identifier_w6_status(self, tmp_path):
        learner = _learner(tmp_path)
        _record(learner, 0)
        identifier = PrimaryContradictionIdentifier(weight_learner=learner)
        status = identifier.w6_status()
        assert status["total_samples"] == 1

    def test_switch_default_off(self):
        from dreambuddy_evolution.agi_config import get_switch

        assert get_switch("enable_w6_monitor", False) is False