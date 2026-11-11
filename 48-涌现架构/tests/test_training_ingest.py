"""training_ingest.py 单元测试（G1 补强）。
覆盖：sample_id 幂等、normalize_sample 字段映射、load_source_rows FAIL-OPEN、ingest 幂等 append-only。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "/home/luke/dreambuddy/48-涌现架构/metrics")

import training_ingest as ti


class TestSampleId(unittest.TestCase):
    def test_deterministic(self):
        row = {"doc_id": "d1", "as_of": "2026-11-11", "gate": "g1"}
        self.assertEqual(ti._sample_id("p3a", row), ti._sample_id("p3a", row))

    def test_differs_by_source_and_fields(self):
        row = {"doc_id": "d1", "as_of": "2026-11-11", "gate": "g1"}
        self.assertNotEqual(ti._sample_id("p3a", row), ti._sample_id("p3b", row))
        row2 = dict(row, doc_id="d2")
        self.assertNotEqual(ti._sample_id("p3a", row), ti._sample_id("p3a", row2))

    def test_prefix(self):
        row = {"doc_id": "d1", "as_of": "a", "gate": "g"}
        self.assertTrue(ti._sample_id("p3a", row).startswith("TS-"))


class TestNormalizeSample(unittest.TestCase):
    def test_field_mapping(self):
        row = {
            "doc_id": "d1",
            "as_of": "2026-11-11",
            "title": "t",
            "dominant_factor": "F1",
            "dominant_dimension": "DIM",
            "direction": "up",
            "horizon": "1w",
            "urgency": "high",
            "impact": "mid",
            "gate": "g1",
            "weight": 0.5,
            "agreement": 0.8,
            "measured_top": "F1",
            "measured_direction": "up",
            "measured_z": 1.2,
            "measured_strength": 0.7,
        }
        s = ti.normalize_sample("p3a", row)
        self.assertEqual(s["schema_version"], ti.SCHEMA_VERSION)
        self.assertEqual(s["source"], "p3a")
        self.assertEqual(s["doc_id"], "d1")
        self.assertEqual(s["dominant_factor"], "F1")
        self.assertEqual(s["measured"]["top"], "F1")
        self.assertEqual(s["measured"]["z"], 1.2)
        self.assertTrue(s["sample_id"].startswith("TS-"))

    def test_missing_fields_tolerated(self):
        s = ti.normalize_sample("p3b", {})
        self.assertIsNone(s["doc_id"])
        self.assertIsNone(s["measured"]["z"])


class TestLoadSourceRows(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(ti.load_source_rows(Path("/tmp/__no_such_file__.jsonl")), [])

    def test_bad_lines_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"doc_id": "d1"}) + "\n")
            f.write("not-json\n")
            f.write("\n")
            f.write(json.dumps([1, 2]) + "\n")
            f.write(json.dumps({"doc_id": "d2"}) + "\n")
            path = f.name
        rows = ti.load_source_rows(Path(path))
        self.assertEqual([r["doc_id"] for r in rows], ["d1", "d2"])


class TestIngest(unittest.TestCase):
    def _make_source(self, tmpdir: str, name: str, rows: list) -> Path:
        p = Path(tmpdir) / f"{name}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return p

    def test_ingest_idempotent_append_only(self):
        with tempfile.TemporaryDirectory() as td:
            src = self._make_source(td, "p3a", [
                {"doc_id": "d1", "as_of": "a", "gate": "g"},
                {"doc_id": "d2", "as_of": "a", "gate": "g"},
            ])
            out = Path(td) / "out"
            st1 = ti.ingest(sources={"p3a": src}, out_dir=out)
            self.assertEqual(st1["total"], 2)
            self.assertEqual(st1["per_source"]["p3a"]["appended"], 2)
            st2 = ti.ingest(sources={"p3a": src}, out_dir=out)
            self.assertEqual(st2["total"], 0)
            self.assertEqual(st2["per_source"]["p3a"]["appended"], 0)
            self.assertEqual(st2["per_source"]["p3a"]["total_in_file"], 2)
            lines = (out / "p3a_samples.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)

    def test_ingest_missing_source_fail_open(self):
        with tempfile.TemporaryDirectory() as td:
            st = ti.ingest(
                sources={"p3a": Path(td) / "missing.jsonl"},
                out_dir=Path(td) / "out",
            )
            self.assertEqual(st["total"], 0)
            self.assertEqual(st["per_source"]["p3a"]["n_rows"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
