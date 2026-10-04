"""验证扩容后贝叶斯训练实际触发

灌 30 train 样本到同一桶（trend_following × TREND_UP），验证：
1. IntentSamplePipeline.ingest 在 bucket_counter >= BUCKET_THRESHOLD(30) 时触发训练
2. IntentTrainer.update_weights 被调用，weights.json 生成
3. Beta 分布 alpha/beta 正确递增（alpha=1+correct, beta=1+wrong）
4. 准确率 ≥ 85% 时 distill_to_rules 和 refine_orchestration 也被触发
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSample, IntentSamplePipeline
from core.intent_trainer import IntentTrainer


def make_sample(idx: int, confirmed: bool = True,
                gold_intent: str = "trend_following",
                scenario_id: str = "TREND_UP") -> IntentSample:
    return IntentSample(
        sample_id=f"s{idx:03d}",
        input={"user_query": "BTC 趋势向上，顺势加仓",
               "scenario_id": scenario_id, "market_features": {"regime": "trending"}},
        gold={"gold_chain": "C", "gold_intent": gold_intent},
        recognizer_output={"predicted_intent": gold_intent if confirmed else "other",
                           "confidence": 0.85, "level": "rule"},
        human_label={"confirmed": confirmed, "corrected_intent": None if confirmed else gold_intent},
        dataset_split="train",
        created_at="2026-10-04T10:00:00Z",
    )


def main():
    tmp = Path(tempfile.mkdtemp())
    storage = tmp / "samples"
    weights_path = tmp / "weights.json"
    rules_path = tmp / "rules.json"
    orch_path = tmp / "orch.json"

    print(f"临时目录: {tmp}")

    # 用自定义 trigger_fn 记录触发，同时调用 IntentTrainer（注入自定义存储路径）
    trainer = IntentTrainer(
        weights_path=weights_path,
        rules_path=rules_path,
        orch_path=orch_path,
        distill_accuracy_target=0.85,
    )
    trigger_log = []

    def mock_trigger(bucket_key, samples):
        trigger_log.append((bucket_key, len(samples)))
        trainer.update_weights(bucket_key, samples)
        acc = IntentSamplePipeline._compute_accuracy(samples)
        if acc >= 0.85 and len(samples) >= 30:
            trainer.distill_to_rules(bucket_key, samples)
            trainer.refine_orchestration(bucket_key, samples)

    pipeline = IntentSamplePipeline(
        storage_path=storage,
        bucket_threshold=30,
        trigger_fn=mock_trigger,
    )

    # 灌 29 个：不触发
    for i in range(1, 30):
        pipeline.ingest(make_sample(i))
    assert len(trigger_log) == 0, f"29 个样本不应触发训练，但触发了 {len(trigger_log)} 次"
    assert pipeline.bucket_counter[("trend_following", "TREND_UP")] == 29
    print("✓ 29 个样本 < 30 阈值，未触发训练")

    # 第 30 个：触发
    pipeline.ingest(make_sample(30))
    assert len(trigger_log) == 1, f"第 30 个样本应触发训练，但触发了 {len(trigger_log)} 次"
    bucket_key, n_samples = trigger_log[0]
    assert bucket_key == ("trend_following", "TREND_UP")
    assert n_samples == 30
    # 触发后清零
    assert pipeline.bucket_counter[("trend_following", "TREND_UP")] == 0
    print(f"✓ 第 30 个样本触发训练: bucket={bucket_key}, samples={n_samples}")

    # 验证 weights.json（贝叶斯 alpha/beta）
    assert weights_path.exists(), "weights.json 应被生成"
    weights = trainer.load_weights()
    key = "trend_following|TREND_UP"
    assert key in weights, f"weights 中应含 key={key}"
    # Beta 先验 alpha=1, beta=1；30 个全对 → alpha=31, beta=1
    assert weights[key]["alpha"] == 31, f"alpha 应为 31，实际 {weights[key]['alpha']}"
    assert weights[key]["beta"] == 1, f"beta 应为 1，实际 {weights[key]['beta']}"
    assert weights[key]["sample_count"] == 30
    posterior_mean = weights[key]["posterior_mean"]
    assert abs(posterior_mean - 31/32) < 1e-6, f"posterior_mean 应为 {31/32:.6f}"
    print(f"✓ 贝叶斯更新正确: alpha={weights[key]['alpha']}, beta={weights[key]['beta']}, "
          f"posterior_mean={posterior_mean:.4f}")

    # 验证 rules.json（distill_to_rules，准确率 100% ≥ 85%）
    assert rules_path.exists(), "rules.json 应被生成"
    rules = trainer.load_rules()
    assert key in rules
    print(f"✓ 规则蒸馏成功: rules.json 含 {len(rules)} 条规则")

    # 验证 orchestration_mapping.json（refine_orchestration）
    assert orch_path.exists(), "orchestration_mapping.json 应被生成"
    mapping = trainer.load_orchestration_mapping()
    assert key in mapping
    assert mapping[key]["pattern"] == "c_chain"
    assert mapping[key]["fallback_level"] == "L0"
    print(f"✓ 编排映射精确化: {key} → {mapping[key]['pattern']} (fallback={mapping[key]['fallback_level']})")

    # 再灌 30 个（其中 3 个错），验证后验累积 + 不蒸馏（90% ≥ 85% 仍蒸馏）
    for i in range(31, 61):
        confirmed = not (i in (31, 32, 33))  # 3 个错
        pipeline.ingest(make_sample(i, confirmed=confirmed))
    assert len(trigger_log) == 2
    weights = trainer.load_weights()
    # 累积：correct=30+27=57, wrong=0+3=3 → alpha=1+57=58, beta=1+3=4
    assert weights[key]["alpha"] == 58, f"alpha 应为 58，实际 {weights[key]['alpha']}"
    assert weights[key]["beta"] == 4, f"beta 应为 4，实际 {weights[key]['beta']}"
    print(f"✓ 第二轮累积后验: alpha={weights[key]['alpha']}, beta={weights[key]['beta']}, "
          f"posterior_mean={weights[key]['posterior_mean']:.4f}")

    print("\n=== 贝叶斯训练触发验证全部通过 ===")
    print(f"weights.json: {weights_path}")
    print(f"rules.json: {rules_path}")
    print(f"orchestration_mapping.json: {orch_path}")


if __name__ == "__main__":
    main()
