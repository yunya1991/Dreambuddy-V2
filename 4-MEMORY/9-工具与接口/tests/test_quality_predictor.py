"""N-P2 质量预测器蒸馏测试（RED 阶段）。

验收标准：
- QualityPredictor 可从 VerificationRecord 历史训练
- predict(features) 返回 p ∈ [0,1]
- 无训练数据时返回默认 p（如 0.5）
- 特征工程：age_days, verify_count, quality_level, content_length
- 增量训练：可逐步添加样本
- 可导出/导入模型参数
"""
import pytest


def test_module_importable():
    from quality_predictor import QualityPredictor, MemoryFeatures


# ---------------------------------------------------------------------------
# MemoryFeatures
# ---------------------------------------------------------------------------

def test_features_from_dict():
    from quality_predictor import MemoryFeatures
    f = MemoryFeatures.from_dict({
        "age_days": 10,
        "verify_count": 5,
        "quality_level": "B",
        "content_length": 200,
    })
    assert f.age_days == 10
    assert f.verify_count == 5
    assert f.quality_level == "B"
    assert f.content_length == 200


def test_features_defaults():
    from quality_predictor import MemoryFeatures
    f = MemoryFeatures()
    assert f.age_days == 0.0
    assert f.verify_count == 0
    assert f.quality_level == "C"
    assert f.content_length == 0


def test_features_to_vector():
    from quality_predictor import MemoryFeatures
    f = MemoryFeatures(age_days=10, verify_count=5, quality_level="B", content_length=200)
    vec = f.to_vector()
    assert len(vec) == 4
    # quality_level 编码: C=0, B=1, A=2, S=3
    assert vec[2] == 1.0  # B


# ---------------------------------------------------------------------------
# QualityPredictor
# ---------------------------------------------------------------------------

def test_predictor_default_p():
    from quality_predictor import QualityPredictor
    pred = QualityPredictor()
    f = QualityPredictor._default_features() if hasattr(QualityPredictor, '_default_features') else None
    # 无训练数据时 predict 返回默认 p
    from quality_predictor import MemoryFeatures
    p = pred.predict(MemoryFeatures())
    assert 0.0 <= p <= 1.0


def test_predictor_train_and_predict():
    from quality_predictor import QualityPredictor, MemoryFeatures
    pred = QualityPredictor()
    # 训练：高 verify_count + 高质量 → 高 p
    samples = [
        (MemoryFeatures(verify_count=10, quality_level="A"), 0.9),
        (MemoryFeatures(verify_count=10, quality_level="A"), 0.85),
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.3),
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.2),
    ]
    pred.train(samples)
    p_high = pred.predict(MemoryFeatures(verify_count=10, quality_level="A"))
    p_low = pred.predict(MemoryFeatures(verify_count=0, quality_level="C"))
    assert p_high > p_low  # 高质量记忆预测 p 更高


def test_predictor_incremental_train():
    from quality_predictor import QualityPredictor, MemoryFeatures
    pred = QualityPredictor()
    pred.train([(MemoryFeatures(verify_count=5, quality_level="B"), 0.7)])
    p1 = pred.predict(MemoryFeatures(verify_count=5, quality_level="B"))
    # 增量添加更多样本
    pred.train([(MemoryFeatures(verify_count=5, quality_level="B"), 0.9)])
    p2 = pred.predict(MemoryFeatures(verify_count=5, quality_level="B"))
    assert 0.0 <= p2 <= 1.0


def test_predictor_clamps_output():
    from quality_predictor import QualityPredictor, MemoryFeatures
    pred = QualityPredictor()
    pred.train([(MemoryFeatures(verify_count=100, quality_level="S"), 1.0)] * 10)
    p = pred.predict(MemoryFeatures(verify_count=100, quality_level="S"))
    assert 0.0 <= p <= 1.0


def test_predictor_export_import():
    from quality_predictor import QualityPredictor, MemoryFeatures
    pred = QualityPredictor()
    pred.train([
        (MemoryFeatures(verify_count=5, quality_level="B"), 0.7),
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.3),
    ])
    params = pred.export_params()
    p_before = pred.predict(MemoryFeatures(verify_count=5, quality_level="B"))

    pred2 = QualityPredictor()
    pred2.import_params(params)
    p_after = pred2.predict(MemoryFeatures(verify_count=5, quality_level="B"))
    assert abs(p_before - p_after) < 1e-9


def test_predictor_handles_empty_training():
    from quality_predictor import QualityPredictor, MemoryFeatures
    pred = QualityPredictor()
    pred.train([])  # 空训练不应报错
    p = pred.predict(MemoryFeatures())
    assert 0.0 <= p <= 1.0
