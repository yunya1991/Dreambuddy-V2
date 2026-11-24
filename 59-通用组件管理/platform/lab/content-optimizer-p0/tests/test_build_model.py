#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_model.py 单测：门禁降级、先验规则、确定性、文件契约。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import build_model as bm  # noqa: E402


def make_gates(g1: bool, g2: bool, g5: bool, features=None) -> dict:
    return {
        "G0": {"pass": True},
        "G1": {"pass": g1},
        "G2": {"pass": g2, "evidence": {"per_feature": features or []}},
        "G3": {"pass": False},
        "G4": {"pass": True},
        "G5": {"pass": g5},
    }


def make_features(rho_a=0.30, rho_b=0.10) -> list[dict]:
    return [
        {
            "platform": "xiaohongshu",
            "feature": "title_len",
            "n": 60,
            "rho": rho_a,
            "status": "ok",
            "controllable": True,
            "qualified": True,
        },
        {
            "platform": "xiaohongshu",
            "feature": "hashtag_count",
            "n": 60,
            "rho": rho_b,
            "status": "ok",
            "controllable": True,
            "qualified": True,
        },
        {
            "platform": "xiaohongshu",
            "feature": "rank",
            "n": 60,
            "rho": 0.90,
            "status": "ok",
            "controllable": False,
            "qualified": False,
        },
        {
            "platform": "douyin",
            "feature": "title_len",
            "n": 0,
            "rho": None,
            "status": "insufficient",
            "controllable": True,
            "qualified": False,
        },
    ]


PREP = {
    "raw_total": 175,
    "deduped_total": 137,
    "deduped_by_platform": {"xiaohongshu": 34, "douyin": 103},
}


class BuildModelTest(unittest.TestCase):
    def test_no_signal_all_prior_and_rules_kept(self):
        model = bm.build_model(
            [{}] * 137,
            PREP,
            make_gates(False, False, False, make_features()),
            "No-Go",
            generated_at="2026-11-24T23:00:00+08:00",
        )
        self.assertEqual(model["gate_status"], "no_signal")
        self.assertEqual(model["verdict"], "No-Go")
        for platform in ("xiaohongshu", "douyin"):
            block = model["platforms"][platform]
            self.assertTrue(block["rules"])
            for feature in block["features"]:
                self.assertEqual(feature["weight"], 0.0)
                self.assertEqual(feature["source"], "prior")
        self.assertTrue(model["rules"])

    def test_evidence_normalizes_qualified_weights(self):
        model = bm.build_model(
            [{}] * 137,
            PREP,
            make_gates(True, True, True, make_features()),
            "Go",
            generated_at="2026-11-24T23:00:00+08:00",
        )
        self.assertEqual(model["gate_status"], "evidence")
        block = model["platforms"]["xiaohongshu"]
        by_name = {f["name"]: f for f in block["features"]}
        # 非可控特征 rank 不进入 features
        self.assertNotIn("rank", by_name)
        total = sum(f["weight"] for f in block["features"])
        self.assertAlmostEqual(total, 1.0, places=3)
        self.assertEqual(by_name["title_len"]["source"], "evidence")
        self.assertGreater(by_name["title_len"]["weight"], by_name["hashtag_count"]["weight"])
        # 抖音证据不足的特征仍然 weight=0
        douyin = model["platforms"]["douyin"]["features"]
        self.assertTrue(all(f["weight"] == 0.0 for f in douyin))

    def test_partial_gate_failure_falls_back_to_no_signal(self):
        model = bm.build_model(
            [{}] * 137,
            PREP,
            make_gates(True, True, False, make_features()),
            "Conditional-Go",
            generated_at="2026-11-24T23:00:00+08:00",
        )
        self.assertEqual(model["gate_status"], "no_signal")

    def test_deterministic_except_generated_at(self):
        gates = make_gates(True, True, True, make_features())
        first = bm.build_model(
            [{}] * 137, PREP, gates, "Go", generated_at="2026-11-24T23:00:00+08:00"
        )
        second = bm.build_model(
            [{}] * 137, PREP, gates, "Go", generated_at="2026-11-25T01:00:00+08:00"
        )
        first.pop("generated_at")
        second.pop("generated_at")
        self.assertEqual(
            json.dumps(first, sort_keys=True, ensure_ascii=False),
            json.dumps(second, sort_keys=True, ensure_ascii=False),
        )

    def test_source_counts_from_prep_info(self):
        model = bm.build_model(
            [{}] * 137,
            PREP,
            make_gates(False, False, False, []),
            "No-Go",
            generated_at="2026-11-24T23:00:00+08:00",
        )
        self.assertEqual(
            model["source"],
            {"rows": 175, "deduped": 137, "by_platform": {"xiaohongshu": 34, "douyin": 103}},
        )

    def test_write_model_roundtrip(self):
        model = bm.build_model(
            [{}] * 137,
            PREP,
            make_gates(False, False, False, []),
            "No-Go",
            generated_at="2026-11-24T23:00:00+08:00",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "optimizer_model.json")
            bm.write_model(model, path)
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
        for key in (
            "schema_version",
            "version",
            "generated_at",
            "gate_status",
            "verdict",
            "source",
            "platforms",
            "rules",
        ):
            self.assertIn(key, loaded)
        self.assertEqual(loaded["schema_version"], bm.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
