"""P0 认知闭环 + 生命周期写回 测试 — TDD RED 阶段

覆盖：
1. skill_lifecycle_writer — 实际写回 frontmatter status/updated/cognitive_links
2. skill_circulation_stats — 调用统计驱动生命周期
3. skill_index_generator — 从 registry.json 生成 SKILL_INDEX.md
4. record_hook/verify_hook — 接入认知系统（get_cle）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─────────────────────────────── 1. skill_lifecycle_writer ───────────────────────────────

def test_lifecycle_writer_module_importable():
    """模块可导入。"""
    import skill_lifecycle_writer  # noqa: F401
    assert hasattr(skill_lifecycle_writer, "write_lifecycle")


def test_lifecycle_writer_writes_status_back(tmp_path):
    """write_lifecycle 应实际修改 SKILL.md frontmatter 的 status。"""
    import skill_lifecycle_writer as lcw

    skill_dir = tmp_path / "dream-lcw"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: dream-lcw\n"
        "description: lcw test\n"
        "version: 1.0.0\n"
        "status: proposed\n"
        "triggers: [lcw]\n"
        "---\n"
        "# LCW\n"
    )
    r = lcw.write_lifecycle(skill_dir, "shadow", evidence=["VM-001"])
    assert r["ok"] is True
    assert r["from"] == "proposed"
    assert r["to"] == "shadow"
    assert r["written"] is True

    # 实际读回验证
    content = (skill_dir / "SKILL.md").read_text()
    assert "status: shadow" in content
    assert "updated:" in content
    assert "VM-001" in content  # cognitive_links 包含 evidence


def test_lifecycle_writer_invalid_transition_fails(tmp_path):
    """非法转换（active→proposed）→ ok=False，文件不改。"""
    import skill_lifecycle_writer as lcw

    skill_dir = tmp_path / "dream-bad"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-bad\ndescription: x\nversion: 1.0.0\nstatus: active\n---\n"
    )
    r = lcw.write_lifecycle(skill_dir, "proposed", evidence=[])
    assert r["ok"] is False
    # 文件未改
    content = (skill_dir / "SKILL.md").read_text()
    assert "status: active" in content


def test_lifecycle_writer_preserves_body(tmp_path):
    """写回 status 后，body 内容保持不变。"""
    import skill_lifecycle_writer as lcw

    skill_dir = tmp_path / "dream-preserve"
    skill_dir.mkdir()
    body = "# Body Title\n\nSome **markdown** content here.\n"
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-preserve\ndescription: x\nversion: 1.0.0\nstatus: shadow\n---\n" + body
    )
    r = lcw.write_lifecycle(skill_dir, "active", evidence=["VM-002"])
    assert r["ok"] is True
    content = (skill_dir / "SKILL.md").read_text()
    assert body in content


def test_lifecycle_writer_appends_cognitive_links(tmp_path):
    """已有 cognitive_links 时，追加不覆盖。"""
    import skill_lifecycle_writer as lcw

    skill_dir = tmp_path / "dream-links"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: dream-links\n"
        "description: x\n"
        "version: 1.0.0\n"
        "status: proposed\n"
        "cognitive_links: [VM-OLD]\n"
        "---\n"
    )
    r = lcw.write_lifecycle(skill_dir, "shadow", evidence=["VM-NEW"])
    assert r["ok"] is True
    content = (skill_dir / "SKILL.md").read_text()
    assert "VM-OLD" in content
    assert "VM-NEW" in content


# ─────────────────────────────── 2. skill_circulation_stats ───────────────────────────────

def test_circulation_module_importable():
    import skill_circulation_stats  # noqa: F401
    assert hasattr(skill_circulation_stats, "record_invocation")


def test_circulation_record_and_get(tmp_path):
    import skill_circulation_stats as cs

    stats_path = tmp_path / "skill_circulation.json"
    cs.record_invocation("dream-x", success=True, stats_path=stats_path)
    cs.record_invocation("dream-x", success=True, stats_path=stats_path)
    cs.record_invocation("dream-x", success=False, stats_path=stats_path)

    s = cs.get_stats("dream-x", stats_path=stats_path)
    assert s["invocation_count"] == 3
    assert s["success_count"] == 2
    assert s["failure_count"] == 1
    assert abs(s["success_rate"] - 0.6667) < 0.001


def test_circulation_should_activate(tmp_path):
    """invocation≥3 且 success_rate≥0.6 → should_activate True。"""
    import skill_circulation_stats as cs

    stats_path = tmp_path / "skill_circulation.json"
    for _ in range(3):
        cs.record_invocation("dream-good", success=True, stats_path=stats_path)
    assert cs.should_activate("dream-good", stats_path=stats_path) is True

    cs.record_invocation("dream-bad", success=False, stats_path=stats_path)
    cs.record_invocation("dream-bad", success=False, stats_path=stats_path)
    cs.record_invocation("dream-bad", success=False, stats_path=stats_path)
    assert cs.should_activate("dream-bad", stats_path=stats_path) is False


def test_circulation_should_deprecate(tmp_path, monkeypatch):
    """90 天零调用 → should_deprecate True。"""
    import skill_circulation_stats as cs

    stats_path = tmp_path / "skill_circulation.json"
    # 手动写一个 100 天前的统计
    from datetime import datetime, timedelta, timezone
    old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    stats_path.write_text(json.dumps({
        "dream-old": {
            "invocation_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "last_invoked_at": old_date,
        }
    }))
    assert cs.should_deprecate("dream-old", stats_path=stats_path, days=90) is True

    # 刚调用过的不应 deprecate
    cs.record_invocation("dream-fresh", success=True, stats_path=stats_path)
    assert cs.should_deprecate("dream-fresh", stats_path=stats_path, days=90) is False


def test_circulation_fail_open(tmp_path):
    """stats_path 目录不存在 → mkdir 创建成功，不崩溃；记录被保存。"""
    import skill_circulation_stats as cs

    stats_path = tmp_path / "nonexistent" / "deep" / "stats.json"
    r = cs.record_invocation("dream-x", success=True, stats_path=stats_path)
    assert r is not None  # 不抛异常
    s = cs.get_stats("dream-x", stats_path=stats_path)
    assert s["invocation_count"] == 1  # 目录被自动创建，记录已保存


# ─────────────────────────────── 3. skill_index_generator ───────────────────────────────

def test_index_generator_module_importable():
    import skill_index_generator  # noqa: F401
    assert hasattr(skill_index_generator, "generate_skill_index")


def test_index_generator_produces_markdown(tmp_path):
    """generate_skill_index 从 registry.json 生成 SKILL_INDEX.md。"""
    import skill_index_generator as sig

    registry = {
        "schema_version": "1.0",
        "total_count": 2,
        "skills": [
            {"name": "dream-a", "description": "A skill", "category": "orchestration",
             "status": "active", "version": "1.0.0"},
            {"name": "dream-b", "description": "B skill", "category": "trading",
             "status": "shadow", "version": "0.1.0"},
        ],
    }
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(json.dumps(registry, ensure_ascii=False))

    out_path = tmp_path / "SKILL_INDEX.md"
    sig.generate_skill_index(reg_path, out_path)

    assert out_path.exists()
    content = out_path.read_text()
    assert "dream-a" in content
    assert "dream-b" in content
    assert "orchestration" in content
    assert "trading" in content
    assert "2" in content  # 总数


def test_index_generator_empty_registry(tmp_path):
    import skill_index_generator as sig

    registry = {"schema_version": "1.0", "total_count": 0, "skills": []}
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(json.dumps(registry))
    out_path = tmp_path / "SKILL_INDEX.md"
    sig.generate_skill_index(reg_path, out_path)
    content = out_path.read_text()
    assert "0" in content


# ─────────────────────────────── 4. 认知 hooks 接入 ───────────────────────────────

def test_record_hook_writes_links_without_duplicate_record(tmp_path):
    """record_hook 不重复调用 cle.record，直接将给定 memory_id 写入 SKILL.md cognitive_links。"""
    import skill_indexer

    skill_dir = tmp_path / "dream-record"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-record\ndescription: x\nversion: 1.0.0\nstatus: active\ncognitive_links: []\n---\n"
    )

    # record_hook 由认知系统 record 流程调用，memory_id 已生成
    r = skill_indexer.record_hook("dream-record", "VM-ORIGINAL-456", skill_dir=skill_dir)
    assert r["linked"] is True
    assert r["memory_id"] == "VM-ORIGINAL-456"  # 原始 id，未被覆盖

    # 验证写入原始 memory_id
    content = (skill_dir / "SKILL.md").read_text()
    assert "VM-ORIGINAL-456" in content


def test_record_hook_no_cognitive_available_field(tmp_path):
    """record_hook 不再调用认知系统，返回值无 cognitive_available 字段。"""
    import skill_indexer

    skill_dir = tmp_path / "dream-fail"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-fail\ndescription: x\nversion: 1.0.0\nstatus: active\n---\n"
    )

    r = skill_indexer.record_hook("dream-fail", "VM-001", skill_dir=skill_dir)
    assert r["linked"] is True
    assert "cognitive_available" not in r  # 不再调用认知系统


def test_verify_hook_lifecycle_without_duplicate_verify(tmp_path):
    """verify_hook 不重复调用 cle.verify，仅在 shadow+success+条件满足时写回 active。"""
    import skill_indexer

    skill_dir = tmp_path / "dream-verify"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: dream-verify\ndescription: x\nversion: 1.0.0\nstatus: shadow\n"
        "confidence: 0.8\napply_count: 3\ncognitive_links: [VM-001]\n---\n"
    )

    entries = [skill_indexer.SkillEntry(name="dream-verify", status="shadow",
                                         confidence=0.8, apply_count=3,
                                         cognitive_links=["VM-001"])]
    r = skill_indexer.verify_hook("dream-verify", True, entries, skill_dir=skill_dir)
    assert r["success"] is True
    assert r["suggested_transition"] == "shadow→active"
    assert "cognitive_available" not in r  # 不再调用认知系统
    assert "verify_result" not in r

    # 验证 status 写回 active
    content = (skill_dir / "SKILL.md").read_text()
    assert "status: active" in content


def test_verify_hook_suggested_transition_without_cognitive(tmp_path):
    """verify_hook 不依赖认知系统，suggested_transition 仍正确计算。"""
    import skill_indexer

    entries = [skill_indexer.SkillEntry(name="s1", status="shadow",
                                         confidence=0.7, apply_count=2)]
    r = skill_indexer.verify_hook("s1", True, entries, skill_dir=None)
    assert r["suggested_transition"] == "shadow→active"
    assert "cognitive_available" not in r
