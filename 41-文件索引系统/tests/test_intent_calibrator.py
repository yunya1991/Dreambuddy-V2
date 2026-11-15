# -*- coding: utf-8 -*-
"""test_intent_calibrator.py — P3 per-intent 校准 + uplift 度量测试"""

import json
import sys
from pathlib import Path

_INDEX_ROOT = Path(__file__).resolve().parent.parent
if str(_INDEX_ROOT) not in sys.path:
    sys.path.insert(0, str(_INDEX_ROOT))

from core.intent_calibrator import (  # noqa: E402
    IntentCalibrationResult,
    calibrate_intent,
    format_report,
    report_to_json,
)
from core.intent_vector_store import IntentVectorStore  # noqa: E402


class MockStore(IntentVectorStore):
    """可控的 mock store：按 message 返回固定的 top-1 / similarity。"""

    def __init__(self, intent_id, top1_map=None, sim_map=None, has_vec=True):
        # 不调用父类 __init__，避免加载真实向量
        self._intent_id = intent_id
        self._top1_map = top1_map or {}  # msg -> (intent, sim)
        self._sim_map = sim_map or {}  # msg -> sim
        self._has_vec = has_vec
        self._loaded = True
        self._vectors = {}

    def has_vector(self, intent_id, lang="zh"):
        return self._has_vec

    def top1(self, query_vector, lang="zh"):
        # query_vector 在这里被用作 message 传递（测试 hack）
        return self._top1_map.get(query_vector)

    def similarity_to(self, intent_id, query_vector, lang="zh"):
        return self._sim_map.get(query_vector)

    def search(self, query_vector, lang="zh", top_k=3, exclude_intents=None):
        top1 = self._top1_map.get(query_vector)
        if top1 and exclude_intents and top1[0] in exclude_intents:
            return []
        return [top1] if top1 else []

    @property
    def intent_ids(self):
        return [self._intent_id]


def _make_unit_dir(tmp_path, intent_id, positives, negatives):
    """在 tmp_path 下创建意图单元目录。"""
    d = tmp_path / intent_id
    d.mkdir(parents=True)
    with open(d / "examples_zh.jsonl", "w", encoding="utf-8") as f:
        for m in positives:
            f.write(json.dumps({"message": m}, ensure_ascii=False) + "\n")
    with open(d / "negatives_zh.jsonl", "w", encoding="utf-8") as f:
        for m in negatives:
            f.write(json.dumps({"message": m}, ensure_ascii=False) + "\n")
    return d


class TestCalibrateIntent:
    def test_no_vector_returns_fail(self, tmp_path):
        _make_unit_dir(tmp_path, "x", ["a"], ["b"])
        store = MockStore("x", has_vec=False)
        res = calibrate_intent("x", store, threshold=0.65, units_dir=tmp_path)
        assert res.has_vector is False
        assert res.pass_calibration is False
        assert res.details["reason"] == "no_vector"

    def test_tpr_and_fpr_with_regex(self, tmp_path, monkeypatch):
        positives = ["pos1", "pos2", "pos3"]
        negatives = ["neg1", "neg2"]
        _make_unit_dir(tmp_path, "x", positives, negatives)

        # regex: pos1→x（命中）, pos2→y（误路由）, pos3→""（漏过）
        # neg1→y, neg2→""
        regex_results = {"pos1": "x", "pos2": "y", "pos3": "", "neg1": "y", "neg2": ""}

        # 语义 top-1: pos3→x（兜底命中）, neg2→x（误命中）
        top1_map = {"pos3": ("x", 0.8), "neg2": ("x", 0.7)}
        store = MockStore("x", top1_map=top1_map)

        # mock embed 让它返回原 message 作为 vec（MockStore 用 message 查表）
        monkeypatch.setattr("core.intent_calibrator.embed", lambda msg, lang="zh": msg)

        res = calibrate_intent(
            "x", store, threshold=0.65, units_dir=tmp_path, regex_results=regex_results
        )
        # TP: pos1(regex→x), pos3(语义→x) = 2; TPR=2/3
        assert res.tp == 2
        assert abs(res.tpr - 2 / 3) < 1e-6
        # FP: neg2(语义→x) = 1; FPR=1/2
        assert res.fp == 1
        assert abs(res.fpr - 0.5) < 1e-6
        assert res.pass_calibration is False  # FPR=50% > 2%

    def test_pass_calibration(self, tmp_path, monkeypatch):
        positives = [f"p{i}" for i in range(20)]
        negatives = [f"n{i}" for i in range(50)]
        _make_unit_dir(tmp_path, "x", positives, negatives)

        # regex 命中所有正例到 x；反例 regex 全部未命中且语义不命中
        regex_results = dict.fromkeys(positives, "x")
        regex_results.update(dict.fromkeys(negatives, ""))
        store = MockStore("x", top1_map={})
        monkeypatch.setattr("core.intent_calibrator.embed", lambda msg, lang="zh": msg)

        res = calibrate_intent(
            "x", store, threshold=0.65, units_dir=tmp_path, regex_results=regex_results
        )
        assert res.tpr == 1.0
        assert res.fpr == 0.0
        assert res.pass_calibration is True

    def test_uplift_with_semantic_contribution(self, tmp_path, monkeypatch):
        """正例 regex 未命中但语义兜底命中 → uplift > 0。"""
        positives = ["p1"]
        negatives = ["n1"]
        _make_unit_dir(tmp_path, "x", positives, negatives)

        regex_results = {"p1": "", "n1": ""}
        # 语义：p1→x（兜底命中），n1→y（不误命中）
        top1_map = {"p1": ("x", 0.8), "n1": ("y", 0.8)}
        store = MockStore("x", top1_map=top1_map)
        monkeypatch.setattr("core.intent_calibrator.embed", lambda msg, lang="zh": msg)

        res = calibrate_intent(
            "x", store, threshold=0.65, units_dir=tmp_path, regex_results=regex_results
        )
        # with: p1→x (TP=1), n1→y (TN=1) → acc=2/2=1.0
        # without: p1→y (not x, 0), n1→y (not x, 1) → acc=1/2=0.5
        assert res.acc_with == 1.0
        assert abs(res.acc_without - 0.5) < 1e-6
        assert abs(res.uplift - 0.5) < 1e-6


class TestReport:
    def test_format_report(self):
        results = [
            IntentCalibrationResult(
                intent_id="a",
                n_pos=10,
                n_neg=20,
                tp=10,
                fp=0,
                tpr=1.0,
                fpr=0.0,
                uplift=0.0,
                pass_calibration=True,
            ),
            IntentCalibrationResult(intent_id="b", has_vector=False),
        ]
        text = format_report(results)
        assert "a" in text
        assert "b" in text
        assert "PASS" in text
        assert "汇总" in text

    def test_report_to_json(self):
        r = IntentCalibrationResult(
            intent_id="a",
            n_pos=10,
            n_neg=20,
            tp=9,
            fp=1,
            tpr=0.9,
            fpr=0.05,
            uplift=0.1,
            pass_calibration=True,
        )
        out = report_to_json([r])
        assert len(out) == 1
        assert out[0]["intent_id"] == "a"
        assert out[0]["tpr"] == 0.9
        assert out[0]["pass_calibration"] is True
