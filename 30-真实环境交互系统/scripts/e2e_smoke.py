"""端到端 smoke 测试：YAML → ScenarioRunner → IntentSample → Pipeline → EvalGate

不依赖真实 DreamOS（用 mock route_fn）。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scenario_runner import ScenarioRunner
from core.intent_sample_pipeline import IntentSamplePipeline
from training.eval_gate import IntentEvalGate


def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    pipeline = IntentSamplePipeline(storage_path=tmp, bucket_threshold=30)
    config = {"scenarios": {"default_timeout": 10, "retry_count": 0}}
    runner = ScenarioRunner(config, MagicMock(), MagicMock(), pipeline=pipeline)

    # 模拟 DreamOS /intent/route 返回正确意图
    def mock_route(text):
        if "趋势" in text or "顺势" in text:
            return {"predicted_intent": "trend_following", "confidence": 0.85, "level": "rule"}
        if "震荡" in text or "高抛低吸" in text or "均值回归" in text:
            return {"predicted_intent": "mean_reversion", "confidence": 0.80, "level": "rule"}
        if "突破" in text:
            return {"predicted_intent": "breakout", "confidence": 0.82, "level": "rule"}
        return {"predicted_intent": "uncertain", "confidence": 0.3, "level": "rule"}

    # 跑 5 个 train + 2 个 eval 场景（抽样，不全跑 45 个）
    scenario_dir = Path("scenarios/intent_training")
    train_files = sorted(scenario_dir.glob("*_train_00[1-5].yaml"))[:3]
    eval_files = sorted(scenario_dir.glob("*_eval_00[1-2].yaml"))[:2]

    with patch.object(runner, "_call_dreamos_intent_route", side_effect=mock_route):
        for f in train_files + eval_files:
            scenario = runner.load_scenario(str(f))
            mock_page = MagicMock()
            runner.run(mock_page, scenario)

    # 验证 IntentSample 落盘
    train_samples = pipeline.load_split("train")
    eval_samples = pipeline.load_split("eval")
    print(f"train 样本: {len(train_samples)}, eval 样本: {len(eval_samples)}")
    assert len(train_samples) == 3
    assert len(eval_samples) == 2

    # 跑 eval 回归门
    gate = IntentEvalGate(pipeline, route_fn=mock_route, accuracy_target=0.5, drift_limit=0.5)
    report = gate.run_eval()
    print(f"EvalReport: accuracy={report.accuracy:.2f} passed={report.passed} "
          f"zero_token_ratio={report.zero_token_ratio:.2f}")
    assert report.accuracy >= 0.5
    print("✓ 端到端 smoke 验证通过")


if __name__ == "__main__":
    main()
