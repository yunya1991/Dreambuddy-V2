"""P2 SKILL创建自动化管道 测试 — TDD RED 阶段

覆盖：
1. skill_candidate_miner — 从认知记忆挖掘 SKILL 候选草稿
2. skill_operon — SKILL 套件（操纵子）协同加载
3. skill_affinity_maturator — 亲和力成熟（基于usage调整triggers/建议deprecated）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─────────────────────────────── 1. skill_candidate_miner ───────────────────────────────

def test_candidate_miner_module_importable():
    import skill_candidate_miner
    assert hasattr(skill_candidate_miner, "mine_candidates")


def test_mine_candidates_from_memories(tmp_path):
    """从认知记忆中挖掘重复出现的 task pattern → SKILL 候选。"""
    import skill_candidate_miner as scm

    # 模拟认知记忆（含 hermes反思 + SKILL 相关内容）
    memories = [
        {"id": "VM-1", "content": "[hermes反思] TDD开发流程被复用，建议形成SKILL", "tags": ["hermes反思", "SKILL"]},
        {"id": "VM-2", "content": "[hermes反思] TDD红绿重构流程可复用", "tags": ["hermes反思", "SKILL"]},
        {"id": "VM-3", "content": "[hermes反思] TDD开发流程第3次复用", "tags": ["hermes反思"]},
        {"id": "VM-4", "content": "bug修复5why分析流程", "tags": ["bugfix"]},
    ]
    db_path = tmp_path / "mem.db"
    scm._write_test_db(db_path, memories)

    candidates = scm.mine_candidates(db_path=db_path, min_occurrences=2)
    assert len(candidates) >= 1
    # TDD pattern 出现3次 → 应被挖掘
    tdd_cands = [c for c in candidates if "tdd" in c["name"].lower() or "tdd" in c["description"].lower()]
    assert len(tdd_cands) >= 1
    assert tdd_cands[0]["evidence_count"] >= 2


def test_mine_candidates_below_threshold_ignored(tmp_path):
    """出现次数 < min_occurrences 的 pattern 不被挖掘。"""
    import skill_candidate_miner as scm

    memories = [
        {"id": "VM-1", "content": "unique pattern xyz", "tags": ["hermes反思"]},
    ]
    db_path = tmp_path / "mem.db"
    scm._write_test_db(db_path, memories)

    candidates = scm.mine_candidates(db_path=db_path, min_occurrences=3)
    assert candidates == []


def test_candidate_has_skill_fields(tmp_path):
    """候选应包含生成 SKILL 所需的字段。"""
    import skill_candidate_miner as scm

    memories = [
        {"id": f"VM-{i}", "content": f"[hermes反思] 回测验证流程可复用 #{i}", "tags": ["hermes反思", "SKILL"]}
        for i in range(4)
    ]
    db_path = tmp_path / "mem.db"
    scm._write_test_db(db_path, memories)

    candidates = scm.mine_candidates(db_path=db_path, min_occurrences=2)
    if candidates:
        c = candidates[0]
        assert "name" in c
        assert "description" in c
        assert "triggers" in c
        assert "category" in c
        assert "evidence_count" in c
        assert "source_memories" in c


def test_generate_skill_draft(tmp_path):
    """generate_skill_draft 从候选生成 SKILL.md frontmatter 草稿。"""
    import skill_candidate_miner as scm

    candidate = {
        "name": "dream-demo-skill",
        "description": "A demo skill for testing",
        "triggers": ["demo", "test"],
        "category": "tooling",
        "evidence_count": 3,
        "source_memories": ["VM-1", "VM-2"],
    }
    draft = scm.generate_skill_draft(candidate)
    assert "name: dream-demo-skill" in draft
    assert "status: proposed" in draft
    assert "triggers:" in draft
    assert "evidence_count: 3" in draft


# ─────────────────────────────── 2. skill_operon ───────────────────────────────

def test_operon_module_importable():
    import skill_operon
    assert hasattr(skill_operon, "load_operons")
    assert hasattr(skill_operon, "expand_operon")


def test_load_operons_from_yaml():
    """从 skill_operon.yaml 加载套件定义。"""
    import skill_operon
    ops = skill_operon.load_operons(Path(__file__).parent / "skill_operon.yaml")
    assert ops is not None
    assert len(ops) > 0


def test_expand_operon_returns_members(tmp_path):
    """expand_operon(skill) 返回该 SKILL 所在套件的所有成员。"""
    import skill_operon

    ops = {
        "tdd-suite": {
            "description": "TDD 开发套件",
            "members": ["dream-tdd-dev-workflow", "tee-red-green-progress", "test-driven-development"],
            "trigger": "TDD",
        }
    }
    members = skill_operon.expand_operon("dream-tdd-dev-workflow", ops)
    assert "dream-tdd-dev-workflow" in members
    assert "tee-red-green-progress" in members
    assert "test-driven-development" in members


def test_expand_operon_unknown_skill_returns_self(tmp_path):
    """不在任何套件中的 SKILL → 返回 [自身]。"""
    import skill_operon
    members = skill_operon.expand_operon("unknown-skill", {})
    assert members == ["unknown-skill"]


def test_get_operon_for_skill(tmp_path):
    """get_operon_for_skill 返回 SKILL 所在套件名。"""
    import skill_operon
    ops = {
        "research-suite": {"members": ["dream-research-workflow", "dream-strategy-research"]}
    }
    assert skill_operon.get_operon_for_skill("dream-research-workflow", ops) == "research-suite"
    assert skill_operon.get_operon_for_skill("dream-other", ops) is None


# ─────────────────────────────── 3. skill_affinity_maturator ───────────────────────────────

def test_affinity_module_importable():
    import skill_affinity_maturator
    assert hasattr(skill_affinity_maturator, "analyze_affinity")


def test_analyze_affinity_low_success_suggests_deprecate(tmp_path):
    """低成功率 + 高调用 → 建议 deprecated 或 trigger 优化。"""
    import skill_affinity_maturator as sam
    from skill_circulation_stats import record_invocation

    sp = tmp_path / "stats.json"
    for _ in range(6):
        record_invocation("dream-bad", success=False, stats_path=sp)
    record_invocation("dream-bad", success=True, stats_path=sp)

    actions = sam.analyze_affinity(stats_path=sp)
    bad = [a for a in actions if a["skill"] == "dream-bad"]
    assert len(bad) >= 1
    assert bad[0]["action"] in ("suggest_deprecate", "refine_triggers")


def test_analyze_affinity_high_success_suggests_activate(tmp_path):
    """高成功率 + 高调用 → 建议 activate（shadow→active）。"""
    import skill_affinity_maturator as sam
    from skill_circulation_stats import record_invocation

    sp = tmp_path / "stats.json"
    for _ in range(5):
        record_invocation("dream-good", success=True, stats_path=sp)

    actions = sam.analyze_affinity(stats_path=sp)
    good = [a for a in actions if a["skill"] == "dream-good"]
    assert len(good) >= 1
    assert good[0]["action"] == "suggest_activate"


def test_analyze_affinity_no_stats_returns_empty(tmp_path):
    """无统计数据 → 空列表。"""
    import skill_affinity_maturator as sam
    sp = tmp_path / "empty.json"
    actions = sam.analyze_affinity(stats_path=sp)
    assert actions == []
