"""IntentSample 数据契约测试"""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample


class TestIntentSampleContract:
    """IntentSample dataclass 字段契约（对齐 spec §3.2 7 字段）"""

    def test_intent_sample_dataclass_fields(self):
        """7 字段齐全：sample_id/input/gold/recognizer_output/human_label/dataset_split/created_at"""
        sample = IntentSample(
            sample_id="test-001",
            input={"user_query": "BTC 趋势", "scenario_id": "TREND_UP", "market_features": {}},
            gold={"gold_chain": "C", "gold_intent": "trend_following"},
            recognizer_output={"predicted_intent": "trend_following", "confidence": 0.8, "level": "rule"},
            human_label={"confirmed": True, "corrected_intent": None},
            dataset_split="train",
            created_at="2026-10-04T10:00:00Z",
        )
        assert sample.sample_id == "test-001"
        assert sample.input["user_query"] == "BTC 趋势"
        assert sample.gold["gold_chain"] == "C"
        assert sample.gold["gold_intent"] == "trend_following"
        assert sample.recognizer_output["confidence"] == 0.8
        assert sample.human_label["confirmed"] is True
        assert sample.dataset_split == "train"
        assert sample.created_at == "2026-10-04T10:00:00Z"

    def test_intent_sample_serialization(self):
        """JSON 往返序列化（to_dict / from_dict）"""
        original = IntentSample(
            sample_id="test-002",
            input={"user_query": "test", "scenario_id": "TREND_DOWN", "market_features": {"regime": "trending"}},
            gold={"gold_chain": "C", "gold_intent": "trend_following"},
            recognizer_output={"predicted_intent": None, "confidence": 0.0, "level": "failopen"},
            human_label={"confirmed": False, "corrected_intent": "trend_following"},
            dataset_split="eval",
            created_at="2026-10-04T10:00:00Z",
        )
        d = original.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        restored_data = json.loads(json_str)
        restored = IntentSample.from_dict(restored_data)
        assert restored.sample_id == original.sample_id
        assert restored.dataset_split == "eval"
        assert restored.human_label["corrected_intent"] == "trend_following"
        assert restored.recognizer_output["level"] == "failopen"

    def test_yaml_intent_training_field_parse(self, tmp_path):
        """YAML 4 字段解析：gold_intent/scenario_id/split/market_features"""
        yaml_content = """
name: test
description: test
intent_training:
  gold_intent: "trend_following"
  scenario_id: "TREND_UP"
  split: "train"
  market_features:
    regime: "trending"
    volatility: "medium"
    data_freshness: "realtime"
steps:
  - name: step1
    action: wait
    seconds: 0
"""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        with open(yaml_file, "r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)

        it = parsed["intent_training"]
        assert it["gold_intent"] == "trend_following"
        assert it["scenario_id"] == "TREND_UP"
        assert it["split"] == "train"
        assert it["market_features"]["regime"] == "trending"
        assert it["market_features"]["data_freshness"] == "realtime"
