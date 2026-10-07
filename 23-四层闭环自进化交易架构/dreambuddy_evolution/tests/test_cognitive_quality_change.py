"""TDD-CV-005: 自进化闭环 - CognitiveBridge.record_quality_change FAIL-OPEN."""
from dreambuddy_evolution.adapters.cognitive_bridge import CognitiveBridge


def test_record_quality_change_disabled_returns_none():
    """enabled=False 时返回 None（FAIL-OPEN）。"""
    bridge = CognitiveBridge(enabled=False)
    result = bridge.record_quality_change({
        "old_dim": "technical",
        "new_dim": "fundamental",
        "divergence_count": 7,
        "structural_break": {"volatility_regime_change": True},
    })
    assert result is None


def test_record_quality_change_fail_open_on_missing_entry():
    """entry 加载失败时返回 None，不抛异常。"""
    bridge = CognitiveBridge(enabled=True, db_path="/nonexistent/path.db")
    # 用 mock 让 _get_entry 返回 None
    bridge._entry = None
    bridge._get_entry = lambda: None  # type: ignore
    result = bridge.record_quality_change({"old_dim": "macro", "new_dim": "technical"})
    assert result is None
