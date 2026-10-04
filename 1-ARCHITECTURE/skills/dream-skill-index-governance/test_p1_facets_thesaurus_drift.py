"""P1 分面分类 + 权威词表 + 漂移修复 测试 — TDD RED 阶段

覆盖：
1. skill_facets — facets 字段推断 + SkillEntry 集成
2. skill_thesaurus — 权威词表加载 + trigger 归一化 + 冲突消歧
3. detect_drift 改进 — 已知 SKILL 根目录不算漂移
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─────────────────────────────── 1. skill_facets ───────────────────────────────

def test_facets_module_importable():
    import skill_facets
    assert hasattr(skill_facets, "infer_facets")
    assert hasattr(skill_facets, "FACET_KEYS")


def test_infer_facets_from_category_trading():
    """category=trading → domain=trading。"""
    import skill_facets
    f = skill_facets.infer_facets(category="trading", triggers=["回测", "策略"])
    assert f["domain"] == "trading"


def test_infer_facets_from_path_memory():
    """路径含 MEMORY → domain=memory。"""
    import skill_facets
    p = Path("/repo/4-MEMORY/skills/dream-foo")
    f = skill_facets.infer_facets(category="orchestration", triggers=[], path=p)
    assert f["domain"] == "memory"


def test_infer_facets_task_type_from_triggers():
    """triggers 含 '调研' → task_type=research。"""
    import skill_facets
    f = skill_facets.infer_facets(category="orchestration", triggers=["深度调研", "市场调研"])
    assert f["task_type"] == "research"


def test_infer_facets_defaults():
    """无信息时返回默认 facets。"""
    import skill_facets
    f = skill_facets.infer_facets(category="uncategorized", triggers=[])
    assert f["domain"] == "uncategorized"
    assert f["task_type"] == "general"
    assert f["potency"] == "unipotent"
    assert f["resource_cost"] == "medium"
    assert f["execution_mode"] == "auto"


def test_skillentry_has_facets_field(tmp_path):
    """SkillEntry 应包含 facets 字段。"""
    from skill_indexer import SkillEntry
    e = SkillEntry(name="x", facets={"domain": "trading"})
    assert e.facets == {"domain": "trading"}


def test_scan_parses_facets_from_frontmatter(tmp_path):
    """SKILL.md frontmatter 含 facets → 被解析。"""
    skill_dir = tmp_path / "dream-f"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: dream-f\n"
        "description: f\n"
        "version: 1.0.0\n"
        "category: trading\n"
        "facets:\n"
        "  domain: trading\n"
        "  task_type: research\n"
        "---\n"
    )
    from skill_indexer import scan_skills
    entries = scan_skills([tmp_path])
    assert entries[0].facets.get("domain") == "trading"
    assert entries[0].facets.get("task_type") == "research"


# ─────────────────────────────── 2. skill_thesaurus ───────────────────────────────

def test_thesaurus_module_importable():
    import skill_thesaurus
    assert hasattr(skill_thesaurus, "load_thesaurus")
    assert hasattr(skill_thesaurus, "normalize_trigger")
    assert hasattr(skill_thesaurus, "disambiguate")


def test_thesaurus_normalize_synonym(tmp_path):
    """同义词归一化：市场调研 → 深度调研。"""
    import skill_thesaurus
    th = skill_thesaurus.load_thesaurus(Path(__file__).parent / "skill_thesaurus.yaml")
    assert th is not None
    norm = skill_thesaurus.normalize_trigger("市场调研", th)
    assert norm == "深度调研"


def test_thesaurus_disambiguate_by_domain(tmp_path):
    """冲突 trigger 'analysis' 按 domain 消歧。"""
    import skill_thesaurus
    th = skill_thesaurus.load_thesaurus(Path(__file__).parent / "skill_thesaurus.yaml")
    # trading domain → dream-data-analysis
    r = skill_thesaurus.disambiguate("analysis", "trading", th)
    assert r == "dream-data-analysis"
    # intelligence domain → dream-intelligence-analysis
    r2 = skill_thesaurus.disambiguate("analysis", "intelligence", th)
    assert r2 == "dream-intelligence-analysis"


def test_thesaurus_unknown_trigger_passthrough(tmp_path):
    """不在词表中的 trigger 原样返回。"""
    import skill_thesaurus
    th = skill_thesaurus.load_thesaurus(Path(__file__).parent / "skill_thesaurus.yaml")
    assert skill_thesaurus.normalize_trigger("xyz-not-in-thesaurus", th) == "xyz-not-in-thesaurus"
    assert skill_thesaurus.disambiguate("xyz", "trading", th) is None


# ─────────────────────────────── 3. detect_drift 改进 ───────────────────────────────

def test_detect_drift_known_root_not_drifted(tmp_path):
    """SKILL 在已知 SKILL 根目录（非双位置）→ 不算漂移。"""
    from skill_indexer import detect_drift, SkillEntry

    # 模拟一个在 6-TRADING/skills 的 SKILL（unknown role 但路径是已知根）
    e = SkillEntry(
        name="dream-trading-only",
        location_role="unknown",
        path=tmp_path / "6-TRADING" / "skills" / "dream-trading-only" / "SKILL.md",
    )
    report = detect_drift([e])
    # 已知根目录下的 SKILL 不应被标记为漂移
    names = {d["name"] for d in report["drifted"]}
    assert "dream-trading-only" not in names


def test_detect_drift_dual_missing_still_drifted(tmp_path):
    """SKILL 只在 trae-entry 不在 project-index → 仍算漂移。"""
    from skill_indexer import detect_drift, SkillEntry

    e = SkillEntry(
        name="dream-only-trae",
        location_role="trae-entry",
        path=tmp_path / ".trae" / "skills" / "dream-only-trae" / "SKILL.md",
    )
    report = detect_drift([e])
    names = {d["name"] for d in report["drifted"]}
    assert "dream-only-trae" in names


def test_detect_drift_dual_present_not_drifted(tmp_path):
    """双位置都有 → 不漂移。"""
    from skill_indexer import detect_drift, SkillEntry

    e1 = SkillEntry(name="dream-dual", location_role="trae-entry",
                    path=tmp_path / ".trae" / "skills" / "dream-dual" / "SKILL.md")
    e2 = SkillEntry(name="dream-dual", location_role="project-index",
                    path=tmp_path / "1-ARCHITECTURE" / "skills" / "dream-dual" / "SKILL.md")
    report = detect_drift([e1, e2])
    assert report["total_drifted"] == 0
