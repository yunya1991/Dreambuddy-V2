#!/usr/bin/env python3
"""
Task 10: SkillLoader 测试（设计节 2.2-2.3）
持久化 pytest 用例。
"""

import json
import os
import sys
import shutil
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from cognitive_superpowers import SkillLoader, SuperpowersSkill


def test_all_14_skills_loaded() -> None:
    loader = SkillLoader()
    assert len(loader.skills) == 14, f"Expected 14 skills, got {len(loader.skills)}: {list(loader.skills.keys())}"


def test_supplement_localized_true_all_14() -> None:
    loader = SkillLoader()
    for sid, sk in loader.skills.items():
        assert sk.localized is True, f"Skill {sid} localized={sk.localized}, expected True"
        assert sk.supplement is not None, f"Skill {sid} supplement is None"


def test_format_red_line_bad_separator_raises() -> None:
    loader = SkillLoader()
    bad_content = "***\nname: Bad\n***\n# Body"
    with pytest.raises(ValueError) as exc_info:
        loader._validate_frontmatter_format(bad_content, "fake/path/bad.md")
    assert "SKILL_LOADER_ERROR" in str(exc_info.value)


def test_format_red_line_no_close_separator_raises() -> None:
    loader = SkillLoader()
    bad_content = "---\nname: NoClose\n# No close separator"
    with pytest.raises(ValueError) as exc_info:
        loader._validate_frontmatter_format(bad_content, "fake/path/noclose.md")
    assert "SKILL_LOADER_ERROR" in str(exc_info.value)


def test_supplement_name_field_matches_skill_id() -> None:
    loader = SkillLoader()
    for sid, sk in loader.skills.items():
        assert sk.supplement is not None, f"Skill {sid} missing supplement"
        sup_lower = sk.supplement.lower()
        has_dreambuddy = "dreambuddy" in sup_lower
        has_supplement = "supplement" in sup_lower
        has_combined = "dreambuddy supplement" in sup_lower or "dreambuddy-supplement" in sup_lower
        assert has_combined or (has_dreambuddy and has_supplement), (
            f"Skill {sid} supplement does not contain 'Dreambuddy' + 'Supplement' pair. "
            f"Found 'dreambuddy'={has_dreambuddy}, 'supplement'={has_supplement}. "
            f"Supplement preview: {sk.supplement[:120]!r}"
        )
        sid_norm = sid.lower().replace("-", "").replace("_", "")
        sup_clean = sup_lower.replace("-", "").replace("_", "")
        assert sid_norm in sup_clean, \
            f"Skill {sid} supplement does not contain skill_id (normalized {sid_norm} not in supplement)"


def test_index_cache_rebuild_md5_match() -> None:
    loader = SkillLoader()
    index_path = loader.INDEX_PATH
    backup_path = index_path.with_suffix(".json.bak_test_skill_loader")

    if index_path.exists():
        shutil.copy2(index_path, backup_path)

    try:
        if index_path.exists():
            index_path.unlink()

        loader2 = SkillLoader()
        assert len(loader2.skills) == 14

        assert index_path.exists(), "skills-index.json should have been rebuilt"

        data = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(data) == 14

        some_sid = list(data.keys())[0]
        real_md5 = data[some_sid]["md5_of_base"]

        data[some_sid]["md5_of_base"] = "wrong_md5_value_abcdef1234567890"
        index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        rebuild_called = {"flag": False}
        original_rebuild = SkillLoader._rebuild_index_cache

        def spy_rebuild(self_obj: Any) -> None:
            rebuild_called["flag"] = True
            return original_rebuild(self_obj)

        SkillLoader._rebuild_index_cache = spy_rebuild
        try:
            loader3 = SkillLoader()
            assert len(loader3.skills) == 14
        finally:
            SkillLoader._rebuild_index_cache = original_rebuild

        assert rebuild_called["flag"] is True, "_rebuild_index_cache should have been called when md5 mismatch"

        fresh = json.loads(index_path.read_text(encoding="utf-8"))
        assert fresh[some_sid]["md5_of_base"] == real_md5, "md5 should have been restored after rebuild"

    finally:
        if backup_path.exists():
            shutil.copy2(backup_path, index_path)
            try:
                backup_path.unlink()
            except OSError:
                pass
