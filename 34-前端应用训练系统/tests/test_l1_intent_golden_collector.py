# -*- coding: utf-8 -*-
"""IntentGoldenCollector 单元测试 — L1 意图 golden set 接入训练链路。

覆盖:
  TR-1.1  实现 TrainingDataProvider 接口
  TR-1.2  get_source_name / get_quality_threshold
  TR-1.3  fetch_cases 完整覆盖全部 golden 标注（对数取自文件，且不低于历史下限）
  TR-1.4  TrainingCase 字段映射（intent/outcome_text/metadata/layer_tags）
  TR-1.5  unknown 标注标记为负样本
  TR-1.6  limit 生效
  TR-1.7  FAIL-OPEN: 文件缺失返回空列表
  TR-1.8  FAIL-OPEN: 损坏行跳过
  TR-1.9  增量: since 晚于文件 mtime 时返回空列表
"""

import json
import os
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import intent_golden_collector as igc  # noqa: E402
from interfaces.training_data_provider import TrainingDataProvider  # noqa: E402

# 标注集只增不减；下限用于捕捉误删/解析中断，实际条数取自文件（避免常量漂移）
_GOLDEN_TOTAL_MIN = 377


class IntentGoldenCollectorTest(unittest.TestCase):
    def test_implements_provider(self):
        self.assertIsInstance(igc.IntentGoldenCollector(), TrainingDataProvider)

    def test_source_and_threshold(self):
        c = igc.IntentGoldenCollector()
        self.assertEqual(c.get_source_name(), "intent_golden")
        self.assertEqual(c.get_quality_threshold(), "B")

    def test_fetch_all_cases(self):
        self.assertTrue(os.path.exists(igc.GOLDEN_PATH), "golden set 缺失")
        valid = 0
        with open(igc.GOLDEN_PATH, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (row.get("message") or "").strip() and (row.get("intent") or "").strip():
                    valid += 1
        cases = igc.IntentGoldenCollector().fetch_cases(limit=100000)
        self.assertEqual(len(cases), valid, "fetch_cases 必须完整覆盖标注集")
        self.assertGreaterEqual(len(cases), _GOLDEN_TOTAL_MIN, "标注集条数不得低于历史下限")

    def test_case_mapping(self):
        cases = igc.IntentGoldenCollector().fetch_cases(limit=5)
        self.assertTrue(cases)
        for case in cases:
            self.assertTrue(case.outcome_text)
            self.assertEqual(case.source, "intent_golden")
            self.assertEqual(case.layer_tags, ["L1"])
            self.assertEqual(case.metadata["expected_intent"], case.intent)
            self.assertEqual(case.metadata["dataset"], "l1_intent_golden")
            # 标注集质量应过默认 B 级门控
            self.assertIn(case.quality, {"S", "A"})

    def test_unknown_is_negative_sample(self):
        cases = igc.IntentGoldenCollector().fetch_cases(limit=1000)
        negatives = [c for c in cases if c.intent == "unknown"]
        self.assertTrue(negatives)
        self.assertTrue(all(c.metadata["negative_sample"] for c in negatives))
        self.assertFalse(any(c.metadata["negative_sample"] for c in cases if c.intent != "unknown"))

    def test_limit(self):
        self.assertEqual(len(igc.IntentGoldenCollector().fetch_cases(limit=7)), 7)

    def test_missing_file_fails_open(self):
        old = igc.GOLDEN_PATH
        try:
            igc.GOLDEN_PATH = os.path.join(tempfile.mkdtemp(), "missing.jsonl")
            self.assertEqual(igc.IntentGoldenCollector().fetch_cases(limit=10), [])
        finally:
            igc.GOLDEN_PATH = old

    def test_corrupt_line_skipped(self):
        old = igc.GOLDEN_PATH
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "golden.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json\n")
            f.write(json.dumps({"message": "BTC什么价", "intent": "price_query"}) + "\n")
            f.write(json.dumps({"message": "", "intent": "price_query"}) + "\n")
        try:
            igc.GOLDEN_PATH = path
            cases = igc.IntentGoldenCollector().fetch_cases(limit=10)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0].intent, "price_query")
        finally:
            igc.GOLDEN_PATH = old

    def test_incremental_since(self):
        cases = igc.IntentGoldenCollector().fetch_cases(limit=10, since="9999999999999")
        self.assertEqual(cases, [])
        cases = igc.IntentGoldenCollector().fetch_cases(limit=10, since="0")
        self.assertTrue(cases)


if __name__ == "__main__":
    unittest.main()
