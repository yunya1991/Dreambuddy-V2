"""影子模式自动晋升测试（RED 阶段）。

需求：影子模式运行到一定阶段/阈值后自动开启（晋升到 live 模式）。
设计：状态机 shadow→live，带滞回（晋升阈值 + 降级阈值 + 最短驻留时间）。

晋升条件（全部满足）：
- 训练样本数 >= min_samples
- AUC >= promote_auc_threshold
- ECE <= promote_ece_threshold
- PSI <= promote_psi_threshold
- 在 shadow 模式驻留时间 >= min_shadow_dwell_seconds

降级条件（任一满足，且 live 驻留 >= min_live_dwell_seconds）：
- AUC < demote_auc_threshold（比 promote 低 → 滞回）
- ECE > demote_ece_threshold（比 promote 高 → 滞回）
- PSI > demote_psi_threshold
"""
import time
import pytest


def test_module_importable():
    from auto_promotion import AutoPromotionConfig, AutoPromotionManager


def test_default_state_is_shadow():
    """默认处于 shadow 模式。"""
    from auto_promotion import AutoPromotionManager
    mgr = AutoPromotionManager()
    assert mgr.is_shadow_mode() is True
    assert mgr.is_live_mode() is False


def test_promotion_requires_all_conditions():
    """晋升需要所有条件同时满足。"""
    from auto_promotion import AutoPromotionConfig, AutoPromotionManager
    cfg = AutoPromotionConfig(
        min_samples=10,
        promote_auc_threshold=0.7,
        promote_ece_threshold=0.15,
        promote_psi_threshold=0.1,
        min_shadow_dwell_seconds=0,  # 测试用 0 秒
    )
    mgr = AutoPromotionManager(config=cfg)

    # 样本数不足 → 不晋升
    decision = mgr.evaluate(sample_count=5, auc=0.9, ece=0.05, psi=0.0)
    assert decision.promoted is False

    # AUC 不足 → 不晋升
    decision = mgr.evaluate(sample_count=20, auc=0.5, ece=0.05, psi=0.0)
    assert decision.promoted is False

    # ECE 超标 → 不晋升
    decision = mgr.evaluate(sample_count=20, auc=0.9, ece=0.3, psi=0.0)
    assert decision.promoted is False

    # 全部满足 → 晋升
    decision = mgr.evaluate(sample_count=20, auc=0.8, ece=0.1, psi=0.05)
    assert decision.promoted is True
    assert mgr.is_live_mode() is True


def test_min_shadow_dwell_time():
    """影子模式最短驻留时间未满时不晋升。"""
    from auto_promotion import AutoPromotionConfig, AutoPromotionManager
    cfg = AutoPromotionConfig(
        min_samples=1,
        promote_auc_threshold=0.7,
        promote_ece_threshold=0.15,
        promote_psi_threshold=0.1,
        min_shadow_dwell_seconds=9999,  # 很长
    )
    mgr = AutoPromotionManager(config=cfg)
    # 所有指标满足但驻留时间不足
    decision = mgr.evaluate(sample_count=100, auc=0.99, ece=0.01, psi=0.01)
    assert decision.promoted is False
    assert decision.reason == "min_shadow_dwell_not_met"


def test_hysteresis_prevents_jitter():
    """滞回：晋升后即使指标轻微回落也不立即降级。"""
    from auto_promotion import AutoPromotionConfig, AutoPromotionManager
    cfg = AutoPromotionConfig(
        min_samples=1,
        promote_auc_threshold=0.7,
        promote_ece_threshold=0.15,
        promote_psi_threshold=0.1,
        demote_auc_threshold=0.5,   # 比 promote 低 0.2 → 滞回
        demote_ece_threshold=0.25,  # 比 promote 高 0.1 → 滞回
        demote_psi_threshold=0.2,   # 比 promote 高 0.1 → 滞回
        min_shadow_dwell_seconds=0,
        min_live_dwell_seconds=0,
    )
    mgr = AutoPromotionManager(config=cfg)

    # 晋升
    mgr.evaluate(sample_count=10, auc=0.8, ece=0.1, psi=0.05)
    assert mgr.is_live_mode() is True

    # AUC 回落到 0.6（仍高于 demote 阈值 0.5）→ 不降级
    decision = mgr.evaluate(sample_count=10, auc=0.6, ece=0.1, psi=0.05)
    assert decision.demoted is False
    assert mgr.is_live_mode() is True

    # AUC 跌破 demote 阈值 0.5 → 降级
    decision = mgr.evaluate(sample_count=10, auc=0.4, ece=0.1, psi=0.05)
    assert decision.demoted is True
    assert mgr.is_shadow_mode() is True


def test_min_live_dwell_prevents_premature_demotion():
    """live 模式最短驻留时间未满时不降级。"""
    from auto_promotion import AutoPromotionConfig, AutoPromotionManager
    cfg = AutoPromotionConfig(
        min_samples=1,
        promote_auc_threshold=0.7,
        promote_ece_threshold=0.15,
        promote_psi_threshold=0.1,
        demote_auc_threshold=0.5,
        min_shadow_dwell_seconds=0,
        min_live_dwell_seconds=9999,  # 很长
    )
    mgr = AutoPromotionManager(config=cfg)

    # 晋升
    mgr.evaluate(sample_count=10, auc=0.8, ece=0.1, psi=0.05)
    assert mgr.is_live_mode() is True

    # 指标恶化但驻留不足 → 不降级
    decision = mgr.evaluate(sample_count=10, auc=0.1, ece=0.9, psi=0.9)
    assert decision.demoted is False
    assert decision.reason == "min_live_dwell_not_met"


def test_metrics_snapshot_recorded():
    """每次 evaluate 记录指标快照。"""
    from auto_promotion import AutoPromotionManager
    mgr = AutoPromotionManager()
    mgr.evaluate(sample_count=5, auc=0.6, ece=0.2, psi=0.05)
    mgr.evaluate(sample_count=10, auc=0.7, ece=0.1, psi=0.03)
    history = mgr.metrics_history()
    assert len(history) == 2
    assert history[-1]["auc"] == 0.7


def test_promotion_log():
    """晋升/降级事件有日志记录。"""
    from auto_promotion import AutoPromotionConfig, AutoPromotionManager
    cfg = AutoPromotionConfig(
        min_samples=1, promote_auc_threshold=0.7,
        promote_ece_threshold=0.15, promote_psi_threshold=0.1,
        min_shadow_dwell_seconds=0, min_live_dwell_seconds=0,
    )
    mgr = AutoPromotionManager(config=cfg)
    mgr.evaluate(sample_count=10, auc=0.8, ece=0.1, psi=0.05)
    mgr.evaluate(sample_count=10, auc=0.3, ece=0.5, psi=0.5)
    events = mgr.event_log()
    events_types = [e["event"] for e in events]
    assert "promoted" in events_types
    assert "demoted" in events_types
