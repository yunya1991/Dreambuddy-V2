"""IntentEvalGate eval 回归门测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample, IntentSamplePipeline
from training.eval_gate import IntentEvalGate, EvalReport


def _make_eval_sample(gold_intent="trend_following", scenario_id="TREND_UP"):
    """eval 样本（predicted 与 gold 一致，由 route_fn 决定实际预测）"""
    return IntentSample(
        sample_id="s",
        input={"user_query": "test", "scenario_id": scenario_id, "market_features": {}},
        gold={"gold_chain": "C", "gold_intent": gold_intent},
        recognizer_output={"predicted_intent": gold_intent, "confidence": 0.8, "level": "rule"},
        human_label={"confirmed": True, "corrected_intent": None},
        dataset_split="eval",
        created_at="2026-10-04T10:00:00Z",
    )


class TestIntentEvalGate:
    def test_run_eval_returns_report(self, tmp_path):
        """返回 EvalReport"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        for i in range(3):
            pipeline.ingest(_make_eval_sample())
        # route_fn 全返回正确意图
        gate = IntentEvalGate(
            pipeline,
            route_fn=lambda q: {"predicted_intent": "trend_following", "level": "rule"},
        )
        report = gate.run_eval()
        assert isinstance(report, EvalReport)
        assert report.accuracy == 1.0
        assert report.passed is True

    def test_accuracy_below_target_fails(self, tmp_path):
        """准确率 < 75% 不通过"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        for i in range(4):
            pipeline.ingest(_make_eval_sample())
        # route_fn 全返回错误意图 → 0% 准确率
        gate = IntentEvalGate(
            pipeline,
            route_fn=lambda q: {"predicted_intent": "other", "level": "rule"},
            accuracy_target=0.75,
        )
        report = gate.run_eval()
        assert report.passed is False
        assert report.accuracy == 0.0

    def test_drift_exceeds_limit_fails(self, tmp_path):
        """波动 ≥3% 不通过"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        for i in range(4):
            pipeline.ingest(_make_eval_sample())
        gate = IntentEvalGate(
            pipeline,
            route_fn=lambda q: {"predicted_intent": "trend_following", "level": "rule"},
            accuracy_target=0.5,
            drift_limit=0.03,
        )
        # 第一次：100% 准确率
        report1 = gate.run_eval()
        assert report1.accuracy == 1.0
        assert report1.passed is True
        # 第二次：改为全错 → 0% 准确率，drift=1.0 ≥ 0.03
        gate._route_fn = lambda q: {"predicted_intent": "wrong", "level": "rule"}
        report2 = gate.run_eval()
        assert report2.accuracy == 0.0
        assert report2.drift >= 0.03
        assert report2.passed is False
