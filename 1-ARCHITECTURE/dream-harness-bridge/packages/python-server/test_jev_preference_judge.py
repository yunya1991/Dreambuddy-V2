#!/usr/bin/env python3
"""test_jev_preference_judge.py — 方案D DPO偏好 TDD (RED)

SPEC debate-jev-integration-spec.md §6:
- JevPreferenceJudge.judge(topic, transcript, strategies) -> list[PreferenceSample]
- jev choice 判定逐轮策略偏好
- 返回策略选择概率分布
- 写入 preference_samples.json 用于 DPO
"""
from __future__ import annotations
import os, sys, json, unittest, tempfile
from unittest.mock import MagicMock

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _make_transcript():
    return [
        {"speaker": "bull", "round": 1, "content": {"thesis": "BTC稀缺", "arguments": ["2100万"]}},
        {"speaker": "bear", "round": 1, "content": {"thesis": "BTC波动大", "arguments": ["20%"]}},
        {"speaker": "bull", "round": 2, "content": {"thesis": "BTC抗通胀", "arguments": ["法币贬值"]}},
        {"speaker": "bear", "round": 2, "content": {"thesis": "BTC泡沫", "arguments": ["郁金香"]}},
    ]


class TestImport(unittest.TestCase):
    def test_import(self):
        from jev_preference_judge import JevPreferenceJudge, PreferenceSample  # noqa: F401


class TestFailOpen(unittest.TestCase):
    def test_no_jev_fn_degraded(self):
        """无 jev_fn → degraded=True。"""
        from jev_preference_judge import JevPreferenceJudge
        j = JevPreferenceJudge(jev_fn=None)
        samples = j.judge("BTC", _make_transcript(), ["evidence_heavy", "disadvantage"])
        self.assertEqual(len(samples), 0)

    def test_jev_degraded(self):
        """jev degraded → 空列表。"""
        from jev_preference_judge import JevPreferenceJudge
        jev = MagicMock(return_value={"answers": {}, "degraded": True})
        j = JevPreferenceJudge(jev_fn=jev)
        samples = j.judge("BTC", _make_transcript(), ["evidence_heavy", "disadvantage"])
        self.assertEqual(len(samples), 0)


class TestPreferenceJudge(unittest.TestCase):
    def test_returns_one_per_round(self):
        """每个 round 一个 preference sample。"""
        from jev_preference_judge import JevPreferenceJudge
        jev = MagicMock(return_value={
            "answers": {"r1": {"choice": "evidence_heavy"}, "r2": {"choice": "disadvantage"}},
            "degraded": False})
        j = JevPreferenceJudge(jev_fn=jev)
        samples = j.judge("BTC", _make_transcript(), ["evidence_heavy", "disadvantage"])
        self.assertEqual(len(samples), 2)

    def test_sample_fields(self):
        """sample 包含 topic/round/strategy/choice。"""
        from jev_preference_judge import JevPreferenceJudge
        jev = MagicMock(return_value={
            "answers": {"r1": {"choice": "evidence_heavy"}},
            "degraded": False})
        j = JevPreferenceJudge(jev_fn=jev)
        samples = j.judge("BTC", _make_transcript()[:2], ["evidence_heavy", "disadvantage"])
        s = samples[0]
        self.assertEqual(s.topic, "BTC")
        self.assertEqual(s.round, 1)
        self.assertEqual(s.choice, "evidence_heavy")

    def test_choice_in_strategies(self):
        """jev 返回的 choice 必须在候选策略中。"""
        from jev_preference_judge import JevPreferenceJudge
        jev = MagicMock(return_value={
            "answers": {"r1": {"choice": "unknown_strategy"}},
            "degraded": False})
        j = JevPreferenceJudge(jev_fn=jev)
        samples = j.judge("BTC", _make_transcript()[:2], ["evidence_heavy", "disadvantage"])
        self.assertEqual(len(samples), 0)  # 无效 choice 过滤


class TestSaveSamples(unittest.TestCase):
    def test_save_to_json(self):
        """save_samples 写入 JSON 文件。"""
        from jev_preference_judge import JevPreferenceJudge, PreferenceSample
        samples = [
            PreferenceSample(topic="BTC", round=1, strategies=["a", "b"], choice="a"),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            JevPreferenceJudge.save_samples(samples, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["choice"], "a")
        finally:
            os.unlink(path)


class TestJevQuestions(unittest.TestCase):
    def test_one_choice_question_per_round(self):
        """每轮一个 choice 问题。"""
        from jev_preference_judge import JevPreferenceJudge
        jev = MagicMock(return_value={
            "answers": {"r1": {"choice": "evidence_heavy"}, "r2": {"choice": "disadvantage"}},
            "degraded": False})
        j = JevPreferenceJudge(jev_fn=jev)
        j.judge("BTC", _make_transcript(), ["evidence_heavy", "disadvantage"])
        questions = jev.call_args[0][1]
        self.assertEqual(len(questions), 2)
        for q in questions.values():
            self.assertEqual(q["type"], "choice")
            self.assertEqual(set(q["criteria"].keys()), {"evidence_heavy", "disadvantage"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
