"""Solution Path quarantined 状态 + path_advantage_history 单测（设计节 7.5 + 7.7）。"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from cognitive_superpowers import ProcessTemplate, ProcessTemplateRegistry


def test_process_template_has_quarantined_field():
    t = ProcessTemplate(template_id="APP-test", name="test", steps=[])
    assert t.quality_level in ("S", "A", "B", "C", "D", "quarantined")
    assert hasattr(t, "path_advantage_history")
    assert hasattr(t, "evaluation_count")
    assert hasattr(t, "consecutive_positive")
    assert hasattr(t, "consecutive_negative")


def test_quarantined_not_recalled():
    """设计节 7.7：quarantined 的 Solution Path recall 时不召回。"""
    registry = ProcessTemplateRegistry()
    registry.register_applied_from_session(
        template_id="APP-bad", name="bad path", steps=["s1"],
        parent_template_id="test-driven-development", solution_path={},
        parent_skill_ids=["test-driven-development"],
        quality_level="quarantined",
    )
    results = registry.retrieve_applied("dev", top_k=5)
    for a in results:
        assert a.get("quality_level") != "quarantined"


def test_path_advantage_history_tracking():
    """附录 A.6：path_advantage_history 累积。"""
    registry = ProcessTemplateRegistry()
    applied_id = "APP-track"
    registry.register_applied_from_session(
        template_id=applied_id, name="t", steps=["s"],
        parent_template_id="tdd", solution_path={},
        parent_skill_ids=["tdd"],
    )
    registry.update_path_advantage(applied_id, path_advantage=0.3, decision="upgrade")
    registry.update_path_advantage(applied_id, path_advantage=0.4, decision="upgrade")
    applied = registry.get_applied_template(applied_id)
    assert applied is not None
    assert len(applied.path_advantage_history) == 2
    assert applied.consecutive_positive == 2
    assert applied.evaluation_count == 2


def test_quarantine_after_consecutive_negatives():
    """设计节 7.5：连续 3 次负向 → quarantined。"""
    registry = ProcessTemplateRegistry()
    applied_id = "APP-neg"
    registry.register_applied_from_session(
        template_id=applied_id, name="t", steps=["s"],
        parent_template_id="tdd", solution_path={},
        parent_skill_ids=["tdd"],
    )
    for _ in range(3):
        registry.update_path_advantage(applied_id, path_advantage=-0.3, decision="alert")
    applied = registry.get_applied_template(applied_id)
    assert applied.quality_level == "quarantined"
    assert applied.consecutive_negative == 3


def test_c_level_penalty_in_retrieve_applied():
    """P5: retrieve_applied 排序时 A/B/S 优先，C 级仅填充（不抢占高等级名额）。"""
    registry = ProcessTemplateRegistry()
    with patch.object(registry, "_persist_applied_template"):
        # 注册 S/A/B/C 各一个，verify_count 相同
        for ql, tid in [("C", "APP-c1"), ("B", "APP-b1"), ("A", "APP-a1"), ("S", "APP-s1")]:
            registry.register_applied_from_session(
                template_id=tid, name=tid, steps=["s"],
                parent_template_id="tdd", solution_path={},
                parent_skill_ids=["tdd"], quality_level=ql,
            )
            registry.get_applied(tid).verify_count = 5

        # top_k=4: 应按 S > A > B > C 排序
        results = registry.retrieve_applied("dev", top_k=4)
        order = [r["quality_level"] for r in results]
        assert order == ["S", "A", "B", "C"], f"C级应排最后，实际: {order}"

        # top_k=2: C 级不应出现（被 S/A 挤出）
        results2 = registry.retrieve_applied("dev", top_k=2)
        qls = [r["quality_level"] for r in results2]
        assert "C" not in qls, f"top_k=2时C级不应出现，实际: {qls}"

        # top_k=3: C 级仍不应出现（被 S/A/B 挤出）
        results3 = registry.retrieve_applied("dev", top_k=3)
        qls3 = [r["quality_level"] for r in results3]
        assert "C" not in qls3, f"top_k=3时C级不应出现，实际: {qls3}"

    # 高等级不足时，C 级作为填充出现
    registry2 = ProcessTemplateRegistry()
    with patch.object(registry2, "_persist_applied_template"):
        for ql, tid in [("C", "APP-c2"), ("A", "APP-a2")]:
            registry2.register_applied_from_session(
                template_id=tid, name=tid, steps=["s"],
                parent_template_id="tdd", solution_path={},
                parent_skill_ids=["tdd"], quality_level=ql,
            )
            registry2.get_applied(tid).verify_count = 3
        results4 = registry2.retrieve_applied("dev", top_k=2)
        order4 = [r["quality_level"] for r in results4]
        assert order4 == ["A", "C"], f"高等级不足时C应填充，实际: {order4}"
