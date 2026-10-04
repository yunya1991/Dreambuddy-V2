"""N-P2 质量预测器增强测试（RED 阶段）。

文档要求补齐：
- 影子模式：打分不影响排序
- 达标门：gold set 上 AUC/ECE
- 灰度放量
- 5% 探索流量
- PSI 漂移监控
- include_suppressed 显式召回
- 审计日志
"""
import pytest


def test_module_importable():
    from quality_predictor import (
        QualityPredictor, ShadowModeConfig, DriftMonitor,
    )


# ---------------------------------------------------------------------------
# 影子模式
# ---------------------------------------------------------------------------

def test_shadow_mode_does_not_affect_recall():
    """影子模式下，预测结果不影响 recall 排序。"""
    from quality_predictor import QualityPredictor, ShadowModeConfig
    qp = QualityPredictor()
    cfg = ShadowModeConfig(shadow_mode=True)
    # 影子模式下 is_suppressed 始终返回 False
    assert qp.is_suppressed(features=None, config=cfg) is False


def test_live_mode_suppresses_low_p():
    """非影子模式下，低 p 记忆被抑制。"""
    from quality_predictor import QualityPredictor, ShadowModeConfig
    from quality_predictor import MemoryFeatures
    qp = QualityPredictor()
    # 训练：高 verify_count → 高 p
    qp.train([
        (MemoryFeatures(verify_count=10, quality_level="A"), 0.9),
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.1),
    ])
    cfg = ShadowModeConfig(shadow_mode=False, suppress_threshold=0.3)
    low_feat = MemoryFeatures(verify_count=0, quality_level="C")
    high_feat = MemoryFeatures(verify_count=10, quality_level="A")
    assert qp.is_suppressed(low_feat, cfg) is True
    assert qp.is_suppressed(high_feat, cfg) is False


# ---------------------------------------------------------------------------
# 灰度 + 探索流量
# ---------------------------------------------------------------------------

def test_gray_release_traffic_routing():
    """灰度放量：只有 gray_traffic_pct% 的流量使用预测器。"""
    from quality_predictor import QualityPredictor, ShadowModeConfig
    qp = QualityPredictor()
    cfg = ShadowModeConfig(shadow_mode=False, gray_traffic_pct=50.0)
    # 统计 1000 次请求中被路由到预测器的比例
    import random
    random.seed(42)
    routed = sum(1 for _ in range(1000) if qp.should_route_to_predictor(cfg))
    # 50% 灰度，应在 400-600 之间
    assert 400 <= routed <= 600


def test_exploration_traffic_includes_suppressed():
    """5% 探索流量：被探索的请求会包含抑制记忆。"""
    from quality_predictor import QualityPredictor, ShadowModeConfig
    qp = QualityPredictor()
    cfg = ShadowModeConfig(shadow_mode=False, exploration_pct=5.0)
    import random
    random.seed(42)
    explored = sum(1 for _ in range(1000) if qp.is_exploration_traffic(cfg))
    # 5% 探索，应在 30-70 之间
    assert 30 <= explored <= 70


# ---------------------------------------------------------------------------
# 达标门（AUC/ECE）
# ---------------------------------------------------------------------------

def test_gold_set_gating_auc():
    """达标门：在 gold set 上计算 AUC。"""
    from quality_predictor import QualityPredictor
    from quality_predictor import MemoryFeatures
    qp = QualityPredictor()
    qp.train([
        (MemoryFeatures(verify_count=10, quality_level="A"), 0.9),
        (MemoryFeatures(verify_count=8, quality_level="A"), 0.85),
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.1),
        (MemoryFeatures(verify_count=1, quality_level="C"), 0.15),
    ])
    gold_set = [
        (MemoryFeatures(verify_count=10, quality_level="A"), 1.0),  # pass
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.0),   # fail
    ]
    metrics = qp.evaluate_on_gold_set(gold_set)
    assert "auc" in metrics
    assert "ece" in metrics
    assert 0.0 <= metrics["auc"] <= 1.0
    assert 0.0 <= metrics["ece"] <= 1.0


def test_gating_passes_when_auc_above_threshold():
    """AUC 达标时 gating 通过。"""
    from quality_predictor import QualityPredictor
    from quality_predictor import MemoryFeatures
    qp = QualityPredictor()
    qp.train([
        (MemoryFeatures(verify_count=10, quality_level="A"), 0.95),
        (MemoryFeatures(verify_count=8, quality_level="A"), 0.9),
        (MemoryFeatures(verify_count=5, quality_level="B"), 0.7),
        (MemoryFeatures(verify_count=2, quality_level="B"), 0.5),
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.05),
        (MemoryFeatures(verify_count=1, quality_level="C"), 0.1),
    ])
    gold_set = [
        (MemoryFeatures(verify_count=10, quality_level="A"), 1.0),
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.0),
    ]
    assert qp.passes_gate(gold_set, min_auc=0.5, max_ece=0.2) is True


# ---------------------------------------------------------------------------
# PSI 漂移监控
# ---------------------------------------------------------------------------

def test_psi_zero_for_identical_distributions():
    """相同分布 PSI = 0。"""
    from quality_predictor import DriftMonitor
    dm = DriftMonitor()
    baseline = [0.5, 0.5, 0.5, 0.5]
    current = [0.5, 0.5, 0.5, 0.5]
    psi = dm.compute_psi(baseline, current)
    assert abs(psi) < 1e-9


def test_psi_positive_for_different_distributions():
    """不同分布 PSI > 0。"""
    from quality_predictor import DriftMonitor
    dm = DriftMonitor()
    baseline = [0.8, 0.1, 0.1]
    current = [0.1, 0.1, 0.8]
    psi = dm.compute_psi(baseline, current)
    assert psi > 0.0


def test_drift_alert_threshold():
    """PSI > 0.25 触发漂移告警。"""
    from quality_predictor import DriftMonitor
    dm = DriftMonitor(alert_threshold=0.25)
    baseline = [0.9, 0.05, 0.05]
    current = [0.05, 0.05, 0.9]
    assert dm.is_drifted(baseline, current) is True


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------

def test_audit_log_records_decisions():
    """审计日志记录抑制决策。"""
    from quality_predictor import QualityPredictor, ShadowModeConfig
    from quality_predictor import MemoryFeatures
    qp = QualityPredictor()
    qp.train([
        (MemoryFeatures(verify_count=0, quality_level="C"), 0.1),
    ])
    cfg = ShadowModeConfig(shadow_mode=False, suppress_threshold=0.3)
    feat = MemoryFeatures(verify_count=0, quality_level="C")
    qp.is_suppressed(feat, cfg, memory_id="VM-test")
    log = qp.get_audit_log()
    assert len(log) >= 1
    entry = log[-1]
    assert entry["memory_id"] == "VM-test"
    assert "suppressed" in entry
