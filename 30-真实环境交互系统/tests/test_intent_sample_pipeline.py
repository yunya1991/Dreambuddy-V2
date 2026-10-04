"""IntentSamplePipeline 测试（落盘 + 分桶 + 触发）"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample, IntentSamplePipeline


def _make_sample(sample_id="s1", gold_intent="trend_following",
                scenario_id="TREND_UP", split="train", confirmed=True):
    return IntentSample(
        sample_id=sample_id,
        input={"user_query": "test", "scenario_id": scenario_id, "market_features": {}},
        gold={"gold_chain": "C", "gold_intent": gold_intent},
        recognizer_output={"predicted_intent": gold_intent if confirmed else "other",
                           "confidence": 0.8, "level": "rule"},
        human_label={"confirmed": confirmed, "corrected_intent": None if confirmed else gold_intent},
        dataset_split=split,
        created_at="2026-10-04T10:00:00Z",
    )


class TestIntentSamplePipeline:
    def test_ingest_persists_sample(self, tmp_path):
        """落盘成功"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        pipeline.ingest(_make_sample("s1"))
        bucket_dir = tmp_path / "trend_following_TREND_UP"
        files = list(bucket_dir.glob("*.json"))
        assert len(files) == 1
        with open(files[0]) as f:
            data = json.load(f)
        assert data["sample_id"] == "s1"
        assert data["gold"]["gold_intent"] == "trend_following"

    def test_bucket_counter_increments(self, tmp_path):
        """分桶计数（仅 train 集）"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        for i in range(3):
            pipeline.ingest(_make_sample(f"s{i}"))
        assert pipeline.bucket_counter[("trend_following", "TREND_UP")] == 3

    def test_trigger_training_at_threshold(self, tmp_path):
        """≥阈值 触发训练（threshold=2 + mock trigger_fn）"""
        call_count = [0]
        def mock_trigger(bucket_key, samples):
            call_count[0] += 1

        pipeline = IntentSamplePipeline(
            storage_path=tmp_path, bucket_threshold=2,
            trigger_fn=mock_trigger,
        )
        pipeline.ingest(_make_sample("s1"))
        assert call_count[0] == 0  # 1 < 2
        pipeline.ingest(_make_sample("s2"))
        assert call_count[0] == 1  # 2 >= 2，触发
        # 触发后清零
        assert pipeline.bucket_counter[("trend_following", "TREND_UP")] == 0

    def test_no_trigger_below_threshold(self, tmp_path):
        """<阈值 不触发"""
        call_count = [0]
        def mock_trigger(bucket_key, samples):
            call_count[0] += 1

        pipeline = IntentSamplePipeline(
            storage_path=tmp_path, bucket_threshold=30,
            trigger_fn=mock_trigger,
        )
        for i in range(10):
            pipeline.ingest(_make_sample(f"s{i}"))
        assert call_count[0] == 0  # 10 < 30

    def test_eval_samples_not_count_train(self, tmp_path):
        """split 隔离：eval 样本落盘但不计入 train 桶"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        pipeline.ingest(_make_sample("s1", split="train"))
        pipeline.ingest(_make_sample("s2", split="eval"))
        # train 桶 1 个（eval 不计数）
        assert pipeline.bucket_counter[("trend_following", "TREND_UP")] == 1
        # 但 eval 样本已落盘
        eval_samples = pipeline.load_split("eval")
        assert len(eval_samples) == 1
        assert eval_samples[0].dataset_split == "eval"

    def test_load_split_returns_only_matching(self, tmp_path):
        """load_split 只返回指定 split 的样本"""
        pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
        pipeline.ingest(_make_sample("s1", split="train"))
        pipeline.ingest(_make_sample("s2", split="train"))
        pipeline.ingest(_make_sample("s3", split="eval"))
        train_samples = pipeline.load_split("train")
        eval_samples = pipeline.load_split("eval")
        assert len(train_samples) == 2
        assert len(eval_samples) == 1
