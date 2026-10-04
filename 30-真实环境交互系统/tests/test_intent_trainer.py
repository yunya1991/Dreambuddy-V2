"""IntentTrainer 训练动作测试

替代 spec §5.1 的 test_dynamic_recognizer_training.py（SD-6）。
HC-1a 合规：训练逻辑在 30 系统内，不修改 dreamos/。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample
from core.intent_trainer import IntentTrainer


def _make_sample(confirmed=True, gold_intent="trend_following", scenario_id="TREND_UP"):
    return IntentSample(
        sample_id="s",
        input={"user_query": "test", "scenario_id": scenario_id, "market_features": {"regime": "trending"}},
        gold={"gold_chain": "C", "gold_intent": gold_intent},
        recognizer_output={"predicted_intent": gold_intent if confirmed else "other",
                           "confidence": 0.8, "level": "rule"},
        human_label={"confirmed": confirmed, "corrected_intent": None if confirmed else gold_intent},
        dataset_split="train",
        created_at="2026-10-04T10:00:00Z",
    )


class TestIntentTrainer:
    def test_update_weights_bayesian(self, tmp_path):
        """贝叶斯后验更新：Beta 分布 alpha/beta 递增"""
        weights_path = tmp_path / "weights.json"
        trainer = IntentTrainer(weights_path=weights_path)
        samples = [_make_sample(confirmed=True) for _ in range(5)]
        trainer.update_weights(("trend_following", "TREND_UP"), samples)
        assert weights_path.exists()
        weights = trainer.load_weights()
        key = "trend_following|TREND_UP"  # JSON 键用 | 分隔
        assert key in weights
        # Beta 先验 alpha=1, beta=1；5 个全对 → alpha=6, beta=1
        assert weights[key]["alpha"] == 6
        assert weights[key]["beta"] == 1
        assert weights[key]["sample_count"] == 5

    def test_distill_to_rules_at_threshold(self, tmp_path):
        """≥85% 准确率蒸馏成功"""
        rules_path = tmp_path / "rules.json"
        trainer = IntentTrainer(rules_path=rules_path, distill_accuracy_target=0.85)
        # 10 个样本，9 对 1 错 → 90% 准确率 ≥ 85%
        samples = [_make_sample(confirmed=True) for _ in range(9)] + [_make_sample(confirmed=False)]
        distilled = trainer.distill_to_rules(("trend_following", "TREND_UP"), samples)
        assert distilled is True
        assert rules_path.exists()

    def test_no_distill_below_accuracy(self, tmp_path):
        """<85% 准确率不蒸馏"""
        rules_path = tmp_path / "rules.json"
        trainer = IntentTrainer(rules_path=rules_path, distill_accuracy_target=0.85)
        # 10 个样本，5 对 5 错 → 50% 准确率 < 85%
        samples = [_make_sample(confirmed=True) for _ in range(5)] + [_make_sample(confirmed=False) for _ in range(5)]
        distilled = trainer.distill_to_rules(("trend_following", "TREND_UP"), samples)
        assert distilled is False
        assert not rules_path.exists()

    def test_refine_orchestration_mapping(self, tmp_path):
        """场景→链路映射精确化（L3→L0）"""
        orch_path = tmp_path / "orch.json"
        trainer = IntentTrainer(orch_path=orch_path)
        samples = [_make_sample(confirmed=True) for _ in range(3)]
        trainer.refine_orchestration(("trend_following", "TREND_UP"), samples)
        assert orch_path.exists()
        mapping = trainer.load_orchestration_mapping()
        key = "trend_following|TREND_UP"
        assert key in mapping
        # TREND_FOLLOWING → C 链（spec §4.2）
        assert mapping[key]["pattern"] == "c_chain"
        assert "C1" in mapping[key]["nodes"]
        assert mapping[key]["fallback_level"] == "L0"
