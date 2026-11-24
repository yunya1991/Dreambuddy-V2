#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retrain_daily.py 单测：幂等 no_change、版本自增、drift、history、dry-run。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import retrain_daily as rd  # noqa: E402

PREP = {
    "raw_total": 175,
    "deduped_total": 137,
    "deduped_by_platform": {"xiaohongshu": 34, "douyin": 103},
}


def make_gates(g1: bool, g2: bool, g5: bool, features=None) -> dict:
    return {
        "G0": {"pass": True},
        "G1": {"pass": g1},
        "G2": {"pass": g2, "evidence": {"per_feature": features or []}},
        "G3": {"pass": False},
        "G4": {"pass": True},
        "G5": {"pass": g5},
    }


EVIDENCE_FEATURES = [
    {
        "platform": "xiaohongshu",
        "feature": "title_len",
        "n": 60,
        "rho": 0.30,
        "status": "ok",
        "controllable": True,
        "qualified": True,
    },
    {
        "platform": "xiaohongshu",
        "feature": "hashtag_count",
        "n": 60,
        "rho": 0.10,
        "status": "ok",
        "controllable": True,
        "qualified": True,
    },
]
ROWS = [{}] * 137


class RetrainDailyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.model_path = os.path.join(self.tmp, "model", "optimizer_model.json")
        self.history_dir = os.path.join(self.tmp, "model", "history")

    def tearDown(self):
        self._tmp.cleanup()

    def _retrain(self, gates, generated_at="2026-11-24T10:00:00+08:00", **kwargs):
        return rd.retrain(
            model_path=self.model_path,
            history_dir=self.history_dir,
            generated_at=generated_at,
            rows=ROWS,
            prep_info=PREP,
            gates=gates,
            verdict="No-Go",
            **kwargs,
        )

    def test_first_run_writes_model_and_history(self):
        result = self._retrain(make_gates(False, False, False))
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["version"], 1)
        self.assertTrue(os.path.isfile(self.model_path))
        self.assertTrue(os.path.isfile(result["history"]))
        self.assertTrue(result["history"].endswith("20261124.json"))
        with open(result["history"], "r", encoding="utf-8") as fh:
            history = json.load(fh)
        self.assertEqual(history["version"], 1)
        self.assertTrue(history["drift"]["rules_added"])
        self.assertIn("model", history)

    def test_second_run_same_input_is_no_change(self):
        self._retrain(make_gates(False, False, False))
        with open(self.model_path, "rb") as fh:
            before = fh.read()
        result = self._retrain(
            make_gates(False, False, False), generated_at="2026-11-24T11:00:00+08:00"
        )
        self.assertEqual(result["status"], "no_change")
        self.assertEqual(result["version"], 1)
        with open(self.model_path, "rb") as fh:
            after = fh.read()
        self.assertEqual(before, after)

    def test_gate_change_bumps_version_and_records_drift(self):
        self._retrain(make_gates(False, False, False))
        result = self._retrain(
            make_gates(True, True, True, EVIDENCE_FEATURES),
            generated_at="2026-11-25T10:00:00+08:00",
        )
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["version"], 2)
        drift = result["drift"]
        self.assertEqual(drift["gate_status"], {"from": "no_signal", "to": "evidence"})
        self.assertTrue(drift["weight_changes"])
        self.assertTrue(result["history"].endswith("20261125.json"))
        with open(self.model_path, "r", encoding="utf-8") as fh:
            model = json.load(fh)
        self.assertEqual(model["version"], 2)
        self.assertEqual(model["gate_status"], "evidence")

    def test_force_updates_even_without_content_change(self):
        self._retrain(make_gates(False, False, False))
        result = self._retrain(make_gates(False, False, False), force=True)
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["version"], 2)

    def test_dry_run_does_not_write(self):
        result = self._retrain(make_gates(False, False, False), dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(os.path.exists(self.model_path))
        self.assertFalse(os.path.exists(self.history_dir))


if __name__ == "__main__":
    unittest.main()
