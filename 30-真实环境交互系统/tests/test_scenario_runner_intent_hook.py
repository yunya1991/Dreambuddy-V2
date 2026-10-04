"""ScenarioRunner IntentSample 产出钩子测试

对齐 spec §3.2（SD-5：伪代码 run_scenario 改为现有 run() 接口扩展）
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scenario_runner import ScenarioRunner
from core.intent_sample_pipeline import IntentSample, IntentSamplePipeline


@pytest.fixture
def runner_with_pipeline(tmp_path):
    config = {"scenarios": {"default_timeout": 60, "retry_count": 0}}
    simulator = MagicMock()
    verifier = MagicMock()
    pipeline = IntentSamplePipeline(storage_path=tmp_path, bucket_threshold=30)
    return ScenarioRunner(config, simulator, verifier, pipeline=pipeline)


@pytest.fixture
def runner_no_pipeline():
    """无 pipeline 的 runner（向后兼容）"""
    config = {"scenarios": {"default_timeout": 60, "retry_count": 0}}
    return ScenarioRunner(config, MagicMock(), MagicMock())


class TestScenarioRunnerIntentHook:
    def test_build_intent_sample_from_yaml(self, runner_with_pipeline):
        """YAML intent_training → IntentSample"""
        scenario = {
            "name": "test",
            "intent_training": {
                "gold_intent": "trend_following",
                "scenario_id": "TREND_UP",
                "split": "train",
                "market_features": {"regime": "trending", "volatility": "medium"},
            },
            "steps": [{"name": "type", "action": "type", "text": "BTC 趋势"}],
        }
        result_mock = MagicMock()
        sample = runner_with_pipeline._build_intent_sample(
            scenario, result_mock, user_input="BTC 趋势"
        )
        assert sample.gold["gold_intent"] == "trend_following"
        assert sample.gold["gold_chain"] == "C"
        assert sample.input["scenario_id"] == "TREND_UP"
        assert sample.input["user_query"] == "BTC 趋势"
        assert sample.input["market_features"]["regime"] == "trending"
        assert sample.dataset_split == "train"

    def test_call_dreamos_intent_route_success(self, runner_with_pipeline):
        """调用 /intent/route 成功"""
        with patch("core.scenario_runner.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "predicted_intent": "trend_following",
                "confidence": 0.82,
                "level": "rule",
            }
            mock_post.return_value = mock_resp

            output = runner_with_pipeline._call_dreamos_intent_route("BTC 趋势")
            assert output["predicted_intent"] == "trend_following"
            assert output["confidence"] == 0.82
            assert output["level"] == "rule"

    def test_human_label_auto_compare(self, runner_with_pipeline):
        """自动对照 gold_intent 生成 human_label"""
        # 匹配
        label = runner_with_pipeline._auto_label(
            {"predicted_intent": "trend_following"}, "trend_following"
        )
        assert label["confirmed"] is True
        assert label["corrected_intent"] is None
        # 不匹配
        label = runner_with_pipeline._auto_label(
            {"predicted_intent": "mean_reversion"}, "trend_following"
        )
        assert label["confirmed"] is False
        assert label["corrected_intent"] == "trend_following"

    def test_failopen_when_dreamos_unavailable(self, runner_with_pipeline):
        """DreamOS 不可用降级（HC-7）"""
        with patch("core.scenario_runner.requests.post", side_effect=Exception("conn refused")):
            output = runner_with_pipeline._call_dreamos_intent_route("BTC 趋势")
            assert output["predicted_intent"] is None
            assert output["level"] == "failopen"
            assert output["confidence"] == 0.0

    def test_run_with_pipeline_captures_sample(self, runner_with_pipeline, tmp_path):
        """run() 末尾钩子触发 IntentSample 落盘"""
        scenario = {
            "name": "test",
            "intent_training": {
                "gold_intent": "trend_following",
                "scenario_id": "TREND_UP",
                "split": "train",
                "market_features": {"regime": "trending"},
            },
            "steps": [{"name": "wait", "action": "wait", "seconds": 0}],
        }
        with patch.object(runner_with_pipeline, "_call_dreamos_intent_route",
                          return_value={"predicted_intent": "trend_following", "confidence": 0.8, "level": "rule"}):
            with patch.object(runner_with_pipeline, "_extract_user_input", return_value="BTC 趋势"):
                mock_page = MagicMock()
                runner_with_pipeline.run(mock_page, scenario)
        # 验证 IntentSample 已落盘
        samples = runner_with_pipeline._pipeline.load_split("train")
        assert len(samples) == 1
        assert samples[0].gold["gold_intent"] == "trend_following"

    def test_run_without_pipeline_no_capture(self, runner_no_pipeline):
        """无 pipeline 时 run() 不触发 capture（向后兼容）"""
        scenario = {
            "name": "test",
            "intent_training": {"gold_intent": "trend_following", "scenario_id": "TREND_UP", "split": "train"},
            "steps": [{"name": "wait", "action": "wait", "seconds": 0}],
        }
        mock_page = MagicMock()
        result = runner_no_pipeline.run(mock_page, scenario)
        # 不报错，正常返回
        assert result.name == "test"
        assert result.passed is True
