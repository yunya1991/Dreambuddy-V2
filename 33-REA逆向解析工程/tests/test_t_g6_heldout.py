"""T-G6 held-out 分桶与季度冻结 — RED 测试

SPEC-33-G §1 G-G6 / §2.11.4 L2-10 / §2.11.9 第 7 条：
  - ≥100 条，按 section 分桶
  - 30% 永久保留，只由人工换入换出
  - 季度冻结；同源生成或曾参与训练/提示的一律作废
  - 不进入任何 Agent 上下文（evaluation_items 只返回非保留池）

RED 契约：core.evolution.heldout 模块不存在。
"""

from __future__ import annotations

import pytest
from core.evolution.heldout import HeldoutError, HeldoutStore, validate_manifest


def _items(total: int = 100, reserved: int = 30) -> list[dict]:
    items = []
    for i in range(total):
        items.append(
            {
                "id": f"H-{i:03d}",
                "section": "modules" if i % 2 == 0 else "dependencies",
                "reserved": i < reserved,
                "source": "human",
                "added_at": "2026-11-11T00:00:00+00:00",
            }
        )
    return items


def test_validate_manifest_accepts_valid_dataset():
    assert len(validate_manifest(_items(), sections={"modules", "dependencies"})) == 100


def test_validate_manifest_requires_100_items():
    with pytest.raises(HeldoutError, match=">=100"):
        validate_manifest(_items(total=99), sections={"modules", "dependencies"})


def test_validate_manifest_requires_30_percent_reserved():
    with pytest.raises(HeldoutError, match="30%"):
        validate_manifest(_items(reserved=20), sections={"modules", "dependencies"})


def test_validate_manifest_rejects_non_human_source():
    items = _items()
    items[0]["source"] = "agent"
    with pytest.raises(HeldoutError, match="human"):
        validate_manifest(items, sections={"modules", "dependencies"})


def test_validate_manifest_rejects_agent_context_leak():
    items = _items()
    items[0]["agent_context"] = True
    with pytest.raises(HeldoutError, match="agent_context"):
        validate_manifest(items, sections={"modules", "dependencies"})


def test_validate_manifest_rejects_unknown_section_bucket():
    items = _items()
    items[0]["section"] = "unknown"
    with pytest.raises(HeldoutError, match="section"):
        validate_manifest(items, sections={"modules", "dependencies"})


def test_freeze_blocks_same_quarter_replacement(tmp_path):
    store = HeldoutStore(tmp_path / "heldout_manifest.json", sections={"modules", "dependencies"})
    store.save(_items(), quarter="2026Q4")
    store.freeze("2026Q4")

    new_item = {
        "id": "H-NEW",
        "section": "modules",
        "reserved": True,
        "source": "human",
        "added_at": "2026-11-11T00:00:00+00:00",
    }
    with pytest.raises(HeldoutError, match="frozen"):
        store.replace("H-000", new_item, operator="alice", quarter="2026Q4")


def test_replace_requires_operator_in_new_quarter(tmp_path):
    store = HeldoutStore(tmp_path / "heldout_manifest.json", sections={"modules", "dependencies"})
    store.save(_items(), quarter="2026Q4")
    store.freeze("2026Q4")

    new_item = {
        "id": "H-NEW",
        "section": "modules",
        "reserved": True,
        "source": "human",
        "added_at": "2027-01-01T00:00:00+00:00",
    }
    with pytest.raises(HeldoutError, match="operator"):
        store.replace("H-000", new_item, operator="", quarter="2027Q1")


def test_evaluation_items_exclude_reserved_pool(tmp_path):
    store = HeldoutStore(tmp_path / "heldout_manifest.json", sections={"modules", "dependencies"})
    store.save(_items(), quarter="2026Q4")

    evaluation = store.evaluation_items()
    assert len(evaluation) == 70
    assert all(not item["reserved"] for item in evaluation)
    assert store.bucket_stats()["modules"]["reserved"] == 15
