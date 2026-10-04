"""SKILL 操纵子（Operon）— SKILL 套件协同加载

借鉴生物学操纵子概念：功能相关的 SKILL 组成一个 operon，
当套件中任一 SKILL 被触发时，自动加载同套件的所有成员。

设计：
- skill_operon.yaml 定义套件（名称 → {description, members, trigger}）
- expand_operon(skill) → 返回该 SKILL 所在套件的所有成员
- get_operon_for_skill(skill) → 返回套件名（或 None）

FAIL-OPEN：YAML 不可读 → 返回空 dict，expand 返回 [skill]
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


def load_operons(yaml_path: Path | str | None = None) -> dict:
    """加载 operon 定义。

    Args:
        yaml_path: skill_operon.yaml 路径（默认同目录）

    Returns:
        dict: {operon_name: {description, members, trigger}}
    """
    if yaml_path is None:
        yaml_path = Path(__file__).resolve().parent / "skill_operon.yaml"
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return {}
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}  # FAIL-OPEN


def get_operon_for_skill(skill_name: str, operons: dict) -> Optional[str]:
    """返回 SKILL 所在的 operon 名，不在任何 operon 中返回 None。"""
    for op_name, op_def in operons.items():
        members = op_def.get("members", []) if isinstance(op_def, dict) else []
        if skill_name in members:
            return op_name
    return None


def expand_operon(skill_name: str, operons: dict) -> list[str]:
    """展开 SKILL 所在 operon 的所有成员。

    若 SKILL 不在任何 operon 中 → 返回 [skill_name]
    """
    op_name = get_operon_for_skill(skill_name, operons)
    if op_name is None:
        return [skill_name]
    op_def = operons[op_name]
    members = op_def.get("members", []) if isinstance(op_def, dict) else []
    return list(members) if members else [skill_name]


def list_operons(operons: dict) -> list[dict]:
    """返回所有 operon 摘要列表。"""
    result = []
    for name, op_def in operons.items():
        if not isinstance(op_def, dict):
            continue
        result.append({
            "name": name,
            "description": op_def.get("description", ""),
            "members": op_def.get("members", []),
            "trigger": op_def.get("trigger", ""),
            "member_count": len(op_def.get("members", [])),
        })
    return result
