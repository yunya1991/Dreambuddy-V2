"""IntentEvalGate eval 回归门测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample, IntentSamplePipeline
from training.eval_gate import IntentEvalGate, EvalReport


def _make_eval_sample(gold_intent="trend_following", scenario_id="TREND_UP", sample_id="s"):
    """eval 样本（predicted 与 gold 一致，由 route_fn 决定实际预测）"""
    return IntentSample(
        sample_id=sample_id,
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


class TestClassificationMetrics:
    """v2 行业标准指标：Precision/Recall/F1/混淆矩阵/FN-FP"""

    def test_f1_and_confusion_matrix_with_mixed_predictions(self, tmp_path):
        """混合预测：2 正确 + 1 误判，验证 F1/混淆矩阵/FN-FP"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        # 3 个 eval 样本：2 trend_following + 1 mean_reversion（唯一 sample_id）
        pipeline.ingest(_make_eval_sample("trend_following", sample_id="s1"))
        pipeline.ingest(_make_eval_sample("trend_following", sample_id="s2"))
        pipeline.ingest(_make_eval_sample("mean_reversion", sample_id="s3"))

        # route_fn: 全部返回 trend_following → mean_reversion 被误判
        def route_fn(q):
            return {"predicted_intent": "trend_following", "level": "rule"}

        gate = IntentEvalGate(pipeline, route_fn=route_fn)
        report = gate.run_eval()

        # 准确率 = 2/3
        assert abs(report.accuracy - 2 / 3) < 1e-6

        # trend_following: TP=2, FP=1, FN=0 → P=2/3, R=1.0, F1=0.8
        assert abs(report.precision["trend_following"] - 2 / 3) < 1e-6
        assert abs(report.recall["trend_following"] - 1.0) < 1e-6
        assert abs(report.f1["trend_following"] - 0.8) < 1e-6

        # mean_reversion: TP=0, FP=0, FN=1 → P=0, R=0, F1=0
        assert report.precision["mean_reversion"] == 0.0
        assert report.recall["mean_reversion"] == 0.0
        assert report.f1["mean_reversion"] == 0.0

        # macro F1 = (0.8 + 0.0) / 2 = 0.4
        assert abs(report.f1_macro - 0.4) < 1e-6

        # 混淆矩阵：labels 字母序 [mean_reversion, trend_following]
        # 行=gold, 列=predicted
        assert report.confusion_matrix == [[0, 1], [0, 2]]
        assert report.intent_labels == ["mean_reversion", "trend_following"]

        # FN 列表：1 个（mean_reversion 被误判为 trend_following）
        assert len(report.fn_list) == 1
        assert report.fn_list[0]["gold"] == "mean_reversion"
        assert report.fn_list[0]["predicted"] == "trend_following"

        # FP 列表：1 个
        assert len(report.fp_list) == 1
        assert report.fp_list[0]["predicted"] == "trend_following"

    def test_compute_classification_metrics_unit(self):
        """_compute_classification_metrics 单元测试：3 意图完整混淆矩阵"""
        predictions = [
            ("trend_following", "trend_following", "1", "q1"),
            ("trend_following", "breakout", "2", "q2"),
            ("mean_reversion", "mean_reversion", "3", "q3"),
            ("mean_reversion", "trend_following", "4", "q4"),
            ("breakout", "breakout", "5", "q5"),
            ("breakout", "breakout", "6", "q6"),
        ]
        prec, rec, f1, f1_macro, cm, labels, fn, fp = \
            IntentEvalGate._compute_classification_metrics(predictions)

        # labels 字母序
        assert labels == ["breakout", "mean_reversion", "trend_following"]

        # trend_following: TP=1, FP=1, FN=1 → P=0.5, R=0.5, F1=0.5
        assert prec["trend_following"] == 0.5
        assert rec["trend_following"] == 0.5
        assert abs(f1["trend_following"] - 0.5) < 1e-6

        # breakout: TP=2, FP=1, FN=0 → P=2/3, R=1.0
        assert abs(prec["breakout"] - 2 / 3) < 1e-6
        assert rec["breakout"] == 1.0

        # 混淆矩阵 3x3：行=gold, 列=predicted
        assert cm == [
            [2, 0, 0],
            [0, 1, 1],
            [1, 0, 1],
        ]
        assert len(fn) == 2
        assert len(fp) == 2
