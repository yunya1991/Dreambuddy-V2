"""skill-indexer 构建器 MVP 测试 — TDD RED 阶段

扫描 SKILL.md frontmatter → 生成 registry.json + dep-graph.json + drift-report.json + conflict-report.json
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─────────────────────────────── 1. 模块可导入（RED 起手） ───────────────────────────────

def test_module_importable():
    """模块可导入（RED 起手已过，现断言导入成功）。"""
    import skill_indexer  # noqa: F401
    assert hasattr(skill_indexer, "scan_skills")
    assert hasattr(skill_indexer, "build")


# ─────────────────────────────── 2. scan_skills：扫描 + 解析 ───────────────────────────────

def test_scan_empty_dir_returns_empty(tmp_path):
    from skill_indexer import scan_skills
    assert scan_skills([tmp_path]) == []


def test_scan_single_skill_extracts_frontmatter(tmp_path):
    skill_dir = tmp_path / "dream-demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: dream-demo\n"
        "description: A demo skill\n"
        "version: 1.0.0\n"
        "status: active\n"
        "category: orchestration\n"
        "triggers: [demo, test]\n"
        "depends_on: [bsk]\n"
        "---\n"
        "# Demo\n"
    )
    from skill_indexer import scan_skills
    entries = scan_skills([tmp_path])
    assert len(entries) == 1
    e = entries[0]
    assert e.name == "dream-demo"
    assert e.version == "1.0.0"
    assert e.status == "active"
    assert e.category == "orchestration"
    assert e.triggers == ["demo", "test"]
    assert e.depends_on == ["bsk"]


def test_scan_missing_frontmatter_fail_open(tmp_path):
    """无 frontmatter → FAIL-OPEN，记录 parse_error，不阻塞。"""
    skill_dir = tmp_path / "no-fm"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# No frontmatter here\n")
    from skill_indexer import scan_skills
    entries = scan_skills([tmp_path])
    assert len(entries) == 1
    assert entries[0].parse_error is not None
    assert entries[0].name == "no-fm"  # 至少从目录名推断


def test_scan_invalid_yaml_fail_open(tmp_path):
    """非法 YAML frontmatter → FAIL-OPEN。"""
    skill_dir = tmp_path / "bad-yaml"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: bad\n"
        "triggers: [unclosed\n"  # 非法 YAML
        "---\n"
        "# Bad\n"
    )
    from skill_indexer import scan_skills
    entries = scan_skills([tmp_path])
    assert len(entries) == 1
    assert entries[0].parse_error is not None


def test_scan_default_fields(tmp_path):
    """缺少可选字段 → 默认值。"""
    skill_dir = tmp_path / "minimal"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: minimal\n"
        "description: minimal skill\n"
        "version: 0.1.0\n"
        "---\n"
        "# Minimal\n"
    )
    from skill_indexer import scan_skills
    entries = scan_skills([tmp_path])
    e = entries[0]
    assert e.status == "active"
    assert e.category == "uncategorized"
    assert e.triggers == []
    assert e.depends_on == []
    assert e.provides == []
    assert e.cognitive_links == []


# ─────────────────────────────── 3. build_registry ───────────────────────────────

def test_build_registry_structure(tmp_path):
    skill_dir = tmp_path / "dream-reg"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-reg\ndescription: reg test\nversion: 2.0.0\n"
        "triggers: [reg]\ndepends_on: [bsk]\n---\n# Reg\n"
    )
    from skill_indexer import scan_skills, build_registry
    entries = scan_skills([tmp_path])
    registry = build_registry(entries)
    assert registry["schema_version"] == "1.0"
    assert registry["total_count"] == 1
    assert registry["skills"][0]["name"] == "dream-reg"
    assert "content_hash" in registry["skills"][0]


# ─────────────────────────────── 4. build_dep_graph ───────────────────────────────

def test_build_dep_graph_structure(tmp_path):
    a = tmp_path / "skill-a"
    a.mkdir()
    (a / "SKILL.md").write_text("---\nname: skill-a\ndescription: a\nversion: 1.0.0\ndepends_on: [skill-b]\n---\n")
    b = tmp_path / "skill-b"
    b.mkdir()
    (b / "SKILL.md").write_text("---\nname: skill-b\ndescription: b\nversion: 1.0.0\ndepends_on: []\n---\n")
    from skill_indexer import scan_skills, build_dep_graph
    entries = scan_skills([tmp_path])
    graph = build_dep_graph(entries)
    assert graph["schema_version"] == "1.0"
    assert any(n["id"] == "skill-a" for n in graph["nodes"])
    edges = graph["edges"]
    assert any(e["from"] == "skill-a" and e["to"] == "skill-b" for e in edges)


# ─────────────────────────────── 5. detect_drift ───────────────────────────────

def test_detect_drift_missing_location(tmp_path):
    """只在 .trae/skills 存在，1-ARCHITECTURE/skills 缺失 → drifted。"""
    trae = tmp_path / ".trae" / "skills" / "dream-only-trae"
    trae.mkdir(parents=True)
    (trae / "SKILL.md").write_text("---\nname: dream-only-trae\ndescription: x\nversion: 1.0.0\n---\n")
    from skill_indexer import scan_skills, detect_drift
    entries = scan_skills([tmp_path])
    report = detect_drift(entries)
    assert report["schema_version"] == "1.0"
    assert report["total_drifted"] >= 1
    drifted_names = {d["name"] for d in report["drifted"]}
    assert "dream-only-trae" in drifted_names


# ─────────────────────────────── 6. detect_conflicts ───────────────────────────────

def test_detect_conflicts_shared_trigger(tmp_path):
    a = tmp_path / "skill-a"
    a.mkdir()
    (a / "SKILL.md").write_text("---\nname: skill-a\ndescription: a\nversion: 1.0.0\ntriggers: [深度调研]\n---\n")
    b = tmp_path / "skill-b"
    b.mkdir()
    (b / "SKILL.md").write_text("---\nname: skill-b\ndescription: b\nversion: 1.0.0\ntriggers: [深度调研, 市场调研]\n---\n")
    from skill_indexer import scan_skills, detect_conflicts
    entries = scan_skills([tmp_path])
    report = detect_conflicts(entries)
    assert report["schema_version"] == "1.0"
    assert report["total_conflicts"] >= 1
    conflict = report["conflicts"][0]
    assert conflict["trigger"] == "深度调研"
    assert set(conflict["skills"]) == {"skill-a", "skill-b"}


def test_detect_conflicts_no_conflict(tmp_path):
    a = tmp_path / "skill-a"
    a.mkdir()
    (a / "SKILL.md").write_text("---\nname: skill-a\ndescription: a\nversion: 1.0.0\ntriggers: [a-trigger]\n---\n")
    b = tmp_path / "skill-b"
    b.mkdir()
    (b / "SKILL.md").write_text("---\nname: skill-b\ndescription: b\nversion: 1.0.0\ntriggers: [b-trigger]\n---\n")
    from skill_indexer import scan_skills, detect_conflicts
    entries = scan_skills([tmp_path])
    report = detect_conflicts(entries)
    assert report["total_conflicts"] == 0
    assert report["conflicts"] == []


# ─────────────────────────────── 7. build 一键生成 ───────────────────────────────

def test_build_writes_4_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    sd = src / "dream-build"
    sd.mkdir()
    (sd / "SKILL.md").write_text("---\nname: dream-build\ndescription: build test\nversion: 1.0.0\ntriggers: [build]\n---\n")
    out = tmp_path / "out"
    out.mkdir()
    from skill_indexer import build
    result = build([src], out)
    assert (out / "registry.json").exists()
    assert (out / "dep-graph.json").exists()
    assert (out / "drift-report.json").exists()
    assert (out / "conflict-report.json").exists()
    assert result["registry"]["total_count"] == 1


# ─────────────────────────────── 8. P2-2 CLI 入口 ───────────────────────────────

import os
import subprocess
import sys

_SKILL_INDEXER = str(Path(__file__).parent / "skill_indexer.py")


def test_cli_build_writes_files(tmp_path):
    """CLI build 子命令应写入 4 个 JSON 文件。"""
    src = tmp_path / "src"
    src.mkdir()
    sd = src / "dream-cli-build"
    sd.mkdir()
    (sd / "SKILL.md").write_text(
        "---\nname: dream-cli-build\ndescription: cli build test\nversion: 1.0.0\ntriggers: [cli]\n---\n"
    )
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, _SKILL_INDEXER, "build", "--roots", str(src), "--output", str(out)],
        check=True, capture_output=True,
    )
    assert (out / "registry.json").exists()
    assert (out / "dep-graph.json").exists()
    assert (out / "drift-report.json").exists()
    assert (out / "conflict-report.json").exists()


def test_cli_query_by_trigger(tmp_path):
    """CLI query --trigger 应输出匹配 SKILL 的 JSON。"""
    src = tmp_path / "src"
    src.mkdir()
    sd = src / "dream-query"
    sd.mkdir()
    (sd / "SKILL.md").write_text(
        "---\nname: dream-query\ndescription: query test\nversion: 1.0.0\ntriggers: [magic]\n---\n"
    )
    proc = subprocess.run(
        [sys.executable, _SKILL_INDEXER, "query", "--trigger", "magic", "--roots", str(src)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)
    names = {s["name"] for s in data.get("skills", data) if isinstance(s, dict)}
    # 兼容 list 或 dict 输出
    if isinstance(data, list):
        names = {s["name"] for s in data}
    assert "dream-query" in names


# ─────────────────────────────── 9. P2-3 validate 子命令 ───────────────────────────────

def test_validate_valid_skill(tmp_path):
    skill_dir = tmp_path / "dream-valid"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-valid\ndescription: valid\nversion: 1.0.0\nstatus: active\ntriggers: [v]\n---\n"
    )
    from skill_indexer import validate
    result = validate(skill_dir)
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_missing_name(tmp_path):
    skill_dir = tmp_path / "dream-no-name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: no name\nversion: 1.0.0\n---\n"
    )
    from skill_indexer import validate
    result = validate(skill_dir)
    assert result["valid"] is False
    assert any("name" in e for e in result["errors"])


def test_validate_invalid_status(tmp_path):
    skill_dir = tmp_path / "dream-bad-status"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-bad-status\ndescription: x\nversion: 1.0.0\nstatus: weird\ntriggers: [s]\n---\n"
    )
    from skill_indexer import validate
    result = validate(skill_dir)
    assert result["valid"] is False
    assert any("status" in e for e in result["errors"])


def test_validate_invalid_version_warning(tmp_path):
    skill_dir = tmp_path / "dream-bad-ver"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-bad-ver\ndescription: x\nversion: not-semver\nstatus: active\ntriggers: [v]\n---\n"
    )
    from skill_indexer import validate
    result = validate(skill_dir)
    assert result["valid"] is True  # 版本不合法只 warning
    assert any("version" in w for w in result["warnings"])


def test_validate_drift_warning(tmp_path):
    """只在 .trae/skills 存在，1-ARCHITECTURE/skills 缺失 → drift warning。"""
    trae = tmp_path / ".trae" / "skills" / "dream-drift"
    trae.mkdir(parents=True)
    (trae / "SKILL.md").write_text(
        "---\nname: dream-drift\ndescription: drift\nversion: 1.0.0\nstatus: active\ntriggers: [d]\n---\n"
    )
    from skill_indexer import validate
    result = validate(trae)
    assert result["valid"] is True  # drift 只 warning
    assert any("drift" in w.lower() for w in result["warnings"])


# ─────────────────────────────── 10. P3-1 override.yaml ───────────────────────────────

def test_override_yaml_merges_fields(tmp_path):
    """同目录存在 skill.override.yaml → override_fields 被合并到 SkillEntry。"""
    skill_dir = tmp_path / "dream-override"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-override\ndescription: override test\nversion: 1.0.0\nstatus: shadow\n---\n"
    )
    (skill_dir / "skill.override.yaml").write_text(
        "id: skl-dream-override-001\n"
        "locations:\n"
        "  - path: 1-ARCHITECTURE/skills/dream-override/SKILL.md\n"
        "    role: project-index\n"
        "lifecycle:\n"
        "  proposed_at: '2026-01-01'\n"
        "  shadow_verified: true\n"
        "  activated_at: null\n"
        "  deprecation_scheduled: null\n"
        "conflicts_with: [other-skill]\n"
        "replaces: [old-skill]\n"
        "replaced_by: null\n"
        "integrity_hash: null\n"
    )
    from skill_indexer import scan_skills
    entries = scan_skills([tmp_path])
    assert len(entries) == 1
    e = entries[0]
    assert e.override_fields is not None
    assert e.override_fields["id"] == "skl-dream-override-001"
    assert e.override_fields["conflicts_with"] == ["other-skill"]
    assert e.override_fields["replaces"] == ["old-skill"]
    assert e.override_fields["replaced_by"] is None


def test_no_override_yaml_defaults(tmp_path):
    """不存在 skill.override.yaml → override_fields 为 None。"""
    skill_dir = tmp_path / "dream-no-override"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-no-override\ndescription: no override\nversion: 1.0.0\n---\n"
    )
    from skill_indexer import scan_skills
    entries = scan_skills([tmp_path])
    assert entries[0].override_fields is None


# ─────────────────────────────── 11. P3-1 生命周期状态机 ───────────────────────────────

def test_lifecycle_valid_transition():
    from skill_indexer import lifecycle_transition
    r = lifecycle_transition("proposed", "shadow", ["review-passed"])
    assert r["ok"] is True
    assert r["from"] == "proposed"
    assert r["to"] == "shadow"
    assert r["evidence"] == ["review-passed"]

    # 任意状态 → archived 合法
    r2 = lifecycle_transition("active", "archived", ["force-cleanup"])
    assert r2["ok"] is True


def test_lifecycle_invalid_transition():
    from skill_indexer import lifecycle_transition
    r = lifecycle_transition("active", "proposed", [])
    assert r["ok"] is False
    assert "error" in r

    r2 = lifecycle_transition("proposed", "active", [])
    assert r2["ok"] is False


# ─────────────────────────────── 12. P3-2 认知 hooks ───────────────────────────────

def test_recall_hook_matches_triggers():
    from skill_indexer import recall_hook, SkillEntry
    entries = [
        SkillEntry(name="dream-research", description="深度调研 skill", category="research",
                   triggers=["调研", "市场调研"]),
        SkillEntry(name="dream-code", description="代码 skill", category="coding",
                   triggers=["写代码"]),
    ]
    result = recall_hook("我要做市场调研", entries)
    assert isinstance(result, list)
    assert len(result) >= 1
    # dream-research 应排第一
    assert result[0]["name"] == "dream-research"


def test_record_hook_returns_link():
    from skill_indexer import record_hook
    r = record_hook("skill-001", "VM-123")
    assert r["skill_id"] == "skill-001"
    # P0 升级：认知系统可用时返回真实 VM-id（以 VM- 开头），不可用时回显输入
    assert r["memory_id"].startswith("VM-")
    assert r["linked"] is True


def test_verify_hook_suggests_shadow_to_active():
    from skill_indexer import verify_hook, SkillEntry
    # 满足升级条件：confidence>=0.6 且 apply_count>=1
    entries = [
        SkillEntry(name="skill-001", status="shadow", confidence=0.65, apply_count=2),
        SkillEntry(name="skill-002", status="active"),
        SkillEntry(name="skill-003", status="shadow", confidence=0.3, apply_count=0),
    ]
    r = verify_hook("skill-001", True, entries)
    assert r["skill_id"] == "skill-001"
    assert r["success"] is True
    assert r["suggested_transition"] == "shadow→active"

    # 非 shadow 状态不建议升级
    r2 = verify_hook("skill-002", True, entries)
    assert r2["suggested_transition"] is None

    # success=False 不建议升级
    r3 = verify_hook("skill-001", False, entries)
    assert r3["suggested_transition"] is None

    # 不满足条件（confidence<0.6 或 apply_count<1）→ pending
    r4 = verify_hook("skill-003", True, entries)
    assert r4["suggested_transition"] is not None
    assert "pending" in r4["suggested_transition"]
